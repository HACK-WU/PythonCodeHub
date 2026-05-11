"""读写锁（Read-Write Lock），支持升级 / 降级。

语义：
- **读锁（共享锁）**：多个持有者可同时获取；只要存在读锁，写锁无法加锁
- **写锁（独占锁）**：同一时刻只能一个持有者；持有写锁时任何读锁 / 写锁都被阻塞
- **降级**：持有写锁 → 直接转为读锁（安全，业务连续性好）
- **升级**：持有读锁 → 转为写锁（需先释放读锁，期间可能被其他写者抢先）

存储结构：
    使用单个 Redis Hash，字段约定：
    - `state`:        "R" 表示读模式；"W" 表示写模式；字段不存在表示无锁
    - `writer`:       写锁持有者 token（仅写模式下存在）
    - `reader:<token>`: 读锁持有者，值为该 token 的重入计数（支持同实例多次 acquire_read）
    - `reader_count`: 当前活跃的不同读者数量（去重后），由脚本维护，
                      用于 O(1) 判断是否仍有读者 / 是否唯一读者

    Hash 整体共用一个 PEXPIRE TTL，避免持锁方崩溃导致永久死锁。

原子性：
    所有操作都通过 Lua 脚本完成，保证 "读取状态 → 条件判断 → 修改 → 续期" 不可分割。

示例：
    >>> rw = RWLock("resource", client=client, ttl=30)
    >>> rw.acquire_read()
    >>> try:
    ...     read_data()
    ... finally:
    ...     rw.release_read()

    >>> with rw.write_lock():  # 上下文管理器语义的写锁
    ...     write_data()
"""

from __future__ import annotations

import random
import time
import uuid
from contextlib import contextmanager
from collections.abc import Iterator

from .constants import DEFAULT_TTL
from .protocols import RedisClientProtocol

# ─────────────────────────────────────────────────────────────────
# acquire_read：仅当当前非写模式（或无锁）时可加读锁
#   KEYS[1] = 锁 key
#   ARGV[1] = reader token
#   ARGV[2] = TTL（毫秒）
#
# 逻辑：
#   1. state 不存在 / state == "R" → 允许：递增 reader:<token>，
#      切换 state 为 "R"，续期 TTL，返回 1
#   2. state == "W"                → 拒绝，返回 0
# ─────────────────────────────────────────────────────────────────
_ACQUIRE_READ_LUA = """
local state = redis.call("hget", KEYS[1], "state")
if state == false or state == "R" then
    redis.call("hset", KEYS[1], "state", "R")
    -- 首次为该 token 加读锁时，reader_count + 1；重入不增计数
    if redis.call("hexists", KEYS[1], "reader:" .. ARGV[1]) == 0 then
        redis.call("hincrby", KEYS[1], "reader_count", 1)
    end
    redis.call("hincrby", KEYS[1], "reader:" .. ARGV[1], 1)
    redis.call("pexpire", KEYS[1], ARGV[2])
    return 1
end
return 0
"""

# ─────────────────────────────────────────────────────────────────
# release_read：释放一次读锁（计数 -1）
#   KEYS[1] = 锁 key
#   ARGV[1] = reader token
#   ARGV[2] = TTL（毫秒，用于仍有读者时续期）
#
# 返回：
#    1  — 已释放一次，仍有其他读者（或本 token 仍有重入计数）
#    0  — 最后一个读者释放，Hash 已清空
#   -1  — 本 token 并未持有读锁
# ─────────────────────────────────────────────────────────────────
_RELEASE_READ_LUA = """
local field = "reader:" .. ARGV[1]
local count = redis.call("hget", KEYS[1], field)
if not count then
    return -1
end
count = tonumber(count) - 1
if count > 0 then
    redis.call("hset", KEYS[1], field, count)
    redis.call("pexpire", KEYS[1], ARGV[2])
    return 1
end
-- 本 token 重入计数归零：移除该字段并读者总数 -1
redis.call("hdel", KEYS[1], field)
local remaining = redis.call("hincrby", KEYS[1], "reader_count", -1)
if remaining <= 0 then
    -- 无任何读者：删除整个 Hash
    redis.call("del", KEYS[1])
    return 0
end
redis.call("pexpire", KEYS[1], ARGV[2])
return 1
"""

