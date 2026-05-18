"""
Redis Key 声明式元数据管理 单元测试
"""

from unittest.mock import MagicMock

import pytest

from ab_redis.key import (
    HashKey,
    KeyPrefixManager,
    ListKey,
    RedisKey,
    SetKey,
    SortedSetKey,
    StringKey,
    register_key,
)


class TestKeyPrefixManager:
    """KeyPrefixManager 前缀管理测试"""

    def test_global_prefix(self):
        mgr = KeyPrefixManager(global_prefix="myapp.ee", cluster_prefix="myapp.ee.cluster1")
        assert mgr.get_prefix(is_global=True) == "myapp.ee"

    def test_cluster_prefix(self):
        mgr = KeyPrefixManager(global_prefix="myapp.ee", cluster_prefix="myapp.ee.cluster1")
        assert mgr.get_prefix(is_global=False) == "myapp.ee.cluster1"

    def test_no_cluster_prefix_fallback(self):
        """cluster_prefix 为 None 时回退到 global_prefix"""
        mgr = KeyPrefixManager(global_prefix="myapp.ee")
        assert mgr.get_prefix(is_global=False) == "myapp.ee"

    def test_empty_prefix(self):
        mgr = KeyPrefixManager(global_prefix="", cluster_prefix="")
        assert mgr.get_prefix(is_global=True) == ""
        assert mgr.get_prefix(is_global=False) == ""


class TestRedisKey:
    """RedisKey 核心功能测试"""

    def test_get_key_without_prefix(self):
        """无前缀管理器时，get_key 直接格式化模板"""
        key = RedisKey(key_tpl="cache.user.{user_id}", ttl=3600, backend="default")
        assert key.get_key(user_id=123) == "cache.user.123"

    def test_get_key_with_prefix(self):
        """有前缀管理器时，自动添加前缀"""
        mgr = KeyPrefixManager(global_prefix="myapp.ee", cluster_prefix="myapp.ee.c1")
        key = RedisKey(
            key_tpl="cache.user.{user_id}",
            ttl=3600,
            backend="default",
            prefix_manager=mgr,
        )
        assert key.get_key(user_id=123) == "myapp.ee.c1.cache.user.123"

    def test_get_key_global_uses_global_prefix(self):
        """is_global=True 使用全局前缀"""
        mgr = KeyPrefixManager(global_prefix="myapp.ee", cluster_prefix="myapp.ee.c1")
        key = RedisKey(
            key_tpl="cache.global.config",
            ttl=3600,
            backend="default",
            is_global=True,
            prefix_manager=mgr,
        )
        assert key.get_key() == "myapp.ee.cache.global.config"

    def test_get_key_no_duplicate_prefix(self):
        """key 已包含前缀时不重复添加"""
        mgr = KeyPrefixManager(global_prefix="myapp.ee", cluster_prefix="myapp.ee.c1")
        key = RedisKey(
            key_tpl="myapp.ee.cache.user.{user_id}",
            ttl=3600,
            backend="default",
            prefix_manager=mgr,
        )
        assert key.get_key(user_id=123) == "myapp.ee.cache.user.123"

    def test_get_key_missing_placeholder_raises(self):
        """模板占位符未提供时抛出 KeyError"""
        key = RedisKey(key_tpl="cache.user.{user_id}", ttl=3600, backend="default")
        with pytest.raises(KeyError):
            key.get_key()

    def test_required_fields(self):
        """缺少必填字段时抛出 ValueError"""
        with pytest.raises(ValueError):
            RedisKey(key_tpl="test", ttl=3600)  # 缺少 backend

        with pytest.raises(ValueError):
            RedisKey(key_tpl="test", backend="default")  # 缺少 ttl

    def test_extra_attributes(self):
        """额外属性存储为实例属性"""
        key = RedisKey(
            key_tpl="test",
            ttl=60,
            backend="default",
            label="测试 key",
            custom_field="hello",
        )
        assert key.label == "测试 key"
        assert key.custom_field == "hello"

    def test_repr(self):
        key = RedisKey(key_tpl="cache.user.{user_id}", ttl=3600, backend="default")
        assert "cache.user.{user_id}" in repr(key)

    def test_client_without_factory_raises(self):
        """未设置 client_factory 时访问 client 抛出 ValueError"""
        key = RedisKey(key_tpl="test", ttl=60, backend="default")
        with pytest.raises(ValueError, match="client_factory"):
            _ = key.client

    def test_client_with_factory(self):
        """client_factory 延迟创建并缓存客户端"""
        mock_factory = MagicMock(return_value=MagicMock())
        key = RedisKey(key_tpl="test", ttl=60, backend="default", client_factory=mock_factory)

        client1 = key.client
        client2 = key.client
        mock_factory.assert_called_once_with("default")
        assert client1 is client2

    def test_expire(self):
        """expire 方法调用 client.expire"""
        mock_client = MagicMock()
        mock_factory = MagicMock(return_value=mock_client)
        key = RedisKey(
            key_tpl="cache.user.{user_id}",
            ttl=3600,
            backend="default",
            client_factory=mock_factory,
        )
        key.expire(user_id=123)
        mock_client.expire.assert_called_once_with("cache.user.123", 3600)


