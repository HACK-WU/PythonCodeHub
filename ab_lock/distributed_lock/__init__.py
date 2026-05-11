"""分布式锁通用模块。

零业务耦合的 Redis 分布式锁实现，通过依赖注入方式支持任意符合
RedisClientProtocol / AsyncRedisClientProtocol 的客户端
（redis-py、redis.asyncio、自定义 Cache、Mock 等）。

公共 API：
    - BaseLock:                  分布式锁抽象基类
    - RedisLock:                 基于 SET NX 的单键互斥锁（支持 watchdog）
    - MultiRedisLock:            基于 Pipeline 的批量锁
    - ReentrantRedisLock:        可重入分布式锁（同实例可多次 acquire）
    - AsyncRedisLock:            异步分布式锁（asyncio + redis.asyncio，支持 watchdog）
    - Redlock:                   基于多节点多数派的高可用分布式锁
    - RWLock:                    分布式读写锁（支持升级 / 降级）
    - SyncWatchdog:              同步看门狗（后台线程自动续期）
    - AsyncWatchdog:             异步看门狗（asyncio.Task 自动续期）
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

看门狗（长事务自动续期）：
    >>> with RedisLock("res", client=client, ttl=30, enable_watchdog=True):
    ...     long_running_business()   # 业务超过 30s 也不会丢锁

Redlock（高可用）：
    >>> from ab_lock.distributed_lock import Redlock
    >>> with Redlock("res", clients=[c1, c2, c3], ttl=10):
    ...     critical_section()

读写锁（降级 / 升级）：
    >>> from ab_lock.distributed_lock import RWLock
    >>> rw = RWLock("res", client=client)
    >>> with rw.write_lock():
    ...     write_data()
    ...     rw.downgrade_to_read()   # 无锁空窗零风险
    ...     read_data()

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
from .redlock import Redlock
from .reentrant_lock import ReentrantRedisLock
from .rw_lock import RWLock
from .watchdog import AsyncWatchdog, SyncWatchdog

__all__ = [
    "DEFAULT_TTL",
    "AsyncRedisClientProtocol",
    "AsyncRedisLock",
    "AsyncWatchdog",
    "BaseLock",
    "MultiRedisLock",
    "PipelineProtocol",
    "RWLock",
    "RedisClientProtocol",
    "RedisLock",
    "Redlock",
    "ReentrantRedisLock",
    "SyncWatchdog",
]

__version__ = "0.3.0"
