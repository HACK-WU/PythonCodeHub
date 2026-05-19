"""
throttling — Celery 任务限流辅助

本模块仅提供：
- ThrottleBackend：全局限流后端协议
- MemoryThrottleBackend：内存后端（仅测试 / 单进程场景）
- RedisThrottleBackend：Redis 后端（可选依赖）
- ThrottleLease：一次限流检查结果
- ThrottleExceededError：显式拒绝时抛出的异常
- acquire_throttle：显式限流检查入口
- throttled_task：函数级限流包装
- build_rate_limited_task_options：单 worker `rate_limit` 透传辅助

设计要点：
- 单 worker 限流直接复用 Celery 原生 `rate_limit`，公共层不重复实现
- 全局限流通过可插拔后端实现；公共层不固定算法，仅给出最小默认实现
- 限流触发后的处理路径必须显式选择：reject / delay / queue
- Redis 仅在显式启用时导入；未安装时抛出明确异常
"""

from __future__ import annotations

import math
import threading
import time
import typing
from dataclasses import dataclass
from functools import wraps

ThrottleAction = typing.Literal["reject", "delay", "queue"]


class ThrottleExceededError(RuntimeError):
    """限流触发且调用方选择拒绝执行。"""

    def __init__(self, lease: "ThrottleLease") -> None:
        super().__init__(
            f"限流已触发: bucket={lease.bucket!r} limit={lease.limit} "
            f"window_seconds={lease.window_seconds} retry_after={lease.retry_after_seconds}"
        )
        self.lease = lease


class MissingOptionalDependencyError(ImportError):
    """缺失可选依赖。"""


@dataclass(frozen=True)
class ThrottleLease:
    """
    一次限流检查结果。

    字段：
        bucket: 调用方提供的限流桶名称
        allowed: 当前调用是否允许继续执行
        limit: 当前窗口允许的最大次数
        window_seconds: 限流窗口长度
        current_count: 当前窗口内已占用次数
        remaining: 当前窗口剩余可用次数
        retry_after_seconds: 建议重试秒数；None 表示后端未提供
    """

    bucket: str
    allowed: bool
    limit: int
    window_seconds: int
    current_count: int
    remaining: int
    retry_after_seconds: int | None = None


class ThrottleBackend(typing.Protocol):
    """全局限流后端协议。"""

    def acquire(self, bucket: str, limit: int, window_seconds: int) -> ThrottleLease:
        """尝试占用当前限流桶中的一个执行名额。"""
        ...


