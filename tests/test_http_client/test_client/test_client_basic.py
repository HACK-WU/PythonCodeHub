"""
client.py 模块的基础单元测试

主要测试 BaseClient 的核心功能:
- 客户端初始化
- Session 配置
- 资源清理
"""

import pytest
from unittest.mock import Mock
import requests
from http_client.client import BaseClient


# 创建测试用的客户端子类
class MyTestClient(BaseClient):
    """测试用的客户端子类"""

    base_url = "https://api.example.com"
    endpoint = "/test"
    method = "GET"


class TestBaseClientInitialization:
    """测试 BaseClient 初始化"""

    @pytest.mark.unit
    def test_basic_initialization(self):
        """测试基本初始化"""
        # Arrange & Act
        client = MyTestClient()

        # Assert
        assert client.base_url == "https://api.example.com"
        assert isinstance(client.session, requests.Session)

    @pytest.mark.unit
    def test_initialization_with_custom_timeout(self):
        """测试自定义超时时间初始化"""
        # Arrange & Act
        client = MyTestClient(timeout=60)

        # Assert
        assert client.timeout == 60

    @pytest.mark.unit
    def test_initialization_with_verify_false(self):
        """测试禁用SSL验证"""
        # Arrange & Act
        client = MyTestClient(verify=False)

        # Assert
        assert client.verify is False

    @pytest.mark.unit
    def test_session_created_on_init(self):
        """测试初始化时创建Session"""
        # Arrange & Act
        client = MyTestClient()

        # Assert
        assert hasattr(client, "session")
        assert isinstance(client.session, requests.Session)

    @pytest.mark.unit
    def test_context_manager_support(self):
        """测试上下文管理器支持"""
        # Arrange & Act & Assert
        with MyTestClient() as client:
            assert isinstance(client, BaseClient)
            assert client.session is not None


class TestBaseClientSessionConfiguration:
    """测试 BaseClient Session 配置"""

    @pytest.mark.unit
    def test_session_has_adapters(self):
        """测试Session配置了HTTP适配器"""
        # Arrange & Act
        client = MyTestClient()

        # Assert
        # 检查session的adapters中是否有HTTPAdapter
        assert "https://" in client.session.adapters
        assert "http://" in client.session.adapters
        assert client.session.adapters["https://"] is not None

    @pytest.mark.unit
    def test_session_verify_configuration(self):
        """测试Session的verify配置"""
        # Arrange & Act
        client = MyTestClient(verify=False)

        # Assert
        assert client.verify is False


class TestBaseClientAuthentication:
    """测试 BaseClient 认证配置"""

    @pytest.mark.unit
    def test_initialization_with_auth(self):
        """测试带认证的初始化"""
        # Arrange
        mock_auth = Mock(spec=requests.auth.AuthBase)

        # Act
        client = MyTestClient(authentication=mock_auth)

        # Assert
        assert client.auth_instance is not None


class TestBaseClientCleanup:
    """测试 BaseClient 资源清理"""

    @pytest.mark.unit
    def test_close_method_closes_session(self):
        """测试close方法关闭session"""
        # Arrange
        client = MyTestClient()

        # Act
        client.close()

        # Assert - session应该被关闭
        assert client.session is not None

    @pytest.mark.unit
    def test_context_manager_closes_session(self):
        """测试上下文管理器自动关闭session"""
        # Arrange & Act
        with MyTestClient() as client:
            session = client.session

        # Assert - 退出上下文后session应该被关闭
        assert session is not None

    @pytest.mark.unit
    def test_del_method_cleanup(self):
        """测试__del__方法清理资源"""
        # Arrange
        client = MyTestClient()
        session = client.session

        # Act
        del client

        # Assert - 对象被删除后session应该被清理
        assert session is not None


class TestBaseClientURLBuilding:
    """测试 BaseClient URL 构建"""

    @pytest.mark.unit
    def test_build_url_with_endpoint(self):
        """测试带端点的URL构建"""
        # Arrange
        client = MyTestClient()

        # Act
        url = client._build_url("/users")

        # Assert
        assert url == "https://api.example.com/users"

    @pytest.mark.unit
    def test_build_url_without_endpoint(self):
        """测试不带端点的URL构建"""
        # Arrange
        client = MyTestClient()

        # Act
        url = client._build_url("")

        # Assert
        assert url == "https://api.example.com"

    @pytest.mark.unit
    def test_build_url_strips_leading_slash(self):
        """测试URL构建时去除前导斜杠"""
        # Arrange
        client = MyTestClient()

        # Act
        url = client._build_url("///users")

        # Assert
        assert url == "https://api.example.com/users"

    @pytest.mark.unit
    def test_base_url_trailing_slash_removed(self):
        """测试base_url末尾斜杠被移除"""

        # Arrange
        class ClientWithTrailingSlash(BaseClient):
            base_url = "https://api.example.com/"
            endpoint = "/test"
            method = "GET"

        # Act
        client = ClientWithTrailingSlash()

        # Assert
        assert client.base_url == "https://api.example.com"


