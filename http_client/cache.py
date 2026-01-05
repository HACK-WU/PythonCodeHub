"""缓存管理模块

提供多种缓存后端实现（内存缓存、Redis 缓存）和缓存客户端混入类
支持灵活的缓存策略和用户级缓存隔离
"""

from __future__ import annotations

import abc
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any
import base64

import redis

from http_client.constants import (
    CACHEABLE_METHODS,
    DEFAULT_CACHE_EXPIRE,
    DEFAULT_CACHE_MAXSIZE,
    REDIS_DEFAULT_DB,
    REDIS_DEFAULT_HOST,
    REDIS_DEFAULT_PORT,
    REDIS_MAX_CONNECTIONS,
)
from http_client.client import BaseClient

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

            # 在 get 操作时也触发惰性清理，清理部分过期项
            self._lazy_cleanup()

            return value

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        with self.lock:
            expire_at = time.time() + expire if expire else None
            self.cache[key] = (value, expire_at)
            self.cache.move_to_end(key)

            # LRU 淘汰：超过容量时移除最旧的项
            while len(self.cache) > self.maxsize:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                logger.debug(f"InMemoryCache evicted oldest key: {oldest_key}")

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

    def __len__(self) -> int:
        """返回当前缓存条目数"""
        with self.lock:
            return len(self.cache)

    def _lazy_cleanup(self) -> None:
        """惰性清理过期缓存项，避免内存泄漏"""
        if len(self.cache) == 0:
            return

        current_time = time.time()
        # 批量清理过期项，最多清理 10% 的缓存或 10 个项目
        max_cleanup = max(1, min(10, len(self.cache) // 10))
        cleanup_count = 0

        # 从最旧的项开始检查
        keys_to_delete = []
        for key, (_, expire_at) in self.cache.items():
            if cleanup_count >= max_cleanup:
                break
            if expire_at is not None and current_time >= expire_at:
                keys_to_delete.append(key)
                cleanup_count += 1

        for key in keys_to_delete:
            del self.cache[key]

        if keys_to_delete:
            logger.debug(f"InMemoryCache lazy cleanup removed {len(keys_to_delete)} expired items")


class RedisCacheBackend(BaseCacheBackend):
    """
    基于 Redis 的缓存后端

    使用 Redis 作为分布式缓存存储，支持多进程/多服务器共享缓存
    自动处理多种类型的序列化和连接池管理

    参数:
        host: Redis 服务器地址
        port: Redis 服务器端口
        db: Redis 数据库编号
        password: Redis 密码（可选）
        key_prefix: 缓存键前缀，用于隔离不同应用的缓存数据
        **kwargs: 其他 Redis 连接参数
    """

    # 类型标记前缀，用于区分不同类型的数据
    _JSON_MARKER = "__JSON__:"
    _BYTES_MARKER = "__BYTES__:"
    _NUMBER_MARKER = "__NUMBER__:"
    _BOOL_MARKER = "__BOOL__:"

    def __init__(
        self,
        host=REDIS_DEFAULT_HOST,
        port=REDIS_DEFAULT_PORT,
        db=REDIS_DEFAULT_DB,
        password=None,
        key_prefix: str = "cache_backend",
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
        self.key_prefix = key_prefix.strip() if key_prefix else ""

    def _make_key(self, key: str) -> str:
        """生成带前缀的完整键名"""
        if self.key_prefix:
            return f"{self.key_prefix}:{key}"
        return key

    def get(self, key: str) -> Any | None:
        """获取缓存值，自动应用 key_prefix"""
        full_key = self._make_key(key)
        try:
            value = self.client.get(full_key)
            if value is not None:
                logger.debug(f"RedisCache hit for key: {key} (full_key: {full_key})")
                # redis-py 返回 bytes，先解码为字符串
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value

                # 根据标记反序列化
                if value_str.startswith(self._JSON_MARKER):
                    json_data = value_str[len(self._JSON_MARKER) :]
                    return json.loads(json_data)
                elif value_str.startswith(self._BYTES_MARKER):
                    base64_data = value_str[len(self._BYTES_MARKER) :]
                    return base64.b64decode(base64_data)
                elif value_str.startswith(self._NUMBER_MARKER):
                    number_data = value_str[len(self._NUMBER_MARKER) :]
                    return json.loads(number_data)
                elif value_str.startswith(self._BOOL_MARKER):
                    bool_data = value_str[len(self._BOOL_MARKER) :]
                    return json.loads(bool_data)
                # 普通字符串
                return value_str
            logger.debug(f"RedisCache miss for key: {key} (full_key: {full_key})")
            return None
        except redis.RedisError:
            logger.exception(f"Redis error getting key '{key}' (full_key: {full_key})")
            return None
        except Exception:
            logger.exception(f"Error deserializing value for key '{key}'")
            return None

    def set(self, key: str, value: Any, expire: int | None = None) -> None:
        """设置缓存值，自动应用 key_prefix"""
        full_key = self._make_key(key)
        try:
            # 根据类型选择序列化策略
            if isinstance(value, bool):
                # bool 必须在 int 之前判断，因为 bool 是 int 的子类
                serialized = self._BOOL_MARKER + json.dumps(value)
            elif isinstance(value, (dict, list, tuple)):
                serialized = self._JSON_MARKER + json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bytes):
                serialized = self._BYTES_MARKER + base64.b64encode(value).decode("ascii")
            elif isinstance(value, (int, float)):
                serialized = self._NUMBER_MARKER + json.dumps(value)
            else:
                # 普通字符串或其他类型，直接转字符串
                serialized = str(value)

            if expire:
                self.client.setex(full_key, expire, serialized)
            else:
                self.client.set(full_key, serialized)

            logger.debug(f"RedisCache set for key: {key} (full_key: {full_key}), expire: {expire}")
        except (TypeError, redis.RedisError):
            logger.exception(f"Redis error setting key '{key}' (full_key: {full_key})")

    def delete(self, key: str) -> None:
        """删除缓存项，自动应用 key_prefix"""
        full_key = self._make_key(key)
        try:
            self.client.delete(full_key)
            logger.debug(f"RedisCache deleted key: {key} (full_key: {full_key})")
        except redis.RedisError:
            logger.exception(f"Redis error deleting key '{key}' (full_key: {full_key})")

    def clear(self) -> None:
        """清空缓存，仅删除带有 key_prefix 前缀的键，避免影响其他数据"""
        try:
            if self.key_prefix:
                # 使用 SCAN 迭代删除匹配前缀的键，避免阻塞
                pattern = f"{self.key_prefix}:*"
                cursor = 0
                deleted_count = 0
                while True:
                    cursor, keys = self.client.scan(cursor, match=pattern, count=100)
                    if keys:
                        self.client.delete(*keys)
                        deleted_count += len(keys)
                    if cursor == 0:
                        break
                logger.debug(f"RedisCache cleared {deleted_count} keys with prefix '{self.key_prefix}'")
            else:
                # 无前缀时清空整个数据库（谨慎使用）
                self.client.flushdb()
                logger.warning("RedisCache cleared entire DB (no key_prefix set)")
        except redis.RedisError:
            logger.exception("Redis error clearing cache")

    def __len__(self) -> int:
        """返回当前缓存条目数（仅统计带前缀的键）"""
        try:
            if self.key_prefix:
                # 使用 SCAN 统计匹配的键数量
                pattern = f"{self.key_prefix}:*"
                count = 0
                cursor = 0
                while True:
                    cursor, keys = self.client.scan(cursor, match=pattern, count=100)
                    count += len(keys)
                    if cursor == 0:
                        break
                return count
            return self.client.dbsize()
        except redis.RedisError:
            logger.exception("Redis error getting cache size")
            return 0

    def ping(self) -> bool:
        """检查 Redis 连接是否正常"""
        try:
            return self.client.ping()
        except redis.RedisError:
            logger.exception("Redis connection check failed")
            return False

    def close(self) -> None:
        """关闭 Redis 连接池，释放资源"""
        try:
            self.pool.disconnect()
            logger.debug("Redis connection pool closed")
        except Exception:
            logger.exception("Failed to close Redis connection pool")

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出，自动关闭连接"""
        self.close()
        return False


def generate_cache_key(
    url: str, method: str, request_data: dict[str, Any], headers: dict, user_identifier: str | None = None
) -> str:
    """生成稳定的缓存键"""
    # 创建请求信息的精简表示
    key_data = {"url": url, "method": method.upper(), "headers": headers, "request_data": request_data}

    # 包含用户标识
    if user_identifier:
        key_data["user"] = user_identifier

    # 稳定序列化
    key_str = json.dumps(key_data, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)

    # 使用更高效的哈希算法
    return hashlib.blake2b(key_str.encode("utf-8"), digest_size=16).hexdigest()


class CacheClient(BaseClient):
    """
    缓存客户端

    为 API 客户端提供透明的缓存功能，支持：
    - 自动缓存 GET/HEAD 请求
    - 用户级缓存隔离
    - 灵活的缓存后端（内存/Redis）
    - 缓存刷新和清除
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

        # 规范化缓存键前缀
        self.cache_key_prefix = self._normalize_cache_key_prefix(self.cache_key_prefix)
        # 初始化缓存后端
        self.cache_backend = self._init_cache_backend()

        if self.is_user_specific is True and user_identifier is None:
            raise ValueError("User identifier is required for user-specific caching")

        self._original_request = None
        # 包装请求方法
        self._wrap_request_methods()

    def _init_cache_backend(self) -> BaseCacheBackend:
        """初始化缓存后端"""
        backend_kwargs = getattr(self, "cache_backend_kwargs", {})
        try:
            return self.cache_backend_class(**backend_kwargs)
        except Exception as e:
            logger.exception(f"Failed to initialize cache backend: {e}")
            # 回退到内存缓存
            return InMemoryCacheBackend()

    def _normalize_cache_key_prefix(self, prefix: Any) -> str:
        """规范化缓存键前缀"""
        if not prefix:
            return ""

        try:
            # 如果是可调用对象，先执行获取结果
            if callable(prefix):
                prefix = prefix()

            # 转换为字符串
            if not isinstance(prefix, str):
                prefix = str(prefix)

            return prefix.strip()

        except Exception as e:
            logger.error(f"Failed to normalize cache key prefix: {e}")
            return ""

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
                logger.exception(f"Custom should_cache_response_func failed, using default logic: {e}")

        # 使用默认逻辑
        return self.default_cache_response_check(result)

    def default_cache_response_check(self, result: Any, *args, **kwargs) -> bool:
        """默认的响应缓存判断逻辑（子类可重写）"""

        # 默认缓存所有响应
        return True

    def _extract_cache_relevant_headers(self, headers: dict) -> dict:
        """提取影响缓存的关键 headers（子类可重写）"""
        relevant_keys = {"Accept-Language", "Accept", "Content-Type"}
        return {k: v for k, v in headers.items() if k in relevant_keys}

    def _get_cache_key(self, request_data: dict, **kwargs) -> str | None:
        """为请求生成缓存键

        参数:
            request_data: 请求配置字典,包含 method、endpoint、params、data、json、headers 等字段

        返回:
            缓存键字符串,如果不应该缓存则返回 None
        """
        if not isinstance(request_data, dict):
            return None

        # 从请求配置中获取 method,如果未指定则使用类默认方法
        method = self._class_default_method

        if method not in self.cacheable_methods:
            return None
        cache_relevant_headers = self._extract_cache_relevant_headers(self.session.headers)

        try:
            cache_key = generate_cache_key(
                url=self.url,
                method=method,
                request_data=cache_relevant_headers,
                headers=request_data,
                user_identifier=self._user_identifier,
            )
            if self.cache_key_prefix:
                return f"{self.cache_key_prefix}_{cache_key}"
            return cache_key
        except Exception as e:
            logger.exception(f"Failed to generate cache key,{e}")
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
            logger.exception(f"Failed to get cache: {e}")

        # 缓存未命中，执行请求
        logger.debug(f"Cache MISS for {request_data.get('endpoint')}")
        result = self._original_request(request_data, is_async)

        if self._should_cache_response(result):
            try:
                self.cache_backend.set(cache_key, result, expire=self._cache_expire)
            except Exception as e:
                logger.exception(f"Failed to cache response: {e}")

        return result

    def _cached_request(self, request_data: dict | list | None = None, is_async: bool = False) -> Any:
        """带缓存的请求处理"""
        # 处理批量请求
        if isinstance(request_data, list):
            return self._process_batch_requests(request_data, is_async)

        # 处理单个请求，None转换为空字典
        if request_data is None:
            request_data = {}
        return self._process_single_request(request_data, is_async)

    def _process_batch_requests(self, request_list: list[dict], is_async: bool = False) -> list[Any]:
        """
        批量请求的缓存处理

        执行流程:
            1. 遍历请求列表，检查每个请求的缓存状态，记录索引位置
            2. 缓存命中的直接存储到对应索引位置
            3. 缓存未命中的收集起来，调用 _original_request 执行（复用 BaseClient 的异步执行器）
            4. 对执行结果逐个进行缓存，并填充到对应索引位置
            5. 返回按原始顺序排列的结果列表
        """
        # 初始化结果列表，长度与请求列表一致，使用 None 占位
        results: list[Any] = [None] * len(request_list)
        miss_cache_requests: list[tuple[int, dict]] = []  # (原始索引, 请求数据)

        # 步骤1: 检查缓存状态，记录索引位置
        for index, request_data in enumerate(request_list):
            cache_key = self._get_cache_key(request_data)
            if cache_key is None:
                miss_cache_requests.append((index, request_data))
                continue

            try:
                # 尝试获取缓存
                cached = self.cache_backend.get(cache_key)
            except Exception as e:
                logger.exception(f"Failed to get cache,{e}")
                cached = None

            if cached is None:
                miss_cache_requests.append((index, request_data))
                continue

            # 缓存命中，直接存储到对应索引位置
            results[index] = cached

        # 步骤2: 对未命中的请求调用原始方法执行（复用 BaseClient 的异步执行器）
        if miss_cache_requests:
            # 提取请求数据列表
            miss_requests_data = [req_data for _, req_data in miss_cache_requests]
            executed_results = self._original_request(miss_requests_data, is_async)

            # 步骤3: 缓存结果并填充到对应索引位置
            for (original_index, _), result in zip(miss_cache_requests, executed_results):
                if not isinstance(result, dict):
                    cache_key = None
                else:
                    # cache_key 从Result中获取
                    cache_key = result.pop("cache_key", None)

                # 填充到原始索引位置
                results[original_index] = result

                if cache_key and self._should_cache_response(result):
                    try:
                        self.cache_backend.set(cache_key, result, expire=self._cache_expire)
                    except Exception as e:
                        logger.exception(f"Failed to cache response,{e}")

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
                    cache_key = str(cache_key)
                    self.cache_backend.set(cache_key, result, expire=self._cache_expire)
                except Exception as e:
                    logger.exception(f"Failed to refresh cache: {e}")

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
            # 处理None参数
            if request_data is None:
                request_data = {}

            # 执行请求
            result = self._original_request(request_data, is_async)
            self._refresh_requests(result)
            return result

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
            logger.exception(f"Cache clear failed: {e}")