# ─────────────────────────────────────────────────────────────────
# acquire_write：仅当完全无锁时可加写锁
#   KEYS[1] = 锁 key
#   ARGV[1] = writer token
#   ARGV[2] = TTL（毫秒）
#
# 返回 1 表示加锁成功，0 表示被其他读者/写者占用
# ─────────────────────────────────────────────────────────────────
_ACQUIRE_WRITE_LUA = """
if redis.call("exists", KEYS[1]) == 0 then
    redis.call("hset", KEYS[1], "state", "W", "writer", ARGV[1])
    redis.call("pexpire", KEYS[1], ARGV[2])
    return 1
end
return 0
"""

# ─────────────────────────────────────────────────────────────────
# release_write：释放写锁（仅当 writer == token 时允许）
#   KEYS[1] = 锁 key
#   ARGV[1] = writer token
#
# 返回 1 表示释放成功，0 表示 token 不匹配（锁已被他人持有或已过期）
# ─────────────────────────────────────────────────────────────────
_RELEASE_WRITE_LUA = """
if redis.call("hget", KEYS[1], "writer") == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

# ─────────────────────────────────────────────────────────────────
# downgrade：写锁 → 读锁（原子转换，中间不释放互斥）
#   KEYS[1] = 锁 key
#   ARGV[1] = token（写锁持有者 → 转为读锁持有者）
#   ARGV[2] = TTL（毫秒）
#
# 返回 1 表示降级成功，0 表示 token 不匹配（未持有写锁）
# ─────────────────────────────────────────────────────────────────
_DOWNGRADE_LUA = """
if redis.call("hget", KEYS[1], "writer") ~= ARGV[1] then
    return 0
end
redis.call("del", KEYS[1])
redis.call("hset", KEYS[1], "state", "R")
redis.call("hincrby", KEYS[1], "reader:" .. ARGV[1], 1)
redis.call("hset", KEYS[1], "reader_count", 1)
redis.call("pexpire", KEYS[1], ARGV[2])
return 1
"""

# ─────────────────────────────────────────────────────────────────
# upgrade：读锁 → 写锁（仅当本 token 是唯一读者时可原子升级）
#   KEYS[1] = 锁 key
#   ARGV[1] = token（读锁持有者 → 转为写锁持有者）
#   ARGV[2] = TTL（毫秒）
#
# 返回:
#    1  — 升级成功
#    0  — 仍有其他读者或本 token 未持有读锁，不能升级
# ─────────────────────────────────────────────────────────────────
_UPGRADE_LUA = """
local field = "reader:" .. ARGV[1]
if not redis.call("hexists", KEYS[1], field) then
    return 0
end
-- O(1) 判断：仅当读者总数为 1（即本 token 是唯一读者）时才允许升级
local reader_count = tonumber(redis.call("hget", KEYS[1], "reader_count") or "0")
if reader_count ~= 1 then
    return 0