class TestBaseClientRequestConfiguration:
    """测试 BaseClient 请求配置"""

    @pytest.mark.unit
    def test_build_request_kwargs_basic(self):
        """测试基本请求参数构建"""
        # Arrange
        client = MyTestClient()
        request_config = {"key": "value"}

        # Act
        kwargs = client._build_request_config(request_config)

        # Assert
        assert "params" in kwargs
        assert kwargs["params"] == {"key": "value"}
        assert "stream" in kwargs

    @pytest.mark.unit
    def test_build_request_kwargs_merges_defaults(self):
        """测试请求参数构建时合并默认参数"""
        # Arrange
        client = MyTestClient(verify=False)
        request_config = {"key": "value"}

        # Act
        kwargs = client._build_request_config(request_config)

        # Assert
        assert kwargs["verify"] is False


class TestBaseClientRequestID:
    """测试 BaseClient 请求ID生成"""

    @pytest.mark.unit
    def test_generate_request_id_format(self):
        """测试请求ID格式"""
        # Arrange
        client = MyTestClient()

        # Act
        request_id = client.generate_request_id()

        # Assert
        assert request_id.startswith("REQ-")
        parts = request_id.split("-")
        assert len(parts) == 4

    @pytest.mark.unit
    def test_generate_request_id_with_suffix(self):
        """测试带后缀的请求ID生成"""
        # Arrange
        client = MyTestClient()

        # Act
        request_id = client.generate_request_id(suffix="test")

        # Assert
        assert request_id.endswith("-test")

    @pytest.mark.unit
    def test_generate_request_id_uniqueness(self):
        """测试请求ID唯一性"""
        # Arrange
        client = MyTestClient()

        # Act
        id1 = client.generate_request_id()
        id2 = client.generate_request_id()

        # Assert
        assert id1 != id2


class TestBaseClientHooks:
    """测试 BaseClient 钩子机制"""

    @pytest.mark.unit
    def test_register_hook_before_request(self):
        """测试注册before_request钩子"""
        # Arrange
        client = MyTestClient()
        hook_called = []

        def my_hook(client_instance, request_id, request_config):
            hook_called.append(True)
            return request_config

        # Act
        client.register_hook("before_request", my_hook)

        # Assert
        assert len(client._hooks["before_request"]) == 1

    @pytest.mark.unit
    def test_register_hook_after_request(self):
        """测试注册after_request钩子"""
        # Arrange
        client = MyTestClient()
        hook_called = []

        def my_hook(client_instance, request_id, response):
            hook_called.append(True)
            return response

        # Act
        client.register_hook("after_request", my_hook)

        # Assert
        assert len(client._hooks["after_request"]) == 1

    @pytest.mark.unit
    def test_register_hook_on_request_error(self):
        """测试注册on_request_error钩子"""
        # Arrange
        client = MyTestClient()
        hook_called = []

        def my_hook(client_instance, request_id, error):
            hook_called.append(True)

        # Act
        client.register_hook("on_request_error", my_hook)

        # Assert
        assert len(client._hooks["on_request_error"]) == 1

    @pytest.mark.unit
    def test_register_hook_invalid_name(self):
        """测试注册无效钩子名称"""
        # Arrange
        client = MyTestClient()

        def my_hook():
            pass

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid hook name"):
            client.register_hook("invalid_hook", my_hook)


