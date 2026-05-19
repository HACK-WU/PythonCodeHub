"""
routing — Celery 任务路由表生成

本模块按声明式规则生成 Celery ``task_routes`` 字典，覆盖最常见两类场景：

- 精确匹配：完整任务名 -> 队列
- 前缀匹配：任务名前缀（如 ``myapp.heavy.``）-> 队列

设计要点（对应设计文档第 6.2 节）：
- 不内置任何项目命名约定
- 不支持正则、不支持通配符；如需更复杂规则请直接传原生 ``task_routes``
- 输出与 Celery 原生 ``task_routes`` 完全兼容，可直接赋给
  ``CeleryConfig.task_routes``
- 当多条规则同时命中时，按「精确匹配 > 前缀匹配（最长前缀优先）」决定优先级
- 仅生成静态字典，不引入 Celery ``Router`` 类，保持调用方可直接 review

用法：
    from ab_celery.config import CeleryConfig
    from ab_celery.routing import RouteRule, build_routes

    routes = build_routes([
        RouteRule(match="myapp.tasks.send_mail", queue="mail"),
        RouteRule(prefix="myapp.heavy.", queue="heavy"),
    ])
    config = CeleryConfig(
        app_name="myapp",
        broker_url="redis://localhost:6379/0",
        task_routes=routes,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger("ab_celery.routing")


@dataclass(frozen=True)
class RouteRule:
    """
    单条路由规则。

    字段：
        match: 完整任务名；与 ``prefix`` 二选一
        prefix: 任务名前缀；与 ``match`` 二选一
        queue: 目标队列名，必填
        options: 额外路由选项（如 ``routing_key``、``exchange`` 等），
            会与 ``{"queue": queue}`` 合并后写入路由值

    约束：
        - ``match`` 与 ``prefix`` 必须且仅有一个被指定
        - ``queue`` 不能为空字符串
    """

    queue: str
    match: str | None = None
    prefix: str | None = None
    options: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # 1. queue 必填
        if not isinstance(self.queue, str) or not self.queue:
            raise TypeError("RouteRule.queue 必须为非空字符串")
        # 2. match / prefix 二选一
        has_match = isinstance(self.match, str) and self.match != ""
        has_prefix = isinstance(self.prefix, str) and self.prefix != ""
        if has_match == has_prefix:
            raise ValueError(
                "RouteRule 必须指定 match 或 prefix 之一（且只能其一）"
            )
        # 3. options 必须为 dict 或 None
        if self.options is not None and not isinstance(self.options, dict):
            raise TypeError("RouteRule.options 必须为 dict 或 None")


def _to_route_value(rule: RouteRule) -> dict[str, Any]:
    """把单条 RouteRule 转换为 Celery task_routes 的 value 字典。"""
    value: dict[str, Any] = {"queue": rule.queue}
    if rule.options:
        # 显式禁止覆盖 queue，避免规则字段与 options 互相打架
        if "queue" in rule.options and rule.options["queue"] != rule.queue:
            raise ValueError(
                f"RouteRule.options 中的 queue 与 RouteRule.queue 冲突：{rule!r}"
            )
        value.update(rule.options)
    return value


def build_routes(rules: Iterable[RouteRule]) -> dict[str, dict[str, Any]]:
    """
    根据声明式规则生成 Celery ``task_routes`` 字典。

    参数：
        rules: 可迭代的 RouteRule 列表

    返回：
        ``dict[str, dict[str, Any]]``，可直接赋给 ``CeleryConfig.task_routes``。
        其中 key 为任务名或 ``<prefix>*`` 形式（Celery 原生 glob 模式）。

    异常：
        TypeError: 输入不是 RouteRule 时抛出
        ValueError: 出现完全等价的重复规则（同 match 或同 prefix）时抛出

    主要步骤：
    1. 校验每条规则类型
    2. 精确匹配规则直接落到结果字典
    3. 前缀匹配规则转换为 Celery 原生支持的 ``"<prefix>*"`` glob 形式
    4. 检测同 key 重复声明并抛出 ValueError
    5. 按「精确匹配在前、前缀匹配按最长前缀在前」的顺序输出，便于调用方调试
    """
    if rules is None:
        raise TypeError("rules 不能为 None")

    exact: dict[str, dict[str, Any]] = {}
    prefix: dict[str, dict[str, Any]] = {}

    for rule in rules:
        if not isinstance(rule, RouteRule):
            raise TypeError(
                f"路由规则必须为 RouteRule 实例，收到 {type(rule).__name__}"
            )

        value = _to_route_value(rule)

        if rule.match is not None:
            if rule.match in exact:
                raise ValueError(f"重复的精确匹配规则：{rule.match!r}")
            exact[rule.match] = value
        else:
            # 前缀匹配统一以 "<prefix>*" 形式落入结果，符合 Celery glob 语义
            key = f"{rule.prefix}*"
            if key in prefix:
                raise ValueError(f"重复的前缀匹配规则：{rule.prefix!r}")
            prefix[key] = value

    # 输出顺序：精确匹配按声明顺序；前缀匹配按前缀长度降序，避免短前缀
    # 抢先命中。Python dict 在 3.7+ 保留插入顺序，因此该顺序可被调用方观察。
    result: dict[str, dict[str, Any]] = {}
    for key, value in exact.items():
        result[key] = value
    for key in sorted(prefix.keys(), key=lambda k: len(k), reverse=True):
        result[key] = prefix[key]
    return result
