"""
task_base — 通用 Celery 任务基类

本模块只暴露：
- AutoRetryTask：带默认自动重试策略的任务基类

设计要点（详见设计文档第 10 章）：
- 仅承担「通用默认行为」：默认重试次数、退避、抖动、失败日志
- 默认仅对常见瞬时异常自动重试（ConnectionError / TimeoutError / OSError），
  避免把 ValueError 这类业务异常一并重试
- 子类可通过覆盖类属性调整重试策略
- 失败日志在「重试耗尽」时打印一次 ERROR；不替代业务自身告警
- 不导入 task_timer / redis / django / redbeat，保持低耦合，
  与 task_timer.install_task_timer 协同时不会产生重复计时

用法：
    from ab_celery.task_base import AutoRetryTask

    @app.task(base=AutoRetryTask, bind=True)
    def fetch_remote(self, url):
        ...

注意：
    自动重试的前提是任务幂等或可接受重复执行。非幂等任务请显式覆盖
    autoretry_for 或不要使用本基类。
"""

import logging

from celery import Task

logger = logging.getLogger("ab_celery.task_base")


class AutoRetryTask(Task):
    """
    通用自动重试任务基类。

    类属性约定（与 Celery >= 5.3 原生 Task 字段一致）：
    - autoretry_for：自动重试的异常元组，默认仅覆盖通用瞬时异常
    - max_retries：最大重试次数，默认 3
    - default_retry_delay：基础重试间隔（秒），默认 3
    - retry_backoff：是否启用指数退避，默认 True
    - retry_backoff_max：退避上限（秒），默认 600
    - retry_jitter：是否在退避基础上附加抖动，默认 True

    子类可通过覆盖以上属性调整策略，例如：

        class MyTask(AutoRetryTask):
            max_retries = 5
            default_retry_delay = 10
            autoretry_for = (ConnectionError,)
    """

    # 默认仅自动重试通用瞬时异常，避免误把业务异常纳入重试
    autoretry_for: tuple[type[BaseException], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    # 保守的默认重试参数
    max_retries: int = 3
    default_retry_delay: int = 3

    # 指数退避 + 抖动，避免重试风暴
    retry_backoff: bool = True
    retry_backoff_max: int = 600
    retry_jitter: bool = True

    # acks_late 不在此处强制开启，交由 CeleryConfig / 任务自身决定，
    # 避免与原本非幂等的任务耦合

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """
        任务最终失败回调。

        参数：
            exc: 失败时抛出的异常对象
            task_id: 当前任务 ID
            args: 任务位置参数
            kwargs: 任务关键字参数
            einfo: ExceptionInfo 对象

        步骤：
        1. 仅在「已达最大重试次数」时输出一条 ERROR 日志
           （未达上限的情况通常意味着 Celery 仍会安排下一次重试，
            重复打 ERROR 日志会污染监控）
        2. 调用父类 on_failure 完成 Celery 默认处理
        """
        retries = getattr(getattr(self, "request", None), "retries", 0) or 0
        if retries >= self.max_retries:
            logger.error(
                "[AutoRetryTask] 任务最终失败 task=%s id=%s retries=%s exc=%s: %s",
                self.name,
                task_id,
                retries,
                type(exc).__name__,
                exc,
            )
        return super().on_failure(exc, task_id, args, kwargs, einfo)
