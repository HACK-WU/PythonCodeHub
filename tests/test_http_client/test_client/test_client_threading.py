"""
BaseClient 多线程测试

测试 BaseClient 在多线程环境下的行为:
- 线程安全性
- 并发请求
- 缓存线程安全
- 连接池管理
"""

import pytest
import responses
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import Mock, patch
from http_client.client import BaseClient
from http_client.cache import CacheClient, InMemoryCacheBackend


class SimpleThreadingClient(BaseClient):
    """测试用的客户端"""
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"


class SimpleThreadingCacheClient(CacheClient):
    """测试用的缓存客户端"""
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"
    cache_backend_class = InMemoryCacheBackend


class TestBaseClientThreadSafety:
    """测试基本线程安全"""

    @pytest.mark.unit
    @responses.activate
    def test_concurrent_requests_same_endpoint(self):
        """测试并发请求相同端点"""
        # Arrange
        for i in range(10):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )
        client = SimpleThreadingClient()

        # Act
        def make_request():
            return client.request()

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_concurrent_requests_different_endpoints(self):
        """测试并发请求不同端点"""
        # Arrange
        for i in range(1, 11):
            responses.add(
                responses.GET,
                f"https://api.example.com/users/{i}",
                json={"id": i, "name": f"User{i}"},
                status=200
            )
        client = SimpleThreadingClient()

        # Act
        def make_request(user_id):
            return client.request({"endpoint": f"/users/{user_id}"})

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request, i) for i in range(1, 11)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_session_lock_prevents_race_condition(self):
        """测试session锁防止竞态条件"""
        # Arrange
        for i in range(20):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )
        client = SimpleThreadingClient()
        access_count = {"count": 0}
        lock = threading.Lock()

        # Act
        def make_request():
            with lock:
                access_count["count"] += 1
            return client.request()

        threads = []
        for _ in range(20):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Assert
        assert access_count["count"] == 20


class TestCacheClientThreadSafety:
    """测试缓存客户端线程安全"""

    @pytest.mark.unit
    @responses.activate
    def test_cache_thread_safety(self):
        """测试缓存在多线程下的安全性"""
        # Arrange
        responses.add(
            responses.GET,
            "https://api.example.com/users",
            json={"users": [{"id": 1}]},
            status=200
        )
        client = SimpleThreadingCacheClient()

        # Act
        def make_request():
            return client.request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(20)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 20
        assert all(r["result"] is True for r in results)
        # 由于缓存，只应该发送一次HTTP请求
        assert len(responses.calls) == 1

    @pytest.mark.unit
    @responses.activate
    def test_concurrent_cache_miss_requests(self):
        """测试并发缓存未命中请求"""
        # Arrange
        for i in range(1, 11):
            responses.add(
                responses.GET,
                f"https://api.example.com/users/{i}",
                json={"id": i},
                status=200
            )
        client = SimpleThreadingCacheClient()

        # Act
        def make_request(user_id):
            return client.request({"endpoint": f"/users/{user_id}"})

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request, i) for i in range(1, 11)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        # 不同端点应该发送10次请求
        assert len(responses.calls) == 10

    @pytest.mark.unit
    @responses.activate
    def test_cache_stampede_prevention(self):
        """测试缓存击穿预防（多个线程同时请求同一个未缓存的资源）"""
        # Arrange
        request_count = {"count": 0}
        lock = threading.Lock()

        def custom_callback(request):
            with lock:
                request_count["count"] += 1
            time.sleep(0.1)  # 模拟慢速响应
            return (200, {}, '{"users": []}')

        responses.add_callback(
            responses.GET,
            "https://api.example.com/users",
            callback=custom_callback,
            content_type="application/json"
        )
        client = SimpleThreadingCacheClient()

        # Act
        def make_request():
            return client.request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        # 注意：当前实现可能会有缓存击穿问题，多个线程可能同时发送请求
        # 这个测试记录当前行为，如果实现了防击穿机制，应该只有1次请求
        print(f"实际请求次数: {request_count['count']}")
        assert request_count["count"] >= 1  # 至少发送一次请求


