"""
cron_registry — 配置驱动的 Cron 任务注册框架

背景：
    当项目中有大量周期任务时，直接在 Celery beat_schedule 中硬编码配置
    存在以下问题：
    - 任务与队列的映射关系散落在各处，难以维护
    - 无法按条件（如集群角色）动态过滤任务
    - expires 需要手动计算，容易出错或遗漏
    - 缺少统一的执行计时和异常记录

解决方案：
    CronRegistry 提供声明式的任务注册框架：
    - 任务声明为 (module_path, cron_expression, run_type) 元组
    - 按队列分组（queue_define），不同队列走不同 Worker
    - filter_fn 回调支持按条件过滤任务（如集群角色、环境变量等）
    - get_crontab_expires 自动计算 expires（5min~1h），防止过期任务堆积
    - task_duration 装饰器统一记录执行耗时和异常

用法：
    from celery import Celery
    from celery.schedules import crontab
    from ab_celery.cron_registry import CronRegistry, get_crontab_expires

    # 1. 定义队列 -> 任务列表映射
    queue_define = {
        "celery_cron": [
            ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
            ("myapp.tasks.refresh_cache", "* * * * *", "cluster"),
        ],
        "celery_heavy_cron": [
            ("myapp.tasks.bulk_process", "*/30 * * * *", "global"),
        ],
    }

    # 2. 定义过滤函数（可选）
    def my_filter(module_name: str, run_type: str) -> bool:
        # 全局任务仅在主节点执行
        if run_type == "global" and not is_primary_node():
            return False
        return True

    # 3. 创建注册器并注册所有任务
    app = Celery("myapp")
    registry = CronRegistry(queue_define, filter_fn=my_filter)
    registry.register_all(app)

依赖：
    - celery
    - Django（仅 import_string 需要，可替换为自定义 import_func）

参考：
    原始实现源自 bk-monitor 的 alarm_backends/service/scheduler/tasks/cron.py。
"""

import datetime
import functools
import logging
import time
import typing

from celery.schedules import crontab

logger = logging.getLogger("ab_celery.cron_registry")


def get_crontab_expires(schedule: crontab, min_expires: int = 300, max_expires: int = 3600) -> int:
    """
    根据 crontab 周期自动计算合理的 expires 值。

    原理：计算相邻两次执行的时间差（即周期长度），作为 expires 的参考值。
    expires 过短会导致任务因延迟而过期丢弃，过长则无法及时清理堆积任务。

    Args:
        schedule: crontab 实例。
        min_expires: 最小 expires（秒），默认 300（5 分钟）。
        max_expires: 最大 expires（秒），默认 3600（1 小时）。

    Returns:
        计算出的 expires 值，限制在 [min_expires, max_expires] 范围内。

    用法：
        run_every = crontab(minute="*/10")
        expires = get_crontab_expires(run_every)  # 约 600
    """
    now = schedule.now()
    next_delta = schedule.remaining_estimate(now)
    next_next_delta = schedule.remaining_estimate(now + next_delta + datetime.timedelta(minutes=1))
    interval = (next_next_delta - next_delta).seconds
    return min(max_expires, max(interval, min_expires))


def task_duration(task_name: str, queue_name: str | None = None):
    """
    任务执行计时装饰器。

    记录任务的执行耗时和异常信息，通过 logging 输出。
    使用 ^[Cron Task] / ![Cron Task] / $[Cron Task] 标记便于日志检索：
    - ^[Cron Task](name)：任务开始
    - ![Cron Task](name)：任务异常
    - $[Cron Task](name)：任务结束（含耗时）

    Args:
        task_name: 任务名称，用于日志标识。
        queue_name: 队列名称，用于日志标识。

    Returns:
        装饰器函数。

    用法：
        @task_duration("my_task", queue_name="celery_cron")
        def my_task():
            ...
    """

    def wrapper(_func):
        @functools.wraps(_func)
        def _inner(*args, **kwargs):
            start = time.time()
            logger.info("^[Cron Task](%s)", task_name)
            exception = None
            try:
                return _func(*args, **kwargs)
            except Exception as e:
                logger.exception("![Cron Task](%s) error: %s", task_name, e)
                exception = e
            finally:
                time_cost = time.time() - start
                logger.info("$[Cron Task](%s) cost: %.3fs", task_name, time_cost)

            if exception:
                raise exception

        return _inner

    return wrapper


