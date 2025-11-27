"""
响应格式化器模块

提供响应格式化的基类和默认实现，用于将 HTTP 响应统一格式化为标准结构
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

import requests

from ab_request.http_client.constants import (
    LOG_FORMAT,
    RESPONSE_CODE_NON_HTTP_ERROR,
    RESPONSE_CODE_UNEXPECTED_TYPE,
)
from ab_request.http_client.exceptions import APIClientError

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


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
        """
        将HTTP响应或异常格式化为统一的标准字典结构

        参数:
            client_instance: BaseClient实例，用于访问响应解析器等配置
            response_or_exception: 请求结果，可能是成功的Response对象或失败的APIClientError异常
            request_config: 原始请求配置字典，包含请求的元数据信息

        返回示例：
        {
            "result": True/False,  # 请求是否成功
            "code": 200/404/其他HTTP状态码或自定义错误码,  # HTTP状态码或自定义错误码
            "message": "Success" or "Error message",  # 成功消息或错误消息
            "data": parsed_data or None  # 解析后的数据或None
        """
        # 初始化标准响应结构，默认为失败状态
        formatted_response: dict[str, Any] = {"result": False, "code": None, "message": "", "data": None}

        if isinstance(response_or_exception, requests.Response):
            # ========== 处理成功的HTTP响应 ==========
            formatted_response["result"] = True
            formatted_response["code"] = response_or_exception.status_code
            formatted_response["message"] = "Success"

            data = None
            if client_instance.response_parser_instance:
                try:
                    # 调用配置的响应解析器解析原始响应
                    data = client_instance.response_parser_instance.parse(client_instance, response_or_exception)
                except Exception as parse_error:
                    logger.error(f"Response parsing failed during formatting: {parse_error}")
                    formatted_response["result"] = False
                    formatted_response["message"] = f"Parsing failed: {parse_error}"
            formatted_response["data"] = data

        elif isinstance(response_or_exception, APIClientError):
            # ========== 处理API客户端异常 ==========
            formatted_response["result"] = False
            if hasattr(response_or_exception, "status_code") and response_or_exception.status_code:
                formatted_response["code"] = response_or_exception.status_code
            else:
                # 对于非HTTP错误（如网络超时、连接失败等），使用通用错误代码
                formatted_response["code"] = RESPONSE_CODE_NON_HTTP_ERROR
            formatted_response["message"] = str(response_or_exception)
            formatted_response["data"] = None

        else:
            # ========== 处理未预期的响应类型（兜底逻辑） ==========
            formatted_response["result"] = False
            # 使用特殊错误代码标识未知类型错误
            formatted_response["code"] = RESPONSE_CODE_UNEXPECTED_TYPE
            formatted_response["message"] = f"Unexpected response/exception type: {type(response_or_exception)}"
            formatted_response["data"] = None

        return formatted_response
