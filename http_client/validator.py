"""响应验证器模块

提供响应验证的基类和常用验证器实现
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

from http_client.exceptions import APIClientResponseValidationError

logger = logging.getLogger(__name__)


class BaseResponseValidator(ABC):
    """
    响应验证器基类

    用于验证 HTTP 响应是否符合预期，不符合时抛出异常
    """

    @abstractmethod
    def validate(
        self,
        client_instance: BaseClient,  # noqa
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
    """

    def __init__(self, allowed_codes: list[int] | set[int] | None = None, strict_mode: bool = True):
        self.allowed_codes = set(allowed_codes) if allowed_codes else {200}
        self.strict_mode = strict_mode

    def validate(
        self,
        client_instance: BaseClient,  # noqa
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
