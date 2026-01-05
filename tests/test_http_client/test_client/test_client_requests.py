"""
BaseClient 实际 HTTP 请求测试

测试 BaseClient 执行真实 HTTP 请求的功能:
- GET/POST/PUT/DELETE 请求
- 请求参数处理
- 响应解析
- 错误处理
"""

import pytest
import responses
from unittest.mock import patch
from http_client.client import BaseClient


class SimpleAPIClient(BaseClient):
    """测试用的API客户端"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"


class PostsAPIClient(BaseClient):
    """测试用的API客户端（/posts端点）"""

    base_url = "https://api.example.com"
    endpoint = "/posts"
    method = "GET"


class SimplePostAPIClient(BaseClient):
    """测试用的API客户端（POST方法）"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"


class UserDetailAPIClient(BaseClient):
    """测试用的API客户端（带user_id占位符）"""

    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    method = "GET"


class UserPutAPIClient(BaseClient):
    """测试用的API客户端（PUT方法）"""

    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    method = "PUT"


class UserDeleteAPIClient(BaseClient):
    """测试用的API客户端（DELETE方法）"""

    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    method = "DELETE"


class TestBaseClientGETRequests:
    """测试 GET 请求"""

    @pytest.mark.unit
    @responses.activate
    def test_simple_get_request(self):
        """测试简单的GET请求"""
        # Arrange
        responses.add(
            responses.GET, "https://api.example.com/users", json={"users": [{"id": 1, "name": "Alice"}]}, status=200
        )
        client = SimpleAPIClient()

        # Act
        result = client.request()

        # Assert
        assert result["result"] is True
        assert result["code"] == 200
        assert "users" in result["data"]

    @pytest.mark.unit
    @responses.activate
    def test_get_request_with_params(self):
        """测试带查询参数的GET请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)
        client = SimpleAPIClient()

        # Act - request_data 直接传入参数，会被自动放入 params
        result = client.request({"page": 1, "limit": 10})

        # Assert
        assert result["result"] is True
        assert len(responses.calls) == 1
        assert "page=1" in responses.calls[0].request.url
        assert "limit=10" in responses.calls[0].request.url

    @pytest.mark.unit
    @responses.activate
    def test_get_request_with_custom_endpoint(self):
        """测试自定义端点的GET请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/posts", json={"posts": []}, status=200)
        client = PostsAPIClient()

        # Act
        result = client.request()

        # Assert
        assert result["result"] is True
        assert responses.calls[0].request.url == "https://api.example.com/posts"

    @pytest.mark.unit
    @responses.activate
    def test_get_request_with_headers(self):
        """测试带自定义请求头的GET请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        # 通过 __init__ 参数传递 headers
        client = SimpleAPIClient(headers={"X-Custom-Header": "test-value", "Accept": "application/json"})

        # Act
        result = client.request()

        # Assert
        assert result["result"] is True
        assert responses.calls[0].request.headers["X-Custom-Header"] == "test-value"


class TestBaseClientPOSTRequests:
    """测试 POST 请求"""

    @pytest.mark.unit
    @responses.activate
    def test_post_request_with_json_data(self):
        """测试带JSON数据的POST请求"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1, "name": "Bob"}, status=201)
        client = SimplePostAPIClient()

        # Act
        result = client.request({"json": {"name": "Bob", "email": "bob@example.com"}})

        # Assert
        assert result["result"] is True
        assert result["code"] == 201
        assert result["data"]["name"] == "Bob"

    @pytest.mark.unit
    @responses.activate
    def test_post_request_with_form_data(self):
        """测试带表单数据的POST请求"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"success": True}, status=200)
        client = SimplePostAPIClient()

        # Act
        result = client.request({"data": {"username": "alice", "password": "secret"}})

        # Assert
        assert result["result"] is True
        assert len(responses.calls) == 1


class TestBaseClientPUTRequests:
    """测试 PUT 请求"""

    @pytest.mark.unit
    @responses.activate
    def test_put_request(self):
        """测试PUT请求"""
        # Arrange
        responses.add(
            responses.PUT, "https://api.example.com/users/1", json={"id": 1, "name": "Updated Name"}, status=200
        )
        client = UserPutAPIClient()

        # Act
        result = client.request({"user_id": 1, "json": {"name": "Updated Name"}})

        # Assert
        assert result["result"] is True
        assert result["data"]["name"] == "Updated Name"


class TestBaseClientDELETERequests:
    """测试 DELETE 请求"""

    @pytest.mark.unit
    @responses.activate
    def test_delete_request(self):
        """测试DELETE请求"""
        # Arrange - 204 状态码通常不返回内容
        responses.add(responses.DELETE, "https://api.example.com/users/1", status=200, json={"success": True})
        client = UserDeleteAPIClient()

        # Act
        result = client.request({"user_id": 1})

        # Assert
        assert result["result"] is True


class TestBaseClientErrorHandling:
    """测试错误处理"""

    @pytest.mark.unit
    @responses.activate
    def test_http_404_error(self):
        """测试404错误"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/999", json={"error": "Not Found"}, status=404)
        client = UserDetailAPIClient()

        # Act
        result = client.request({"user_id": 999})

        # Assert
        assert result["result"] is False
        # HTTP 错误会被捕获并设置 status_code
        assert result["code"] in (404, -1)  # 根据实现，可能是 404 或 -1

    @pytest.mark.unit
    @responses.activate
    def test_http_500_error(self):
        """测试500错误"""
        # Arrange
        responses.add(
            responses.GET, "https://api.example.com/users", json={"error": "Internal Server Error"}, status=500
        )
        client = SimpleAPIClient()

        # Act
        result = client.request()

        # Assert
        assert result["result"] is False
        # HTTP 错误会被捕获并设置 status_code
        assert result["code"] in (500, -1)  # 根据实现，可能是 500 或 -1

    @pytest.mark.unit
    def test_timeout_error(self):
        """测试超时错误"""
        # Arrange
        client = SimpleAPIClient(timeout=0.001)

        with patch.object(client.session, "request") as mock_request:
            import requests

            mock_request.side_effect = requests.exceptions.Timeout("Request timeout")

            # Act
            result = client.request()

            # Assert
            assert result["result"] is False
            assert result["code"] == -1

    @pytest.mark.unit
    def test_network_error(self):
        """测试网络错误"""
        # Arrange
        client = SimpleAPIClient()

        with patch.object(client.session, "request") as mock_request:
            import requests

            mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")

            # Act
            result = client.request()

            # Assert
            assert result["result"] is False
            assert result["code"] == -1


