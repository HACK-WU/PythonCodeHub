"""
DRFClient 测试

测试 DRF Serializer 集成功能:
- DRF Serializer 字段验证
- 批量请求验证 (many=True)
- 验证错误处理
- 嵌套序列化器
- 自定义验证方法
- 与缓存集成
"""

import pytest
import responses
import django
from django.conf import settings

# 配置 Django 设置
if not settings.configured:
    settings.configure(
        DEBUG=True,
        SECRET_KEY="test-secret-key",
        USE_I18N=True,
        USE_L10N=True,
        USE_TZ=True,
    )
    django.setup()

from rest_framework import serializers

from http_client.client import DRFClient
from http_client.exceptions import APIClientRequestValidationError


class SimpleDRFClient(DRFClient):
    """测试用的基础 DRF 客户端"""

    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"


class TestDRFClientBasic:
    """测试 DRFClient 基本功能"""

    @pytest.mark.unit
    @responses.activate
    def test_drf_serializer_validation_success(self):
        """测试 DRF Serializer 验证成功"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1, "username": "john"}, status=201)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100, required=True)
            email = serializers.EmailField(required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - DRF Serializer 直接验证 request_data
        result = client.request({"username": "john", "email": "john@example.com"})

        # Assert
        assert result["result"] is True
        assert result["data"]["username"] == "john"

    @pytest.mark.unit
    def test_drf_serializer_validation_error(self):
        """测试 DRF Serializer 验证失败"""

        # Arrange
        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100, required=True)
            email = serializers.EmailField(required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act & Assert - 缺少必需字段
        with pytest.raises(APIClientRequestValidationError, match="请求参数验证失败"):
            client.request({"username": "john"})  # 缺少 email

    @pytest.mark.unit
    def test_drf_serializer_invalid_email(self):
        """测试 DRF EmailField 验证"""

        # Arrange
        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)
            email = serializers.EmailField()

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act & Assert
        with pytest.raises(APIClientRequestValidationError):
            client.request({"username": "john", "email": "invalid-email"})


class TestDRFClientFieldTypes:
    """测试不同字段类型的验证"""

    @pytest.mark.unit
    @responses.activate
    def test_integer_field_validation(self):
        """测试 IntegerField 验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            age = serializers.IntegerField(min_value=0, max_value=150, required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - 有效年龄
        result = client.request({"age": 25})
        assert result["result"] is True

        # Act & Assert - 年龄超出范围
        with pytest.raises(APIClientRequestValidationError):
            client.request({"age": 200})

    @pytest.mark.unit
    @responses.activate
    def test_choice_field_validation(self):
        """测试 ChoiceField 验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            role = serializers.ChoiceField(choices=["admin", "user", "guest"])

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - 有效选择
        result = client.request({"role": "admin"})
        assert result["result"] is True

        # Act & Assert - 无效选择
        with pytest.raises(APIClientRequestValidationError):
            client.request({"role": "superuser"})

    @pytest.mark.unit
    @responses.activate
    def test_boolean_field_validation(self):
        """测试 BooleanField 验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            is_active = serializers.BooleanField(default=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act
        result = client.request({"is_active": False})

        # Assert
        assert result["result"] is True


class TestDRFClientNestedSerializer:
    """测试嵌套序列化器"""

    @pytest.mark.unit
    @responses.activate
    def test_nested_serializer(self):
        """测试嵌套序列化器验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class AddressSerializer(serializers.Serializer):
            city = serializers.CharField(required=True)
            street = serializers.CharField(required=True)
            zip_code = serializers.CharField(max_length=10)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)
            address = AddressSerializer(required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - 有效嵌套数据
        result = client.request(
            {"username": "john", "address": {"city": "Beijing", "street": "Main St", "zip_code": "100000"}}
        )
        assert result["result"] is True

        # Act & Assert - 嵌套数据缺少必需字段
        with pytest.raises(APIClientRequestValidationError):
            client.request({"username": "john", "address": {"city": "Beijing"}})  # 缺少 street

    @pytest.mark.unit
    @responses.activate
    def test_list_field_validation(self):
        """测试 ListField 验证"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            tags = serializers.ListField(child=serializers.CharField(), required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act
        result = client.request({"tags": ["python", "django", "drf"]})

        # Assert
        assert result["result"] is True


class TestDRFClientCustomValidation:
    """测试自定义验证方法"""

    @pytest.mark.unit
    @responses.activate
    def test_custom_validate_method(self):
        """测试自定义 validate 方法"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)
            password = serializers.CharField(max_length=100)
            confirm_password = serializers.CharField(max_length=100)

            def validate(self, data):
                if data.get("password") != data.get("confirm_password"):
                    raise serializers.ValidationError("Passwords do not match")
                return data

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - 密码匹配
        result = client.request({"username": "john", "password": "secret123", "confirm_password": "secret123"})
        assert result["result"] is True

        # Act & Assert - 密码不匹配
        with pytest.raises(APIClientRequestValidationError):
            client.request({"username": "john", "password": "secret123", "confirm_password": "different"})

    @pytest.mark.unit
    def test_field_level_validation(self):
        """测试字段级别验证"""

        # Arrange
        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)

            def validate_username(self, value):
                if value.lower() in ["admin", "root"]:
                    raise serializers.ValidationError("Reserved username")
                return value

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act & Assert
        with pytest.raises(APIClientRequestValidationError):
            client.request({"username": "admin"})


class TestDRFClientBatchRequests:
    """测试批量请求验证"""

    @pytest.mark.unit
    @responses.activate
    def test_batch_requests_with_drf_serializer(self):
        """测试批量请求使用 DRF Serializer 验证"""
        # Arrange
        for i in range(3):
            responses.add(responses.POST, "https://api.example.com/users", json={"id": i}, status=201)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100, required=True)
            email = serializers.EmailField(required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act
        results = client.request(
            [
                {"username": "user1", "email": "user1@example.com"},
                {"username": "user2", "email": "user2@example.com"},
                {"username": "user3", "email": "user3@example.com"},
            ]
        )

        # Assert
        assert len(results) == 3
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    def test_batch_requests_validation_error(self):
        """测试批量请求中有验证错误"""

        # Arrange
        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100, required=True)
            email = serializers.EmailField(required=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act & Assert - 批量请求中有无效数据
        with pytest.raises(APIClientRequestValidationError):
            client.request(
                [
                    {"username": "user1", "email": "user1@example.com"},
                    {"username": "user2"},  # 缺少 email
                ]
            )


class TestDRFClientInnerSerializer:
    """测试内嵌序列化器"""

    @pytest.mark.unit
    @responses.activate
    def test_inner_drf_serializer(self):
        """测试使用内嵌的 DRF Serializer"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserClient(SimpleDRFClient):
            class RequestSerializer(serializers.Serializer):
                username = serializers.CharField(max_length=100, required=True)
                age = serializers.IntegerField(min_value=0, required=True)

        client = UserClient()

        # Act
        result = client.request({"username": "john", "age": 25})

        # Assert
        assert result["result"] is True


class TestDRFClientEdgeCases:
    """测试边缘情况"""

    @pytest.mark.unit
    def test_no_serializer_configured(self):
        """测试未配置序列化器"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserClient(SimpleDRFClient):
            pass

        client = UserClient()

        # Act - 应该正常工作，不进行验证
        # 由于没有 mock 响应，这里只测试验证部分
        assert client.request_serializer_instance is None

    @pytest.mark.unit
    def test_invalid_serializer_type(self):
        """测试配置了无效的序列化器类型"""

        # Arrange
        class NotASerializer:
            pass

        # Act & Assert
        with pytest.raises(Exception):  # 应该在初始化时抛出异常

            class UserClient(SimpleDRFClient):
                request_serializer_class = NotASerializer

            UserClient()

    @pytest.mark.unit
    @responses.activate
    def test_serializer_with_default_values(self):
        """测试带默认值的序列化器"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)
            role = serializers.CharField(default="user")
            is_active = serializers.BooleanField(default=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - 只提供 username，其他字段使用默认值
        result = client.request({"username": "john"})

        # Assert
        assert result["result"] is True


class TestDRFClientIntegration:
    """测试 DRFClient 与其他功能的集成"""

    @pytest.mark.unit
    @responses.activate
    def test_drf_with_hooks(self):
        """测试 DRF Serializer 与钩子的集成"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        execution_order = []

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        def before_hook(client_instance, request_id, request_data):
            execution_order.append("before_hook")
            return request_data

        client.register_hook("before_request", before_hook)

        # Act
        result = client.request({"username": "john"})

        # Assert
        assert result["result"] is True
        assert "before_hook" in execution_order

    @pytest.mark.unit
    @responses.activate
    def test_drf_serializer_with_read_only_fields(self):
        """测试带只读字段的序列化器"""
        # Arrange
        responses.add(responses.POST, "https://api.example.com/users", json={"id": 1}, status=201)

        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100)
            created_at = serializers.DateTimeField(read_only=True)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act - read_only 字段会被忽略
        result = client.request({"username": "john", "created_at": "2024-01-01"})

        # Assert
        assert result["result"] is True


class TestDRFClientErrorMessages:
    """测试错误消息"""

    @pytest.mark.unit
    def test_validation_error_details(self):
        """测试验证错误包含详细信息"""

        # Arrange
        class UserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=5, required=True)
            email = serializers.EmailField(required=True)
            age = serializers.IntegerField(min_value=0, max_value=150)

        class UserClient(SimpleDRFClient):
            request_serializer_class = UserSerializer

        client = UserClient()

        # Act & Assert
        try:
            client.request({"username": "verylongusername", "email": "invalid", "age": 200})
            assert False, "Should raise validation error"
        except APIClientRequestValidationError as e:
            # 验证错误消息包含详细信息
            assert hasattr(e, "errors")
            assert e.errors is not None
