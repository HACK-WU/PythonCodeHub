"""
queues — Celery 队列声明的轻量工厂

本模块仅提供一组保守的辅助函数，帮助调用方以声明式方式构造一组
``kombu.Queue``，并将其作为 ``CeleryConfig.task_queues`` 的输入。

设计要点（对应设计文档第 6.2 节）：
- 不固化任何项目命名约定（不预设 default / heavy / cron 等队列名）
- 不引入新的第三方依赖；仅使用 celery 自带的 kombu
- 输入支持「字符串列表」或「(名称, 选项)」元组列表两种形式
- 输出统一为 ``list[kombu.Queue]``，可直接赋给 ``CeleryConfig.task_queues``
- 不主动注入交换机类型 / routing_key，调用方未显式指定时由 kombu 自行决定

用法：
    from ab_celery.config import CeleryConfig
    from ab_celery.queues import build_queues

    queues = build_queues(["default", "heavy", "cron"])
    config = CeleryConfig(
        app_name="myapp",
        broker_url="redis://localhost:6379/0",
        task_queues=queues,
    )
"""

from __future__ import annotations

import logging
from typing import Any
from collections.abc import Iterable

from kombu import Queue

logger = logging.getLogger("ab_celery.queues")

# 队列声明的两种合法输入形式：
# 1. 仅名称的字符串
# 2. (名称, 选项 dict) 二元元组
QueueSpec = str | tuple[str, dict[str, Any]]


def build_queue(name: str, **options: Any) -> Queue:
    """
    构造单个 kombu.Queue。

    参数：
        name: 队列名，必须为非空字符串
        **options: 透传给 kombu.Queue 的关键字参数（如 routing_key、exchange 等）

    返回：
        kombu.Queue 实例
    """
    # 1. 校验队列名
    if not isinstance(name, str) or not name:
        raise TypeError("队列名必须为非空字符串")
    # 2. 透传给 kombu.Queue
    return Queue(name, **options)


def build_queues(specs: Iterable[QueueSpec]) -> list[Queue]:
    """
    根据声明列表批量构造 kombu.Queue 列表。

    参数：
        specs: 可迭代的队列声明，元素可以是：
            - 字符串：仅指定队列名
            - (name, options_dict) 二元元组：指定队列名与额外 Queue 选项

    返回：
        list[kombu.Queue]，可直接用作 CeleryConfig.task_queues

    异常：
        TypeError: 输入既不是字符串也不是 (str, dict) 元组时抛出
        ValueError: 出现重复队列名时抛出，避免静默覆盖

    主要步骤：
    1. 遍历输入声明并按形式分发到 build_queue
    2. 对队列名做去重校验，重复名直接抛出 ValueError
    3. 返回构造完成的 Queue 列表
    """
    if specs is None:
        raise TypeError("specs 不能为 None")

    queues: list[Queue] = []
    seen: set[str] = set()

    for spec in specs:
        if isinstance(spec, str):
            name, options = spec, {}
        elif isinstance(spec, tuple) and len(spec) == 2 and isinstance(spec[0], str) and isinstance(spec[1], dict):
            name, options = spec
        else:
            raise TypeError(
                f"队列声明必须为字符串或 (name, options_dict) 二元元组，收到 {type(spec).__name__}: {spec!r}"
            )

        if name in seen:
            raise ValueError(f"队列名重复：{name!r}")
        seen.add(name)
        queues.append(build_queue(name, **options))

    return queues
