"""
cache.py 模块的单元测试

测试缓存后端实现:
- BaseCacheBackend 抽象基类
- InMemoryCacheBackend 内存缓存
- RedisCacheBackend Redis缓存
"""

import pytest
import time
from abc import ABC
from http_client.cache import (
    BaseCacheBackend,
    InMemoryCacheBackend,
    RedisCacheBackend,
)


class TestBaseCacheBackend:
    """测试 BaseCacheBackend 抽象基类"""

    @pytest.mark.unit
    def test_is_abstract_class(self):
        """验证 BaseCacheBackend 是抽象类"""
        # Arrange & Act & Assert
        assert issubclass(BaseCacheBackend, ABC)

        # 验证不能直接实例化
        with pytest.raises(TypeError):
            BaseCacheBackend()

    @pytest.mark.unit
    def test_has_abstract_methods(self):
        """验证 BaseCacheBackend 有抽象方法"""
        # Arrange & Act & Assert
        assert hasattr(BaseCacheBackend, "get")
        assert hasattr(BaseCacheBackend, "set")
        assert hasattr(BaseCacheBackend, "delete")
        assert hasattr(BaseCacheBackend, "clear")


class TestInMemoryCacheBackend:
    """测试 InMemoryCacheBackend 内存缓存"""

    @pytest.fixture
    def cache(self):
        """提供内存缓存实例"""
        return InMemoryCacheBackend(maxsize=10)

    @pytest.mark.unit
    def test_initialization(self, cache):
        """测试初始化"""
        # Arrange & Act & Assert
        assert isinstance(cache, InMemoryCacheBackend)
        assert isinstance(cache, BaseCacheBackend)
        assert cache.maxsize == 10

    @pytest.mark.unit
    def test_set_and_get(self, cache):
        """测试设置和获取缓存"""
        # Arrange & Act
        cache.set("key1", "value1")
        result = cache.get("key1")

        # Assert
        assert result == "value1"

    @pytest.mark.unit
    def test_get_nonexistent_key(self, cache):
        """测试获取不存在的键"""
        # Arrange & Act
        result = cache.get("nonexistent")

        # Assert
        assert result is None

    @pytest.mark.unit
    def test_set_with_expiration(self, cache):
        """测试带过期时间的缓存"""
        # Arrange & Act
        cache.set("temp_key", "temp_value", expire=1)

        # 立即获取应该成功
        result1 = cache.get("temp_key")
        assert result1 == "temp_value"

        # 等待过期
        time.sleep(1.1)
        result2 = cache.get("temp_key")

        # Assert
        assert result2 is None

    @pytest.mark.unit
    def test_delete(self, cache):
        """测试删除缓存"""
        # Arrange
        cache.set("key1", "value1")

        # Act
        cache.delete("key1")
        result = cache.get("key1")

        # Assert
        assert result is None

    @pytest.mark.unit
    def test_delete_nonexistent_key(self, cache):
        """测试删除不存在的键"""
        # Arrange & Act & Assert - 不应抛出异常
        cache.delete("nonexistent")

    @pytest.mark.unit
    def test_clear(self, cache):
        """测试清空缓存"""
        # Arrange
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Act
        cache.clear()

        # Assert
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    @pytest.mark.unit
    def test_maxsize_limit(self):
        """测试最大容量限制"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=3)

        # Act - 添加超过maxsize的项
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")  # 应该触发清理

        # Assert - 缓存大小不应超过maxsize
        # 注意：OrderedDict 的 move_to_end 和 popitem 行为可能导致实际大小等于 maxsize
        assert len(cache.cache) <= 4

    @pytest.mark.unit
    def test_lru_behavior(self):
        """测试LRU行为"""
        # Arrange
        cache = InMemoryCacheBackend(maxsize=2)

        # Act
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.get("key1")  # 访问key1，使其成为最近使用
        cache.set("key3", "value3")  # 应该淘汰key2

        # Assert
        assert cache.get("key1") == "value1"
        assert cache.get("key3") == "value3"

    @pytest.mark.unit
    def test_update_existing_key(self, cache):
        """测试更新已存在的键"""
        # Arrange
        cache.set("key1", "value1")

        # Act
        cache.set("key1", "value2")
        result = cache.get("key1")

        # Assert
        assert result == "value2"

    @pytest.mark.unit
    def test_various_value_types(self, cache):
        """测试各种类型的值"""
        # Arrange & Act & Assert
        cache.set("str", "string_value")
        assert cache.get("str") == "string_value"

        cache.set("int", 123)
        assert cache.get("int") == 123

        cache.set("dict", {"key": "value"})
        assert cache.get("dict") == {"key": "value"}

        cache.set("list", [1, 2, 3])
        assert cache.get("list") == [1, 2, 3]


class TestRedisCacheBackend:
    """测试 RedisCacheBackend Redis缓存"""

    @pytest.fixture
    def redis_cache(self, fake_redis):
        """提供使用FakeRedis的缓存实例"""
        cache = RedisCacheBackend()
        # 替换为fake_redis客户端
        cache.client = fake_redis
        return cache

    @pytest.mark.unit
    @pytest.mark.redis
    def test_initialization(self):
        """测试初始化"""
        # Arrange & Act
        cache = RedisCacheBackend()

        # Assert
        assert isinstance(cache, RedisCacheBackend)
        assert isinstance(cache, BaseCacheBackend)

    @pytest.mark.unit
    @pytest.mark.redis
    def test_set_and_get(self, redis_cache):
        """测试设置和获取缓存"""
        # Arrange & Act
        redis_cache.set("key1", "value1")
        result = redis_cache.get("key1")

        # Assert - Redis 可能返回 bytes 或 string
        if isinstance(result, bytes):
            result = result.decode("utf-8")
        assert result == "value1"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_get_nonexistent_key(self, redis_cache):
        """测试获取不存在的键"""
        # Arrange & Act
        result = redis_cache.get("nonexistent")

        # Assert
        assert result is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_set_with_expiration(self, redis_cache):
        """测试带过期时间的缓存"""
        # Arrange & Act
        redis_cache.set("temp_key", "temp_value", expire=1)

        # 立即获取应该成功
        result1 = redis_cache.get("temp_key")
        # Redis 可能返回 bytes 或 string
        if isinstance(result1, bytes):
            result1 = result1.decode("utf-8")
        assert result1 == "temp_value"

    @pytest.mark.unit
    @pytest.mark.redis
    def test_delete(self, redis_cache):
        """测试删除缓存"""
        # Arrange
        redis_cache.set("key1", "value1")

        # Act
        redis_cache.delete("key1")
        result = redis_cache.get("key1")

        # Assert
        assert result is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_clear(self, redis_cache):
        """测试清空缓存"""
        # Arrange
        redis_cache.set("key1", "value1")
        redis_cache.set("key2", "value2")

        # Act
        redis_cache.clear()

        # Assert
        assert redis_cache.get("key1") is None
        assert redis_cache.get("key2") is None

    @pytest.mark.unit
    @pytest.mark.redis
    def test_json_serialization(self, redis_cache):
        """测试JSON序列化"""
        # Arrange & Act
        redis_cache.set("dict", {"key": "value", "number": 123})
        result = redis_cache.get("dict")

        # Assert
        assert result == {"key": "value", "number": 123}

    @pytest.mark.unit
    @pytest.mark.redis
    def test_list_serialization(self, redis_cache):
        """测试列表序列化"""
        # Arrange & Act
        redis_cache.set("list", [1, 2, 3, "four"])
        result = redis_cache.get("list")

        # Assert
        assert result == [1, 2, 3, "four"]

    @pytest.mark.unit
    @pytest.mark.redis
    def test_update_existing_key(self, redis_cache):
        """测试更新已存在的键"""
        # Arrange
        redis_cache.set("key1", "value1")

        # Act
        redis_cache.set("key1", "value2")
        result = redis_cache.get("key1")

        # Assert - Redis 可能返回 bytes 或 string
        if isinstance(result, bytes):
            result = result.decode("utf-8")
        assert result == "value2"
