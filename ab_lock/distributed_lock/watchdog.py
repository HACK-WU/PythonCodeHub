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
3. 续期失败（token 已不在）会自动停止看门狗并触发 on_lost 回调。
4. 续期 RPC 连续失败超过阈值（默认 3 次）也会视为锁丢失，避免长时间
   网络故障掩盖真实的锁状态。
5. 主动调用 stop() 后，即使 RPC 仍在飞行中收到失败响应，也不会误触发
   on_lost 回调。
6. 提供 `SyncWatchdog`（基于 threading）与 `AsyncWatchdog`（基于 asyncio.Task）
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

# 续期 RPC 连续失败的默认上限：超过则视为锁丢失，触发 on_lost
DEFAULT_MAX_RENEW_FAILURES = 3


def _parse_renew_result(result) -> bool:
    """解析 RENEW_LUA 的返回值，返回是否续期成功。

    参数:
        result: Redis Lua 脚本返回值，正常情况下为 1 或 0；
                不同客户端可能返回 int / bytes / str / None

    返回值:
        True  — 续期成功（token 匹配且已 PEXPIRE）
        False — 续期失败（token 不匹配 / 锁已过期 / 返回值异常）

    该函数容忍各种边界返回，避免 int(None) 等异常被外层吞掉，
    导致锁实际丢失但被误判为"瞬时失败可重试"。
    """
    if result is None:
        return False
    try:
        return int(result) == 1
    except (TypeError, ValueError):
        return False


