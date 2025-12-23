"""
测试 http_client.exceptions 模块

测试异常类的实例化、属性和继承关系
"""

import pytest
from unittest.mock import Mock
from http_client.exceptions import (
    APIClientError,
    APIClientHTTPError,
    APIClientNetworkError,
    APIClientTimeoutError,
    APIClientValidationError,
    APIClientRequestValidationError,
    APIClientResponseValidationError,
)


class TestAPIClientHTTPError:
    """测试 APIClientHTTPError 异常类"""

    @pytest.mark.unit
    def test_initialization_with_response(self):
        """UT-EXC-001: 带 response 的初始化"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.reason = 'Not Found'
        
        error = APIClientHTTPError("Not found error", response=mock_response)
        
        assert str(error) == "Not found error"
        assert error.response == mock_response
        assert error.status_code == 404

    @pytest.mark.unit
    def test_initialization_without_response(self):
        """UT-EXC-002: 不带 response 的初始化"""
        error = APIClientHTTPError("HTTP error")
        
        assert str(error) == "HTTP error"
        assert error.response is None
        assert error.status_code is None

    @pytest.mark.unit
    def test_inherits_from_base(self):
        """UT-EXC-005: 继承自 APIClientError"""
        error = APIClientHTTPError("Test")
        
        assert isinstance(error, APIClientError)
        assert isinstance(error, Exception)


class TestAPIClientRequestValidationError:
    """测试 APIClientRequestValidationError 异常类"""

    @pytest.mark.unit
    def test_initialization_with_errors(self):
        """UT-EXC-003: 带 errors 字典的初始化"""
        errors = {
            'username': ['Username is required'],
            'email': ['Invalid email format']
        }
        
        error = APIClientRequestValidationError("Validation failed", errors=errors)
        
        assert str(error) == "Validation failed"
        assert error.errors == errors
        assert 'username' in error.errors
        assert 'email' in error.errors

    @pytest.mark.unit
    def test_initialization_without_errors(self):
        """测试不带 errors 的初始化"""
        error = APIClientRequestValidationError("Validation failed")
        
        assert str(error) == "Validation failed"
        assert error.errors == {}


class TestAPIClientResponseValidationError:
    """测试 APIClientResponseValidationError 异常类"""

    @pytest.mark.unit
    def test_initialization_with_all_params(self):
        """UT-EXC-004: 带 response 和 validation_result 的初始化"""
        mock_response = Mock()
        mock_response.status_code = 200
        validation_result = {'status_code': 200, 'allowed_codes': [201, 202]}
        
        error = APIClientResponseValidationError(
            "Status code not allowed",
            response=mock_response,
            validation_result=validation_result
        )
        
        assert str(error) == "Status code not allowed"
        assert error.response == mock_response
        assert error.validation_result == validation_result

    @pytest.mark.unit
    def test_initialization_minimal(self):
        """测试最少参数初始化"""
        error = APIClientResponseValidationError("Validation error")
        
        assert error.response is None
        assert error.validation_result == {}


class TestExceptionHierarchy:
    """测试异常继承关系"""

    @pytest.mark.unit
    def test_all_exceptions_inherit_from_base(self):
        """UT-EXC-005: 所有异常继承自 APIClientError"""
        exceptions = [
            APIClientHTTPError("test"),
            APIClientNetworkError("test"),
            APIClientTimeoutError("test"),
            APIClientValidationError("test"),
            APIClientRequestValidationError("test"),
            APIClientResponseValidationError("test"),
        ]
        
        for exc in exceptions:
            assert isinstance(exc, APIClientError)
            assert isinstance(exc, Exception)

    @pytest.mark.unit
    def test_exception_message_str(self):
        """UT-EXC-006: 异常消息字符串化"""
        test_message = "This is a test error"
        exceptions = [
            APIClientError(test_message),
            APIClientHTTPError(test_message),
            APIClientNetworkError(test_message),
            APIClientTimeoutError(test_message),
            APIClientValidationError(test_message),
        ]
        
        for exc in exceptions:
            assert str(exc) == test_message


class TestOtherExceptions:
    """测试其他异常类"""

    @pytest.mark.unit
    def test_network_error(self):
        """测试 APIClientNetworkError"""
        error = APIClientNetworkError("Network connection failed")
        
        assert str(error) == "Network connection failed"
        assert isinstance(error, APIClientError)

    @pytest.mark.unit
    def test_timeout_error(self):
        """测试 APIClientTimeoutError"""
        error = APIClientTimeoutError("Request timed out")
        
        assert str(error) == "Request timed out"
        assert isinstance(error, APIClientError)

    @pytest.mark.unit
    def test_validation_error(self):
        """测试 APIClientValidationError"""
        error = APIClientValidationError("Invalid configuration")
        
        assert str(error) == "Invalid configuration"
        assert isinstance(error, APIClientError)


class TestExceptionUsage:
    """测试异常的实际使用场景"""

    @pytest.mark.unit
    def test_raise_and_catch_http_error(self):
        """测试抛出和捕获 HTTP 错误"""
        mock_response = Mock()
        mock_response.status_code = 500
        
        with pytest.raises(APIClientHTTPError) as exc_info:
            raise APIClientHTTPError("Server error", response=mock_response)
        
        assert exc_info.value.status_code == 500

    @pytest.mark.unit
    def test_raise_and_catch_base_error(self):
        """测试捕获基类异常"""
        with pytest.raises(APIClientError):
            raise APIClientHTTPError("Test error")

    @pytest.mark.unit
    def test_exception_with_cause(self):
        """测试异常链"""
        original_error = ValueError("Original error")
        
        try:
            raise APIClientNetworkError("Network error") from original_error
        except APIClientNetworkError as e:
            assert e.__cause__ == original_error
