"""
key — Redis Key 声明式元数据管理模式

背景：
    在使用 Redis 的项目中，key 的模板、TTL、所属后端等信息通常散落在各处，
    以纯字符串硬编码的方式使用。这导致：
    - key 命名不一致，难以维护
    - TTL 和后端配置与使用处脱节，修改时容易遗漏
    - 无法集中查看所有 key 的定义和用途
    - 多环境/多集群部署时前缀管理混乱

解决方案：
    RedisKey 提供声明式的 key 元数据管理：
    - key_tpl：key 模板，支持 {placeholder} 格式化
    - ttl：过期时间（秒）
    - backend：对应的 Redis 实例/数据库标识
    - is_global：是否全局 key（跨集群共享 vs 集群隔离）
    - get_key(**kwargs)：格式化模板 + 自动添加前缀
    - expire(**kwargs)：便捷设置过期

    类型子类区分 Redis 数据结构：
    - StringKey / SetKey / ListKey / SortedSetKey
    - HashKey：额外支持 field_tpl 和 get_field()

    KeyPrefixManager 管理前缀：
    - global_prefix：全局 key 前缀
    - cluster_prefix：集群隔离 key 前缀

用法：
    from ab_redis.key import RedisKey, HashKey, KeyPrefixManager

    # 1. 创建前缀管理器
    prefix_mgr = KeyPrefixManager(
        global_prefix="myapp.ee",
        cluster_prefix="myapp.ee.cluster1",
    )

    # 2. 定义 key
    USER_CACHE = RedisKey(
        key_tpl="cache.user.{user_id}",
        ttl=3600,
        backend="default",
        is_global=True,
        label="用户信息缓存",
        prefix_manager=prefix_mgr,
    )

    DIMENSION_CACHE = HashKey(
        key_tpl="cache.dimension.{strategy_id}.{item_id}",
        field_tpl="{dimensions_md5}",
        ttl=1800,
        backend="service",
        label="维度信息缓存",
        prefix_manager=prefix_mgr,
    )

    # 3. 使用
    key = USER_CACHE.get_key(user_id=123)
    # -> "myapp.ee.cache.user.123"

    field = DIMENSION_CACHE.get_field(dimensions_md5="abc123")
    # -> "abc123"

    DIMENSION_CACHE.expire(strategy_id=1, item_id=2)

依赖：
    - redis（仅 client_factory 需要时）

参考：
    原始实现源自 bk-monitor 的 alarm_backends/core/cache/key.py。
"""

import typing


class KeyPrefixManager:
    """
    Redis Key 前缀管理器。

    管理全局前缀和集群隔离前缀，支持 is_global 标记自动选择前缀。

    Args:
        global_prefix: 全局 key 前缀（跨集群共享的 key 使用）。
        cluster_prefix: 集群隔离 key 前缀（仅当前集群可见的 key 使用）。
            为 None 时等同于 global_prefix（无集群隔离）。

    用法：
        prefix_mgr = KeyPrefixManager(
            global_prefix="myapp.ee",
            cluster_prefix="myapp.ee.cluster1",
        )
    """

    def __init__(self, global_prefix: str, cluster_prefix: str | None = None):
        self.global_prefix = global_prefix
        self.cluster_prefix = cluster_prefix or global_prefix

    def get_prefix(self, is_global: bool = False) -> str:
        """
        根据 is_global 标记返回对应前缀。

        Args:
            is_global: True 返回全局前缀，False 返回集群前缀。

        Returns:
            对应的前缀字符串。
        """
        return self.global_prefix if is_global else self.cluster_prefix


