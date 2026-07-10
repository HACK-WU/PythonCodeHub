"""线程机件：在子线程 / 线程池中继承父线程上下文。

消费 :mod:`ab_thread.context` 中的 :class:`ContextPropagator` 抽象，把“父线程拍快照 →
子线程恢复 → 子线程收尾”落到具体线程实现上。默认仅传播 ``local``（:class:`LocalPropagator`），
需要额外上下文（Django 时区/语言、DB 连接等）由调用方通过 ``propagators`` 注入。

典型用法::

    from ab_thread import local, InheritParentThread, ThreadPool

    local.user_id = 1001

    def worker():
        assert local.user_id == 1001  # 继承自父线程

    t = InheritParentThread(target=worker)
    t.start(); t.join()

    with ThreadPool(4) as pool:
        pool.map_async(lambda: local.user_id, [None] * 3)
"""

from __future__ import annotations

import functools
import logging
import threading
from multiprocessing.pool import ThreadPool as _ThreadPool
from types import TracebackType
from typing import Any, TypeVar
from collections.abc import Callable, Iterable

from ab_thread.context import ContextPropagator, LocalPropagator, capture_context

logger = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["InheritParentThread", "ThreadPool"]


class InheritParentThread(threading.Thread):
    """支持继承父线程上下文（默认仅 ``local``）的线程类。

    构造时（父线程内）拍摄所有传播器的上下文快照并冻结，``start`` 后在子线程内
    :meth:`sync` 恢复，任务结束后 :meth:`unsync` 清理。

    :param propagators: 传播器列表；默认 ``[LocalPropagator()]``。
    :param args/kwargs: 透传给 :class:`threading.Thread`。
    """

    def __init__(
        self,
        *args: Any,
        propagators: list[ContextPropagator] | None = None,
        **kwargs: Any,
    ) -> None:
        self._propagators: list[ContextPropagator] = propagators if propagators is not None else [LocalPropagator()]
        # 构造时在父线程内拍摄快照并冻结；构造后、start 前的 local 修改不纳入本次继承
        self._captured: list[tuple[ContextPropagator, Any]] = self._capture()
        super().__init__(*args, **kwargs)

    def _capture(self) -> list[tuple[ContextPropagator, Any]]:
        """在父线程内拍摄所有传播器的上下文快照（构造时调用）。"""
        return capture_context(self._propagators)

    def sync(self) -> None:
        """将父线程上下文同步到当前（子）线程。"""
        # 本方法在子线程内执行；self._captured 已由构造时的 _capture() 在父线程拍摄并冻结
        # 直接调用 run()（不经 start()）时 _captured 为 None（理论上不会，构造时已拍摄），此处兜底
        if not self._captured:
            return
        for propagator, ctx in self._captured:
            propagator.apply(ctx)

    def unsync(self) -> None:
        """清理当前（子）线程的上下文。"""
        # 此阶段 ctx 已无用，仅逐传播器触发 cleanup（如关闭 DB 连接、清空 local）
        # 与 sync() 对称：_captured 为 None 时跳过
        if not self._captured:
            return
        for propagator, _ in self._captured:
            propagator.cleanup()

    def run(self) -> None:
        # 子线程入口：先恢复父线程上下文，再执行构造时传入的 target
        # （super().run() 会按约定调用 self._target(*self._args, **self._kwargs)）；
        # 无论成功或异常都执行 unsync 清理；异常仅记录不向上抛——子线程无法把异常传播到父线程
        self.sync()
        try:
            super().run()
        except Exception:  # noqa: BLE001 - 子线程异常需记录避免静默丢失
            logger.exception("InheritParentThread.run failed")
        finally:
            # finally 保证即使记录异常时也执行清理，防止子线程上下文泄漏
            self.unsync()


