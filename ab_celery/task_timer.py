"""
task_timer — Celery 任务自动计时与 MetricsRecorder 协议

背景：
    为 Celery 任务添加执行计时是常见的可观测性需求。手动为每个任务添加计时代码
    既繁琐又容易遗漏。本模块提供两种方式：

    1. install_task_timer：monkey-patch app.task，自动为所有注册任务包裹计时器
    2. task_timer：装饰器，为单个函数添加计时和异常记录

设计要点：
    - MetricsRecorder 是一个 Protocol，定义了计时接口。用户可实现自己的 Recorder
      对接 Prometheus、StatsD、OpenTelemetry 等任意后端
    - install_task_timer 不绑定任何特定指标后端，通过 recorder 参数注入
    - task_timer 装饰器同样通过 recorder 参数解耦指标后端

用法：
    # 1. 实现 MetricsRecorder
    class MyRecorder:
        def record_time(self, task_name, queue, exception_name, duration):
            my_metrics.histogram("task_duration", duration, labels={
                "task": task_name, "queue": queue, "exception": exception_name
            })

    # 2. 安装自动计时
    from ab_celery.task_timer import install_task_timer
    app = Celery("myapp")
    install_task_timer(app, recorder=MyRecorder())

    # 3. 或使用装饰器为单个函数计时
    from ab_celery.task_timer import task_timer

    @task_timer(queue="celery", recorder=MyRecorder())
    def my_task():
        ...

依赖：
    - celery

参考：
    原始实现源自 bk-monitor 的 core/prometheus/tools.py 中的
    celery_app_timer、task_timer 和 hack_task。
"""

import time
import typing
from functools import wraps
from types import MethodType


class MetricsRecorder(typing.Protocol):
    """
    任务计时指标记录器协议。

    任何实现了 record_time 方法的对象均可作为 recorder 使用，
    无需显式继承本 Protocol（鸭子类型）。
    """

    def record_time(self, task_name: str, queue: str, exception_name: str, duration: float) -> None:
        """
        记录一次任务执行耗时。

        Args:
            task_name: 任务名称（函数名）
            queue: 队列名称
            exception_name: 异常类名，无异常时为 "None"
            duration: 执行耗时（秒）
        """
        ...


class _DefaultRecorder:
    """默认 recorder：使用 logging 记录任务耗时。"""

    def __init__(self) -> None:
        import logging

        self._logger = logging.getLogger("ab_celery.task_timer")

    def record_time(self, task_name: str, queue: str, exception_name: str, duration: float) -> None:
        self._logger.info(
            "[task_timer] task=%s queue=%s exception=%s duration=%.3fs",
            task_name,
            queue,
            exception_name,
            duration,
        )


def task_timer(
    queue: str = "celery",
    recorder: MetricsRecorder | None = None,
) -> typing.Callable[[typing.Callable], typing.Callable]:
    """
    函数计时装饰器。

    包裹被装饰函数，记录执行耗时和异常信息，通过 recorder 上报。

    Args:
        queue: 队列名称，传递给 recorder 作为标签。
        recorder: 指标记录器，为 None 时使用默认的 logging recorder。

    Returns:
        装饰器函数。

    用法：
        @task_timer(queue="celery", recorder=my_recorder)
        def my_task():
            ...
    """
    if recorder is None:
        recorder = _DefaultRecorder()

    def actual_timer(func: typing.Callable) -> typing.Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result, exception = None, None
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                exception = e

            exception_name = exception.__class__.__name__ if exception else "None"
            recorder.record_time(
                task_name=func.__name__,
                queue=queue,
                exception_name=exception_name,
                duration=time.time() - start_time,
            )

            if exception:
                raise exception
            return result

        return wrapper

    return actual_timer


def _hack_task(self, recorder: MetricsRecorder, *args, **kwargs):
    """
    替换 app.task 的 wrapper：为每个注册的任务自动包裹计时器。

    当 app.task 被调用时，实际执行流程：
    1. 调用原始 app.task 获取 task decorator
    2. 用 task_timer 包裹用户函数
    3. 将包裹后的函数传给原始 task decorator
    """

    def wrapper(func):
        return self._old_task(*args, **kwargs)(task_timer(queue=kwargs.get("queue"), recorder=recorder)(func))

    return wrapper


def install_task_timer(app, recorder: MetricsRecorder | None = None):
    """
    为 Celery app 安装任务自动计时。

    通过 monkey-patch app.task 方法，使所有后续注册的任务自动包裹计时器，
    无需逐个任务手动添加 @task_timer 装饰器。

    Args:
        app: Celery 应用实例。
        recorder: 指标记录器，为 None 时使用默认的 logging recorder。

    用法：
        from ab_celery.task_timer import install_task_timer

        app = Celery("myapp")
        install_task_timer(app, recorder=MyRecorder())

        # 之后注册的所有任务都会自动计时
        @app.task
        def my_task():
            ...
    """
    if recorder is None:
        recorder = _DefaultRecorder()

    app._old_task = app.task
    app.task = MethodType(lambda self, *a, **kw: _hack_task(self, recorder, *a, **kw), app)