class TestHashKey:
    """HashKey 测试"""

    def test_field_tpl_required_in_config(self):
        """通过 register_key 注册时 field_tpl 为必填"""
        # 直接构造时 field_tpl 默认为空字符串
        key = HashKey(key_tpl="cache.dim", ttl=60, backend="default", field_tpl="{md5}")
        assert key.field_tpl == "{md5}"

    def test_get_field(self):
        key = HashKey(
            key_tpl="cache.dimension.{strategy_id}",
            ttl=1800,
            backend="service",
            field_tpl="{dimensions_md5}",
        )
        assert key.get_field(dimensions_md5="abc123") == "abc123"

    def test_get_key_and_field_combined(self):
        mgr = KeyPrefixManager(global_prefix="myapp")
        key = HashKey(
            key_tpl="cache.dimension.{strategy_id}.{item_id}",
            ttl=1800,
            backend="service",
            field_tpl="{dimensions_md5}",
            prefix_manager=mgr,
        )
        assert key.get_key(strategy_id=1, item_id=2) == "myapp.cache.dimension.1.2"
        assert key.get_field(dimensions_md5="abc") == "abc"


class TestKeySubclasses:
    """类型子类测试"""

    def test_string_key(self):
        key = StringKey(key_tpl="test", ttl=60, backend="default")
        assert isinstance(key, RedisKey)

    def test_set_key(self):
        key = SetKey(key_tpl="test", ttl=60, backend="default")
        assert isinstance(key, RedisKey)

    def test_list_key(self):
        key = ListKey(key_tpl="test", ttl=60, backend="default")
        assert isinstance(key, RedisKey)

    def test_sorted_set_key(self):
        key = SortedSetKey(key_tpl="test", ttl=60, backend="default")
        assert isinstance(key, RedisKey)


class TestRegisterKey:
    """register_key 工厂测试"""

    def test_register_string_key(self):
        key = register_key(
            {
                "key_type": "string",
                "key_tpl": "cache.user.{user_id}",
                "ttl": 3600,
                "backend": "default",
            }
        )
        assert isinstance(key, StringKey)
        assert key.key_tpl == "cache.user.{user_id}"

    def test_register_hash_key(self):
        key = register_key(
            {
                "key_type": "hash",
                "key_tpl": "cache.dim.{strategy_id}",
                "ttl": 1800,
                "backend": "service",
                "field_tpl": "{md5}",
            }
        )
        assert isinstance(key, HashKey)
        assert key.field_tpl == "{md5}"

    def test_register_set_key(self):
        key = register_key({"key_type": "set", "key_tpl": "test", "ttl": 60, "backend": "default"})
        assert isinstance(key, SetKey)

    def test_register_list_key(self):
        key = register_key({"key_type": "list", "key_tpl": "test", "ttl": 60, "backend": "default"})
        assert isinstance(key, ListKey)

    def test_register_sorted_set_key(self):
        key = register_key({"key_type": "sorted_set", "key_tpl": "test", "ttl": 60, "backend": "default"})
        assert isinstance(key, SortedSetKey)

    def test_unsupported_key_type_raises(self):
        with pytest.raises(TypeError, match="unsupported key type"):
            register_key({"key_type": "unknown", "key_tpl": "test", "ttl": 60, "backend": "default"})

    def test_register_preserves_extra_config(self):
        key = register_key(
            {
                "key_type": "string",
                "key_tpl": "test",
                "ttl": 60,
                "backend": "default",
                "label": "测试",
                "is_global": True,
            }
        )
        assert key.label == "测试"
        assert key.is_global is True

    def test_register_does_not_modify_input(self):
        """register_key 不应修改传入的 config 字典"""
        config = {
            "key_type": "string",
            "key_tpl": "test",
            "ttl": 60,
            "backend": "default",
        }
        config_copy = dict(config)
        register_key(config)
        assert config == config_copy


class TestEndToEnd:
    """端到端场景测试"""

    def test_multi_cluster_key_isolation(self):
        """多集群场景：全局 key 共享前缀，集群 key 隔离前缀"""
        mgr = KeyPrefixManager(
            global_prefix="monitor.ee",
            cluster_prefix="monitor.ee.cluster-shanghai",
        )

        global_key = RedisKey(
            key_tpl="config.global",
            ttl=86400,
            backend="service",
            is_global=True,
            prefix_manager=mgr,
        )
        cluster_key = RedisKey(
            key_tpl="cache.local.{item_id}",
            ttl=300,
            backend="service",
            is_global=False,
            prefix_manager=mgr,
        )

        assert global_key.get_key() == "monitor.ee.config.global"
        assert cluster_key.get_key(item_id=42) == "monitor.ee.cluster-shanghai.cache.local.42"

    def test_full_workflow_with_hash(self):
        """完整工作流：定义 HashKey → get_key + get_field → expire"""
        mock_client = MagicMock()
        mgr = KeyPrefixManager(global_prefix="myapp")

        dim_cache = HashKey(
            key_tpl="dimension.cache.{strategy_id}.{item_id}",
            field_tpl="{dimensions_md5}",
            ttl=86400,
            backend="service",
            prefix_manager=mgr,
            client_factory=lambda backend: mock_client,
        )

        # 生成 key 和 field
        redis_key = dim_cache.get_key(strategy_id=1, item_id=2)
        redis_field = dim_cache.get_field(dimensions_md5="abc123")

        assert redis_key == "myapp.dimension.cache.1.2"
        assert redis_field == "abc123"

        # 设置过期
        dim_cache.expire(strategy_id=1, item_id=2)
        mock_client.expire.assert_called_once_with("myapp.dimension.cache.1.2", 86400)
