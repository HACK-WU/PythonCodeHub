"""
缓存后端抽象层

提供可插拔的缓存后端接口，以及内置的内存字典实现。
使用者可自行实现 BaseCacheBackend 来对接 Redis、Memcached 等外部存储。
"""

import abc
import threading
import time
from typing import Any


class BaseCacheBackend(abc.ABC):
    """缓存后端抽象基类"""

    @abc.abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """获取缓存值，不存在时返回 default"""
        ...

    @abc.abstractmethod
    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        """设置缓存值，timeout 单位为秒，None 表示永不过期"""
        ...


class DictCacheBackend(BaseCacheBackend):
    """
    基于内存字典的缓存后端。

    适用于测试、单进程场景。支持 TTL 过期，线程安全。
    不支持分布式，进程间不共享。
    """

    def __init__(self):
        self._store: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            value, expires_at = entry
            if expires_at is not None and time.monotonic() > expires_at:
                del self._store[key]
                return default
            return value

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        expires_at = None
        if timeout is not None:
            expires_at = time.monotonic() + timeout
        with self._lock:
            self._store[key] = (value, expires_at)
