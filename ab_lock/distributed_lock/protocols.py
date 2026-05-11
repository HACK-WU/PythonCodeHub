"""Redis 客户端协议定义。

通过 typing.Protocol 显式声明分布式锁所依赖的客户端接口契约，
实现使用方（任意 Redis 客户端实现）与锁逻辑之间的解耦。

任何符合本协议的对象均可作为 client 注入到 RedisLock / MultiRedisLock 中，
例如：redis-py 的 StrictRedis、自定义的 Cache 包装类、单元测试中的 MagicMock。
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PipelineProtocol(Protocol):
    """Redis Pipeline 接口契约。

    分布式锁仅使用 Pipeline 的 set 方法和 execute 方法，
    用于批量发送 SET NX 命令以减少网络往返。
    """

    def set(self, name: str, value: Any, ex: int | None = None, nx: bool = False) -> Any:
        """向 Pipeline 中追加一个 SET 命令（不立即执行）。"""
        ...

    def execute(self) -> list:
        """执行 Pipeline 中累积的所有命令，返回结果列表。"""
        ...


@runtime_checkable
class RedisClientProtocol(Protocol):
    """Redis 客户端接口契约。

    分布式锁所依赖的 Redis 客户端方法集合。任何客户端只要实现以下方法，
    即可作为 client 参数注入。
    """

    def set(self, name: str, value: Any, ex: int | None = None, nx: bool = False) -> Any:
        """SET 命令，支持 ex（过期秒数）与 nx（仅当不存在时设置）。"""
        ...

    def get(self, name: str) -> Any:
        """GET 命令，返回 key 对应的值，不存在返回 None。"""
        ...

    def delete(self, *names: str) -> int:
        """DEL 命令，删除一个或多个 key，返回实际删除数量。"""
        ...

    def mget(self, keys: list) -> list:
        """MGET 命令，批量读取多个 key 的值，返回与输入顺序一致的列表。"""
        ...

    def pipeline(self, transaction: bool = True) -> PipelineProtocol:
        """创建 Pipeline 对象用于批量执行命令；transaction=False 时为非事务模式。"""
        ...
