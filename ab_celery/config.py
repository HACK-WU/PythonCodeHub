"""
config — Celery 通用配置的结构化表达与标准化构造

本模块仅提供：
- CeleryConfig：以 dataclass 表达的结构化配置对象
- build_celery_config：把 CeleryConfig 或 dict 转换为可直接用于
  Celery.conf.update 的扁平字典

设计要点：
- 仅强依赖 celery；不引入 pydantic / attrs / environs 等第三方库
- 不读取环境变量、不加载 .env、不接入任何配置中心
- 字段范围严格遵循设计文档第 8.1 / 8.2 / 8.3 节的三层划分
- 默认值保守，鼓励调用方按需显式覆盖
- 字段命名采用 Celery >= 5.3 原生小写蛇形命名（如 broker_url、task_default_queue）

用法：
    from celery import Celery
    from ab_celery.config import CeleryConfig, build_celery_config

    config = CeleryConfig(
        app_name="myapp",
        broker_url="redis://localhost:6379/0",
        timezone="Asia/Shanghai",
    )
    app = Celery(config.app_name)
    app.conf.update(build_celery_config(config))
"""

import logging
from dataclasses import dataclass, field, fields
from typing import Any

logger = logging.getLogger("ab_celery.config")

# 不需要直接映射到 Celery conf 的元字段
# 这些字段用于 ab_celery 自身的接入装配，不会出现在最终的 conf 字典中
_META_FIELDS = frozenset({"app_name"})


@dataclass
class CeleryConfig:
    """
    Celery 通用配置对象。

    分三层组织字段，对应设计文档第 8.1 / 8.2 / 8.3 节：

    8.1 基础层：连接、时区、序列化
    8.2 任务与 worker 行为层：默认队列、超时、确认、重试、预取等
    8.3 调度与路由层：beat scheduler、队列定义、任务路由

    所有字段均为可选并提供保守默认值；调用方仅需覆盖关心的字段。
    传入未在本类中定义的字段会被 dataclass 拒绝并抛出 TypeError。
    """

    # ---------- 8.1 基础层 ----------
    app_name: str = "celery"
    broker_url: str = "memory://"
    result_backend: str | None = None
    timezone: str = "UTC"
    enable_utc: bool = True
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = field(default_factory=lambda: ["json"])

    # ---------- 8.2 任务与 worker 行为层 ----------
    task_default_queue: str = "celery"
    task_track_started: bool = False
    task_time_limit: int | None = None
    task_soft_time_limit: int | None = None
    task_acks_late: bool = False
    task_reject_on_worker_lost: bool = False
    task_default_retry_delay: int = 3
    task_default_max_retries: int = 3
    worker_prefetch_multiplier: int = 1
    broker_connection_retry_on_startup: bool = True
    task_publish_retry: bool = True
    result_expires: int = 24 * 60 * 60
    result_extended: bool = False

    # ---------- 8.3 调度与路由层 ----------
    beat_scheduler: str | None = None
    task_queues: list[dict[str, Any]] | None = None
    task_routes: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        # 简单类型校验：仅校验最容易误用的几类字段
        # 1. app_name 必须为字符串
        if not isinstance(self.app_name, str) or not self.app_name:
            raise TypeError("app_name 必须为非空字符串")
        # 2. broker_url 必须为字符串
        if not isinstance(self.broker_url, str) or not self.broker_url:
            raise TypeError("broker_url 必须为非空字符串")
        # 3. result_backend 允许 None 或字符串
        if self.result_backend is not None and not isinstance(self.result_backend, str):
            raise TypeError("result_backend 必须为字符串或 None")
        # 4. accept_content 必须为字符串列表
        if not isinstance(self.accept_content, list) or not all(
            isinstance(item, str) for item in self.accept_content
        ):
            raise TypeError("accept_content 必须为字符串列表")
        # 5. 数值类型字段统一拒绝 bool 当作整数
        for int_field in (
            "task_default_retry_delay",
            "task_default_max_retries",
            "worker_prefetch_multiplier",
            "result_expires",
        ):
            value = getattr(self, int_field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{int_field} 必须为 int 类型")
        # 6. 可选 int 字段
        for opt_int_field in ("task_time_limit", "task_soft_time_limit"):
            value = getattr(self, opt_int_field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError(f"{opt_int_field} 必须为 int 类型或 None")
        # 7. 队列与路由的容器类型
        if self.task_queues is not None and not isinstance(self.task_queues, list):
            raise TypeError("task_queues 必须为 list 或 None")
        if self.task_routes is not None and not isinstance(self.task_routes, dict):
            raise TypeError("task_routes 必须为 dict 或 None")

    def to_conf_dict(self) -> dict[str, Any]:
        """
        将自身转换为可直接交给 Celery.conf.update 的扁平字典。

        转换规则：
        1. 跳过 _META_FIELDS 中的元字段（如 app_name）
        2. 跳过值为 None 的可选字段，避免覆盖 Celery 自身默认值
        3. 其余字段以原字段名（即 Celery 原生 conf key）输出
        """
        conf: dict[str, Any] = {}
        for f in fields(self):
            if f.name in _META_FIELDS:
                continue
            value = getattr(self, f.name)
            if value is None:
                continue
            conf[f.name] = value
        return conf


def build_celery_config(config: "CeleryConfig | dict[str, Any]") -> dict[str, Any]:
    """
    构造可直接用于 Celery.conf.update 的标准化配置字典。

    参数：
        config: CeleryConfig 实例或标准 dict。

    返回：
        扁平的 Celery 配置字典；不包含 ab_celery 元字段（如 app_name）。

    异常：
        TypeError：当 config 既不是 CeleryConfig 也不是 dict 时抛出。

    主要步骤：
    1. 校验入参类型
    2. 若为 dict，先用 CeleryConfig(**config) 重新校验字段合法性
    3. 调用 CeleryConfig.to_conf_dict 输出最终结果
    """
    if isinstance(config, CeleryConfig):
        normalized = config
    elif isinstance(config, dict):
        # 通过 dataclass 构造一遍以拒绝未知字段并执行类型校验
        normalized = CeleryConfig(**config)
    else:
        raise TypeError(
            f"build_celery_config 仅接受 CeleryConfig 或 dict，收到 {type(config).__name__}"
        )

    return normalized.to_conf_dict()
