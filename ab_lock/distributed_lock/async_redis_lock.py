"""基于 asyncio 的异步分布式锁。

适用于使用 redis.asyncio / aioredis 的异步项目。所有方法均为协程，
配合 async with 语法使用。

设计要点：
1. 复用 RedisLock 的 SET NX + token 校验 + Lua 释放算法
2. 接受任意符合 AsyncRedisClientProtocol 协议的异步客户端
3. 实现 __aenter__ / __aexit__，支持 async with 自动加锁/释放
4. 用 asyncio.sleep 替代 time.sleep，避免阻塞事件循环
5. 用 time.monotonic() 计时，避免 asyncio.get_event_loop() 在 Python 3.12+ 的弃用风险
6. 重试间隔加入随机抖动，缓解多协程惊群效应
"""

import asyncio
import logging
import random
import time
import uuid
from collections.abc import Callable

from .constants import DEFAULT_TTL
from .lua_scripts import RELEASE_LUA
from .protocols import AsyncRedisClientProtocol
from .watchdog import AsyncWatchdog

logger = logging.getLogger(__name__)


class AsyncRedisLock:
    """基于 Redis SET NX 的异步分布式互斥锁。

    特性：
    - 完全异步：所有 IO 通过 await 执行，不阻塞事件循环
    - 通过依赖注入接受任意符合 AsyncRedisClientProtocol 的客户端
    - 使用唯一 token（UUID）标识锁持有者，防止误释放
    - 支持等待重试（_wait 参数）与可配置重试间隔（含抖动）
    - 释放锁通过 Lua 脚本保证原子性

    示例::

        import redis.asyncio as aioredis
        from ab_lock.distributed_lock import AsyncRedisLock

        client = aioredis.Redis(host="127.0.0.1")
        async with AsyncRedisLock("res", client=client, ttl=30) as lock:
            await do_async_work()
    """

    def __init__(
        self,
        name: str,
        client: AsyncRedisClientProtocol,
        ttl: int | None = None,
        enable_watchdog: bool = False,
        watchdog_interval: float | None = None,
        on_lock_lost: Callable[[str], None] | None = None,
    ):
        """初始化异步 Redis 单键锁。

        参数:
            name:              锁的 Redis key 名称
            client:            满足 AsyncRedisClientProtocol 协议的异步 Redis 客户端（必填）
            ttl:               锁过期时间（秒），默认 60 秒
            enable_watchdog:   是否启用看门狗自动续期，默认 False
            watchdog_interval: 续期间隔（秒），默认 ttl/3
            on_lock_lost:      锁丢失回调（续期失败时触发），仅在 enable_watchdog=True 时生效

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        if client is None:
            raise ValueError("AsyncRedisLock requires a non-None 'client' argument")
        self.name = name
        self.client = client
        self.ttl = ttl or DEFAULT_TTL
        # 当前实例持有的锁令牌；None 表示未持锁
        self._token: str | None = None
        # 看门狗相关配置
        self._enable_watchdog = enable_watchdog
        self._watchdog_interval = watchdog_interval
        self._on_lock_lost = on_lock_lost
        self._watchdog: AsyncWatchdog | None = None

    async def acquire(self, _wait: float = 0, retry_interval: float = 0.01) -> bool:
        """异步尝试获取锁。

        参数:
            _wait:          最长等待时间（秒），默认 0 表示非阻塞，仅尝试一次；
                            > 0 时在该时间窗口内按 retry_interval 轮询重试
            retry_interval: 重试间隔（秒），默认 0.01 秒；实际等待会加入
                            0.5x ~ 1.5x 的随机抖动以缓解惊群

        返回值:
            True  — 成功获取锁
            False — 在等待时间内未能获取锁
        """
        token = uuid.uuid4().hex
        deadline = time.monotonic() + _wait
        while True:
            if await self.client.set(self.name, token, ex=self.ttl, nx=True):
                self._token = token
                # 加锁成功后按需启动看门狗
                if self._enable_watchdog:
                    try:
                        self._watchdog = AsyncWatchdog(
                            client=self.client,
                            key=self.name,
                            token=token,
                            ttl=self.ttl,
                            interval=self._watchdog_interval,
                            on_lost=self._on_lock_lost,
                        )
                        await self._watchdog.start()
                    except Exception:
                        # 看门狗启动失败：主动回滚已加的锁，避免泄漏到 TTL 过期
                        self._watchdog = None
                        try:
                            await self.client.eval(RELEASE_LUA, 1, self.name, token)
                        finally:
                            self._token = None
                        raise
                return True
            # 非阻塞或已超时：直接返回失败
            if time.monotonic() >= deadline:
                return False
            # 加入抖动避免多协程同时唤醒造成惊群
            await asyncio.sleep(retry_interval * (0.5 + random.random()))

    async def release(self) -> int:
        """异步释放锁（原子操作）。

        通过 Lua 脚本在 Redis 端原子执行"校验 token → 删除 key"，
        避免 GET + DELETE 之间的竞态条件。

        若启用了看门狗，会先停止 Task 再删除 key。

        返回值:
            1 — 成功删除锁 key
            0 — 本实例未持锁，或 token 不匹配（锁已被他人持有或已过期）

        说明：
            无论 Redis 端释放是否成功（返回 1 或 0），本地 token 都会被清空，
            因此 release 不是幂等的——重复调用会得到 0。
        """
        if not self._token:
            return 0
        # 先停止看门狗
        if self._watchdog is not None:
            await self._watchdog.stop()
            self._watchdog = None
        try:
            result = await self.client.eval(RELEASE_LUA, 1, self.name, self._token)
            return int(result)
        finally:
            self._token = None

    def is_locked(self) -> bool:
        """查询本实例是否持有锁（仅看本地 token，不发起网络请求）。

        注意：Redis 端可能因 TTL 过期已释放，强一致需直接查询 Redis。
        """
        return self._token is not None

    async def __aenter__(self):
        """进入 async with 代码块时自动获取锁。

        异常:
            TimeoutError: 加锁失败时抛出，避免在未持锁的情况下执行临界区
        """
        if not await self.acquire():
            raise TimeoutError(f"Failed to acquire lock: {self.name}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出 async with 代码块时自动释放锁。

        异常处理策略：
        - 临界区无异常（exc_type is None）时，release 异常正常向上抛出
        - 临界区已有异常时，release 失败仅记录日志，不覆盖原始异常
        """
        try:
            await self.release()
        except Exception:
            if exc_type is None:
                raise
            # 原始异常优先：仅记录 release 失败，避免掩盖真正的业务异常
            logger.warning(
                "release() failed during __aexit__ for lock %s; preserving original exception",
                self.name,
                exc_info=True,
            )
