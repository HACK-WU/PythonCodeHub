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

from http_client.constants import (
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


def generate_cache_key(
    url: str, method: str, request_kwargs: dict[str, Any], user_identifier: str | None = None
) -> str:
    """生成稳定的缓存键"""
    # 创建请求信息的精简表示
    key_data = {
        "url": url,
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

    使用方式：
        class MyAPIClient(BaseClient, CacheClientMixin):
            pass

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
        should_cache_response_func: callable | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # 缓存配置
        self.enable_cache = True
        self._cache_expire = cache_expire or self.default_cache_expire
        self._user_identifier = user_identifier
        self._should_cache_response_func = should_cache_response_func
        # 初始化缓存后端
        self.cache_backend = self._init_cache_backend()

        if self.is_user_specific is True and user_identifier is None:
            raise ValueError("User identifier is required for user-specific caching")

        # 包装请求方法
        self._wrap_request_methods()

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

    def _should_cache_response(self, result: Any) -> bool:
        """判断响应是否应该被缓存（子类可重写或通过参数覆盖）"""
        # 优先使用用户传入的自定义函数
        if self._should_cache_response_func is not None:
            try:
                return self._should_cache_response_func(result)
            except Exception as e:
                logger.error(f"Custom should_cache_response_func failed: {e}, using default logic")

        # 使用默认逻辑
        return self.default_cache_response_check(result)

    def default_cache_response_check(self, result: Any) -> bool:
        """默认的响应缓存判断逻辑（子类可重写）"""
        if isinstance(result, dict):
            return result.get("result") is True
        return True  # 默认缓存所有响应

    def _extract_cache_relevant_headers(self, headers: dict) -> dict:
        """提取影响缓存的关键 headers（子类可重写）"""
        relevant_keys = {"Accept-Language", "Accept", "Content-Type"}
        return {k: v for k, v in headers.items() if k in relevant_keys}

    def _get_cache_key(self, request_data: dict) -> str | None:
        """为请求生成缓存键"""
        if not isinstance(request_data, dict):
            return None

        method = request_data.get("method", "GET").upper()

        if method not in self.cacheable_methods:
            return None

        # 排除缓存控制参数
        exclude_keys = {"method", "endpoint", "cache", "cache_expire", "headers"}
        request_kwargs = {k: v for k, v in request_data.items() if k not in exclude_keys}

        # 提取影响响应的关键 headers
        if "headers" in request_data:
            cache_relevant_headers = self._extract_cache_relevant_headers(request_data["headers"])
            if cache_relevant_headers:
                request_kwargs["_headers"] = cache_relevant_headers
        try:
            return generate_cache_key(
                url=self.url,
                method=method,
                request_kwargs=request_kwargs,
                user_identifier=self._user_identifier,
            )
        except Exception as e:
            logger.error(f"Failed to generate cache key: {e}")
            return None

    def _process_single_request(self, request_data: dict, is_async: bool = False) -> Any:
        """处理带缓存的单个请求"""

        if not self.enable_cache:
            return self._original_request(request_data, is_async)

        # 获取缓存键
        cache_key = self._get_cache_key(request_data)
        if not cache_key:
            return self._original_request(request_data, is_async)
        try:
            # 尝试获取缓存
            cached = self.cache_backend.get(cache_key)
            if cached is not None:
                return cached
        except Exception as e:
            logger.error(f"Failed to get cache: {e}")

        # 缓存未命中，执行请求
        logger.debug(f"Cache MISS for {request_data.get('endpoint')}")
        result = self._original_request(request_data, is_async)

        if self._should_cache_response(result):
            try:
                self.cache_backend.set(cache_key, result, expire=self._cache_expire)
            except Exception as e:
                logger.error(f"Failed to cache response: {e}")

        return result

    def _cached_request(self, request_data: dict | list | None = None, is_async: bool = False) -> Any:
        """带缓存的请求处理"""
        # 处理批量请求
        if isinstance(request_data, list):
            return self._process_batch_requests(request_data, is_async)

        # 处理单个请求
        return self._process_single_request(request_data, is_async)

    def _process_batch_requests(self, request_list: list[dict], is_async: bool = False) -> list[Any]:
        """
        批量请求的缓存处理

        执行流程:
            1. 遍历请求列表，检查每个请求的缓存状态
            2. 缓存命中的直接记录结果
            3. 缓存未命中的收集起来，调用 _original_request 执行（复用 BaseClient 的异步执行器）
            4. 对执行结果逐个进行缓存
            5. 合并结果并保持原始顺序
        """
        results: list[Any] = []
        miss_cache_requests: list[dict] = []

        # 步骤1: 检查缓存状态
        for request_data in request_list:
            cache_key = self._get_cache_key(request_data)
            if cache_key is None:
                miss_cache_requests.append(request_data)
                continue

            try:
                # 尝试获取缓存
                cached = self.cache_backend.get(cache_key)
            except Exception as e:
                logger.error(f"Failed to get cache: {e}")
                cached = None

            if cached is None:
                miss_cache_requests.append(request_data)
                continue

            results.append(cached)

        # 步骤2: 对未命中的请求调用原始方法执行（复用 BaseClient 的异步执行器）
        if miss_cache_requests:
            executed_results = self._original_request(miss_cache_requests, is_async)

            # 步骤3: 缓存结果并填充到对应位置
            for result in executed_results:
                if not isinstance(result, dict):
                    cache_key = None
                else:
                    # cache_key 从Result中获取
                    cache_key = result.pop("cache_key", None)

                results.append(result)

                if cache_key and self._should_cache_response(result):
                    try:
                        self.cache_backend.set(cache_key, result, expire=self._cache_expire)
                    except Exception as e:
                        logger.error(f"Failed to cache response: {e}")

        return results

    def _refresh_requests(self, executed_results):
        """
        刷新请求的缓存处理
        """
        if not isinstance(executed_results, list):
            executed_results = [executed_results]

        for result in executed_results:
            if not isinstance(result, dict):
                continue
            cache_key = result.pop("cache_key", None)
            if cache_key and self._should_cache_response(result):
                try:
                    self.cache_backend.set(cache_key, result, expire=self._cache_expire)
                except Exception as e:
                    logger.error(f"Failed to refresh cache: {e}")

    def _uncached_request(
        self,
        mode: str,  # 'cacheless' 或 'refresh'
        request_data: dict | list | None = None,
        is_async: bool = False,
    ) -> Any:
        """绕过缓存的请求处理"""
        if mode == "cacheless":
            return self._original_request(request_data, is_async)

        if mode == "refresh":
            result = self._original_request(request_data, is_async)
            return self._refresh_requests(result)

        logger.error(f"Invalid cache mode: {mode}")
        return self._original_request(request_data, is_async)

    def clear_cache(self, pattern: str | None = None) -> None:
        """清除缓存，支持模式匹配"""
        if not self.cache_backend:
            return

        try:
            # Redis 支持模式删除，使用 SCAN 代替 KEYS 避免阻塞
            if isinstance(self.cache_backend, RedisCacheBackend) and pattern:
                cursor = 0
                while True:
                    cursor, keys = self.cache_backend.client.scan(cursor, match=pattern, count=100)
                    if keys:
                        self.cache_backend.client.delete(*keys)
                    if cursor == 0:
                        break
                logger.info(f"Cleared cache keys matching: {pattern}")
            else:
                self.cache_backend.clear()
                logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Cache clear failed: {e}")
