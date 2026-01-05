"""
validator.py 模块的单元测试

测试用例:
- UT-VAL-001: StatusCodeValidator 验证默认允许的状态码（200）
- UT-VAL-002: StatusCodeValidator 验证自定义允许的状态码列表
- UT-VAL-003: StatusCodeValidator 严格模式拒绝未授权的状态码
- UT-VAL-004: StatusCodeValidator 非严格模式的行为
- UT-VAL-005: StatusCodeValidator 处理集合类型的 allowed_codes
- UT-VAL-006: StatusCodeValidator 在有 parsed_data 时跳过验证
- UT-VAL-007: BaseResponseValidator 抽象方法验证
"""

import pytest
from abc import ABC
from unittest.mock import Mock
from http_client.validator import BaseResponseValidator, StatusCodeValidator
from http_client.exceptions import APIClientResponseValidationError


class TestBaseResponseValidator:
    """测试 BaseResponseValidator 抽象基类"""

    @pytest.mark.unit
    def test_is_abstract_class(self):
        """UT-VAL-007: BaseResponseValidator 是抽象类"""
        # Arrange & Act & Assert
        assert issubclass(BaseResponseValidator, ABC)

        # 验证不能直接实例化
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseResponseValidator()

    @pytest.mark.unit
    def test_has_abstract_validate_method(self):
        """UT-VAL-007: BaseResponseValidator 有抽象 validate 方法"""
        # Arrange & Act & Assert
        assert hasattr(BaseResponseValidator, "validate")
        assert getattr(BaseResponseValidator.validate, "__isabstractmethod__", False)


class TestStatusCodeValidatorInitialization:
    """测试 StatusCodeValidator 初始化"""

    @pytest.mark.unit
    def test_default_initialization(self):
        """验证默认初始化（只允许 200）"""
        # Arrange & Act
        validator = StatusCodeValidator()

        # Assert
        assert validator.allowed_codes == {200}
        assert validator.strict_mode is True

    @pytest.mark.unit
    def test_initialization_with_list(self):
        """UT-VAL-002: 使用列表初始化允许的状态码"""
        # Arrange & Act
        validator = StatusCodeValidator(allowed_codes=[200, 201, 204])

        # Assert
        assert validator.allowed_codes == {200, 201, 204}
        assert validator.strict_mode is True

    @pytest.mark.unit
    def test_initialization_with_set(self):
        """UT-VAL-005: 使用集合初始化允许的状态码"""
        # Arrange & Act
        validator = StatusCodeValidator(allowed_codes={200, 201, 202})

        # Assert
        assert validator.allowed_codes == {200, 201, 202}

    @pytest.mark.unit
    def test_initialization_with_strict_mode_false(self):
        """UT-VAL-004: 初始化时设置非严格模式"""
        # Arrange & Act
        validator = StatusCodeValidator(allowed_codes=[200], strict_mode=False)

        # Assert
        assert validator.allowed_codes == {200}
        assert validator.strict_mode is False

    @pytest.mark.unit
    def test_initialization_with_none(self):
        """验证 allowed_codes 为 None 时使用默认值"""
        # Arrange & Act
        validator = StatusCodeValidator(allowed_codes=None)

        # Assert
        assert validator.allowed_codes == {200}