class ThreadPool(_ThreadPool):
    """支持线程局部变量继承的线程池（包装标准库 ``multiprocessing.pool.ThreadPool``）。

    提交到池中的任务会自动在 worker 线程内恢复父线程上下文，执行后清理。
    通过 ``propagators`` 注入需要扩展的上下文（默认仅 ``local``）。

    :param args/kwargs: 透传给 :class:`multiprocessing.pool.ThreadPool`。
    :param propagators: 传播器列表；默认 ``[LocalPropagator()]``。
    """

    def __init__(
        self,
        *args: Any,
        propagators: list[ContextPropagator] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._propagators: list[ContextPropagator] = propagators if propagators is not None else [LocalPropagator()]

    def __enter__(self) -> ThreadPool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        # 优雅关闭：close() 禁止再提交新任务，join() 等待在途任务完成并回收 worker 线程。
        # 若希望立即强制终止（不等待在途任务），可改用 self.terminate()
        self.close()
        self.join()
        return False

    def _wrap(self, func: Callable[..., T]) -> Callable[..., T]:
        """捕获当前（父）线程上下文并包装 ``func``，使其在 worker 内继承+清理。"""
        # 关键：在【提交任务的父线程】此刻拍摄快照，快照随闭包冻结传入 worker 线程；
        # worker 内仅负责 apply/cleanup，不再接触父线程状态，避免跨线程竞态
        captured = capture_context(self._propagators)

        @functools.wraps(func)  # 保留原函数 __name__/__doc__，便于日志与重试逻辑识别
        def wrapper(*args: Any, **kwargs: Any) -> T:
            for propagator, ctx in captured:
                propagator.apply(ctx)
            try:
                return func(*args, **kwargs)
            finally:
                # finally 保证即使任务抛异常也执行 cleanup，防止 worker 线程上下文泄漏
                for propagator, _ in captured:
                    propagator.cleanup()

        return wrapper

    def map_ignore_exception(
        self,
        func: Callable[..., T],
        iterable: Iterable[Any],
        return_exception: bool = False,
    ) -> list[T | BaseException]:
        """忽略错误版的 ``map``：单个任务异常不中断其余任务。

        注意：本方法逐任务调用 :meth:`apply_async`，因此每个任务在**提交时刻**
        独立拍摄父线程上下文快照（与 :meth:`map_async` 整批共享一次快照不同）；
        若提交期间父线程上下文不变，两者行为一致。

        :param func: 要执行的函数
        :param iterable: 参数可迭代对象（每个元素作为 ``args`` 传入；
                         非 tuple/list 会被包成单元素 tuple）
        :param return_exception: 是否将异常对象作为结果返回
        :return: 结果列表
        """
        futures = []
        for params in iterable:
            if not isinstance(params, tuple | list):
                params = (params,)
            futures.append(self.apply_async(func, args=params))

        results = []
        for future in futures:
            try:
                results.append(future.get())
            except Exception as exc:  # noqa: BLE001
                if return_exception:
                    results.append(exc)
                logger.exception("ThreadPool.map_ignore_exception task failed")
        return results

    # 以下四个方法统一在提交任务前用 self._wrap 包裹 func，使任务在 worker 线程内
    # 自动继承+清理父线程上下文；其余参数（chunksize/callback/args/kwds）原样透传基类

    def map_async(  # noqa
        self,
        func: Callable[..., Any],
        iterable: Iterable[Any],
        chunksize: int | None = None,
        callback: Callable[[Any], None] | None = None,
    ) -> Any:
        # 批量异步：iterable 中每个元素作为一次任务入参，并行执行
        return super().map_async(self._wrap(func), iterable, chunksize=chunksize, callback=callback)

    def apply_async(  # noqa
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwds: dict[str, Any] | None = None,
        callback: Callable[[Any], None] | None = None,
    ) -> Any:
        # 单任务异步；kwds 默认 {} 以避免可变默认参数陷阱
        kwds = kwds or {}
        return super().apply_async(self._wrap(func), args=args, kwds=kwds, callback=callback)

    def imap(
        self,
        func: Callable[..., Any],
        iterable: Iterable[Any],
        chunksize: int = 1,
    ) -> Any:
        # 惰性迭代器版 map（按提交顺序产出结果）
        return super().imap(self._wrap(func), iterable, chunksize=chunksize)

    def imap_unordered(
        self,
        func: Callable[..., Any],
        iterable: Iterable[Any],
        chunksize: int = 1,
    ) -> Any:
        # 惰性迭代器版 map（结果就绪即产出，不保证顺序，吞吐更高）
        return super().imap_unordered(self._wrap(func), iterable, chunksize=chunksize)