def _validate_ttl_and_interval(ttl: int, interval: float | None) -> float:
    """校验 ttl/interval 并返回最终使用的 interval。

    参数:
        ttl:      锁 TTL（秒），必须为正数
        interval: 用户指定的续期间隔（秒），None 表示使用默认 ttl/3

    返回值:
        最终生效的 interval（秒）

    异常:
        ValueError: ttl 非正、interval 非正、interval >= ttl 时抛出

    校验规则覆盖三种边界：
    1. ttl 必须 > 0（None / 0 / 负数会让 PEXPIRE 直接失败或导致死循环）
    2. interval 显式传入时必须 > 0（避免 wait(0) 高频空转打爆 CPU/Redis）
    3. interval 必须 < ttl（否则锁在续期前就已过期，看门狗形同虚设）
    """
    if not isinstance(ttl, int) or ttl <= 0:
        raise ValueError(f"watchdog ttl must be a positive int, got {ttl!r}")
    if interval is not None and interval <= 0:
        raise ValueError(f"watchdog interval must be > 0, got {interval}")
    final_interval = interval if interval is not None else max(ttl / 3, 0.1)
    if final_interval >= ttl:
        raise ValueError(f"watchdog interval ({final_interval}s) must be < ttl ({ttl}s)")
    return final_interval


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
    - on_lost 回调在后台线程中执行，调用方需自行保证回调线程安全
    """

    def __init__(
        self,
        client: RedisClientProtocol,
        key: str,
        token: str,
        ttl: int,
        interval: float | None = None,
        on_lost: Callable[[str], None] | None = None,
        max_renew_failures: int = DEFAULT_MAX_RENEW_FAILURES,
    ):
        """初始化同步看门狗。

        参数:
            client:             Redis 客户端（需支持 eval）
            key:                锁的 Redis key
            token:              当前持锁实例的 token，用于续期时原子校验
            ttl:                锁 TTL（秒），每次续期会刷新到该值；必须为正整数
            interval:           续期间隔（秒），默认为 ttl/3；必须 > 0 且 < ttl
            on_lost:            锁丢失回调：当续期发现 token 不匹配，
                                或连续 max_renew_failures 次 RPC 异常时触发；
                                参数为锁 key。注意回调在后台线程执行，
                                需自行保证线程安全且避免长时间阻塞
            max_renew_failures: 续期 RPC 连续失败的容忍次数，超过则视为锁丢失；
                                默认 3，必须 >= 1
        """
        if max_renew_failures < 1:
            raise ValueError(f"max_renew_failures must be >= 1, got {max_renew_failures}")
        self.client = client
        self.key = key
        self.token = token
        self.ttl = ttl
        # 校验并计算最终 interval（覆盖 None/0/负数/>=ttl 等边界）
        self.interval = _validate_ttl_and_interval(ttl, interval)
        # 提前算好 ms，避免每次循环重算
        self._ttl_ms = ttl * 1000
        self._on_lost = on_lost
        self._max_renew_failures = max_renew_failures
        # 线程与停止信号；每次 start() 会新建独立 Event，避免新旧线程串扰
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        # _state_lock 仅保护 _thread / _stop_event 的并发访问
        self._state_lock = threading.Lock()

    def start(self):
        """启动看门狗后台线程（幂等）。

        若已有存活线程则直接返回；否则新建独立 stop_event 并启动 daemon 线程。
        新建独立 Event 可防止上一轮 stop() 超时未结束的旧线程，被本轮
        clear() 操作"复活"再次进入续期循环。
        """
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            # 关键：每次都使用全新 Event，与上一轮线程彻底隔离
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._thread = threading.Thread(
                target=self._run,
                args=(stop_event,),
                name=f"watchdog-{self.key}",
                daemon=True,
            )
            self._thread.start()

    def stop(self, join_timeout: float = 1.0):
        """停止看门狗（幂等）。

        参数:
            join_timeout: 等待线程结束的最长时间（秒）

        若 join 超时（线程仍在阻塞的续期 RPC 中）：
        - 记录 warning 日志便于问题排查
        - 保留 _thread 引用，避免下一次 start() 启动出"幽灵双线程"
        - stop_event 已被 set，旧线程一旦 RPC 返回会自然退出
        """
        with self._state_lock:
            thread = self._thread
            stop_event = self._stop_event
        if stop_event is not None:
            stop_event.set()
        if thread is None:
            return
        thread.join(timeout=join_timeout)
        if thread.is_alive():
            # 线程仍在阻塞 RPC：不清空引用，等其自然结束
            logger.warning(
                "watchdog thread for %s did not stop within %.2fs; will exit later",
                self.key,
                join_timeout,
            )
            return
        with self._state_lock:
            # 确认仍是同一线程后再清理（防御并发 stop/start）
            if self._thread is thread:
                self._thread = None
                self._stop_event = None

    def _run(self, stop_event: threading.Event):
        """后台线程主循环：周期性续期，直到被 stop / token 失效 / 连续失败超阈值。

        参数:
            stop_event: 本轮启动时绑定的停止信号；每个线程持有自己的引用，
                        不受后续 start() 新建 Event 影响
        """
        consecutive_failures = 0
        while not stop_event.wait(self.interval):
            try:
                result = self.client.eval(RENEW_LUA, 1, self.key, self.token, self._ttl_ms)
            except Exception:
                consecutive_failures += 1
                logger.warning(
                    "watchdog: renew RPC failed for %s (%d/%d), will retry",
                    self.key,
                    consecutive_failures,
                    self._max_renew_failures,
                    exc_info=True,
                )
                if consecutive_failures >= self._max_renew_failures:
                    # 连续多次 RPC 失败 → 视为锁丢失，避免长时间网络故障
                    # 让业务方误以为仍持锁
                    if not stop_event.is_set():
                        logger.error(
                            "watchdog: %d consecutive renew failures for %s, treating as lost",
                            consecutive_failures,
                            self.key,
                        )
                        self._invoke_on_lost()
                    return
                continue

            # 续期 RPC 成功返回：解析结果
            if _parse_renew_result(result):
                consecutive_failures = 0
                # RPC 阻塞期间可能被 stop，立即检查以加快 release 响应
                if stop_event.is_set():
                    return
                continue

            # token 不匹配：锁已被他人持有或已过期
            # 主动 stop 后到达这里属于竞态（RPC 已成功完成但解析时 stop 已触发），
            # 避免误报：stop 已被设置时不再触发 on_lost
            if stop_event.is_set():
                return
            logger.warning(
                "watchdog: lock %s lost (token mismatch or expired), stopping",
                self.key,
            )
            self._invoke_on_lost()
            return

    def _invoke_on_lost(self):
        """安全调用 on_lost 回调，吞掉用户回调内部的异常。"""
        if self._on_lost is None:
            return
        try:
            self._on_lost(self.key)
        except Exception:
            logger.exception("watchdog on_lost callback raised for %s", self.key)


class AsyncWatchdog:
    """异步看门狗：asyncio.Task 定时续期异步锁。

    使用示例（伪代码）：
        创建 AsyncWatchdog 实例后，先 ``start()`` 启动续期 Task，
        业务执行完成后在 ``finally`` 块中 ``stop()`` 停止续期。
        AsyncRedisLock 已封装好该流程，外部一般无需直接使用。

    协程安全说明：
    - on_lost 回调在 Task 协程上下文中执行；若回调是同步函数应保证短小快速，
      若需做异步 IO 建议在回调中 schedule 一个新 Task
    """

    def __init__(
        self,
        client: AsyncRedisClientProtocol,
        key: str,
        token: str,
        ttl: int,
        interval: float | None = None,
        on_lost: Callable[[str], None] | None = None,
        max_renew_failures: int = DEFAULT_MAX_RENEW_FAILURES,
    ):
        """初始化异步看门狗（参数语义同 SyncWatchdog）。"""
        if max_renew_failures < 1:
            raise ValueError(f"max_renew_failures must be >= 1, got {max_renew_failures}")
        self.client = client
        self.key = key
        self.token = token
        self.ttl = ttl
        self.interval = _validate_ttl_and_interval(ttl, interval)
        self._ttl_ms = ttl * 1000
        self._on_lost = on_lost
        self._max_renew_failures = max_renew_failures
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None

    async def start(self):
        """启动看门狗 Task（幂等）。

        每次启动新建独立 stop_event，避免上一轮残留状态影响本轮。
        """
        if self._task is not None and not self._task.done():
            return
        stop_event = asyncio.Event()
        coro = self._run(stop_event)
        try:
            task = asyncio.create_task(coro, name=f"watchdog-{self.key}")
        except Exception:
            # create_task 失败（事件循环已关闭等）：主动关闭未消费的 coroutine，
            # 避免触发 "coroutine was never awaited" 的 RuntimeWarning
            coro.close()
            raise
        self._stop_event = stop_event
        self._task = task

    async def stop(self):
        """停止看门狗（幂等）。

        优雅停止策略：
        1. 先 set stop_event，让 _run 在下一个等待点正常退出
        2. 若 Task 仍未结束（例如续期 RPC 长时间阻塞），cancel 兜底
        3. await Task 回收资源，吞掉 CancelledError 与内部异常
        """
        stop_event = self._stop_event
        task = self._task
        if stop_event is not None:
            stop_event.set()
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            # _run 内部已记录细节；stop 不应再向调用方抛出
            logger.debug("async watchdog task ended with exception", exc_info=True)
        finally:
            self._task = None
            self._stop_event = None

    async def _run(self, stop_event: asyncio.Event):
        """Task 主循环：等待 stop_event 或间隔超时；超时则续期一次。

        参数:
            stop_event: 本轮启动时绑定的停止信号
        """
        consecutive_failures = 0
        while True:
            try:
                # 等待 stop_event 或间隔超时，任一先到
                await asyncio.wait_for(stop_event.wait(), timeout=self.interval)
                # stop_event 被 set，正常退出
                return
            except TimeoutError:
                # 超时 = 该续期了
                pass

            try:
                result = await self.client.eval(RENEW_LUA, 1, self.key, self.token, self._ttl_ms)
            except asyncio.CancelledError:
                # cancel 兜底：直接退出，不触发 on_lost
                raise
            except Exception:
                consecutive_failures += 1
                logger.warning(
                    "async watchdog: renew RPC failed for %s (%d/%d), will retry",
                    self.key,
                    consecutive_failures,
                    self._max_renew_failures,
                    exc_info=True,
                )
                if consecutive_failures >= self._max_renew_failures:
                    if not stop_event.is_set():
                        logger.error(
                            "async watchdog: %d consecutive renew failures for %s, treating as lost",
                            consecutive_failures,
                            self.key,
                        )
                        self._invoke_on_lost()
                    return
                continue

            if _parse_renew_result(result):
                consecutive_failures = 0
                if stop_event.is_set():
                    return
                continue

            # token 不匹配；主动 stop 触发的竞态不报 on_lost
            if stop_event.is_set():
                return
            logger.warning(
                "async watchdog: lock %s lost (token mismatch or expired), stopping",
                self.key,
            )
            self._invoke_on_lost()
            return

    def _invoke_on_lost(self):
        """安全调用 on_lost 回调，吞掉用户回调内部的异常。"""
        if self._on_lost is None:
            return
        try:
            self._on_lost(self.key)
        except Exception:
            logger.exception("async watchdog on_lost callback raised for %s", self.key)
