"""线程上下文传播抽象（与 :mod:`ab_thread.local` 配合）。

``local`` 提供**线程隔离**的存储，本模块提供**跨线程传播** 的能力描述：父线程在创建
子线程（或提交到线程池）时，将其 ``local`` 等上下文快照带过去，子线程执行期间可见，
结束后自动清理，互不污染。

设计原则：保持 ``ab_thread`` 零三方依赖。本模块只定义传播接口与默认实现
（:class:`LocalPropagator`，仅传播 ``local``）；任何“额外上下文”（Django 时区/语言、
DB 连接、tracing 等）都通过 :class:`ContextPropagator` 接口**由调用方自行注入**，
不在此处硬编码任何框架依赖。具体的线程机件见 :mod:`ab_thread.thread`。

典型用法::

    from ab_thread import local, InheritParentThread, ThreadPool

    local.user_id = 1001

    def worker():
        assert local.user_id == 1001  # 继承自父线程

    t = InheritParentThread(target=worker)
    t.start(); t.join()

    # 线程池
    with ThreadPool(4) as pool:
        pool.map_async(lambda: local.user_id, [None] * 3)

Django 场景（由调用方在自己的模块里实现，本模块不含 Django 依赖）::

    from ab_thread import ContextPropagator

    class DjangoPropagator(ContextPropagator):
        def capture(self):
            from django.utils import timezone, translation
            return (timezone.get_current_timezone().zone, translation.get_language())

        def apply(self, ctx):
            from django.utils import timezone, translation
            timezone.activate(ctx[0]); translation.activate(ctx[1])

        def cleanup(self):
            from django.db import connections
            connections.close_all()  # 释放线程持有的 DB 连接

    InheritParentThread(target=worker, propagators=[LocalPropagator(), DjangoPropagator()])
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar
from collections.abc import Callable

from ab_thread.local import local

__all__ = ["ContextPropagator", "LocalPropagator", "capture_context", "run_with_context"]

T = TypeVar("T")


class ContextPropagator(ABC):
    """跨线程上下文传播器接口。

    实现“父线程取快照 → 子线程恢复 → 子线程收尾”三段式。
    默认实现见 :class:`LocalPropagator`；调用方按需子类化以携带框架上下文
    （如 Django 时区/语言、DB 连接、OpenTelemetry tracing 等）。

    三个方法均在**对应线程**内调用：``capture`` 在父线程、``apply``/``cleanup``
    在子线程，因此各自访问的都是当前线程自己的状态，天然线程安全。
    """

    @abstractmethod
    def capture(self) -> Any:
        """在父线程中采集上下文快照，返回值原样传给 :meth:`apply`。"""

    @abstractmethod
    def apply(self, ctx: Any) -> None:
        """在子线程中恢复上下文（``ctx`` 为 :meth:`capture` 的返回值）。"""

    @abstractmethod
    def cleanup(self) -> None:
        """在子线程任务结束后清理上下文（释放连接、清空 local 等）。"""


class LocalPropagator(ContextPropagator):
    """默认传播器：仅同步 :data:`ab_thread.local.local` 的全部属性。

    ``local.__iter__`` 返回 ``iter(list(...))``，因此 ``capture`` 返回的列表
    与原 ``local`` 命名空间解耦，后续对 ``local`` 的增删不影响已拍快照。
    """

    def capture(self) -> list[tuple[str, Any]]:
        return list(local)  # [(key, value), ...]

    def apply(self, ctx: list[tuple[str, Any]]) -> None:
        for key, value in ctx:
            setattr(local, key, value)

    def cleanup(self) -> None:
        # 子线程运行期间可能写入新属性，一并清理避免泄漏到后续复用
        for key, _ in list(local):
            delattr(local, key)


def capture_context(propagators: list[ContextPropagator]) -> list[tuple[ContextPropagator, Any]]:
    """在父线程内拍摄传播器上下文快照，返回 ``[(propagator, ctx), ...]``。

    须在父线程中调用；返回值（含各传播器的快照）应随构造参数或闭包冻结后传入子线程，
    供 :meth:`ContextPropagator.apply` 恢复，子线程不再回读父线程状态，避免跨线程竞态。
    """
    return [(p, p.capture()) for p in propagators]


def run_with_context(
    func: Callable[..., T],
    captured: list[tuple[ContextPropagator, Any]],
    *args: Any,
    **kwargs: Any,
) -> T:
    """在指定上下文快照中执行函数，结束后清理（同线程内，不新建线程）。

    适用于：已在 worker 线程内，需要用**外部传入**的快照恢复上下文后执行任务，
    例如自定义线程/执行器在父线程拍摄快照后传入。本函数是
    :class:`InheritParentThread` 与 :class:`ThreadPool` 内部 apply→run→cleanup
    逻辑的等价提取，便于调用方在不新建线程时复用同一套上下文生命周期。

    :param func: 待执行函数
    :param captured: 由 :meth:`ContextPropagator.capture` 采集的快照列表，
                     形如 ``[(propagator, ctx), ...]``；通常由父线程拍摄后传入
    :param args/kwargs: 透传给 ``func``
    :return: ``func`` 的返回值
    """
    for propagator, ctx in captured:
        propagator.apply(ctx)
    try:
        return func(*args, **kwargs)
    finally:
        for propagator, _ in captured:
            propagator.cleanup()
