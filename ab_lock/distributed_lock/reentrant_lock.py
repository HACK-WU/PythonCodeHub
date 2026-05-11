"""基于 Redis Hash + Lua 脚本的可重入分布式锁。

可重入语义：同一个锁实例（共享同一个 token）可多次 acquire，
内部维护重入计数器。release 时计数器递减，归零时才真正删除 key。

实现要点：
1. 用 Redis Hash 存储 {token: count}，借助 HSET / HGET / HINCRBY
2. 用 Lua 脚本将 "检查 token → 计数+1 / 删除 → 续期 TTL" 合并为原子操作
3. 不同实例（不同 token）之间仍然互斥，与普通分布式锁语义一致
"""

import random
import time
import uuid

from .base import BaseLock
from .protocols import RedisClientProtocol

# ─────────────────────────────────────────────────────────────────
# 加锁脚本：
#   KEYS[1] = 锁 key
#   ARGV[1] = 当前实例 token
#   ARGV[2] = TTL（秒）
#
# 逻辑：
#   1. 若 key 不存在 → HSET 写入 {token: 1}，PEXPIRE 设置 TTL，返回 1（新加锁）
#   2. 若 key 存在且 token 相同 → HINCRBY 计数 +1，PEXPIRE 续期，返回 1（重入成功）
#   3. 若 key 存在且 token 不同 → 返回 0（被他人持有，加锁失败）
# ─────────────────────────────────────────────────────────────────
_ACQUIRE_LUA = """
if redis.call("exists", KEYS[1]) == 0 then
    redis.call("hset", KEYS[1], ARGV[1], 1)
    redis.call("pexpire", KEYS[1], ARGV[2])
    return 1
end
if redis.call("hexists", KEYS[1], ARGV[1]) == 1 then
    redis.call("hincrby", KEYS[1], ARGV[1], 1)
    redis.call("pexpire", KEYS[1], ARGV[2])
    return 1
end
return 0
"""

# ─────────────────────────────────────────────────────────────────
# 释放脚本：
#   KEYS[1] = 锁 key
#   ARGV[1] = 当前实例 token
#   ARGV[2] = TTL（毫秒），用于 remaining > 0 时续期
#
# 逻辑：
#   1. 若不持有该锁 → 返回 -1（异常释放，可能 TTL 已过期）
#   2. 计数 -1，若仍 > 0 → 续期 TTL 并返回剩余计数
#   3. 计数 == 0 → DEL 删除 key，返回 0（彻底释放）
# ─────────────────────────────────────────────────────────────────
_RELEASE_LUA = """
if redis.call("hexists", KEYS[1], ARGV[1]) == 0 then
    return -1
end
local remaining = redis.call("hincrby", KEYS[1], ARGV[1], -1)
if remaining > 0 then
    redis.call("pexpire", KEYS[1], ARGV[2])
    return remaining
end
redis.call("del", KEYS[1])
return 0
"""


class ReentrantRedisLock(BaseLock):
    """基于 Redis Hash + Lua 脚本实现的可重入分布式锁。

    特性：
    - 同一实例（同一 token）可多次 acquire，内部维护重入计数
    - 不同实例之间仍然互斥
    - 加锁 / 释放 / 续期均通过 Lua 脚本保证原子性
    - 每次 acquire 都会续期 TTL，避免长时间业务被锁过期打断
    - 支持等待重试（_wait 参数）

    注意事项：
    - 必须配对调用 acquire / release（推荐用 with 语句）
    - 释放次数必须等于加锁次数，否则锁会"残留"直到 TTL 过期

    示例：
        >>> with ReentrantRedisLock("res", client=client) as lock:
        ...     # 已加锁，count=1
        ...     with lock:
        ...         # 重入，count=2
        ...         do_something()
        ...     # count=1，未真正释放
        ... # count=0，锁被删除
    """

    def __init__(self, name: str, client: RedisClientProtocol, ttl: int | None = None):
        """初始化可重入锁。

        参数:
            name:   锁的 Redis key 名称
            client: 满足 RedisClientProtocol 协议的 Redis 客户端实例（必填）
            ttl:    锁过期时间（秒），默认 60 秒；每次重入会续期到该值

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        super().__init__(name, ttl)
        if client is None:
            raise ValueError("ReentrantRedisLock requires a non-None 'client' argument")
        self.client = client
        # 实例 token：所有重入共享同一个 token，用于在 Redis 端识别"是同一持有者"
        self._token: str = uuid.uuid4().hex
        # 本地重入计数：与 Redis 端 Hash 中的计数同步，便于快速 is_locked 判断
        self._local_count: int = 0

    def acquire(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """尝试获取锁，支持重入。

        参数:
            _wait:          最长等待时间（秒），默认 0 表示非阻塞，仅尝试一次；
                            > 0 时在该时间窗口内按 retry_interval 轮询重试
            retry_interval: 重试间隔（秒），默认 0.01 秒

        返回值:
            True  — 成功获取锁（首次加锁或重入）
            False — 在等待时间内未能获取锁（被他人持有）

        说明：
            TTL 以毫秒传入 PEXPIRE，便于精确控制；脚本会在每次 acquire
            时刷新 TTL，避免长时间持锁被过期打断。
        """
        ttl_ms = self.ttl * 1000
        deadline = time.monotonic() + _wait
        while True:
            result = self.client.eval(_ACQUIRE_LUA, 1, self.name, self._token, ttl_ms)
            if int(result) == 1:
                self._local_count += 1
                return True
            # 非阻塞或已超时：直接返回失败
            if time.monotonic() >= deadline:
                return False
            # 加入抖动避免多进程同时唤醒造成惊群
            time.sleep(retry_interval * (0.5 + random.random()))

    def release(self) -> int:
        """释放锁（计数 -1）。

        返回值:
            >0   — 仍处于重入状态，返回剩余持有计数
            0    — 计数归零，锁已被彻底删除
            -1   — 本实例未持有该锁（异常释放，不会修改 Redis 状态）

        异常:
            RuntimeError: 本地未持锁时抛出，避免误用
        """
        if self._local_count <= 0:
            raise RuntimeError(f"release() called on a lock not held by this instance: {self.name}")
        ttl_ms = self.ttl * 1000
        result = int(self.client.eval(_RELEASE_LUA, 1, self.name, self._token, ttl_ms))
        if result == -1:
            # Redis 端已不存在（TTL 过期或被外部清理），
            # 强制清零本地计数，避免本地状态永久泄漏
            self._local_count = 0
        else:
            # 本地计数与 Redis 同步递减
            self._local_count -= 1
        return result

    def is_locked(self) -> bool:
        """查询本实例当前是否持有锁（仅看本地计数，不发起网络请求）。"""
        return self._local_count > 0

    @property
    def lock_count(self) -> int:
        """当前本地重入计数。"""
        return self._local_count
