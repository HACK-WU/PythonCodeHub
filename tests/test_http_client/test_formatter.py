"""
formatter.py 模块的单元测试

测试用例:
- UT-FMT-001: DefaultResponseFormatter 格式化标准响应
- UT-FMT-002: DefaultResponseFormatter 格式化带解析数据的响应
- UT-FMT-003: DefaultResponseFormatter 处理 kwargs 参数
- UT-FMT-004: BaseResponseFormatter 抽象方法验证
"""

import pytest
from abc import ABC
from http_client.formatter import BaseResponseFormatter, DefaultResponseFormatter


class TestBaseResponseFormatter:
    """测试 BaseResponseFormatter 抽象基类"""

    @pytest.mark.unit
    def test_is_abstract_class(self):
        """UT-FMT-004: BaseResponseFormatter 是抽象类"""
        # Arrange & Act & Assert
        assert issubclass(BaseResponseFormatter, ABC)

        # 验证不能直接实例化
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseResponseFormatter()

    @pytest.mark.unit
    def test_has_abstract_format_method(self):
        """UT-FMT-004: BaseResponseFormatter 有抽象 format 方法"""
        # Arrange & Act & Assert
        assert hasattr(BaseResponseFormatter, "format")
        assert getattr(BaseResponseFormatter.format, "__isabstractmethod__", False)


class TestDefaultResponseFormatter:
    """测试 DefaultResponseFormatter 格式化器"""

    @pytest.fixture
    def formatter(self):
        """提供 DefaultResponseFormatter 实例"""
        return DefaultResponseFormatter()

    @pytest.mark.unit
    def test_initialization(self, formatter):
        """验证 DefaultResponseFormatter 可以正确初始化"""
        # Arrange & Act & Assert
        assert isinstance(formatter, DefaultResponseFormatter)
        assert isinstance(formatter, BaseResponseFormatter)

    @pytest.mark.unit
    def test_format_standard_response(self, formatter):
        """UT-FMT-001: 格式化标准响应"""
        # Arrange
        formatted_response = {"result": True, "code": 200, "message": "Success", "data": {"user_id": 123}}

        # Act
        result = formatter.format(formatted_response)

        # Assert
        assert result == formatted_response
        assert result["result"] is True
        assert result["code"] == 200
        assert result["message"] == "Success"
        assert result["data"] == {"user_id": 123}

    @pytest.mark.unit
    def test_format_with_parsed_data(self, formatter):
        """UT-FMT-002: 格式化带解析数据的响应"""
        # Arrange
        formatted_response = {"result": True, "code": 200, "message": "Success", "data": None}
        parsed_data = {"parsed": "content"}

        # Act
        result = formatter.format(formatted_response, parsed_data=parsed_data)

        # Assert
        assert result == formatted_response
        # DefaultResponseFormatter 直接返回 formatted_response，不会使用 parsed_data
        assert result["data"] is None

    @pytest.mark.unit
    def test_format_with_kwargs(self, formatter):
        """UT-FMT-003: 处理额外的 kwargs 参数"""
        # Arrange
        formatted_response = {"result": False, "code": 404, "message": "Not Found", "data": None}

        # Act
        result = formatter.format(
            formatted_response, parsed_data={"extra": "data"}, custom_arg="custom_value", another_arg=42
        )

        # Assert
        assert result == formatted_response
        assert result["result"] is False
        assert result["code"] == 404

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "formatted_response,expected",
        [
            (
                {"result": True, "code": 200, "message": "OK", "data": []},
                {"result": True, "code": 200, "message": "OK", "data": []},
            ),
            (
                {"result": False, "code": 500, "message": "Error", "data": None},
                {"result": False, "code": 500, "message": "Error", "data": None},
            ),
            (
                {"result": True, "code": 201, "message": "Created", "data": {"id": 1}},
                {"result": True, "code": 201, "message": "Created", "data": {"id": 1}},
            ),
        ],
    )
    def test_format_various_responses(self, formatter, formatted_response, expected):
        """参数化测试: 格式化各种类型的响应"""
        # Arrange & Act
        result = formatter.format(formatted_response)

        # Assert
        assert result == expected

    @pytest.mark.unit
    def test_format_empty_response(self, formatter):
        """测试格式化空响应字典"""
        # Arrange
        formatted_response = {}

        # Act
        result = formatter.format(formatted_response)

        # Assert
        assert result == {}

    @pytest.mark.unit
    def test_format_response_with_extra_fields(self, formatter):
        """测试格式化包含额外字段的响应"""
        # Arrange
        formatted_response = {
            "result": True,
            "code": 200,
            "message": "Success",
            "data": {"value": 1},
            "extra_field": "extra_value",
            "timestamp": 1234567890,
        }

        # Act
        result = formatter.format(formatted_response)

        # Assert
        assert result == formatted_response
        assert "extra_field" in result
        assert "timestamp" in result

    @pytest.mark.unit
    def test_format_does_not_modify_input(self, formatter):
        """测试 format 方法不会修改输入参数"""
        # Arrange
        original_response = {"result": True, "code": 200, "message": "Success", "data": {"mutable": [1, 2, 3]}}
        response_copy = original_response.copy()

        # Act
        result = formatter.format(original_response)

        # Assert
        assert original_response == response_copy
        assert result == original_response

    @pytest.mark.unit
    def test_format_with_none_parsed_data(self, formatter):
        """测试 parsed_data 为 None 的情况"""
        # Arrange
        formatted_response = {"result": True, "data": "original"}

        # Act
        result = formatter.format(formatted_response, parsed_data=None)

        # Assert
        assert result == formatted_response
        assert result["data"] == "original"
