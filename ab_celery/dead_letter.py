"""
dead_letter — 死信队列声明与失败任务转发辅助

本模块仅提供：
- DeadLetterBinding：单条源队列 -> DLQ 绑定声明
- DeadLetterRecord：一次死信投递的结构化记录
- build_dead_letter_queues：批量构造源队列与 DLQ 队列
- build_dead_letter_routes：按任务名前缀生成 DLQ 路由
- forward_to_dead_letter：显式把失败任务转发到 DLQ
- redrive_dead_letter：显式把死信任务重投递回原队列

设计要点：
- 仅抽象最小可复用路径，不隐藏 broker 差异
- RabbitMQ 使用原生 DLX 语义；Redis 不支持原生 DLX，因此退化为显式转发
- 不提供隐式自动重投，不内置死信判定策略
- 不依赖真实 broker；所有接口均可在单元测试中通过 mock 验证
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kombu import Exchange, Queue

from ab_celery.queues import build_queues
from ab_celery.routing import RouteRule, build_routes

logger = logging.getLogger("ab_celery.dead_letter")

_SUPPORTED_BROKERS = frozenset({"rabbitmq", "redis"})


@dataclass(frozen=True)
class DeadLetterBinding:
    """
    单条死信绑定声明。

    字段：
        source_queue: 原始业务队列名
        dead_letter_queue: 死信队列名
        source_options: 源队列附加选项
        dead_letter_options: DLQ 附加选项
        routing_key: 可选；显式指定源队列的 routing_key
        dead_letter_routing_key: 可选；显式指定 DLQ 的 routing_key
        match: 精确任务名；与 prefix 二选一，用于 build_dead_letter_routes
        prefix: 任务名前缀；与 match 二选一

    约束：
        - source_queue / dead_letter_queue 必须为非空字符串，且不能相同
        - source_options / dead_letter_options 必须为 dict
        - match / prefix 至多指定一个
    """

    source_queue: str
    dead_letter_queue: str
    source_options: dict[str, Any] = field(default_factory=dict)
    dead_letter_options: dict[str, Any] = field(default_factory=dict)
    routing_key: str | None = None
    dead_letter_routing_key: str | None = None
    match: str | None = None
    prefix: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_queue, str) or not self.source_queue:
            raise TypeError("DeadLetterBinding.source_queue 必须为非空字符串")
        if not isinstance(self.dead_letter_queue, str) or not self.dead_letter_queue:
            raise TypeError("DeadLetterBinding.dead_letter_queue 必须为非空字符串")
        if self.source_queue == self.dead_letter_queue:
            raise ValueError("source_queue 与 dead_letter_queue 不能相同")
        if not isinstance(self.source_options, dict):
            raise TypeError("DeadLetterBinding.source_options 必须为 dict")
        if not isinstance(self.dead_letter_options, dict):
            raise TypeError("DeadLetterBinding.dead_letter_options 必须为 dict")
        if self.routing_key is not None and (
            not isinstance(self.routing_key, str) or not self.routing_key
        ):
            raise TypeError("DeadLetterBinding.routing_key 必须为非空字符串或 None")
        if self.dead_letter_routing_key is not None and (
            not isinstance(self.dead_letter_routing_key, str)
            or not self.dead_letter_routing_key
        ):
            raise TypeError(
                "DeadLetterBinding.dead_letter_routing_key 必须为非空字符串或 None"
            )

        has_match = isinstance(self.match, str) and self.match != ""
        has_prefix = isinstance(self.prefix, str) and self.prefix != ""
        if has_match and has_prefix:
            raise ValueError("DeadLetterBinding.match 与 prefix 不能同时指定")
        if self.match is not None and not has_match:
            raise TypeError("DeadLetterBinding.match 必须为非空字符串或 None")
        if self.prefix is not None and not has_prefix:
            raise TypeError("DeadLetterBinding.prefix 必须为非空字符串或 None")


@dataclass(frozen=True)
class DeadLetterRecord:
    """
    一次死信投递记录。

    字段：
        task_name: 任务名
        queue: 原始队列名
        payload: 原任务载荷，由调用方决定结构
        reason: 死信原因，由调用方决定文本
        task_id: 可选，原任务 ID
        headers: 可选，附加头信息
    """

    task_name: str
    queue: str
    payload: dict[str, Any]
    reason: str
    task_id: str | None = None
    headers: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.task_name, str) or not self.task_name:
            raise TypeError("DeadLetterRecord.task_name 必须为非空字符串")
        if not isinstance(self.queue, str) or not self.queue:
            raise TypeError("DeadLetterRecord.queue 必须为非空字符串")
        if not isinstance(self.payload, dict):
            raise TypeError("DeadLetterRecord.payload 必须为 dict")
        if not isinstance(self.reason, str) or not self.reason:
            raise TypeError("DeadLetterRecord.reason 必须为非空字符串")
        if self.task_id is not None and (
            not isinstance(self.task_id, str) or not self.task_id
        ):
            raise TypeError("DeadLetterRecord.task_id 必须为非空字符串或 None")
        if not isinstance(self.headers, dict):
            raise TypeError("DeadLetterRecord.headers 必须为 dict")


def _validate_broker_kind(broker_kind: str) -> None:
    if broker_kind not in _SUPPORTED_BROKERS:
        raise ValueError(
            f"broker_kind 仅支持 {sorted(_SUPPORTED_BROKERS)!r}，收到 {broker_kind!r}"
        )


def _dedupe_bindings(bindings: list[DeadLetterBinding]) -> None:
    seen_source: set[str] = set()
    seen_dead_letter: set[str] = set()
    for binding in bindings:
        if binding.source_queue in seen_source:
            raise ValueError(f"重复的 source_queue 绑定：{binding.source_queue!r}")
        if binding.dead_letter_queue in seen_dead_letter:
            raise ValueError(
                f"重复的 dead_letter_queue 绑定：{binding.dead_letter_queue!r}"
            )
        seen_source.add(binding.source_queue)
        seen_dead_letter.add(binding.dead_letter_queue)


def _build_dead_letter_exchange(name: str) -> Exchange:
    return Exchange(name, type="direct")


def _build_rabbitmq_queue_specs(
    bindings: list[DeadLetterBinding],
) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    for binding in bindings:
        dlq_routing_key = binding.dead_letter_routing_key or binding.dead_letter_queue
        dlx_name = f"{binding.dead_letter_queue}.dlx"
        dlx = _build_dead_letter_exchange(dlx_name)

        source_options = dict(binding.source_options)
        if binding.routing_key is not None:
            source_options.setdefault("routing_key", binding.routing_key)
        source_options.setdefault(
            "queue_arguments",
            {
                "x-dead-letter-exchange": dlx_name,
                "x-dead-letter-routing-key": dlq_routing_key,
            },
        )

        dead_letter_options = dict(binding.dead_letter_options)
        dead_letter_options.setdefault("exchange", dlx)
        dead_letter_options.setdefault("routing_key", dlq_routing_key)

        specs.append((binding.source_queue, source_options))
        specs.append((binding.dead_letter_queue, dead_letter_options))
    return specs


def _build_redis_queue_specs(
    bindings: list[DeadLetterBinding],
) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    for binding in bindings:
        source_options = dict(binding.source_options)
        if binding.routing_key is not None:
            source_options.setdefault("routing_key", binding.routing_key)

        dead_letter_options = dict(binding.dead_letter_options)
        if binding.dead_letter_routing_key is not None:
            dead_letter_options.setdefault(
                "routing_key", binding.dead_letter_routing_key
            )

        specs.append((binding.source_queue, source_options))
        specs.append((binding.dead_letter_queue, dead_letter_options))
    return specs


def build_dead_letter_queues(
    bindings: list[DeadLetterBinding],
    *,
    broker_kind: str,
) -> list[Queue]:
    """
    按绑定声明批量构造源队列与 DLQ 队列。

    参数：
        bindings: 死信绑定声明列表
        broker_kind: broker 类型，仅支持 rabbitmq / redis

    返回：
        list[kombu.Queue]，可直接赋给 CeleryConfig.task_queues

    规则：
        - RabbitMQ：源队列自动补齐原生 DLX 参数，DLQ 绑定到独立 direct exchange
        - Redis：仅声明业务队列与 DLQ，不添加原生死信参数
    """
    if bindings is None:
        raise TypeError("bindings 不能为 None")
    if not isinstance(bindings, list):
        raise TypeError("bindings 必须为 list[DeadLetterBinding]")

    _validate_broker_kind(broker_kind)
    for binding in bindings:
        if not isinstance(binding, DeadLetterBinding):
            raise TypeError(
                f"bindings 元素必须为 DeadLetterBinding，收到 {type(binding).__name__}"
            )
    _dedupe_bindings(bindings)

    if broker_kind == "rabbitmq":
        return build_queues(_build_rabbitmq_queue_specs(bindings))
    return build_queues(_build_redis_queue_specs(bindings))


def build_dead_letter_routes(
    bindings: list[DeadLetterBinding],
) -> dict[str, dict[str, Any]]:
    """
    从 DeadLetterBinding 中提取 match/prefix 规则，生成 DLQ 路由表。

    说明：
        - 仅为显式转发场景服务，key/value 与 Celery 原生 task_routes 兼容
        - 未声明 match/prefix 的 binding 不参与路由生成
        - options 只写入 queue，不自动注入 routing_key/exchange，避免越权覆盖
    """
    if bindings is None:
        raise TypeError("bindings 不能为 None")
    if not isinstance(bindings, list):
        raise TypeError("bindings 必须为 list[DeadLetterBinding]")

    rules: list[RouteRule] = []
    for binding in bindings:
        if not isinstance(binding, DeadLetterBinding):
            raise TypeError(
                f"bindings 元素必须为 DeadLetterBinding，收到 {type(binding).__name__}"
            )
        if binding.match is not None:
            rules.append(RouteRule(queue=binding.dead_letter_queue, match=binding.match))
        elif binding.prefix is not None:
            rules.append(RouteRule(queue=binding.dead_letter_queue, prefix=binding.prefix))
    return build_routes(rules)


def forward_to_dead_letter(
    publisher: Any,
    record: DeadLetterRecord,
    *,
    dead_letter_queue: str,
    headers: dict[str, Any] | None = None,
) -> None:
    """
    显式把失败任务转发到 DLQ。

    参数：
        publisher: 具备 delay 或 apply_async 方法的发送对象
        record: 结构化死信记录
        dead_letter_queue: 目标 DLQ 名
        headers: 可选；额外头信息，优先级高于 record.headers

    行为：
        - 优先调用 publisher.apply_async，透传 queue 与 headers
        - 若无 apply_async，则退化为 publisher.delay(record_dict)
        - 仅做显式调用，不负责异常吞掉与重试
    """
    if not isinstance(record, DeadLetterRecord):
        raise TypeError(
            f"record 必须为 DeadLetterRecord，收到 {type(record).__name__}"
        )
    if not isinstance(dead_letter_queue, str) or not dead_letter_queue:
        raise TypeError("dead_letter_queue 必须为非空字符串")

    merged_headers = dict(record.headers)
    if headers:
        if not isinstance(headers, dict):
            raise TypeError("headers 必须为 dict 或 None")
        merged_headers.update(headers)

    payload = {
        "task_name": record.task_name,
        "queue": record.queue,
        "task_id": record.task_id,
        "reason": record.reason,
        "payload": record.payload,
        "headers": merged_headers,
    }

    if hasattr(publisher, "apply_async"):
        publisher.apply_async(args=(payload,), queue=dead_letter_queue, headers=merged_headers)
    elif hasattr(publisher, "delay"):
        publisher.delay(payload)
    else:
        raise TypeError("publisher 必须具备 apply_async 或 delay 方法")

    logger.warning(
        "[dead_letter] forward task=%s source_queue=%s dlq=%s reason=%s task_id=%s",
        record.task_name,
        record.queue,
        dead_letter_queue,
        record.reason,
        record.task_id,
    )


def redrive_dead_letter(
    publisher: Any,
    record: DeadLetterRecord,
    *,
    target_queue: str | None = None,
    headers: dict[str, Any] | None = None,
) -> None:
    """
    显式把死信任务重投递回目标队列。

    参数：
        publisher: 具备 apply_async 方法的发送对象
        record: 结构化死信记录
        target_queue: 显式目标队列；为 None 时回投到 record.queue
        headers: 可选，附加头，合并后注入 dead_letter_redrive 标记
    """
    if not isinstance(record, DeadLetterRecord):
        raise TypeError(
            f"record 必须为 DeadLetterRecord，收到 {type(record).__name__}"
        )
    if not hasattr(publisher, "apply_async"):
        raise TypeError("publisher 必须具备 apply_async 方法")

    queue = record.queue if target_queue is None else target_queue
    if not isinstance(queue, str) or not queue:
        raise TypeError("target_queue 必须为非空字符串或 None")

    merged_headers = dict(record.headers)
    merged_headers["dead_letter_redrive"] = True
    if headers:
        if not isinstance(headers, dict):
            raise TypeError("headers 必须为 dict 或 None")
        merged_headers.update(headers)

    publisher.apply_async(
        kwargs=dict(record.payload),
        queue=queue,
        headers=merged_headers,
    )

    logger.info(
        "[dead_letter] redrive task=%s from_dlq=%s target_queue=%s task_id=%s",
        record.task_name,
        record.queue,
        queue,
        record.task_id,
    )


__all__ = [
    "DeadLetterBinding",
    "DeadLetterRecord",
    "build_dead_letter_queues",
    "build_dead_letter_routes",
    "forward_to_dead_letter",
    "redrive_dead_letter",
]
