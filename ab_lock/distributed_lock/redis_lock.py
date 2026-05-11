"""基于 Redis SET NX 的单键分布式互斥锁。"""

import random
import time
import uuid

from .base import BaseLock
from .lua_scripts import RELEASE_LUA
from .protocols import RedisClientProtocol


class RedisLock(BaseLock):
    """基于 Redis SET NX 指令实现的单键分布式互斥锁。

    特性：
    - 通过依赖注入接受任意符合 RedisClientProtocol 的客户端
    - 使用唯一 token（UUID）标识锁持有者，防止误释放他人持有的锁
    - 支持等待重试（timeout 参数）与可配置重试间隔（retry_interval）
    - 锁过期时间由 ttl 控制，避免持锁方崩溃导致死锁
    - 释放锁通过 Lua 脚本保证原子性，杜绝误删他人锁的竞态条件
    """

    def __init__(self, name: str, client: RedisClientProtocol, ttl: int | None = None):
        """初始化 Redis 单键锁。

        参数:
            name:   锁的 Redis key 名称
            client: 满足 RedisClientProtocol 协议的 Redis 客户端实例（必填）
            ttl:    锁过期时间（秒），默认 60 秒

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        super().__init__(name, ttl)
        if client is None:
            raise ValueError("RedisLock requires a non-None 'client' argument")
        self.client = client
        # 当前实例持有的锁令牌；None 表示未持锁
        self._token: str | None = None

    def acquire(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """尝试获取 Redis 分布式锁。

        参数:
            _wait:          最长等待时间（秒），默认 0 表示非阻塞，仅尝试一次；
                            > 0 时在该时间窗口内按 retry_interval 轮询重试
            retry_interval: 重试间隔（秒），默认 0.01 秒；实际等待会加入
                            0.5x ~ 1.5x 的随机抖动以缓解多进程惊群

        返回值:
            True  — 成功获取锁
            False — 在等待时间内未能获取锁

        执行步骤：
        1. 生成唯一 token，用于标识当前锁持有者
        2. 计算等待截止时间（使用 monotonic，免受系统时钟回拨影响）
        3. 循环调用 SET NX 尝试加锁：
           - 成功则保存 token 并返回 True
           - 失败且已超时则返回 False
           - 失败且未超时则 sleep 带抖动的 retry_interval 后重试
        """
        token = uuid.uuid4().hex
        deadline = time.monotonic() + _wait
        while True:
            if self.client.set(self.name, token, ex=self.ttl, nx=True):
                self._token = token
                return True
            # 非阻塞或已超时：直接返回失败
            if time.monotonic() >= deadline:
                return False
            # 加入抖动避免多进程同时唤醒造成惊群
            time.sleep(retry_interval * (0.5 + random.random()))

    def release(self):
        """释放 Redis 分布式锁（原子操作）。

        通过 Lua 脚本在 Redis 端原子执行 "校验 token → 删除 key"，
        避免先 GET 再 DELETE 导致的竞态条件（锁 TTL 过期后被他人获取，
        本实例误删他人锁）。

        返回值:
            1 — 成功删除锁 key
            0 — 本实例未持锁，或 token 不匹配（锁已被他人持有或已过期）
        """
        if not self._token:
            return 0
        try:
            return int(self.client.eval(RELEASE_LUA, 1, self.name, self._token))
        finally:
            self._token = None

    def is_locked(self) -> bool:
        """查询本实例是否持有锁（仅看本地 token，不发起网络请求）。

        注意：Redis 端可能因 TTL 过期已释放，强一致需直接查询 Redis。
        """
        return self._token is not None
