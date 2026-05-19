"""
idempotency — 任务幂等去重辅助

本模块仅提供：
- IdempotencyBackend：幂等存储后端协议
- MemoryIdempotencyBackend：内存后端（仅测试 / 单进程场景）
- RedisIdempotencyBackend：Redis 后端（可选依赖）
- IdempotencyLease：一次幂等占用结果
- acquire_idempotency / release_idempotency：显式占用与释放入口
- idempotent_task：函数级幂等包装

设计要点：
- 幂等键完全由调用方提供，公共层不内置 hash 策略
- 后端可插拔，公共层默认提供内存实现；Redis 仅在显式启用时导入
- 使用 owner 表达一次任务执行上下文；同一个 key + owner 的重复获取视为重入，
  以保证 AutoRetryTask 的重试不被误判为重复
- 不负责业务结果缓存；仅解决“是否允许执行”这一最小问题
"""

from __future__ import annotations

import threading
import time
import typing
from dataclasses import dataclass
from functools import wraps


class IdempotencyConflictError(RuntimeError):
    """幂等键已被其他 owner 占用。"""


class MissingOptionalDependencyError(ImportError):
    """缺失可选依赖。"""


@dataclass(frozen=True)
class IdempotencyLease:
    """
    一次幂等占用结果。

    字段：
        key: 调用方提供的幂等键
        owner: 当前执行上下文标识；同 key + owner 可重复获取
        acquired: 是否由当前调用新获取成功
        reentrant: 是否命中同 owner 重入
        expires_at: 过期时间戳；None 表示后端不提供
    """

    key: str
    owner: str
    acquired: bool
    reentrant: bool
    expires_at: float | None = None


class IdempotencyBackend(typing.Protocol):
    """幂等后端协议。"""

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> IdempotencyLease:
        """尝试占用幂等键。"""
        ...

    def release(self, key: str, owner: str) -> bool:
        """仅释放自己持有的幂等键。"""
        ...

    def is_locked(self, key: str) -> bool:
        """判断幂等键当前是否被占用。"""
        ...


