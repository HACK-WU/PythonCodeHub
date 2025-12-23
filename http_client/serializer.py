"""
请求序列化器模块

提供请求参数验证的基类和常用验证器实现，类似于 DRF 的 Serializer 设计

使用示例:
    # 方式1: 定义独立的序列化器类
    class UserRequestSerializer(BaseRequestSerializer):
        def validate(self, data):
            errors = {}
            if not data.get("username"):
                errors["username"] = ["用户名不能为空"]
            if not data.get("email"):
                errors["email"] = ["邮箱不能为空"]
            if errors:
                raise APIClientRequestValidationError("请求参数验证失败", errors=errors)
            return data

    class UserAPIClient(BaseClient):
        base_url = "https://api.example.com"
        request_serializer_class = UserRequestSerializer

    # 方式2: 直接在 BaseClient 中定义内嵌的 RequestSerializer 类
    class UserAPIClient(BaseClient):
        base_url = "https://api.example.com"

        class RequestSerializer(BaseRequestSerializer):
            def validate(self, data):
                errors = {}
                if not data.get("username"):
                    errors["username"] = ["用户名不能为空"]
                if errors:
                    raise APIClientRequestValidationError("请求参数验证失败", errors=errors)
                return data
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseRequestSerializer(ABC):
    """
    请求序列化器基类

    用于在发送 HTTP 请求前对请求参数进行验证和转换

    子类需要实现 validate 方法来定义具体的验证逻辑
    """

    @abstractmethod
    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        验证请求数据

        参数:
            data: 请求配置字典，包含 method、endpoint、params、json、data 等字段

        返回:
            验证通过后的数据（可以在此进行数据转换）

        异常:
            APIClientRequestValidationError: 当验证失败时抛出
        """