class MemoryThrottleBackend:
    """
    内存限流后端。

    说明：
    - 仅适用于单进程 / 单测场景
    - 使用固定窗口计数实现最小限流能力
    - 通过线程锁保证进程内并发安全
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[int, int]] = {}

    def _now(self) -> float:
        return time.time()

    def acquire(self, bucket: str, limit: int, window_seconds: int) -> ThrottleLease:
        _validate_bucket_limit_window(bucket, limit, window_seconds)
        now = self._now()
        window_index = int(now // window_seconds)
        window_end = (window_index + 1) * window_seconds

        with self._lock:
            stored_window_index, count = self._entries.get(bucket, (window_index, 0))
            if stored_window_index != window_index:
                stored_window_index, count = window_index, 0

            if count < limit:
                count += 1
                self._entries[bucket] = (stored_window_index, count)
                return ThrottleLease(
                    bucket=bucket,
                    allowed=True,
                    limit=limit,
                    window_seconds=window_seconds,
                    current_count=count,
                    remaining=max(0, limit - count),
                    retry_after_seconds=max(1, math.ceil(window_end - now)),
                )

            self._entries[bucket] = (stored_window_index, count)
            return ThrottleLease(
                bucket=bucket,
                allowed=False,
                limit=limit,
                window_seconds=window_seconds,
                current_count=count,
                remaining=0,
                retry_after_seconds=max(1, math.ceil(window_end - now)),
            )


class RedisThrottleBackend:
    """
    Redis 限流后端。

    说明：
    - 仅在实例化时尝试导入 redis
    - 使用固定窗口计数实现最小全局限流能力
    - 具体算法可由调用方自定义后端替换
    """

    def __init__(self, client: typing.Any, *, prefix: str = "ab_celery:throttle") -> None:
        if not isinstance(prefix, str) or not prefix:
            raise TypeError("prefix 必须为非空字符串")
        self._redis_module = _import_redis()
        self.client = client
        self.prefix = prefix

    def _full_key(self, bucket: str, window_index: int) -> str:
        return f"{self.prefix}:{bucket}:{window_index}"

    def acquire(self, bucket: str, limit: int, window_seconds: int) -> ThrottleLease:
        _validate_bucket_limit_window(bucket, limit, window_seconds)
        now = time.time()
        window_index = int(now // window_seconds)
        window_end = (window_index + 1) * window_seconds
        redis_key = self._full_key(bucket, window_index)

        current_count = self.client.incr(redis_key)
        if current_count == 1:
            self.client.expire(redis_key, window_seconds)

        ttl = self.client.ttl(redis_key)
        retry_after_seconds = _ttl_to_retry_after(ttl, window_end=window_end, now=now)
        allowed = current_count <= limit
        remaining = max(0, limit - min(current_count, limit))
        return ThrottleLease(
            bucket=bucket,
            allowed=allowed,
            limit=limit,
            window_seconds=window_seconds,
            current_count=current_count,
            remaining=remaining,
            retry_after_seconds=retry_after_seconds,
        )


def acquire_throttle(
    backend: ThrottleBackend,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
) -> ThrottleLease:
    """显式执行一次限流检查。"""
    if backend is None:
        raise TypeError("backend 不能为 None")
    return backend.acquire(bucket=bucket, limit=limit, window_seconds=window_seconds)


def build_rate_limited_task_options(
    *,
    rate_limit: str,
    **task_options: typing.Any,
) -> dict[str, typing.Any]:
    """
    构造带 Celery 原生 `rate_limit` 的任务选项。

    该函数只做参数透传与基础校验，不实现任何额外限流语义。
    """
    if not isinstance(rate_limit, str) or not rate_limit.strip():
        raise TypeError("rate_limit 必须为非空字符串")
    options = dict(task_options)
    options["rate_limit"] = rate_limit.strip()
    return options


def throttled_task(
    *,
    backend: ThrottleBackend,
    bucket_getter: typing.Callable[..., str],
    limit: int,
    window_seconds: int,
    on_throttled: ThrottleAction,
    queue_handler: typing.Callable[..., typing.Any] | None = None,
    sleep_func: typing.Callable[[float], None] = time.sleep,
) -> typing.Callable[[typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]]:
    """
    为普通函数提供最小限流包装。

    参数：
        backend: 全局限流后端
        bucket_getter: 从入参中提取限流桶名称
        limit: 当前窗口最大允许次数
        window_seconds: 限流窗口长度
        on_throttled: 触发限流后的处理路径，只允许 reject / delay / queue
        queue_handler: 当 on_throttled="queue" 时必须提供，用于显式排队 / 重试
        sleep_func: 当 on_throttled="delay" 时使用的休眠函数，便于测试替换
    """
    if backend is None:
        raise TypeError("backend 不能为 None")
    if not callable(bucket_getter):
        raise TypeError("bucket_getter 必须为可调用对象")
    _validate_limit_window(limit, window_seconds)
    _validate_on_throttled(on_throttled)
    if on_throttled == "queue" and not callable(queue_handler):
        raise TypeError('on_throttled="queue" 时必须提供 queue_handler')
    if on_throttled == "delay" and not callable(sleep_func):
        raise TypeError("sleep_func 必须为可调用对象")

    def decorator(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            bucket = bucket_getter(*args, **kwargs)
            lease = acquire_throttle(
                backend,
                bucket=bucket,
                limit=limit,
                window_seconds=window_seconds,
            )
            if lease.allowed:
                return func(*args, **kwargs)

            if on_throttled == "reject":
                raise ThrottleExceededError(lease)
            if on_throttled == "delay":
                delay_seconds = lease.retry_after_seconds or window_seconds
                sleep_func(delay_seconds)
                return func(*args, **kwargs)
            return queue_handler(lease, *args, **kwargs)

        return wrapper

    return decorator


def _validate_bucket_limit_window(bucket: str, limit: int, window_seconds: int) -> None:
    if not isinstance(bucket, str) or not bucket:
        raise TypeError("bucket 必须为非空字符串")
    _validate_limit_window(limit, window_seconds)


def _validate_limit_window(limit: int, window_seconds: int) -> None:
    if not isinstance(limit, int) or limit <= 0:
        raise TypeError("limit 必须为正整数")
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise TypeError("window_seconds 必须为正整数")


def _validate_on_throttled(on_throttled: str) -> None:
    if on_throttled not in {"reject", "delay", "queue"}:
        raise TypeError('on_throttled 只允许为 "reject"、"delay" 或 "queue"')


def _ttl_to_retry_after(ttl: typing.Any, *, window_end: float, now: float) -> int:
    if ttl is None or ttl == -1:
        return max(1, math.ceil(window_end - now))
    if ttl == -2:
        return 1
    if not isinstance(ttl, int):
        raise TypeError("Redis ttl 必须为 int 或 None")
    return max(1, ttl)


def _import_redis() -> typing.Any:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise MissingOptionalDependencyError(
            "使用 RedisThrottleBackend 需要先安装可选依赖 redis"
        ) from exc
    return redis


__all__ = [
    "MemoryThrottleBackend",
    "MissingOptionalDependencyError",
    "RedisThrottleBackend",
    "ThrottleBackend",
    "ThrottleExceededError",
    "ThrottleLease",
    "acquire_throttle",
    "build_rate_limited_task_options",
    "throttled_task",
]
