"""
缓存管理模块

提供多种缓存后端实现（内存缓存、Redis 缓存）和缓存客户端混入类
支持灵活的缓存策略和用户级缓存隔离
"""

import abc
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

import redis

from ab_request.http_client.constants import (
    CACHEABLE_METHODS,
    DEFAULT_CACHE_EXPIRE,
    DEFAULT_CACHE_MAXSIZE,
    LOG_FORMAT,
    REDIS_DEFAULT_DB,
    REDIS_DEFAULT_HOST,
    REDIS_DEFAULT_PORT,
    REDIS_MAX_CONNECTIONS,
)

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class BaseCacheBackend(abc.ABC):
    """缓存后端基类"""

    @abc.abstractmethod
    def get(self, key: str) -> Any | None:
        """获取缓存值"""

    @abc.abstractmethod
    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        """设置缓存值，expire 为过期时间（秒）"""

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """删除缓存项"""

    @abc.abstractmethod
    def clear(self) -> None:
        """清空所有缓存"""


class InMemoryCacheBackend(BaseCacheBackend):
    """
    基于内存的 LRU 缓存后端

    使用 OrderedDict 实现 LRU（最近最少使用）缓存策略
    支持过期时间和最大容量限制

    参数:
        maxsize: 缓存最大条目数
    """

    def __init__(self, maxsize: int = DEFAULT_CACHE_MAXSIZE):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        with self.lock:
            if key not in self.cache:
                return None

            value, expire_at = self.cache[key]
            if expire_at is not None and time.time() >= expire_at:
                del self.cache[key]
                logger.debug(f"InMemoryCache expired for key: {key}")
                return None

            # 更新访问顺序
            self.cache.move_to_end(key)
            logger.debug(f"InMemoryCache hit for key: {key}")
            return value

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        with self.lock:
            expire_at = time.time() + expire if expire else None
            self.cache[key] = (value, expire_at)
            self.cache.move_to_end(key)

            # 清理过期项
            while len(self.cache) > self.maxsize:
                oldest_key = next(iter(self.cache))
                _, oldest_expire = self.cache[oldest_key]
                if oldest_expire is not None and time.time() >= oldest_expire:
                    del self.cache[oldest_key]
                else:
                    break

            logger.debug(f"InMemoryCache set for key: {key}, expire: {expire}")

    def delete(self, key: str) -> None:
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                logger.debug(f"InMemoryCache deleted key: {key}")

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()
            logger.debug("InMemoryCache cleared")


class RedisCacheBackend(BaseCacheBackend):
    """
    基于 Redis 的缓存后端

    使用 Redis 作为分布式缓存存储，支持多进程/多服务器共享缓存
    自动处理 JSON 序列化和连接池管理

    参数:
        host: Redis 服务器地址
        port: Redis 服务器端口
        db: Redis 数据库编号
        password: Redis 密码（可选）
        **kwargs: 其他 Redis 连接参数
    """

    def __init__(
        self,
        host=REDIS_DEFAULT_HOST,
        port=REDIS_DEFAULT_PORT,
        db=REDIS_DEFAULT_DB,
        password=None,
        **kwargs,
    ):
        # 使用连接池提高性能
        self.pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=False,
            max_connections=REDIS_MAX_CONNECTIONS,
            **kwargs,
        )
        self.client = redis.Redis(connection_pool=self.pool)

    def get(self, key: str) -> Any | None:
        try:
            value = self.client.get(key)
            if value is not None:
                logger.debug(f"RedisCache hit for key: {key}")
                try:
                    # 尝试解析为JSON
                    return json.loads(value)
                except json.JSONDecodeError:
                    # 原始字节数据
                    return value
            logger.debug(f"RedisCache miss for key: {key}")
            return None
        except redis.RedisError as e:
            logger.error(f"Redis error getting key '{key}': {e}")
            return None

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        try:
            # 自动序列化JSON可序列化对象
            if not isinstance(value, (bytes, str, int, float)):
                value = json.dumps(value)

            if expire:
                self.client.setex(key, expire, value)
            else:
                self.client.set(key, value)

            logger.debug(f"RedisCache set for key: {key}, expire: {expire}")
        except (TypeError, redis.RedisError) as e:
            logger.error(f"Redis error setting key '{key}': {e}")

    def delete(self, key: str) -> None:
        try:
            self.client.delete(key)
            logger.debug(f"RedisCache deleted key: {key}")
        except redis.RedisError as e:
            logger.error(f"Redis error deleting key '{key}': {e}")

    def clear(self) -> None:
        try:
            self.client.flushdb()
            logger.debug("RedisCache cleared (current DB)")
        except redis.RedisError as e:
            logger.error(f"Redis error clearing cache: {e}")