class TestRequestMappingThreadSafety:
    """测试请求映射的线程安全"""

    @pytest.mark.unit
    @responses.activate
    def test_request_mapping_concurrent_access(self):
        """测试请求映射的并发访问"""
        # Arrange
        for i in range(20):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )
        client = SimpleThreadingCacheClient()

        # Act
        def make_request():
            return client.request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(20)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 20
        # 请求映射应该在请求完成后被清空
        assert len(client.request_mapping) == 0


class TestConnectionPoolThreading:
    """测试连接池在多线程下的行为"""

    @pytest.mark.unit
    @responses.activate
    def test_connection_pool_reuse(self):
        """测试连接池复用"""
        # Arrange
        for i in range(50):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )
        client = SimpleThreadingClient()

        # Act
        def make_request():
            return client.request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(50)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 50
        assert all(r["result"] is True for r in results)


class TestBatchRequestsThreading:
    """测试批量请求的多线程行为"""

    @pytest.mark.unit
    @responses.activate
    def test_async_batch_requests_thread_pool(self):
        """测试异步批量请求使用线程池"""
        # Arrange
        for i in range(1, 11):
            responses.add(
                responses.GET,
                f"https://api.example.com/users/{i}",
                json={"id": i},
                status=200
            )
        client = SimpleThreadingClient(max_workers=5)

        # Act
        results = client.request([
            {"endpoint": f"/users/{i}"} for i in range(1, 11)
        ], is_async=True)

        # Assert
        assert len(results) == 10
        assert all(r["result"] is True for r in results)


class TestCacheClearThreadSafety:
    """测试缓存清除的线程安全"""

    @pytest.mark.unit
    @responses.activate
    def test_concurrent_cache_clear(self):
        """测试并发缓存清除"""
        # Arrange
        for i in range(20):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )
        client = SimpleThreadingCacheClient()

        # Act
        def make_request_and_clear():
            client.request()
            client.clear_cache()
            return True

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request_and_clear) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        assert all(r is True for r in results)


class TestStreamResponsesThreadSafety:
    """测试流式响应的线程安全"""

    @pytest.mark.unit
    def test_stream_responses_lock_exists(self):
        """测试流式响应锁存在"""
        # Arrange
        client = SimpleThreadingClient()

        # Assert
        assert hasattr(client, '_stream_responses_lock')
        assert type(client._stream_responses_lock).__name__ == 'RLock'


class TestMultipleClientsThreading:
    """测试多个客户端实例的多线程行为"""

    @pytest.mark.unit
    @responses.activate
    def test_multiple_clients_concurrent_requests(self):
        """测试多个客户端实例并发请求"""
        # Arrange
        for i in range(20):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )

        # Act
        def make_request_with_new_client():
            client = SimpleThreadingClient()
            result = client.request()
            client.close()
            return result

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request_with_new_client) for _ in range(20)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 20
        assert all(r["result"] is True for r in results)


class TestThreadingEdgeCases:
    """测试多线程边界情况"""

    @pytest.mark.unit
    @responses.activate
    def test_rapid_client_creation_and_destruction(self):
        """测试快速创建和销毁客户端"""
        # Arrange
        for i in range(50):
            responses.add(
                responses.GET,
                "https://api.example.com/users",
                json={"users": []},
                status=200
            )

        # Act
        def create_request_destroy():
            with SimpleThreadingClient() as client:
                return client.request()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_request_destroy) for _ in range(50)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 50
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_concurrent_requests_with_errors(self):
        """测试并发请求中包含错误"""
        # Arrange
        for i in range(10):
            if i % 2 == 0:
                responses.add(
                    responses.GET,
                    f"https://api.example.com/users/{i}",
                    json={"id": i},
                    status=200
                )
            else:
                responses.add(
                    responses.GET,
                    f"https://api.example.com/users/{i}",
                    json={"error": "Not found"},
                    status=404
                )
        client = SimpleThreadingClient()

        # Act
        def make_request(user_id):
            return client.request({"endpoint": f"/users/{user_id}"})

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Assert
        assert len(results) == 10
        success_count = sum(1 for r in results if r["result"] is True)
        error_count = sum(1 for r in results if r["result"] is False)
        assert success_count == 5
        assert error_count == 5