def _default_import_func(module_path: str):
    """
    默认的模块导入函数，使用 Django 的 import_string。

    如果项目不使用 Django，可在 CronRegistry 构造时传入自定义 import_func。
    """
    from django.utils.module_loading import import_string

    return import_string(module_path)


class CronRegistry:
    """
    配置驱动的 Cron 任务注册器。

    从队列->任务列表映射中读取任务配置，按条件过滤后批量注册到 Celery app
    的 beat_schedule 中。

    Args:
        queue_define: 队列名 -> 任务列表的映射。
            任务列表中每项为 (module_path, cron_expression, run_type) 三元组：
            - module_path: 任务函数的模块路径（如 "myapp.tasks.cleanup"）
            - cron_expression: cron 表达式（如 "*/5 * * * *"）
            - run_type: 运行类型标识（如 "global"、"cluster"），用于 filter_fn 过滤
        filter_fn: 任务过滤回调，签名为 (module_name, run_type) -> bool。
            返回 False 时跳过该任务。默认不过滤。
        import_func: 模块导入函数，签名为 (module_path) -> object。
            默认使用 Django 的 import_string。
        default_expires: 默认 expires 计算函数，签名为 (crontab) -> int。
            默认使用 get_crontab_expires。

    用法：
        registry = CronRegistry(
            queue_define={"celery_cron": [("myapp.tasks.cleanup", "0 */2 * * *", "global")]},
            filter_fn=lambda name, run_type: run_type != "global" or is_primary(),
        )
        registry.register_all(app)
    """

    def __init__(
        self,
        queue_define: dict[str, list[tuple[str, str, str]]],
        filter_fn: typing.Callable[[str, str], bool] | None = None,
        import_func: typing.Callable[[str], typing.Any] | None = None,
        default_expires: typing.Callable[[crontab], int] | None = None,
    ):
        self.queue_define = queue_define
        self.filter_fn = filter_fn
        self.import_func = import_func or _default_import_func
        self.default_expires = default_expires or get_crontab_expires

    def _resolve_func(self, module_path: str, queue: str):
        """
        根据 module_path 解析并包装任务函数。

        尝试导入 module_path 对应的模块/函数：
        1. 先尝试直接导入 module_path，若结果有 main 属性则使用 main
        2. 失败则尝试导入 module_path.main

        包装后的函数自带 task_duration 计时逻辑。
        """

        def _inner_func(*args, **kwargs):
            try:
                process_func = self.import_func(module_path)
                process_func = getattr(process_func, "main", process_func)
            except ImportError:
                process_func = self.import_func(f"{module_path}.main")

            return task_duration(module_path, queue)(process_func)(*args, **kwargs)

        return _inner_func

    def register_all(self, app) -> None:
        """
        将所有通过过滤的任务注册到 Celery app 的 beat_schedule。

        遍历 queue_define 中的所有队列和任务，对每个任务：
        1. 调用 filter_fn 判断是否需要注册
        2. 解析 module_path 获取任务函数
        3. 解析 cron 表达式创建 crontab schedule
        4. 计算 expires
        5. 注册到 app.conf.beat_schedule

        Args:
            app: Celery 应用实例。
        """
        registered_count = 0
        for queue, crontab_tasks in self.queue_define.items():
            for module_name, cron_expr, run_type in crontab_tasks:
                # 过滤
                if self.filter_fn and not self.filter_fn(module_name, run_type):
                    continue

                func_name = str(module_name.replace(".", "_"))
                cron_list = cron_expr.split()
                func = self._resolve_func(module_name, queue=queue)
                func.__name__ = func_name
                run_every = crontab(*cron_list)

                app.conf.beat_schedule[func_name] = {
                    "task": func_name,
                    "schedule": run_every,
                    "args": (),
                    "kwargs": {},
                    "options": {"queue": queue},
                    "relative": False,
                    "expires": self.default_expires(run_every),
                }

                # 同时将函数注册为 Celery task
                app.task(func, name=func_name, queue=queue)
                registered_count += 1

        logger.info(
            "[cron_registry] registered %d tasks from %d queues",
            registered_count,
            len(self.queue_define),
        )
