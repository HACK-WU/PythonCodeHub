"""
BaseClient 缓存功能测试

测试 CacheClient 的缓存功能:
- 缓存命中和未命中
- 缓存过期
- 用户级缓存隔离
- 缓存刷新和清除
- 批量请求缓存
"""

import pytest
import responses
import time
from http_client.cache import CacheClient, InMemoryCacheBackend


class SimpleCacheAPIClient(CacheClient):
    """测试用的缓存API客户端"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend


class SimpleCachePostsClient(CacheClient):
    """测试用的缓存API客户端（/posts端点）"""

    base_url = "https://api.example.com"
    endpoint = "/posts"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend


class SimpleCachePostAPIClient(CacheClient):
    """测试用的缓存API客户端（POST方法）"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"
    cache_backend_class = InMemoryCacheBackend


class TestCacheClientBasic:
    """测试缓存基本功能"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_hit(self):
        """测试缓存命中"""
        # Arrange
        responses.add(
            responses.GET, "https://api.example.com/users", json={"users": [{"id": 1, "name": "Alice"}]}, status=200
        )
        client = SimpleCacheAPIClient()

        # Act - 第一次请求
        result1 = client.request()
        # 第二次请求应该命中缓存
        result2 = client.request()

        # Assert
        assert result1["data"] == result2["data"]
        # 只应该发送一次HTTP请求
        assert len(responses.calls) == 1

    @pytest.mark.unit
    @responses.activate
    def test_cache_miss(self):
        """测试缓存未命中"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        responses.add(responses.GET, "https://api.example.com/posts", json={"posts": []}, status=200)
        users_client = SimpleCacheAPIClient()
        posts_client = SimpleCachePostsClient()

        # Act
        users_client.request()
        posts_client.request()

        # Assert
        # 不同的端点应该发送两次请求
        assert len(responses.calls) == 2

    @pytest.mark.unit
    @responses.activate
    def test_cache_with_different_params(self):
        """测试不同参数的缓存"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleCacheAPIClient()

        # Act
        client.request({"params": {"page": 1}})
        client.request({"params": {"page": 2}})

        # Assert
        # 不同参数应该发送两次请求
        assert len(responses.calls) == 2

    @pytest.mark.unit
    @responses.activate
    def test_post_request_not_cached(self):
        """测试POST请求不被缓存"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)
        client = SimpleCachePostAPIClient()

        # Act
        client.request({"json": {"name": "Alice"}})
        client.request({"json": {"name": "Alice"}})

        # Assert
        # POST请求不应该被缓存，应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheClientExpiration:
    """测试缓存过期"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_expiration(self):
        """测试缓存过期"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleCacheAPIClient(cache_expire=1)  # 1秒过期

        # Act
        client.request()
        time.sleep(1.1)  # 等待缓存过期
        client.request()

        # Assert
        # 缓存过期后应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheClientUserSpecific:
    """测试用户级缓存隔离"""

    @pytest.mark.unit
    @responses.activate
    def test_user_specific_cache(self):
        """测试用户级缓存隔离"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        class UserSpecificClient(CacheClient):
            base_url = "https://api.example.com"
            endpoint = "/users"
            method = "GET"
            is_user_specific = True
            cache_backend_class = InMemoryCacheBackend

        # Act
        client1 = UserSpecificClient(user_identifier="user1")
        client2 = UserSpecificClient(user_identifier="user2")

        client1.request()
        client2.request()

        # Assert
        # 不同用户应该发送两次请求
        assert len(responses.calls) == 2

    @pytest.mark.unit
    def test_user_specific_without_identifier_raises_error(self):
        """测试用户级缓存没有提供用户标识时抛出错误"""

        # Arrange
        class UserSpecificClient(CacheClient):
            base_url = "https://api.example.com"
            is_user_specific = True

        # Act & Assert
        with pytest.raises(ValueError, match="User identifier is required"):
            UserSpecificClient()


class TestCacheClientRefresh:
    """测试缓存刷新"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_refresh(self):
        """测试缓存刷新"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": [{"id": 1}]}, status=200)
        responses.add(
            responses.GET, "https://api.example.com/users", json={"users": [{"id": 1}, {"id": 2}]}, status=200
        )
        client = SimpleCacheAPIClient()

        # Act
        result1 = client.request()
        result2 = client.refresh()  # 刷新缓存
        result3 = client.request()  # 应该使用刷新后的缓存

        # Assert
        assert len(result1["data"]["users"]) == 1
        assert len(result2["data"]["users"]) == 2
        assert len(result3["data"]["users"]) == 2
        # 应该发送两次请求（第一次和刷新）
        assert len(responses.calls) == 2


class TestCacheClientCacheless:
    """测试绕过缓存"""

    @pytest.mark.unit
    @responses.activate
    def test_cacheless_request(self):
        """测试绕过缓存的请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleCacheAPIClient()

        # Act
        client.request()
        client.cacheless()  # 绕过缓存

        # Assert
        # 应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheClientClear:
    """测试缓存清除"""

    @pytest.mark.unit
    @responses.activate
    def test_clear_cache(self):
        """测试清除缓存"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleCacheAPIClient()

        # Act
        client.request()
        client.clear_cache()
        client.request()

        # Assert
        # 清除缓存后应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheClientBatchRequests:
    """测试批量请求缓存"""

    @pytest.mark.unit
    @responses.activate
    def test_batch_requests_with_cache(self):
        """测试批量请求的缓存"""
        # Arrange
        # 注意：批量请求会使用类的默认endpoint，所以需要mock默认URL
        responses.add(responses.GET, "https://api.example.com/users", json={"id": 1, "name": "Alice"}, status=200)
        responses.add(responses.GET, "https://api.example.com/users", json={"id": 2, "name": "Bob"}, status=200)
        client = SimpleCacheAPIClient()

        # Act - 第一次批量请求
        results1 = client.request([{"params": {"id": 1}}, {"params": {"id": 2}}])
        # 第二次批量请求应该命中缓存
        results2 = client.request([{"params": {"id": 1}}, {"params": {"id": 2}}])

        # Assert
        assert len(results1) == 2
        assert len(results2) == 2
        # 只应该发送两次HTTP请求（第一次批量请求）
        assert len(responses.calls) == 2

    @pytest.mark.unit
    @responses.activate
    def test_batch_requests_partial_cache_hit(self):
        """测试批量请求部分缓存命中"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"id": 1, "name": "Alice"}, status=200)
        responses.add(responses.GET, "https://api.example.com/users", json={"id": 2, "name": "Bob"}, status=200)
        responses.add(responses.GET, "https://api.example.com/users", json={"id": 3, "name": "Charlie"}, status=200)
        client = SimpleCacheAPIClient()

        # Act
        # 第一次请求id=1和id=2
        results1 = client.request([{"params": {"id": 1}}, {"params": {"id": 2}}])
        # 第二次请求id=1（缓存命中）和id=3（缓存未命中）
        results2 = client.request([{"params": {"id": 1}}, {"params": {"id": 3}}])

        # Assert
        assert len(results1) == 2
        assert len(results2) == 2
        # 应该发送3次HTTP请求（id=1, id=2, id=3）
        assert len(responses.calls) == 3


