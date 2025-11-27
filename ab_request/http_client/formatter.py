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
        request_config: dict[str, Any],
        parsed_data: Any = None,
        parse_error: Exception | None = None,
    ) -> dict[str, Any]:
        """
        格式化响应或异常为统一的字典结构

        参数:
            client_instance: 调用此格式化器的 BaseClient 实例
            response_or_exception: 成功的 requests.Response 对象或捕获到的 APIClientError 异常
            request_config: 原始请求配置字典
            parsed_data: 已解析的响应数据（由 response_parser 解析后的结果）
            parse_error: 解析过程中发生的异常（如果有）

        返回:
            格式化后的字典结构
        """


class DefaultResponseFormatter(BaseResponseFormatter):
    """默认响应格式化器，生成 {result, code, message, data} 结构。"""

    def format(
        self,
        client_instance: "BaseClient",  # noqa: F821
        response_or_exception: requests.Response | APIClientError,
        request_config: dict[str, Any],
        parsed_data: Any = None,
        parse_error: Exception | None = None,
    ) -> dict[str, Any]:
        """
        将HTTP响应或异常格式化为统一的标准字典结构

        参数:
            client_instance: BaseClient实例，用于访问配置信息
            response_or_exception: 请求结果，可能是成功的Response对象或失败的APIClientError异常
            request_config: 原始请求配置字典，包含请求的元数据信息
            parsed_data: 已解析的响应数据（由 response_parser 在 client 中解析）
            parse_error: 解析过程中发生的异常（如果有）

        返回值:
            dict[str, Any]: 标准化的响应字典，包含以下字段：
                - result (bool): 请求是否成功的标志
                - code (int|None): HTTP状态码或错误代码
                - message (str): 响应消息或错误描述
                - data (Any): 解析后的响应数据或None

        该方法实现完整的响应格式化流程，包含：
        1. 初始化标准响应结构（默认失败状态）
        2. 处理成功响应：提取状态码、使用已解析的数据
        3. 处理解析错误：标记为失败并记录错误信息
        4. 处理异常响应：提取错误信息和状态码
        5. 处理异常类型：兜底处理未预期的响应类型
        """
        # 初始化标准响应结构，默认为失败状态
        formatted_response: dict[str, Any] = {"result": False, "code": None, "message": "", "data": None}

        if isinstance(response_or_exception, requests.Response):
            # ========== 处理成功的HTTP响应 ==========
            # 检查是否有解析错误
            if parse_error:
                # 虽然HTTP请求成功，但数据解析失败，标记为失败
                formatted_response["result"] = False
                formatted_response["code"] = response_or_exception.status_code
                formatted_response["message"] = f"Parsing failed: {parse_error}"
                formatted_response["data"] = None
            else:
                # HTTP请求成功且数据解析成功（或无需解析）
                formatted_response["result"] = True
                formatted_response["code"] = response_or_exception.status_code
                formatted_response["message"] = "Success"
                # 使用已解析的数据（可能为None，表示无需解析或解析器未配置）
                formatted_response["data"] = parsed_data

        elif isinstance(response_or_exception, APIClientError):
            # ========== 处理API客户端异常 ==========
            formatted_response["result"] = False
            if hasattr(response_or_exception, "status_code") and response_or_exception.status_code:
                # HTTP错误：使用响应的状态码
                formatted_response["code"] = response_or_exception.status_code
            else:
                # 非HTTP错误（如网络超时、连接失败等），使用通用错误代码
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
