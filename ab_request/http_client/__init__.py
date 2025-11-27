"""
AB Request HTTP Client 模块

提供功能强大、易于扩展的 HTTP 客户端框架

主要组件:
    - BaseClient: 客户端基类
    - 异常类: APIClientError 及其子类
    - 解析器: JSONResponseParser, ContentResponseParser 等
    - 格式化器: DefaultResponseFormatter
    - 执行器: ThreadPoolAsyncExecutor
    - 缓存: CacheClientMixin, InMemoryCacheBackend, RedisCacheBackend

使用示例:
    >>> from ab_request.http_client import BaseClient, JSONResponseParser
    >>>
    >>> class MyAPIClient(BaseClient):
    ...     base_url = "https://api.example.com"
    ...     response_parser_class = JSONResponseParser
    >>>
    >>> client = MyAPIClient()
    >>> result = client.request({"endpoint": "/users", "params": {"page": 1}})
"""

# 核心客户端
from ab_request.http_client.client import BaseClient

# 异常类
from ab_request.http_client.exceptions import (
    APIClientError,
    APIClientHTTPError,
    APIClientNetworkError,
    APIClientTimeoutError,
    APIClientValidationError,
)

# 响应解析器
from ab_request.http_client.parser import (
    BaseResponseParser,
    ContentResponseParser,
    FileWriteResponseParser,
    JSONResponseParser,
    RawResponseParser,
)

# 响应格式化器
from ab_request.http_client.formatter import (
    BaseResponseFormatter,
    DefaultResponseFormatter,
)

# 异步执行器
from ab_request.http_client.async_executor import (
    BaseAsyncExecutor,
    ThreadPoolAsyncExecutor,
)

# 缓存支持
from ab_request.http_client.cache import (
    BaseCacheBackend,
    CacheClientMixin,
    InMemoryCacheBackend,
    RedisCacheBackend,
)

# 常量配置
from ab_request.http_client.constants import (
    CACHEABLE_METHODS,
    DEFAULT_CACHE_EXPIRE,
    DEFAULT_MAX_WORKERS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    HTTP_METHOD_DELETE,
    HTTP_METHOD_GET,
    HTTP_METHOD_HEAD,
    HTTP_METHOD_OPTIONS,
    HTTP_METHOD_PATCH,
    HTTP_METHOD_POST,
    HTTP_METHOD_PUT,
    HTTP_METHOD_TRACE,
)

__all__ = [
    # 核心类
    "BaseClient",
    # 异常
    "APIClientError",
    "APIClientHTTPError",
    "APIClientNetworkError",
    "APIClientTimeoutError",
    "APIClientValidationError",
    # 解析器
    "BaseResponseParser",
    "JSONResponseParser",
    "ContentResponseParser",
    "RawResponseParser",
    "FileWriteResponseParser",
    # 格式化器
    "BaseResponseFormatter",
    "DefaultResponseFormatter",
    # 执行器
    "BaseAsyncExecutor",
    "ThreadPoolAsyncExecutor",
    # 缓存
    "BaseCacheBackend",
    "InMemoryCacheBackend",
    "RedisCacheBackend",
    "CacheClientMixin",
    # 常量
    "DEFAULT_TIMEOUT",
    "DEFAULT_RETRIES",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_CACHE_EXPIRE",
    "CACHEABLE_METHODS",
    "HTTP_METHOD_GET",
    "HTTP_METHOD_POST",
    "HTTP_METHOD_PUT",
    "HTTP_METHOD_DELETE",
    "HTTP_METHOD_PATCH",
    "HTTP_METHOD_HEAD",
    "HTTP_METHOD_OPTIONS",
    "HTTP_METHOD_TRACE",
]

__version__ = "1.0.0"
__author__ = "HACK-WU"
