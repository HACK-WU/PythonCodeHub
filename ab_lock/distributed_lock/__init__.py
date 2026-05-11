"""分布式锁通用模块。

零业务耦合的 Redis 分布式锁实现，通过依赖注入方式支持任意符合
RedisClientProtocol / AsyncRedisClientProtocol 的客户端
（redis-py、redis.asyncio、自定义 Cache、Mock 等）。

公共 API：
    - BaseLock:                  分布式锁抽象基类
    - RedisLock:                 基于 SET NX 的单键互斥锁
    - MultiRedisLock:            基于 Pipeline 的批量锁
    - ReentrantRedisLock:        可重入分布式锁（同实例可多次 acquire）
    - AsyncRedisLock:            异步分布式锁（asyncio + redis.asyncio）
    - RedisClientProtocol:       Redis 客户端接口契约（同步）
    - AsyncRedisClientProtocol:  Redis 客户端接口契约（异步）
    - PipelineProtocol:          Redis Pipeline 接口契约
    - DEFAULT_TTL:               默认锁过期时间（秒）

基本用法：
    >>> from ab_lock.distributed_lock import RedisLock
    >>> import redis
    >>> client = redis.StrictRedis()
    >>> with RedisLock("my-resource", client=client, ttl=30) as lock:
    ...     do_something()

异步用法：
    >>> from ab_lock.distributed_lock import AsyncRedisLock
    >>> import redis.asyncio as aioredis
    >>> client = aioredis.Redis()
    >>> async with AsyncRedisLock("my-resource", client=client) as lock:
    ...     await do_something_async()
"""

from .async_redis_lock import AsyncRedisLock
from .base import BaseLock
from .constants import DEFAULT_TTL
from .multi_redis_lock import MultiRedisLock
from .protocols import (
    AsyncRedisClientProtocol,
    PipelineProtocol,
    RedisClientProtocol,
)
from .redis_lock import RedisLock
from .reentrant_lock import ReentrantRedisLock

__all__ = [
    "DEFAULT_TTL",
    "AsyncRedisClientProtocol",
    "AsyncRedisLock",
    "BaseLock",
    "MultiRedisLock",
    "PipelineProtocol",
    "RedisClientProtocol",
    "RedisLock",
    "ReentrantRedisLock",
]

__version__ = "0.2.0"
