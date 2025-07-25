import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class APIClientError(Exception):
    """自定义 API 客户端异常基类"""


class APIClientHTTPError(APIClientError):
    """表示 HTTP 错误响应的异常"""

    def __init__(self, message, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response else None


class APIClientNetworkError(APIClientError):
    """表示网络问题导致的异常"""


class APIClientTimeoutError(APIClientError):
    """表示请求超时的异常"""


class APIClientValidationError(APIClientError):
    """表示输入验证失败的异常"""


class BaseResponseFormatter(ABC):
    """响应格式化器基类，定义如何格式化响应和异常。"""

    @abstractmethod
    def format(
        self,
        client_instance: "BaseClient",  # noqa: F821
        response_or_exception: requests.Response | APIClientError,
        request_config: dict[str, Any],  # 传入请求配置，可能需要其中的信息
    ) -> dict[str, Any]:
        """
        格式化响应或异常为统一的字典结构。
        :param client_instance: 调用此格式化器的 BaseClient 实例。
        :param response_or_exception: 成功的 requests.Response 对象或捕获到的 APIClientError 异常。
        :param request_config: 原始请求配置。
        :return: 格式化后的字典。
        """


class DefaultResponseFormatter(BaseResponseFormatter):
    """默认响应格式化器，生成 {result, code, message, data} 结构。"""

    def format(
        self,
        client_instance: "BaseClient",  # noqa: F821
        response_or_exception: requests.Response | APIClientError,
        request_config: dict[str, Any],
    ) -> dict[str, Any]:
        formatted_response: dict[str, Any] = {"result": False, "code": None, "message": "", "data": None}

        if isinstance(response_or_exception, requests.Response):
            # 请求成功
            formatted_response["result"] = True
            formatted_response["code"] = response_or_exception.status_code
            formatted_response["message"] = "Success"

            data = None
            if client_instance.response_parser_instance:
                try:
                    data = client_instance.response_parser_instance.parse(client_instance, response_or_exception)
                except Exception as parse_error:
                    logger.error(f"Response parsing failed during formatting: {parse_error}")
                    formatted_response["result"] = False  # 可选：将解析错误也标记为失败
                    formatted_response["message"] = f"Parsing failed: {parse_error}"
            formatted_response["data"] = data

        elif isinstance(response_or_exception, APIClientError):
            # 请求失败
            formatted_response["result"] = False
            if hasattr(response_or_exception, "status_code") and response_or_exception.status_code:
                formatted_response["code"] = response_or_exception.status_code
            else:
                # 对于非 HTTP 错误，可以定义一个通用代码或留空
                formatted_response["code"] = -1  # 或者 0, None 等
            formatted_response["message"] = str(response_or_exception)
            formatted_response["data"] = None  # 失败时数据为 None

        else:
            # 理论上不应该到达这里，但为了健壮性
            formatted_response["result"] = False
            formatted_response["code"] = -2
            formatted_response["message"] = f"Unexpected response/exception type: {type(response_or_exception)}"
            formatted_response["data"] = None

        return formatted_response