class TestStatusCodeValidatorValidation:
    """测试 StatusCodeValidator 验证逻辑"""

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.fixture
    def mock_response(self):
        """Mock Response 对象"""
        response = Mock()
        response.status_code = 200
        response.url = "https://api.example.com/test"
        return response

    @pytest.mark.unit
    def test_validate_allowed_status_code_200(self, mock_client, mock_response):
        """UT-VAL-001: 验证默认允许的状态码（200）"""
        # Arrange
        validator = StatusCodeValidator()
        mock_response.status_code = 200

        # Act & Assert - 不应抛出异常
        validator.validate(mock_client, mock_response, parsed_data=None)

    @pytest.mark.unit
    def test_validate_custom_allowed_codes(self, mock_client, mock_response):
        """UT-VAL-002: 验证自定义允许的状态码"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200, 201, 204])

        # Act & Assert - 测试所有允许的状态码
        for code in [200, 201, 204]:
            mock_response.status_code = code
            validator.validate(mock_client, mock_response, parsed_data=None)

    @pytest.mark.unit
    def test_validate_rejects_unauthorized_code_strict_mode(self, mock_client, mock_response):
        """UT-VAL-003: 严格模式拒绝未授权的状态码"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200, 201])
        mock_response.status_code = 404

        # Act & Assert
        with pytest.raises(APIClientResponseValidationError) as exc_info:
            validator.validate(mock_client, mock_response, parsed_data=None)

        # 验证异常信息
        assert "404" in str(exc_info.value)
        assert "not in allowed codes" in str(exc_info.value)
        assert exc_info.value.response == mock_response
        assert exc_info.value.validation_result == {"status_code": 404, "allowed_codes": [200, 201]}

    @pytest.mark.unit
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 500, 502, 503])
    def test_validate_rejects_various_error_codes(self, mock_client, mock_response, status_code):
        """参数化测试: 严格模式拒绝各种错误状态码"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200])
        mock_response.status_code = status_code

        # Act & Assert
        with pytest.raises(APIClientResponseValidationError) as exc_info:
            validator.validate(mock_client, mock_response, parsed_data=None)

        assert exc_info.value.validation_result["status_code"] == status_code

    @pytest.mark.unit
    def test_validate_non_strict_mode_allows_any_code(self, mock_client, mock_response):
        """UT-VAL-004: 非严格模式不验证状态码"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200], strict_mode=False)
        mock_response.status_code = 404

        # Act & Assert - 非严格模式不应抛出异常
        validator.validate(mock_client, mock_response, parsed_data=None)

    @pytest.mark.unit
    def test_validate_skips_when_parsed_data_exists(self, mock_client, mock_response):
        """UT-VAL-006: 当存在 parsed_data 时跳过验证"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200])
        mock_response.status_code = 404
        parsed_data = {"result": "some data"}

        # Act & Assert - 有 parsed_data 时不应验证，不抛出异常
        validator.validate(mock_client, mock_response, parsed_data=parsed_data)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "parsed_data",
        [
            {"key": "value"},
            [],
            "string data",
            123,
            True,
        ],
    )
    def test_validate_skips_with_various_parsed_data(self, mock_client, mock_response, parsed_data):
        """参数化测试: 各种类型的 parsed_data 都会跳过验证"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200])
        mock_response.status_code = 500

        # Act & Assert
        validator.validate(mock_client, mock_response, parsed_data=parsed_data)

    @pytest.mark.unit
    def test_validate_error_message_format(self, mock_client, mock_response):
        """验证错误消息的格式"""
        # Arrange
        validator = StatusCodeValidator(allowed_codes=[200, 201])
        mock_response.status_code = 404

        # Act & Assert
        with pytest.raises(APIClientResponseValidationError) as exc_info:
            validator.validate(mock_client, mock_response, parsed_data=None)

        error_msg = str(exc_info.value)
        assert "404" in error_msg
        assert "200" in error_msg or "201" in error_msg

    @pytest.mark.unit
    def test_validator_is_instance_of_base(self):
        """验证 StatusCodeValidator 是 BaseResponseValidator 的实例"""
        # Arrange & Act
        validator = StatusCodeValidator()

        # Assert
        assert isinstance(validator, BaseResponseValidator)
        assert isinstance(validator, StatusCodeValidator)

    @pytest.mark.unit
    def test_allowed_codes_immutability(self):
        """验证 allowed_codes 转换为集合后的行为"""
        # Arrange
        original_list = [200, 201, 200, 201]  # 包含重复项
        validator = StatusCodeValidator(allowed_codes=original_list)

        # Act & Assert
        assert validator.allowed_codes == {200, 201}
        assert len(validator.allowed_codes) == 2
