"""
HTTP 客户端异常模块

定义所有 API 客户端相关的异常类，提供统一的错误处理机制
"""

import requests


class APIClientError(Exception):
    """
    API 客户端异常基类

    所有自定义异常的基类，用于统一捕获和处理客户端相关错误
    """


class APIClientHTTPError(APIClientError):
    """
    HTTP 错误响应异常

    当服务器返回 4xx 或 5xx 状态码时抛出此异常

    参数:
        message: 错误描述信息
        response: 原始的 requests.Response 对象（可选）

    属性:
        response: 保存原始响应对象，便于获取详细错误信息
        status_code: HTTP 状态码
    """

    def __init__(self, message: str, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response else None


class APIClientNetworkError(APIClientError):
    """
    网络连接异常

    当网络连接失败、DNS 解析失败等网络层面问题时抛出此异常
    """


class APIClientTimeoutError(APIClientError):
    """
    请求超时异常

    当请求执行时间超过设定的超时时间时抛出此异常
    """


class APIClientValidationError(APIClientError):
    """
    输入验证异常

    当请求参数、配置等输入数据验证失败时抛出此异常
    """
