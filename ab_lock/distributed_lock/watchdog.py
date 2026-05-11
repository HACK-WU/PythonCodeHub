"""看门狗（Watchdog）自动续期机制。

场景：
    当锁的 TTL 小于实际业务执行时间时，锁会在业务完成前过期被他人抢占，
    导致并发问题。看门狗通过后台线程/协程定时续期 TTL，确保只要持锁方
    还在正常运行，锁就不会因 TTL 过期而被释放。

设计要点：
1. 续期通过 Lua 脚本（RENEW_LUA）保证"token 校验 + PEXPIRE"的原子性，
   避免误续期他人持有的锁。
2. 续期间隔默认为 TTL 的 1/3（Redisson 的经典策略），在可用性与网络开销
   之间取得平衡。
3. 续期失败（token 已不在）会自动停止看门狗并记录日志，业务方可通过
   监听器感知。
4. 提供 `SyncWatchdog`（基于 threading）与 `AsyncWatchdog`（基于 asyncio.Task）
   两种实现，分别服务于 RedisLock / AsyncRedisLock。

集成方式（在 RedisLock / AsyncRedisLock 中已加入 `enable_watchdog` 参数）：
    with RedisLock("res", client, ttl=30, enable_watchdog=True):
        long_running_business()   # 业务执行超过 30 秒也不会丢锁

    async with AsyncRedisLock("res", client, ttl=30, enable_watchdog=True):
        await long_running_async_business()
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

from .lua_scripts import RENEW_LUA
from .protocols import AsyncRedisClientProtocol, RedisClientProtocol

logger = logging.getLogger(__name__)


class SyncWatchdog:
    """同步看门狗：后台线程定时续期 Redis 锁。

    使用方式：
        >>> dog = SyncWatchdog(client, key, token, ttl=30)
        >>> dog.start()
        >>> try:
        ...     do_long_running_work()
        ... finally:
        ...     dog.stop()

    线程安全说明：
    - start / stop 可重复调用，内部通过 threading.Event 幂等控制
    - 守护线程（daemon=True），主进程退出时不会阻塞
    """

    def __init__(
        self,
        client: RedisClientProtocol,
        key: str,
        token: str,
        ttl: int,
        interval: float | None = None,
        on_lost: Callable[[str], None] | None = None,
    ):
        """初始化同步看门狗。

        参数:
            client:   Redis 客户端（需支持 eval）
            key:      锁的 Redis key
            token:    当前持锁实例的 token，用于续期时原子校验
            ttl:      锁 TTL（秒），每次续期会刷新到该值
            interval: 续期间隔（秒），默认为 ttl/3；必须小于 ttl
            on_lost:  锁丢失回调：当续期发现 token 已不匹配时触发，
                      参数为锁 key；常用于业务侧感知异常并中断任务
        """
        self.client = client
        self.key = key
        self.token = token
        self.ttl = ttl
        # 经典策略：续期间隔 = TTL/3，保证即使一次续期失败仍有后续机会
        self.interval = interval if interval is not None else max(ttl / 3, 0.1)
        if self.interval >= ttl:
            raise ValueError(f"watchdog interval ({self.interval}s) must be < ttl ({ttl}s)")
        self._on_lost = on_lost
        # Event 用于优雅停止：wait(timeout) 可被 set() 立即唤醒
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        """启动看门狗后台线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"watchdog-{self.key}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout: float = 1.0):
        """停止看门狗（幂等）。

        参数:
            join_timeout: 等待线程结束的最长时间（秒）
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)
            self._thread = None

    def _run(self):
        """后台线程主循环：周期性续期，直到被 stop 或 token 失效。"""
        ttl_ms = self.ttl * 1000
        while not self._stop_event.wait(self.interval):
            try:
                result = self.client.eval(RENEW_LUA, 1, self.key, self.token, ttl_ms)
                if int(result) != 1:
                    # token 不匹配：锁已被他人持有或已过期
                    logger.warning("watchdog: lock %s lost (token mismatch or expired), stopping", self.key)
                    if self._on_lost is not None:
                        try:
                            self._on_lost(self.key)
                        except Exception:
                            logger.exception("watchdog on_lost callback raised for %s", self.key)
                    return
            except Exception:
                # 网络抖动等瞬时异常：记录后继续下一轮，不直接退出
                logger.exception("watchdog: renew failed for %s, will retry", self.key)
            # 续期 RPC 可能阻塞较久；完成后立即检查 stop，使 release 路径响应更快
            if self._stop_event.is_set():
                return


class AsyncWatchdog:
    """异步看门狗：asyncio.Task 定时续期异步锁。

    使用方式：
        >>> dog = AsyncWatchdog(client, key, token, ttl=30)
        >>> await dog.start()
        >>> try:
        ...     await long_running_async_work()
        ... finally:
        ...     await dog.stop()
    """

    def __init__(
        self,
        client: AsyncRedisClientProtocol,
        key: str,
        token: str,
        ttl: int,
        interval: float | None = None,
        on_lost: Callable[[str], None] | None = None,
    ):
        """初始化异步看门狗（参数同 SyncWatchdog）。"""
        self.client = client
        self.key = key
        self.token = token
        self.ttl = ttl
        self.interval = interval if interval is not None else max(ttl / 3, 0.1)
        if self.interval >= ttl:
            raise ValueError(f"watchdog interval ({self.interval}s) must be < ttl ({ttl}s)")
        self._on_lost = on_lost
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self):
        """启动看门狗 Task（幂等）。"""
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        try:
            self._task = asyncio.create_task(self._run(), name=f"watchdog-{self.key}")
        except Exception:
            # create_task 失败（例如事件循环已关闭）：清理 _stop_event 防止脏状态
            self._stop_event = None
            raise

    async def stop(self):
        """停止看门狗（幂等）。

        优雅停止策略：
        1. 先 set stop_event，让 _run 在下一个等待点正常退出
        2. 若 Task 仍未结束（例如续期 RPC 长时间阻塞），cancel 兜底
        3. await Task 回收资源，吞掉 CancelledError
        """
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                # _run 内部已记录细节；stop 不应再向调用方抛出
                logger.debug("async watchdog task ended with exception", exc_info=True)
            self._task = None
            self._stop_event = None

    async def _run(self):
        """Task 主循环：asyncio.wait_for 带超时等待 stop_event，超时则续期一次。"""
        assert self._stop_event is not None
        ttl_ms = self.ttl * 1000
        while True:
            try:
                # 等待 stop_event 或间隔超时，任一先到
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                # stop_event 被 set，退出循环
                return
            except TimeoutError:
                # 超时 = 该续期了
                pass
            try:
                result = await self.client.eval(RENEW_LUA, 1, self.key, self.token, ttl_ms)
                if int(result) != 1:
                    logger.warning(
                        "async watchdog: lock %s lost (token mismatch or expired), stopping",
                        self.key,
                    )
                    if self._on_lost is not None:
                        try:
                            self._on_lost(self.key)
                        except Exception:
                            logger.exception("async watchdog on_lost callback raised for %s", self.key)
                    return
            except Exception:
                logger.exception("async watchdog: renew failed for %s, will retry", self.key)
