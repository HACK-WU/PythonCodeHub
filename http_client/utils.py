"""工具函数模块

提供敏感信息脱敏等实用功能
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


# 默认敏感请求头名称集合
DEFAULT_SENSITIVE_HEADERS = {
    "Authorization",
    "Cookie",
    "X-API-Key",
    "X-Auth-Token",
    "X-Access-Token",
    "API-Key",
    "Auth-Token",
    "Session-ID",
}

# 默认敏感URL参数名称集合
DEFAULT_SENSITIVE_PARAMS = {
    "token",
    "password",
    "secret",
    "key",
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "session",
    "pwd",
}


def sanitize_headers(
    headers: dict[str, str],
    sensitive_keys: set[str] | None = None,
    mask: str = "***",
) -> dict[str, str]:
    """
    脱敏请求头中的敏感信息

    参数:
        headers: 原始请求头字典
        sensitive_keys: 敏感键名集合，不区分大小写。None 时使用默认集合
        mask: 脱敏后的替换字符串

    返回:
        脱敏后的请求头字典（新字典，不修改原字典）

    示例:
        >>> headers = {"Authorization": "Bearer token123", "Content-Type": "application/json"}
        >>> sanitize_headers(headers)
        {"Authorization": "***", "Content-Type": "application/json"}
    """
    if sensitive_keys is None:
        sensitive_keys = DEFAULT_SENSITIVE_HEADERS

    # 创建不区分大小写的查找集合
    sensitive_keys_lower = {k.lower() for k in sensitive_keys}

    return {k: mask if k.lower() in sensitive_keys_lower else v for k, v in headers.items()}


def sanitize_url(
    url: str,
    sensitive_params: set[str] | None = None,
    mask: str = "***",
) -> str:
    """
    脱敏 URL 中的敏感参数

    参数:
        url: 原始 URL
        sensitive_params: 敏感参数名集合，不区分大小写。None 时使用默认集合
        mask: 脱敏后的替换字符串

    返回:
        脱敏后的 URL

    示例:
        >>> sanitize_url("https://api.example.com/user?token=abc123&page=1")
        "https://api.example.com/user?token=***&page=1"
    """
    if sensitive_params is None:
        sensitive_params = DEFAULT_SENSITIVE_PARAMS

    # 创建不区分大小写的查找集合
    sensitive_params_lower = {p.lower() for p in sensitive_params}

    # 解析 URL
    parsed = urlparse(url)

    # 如果没有查询参数，直接返回
    if not parsed.query:
        return url

    # 解析查询参数
    params = parse_qs(parsed.query, keep_blank_values=True)

    # 脱敏敏感参数
    sanitized_params = {}
    for key, values in params.items():
        if key.lower() in sensitive_params_lower:
            # 保持参数结构，但值替换为 mask
            sanitized_params[key] = [mask] * len(values)
        else:
            sanitized_params[key] = values

    # 重新构建查询字符串
    sanitized_query = urlencode(sanitized_params, doseq=True)

    # 重新构建 URL
    return urlunparse(parsed._replace(query=sanitized_query))


def sanitize_dict(
    data: dict[str, Any],
    sensitive_keys: set[str] | None = None,
    mask: str = "***",
    recursive: bool = True,
) -> dict[str, Any]:
    """
    脱敏字典中的敏感字段

    参数:
        data: 原始数据字典
        sensitive_keys: 敏感键名集合，不区分大小写。None 时使用默认集合
        mask: 脱敏后的替换字符串
        recursive: 是否递归处理嵌套字典

    返回:
        脱敏后的字典（新字典，不修改原字典）

    示例:
        >>> data = {"username": "john", "password": "secret123", "meta": {"api_key": "key123"}}
        >>> sanitize_dict(data)
        {"username": "john", "password": "***", "meta": {"api_key": "***"}}
    """
    if sensitive_keys is None:
        # 合并请求头和URL参数的敏感键
        sensitive_keys = DEFAULT_SENSITIVE_HEADERS | DEFAULT_SENSITIVE_PARAMS

    # 创建不区分大小写的查找集合
    sensitive_keys_lower = {k.lower() for k in sensitive_keys}

    result = {}
    for key, value in data.items():
        if key.lower() in sensitive_keys_lower:
            result[key] = mask
        elif recursive and isinstance(value, dict):
            result[key] = sanitize_dict(value, sensitive_keys, mask, recursive)
        else:
            result[key] = value

    return result


def mask_string(
    text: str,
    pattern: str,
    mask: str = "***",
    keep_prefix: int = 0,
    keep_suffix: int = 0,
) -> str:
    """
    使用正则表达式匹配并脱敏字符串中的敏感内容

    参数:
        text: 原始文本
        pattern: 正则表达式模式
        mask: 脱敏后的替换字符串
        keep_prefix: 保留匹配内容的前N个字符
        keep_suffix: 保留匹配内容的后N个字符

    返回:
        脱敏后的文本

    示例:
        >>> mask_string("Bearer token_abc123xyz", r"token_\w+", keep_prefix=6)
        "Bearer token_***"
    """

    def replace_match(match):
        matched_text = match.group(0)
        if keep_prefix == 0 and keep_suffix == 0:
            return mask

        prefix = matched_text[:keep_prefix] if keep_prefix > 0 else ""
        suffix = matched_text[-keep_suffix:] if keep_suffix > 0 else ""
        return f"{prefix}{mask}{suffix}"

    return re.sub(pattern, replace_match, text)
