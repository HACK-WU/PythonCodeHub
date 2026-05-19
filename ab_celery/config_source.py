"""
config_source — 配置源适配协议与最小加载入口

本模块仅提供：
- ConfigSource：配置源协议
- MemoryConfigSource：内存配置源（仅测试 / 简单场景）
- load_celery_config：从配置源显式加载一次 CeleryConfig
- build_celery_config_from_source：从配置源直接构造 Celery conf 字典

设计要点：
- 仅覆盖「加载一次 → 构造 CeleryConfig」的最小路径
- 不接入任何具体配置中心客户端，不处理运行期热更新
- 拉取失败后的兜底策略必须由调用方显式提供
- 内存实现仅支持 dict / CeleryConfig / 无参函数三种输入
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ab_celery.config import CeleryConfig, build_celery_config

ConfigPayload = CeleryConfig | dict[str, Any]
ConfigFallback = Callable[[Exception], ConfigPayload]
ConfigProvider = ConfigPayload | Callable[[], ConfigPayload]


class ConfigSource(Protocol):
    """配置源协议。"""

    def load(self) -> ConfigPayload:
        """加载一次配置内容。"""
        ...


class MemoryConfigSource:
    """
    内存配置源。

    说明：
    - 仅用于测试或简单场景
    - 支持直接传入 dict / CeleryConfig
    - 支持传入无参函数，便于模拟一次配置拉取
    """

    def __init__(self, provider: ConfigProvider) -> None:
        if not callable(provider) and not isinstance(provider, (dict, CeleryConfig)):
            raise TypeError("provider 必须为 dict、CeleryConfig 或无参可调用对象")
        self.provider = provider

    def load(self) -> ConfigPayload:
        payload = self.provider() if callable(self.provider) else self.provider
        return _clone_payload(payload)


def load_celery_config(
    source: ConfigSource,
    *,
    fallback: ConfigFallback | None = None,
) -> CeleryConfig:
    """
    从配置源显式加载一次 CeleryConfig。

    参数：
        source: 配置源协议实现
        fallback: 当 source.load() 抛错时使用的显式兜底函数
    """
    if source is None:
        raise TypeError("source 不能为 None")
    if fallback is not None and not callable(fallback):
        raise TypeError("fallback 必须为可调用对象或 None")

    try:
        payload = source.load()
    except Exception as exc:
        if fallback is None:
            raise
        payload = fallback(exc)

    return _normalize_payload(payload)


def build_celery_config_from_source(
    source: ConfigSource,
    *,
    fallback: ConfigFallback | None = None,
) -> dict[str, Any]:
    """从配置源显式加载一次，并构造 Celery conf 字典。"""
    config = load_celery_config(source, fallback=fallback)
    return build_celery_config(config)


def _clone_payload(payload: ConfigPayload) -> ConfigPayload:
    if isinstance(payload, CeleryConfig):
        return payload
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError("配置源必须返回 CeleryConfig 或 dict")


def _normalize_payload(payload: ConfigPayload) -> CeleryConfig:
    if isinstance(payload, CeleryConfig):
        return payload
    if isinstance(payload, dict):
        return CeleryConfig(**payload)
    raise TypeError("配置源必须返回 CeleryConfig 或 dict")


__all__ = [
    "ConfigSource",
    "MemoryConfigSource",
    "build_celery_config_from_source",
    "load_celery_config",
]