end
-- 原子切换为写模式
redis.call("del", KEYS[1])
redis.call("hset", KEYS[1], "state", "W", "writer", ARGV[1])
redis.call("pexpire", KEYS[1], ARGV[2])
return 1
"""


class RWLock:
    """基于 Redis Hash + Lua 脚本实现的分布式读写锁。

    支持的操作：
    - acquire_read / release_read           读锁（共享）
    - acquire_write / release_write         写锁（独占）
    - downgrade_to_read                     写锁 → 读锁（原子）
    - try_upgrade_to_write                  读锁 → 写锁（原子，需唯一读者）
    - read_lock() / write_lock()            with 上下文管理器

    并发行为：
    - 同一实例可重入读锁（计数）
    - 不同实例的读锁可共存
    - 写锁完全独占
    - 升级需确保当前只有自己一个读者，否则需等待或放弃
    """

    def __init__(self, name: str, client: RedisClientProtocol, ttl: int | None = None):
        """初始化读写锁。

        参数:
            name:   锁在 Redis 中的 Hash key 名称
            client: 满足 RedisClientProtocol 协议的 Redis 客户端
            ttl:    锁过期时间（秒），默认 60 秒

        异常:
            ValueError: client 为 None 时抛出
        """
        if client is None:
            raise ValueError("RWLock requires a non-None 'client' argument")
        self.name = name
        self.client = client
        self.ttl = ttl or DEFAULT_TTL
        # 实例 token：在首次 acquire_read / acquire_write 时才生成，
        # 避免多轮 acquire/release 周期复用 token 导致与 Redis 端状态错位。
        # 升级 / 降级场景下该 token 会被延续使用。
        self._token: str | None = None
        # 本地读计数（重入用）
        self._read_count: int = 0
        # 本地是否持有写锁
        self._holds_write: bool = False

    def _ensure_token(self) -> str:
        """首次加锁时生成 token；重入 / 升降级复用现有 token。"""
        if self._token is None:
            self._token = uuid.uuid4().hex
        return self._token

    # ─────────────────────────────────────────────────────
    # 读锁
    # ─────────────────────────────────────────────────────
    def acquire_read(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """获取读锁（共享）。

        参数:
            _wait:          最长等待时间（秒），0 表示仅尝试一次
            retry_interval: 重试间隔（秒），加入抖动缓解惊群

        返回值:
            True  — 获取成功
            False — 被写锁阻塞且超时
        """
        # 首次加锁时才生成 token，避免多轮周期复用造成本地 / Redis 状态不一致
        if self._read_count == 0 and not self._holds_write:
            self._token = uuid.uuid4().hex
        token = self._token
        ttl_ms = self.ttl * 1000
        deadline = time.monotonic() + _wait
        while True:
            result = self.client.eval(_ACQUIRE_READ_LUA, 1, self.name, token, ttl_ms)
            if int(result) == 1:
                self._read_count += 1
                return True
            if time.monotonic() >= deadline:
                # 首次加锁就失败：Redis 端没有任何 token 记录，本地 token 也应释放以便下次重新生成
                if self._read_count == 0 and not self._holds_write:
                    self._token = None
                return False
            time.sleep(retry_interval * (0.5 + random.random()))

    def release_read(self) -> int:
        """释放一次读锁（计数 -1）。

        返回值（透传 Lua 脚本）:
             1 — 释放一次，仍有其他读者
             0 — 最后一个读者，Hash 已删除
            -1 — 本实例并未持有读锁

        异常:
            RuntimeError: 本地读计数已为 0 仍调用
        """
        if self._read_count <= 0:
            raise RuntimeError(f"release_read called without holding read lock: {self.name}")
        if self._token is None:
            raise RuntimeError(f"release_read called without active token: {self.name}")
        ttl_ms = self.ttl * 1000
        result = int(self.client.eval(_RELEASE_READ_LUA, 1, self.name, self._token, ttl_ms))
        if result == -1:
            # Redis 端已不存在（TTL 过期 或 被外部清理）：
            # 强制清零本地计数与 token，避免后续调用被默默忽略
            self._read_count = 0
            if not self._holds_write:
                self._token = None
        elif result == 0:
            # Hash 已被 Lua 整体删除（本实例是最后一个读者）：
            # 无论之前重入几次，本地计数都应一次性清零
            self._read_count = 0
            if not self._holds_write:
                self._token = None
        else:
            self._read_count -= 1
            if self._read_count == 0 and not self._holds_write:
                self._token = None
        return result

    # ─────────────────────────────────────────────────────
    # 写锁
    # ─────────────────────────────────────────────────────
    def acquire_write(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """获取写锁（独占）。

        参数:
            _wait:          最长等待时间（秒），0 表示仅尝试一次
            retry_interval: 重试间隔（秒），加入抖动缓解惊群

        返回值:
            True  — 获取成功
            False — 被任何读 / 写锁阻塞且超时
        """
        # 首次加锁时才生成 token，避免多轮周期复用导致状态错位
        if self._read_count == 0 and not self._holds_write:
            self._token = uuid.uuid4().hex
        token = self._token
        ttl_ms = self.ttl * 1000
        deadline = time.monotonic() + _wait
        while True:
            result = self.client.eval(_ACQUIRE_WRITE_LUA, 1, self.name, token, ttl_ms)
            if int(result) == 1:
                self._holds_write = True
                return True
            if time.monotonic() >= deadline:
                if self._read_count == 0 and not self._holds_write:
                    self._token = None
                return False
            time.sleep(retry_interval * (0.5 + random.random()))

    def release_write(self) -> int:
        """释放写锁。

        返回值:
            1 — 释放成功
            0 — token 不匹配（锁已被他人持有或已过期）

        异常:
            RuntimeError: 本地未持写锁仍调用
        """
        if not self._holds_write:
            raise RuntimeError(f"release_write called without holding write lock: {self.name}")
        if self._token is None:
            raise RuntimeError(f"release_write called without active token: {self.name}")
        result = int(self.client.eval(_RELEASE_WRITE_LUA, 1, self.name, self._token))
        self._holds_write = False
        # 写锁释放后若本地不再持有任何锁，清理 token以便下次重新生成
        if self._read_count == 0:
            self._token = None
        return result

    # ─────────────────────────────────────────────────────
    # 升级 / 降级
    # ─────────────────────────────────────────────────────
    def downgrade_to_read(self) -> bool:
        """写锁 → 读锁（原子降级）。

        业务场景：数据写入后仍需对外提供读一致性，先写后读时不释放互斥。

        返回值:
            True  — 降级成功，调用方持有读锁，计数 +1
            False — 本实例未持有写锁（或已被他人抢占）

        异常:
            RuntimeError: 本地未持写锁
        """
        if not self._holds_write:
            raise RuntimeError(f"downgrade_to_read called without holding write lock: {self.name}")
        if self._token is None:
            raise RuntimeError(f"downgrade_to_read called without active token: {self.name}")
        ttl_ms = self.ttl * 1000
        result = int(self.client.eval(_DOWNGRADE_LUA, 1, self.name, self._token, ttl_ms))
        if result == 1:
            self._holds_write = False
            self._read_count += 1
            return True
        # 降级失败（不应发生；除非 Redis 端状态被篡改 / TTL 过期）：
        # 本地视为已失去锁，清理 token 与状态，避免后续操作错位
        self._holds_write = False
        self._token = None
        return False

    def try_upgrade_to_write(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """读锁 → 写锁（原子升级）。

        **仅当本 token 是当前唯一的读者**时才会成功。
        如果还有其他读者：
        - _wait > 0: 在该时间窗口内轮询重试，等其他读者释放
        - _wait = 0: 立即返回 False，调用方可选择“resease_read + acquire_write”（会有无锁窗口期）

        参数:
            _wait:          最长等待时间（秒）
            retry_interval: 重试间隔（秒），加入抖动缓解惊群

        返回值:
            True  — 升级成功，本实例持有写锁；本地读计数清零
            False — 仍有其他读者且超时；本地状态不变

        异常:
            RuntimeError: 本地未持读锁
        """
        if self._read_count <= 0:
            raise RuntimeError(f"try_upgrade_to_write called without holding read lock: {self.name}")
        if self._token is None:
            raise RuntimeError(f"try_upgrade_to_write called without active token: {self.name}")
        ttl_ms = self.ttl * 1000
        deadline = time.monotonic() + _wait
        while True:
            result = int(self.client.eval(_UPGRADE_LUA, 1, self.name, self._token, ttl_ms))
            if result == 1:
                # 升级成功：清零本地读计数（对应 Lua 中的 HDEL），设置写持有标记
                self._read_count = 0
                self._holds_write = True
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(retry_interval * (0.5 + random.random()))

    # ─────────────────────────────────────────────────────
    # 上下文管理器（with 语法糖）
    # ─────────────────────────────────────────────────────
    @contextmanager
    def read_lock(self, _wait: float = 0) -> Iterator[RWLock]:
        """`with rw.read_lock():` 自动获取/释放读锁。"""
        if not self.acquire_read(_wait=_wait):
            raise TimeoutError(f"Failed to acquire read lock: {self.name}")
        try:
            yield self
        finally:
            self.release_read()

    @contextmanager
    def write_lock(self, _wait: float = 0) -> Iterator[RWLock]:
        """`with rw.write_lock():` 自动获取/释放写锁。"""
        if not self.acquire_write(_wait=_wait):
            raise TimeoutError(f"Failed to acquire write lock: {self.name}")
        try:
            yield self
        finally:
            self.release_write()

    # ─────────────────────────────────────────────────────
    # 状态查询（本地视角，不发起网络请求）
    # ─────────────────────────────────────────────────────
    @property
    def read_count(self) -> int:
        """本实例当前持有的读锁重入计数。"""
        return self._read_count

    @property
    def holds_write(self) -> bool:
        """本实例是否持有写锁。"""
        return self._holds_write

    def is_locked(self) -> bool:
        """本实例是否持有任何锁（读或写）。"""
        return self._read_count > 0 or self._holds_write