class TestCacheClientCustomCacheCheck:
    """测试自定义缓存检查"""

    @pytest.mark.unit
    @responses.activate
    def test_custom_should_cache_response_func(self):
        """测试自定义缓存响应检查函数"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"error": "Not authorized"}, status=200)

        def custom_cache_check(result):
            # 只缓存没有error字段的响应
            return "error" not in result.get("data", {})

        client = SimpleCacheAPIClient(should_cache_response_func=custom_cache_check)

        # Act
        client.request()
        client.request()

        # Assert
        # 由于响应包含error，不应该被缓存，应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheClientDisabled:
    """测试禁用缓存"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_disabled(self):
        """测试禁用缓存"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleCacheAPIClient()
        client.enable_cache = False

        # Act
        client.request()
        client.request()

        # Assert
        # 禁用缓存后应该发送两次请求
        assert len(responses.calls) == 2


class TestCacheBackendFallback:
    """测试缓存后端回退"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_backend_initialization_failure_fallback(self):
        """测试缓存后端初始化失败时回退到内存缓存"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        class FailingCacheBackend:
            def __init__(self):
                raise Exception("Backend initialization failed")

        class ClientWithFailingBackend(CacheClient):
            base_url = "https://api.example.com"
            endpoint = "/users"
            method = "GET"
            cache_backend_class = FailingCacheBackend

        # Act
        client = ClientWithFailingBackend()
        result = client.request()

        # Assert
        # 应该回退到内存缓存并正常工作
        assert result["result"] is True
        assert isinstance(client.cache_backend, InMemoryCacheBackend)


class TestCacheClientConcurrent:
    """测试并发请求下的缓存效果（使用 is_async=True）"""

    @pytest.mark.unit
    @responses.activate
    def test_async_batch_requests_cache_hit(self):
        """测试异步批量请求时的缓存命中"""
        # Arrange
        for _ in range(10):
            responses.add(responses.GET, "https://api.example.com/users", json={"users": [{"id": 1}]}, status=200)
        client = SimpleCacheAPIClient(max_workers=5)

        # Act - 第一次异步批量请求
        request_list = [{} for _ in range(10)]
        results1 = client.request(request_list, is_async=True)

        # 第二次异步批量请求应命中缓存
        results2 = client.request(request_list, is_async=True)

        # Assert
        assert len(results1) == 10
        assert len(results2) == 10
        assert all(r["result"] is True for r in results1)
        assert all(r["result"] is True for r in results2)
        # 第二次请求应全部命中缓存，总请求次数应等于第一次的请求数
        assert len(responses.calls) == 10

    @pytest.mark.unit
    @responses.activate
    def test_async_batch_requests_different_params(self):
        """测试异步批量请求不同参数时的缓存隔离"""
        # Arrange
        for _ in range(5):
            responses.add(responses.GET, "https://api.example.com/users", json={"data": "ok"}, status=200)
        client = SimpleCacheAPIClient(max_workers=5)

        # Act - 5个不同参数的异步批量请求
        request_list = [{"page": i} for i in range(1, 6)]
        results1 = client.request(request_list, is_async=True)

        # 第二次相同参数请求应命中缓存
        results2 = client.request(request_list, is_async=True)

        # Assert
        assert len(results1) == 5
        assert len(results2) == 5
        assert all(r["result"] is True for r in results1)
        assert all(r["result"] is True for r in results2)
        # 第二次请求全部命中缓存
        assert len(responses.calls) == 5

    @pytest.mark.unit
    @responses.activate
    def test_async_batch_partial_cache_hit(self):
        """测试异步批量请求部分缓存命中"""
        # Arrange
        for _ in range(8):
            responses.add(responses.GET, "https://api.example.com/users", json={"data": "ok"}, status=200)
        client = SimpleCacheAPIClient(max_workers=5)

        # Act - 第一次请求 page 1-5
        request_list1 = [{"page": i} for i in range(1, 6)]
        results1 = client.request(request_list1, is_async=True)
        assert len(responses.calls) == 5

        # 第二次请求 page 3-8，其中 3-5 应命中缓存，6-8 需新请求
        request_list2 = [{"page": i} for i in range(3, 9)]
        results2 = client.request(request_list2, is_async=True)

        # Assert
        assert len(results1) == 5
        assert len(results2) == 6
        assert all(r["result"] is True for r in results1)
        assert all(r["result"] is True for r in results2)
        # 新增3次请求（page 6, 7, 8）
        assert len(responses.calls) == 8

    @pytest.mark.unit
    @responses.activate
    def test_async_cache_after_warmup(self):
        """测试预热缓存后的异步批量请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": [{"id": 1}]}, status=200)
        client = SimpleCacheAPIClient(max_workers=5)

        # 预热缓存（单个请求）
        warmup_result = client.request()
        assert warmup_result["result"] is True
        assert len(responses.calls) == 1

        # Act - 预热后异步批量发送相同请求
        request_list = [{} for _ in range(10)]
        results = client.request(request_list, is_async=True)

        # Assert
        assert len(results) == 10
        assert all(r["result"] is True for r in results)
        # 预热后所有请求都应命中缓存，不发送新的HTTP请求
        assert len(responses.calls) == 1

    @pytest.mark.unit
    @responses.activate
    def test_async_batch_with_max_workers(self):
        """测试不同 max_workers 配置下的异步批量请求"""
        # Arrange
        for _ in range(20):
            responses.add(responses.GET, "https://api.example.com/users", json={"data": "ok"}, status=200)

        # 使用较大的 max_workers
        client = SimpleCacheAPIClient(max_workers=10)

        # Act
        request_list = [{"id": i} for i in range(20)]
        results = client.request(request_list, is_async=True)

        # Assert
        assert len(results) == 20
        assert all(r["result"] is True for r in results)
        assert len(responses.calls) == 20