class TestBaseClientBatchRequests:
    """测试批量请求"""

    @pytest.mark.unit
    @responses.activate
    def test_batch_get_requests_sync(self):
        """测试同步批量GET请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1, "name": "Alice"}, status=200)
        responses.add(responses.GET, "https://api.example.com/users/2", json={"id": 2, "name": "Bob"}, status=200)
        client = UserDetailAPIClient()

        # Act
        results = client.request([{"user_id": 1}, {"user_id": 2}], is_async=False)

        # Assert
        assert len(results) == 2
        assert results[0]["data"]["name"] == "Alice"
        assert results[1]["data"]["name"] == "Bob"

    @pytest.mark.unit
    @responses.activate
    def test_batch_get_requests_async(self):
        """测试异步批量GET请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1, "name": "Alice"}, status=200)
        responses.add(responses.GET, "https://api.example.com/users/2", json={"id": 2, "name": "Bob"}, status=200)
        client = UserDetailAPIClient()

        # Act
        results = client.request([{"user_id": 1}, {"user_id": 2}], is_async=True)

        # Assert
        assert len(results) == 2
        # 异步请求结果顺序可能不同，所以检查是否都存在
        names = {r["data"]["name"] for r in results}
        assert "Alice" in names
        assert "Bob" in names

    @pytest.mark.unit
    @responses.activate
    def test_batch_mixed_methods(self):
        """测试混合方法的批量请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1, "name": "Alice"}, status=200)
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 2, "name": "Bob"}, status=201)
        get_client = UserDetailAPIClient()
        post_client = SimplePostAPIClient()

        # Act
        get_result = get_client.request({"user_id": 1})
        post_result = post_client.request({"json": {"name": "Bob"}})

        # Assert
        assert get_result["code"] == 200
        assert post_result["code"] == 201


class TestBaseClientContextManager:
    """测试上下文管理器"""

    @pytest.mark.unit
    @responses.activate
    def test_context_manager_usage(self):
        """测试使用上下文管理器"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        # Act & Assert
        with SimpleAPIClient() as client:
            result = client.request()
            assert result["result"] is True

    @pytest.mark.unit
    @responses.activate
    def test_class_method_call(self):
        """测试类方法调用"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        # Act
        result = SimpleAPIClient.request()

        # Assert
        assert result["result"] is True
