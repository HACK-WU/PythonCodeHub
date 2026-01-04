"""
BaseClient 序列化器测试

测试请求序列化器功能:
- 请求参数验证
- 参数转换
- 自定义序列化器
- 序列化错误处理
"""

import pytest
import responses
from http_client.client import BaseClient
from http_client.serializer import BaseRequestSerializer
from http_client.exceptions import APIClientValidationError


class SimpleSerializerClient(BaseClient):
    """测试用的客户端"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"


class SimpleSerializerPostClient(BaseClient):
    """测试用的客户端（POST方法）"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"


class TestRequestSerializerBasic:
    """测试基本序列化器功能"""

    @pytest.mark.unit
    @responses.activate
    def test_request_with_serializer(self):
        """测试带序列化器的请求"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1, "name": "Alice"}, status=201)

        class UserSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                # 验证必需字段
                if "json" not in request_config:
                    raise APIClientValidationError("json field is required")
                data = request_config["json"]
                if "name" not in data:
                    raise APIClientValidationError("name is required")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = UserSerializer

        client = ClientWithSerializer()

        # Act
        result = client.request({"json": {"name": "Alice", "email": "alice@example.com"}})

        # Assert
        assert result["result"] is True
        assert result["data"]["name"] == "Alice"

    @pytest.mark.unit
    def test_serializer_validation_error(self):
        """测试序列化器验证错误"""

        # Arrange
        class StrictSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                if "json" not in request_config:
                    raise APIClientValidationError("json field is required")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = StrictSerializer

        client = ClientWithSerializer()

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="json field is required"):
            client.request()


class TestRequestSerializerTransformation:
    """测试序列化器数据转换"""

    @pytest.mark.unit
    @responses.activate
    def test_serializer_transforms_data(self):
        """测试序列化器转换数据"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class TransformSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                # 转换数据格式：将所有字符串转为大写
                transformed = {k: v.upper() if isinstance(v, str) else v for k, v in request_config.items()}
                return transformed

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = TransformSerializer

        client = ClientWithSerializer()

        # Act
        result = client.request({"name": "alice"})

        # Assert
        assert result["result"] is True
        # 验证请求数据被转换
        assert responses.calls[0].request.body == b'{"name": "ALICE"}'

    @pytest.mark.unit
    @responses.activate
    def test_serializer_adds_default_values(self):
        """测试序列化器添加默认值"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class DefaultValueSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                # 添加默认值
                request_config.setdefault("status", "active")
                request_config.setdefault("role", "user")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = DefaultValueSerializer

        client = ClientWithSerializer()

        # Act
        result = client.request({"name": "Alice"})

        # Assert
        assert result["result"] is True
        # 验证默认值被添加
        import json

        body = json.loads(responses.calls[0].request.body)
        assert body["status"] == "active"
        assert body["role"] == "user"


class TestRequestSerializerInnerClass:
    """测试内嵌序列化器类"""

    @pytest.mark.unit
    @responses.activate
    def test_inner_serializer_class(self):
        """测试使用内嵌序列化器类"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class ClientWithInnerSerializer(SimpleSerializerPostClient):
            class RequestSerializer(BaseRequestSerializer):
                def validate(self, request_config):
                    if "json" in request_config:
                        data = request_config["json"]
                        if "email" in data and "@" not in data["email"]:
                            raise APIClientValidationError("Invalid email format")
                    return request_config

        client = ClientWithInnerSerializer()

        # Act & Assert - 有效邮箱
        result = client.request({"json": {"name": "Alice", "email": "alice@example.com"}})
        assert result["result"] is True

        # Act & Assert - 无效邮箱
        with pytest.raises(APIClientValidationError, match="Invalid email format"):
            client.request({"json": {"name": "Bob", "email": "invalid-email"}})


