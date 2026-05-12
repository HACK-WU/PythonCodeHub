"""Redlock 算法：基于多个独立 Redis 实例的高可用分布式锁。

参考：https://redis.io/docs/manual/patterns/distributed-locks/

核心思想：
    在 N 个**相互独立**（非主从复制）的 Redis 实例上同时尝试加锁，
    仅当 **多数派（N/2 + 1）** 节点加锁成功，且整体耗时 < TTL 时，
    才认为加锁成功。失败时回滚已获取的部分。

与单节点 RedisLock 的差异：
- 单节点方案在 Redis Master 故障切换期间可能出现两个客户端同时持锁
  （锁信息未来得及复制到新 Master）。
- Redlock 要求多数派节点同时失效才会产生脑裂，可用性显著提升。

使用前提：
- 提供 N 个独立的 Redis 实例（建议 N ≥ 3 且为奇数，如 3 / 5 / 7）
- 各实例之间无主从关系、独立部署、独立故障域
- 系统时钟不能发生大幅跳跃（算法假设各节点时钟漂移在可控范围内）

算法步骤（对应 acquire）：
1. 记录开始时间 t0
2. 依次向 N 个实例发送 SET NX PX，设置较短的超时，避免单节点故障拖慢整体
3. 统计成功节点数 n_success
4. 计算耗时 elapsed = now - t0；有效剩余 TTL = ttl - elapsed - clock_drift
5. 若 n_success ≥ quorum 且 有效剩余 TTL > 0：加锁成功
6. 否则：向所有节点（包括失败节点，防止超时实际写入成功）发 DEL 回滚

算法步骤（对应 release）：
- 向所有节点发送 Lua 脚本原子释放（token 校验）
"""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid
import warnings
from collections.abc import Callable

from .base import BaseLock
from .lua_scripts import RELEASE_LUA, RENEW_LUA
from .protocols import RedisClientProtocol

logger = logging.getLogger(__name__)

# 时钟漂移补偿系数（Redis 官方推荐 0.01，即 1%）。
# 有效持锁时间会扣除 elapsed + ttl * CLOCK_DRIFT_FACTOR，
# 避免因系统时钟漂移导致实际过期比预期提前。
CLOCK_DRIFT_FACTOR = 0.01

# 看门狗 stop 时等待线程退出的最大秒数；与 SyncWatchdog.stop 默认值保持一致，
# 避免 release 路径阻塞业务调用方过久。
_WATCHDOG_JOIN_TIMEOUT = 1.0


