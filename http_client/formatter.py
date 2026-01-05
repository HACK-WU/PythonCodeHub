"""
响应格式化器模块

提供响应格式化的基类和默认实现，用于将 HTTP 响应统一格式化为标准结构
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


logger = logging.getLogger(__name__)


class BaseResponseFormatter(ABC):
    """响应格式化器基类，定义如何格式化响应和异常。"""

    @abstractmethod
    def format(
        self,
        formated_response: dict,
        parsed_data: Any = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        格式化响应或异常为统一的字典结构

        参数:
           formatted_response: 格式化后的响应
           parsed_data: 解析后的数据

        返回:
            格式化后的字典结构
        """


class DefaultResponseFormatter(BaseResponseFormatter):
    """默认响应格式化器，生成 {result, code, message, data} 结构。"""

    def format(
        self,
        formated_response: dict,
        parsed_data: Any = None,
        **kwargs,
    ) -> dict[str, Any]:
        """
        格式化响应或异常为统一的字典结构

        参数:
           formatted_response: 格式化后的响应
           parsed_data: 解析后的数据

        返回:
            格式化后的字典结构
        """
        return formated_response
