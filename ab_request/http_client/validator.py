"""
响应验证器模块

提供响应验证的基类和常用验证器实现
"""

import logging
from abc import ABC, abstractmethod
from typing import Any
from collections.abc import Callable

import requests

from ab_request.http_client.constants import LOG_FORMAT
from ab_request.http_client.exceptions import APIClientResponseValidationError

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class BaseResponseValidator(ABC):
    """
    响应验证器基类

    用于验证 HTTP 响应是否符合预期，不符合时抛出异常
    """

    @abstractmethod
    def validate(
        self,
        client_instance: "BaseClient",  # noqa
        response: requests.Response,
        parsed_data: Any,  # noqa: F821
    ) -> None:
        """
        验证响应

        参数:
            client_instance: 调用此验证器的 BaseClient 实例
            response: HTTP 响应对象
            parsed_data: 解析后的响应数据

        异常:
            APIClientResponseValidationError: 当验证失败时抛出
        """


class StatusCodeValidator(BaseResponseValidator):
    """
    状态码验证器

    验证响应状态码是否在允许的范围内

    参数:
        allowed_codes: 允许的状态码列表或集合，默认只允许 200
        strict_mode: 严格模式，True 时只允许列表中的状态码

    使用示例:
        >>> validator = StatusCodeValidator(allowed_codes=[200, 201, 204])
        >>> validator.validate(client, response, data)

    注意:
        此验证器在解析前和解析后都会执行，主要用于验证原始响应
    """

    def __init__(self, allowed_codes: list[int] | set[int] | None = None, strict_mode: bool = True):
        self.allowed_codes = set(allowed_codes) if allowed_codes else {200}
        self.strict_mode = strict_mode

    def validate(
        self,
        client_instance: "BaseClient",  # noqa
        response: requests.Response,
        parsed_data: Any,  # noqa: F821
    ) -> None:
        # 只在原始响应阶段验证（parsed_data 为 None 时）
        if parsed_data is not None:
            return

        status_code = response.status_code

        if self.strict_mode and status_code not in self.allowed_codes:
            raise APIClientResponseValidationError(
                f"Response status code {status_code} not in allowed codes: {self.allowed_codes}",
                response=response,
                validation_result={"status_code": status_code, "allowed_codes": list(self.allowed_codes)},
            )


class JSONFieldValidator(BaseResponseValidator):
    """
    JSON 字段验证器

    验证解析后的 JSON 数据是否包含必需字段，并可对字段值进行自定义验证

    参数:
        required_fields: 必需字段列表
        field_validators: 字段值验证函数字典 {field_name: validator_func}
                         validator_func 签名: (value) -> bool

    使用示例:
        >>> validator = JSONFieldValidator(
        ...     required_fields=["code", "data"], field_validators={"code": lambda x: x == 0}
        ... )
        >>> validator.validate(client, response, data)

    注意:
        此验证器只在解析后执行（parsed_data 不为 None 时）
    """

    def __init__(self, required_fields: list[str] | None = None, field_validators: dict[str, Callable] | None = None):
        self.required_fields = required_fields or []
        self.field_validators = field_validators or {}

    def validate(
        self,
        client_instance: "BaseClient",  # noqa
        response: requests.Response,
        parsed_data: Any,  # noqa: F821
    ) -> None:
        # 只在解析后阶段验证（parsed_data 不为 None 时）
        if parsed_data is None:
            return

        if not isinstance(parsed_data, dict):
            raise APIClientResponseValidationError(
                f"Expected dict type for JSON validation, got {type(parsed_data).__name__}",
                response=response,
                validation_result={"expected_type": "dict", "actual_type": type(parsed_data).__name__},
            )

        # 验证必需字段
        missing_fields = [field for field in self.required_fields if field not in parsed_data]
        if missing_fields:
            raise APIClientResponseValidationError(
                f"Missing required fields: {missing_fields}",
                response=response,
                validation_result={"missing_fields": missing_fields, "available_fields": list(parsed_data.keys())},
            )

        # 验证字段值
        for field_name, validator_func in self.field_validators.items():
            if field_name not in parsed_data:
                continue

            field_value = parsed_data[field_name]
            try:
                if not validator_func(field_value):
                    raise APIClientResponseValidationError(
                        f"Field '{field_name}' validation failed: value={field_value}",
                        response=response,
                        validation_result={"failed_field": field_name, "field_value": field_value},
                    )
            except APIClientResponseValidationError:
                raise
            except Exception as e:
                raise APIClientResponseValidationError(
                    f"Field '{field_name}' validator raised exception: {e}",
                    response=response,
                    validation_result={"failed_field": field_name, "error": str(e)},
                )


class CustomValidator(BaseResponseValidator):
    """
    自定义验证器

    使用自定义函数进行验证

    参数:
        validator_func: 验证函数，签名: (client, response, parsed_data) -> bool
                       返回 True 表示验证通过，False 表示验证失败
        error_message: 验证失败时的错误消息

    使用示例:
        >>> def my_validator(client, response, data):
        ...     return data.get("success") is True
        >>>
        >>> validator = CustomValidator(validator_func=my_validator, error_message="Response success field is not True")
        >>> validator.validate(client, response, data)
    """

    def __init__(self, validator_func: Callable, error_message: str = "Custom validation failed"):
        self.validator_func = validator_func
        self.error_message = error_message

    def validate(
        self,
        client_instance: "BaseClient",  # noqa
        response: requests.Response,
        parsed_data: Any,  # noqa: F821
    ) -> None:
        try:
            result = self.validator_func(client_instance, response, parsed_data)
            if not result:
                raise APIClientResponseValidationError(
                    self.error_message, response=response, validation_result={"custom_validation": False}
                )
        except APIClientResponseValidationError:
            raise
        except Exception as e:
            raise APIClientResponseValidationError(
                f"Validator function raised exception: {e}",
                response=response,
                validation_result={"error": str(e)},
            )