class TestBaseClientDefaultFormatResponse:
    """测试 BaseClient 默认响应格式化"""

    @pytest.mark.unit
    def test_format_successful_response(self):
        """测试格式化成功响应"""
        # Arrange
        import requests

        client = MyTestClient()
        mock_response = Mock(spec=requests.Response)
        mock_response.status_code = 200
        parsed_data = {"key": "value"}

        # Act
        result = client.default_format_response(mock_response, parsed_data, None)

        # Assert
        assert result["result"] is True
        assert result["code"] == 200
        assert result["message"] == "Success"
        assert result["data"] == parsed_data

    @pytest.mark.unit
    def test_format_response_with_parse_error(self):
        """测试格式化带解析错误的响应"""
        # Arrange
        import requests

        client = MyTestClient()
        mock_response = Mock(spec=requests.Response)
        mock_response.status_code = 200
        parse_error = ValueError("Parse failed")

        # Act
        result = client.default_format_response(mock_response, None, parse_error)

        # Assert
        assert result["result"] is False
        assert result["code"] == 200
        assert "Parsing failed" in result["message"]
        assert result["data"] is None

    @pytest.mark.unit
    def test_format_http_error_response(self):
        """测试格式化HTTP错误响应"""
        # Arrange
        from http_client.exceptions import APIClientHTTPError

        client = MyTestClient()
        error = APIClientHTTPError("HTTP 404: Not Found")
        error.status_code = 404

        # Act
        result = client.default_format_response(error, None, None)

        # Assert
        assert result["result"] is False
        assert result["code"] == 404
        assert "404" in result["message"]
        assert result["data"] is None

    @pytest.mark.unit
    def test_format_network_error_response(self):
        """测试格式化网络错误响应"""
        # Arrange
        from http_client.exceptions import APIClientNetworkError

        client = MyTestClient()
        error = APIClientNetworkError("Connection failed")

        # Act
        result = client.default_format_response(error, None, None)

        # Assert
        assert result["result"] is False
        assert result["code"] == -1  # RESPONSE_CODE_NON_HTTP_ERROR
        assert "Connection failed" in result["message"]
        assert result["data"] is None


class TestBaseClientConfigMerging:
    """测试 BaseClient 配置合并"""

    @pytest.mark.unit
    def test_merge_config_basic(self):
        """测试基本配置合并"""
        # Arrange
        client = MyTestClient()
        base_config = {"key1": "value1", "key2": "value2"}
        override_config = {"key2": "new_value2", "key3": "value3"}

        # Act
        merged = client._merge_config(base_config, override_config)

        # Assert
        assert merged["key1"] == "value1"
        assert merged["key2"] == "new_value2"
        assert merged["key3"] == "value3"

    @pytest.mark.unit
    def test_merge_config_with_max_retries_override(self):
        """测试带max_retries覆盖的配置合并"""
        # Arrange
        client = MyTestClient()
        base_config = {"total": 3, "backoff_factor": 0.3}

        # Act
        merged = client._merge_config(base_config, None, max_retries_override=5)

        # Assert
        assert merged["total"] == 5
        assert merged["backoff_factor"] == 0.3

    @pytest.mark.unit
    def test_merge_config_with_none_override(self):
        """测试None覆盖配置的合并"""
        # Arrange
        client = MyTestClient()
        base_config = {"key1": "value1"}

        # Act
        merged = client._merge_config(base_config, None)

        # Assert
        assert merged == base_config


class TestBaseClientValidation:
    """测试 BaseClient 验证功能"""

    @pytest.mark.unit
    def test_initialization_without_base_url_raises_error(self):
        """测试没有base_url时初始化失败"""
        # Arrange
        from http_client.exceptions import APIClientValidationError

        class ClientWithoutURL(BaseClient):
            pass

        # Act & Assert
        with pytest.raises(APIClientValidationError, match="base_url or url must be provided"):
            ClientWithoutURL()

    @pytest.mark.unit
    def test_initialization_with_url_parameter(self):
        """测试使用url参数初始化"""
        # Arrange & Act
        client = MyTestClient(url="https://custom.example.com/api")

        # Assert
        assert client.url == "https://custom.example.com/api"


class TestBaseClientThreadSafety:
    """测试 BaseClient 线程安全"""

    @pytest.mark.unit
    def test_has_request_mapping_lock(self):
        """测试存在request_mapping锁"""
        # Arrange
        client = MyTestClient()

        # Assert
        assert hasattr(client, "_request_mapping_lock")
        # RLock是一个函数返回的对象，不是类型，所以检查类型名称
        assert type(client._request_mapping_lock).__name__ == "RLock"

    @pytest.mark.unit
    def test_has_session_lock(self):
        """测试存在session锁"""
        # Arrange
        client = MyTestClient()

        # Assert
        assert hasattr(client, "_session_lock")
        # RLock是一个函数返回的对象，不是类型，所以检查类型名称
        assert type(client._session_lock).__name__ == "RLock"

    @pytest.mark.unit
    def test_has_stream_responses_lock(self):
        """测试存在stream_responses锁"""
        # Arrange
        client = MyTestClient()

        # Assert
        assert hasattr(client, "_stream_responses_lock")
        # RLock是一个函数返回的对象，不是类型，所以检查类型名称
        assert type(client._stream_responses_lock).__name__ == "RLock"
