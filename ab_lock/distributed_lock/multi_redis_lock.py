"""基于 Redis Pipeline 的批量分布式锁。"""

import uuid

from .constants import DEFAULT_TTL
from .protocols import RedisClientProtocol


class MultiRedisLock:
    """基于 Redis Pipeline 的批量分布式锁。

    适用场景：需要同时对多个资源加锁，通过 Pipeline 批量执行 SET NX 减少网络
    往返，提升大批量加锁的性能。

    特性：
    - 通过依赖注入接受任意符合 RedisClientProtocol 的客户端
    - 所有 key 共享同一个 token，简化 token 管理
    - 加锁为"尽力而为"模式：部分 key 加锁失败不影响其他 key
    - 释放时通过 MGET 批量校验 token，只删除本实例持有的 key
    """

    def __init__(self, keys: list[str], client: RedisClientProtocol, ttl: int | None = None):
        """初始化批量 Redis 锁。

        参数:
            keys:   需要加锁的 Redis key 列表
            client: 满足 RedisClientProtocol 协议的 Redis 客户端实例（必填）
            ttl:    每个锁的过期时间（秒），默认 60 秒

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        if client is None:
            raise ValueError("MultiRedisLock requires a non-None 'client' argument")
        self.keys = keys
        self.client = client
        self.ttl = ttl or DEFAULT_TTL
        # 所有 key 共享同一个 token，标识本次批量锁的持有者
        self._token = uuid.uuid4().hex
        # 实际加锁成功的 key 集合，用于后续释放
        self._lock_success_keys: set[str] = set()

    def acquire(self) -> set[str]:
        """批量尝试获取锁（非阻塞）。

        返回值:
            成功获取锁的 key 集合（set）；keys 为空时返回空列表

        执行步骤：
        1. 对 keys 去重，避免重复加锁
        2. 通过 Pipeline 批量执行 SET NX，减少网络往返
        3. 收集加锁成功的 key 存入 _lock_success_keys
        """
        if not self.keys:
            return set()

        # 去重，避免对同一 key 重复加锁
        keys = list(set(self.keys))

        # 非事务 Pipeline 批量发送 SET NX
        pipeline = self.client.pipeline(transaction=False)
        for key in keys:
            pipeline.set(key, self._token, ex=self.ttl, nx=True)

        results = pipeline.execute()

        for index, locked in enumerate(results):
            if locked:
                self._lock_success_keys.add(keys[index])

        return self._lock_success_keys

    def release(self):
        """批量释放本实例持有的锁。

        返回值:
            实际被删除的 key 列表；若无成功加锁的 key 则返回 None

        执行步骤：
        1. 若无成功加锁的 key，直接返回
        2. 通过 MGET 批量读取各 key 的当前 token 值
        3. 比对 token，仅删除 token 与本实例一致的 key，防止误释放他人的锁
        """
        if not self._lock_success_keys:
            return

        lock_success_keys = list(self._lock_success_keys)

        results = self.client.mget(lock_success_keys)

        keys_to_delete = []
        for index, token in enumerate(results):
            if token == self._token:
                keys_to_delete.append(lock_success_keys[index])

        if keys_to_delete:
            self.client.delete(*keys_to_delete)
        return keys_to_delete

    def is_locked(self, key: str) -> bool:
        """查询指定 key 是否已被本实例成功加锁。

        参数:
            key: 待查询的 Redis key

        返回值:
            True  — 该 key 已被本实例持有
            False — 该 key 未被本实例持有
        """
        return key in self._lock_success_keys
