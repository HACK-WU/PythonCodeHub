"""
ab_cache.using_cache - 函数级缓存装饰器框架

从 drf_resource.resources.cache 抽取的缓存核心实现，
完全自包含，不依赖 Django / drf_resource / ab_hash 等外部包。

核心组件:
    - CacheTypeItem: 缓存类型定义
    - BaseCacheType: 缓存类型基类
    - DefaultCacheType: 默认缓存类型
    - BaseUsingCache: 使用缓存基类
    - DefaultUsingCache: 默认使用缓存实现
    - using_cache: 缓存装饰器（DefaultUsingCache 别名）
    - CacheResource: 支持缓存的 Resource Mixin
    - configure: 全局配置缓存后端和用户信息提供者
    - BaseCacheBackend: 缓存后端抽象基类
    - DictCacheBackend: 基于内存字典的缓存后端

使用示例:
    from ab_cache.using_cache import configure, using_cache, CacheTypeItem
    from ab_cache.using_cache.backends import DictCacheBackend

    configure(
        cache_backend=DictCacheBackend(),
        user_info_provider=lambda: "current_user",
    )

    @using_cache(cache_type=CacheTypeItem(key="data", timeout=60))
    def get_data():
        return {"key": "value"}
"""

from ab_cache.using_cache.backends import BaseCacheBackend, DictCacheBackend
from ab_cache.using_cache.cache import (
    BaseCacheType,
    BaseUsingCache,
    CacheResource,
    CacheTypeItem,
    DefaultCacheType,
    DefaultUsingCache,
    configure,
    using_cache,
)

__all__ = [
    "CacheTypeItem",
    "BaseCacheType",
    "DefaultCacheType",
    "BaseUsingCache",
    "DefaultUsingCache",
    "using_cache",
    "CacheResource",
    "configure",
    "BaseCacheBackend",
    "DictCacheBackend",
]
