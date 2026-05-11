"""分布式锁通用模块。

零业务耦合的 Redis 分布式锁实现，通过依赖注入方式支持任意符合
RedisClientProtocol 的客户端（redis-py、自定义 Cache、Mock 等）。

公共 API：
    - BaseLock:             分布式锁抽象基类
    - RedisLock:            基于 SET NX 的单键互斥锁
    - MultiRedisLock:       基于 Pipeline 的批量锁
    - RedisClientProtocol:  Redis 客户端接口契约
    - PipelineProtocol:     Redis Pipeline 接口契约
    - DEFAULT_TTL:          默认锁过期时间（秒）

基本用法：
    >>> from distributed_lock import RedisLock
    >>> import redis
    >>> client = redis.StrictRedis()
    >>> with RedisLock("my-resource", client=client, ttl=30) as lock:
    ...     do_something()
"""

from .base import BaseLock
from .constants import DEFAULT_TTL
from .multi_redis_lock import MultiRedisLock
from .protocols import PipelineProtocol, RedisClientProtocol
from .redis_lock import RedisLock

__all__ = [
    "DEFAULT_TTL",
    "BaseLock",
    "MultiRedisLock",
    "PipelineProtocol",
    "RedisClientProtocol",
    "RedisLock",
]

__version__ = "0.1.0"