class RedisKey:
    """
    Redis Key 的元数据描述对象。

    将 key 的模板、TTL、后端、前缀等信息集中声明，
    通过 get_key() 方法生成完整的 Redis key 字符串。

    Args:
        key_tpl: key 模板，支持 {placeholder} 格式化。
            例如 "cache.user.{user_id}"
        ttl: 过期时间（秒）。
        backend: 对应的 Redis 实例/数据库标识。
            例如 "default"、"service"、"queue"
        is_global: 是否全局 key。全局 key 使用 global_prefix，
            非全局 key 使用 cluster_prefix。默认 False。
        prefix_manager: 前缀管理器。为 None 时不添加前缀。
        client_factory: Redis 客户端工厂，签名为 (backend: str) -> client。
            为 None 时 expire() 等方法不可用。
        label: key 的描述信息（可选，仅用于文档）。
        **extra: 其他自定义属性，存储为实例属性。

    用法：
        USER_CACHE = RedisKey(
            key_tpl="cache.user.{user_id}",
            ttl=3600,
            backend="default",
            prefix_manager=prefix_mgr,
        )
        key = USER_CACHE.get_key(user_id=123)
    """

    def __init__(
        self,
        key_tpl: str | None = None,
        ttl: int | None = None,
        backend: str | None = None,
        is_global: bool = False,
        prefix_manager: KeyPrefixManager | None = None,
        client_factory: typing.Callable[[str], typing.Any] | None = None,
        label: str = "",
        **extra,
    ):
        if not all([key_tpl, ttl is not None, backend]):
            raise ValueError("key_tpl, ttl, and backend are required")
        self.key_tpl = key_tpl
        self.ttl = ttl
        self.backend = backend
        self.is_global = is_global
        self.prefix_manager = prefix_manager
        self._client_factory = client_factory
        self._cache = None
        self.label = label
        for k, v in extra.items():
            setattr(self, k, v)

    @property
    def client(self):
        """
        获取 Redis 客户端实例（延迟初始化）。

        通过 client_factory(backend) 创建客户端，创建后缓存复用。

        Raises:
            ValueError: 未设置 client_factory 时抛出。
        """
        if self._cache is None:
            if self._client_factory is None:
                raise ValueError("client_factory is not set, cannot get Redis client")
            self._cache = self._client_factory(self.backend)
        return self._cache

    def get_key(self, **kwargs) -> str:
        """
        根据 key_tpl 和参数生成完整的 Redis key。

        流程：
        1. 用 kwargs 格式化 key_tpl
        2. 如果设置了 prefix_manager，自动添加前缀
        3. 前缀仅在不已存在时添加（防止重复拼接）

        Args:
            **kwargs: key 模板中的占位符参数。

        Returns:
            完整的 Redis key 字符串。

        Raises:
            KeyError: 模板中的占位符未在 kwargs 中提供。
        """
        key = self.key_tpl.format(**kwargs)

        if self.prefix_manager:
            key_prefix = self.prefix_manager.get_prefix(self.is_global)
            # 检查是否已包含全局前缀或集群前缀，防止重复拼接
            already_prefixed = key.startswith(key_prefix) or key.startswith(self.prefix_manager.global_prefix)
            if not already_prefixed:
                key = ".".join([key_prefix, key])

        return key

    def expire(self, **key_kwargs) -> None:
        """
        便捷方法：设置 key 的过期时间。

        Args:
            **key_kwargs: 传给 get_key() 的参数。

        Raises:
            ValueError: 未设置 client_factory 时抛出。
        """
        self.client.expire(self.get_key(**key_kwargs), self.ttl)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(key_tpl={self.key_tpl!r}, ttl={self.ttl}, backend={self.backend!r})"


class StringKey(RedisKey):
    """String 数据结构的 Key 对象。"""


class HashKey(RedisKey):
    """
    Hash 数据结构的 Key 对象。

    额外支持 field_tpl：Hash field 的模板，用于生成 field 名称。

    Args:
        field_tpl: Hash field 模板，支持 {placeholder} 格式化。
            例如 "{dimensions_md5}"
    """

    def __init__(
        self,
        key_tpl: str | None = None,
        ttl: int | None = None,
        backend: str | None = None,
        field_tpl: str = "",
        **kwargs,
    ):
        super().__init__(key_tpl, ttl, backend, **kwargs)
        self.field_tpl = field_tpl

    def get_field(self, **kwargs) -> str:
        """
        根据 field_tpl 和参数生成 Hash field 名称。

        Args:
            **kwargs: field 模板中的占位符参数。

        Returns:
            Hash field 字符串。
        """
        return self.field_tpl.format(**kwargs)


class SetKey(RedisKey):
    """Set 数据结构的 Key 对象。"""


class ListKey(RedisKey):
    """List 数据结构的 Key 对象。"""


class SortedSetKey(RedisKey):
    """SortedSet 数据结构的 Key 对象。"""


# key_type → 子类映射
_KEY_TYPE_MAP: dict[str, type[RedisKey]] = {
    "string": StringKey,
    "hash": HashKey,
    "set": SetKey,
    "list": ListKey,
    "sorted_set": SortedSetKey,
}


def _underscore_to_camel(name: str) -> str:
    """
    下划线转驼峰：sorted_set -> SortedSet

    Args:
        name: 下划线分隔的字符串。

    Returns:
        驼峰格式的字符串。
    """
    return "".join(word.capitalize() for word in name.split("_"))


def register_key(config: dict) -> RedisKey:
    """
    配置驱动的 Key 注册工厂。

    根据 config 中的 key_type 字段选择对应的 Key 子类，
    并用其余字段作为构造参数创建实例。

    Args:
        config: key 配置字典，必须包含 key_type 字段。
            支持的 key_type：string、hash、set、list、sorted_set。
            其余字段作为 Key 子类构造参数。

    Returns:
        对应类型的 RedisKey 实例。

    Raises:
        TypeError: 不支持的 key_type。

    用法：
        USER_CACHE = register_key({
            "key_type": "string",
            "key_tpl": "cache.user.{user_id}",
            "ttl": 3600,
            "backend": "default",
            "label": "用户信息缓存",
        })
    """
    config = dict(config)  # 浅拷贝，避免修改原字典
    key_type = config.pop("key_type")
    key_cls = _KEY_TYPE_MAP.get(key_type)
    if not key_cls:
        raise TypeError(f"unsupported key type: {key_type}, supported: {list(_KEY_TYPE_MAP.keys())}")
    return key_cls(**config)