class MemoryIdempotencyBackend:
    """
    内存幂等后端。

    说明：
    - 仅适用于单进程 / 单测场景
    - 通过线程锁保证进程内并发安全
    - 记录 owner 与过期时间；同 owner 可重入
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[str, float]] = {}

    def _now(self) -> float:
        return time.time()

    def _purge_if_expired(self, key: str, now: float | None = None) -> None:
        now = self._now() if now is None else now
        entry = self._entries.get(key)
        if entry is None:
            return
        _, expires_at = entry
        if expires_at <= now:
            self._entries.pop(key, None)

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> IdempotencyLease:
        _validate_key_owner_ttl(key, owner, ttl_seconds)
        now = self._now()
        with self._lock:
            self._purge_if_expired(key, now=now)
            entry = self._entries.get(key)
            if entry is None:
                expires_at = now + ttl_seconds
                self._entries[key] = (owner, expires_at)
                return IdempotencyLease(
                    key=key,
                    owner=owner,
                    acquired=True,
                    reentrant=False,
                    expires_at=expires_at,
                )

            current_owner, expires_at = entry
            if current_owner == owner:
                return IdempotencyLease(
                    key=key,
                    owner=owner,
                    acquired=False,
                    reentrant=True,
                    expires_at=expires_at,
                )

        raise IdempotencyConflictError(f"幂等键已被占用: key={key!r}")

    def release(self, key: str, owner: str) -> bool:
        _validate_key_owner(key, owner)
        with self._lock:
            self._purge_if_expired(key)
            entry = self._entries.get(key)
            if entry is None:
                return False
            current_owner, _ = entry
            if current_owner != owner:
                return False
            self._entries.pop(key, None)
            return True

    def is_locked(self, key: str) -> bool:
        if not isinstance(key, str) or not key:
            raise TypeError("key 必须为非空字符串")
        with self._lock:
            self._purge_if_expired(key)
            return key in self._entries


class RedisIdempotencyBackend:
    """
    Redis 幂等后端。

    说明：
    - 仅在实例化时尝试导入 redis
    - 使用 set(nx=True, ex=ttl_seconds) 做首次占用
    - 同 owner 重入通过读取当前 value 判定
    - release 仅删除自己持有的 key
    """

    def __init__(self, client: typing.Any, *, prefix: str = "ab_celery:idempotency") -> None:
        if not isinstance(prefix, str) or not prefix:
            raise TypeError("prefix 必须为非空字符串")
        self._redis_module = _import_redis()
        self.client = client
        self.prefix = prefix

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}:{key}"

    def _decode(self, value: typing.Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        if isinstance(value, str):
            return value
        raise TypeError("Redis 幂等值必须为 str / bytes / None")

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> IdempotencyLease:
        _validate_key_owner_ttl(key, owner, ttl_seconds)
        redis_key = self._full_key(key)
        ok = self.client.set(redis_key, owner, nx=True, ex=ttl_seconds)
        ttl = self.client.ttl(redis_key)
        expires_at = _ttl_to_expires_at(ttl)
        if ok:
            return IdempotencyLease(
                key=key,
                owner=owner,
                acquired=True,
                reentrant=False,
                expires_at=expires_at,
            )

        current_owner = self._decode(self.client.get(redis_key))
        if current_owner == owner:
            return IdempotencyLease(
                key=key,
                owner=owner,
                acquired=False,
                reentrant=True,
                expires_at=expires_at,
            )

        raise IdempotencyConflictError(f"幂等键已被占用: key={key!r}")

    def release(self, key: str, owner: str) -> bool:
        _validate_key_owner(key, owner)
        redis_key = self._full_key(key)
        current_owner = self._decode(self.client.get(redis_key))
        if current_owner != owner:
            return False
        return bool(self.client.delete(redis_key))

    def is_locked(self, key: str) -> bool:
        if not isinstance(key, str) or not key:
            raise TypeError("key 必须为非空字符串")
        ttl = self.client.ttl(self._full_key(key))
        return ttl is None or ttl != -2


def acquire_idempotency(
    backend: IdempotencyBackend,
    *,
    key: str,
    owner: str,
    ttl_seconds: int,
) -> IdempotencyLease:
    """显式获取幂等占用。"""
    if backend is None:
        raise TypeError("backend 不能为 None")
    return backend.acquire(key=key, owner=owner, ttl_seconds=ttl_seconds)


def release_idempotency(
    backend: IdempotencyBackend,
    *,
    key: str,
    owner: str,
) -> bool:
    """显式释放幂等占用。"""
    if backend is None:
        raise TypeError("backend 不能为 None")
    return backend.release(key=key, owner=owner)


def idempotent_task(
    *,
    backend: IdempotencyBackend,
    key_getter: typing.Callable[..., str],
    owner_getter: typing.Callable[..., str],
    ttl_seconds: int,
    release_on_success: bool = False,
) -> typing.Callable[[typing.Callable[..., typing.Any]], typing.Callable[..., typing.Any]]:
    """
    为普通函数提供最小幂等包装。

    参数：
        backend: 幂等后端
        key_getter: 从入参中提取幂等键
        owner_getter: 从入参中提取执行 owner；同 owner 视为重入
        ttl_seconds: 幂等 TTL，必须为正整数
        release_on_success: 成功后是否立即释放；默认 False，保留 TTL 窗口
    """
    if backend is None:
        raise TypeError("backend 不能为 None")
    if not callable(key_getter):
        raise TypeError("key_getter 必须为可调用对象")
    if not callable(owner_getter):
        raise TypeError("owner_getter 必须为可调用对象")
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise TypeError("ttl_seconds 必须为正整数")
    if not isinstance(release_on_success, bool):
        raise TypeError("release_on_success 必须为 bool")

    def decorator(func: typing.Callable[..., typing.Any]) -> typing.Callable[..., typing.Any]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = key_getter(*args, **kwargs)
            owner = owner_getter(*args, **kwargs)
            lease = backend.acquire(key=key, owner=owner, ttl_seconds=ttl_seconds)
            try:
                return func(*args, **kwargs)
            finally:
                if release_on_success and (lease.acquired or lease.reentrant):
                    backend.release(key=key, owner=owner)

        return wrapper

    return decorator


def _validate_key_owner(key: str, owner: str) -> None:
    if not isinstance(key, str) or not key:
        raise TypeError("key 必须为非空字符串")
    if not isinstance(owner, str) or not owner:
        raise TypeError("owner 必须为非空字符串")


def _validate_key_owner_ttl(key: str, owner: str, ttl_seconds: int) -> None:
    _validate_key_owner(key, owner)
    if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
        raise TypeError("ttl_seconds 必须为正整数")


def _ttl_to_expires_at(ttl: typing.Any) -> float | None:
    if ttl is None:
        return None
    if ttl in (-1, -2):
        return None
    if not isinstance(ttl, int):
        raise TypeError("Redis ttl 必须为 int 或 None")
    return time.time() + ttl


def _import_redis() -> typing.Any:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise MissingOptionalDependencyError(
            "使用 RedisIdempotencyBackend 需要先安装可选依赖 redis"
        ) from exc
    return redis


__all__ = [
    "IdempotencyBackend",
    "IdempotencyConflictError",
    "IdempotencyLease",
    "MemoryIdempotencyBackend",
    "MissingOptionalDependencyError",
    "RedisIdempotencyBackend",
    "acquire_idempotency",
    "idempotent_task",
    "release_idempotency",
]