class TestRequestSerializerInstance:
    """测试序列化器实例"""

    @pytest.mark.unit
    @responses.activate
    def test_serializer_instance_parameter(self):
        """测试通过参数传递序列化器实例"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class CustomSerializer(BaseRequestSerializer):
            def __init__(self, required_fields):
                self.required_fields = required_fields

            def validate(self, request_config):
                if "json" in request_config:
                    data = request_config["json"]
                    for field in self.required_fields:
                        if field not in data:
                            raise APIClientValidationError(f"{field} is required")
                return request_config

        serializer = CustomSerializer(required_fields=["name", "email"])
        client = SimpleSerializerPostClient(request_serializer=serializer)

        # Act & Assert - 缺少必需字段
        with pytest.raises(APIClientValidationError, match="email is required"):
            client.request({"json": {"name": "Alice"}})

        # Act & Assert - 包含所有必需字段
        result = client.request({"json": {"name": "Alice", "email": "alice@example.com"}})
        assert result["result"] is True


class TestRequestSerializerBatchRequests:
    """测试批量请求的序列化"""

    @pytest.mark.unit
    @responses.activate
    def test_serializer_validates_batch_requests(self):
        """测试序列化器验证批量请求"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 2}, status=201)

        class BatchSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                if "json" in request_config:
                    data = request_config["json"]
                    if "name" not in data:
                        raise APIClientValidationError("name is required")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = BatchSerializer

        client = ClientWithSerializer()

        # Act
        results = client.request([{"json": {"name": "Alice"}}, {"json": {"name": "Bob"}}])

        # Assert
        assert len(results) == 2
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_serializer_batch_partial_validation_error(self):
        """测试批量请求验证错误时直接抛出异常"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class StrictSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                if "name" not in request_config:
                    raise APIClientValidationError("name is required")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = StrictSerializer

        client = ClientWithSerializer()

        # Act & Assert - 批量请求中有验证错误时会直接抛出异常
        with pytest.raises(APIClientValidationError, match="name is required"):
            client.request(
                [
                    {"name": "Alice"},
                    {"email": "bob@example.com"},  # 缺少name
                ]
            )


class TestRequestSerializerComplexValidation:
    """测试复杂验证场景"""

    @pytest.mark.unit
    @responses.activate
    def test_serializer_nested_data_validation(self):
        """测试嵌套数据验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class NestedSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                if "json" in request_config:
                    data = request_config["json"]
                    if "address" in data:
                        address = data["address"]
                        if not isinstance(address, dict):
                            raise APIClientValidationError("address must be a dict")
                        if "city" not in address:
                            raise APIClientValidationError("address.city is required")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = NestedSerializer

        client = ClientWithSerializer()

        # Act & Assert - 有效嵌套数据
        result = client.request({"json": {"name": "Alice", "address": {"city": "Beijing", "street": "Main St"}}})
        assert result["result"] is True

        # Act & Assert - 无效嵌套数据
        with pytest.raises(APIClientValidationError, match="address.city is required"):
            client.request({"json": {"name": "Bob", "address": {"street": "Main St"}}})

    @pytest.mark.unit
    @responses.activate
    def test_serializer_conditional_validation(self):
        """测试条件验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class ConditionalSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                if "json" in request_config:
                    data = request_config["json"]
                    # 如果提供了email，必须是有效格式
                    if "email" in data and "@" not in data["email"]:
                        raise APIClientValidationError("Invalid email format")
                    # 如果role是admin，必须提供password
                    if data.get("role") == "admin" and "password" not in data:
                        raise APIClientValidationError("Admin must have password")
                return request_config

        class ClientWithSerializer(SimpleSerializerPostClient):
            request_serializer_class = ConditionalSerializer

        client = ClientWithSerializer()

        # Act & Assert - 普通用户不需要密码
        result = client.request({"json": {"name": "Alice", "role": "user"}})
        assert result["result"] is True

        # Act & Assert - 管理员需要密码
        with pytest.raises(APIClientValidationError, match="Admin must have password"):
            client.request({"json": {"name": "Bob", "role": "admin"}})


class TestRequestSerializerWithCache:
    """测试序列化器与缓存的配合"""

    @pytest.mark.unit
    @responses.activate
    def test_serializer_with_cache_client(self):
        """测试序列化器与缓存客户端配合使用"""
        # Arrange
        from http_client.cache import CacheClient, InMemoryCacheBackend

        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        class ValidatingSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                # 验证params
                if "params" in request_config:
                    params = request_config["params"]
                    if "page" in params and params["page"] < 1:
                        raise APIClientValidationError("page must be >= 1")
                return request_config

        class CacheClientWithSerializer(CacheClient):
            base_url = "https://api.example.com"
            endpoint = "/users"
            method = "GET"
            cache_backend_class = InMemoryCacheBackend
            request_serializer_class = ValidatingSerializer

        client = CacheClientWithSerializer()

        # Act & Assert - 有效请求
        result1 = client.request({"params": {"page": 1}})
        result2 = client.request({"params": {"page": 1}})  # 应该命中缓存
        assert result1["result"] is True
        assert result2["result"] is True
        assert len(responses.calls) == 1  # 只发送一次请求

        # Act & Assert - 无效请求
        with pytest.raises(APIClientValidationError, match="page must be >= 1"):
            client.request({"params": {"page": 0}})


class TestRequestSerializerErrorHandling:
    """测试序列化器错误处理"""

    @pytest.mark.unit
    def test_serializer_exception_propagation(self):
        """测试序列化器异常传播"""

        # Arrange
        class FailingSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                raise APIClientValidationError("Validation failed")

        class ClientWithSerializer(SimpleSerializerClient):
            request_serializer_class = FailingSerializer

        client = ClientWithSerializer()

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="Validation failed"):
            client.request()

    @pytest.mark.unit
    @responses.activate
    def test_serializer_none_return_value(self):
        """测试序列化器返回None"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users", json={"users": []}, status=200)

        class NoneReturningSerializer(BaseRequestSerializer):
            def validate(self, request_config):
                # 返回None（不推荐，但应该处理）
                return request_config

        class ClientWithSerializer(SimpleSerializerClient):
            request_serializer_class = NoneReturningSerializer

        client = ClientWithSerializer()

        # Act
        result = client.request()

        # Assert
        assert result["result"] is True
