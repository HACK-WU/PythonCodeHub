"""
orchestration — Celery Canvas 编排原语薄封装

仅暴露：
- build_chain / build_group / build_chord：三种声明式编排入口
- log_orchestration_apply：编排触发后的统一 INFO 日志钩子

设计要点（详见 .codebuddy/plan/track-a-orchestration/requirements.md）：
- 薄封装：返回对象就是 Celery 原生 chain/group/chord，行为完全一致
- 可降级：调用方可随时退回 celery.chain / celery.group / celery.chord
- 不重新发明 Canvas：未覆盖能力（starmap/chunks/map）请直接使用原生 API
- 不修改消息体：name 仅作为对象属性写入，不污染 broker 序列化结果
- 不叠加重试：与 AutoRetryTask 协同时，不在编排层添加任何重试逻辑
- 失败传播策略：与 Celery 默认完全一致，不做隐式覆盖

仅依赖 celery 与 logging，不引入 ab_celery 内部其他模块。

用法：
    from ab_celery.orchestration import build_chain, build_group, build_chord

    workflow = build_chain(task_a.s(1), task_b.s(), name="user-onboard")
    async_result = workflow.apply_async()
"""

import logging
from typing import Iterable, Optional

from celery.canvas import Signature, _chain, _chord, chain, chord, group

logger = logging.getLogger("ab_celery.orchestration")

# 编排对象上记录可读名称的属性键，避免与 Canvas 自身属性冲突
_NAME_ATTR = "_ab_orchestration_name"

__all__ = [
    "build_chain",
    "build_group",
    "build_chord",
    "log_orchestration_apply",
]


def _validate_signatures(items: Iterable, ctx: str) -> list:
    """
    校验编排成员，返回经过类型确认的成员列表

    参数:
        items: 待校验的可迭代成员
        ctx: 上下文名称，用于异常消息（"chain" / "group" / "chord header"）

    返回值:
        list[Signature]：校验通过的成员列表

    1. 物化为 list 以便索引定位
    2. 空列表抛 ValueError，明确指出 ctx 至少需要 1 个成员
    3. 任一成员非 Signature 抛 TypeError，消息中标明索引
    """
    members = list(items)
    if not members:
        raise ValueError(f"{ctx} 至少需要 1 个成员")
    for idx, item in enumerate(members):
        if not isinstance(item, Signature):
            raise TypeError(
                f"{ctx} 第 {idx} 个成员必须是 celery Signature，"
                f"实际类型为 {type(item).__name__}"
            )
    return members


def _validate_name(name: Optional[str]) -> None:
    """校验 name：允许 None，否则必须是非空字符串"""
    if name is None:
        return
    if not isinstance(name, str) or not name:
        raise ValueError("name 必须是非空字符串或 None")


def _attach_name(obj, name: Optional[str]):
    """将 name 写入对象属性；name 为 None 时不修改任何字段"""
    if name is not None:
        setattr(obj, _NAME_ATTR, name)
    return obj


def build_chain(*signatures: Signature, name: Optional[str] = None) -> chain:
    """
    构造 celery chain 编排对象（薄封装）

    参数:
        *signatures: 至少 1 个 Signature 成员，按顺序串行执行
        name: 可选，可读名称，仅记录在返回对象的 _ab_orchestration_name 属性上

    返回值:
        celery.canvas.chain：与原生 chain 完全等价的可调用对象

    1. 校验 name 合法性
    2. 校验成员非空且全部为 Signature
    3. 构造 chain，附加 name 属性后返回
    """
    _validate_name(name)
    members = _validate_signatures(signatures, "chain")
    obj = chain(*members)
    return _attach_name(obj, name)


def build_group(*signatures: Signature, name: Optional[str] = None) -> group:
    """
    构造 celery group 编排对象（薄封装）

    参数:
        *signatures: 至少 1 个 Signature 成员，并行执行
        name: 可选，可读名称

    返回值:
        celery.canvas.group：与原生 group 完全等价的可调用对象

    1. 校验 name 合法性
    2. 校验成员非空且全部为 Signature
    3. 构造 group，附加 name 属性后返回
    """
    _validate_name(name)
    members = _validate_signatures(signatures, "group")
    obj = group(*members)
    return _attach_name(obj, name)


def build_chord(
    header: Iterable[Signature],
    body: Signature,
    *,
    name: Optional[str] = None,
) -> chord:
    """
    构造 celery chord 编排对象（薄封装）

    参数:
        header: 至少 1 个 Signature 成员的可迭代对象，并行执行
        body: 单个 Signature，header 全部完成后触发
        name: 可选，可读名称

    返回值:
        celery.canvas.chord：与原生 chord 完全等价的可调用对象

    1. 校验 name 合法性
    2. 校验 header 非空且全部为 Signature
    3. 校验 body 为 Signature 类型
    4. 构造 chord，附加 name 属性后返回；不为 AutoRetryTask 重试中场景追加判定逻辑
    """
    _validate_name(name)
    header_members = _validate_signatures(header, "chord header")
    if not isinstance(body, Signature):
        raise TypeError(
            f"chord body 必须是 celery Signature，"
            f"实际类型为 {type(body).__name__}"
        )
    obj = chord(header_members, body)
    return _attach_name(obj, name)


def log_orchestration_apply(orch_obj, async_result) -> None:
    """
    编排对象触发后的统一日志钩子

    参数:
        orch_obj: 编排对象，可为 build_chain/build_group/build_chord 返回值
                  或原生 celery.chain / group / chord
        async_result: orch_obj.apply_async() / .delay() 的返回值

    1. 推断编排类型（chain/group/chord/unknown）
    2. 读取 _ab_orchestration_name（若有）
    3. 估算成员数量（chord 取 header 长度）
    4. 输出一条 INFO 日志，包含类型、name、成员数、根任务 ID

    本函数不做任何副作用修改，仅打印日志；与原生 Canvas 对象兼容。
    """
    # 类型识别：优先匹配 chord（chord 不是 chain/group 子类）
    # 注意：celery 的 chain()/chord() 是用户面 API，构造的实例类是 _chain/_chord
    if isinstance(orch_obj, _chord):
        kind = "chord"
        try:
            member_count = len(list(orch_obj.tasks))
        except Exception:
            member_count = -1
    elif isinstance(orch_obj, _chain):
        kind = "chain"
        member_count = len(getattr(orch_obj, "tasks", ()) or ())
    elif isinstance(orch_obj, group):
        kind = "group"
        member_count = len(getattr(orch_obj, "tasks", ()) or ())
    else:
        kind = "unknown"
        member_count = -1

    name = getattr(orch_obj, _NAME_ATTR, None)
    root_id = getattr(async_result, "id", None) or getattr(
        async_result, "task_id", None
    )

    logger.info(
        "[orchestration] kind=%s name=%s members=%s root_id=%s",
        kind,
        name if name is not None else "-",
        member_count,
        root_id,
    )