def _generate_cache_key(
    base_url: str, endpoint: str, method: str, request_kwargs: dict[str, Any], user_identifier: str | None = None
) -> str:
    """生成稳定的缓存键"""
    # 创建请求信息的精简表示
    key_data = {
        "url": f"{base_url}/{endpoint}".rstrip("/"),
        "method": method.upper(),
    }

    # 添加影响响应的关键参数
    for k in ["params", "data", "json"]:
        if request_kwargs.get(k):
            key_data[k] = request_kwargs[k]

    # 包含用户标识
    if user_identifier:
        key_data["user"] = user_identifier

    # 稳定序列化
    key_str = json.dumps(key_data, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)

    # 使用更高效的哈希算法
    return hashlib.blake2b(key_str.encode("utf-8"), digest_size=16).hexdigest()


class CacheClientMixin:
    """
    缓存客户端混入类

    为 API 客户端提供透明的缓存功能，支持：
    - 自动缓存 GET/HEAD 请求
    - 用户级缓存隔离
    - 灵活的缓存后端（内存/Redis）
    - 缓存刷新和清除

    类属性:
        cache_backend_class: 缓存后端类
        default_cache_expire: 默认缓存过期时间（秒）
        cacheable_methods: 可缓存的 HTTP 方法集合
        is_user_specific: 是否启用用户级缓存隔离
    """

    cache_backend_class: type[BaseCacheBackend] = InMemoryCacheBackend
    default_cache_expire: int | None = DEFAULT_CACHE_EXPIRE
    cacheable_methods = CACHEABLE_METHODS
    is_user_specific: bool = False

    def __init__(
        self,
        *args,
        cache_expire: int | None = None,
        user_identifier: str | None = None,
        cache_enabled: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # 缓存配置
        self._cache_enabled = cache_enabled
        self._cache_expire = cache_expire or self.default_cache_expire
        self._user_identifier = user_identifier
        # 初始化缓存后端
        self.cache_backend = self._init_cache_backend()

        if self.is_user_specific is True and user_identifier is None:
            raise ValueError("User identifier is required for user-specific caching")

        # 包装请求方法
        if cache_enabled:
            self._wrap_request_methods()

        logger.info(
            f"Cache initialized for {type(self).__name__}. "
            f"Backend: {type(self.cache_backend).__name__}, "
            f"User: {user_identifier or 'N/A'}"
        )

    def _init_cache_backend(self) -> BaseCacheBackend:
        """初始化缓存后端"""
        backend_kwargs = getattr(self, "cache_backend_kwargs", {})
        try:
            return self.cache_backend_class(**backend_kwargs)
        except Exception as e:
            logger.error(f"Failed to initialize cache backend: {e}")
            # 回退到内存缓存
            return InMemoryCacheBackend()

    def _wrap_request_methods(self):
        """包装请求方法以支持缓存"""
        # 保存原始方法引用
        self._original_request = self.request

        # 创建带缓存的包装器
        self.request = self._cached_request

        # 添加缓存控制方法
        self.cacheless = functools.partial(self._uncached_request, mode="cacheless")
        self.refresh = functools.partial(self._uncached_request, mode="refresh")

    def _should_cache(self, method: str) -> bool:
        """判断请求是否应该被缓存"""
        return method.upper() in self.cacheable_methods

    def _get_cache_key(self, request_data: dict) -> str | None:
        """为请求生成缓存键"""
        if not isinstance(request_data, dict):
            return None

        method = request_data.get("method", "GET").upper()
        if not self._should_cache(method):
            return None

        endpoint = request_data.get("endpoint", "")
        request_kwargs = {
            k: v for k, v in request_data.items() if k not in ("method", "endpoint", "cache", "cache_expire")
        }

        return _generate_cache_key(
            base_url=self.base_url,
            endpoint=endpoint,
            method=method,
            request_kwargs=request_kwargs,
            user_identifier=self._user_identifier,
        )

    def _process_single_request(self, request_data: dict, is_async: bool = False) -> Any:
        """处理带缓存的单个请求"""
        # 检查是否启用缓存
        use_cache = request_data.get("cache", True) if isinstance(request_data, dict) else True
        if not use_cache:
            return self._original_request(request_data, is_async)

        # 获取缓存键
        cache_key = self._get_cache_key(request_data)
        if not cache_key:
            return self._original_request(request_data, is_async)

        # 尝试获取缓存
        if (cached := self.cache_backend.get(cache_key)) is not None:
            logger.info(f"Cache HIT for {request_data.get('endpoint')}")
            return cached

        # 缓存未命中，执行请求
        logger.debug(f"Cache MISS for {request_data.get('endpoint')}")
        result = self._original_request(request_data, is_async)

        # 缓存成功响应
        if not is_async and isinstance(result, dict) and result.get("result") is True:
            expire = request_data.get("cache_expire", self._cache_expire)
            try:
                self.cache_backend.set(cache_key, result, expire=expire)
            except Exception as e:
                logger.error(f"Failed to cache response: {e}")

        return result

    def _cached_request(self, request_data: dict | list | None = None, is_async: bool = False) -> Any:
        """带缓存的请求处理"""
        # 处理批量请求
        if isinstance(request_data, list):
            return [self._process_single_request(item, is_async) for item in request_data]

        # 处理单个请求
        return self._process_single_request(request_data, is_async)

    def _uncached_request(
        self,
        mode: str,  # 'cacheless' 或 'refresh'
        request_data: dict | list | None = None,
        is_async: bool = False,
    ) -> Any:
        """绕过缓存的请求处理"""
        # 完全绕过缓存
        if mode == "cacheless":
            return self._original_request(request_data, is_async)

        # 刷新缓存模式
        if mode == "refresh":
            # 执行原始请求
            result = self._original_request(request_data, is_async)

            # 更新缓存
            if isinstance(request_data, dict):
                cache_key = self._get_cache_key(request_data)
                if cache_key and not is_async:
                    expire = request_data.get("cache_expire", self._cache_expire)
                    try:
                        self.cache_backend.set(cache_key, result, expire=expire)
                        logger.info(f"Cache refreshed for {request_data.get('endpoint')}")
                    except Exception as e:
                        logger.error(f"Failed to refresh cache: {e}")
            return result

        logger.error(f"Invalid cache mode: {mode}")
        return self._original_request(request_data, is_async)

    def clear_cache(self, pattern: str | None = None) -> None:
        """清除缓存，支持模式匹配"""
        if not self.cache_backend:
            return

        try:
            # Redis 支持模式删除
            if isinstance(self.cache_backend, RedisCacheBackend) and pattern:
                keys = self.cache_backend.client.keys(pattern)
                if keys:
                    self.cache_backend.client.delete(*keys)
                    logger.info(f"Cleared cache keys matching: {pattern}")
            else:
                self.cache_backend.clear()
                logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Cache clear failed: {e}")

    def disable_cache(self):
        """临时禁用缓存"""
        self._cache_enabled = False
        if hasattr(self, "_original_request"):
            self.request = self._original_request

    def enable_cache(self):
        """启用缓存"""
        self._cache_enabled = True
        if hasattr(self, "_original_request"):
            self.request = self._cached_request
