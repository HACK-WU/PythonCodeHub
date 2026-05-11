"""基于 Redis SET NX 的单键分布式互斥锁。"""

import time
import uuid

from .base import BaseLock
from .protocols import RedisClientProtocol


class RedisLock(BaseLock):
    """基于 Redis SET NX 指令实现的单键分布式互斥锁。

    特性：
    - 通过依赖注入接受任意符合 RedisClientProtocol 的客户端
    - 使用唯一 token（UUID）标识锁持有者，防止误释放他人持有的锁
    - 支持短暂等待重试（_wait 参数），适用于轻度竞争场景
    - 锁过期时间由 ttl 控制，避免持锁方崩溃导致死锁
    """

    def __init__(self, name: str, client: RedisClientProtocol, ttl: int | None = None):
        """初始化 Redis 单键锁。

        参数:
            name:   锁的 Redis key 名称
            client: 满足 RedisClientProtocol 协议的 Redis 客户端实例（必填）
            ttl:    锁过期时间（秒），默认 60 秒

        异常:
            ValueError: 当 client 为 None 时抛出
        """
        super().__init__(name, ttl)
        if client is None:
            raise ValueError("RedisLock requires a non-None 'client' argument")
        self.client = client
        # 当前实例持有的锁令牌；None 表示未持锁
        self._token: str | None = None

    def acquire(self, _wait: float = 0.001) -> bool:
        """尝试获取 Redis 分布式锁。

        参数:
            _wait: 最长等待时间（秒），默认 0.001 秒；超时后返回 False

        返回值:
            True  — 成功获取锁
            False — 在等待时间内未能获取锁

        执行步骤：
        1. 生成唯一 token，用于标识当前锁持有者
        2. 计算等待截止时间
        3. 循环调用 SET NX 尝试加锁：
           - 成功则保存 token 并返回 True
           - 失败且未超时则短暂 sleep 后重试
           - 超时则返回 False
        """
        token = uuid.uuid4().hex
        wait_until = time.time() + _wait
        while not self.client.set(self.name, token, ex=self.ttl, nx=True):
            if time.time() < wait_until:
                time.sleep(0.01)
            else:
                return False

        self._token = token
        return True

    def release(self):
        """释放 Redis 分布式锁。

        返回值:
            True/非零  — 成功删除锁 key
            False      — 未持锁或 token 不匹配（锁已被他人持有或已过期），不执行删除

        执行步骤：
        1. 检查本实例是否持有 token，未持锁直接返回 False
        2. 从 Redis 读取当前锁的 token 值
        3. 比对 token，仅当一致时才删除 key，防止误释放他人的锁
        """
        if not self._token:
            return False
        token = self.client.get(self.name)
        if not token or token != self._token:
            return False
        return self.client.delete(self.name)
