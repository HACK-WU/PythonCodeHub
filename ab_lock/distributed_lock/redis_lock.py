"""基于 Redis SET NX 的单键分布式互斥锁。"""

import logging
import random
import time
import uuid
from collections.abc import Callable

from .base import BaseLock
from .lua_scripts import RELEASE_LUA
from .protocols import RedisClientProtocol
from .watchdog import SyncWatchdog

logger = logging.getLogger(__name__)


class RedisLock(BaseLock):
    """基于 Redis SET NX 指令实现的单键分布式互斥锁。

    特性：
    - 通过依赖注入接受任意符合 RedisClientProtocol 的客户端
    - 使用唯一 token（UUID）标识锁持有者，防止误释放他人持有的锁
    - 支持等待重试（wait 参数）与可配置重试间隔（retry_interval）
    - 锁过期时间由 ttl 控制，避免持锁方崩溃导致死锁
    - 释放锁通过 Lua 脚本保证原子性，杜绝误删他人锁的竞态条件
    - 可选 watchdog 自动续期：长事务超过 TTL 也不会丢锁
    """

    def __init__(
        self,
        name: str,
        client: RedisClientProtocol,
        ttl: int | None = None,
        enable_watchdog: bool = False,
        watchdog_interval: float | None = None,
        on_lock_lost: Callable[[str], None] | None = None,
    ):
        """初始化 Redis 单键锁。

        参数:
            name:              锁的 Redis key 名称
            client:            满足 RedisClientProtocol 协议的 Redis 客户端实例（必填）
            ttl:               锁过期时间（秒），未指定时使用 BaseLock 默认值
            enable_watchdog:   是否启用看门狗自动续期，默认 False；
                               启用后 acquire 成功会自动启动后台续期线程，
                               release 时自动停止
            watchdog_interval: 续期间隔（秒），默认 ttl/3
            on_lock_lost:      锁丢失回调（续期发现 token 不匹配时触发），
                               回调参数为锁 key；仅在 enable_watchdog=True 时生效

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        super().__init__(name, ttl)
        if client is None:
            raise ValueError("RedisLock requires a non-None 'client' argument")
        self.client = client
        # 当前实例持有的锁令牌；None 表示未持锁
        self._token: str | None = None
        # 看门狗相关配置
        self._enable_watchdog = enable_watchdog
        self._watchdog_interval = watchdog_interval
        self._on_lock_lost = on_lock_lost
        self._watchdog: SyncWatchdog | None = None

    def acquire(self, wait: float = 0, retry_interval: float = 0.01) -> bool:
        """尝试获取 Redis 分布式锁。

        参数:
            wait:           最长等待时间（秒），默认 0 表示非阻塞，仅尝试一次；
                            > 0 时在该时间窗口内按 retry_interval 轮询重试
            retry_interval: 重试间隔（秒），默认 0.01 秒；实际等待会加入
                            0.5x ~ 1.5x 的随机抖动以缓解多进程惊群

        返回值:
            True  — 成功获取锁
            False — 在等待时间内未能获取锁

        异常:
            RuntimeError: 当本实例已持有锁时（防止重复 acquire 覆盖 _token）

        执行步骤：
        1. 校验本实例当前未持锁，避免覆盖既有 token 导致旧 watchdog 误报
        2. 生成唯一 token，用于标识当前锁持有者
        3. 计算等待截止时间（使用 monotonic，免受系统时钟回拨影响）
        4. 循环调用 SET NX 尝试加锁，成功则按需启动 watchdog；
           失败则按抖动间隔重试，直至超时
        """
        # 防止对同一实例重复 acquire 导致 _token 被覆盖、旧 watchdog 误报
        if self._token is not None:
            raise RuntimeError(f"RedisLock {self.name!r} is already acquired by this instance")

        token = uuid.uuid4().hex
        deadline = time.monotonic() + wait
        while True:
            if self.client.set(self.name, token, ex=self.ttl, nx=True):
                # 加锁成功后按需启动看门狗；启动失败会原子回滚已加的锁
                self._start_watchdog_or_rollback(token)
                self._token = token
                return True
            # 非阻塞或已超时：直接返回失败
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            # 加入抖动避免多进程同时唤醒造成惊群；
            # 同时不允许 sleep 超过剩余 deadline，保证 wait 严格生效
            sleep_for = min(remaining, retry_interval * (0.5 + random.random()))
            time.sleep(sleep_for)

    def _start_watchdog_or_rollback(self, token: str):
        """按配置启动看门狗；启动失败则原子回滚 Redis 端已加的锁。

        参数:
            token: 当前 acquire 周期生成的 token，用于回滚 RELEASE_LUA 校验

        步骤：
        1. 未启用 watchdog 直接返回
        2. 创建并启动 SyncWatchdog
        3. 启动失败：清空 _watchdog，并尽力释放 Redis 端锁；
           回滚 release 异常仅记录日志，避免遮蔽原始启动异常
        """
        if not self._enable_watchdog:
            return
        try:
            self._watchdog = SyncWatchdog(
                client=self.client,
                key=self.name,
                token=token,
                ttl=self.ttl,
                interval=self._watchdog_interval,
                on_lost=self._on_lock_lost,
            )
            self._watchdog.start()
        except Exception:
            self._watchdog = None
            try:
                self.client.eval(RELEASE_LUA, 1, self.name, token)
            except Exception:
                # 回滚释放失败仅记日志，保留原始启动异常向上抛
                logger.exception(
                    "rollback release failed for %s after watchdog start error",
                    self.name,
                )
            raise

    def release(self):
        """释放 Redis 分布式锁（原子操作）。

        通过 Lua 脚本在 Redis 端原子执行 "校验 token → 删除 key"，
        避免先 GET 再 DELETE 导致的竞态条件（锁 TTL 过期后被他人获取，
        本实例误删他人锁）。

        若启用了看门狗，会先停止续期线程再删除 key，保证看门狗不会在
        释放后继续尝试续期；watchdog stop 异常不阻断后续 release。

        返回值:
            1 — 成功删除锁 key
            0 — 本实例未持锁，或 token 不匹配（锁已被他人持有或已过期）
        """
        if not self._token:
            return 0
        # 先停止看门狗：失败仅记录日志，不能因为 stop 异常而跳过 RELEASE_LUA
        # 否则 Redis 端的锁会泄漏到 TTL 过期才被释放
        if self._watchdog is not None:
            try:
                self._watchdog.stop()
            except Exception:
                logger.warning(
                    "watchdog stop failed during release for %s; continuing release",
                    self.name,
                    exc_info=True,
                )
            finally:
                self._watchdog = None
        try:
            result = self.client.eval(RELEASE_LUA, 1, self.name, self._token)
            # 容忍 None / bytes / str 等返回，避免 int(None) 抛 TypeError
            if result is None:
                return 0
            try:
                return 1 if int(result) == 1 else 0
            except (TypeError, ValueError):
                logger.warning("unexpected RELEASE_LUA result for %s: %r", self.name, result)
                return 0
        finally:
            self._token = None

    def is_locked(self) -> bool:
        """查询本实例是否持有锁（仅看本地 token，不发起网络请求）。

        注意：Redis 端可能因 TTL 过期已释放，强一致需直接查询 Redis。
        """
        return self._token is not None