class Redlock(BaseLock):
    """Redlock 算法实现的高可用分布式锁。

    特性：
    - 接受 N 个独立 Redis 客户端，需多数派加锁成功
    - 加锁失败自动回滚已获取节点，避免锁泄漏
    - 支持重试与指数退避（retry_times + retry_delay）
    - 使用唯一 token，释放时通过 Lua 脚本原子校验
    - 返回的 `valid_until` 可用于业务侧判断锁是否仍有效

    示例：
        >>> import redis
        >>> clients = [
        ...     redis.StrictRedis(host="10.0.0.1"),
        ...     redis.StrictRedis(host="10.0.0.2"),
        ...     redis.StrictRedis(host="10.0.0.3"),
        ... ]
        >>> with Redlock("order:123", clients=clients, ttl=10) as lock:
        ...     do_critical_work()
    """

    def __init__(
        self,
        name: str,
        clients: list[RedisClientProtocol],
        ttl: int | None = None,
        retry_times: int = 3,
        retry_delay: float = 0.2,
        node_timeout: float | None = None,
        enable_watchdog: bool = False,
        watchdog_interval: float | None = None,
        on_lock_lost: Callable[[str], None] | None = None,
    ):
        """初始化 Redlock。

        参数:
            name:              锁的 Redis key 名称
            clients:           独立 Redis 实例客户端列表，建议 3/5/7 个
            ttl:               锁过期时间（秒），默认 60 秒
            retry_times:       加锁失败总重试次数，默认 3
            retry_delay:       重试间隔基数（秒），实际间隔会加入随机抖动
            node_timeout:      [已废弃] 单节点操作超时（秒）。当前实现不使用该参数，
                               请在构造 Redis 客户端时显式设置 socket_timeout 控制单节点超时；
                               算法内部通过 `elapsed > ttl` 提前熔断防止整体被慢节点拖死。
                               传入非 None 值会触发 DeprecationWarning。
            enable_watchdog:   是否启用看门狗多节点自动续期，默认 False；
                               启用后 acquire 成功会启动后台续期线程，仅当多数派节点续期
                               成功才认为锁仍有效；否则触发 on_lock_lost 并停止看门狗
            watchdog_interval: 续期间隔（秒），默认 ttl/3
            on_lock_lost:      锁丢失回调（多数派节点续期失败时触发），
                               仅在 enable_watchdog=True 时生效

        异常:
            ValueError: clients 为空时抛出
        """
        super().__init__(name, ttl)
        if not clients:
            raise ValueError("Redlock requires at least one Redis client")
        self.clients: list[RedisClientProtocol] = list(clients)
        self.n = len(self.clients)
        # 多数派阈值：N/2 + 1
        self.quorum = self.n // 2 + 1
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        if node_timeout is not None:
            warnings.warn(
                "Redlock.node_timeout is deprecated and has no effect; "
                "configure socket_timeout on the underlying Redis client instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # 共享状态保护锁：_token / _valid_until / _watchdog_* 均通过它互斥访问
        self._state_lock = threading.Lock()
        self._token: str | None = None
        # 加锁成功后的有效截止时间（monotonic），None 表示未持锁
        self._valid_until: float | None = None

        # 看门狗相关配置
        self._enable_watchdog = enable_watchdog
        self._watchdog_interval = watchdog_interval
        self._on_lock_lost = on_lock_lost
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop: threading.Event | None = None

    # ─────────────────────────────────────────────────────
    # 内部辅助方法
    # ─────────────────────────────────────────────────────
    def _lock_instance(self, client: RedisClientProtocol, token: str) -> bool:
        """在单个实例上尝试加锁；任何异常都视为失败（节点不可用）。"""
        try:
            return bool(client.set(self.name, token, ex=self.ttl, nx=True))
        except Exception:
            logger.debug("redlock: SET NX failed on one instance", exc_info=True)
            return False

    def _unlock_instance(self, client: RedisClientProtocol, token: str):
        """在单个实例上释放锁（Lua 脚本原子校验 token）；异常吞掉。"""
        try:
            client.eval(RELEASE_LUA, 1, self.name, token)
        except Exception:
            logger.debug("redlock: release failed on one instance", exc_info=True)

    def _renew_instance(self, client: RedisClientProtocol, token: str, ttl_ms: int) -> bool:
        """在单节点上续期；token 不匹配或异常返回 False。"""
        try:
            return int(client.eval(RENEW_LUA, 1, self.name, token, ttl_ms)) == 1
        except Exception:
            logger.debug("redlock: renew failed on one instance", exc_info=True)
            return False

    # ──────────────────────────────────────────────────
    # Watchdog（多节点多数派续期）
    # ──────────────────────────────────────────────────
    def _start_watchdog(self, token: str):
        """启动后台续期线程（幂等）。

        续期策略：
        - 间隔默认 ttl/3，必须小于 ttl
        - 每轮遵循 Redlock 多数派语义：向所有节点发送 RENEW，
          仅当 >= quorum 个节点返回 1 才认为续期成功。否则触发 on_lock_lost
          并退出线程（不释放现有节点，交由 release / TTL 过期清理）
        """
        interval = self._watchdog_interval if self._watchdog_interval is not None else max(self.ttl / 3, 0.1)
        if interval >= self.ttl:
            raise ValueError(f"watchdog interval ({interval}s) must be < ttl ({self.ttl}s)")

        self._watchdog_stop = threading.Event()
        stop_event = self._watchdog_stop
        ttl_ms = self.ttl * 1000

        def _run():
            while not stop_event.wait(interval):
                renewed = 0
                for client in self.clients:
                    if stop_event.is_set():
                        return
                    if self._renew_instance(client, token, ttl_ms):
                        renewed += 1
                if renewed >= self.quorum:
                    # 多数派续期成功：延后本地有效截止时间（写共享状态需加锁）
                    valid_time = self.ttl - self.ttl * CLOCK_DRIFT_FACTOR
                    new_until = time.monotonic() + valid_time
                    with self._state_lock:
                        # 仅当 token 仍然属于本轮加锁结果时才更新；防止 release 后仍写入
                        if self._token == token:
                            self._valid_until = new_until
                else:
                    logger.warning(
                        "redlock watchdog: lock %s lost (renewed %d/%d < quorum %d), stopping",
                        self.name,
                        renewed,
                        self.n,
                        self.quorum,
                    )
                    if self._on_lock_lost is not None:
                        try:
                            self._on_lock_lost(self.name)
                        except Exception:
                            logger.exception("redlock watchdog on_lock_lost callback raised for %s", self.name)
                    return
                # 续期 RPC 可能耗时较久，完成后立即检查 stop
                if stop_event.is_set():
                    return

        self._watchdog_thread = threading.Thread(target=_run, name=f"redlock-watchdog-{self.name}", daemon=True)
        self._watchdog_thread.start()

    def _stop_watchdog(self):
        """停止后台续期线程（幂等）。

        join 超时固定为 _WATCHDOG_JOIN_TIMEOUT(1s)，避免 release 路径阻塞业务过久；
        超时后由 daemon 线程自然结束，不影响主流程。
        """
        if self._watchdog_stop is not None:
            self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=_WATCHDOG_JOIN_TIMEOUT)
        self._watchdog_thread = None
        self._watchdog_stop = None

    # ─────────────────────────────────────────────────────
    # 公开 API
    # ─────────────────────────────────────────────────────
    def acquire(self, wait: float = 0) -> bool:
        """尝试在多数派实例上加锁。

        参数:
            wait: 兼容 BaseLock 接口的等待时间（未使用；Redlock 使用
                   retry_times / retry_delay 控制重试）

        返回值:
            True  — 多数派加锁成功，且扣除耗时后仍有足够的有效持锁时间
            False — 达到最大重试次数仍未成功
        """
        for attempt in range(self.retry_times):
            # 每轮重新生成 token，避免上一轮回滚失败时残留 key 干扰本轮 SET NX
            token = uuid.uuid4().hex
            start = time.monotonic()

            # 步骤 1：向所有节点尝试加锁
            #   单节点超时熔断：如果整体耗时已经超过 ttl，再继续遍历也来不及，
            #   提前进入回滚阶段，避免被慢节点拖死整次 acquire。
            success_clients: list[RedisClientProtocol] = []
            for client in self.clients:
                if time.monotonic() - start > self.ttl:
                    logger.warning("redlock: acquire aborted mid-loop, elapsed exceeds ttl=%d", self.ttl)
                    break
                if self._lock_instance(client, token):
                    success_clients.append(client)

            # 步骤 2：计算耗时与有效持锁时间
            elapsed = time.monotonic() - start
            # 扣除时钟漂移补偿，得到实际可用的持锁时长
            valid_time = self.ttl - elapsed - self.ttl * CLOCK_DRIFT_FACTOR

            # 步骤 3：判断是否达到多数派 且 仍有有效持锁时间
            if len(success_clients) >= self.quorum and valid_time > 0:
                with self._state_lock:
                    self._token = token
                    self._valid_until = time.monotonic() + valid_time
                logger.debug(
                    "redlock acquired: name=%s quorum=%d/%d valid=%.3fs",
                    self.name,
                    len(success_clients),
                    self.n,
                    valid_time,
                )
                # 加锁成功后按需启动看门狗
                if self._enable_watchdog:
                    try:
                        self._start_watchdog(token)
                    except Exception:
                        # 看门狗启动失败：主动回滚已加的锁，避免泄漏到 TTL 过期
                        for client in self.clients:
                            self._unlock_instance(client, token)
                        with self._state_lock:
                            self._token = None
                            self._valid_until = None
                        raise
                return True

            # 多数派达到但耗时过长：单独告警，便于定位"看似成功却被丢弃"的场景
            if len(success_clients) >= self.quorum and valid_time <= 0:
                logger.warning(
                    "redlock: quorum %d/%d reached but elapsed=%.3fs >= ttl=%d, rolling back",
                    len(success_clients),
                    self.n,
                    elapsed,
                    self.ttl,
                )

            # 步骤 4：失败回滚——向**所有节点**（包括失败节点）发 DEL，
            # 防止因网络超时 / 节点响应丢失导致的"实际写入成功但返回失败"
            for client in self.clients:
                self._unlock_instance(client, token)

            # 重试前随机 sleep，缓解惊群
            if attempt < self.retry_times - 1:
                time.sleep(self.retry_delay * (0.5 + random.random()))

        return False

    def release(self) -> int:
        """向所有实例释放锁（原子校验 token）。

        返回值:
            实际释放成功的节点数量（token 匹配并删除）
        """
        # 取出 token 并清空本地状态：必须在 _state_lock 内一次性完成，
        # 防止 watchdog 线程在 release 期间继续写 _valid_until
        with self._state_lock:
            if not self._token:
                return 0
            token = self._token
            self._token = None
            self._valid_until = None

        # 先停看门狗，避免释放过程中仍在续期（_state_lock 不持有，避免死锁）
        if self._watchdog_thread is not None:
            self._stop_watchdog()

        released = 0
        for client in self.clients:
            try:
                result = client.eval(RELEASE_LUA, 1, self.name, token)
                if int(result) == 1:
                    released += 1
            except Exception:
                logger.debug("redlock: release failed on one instance", exc_info=True)
        return released

    def is_locked(self) -> bool:
        """查询本实例是否持有锁（本地视角）。

        仅判断 token 是否存在以及 valid_until 是否未到期，
        不发起网络请求。
        """
        with self._state_lock:
            if self._token is None or self._valid_until is None:
                return False
            return time.monotonic() < self._valid_until

    @property
    def valid_until(self) -> float | None:
        """当前锁的有效截止时间（time.monotonic() 时间戳），未持锁时为 None。

        业务侧可用 `lock.valid_until - time.monotonic()` 判断剩余时间，
        避免在锁即将过期时仍执行耗时操作。
        """
        with self._state_lock:
            return self._valid_until
