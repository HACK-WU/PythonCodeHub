"""
ab_celery — Celery 兼容性工具模块

本模块提供从 Celery 4 迁移到 Celery 5 时所需的兼容性代码。

背景：
    Celery 5 移除了 `celery.task.base.PeriodicTask` 类以及 `@periodic_task` 装饰器，
    导致依赖这些 API 的 Celery 4 代码无法直接在 Celery 5 上运行。
    本模块重新实现了上述功能，以兼容旧版代码，避免大规模重构。

迁移建议：
    官方推荐做法是改用 beat_schedule 配置项来声明周期任务，示例：
        app.conf.beat_schedule = {
            'task-name': {
                'task': 'myapp.tasks.my_task',
                'schedule': 30.0,
            },
        }
    新项目应避免使用本模块中的 PeriodicTask 和 periodic_task，
    仅在存量 Celery 4 代码迁移阶段作为过渡方案使用。
"""

from celery import Task
from celery.schedules import maybe_schedule


class PeriodicTask(Task):
    """
    周期任务基类，自动将自身注册到 beat_schedule 配置中。

    兼容说明（Celery 4 → Celery 5）：
        Celery 5 删除了内置的 PeriodicTask 基类。
        本类重新实现了该功能，供从 Celery 4 迁移的存量代码使用。
        新代码请直接使用 app.conf.beat_schedule 进行配置，不建议继续继承本类。

    用法示例（兼容旧式写法）：
        class MyTask(PeriodicTask):
            run_every = timedelta(seconds=30)

            def run(self, *args, **kwargs):
                ...

    属性：
        run_every: 执行间隔，可为 timedelta、crontab 或数字（秒）。
        relative:  是否使用相对调度时间，默认 False。
        options:   传递给 apply_async 的额外参数，默认为空。
        compat:    标记为兼容模式，默认 True。
    """

    abstract = True
    ignore_result = True
    relative = False
    options = None
    compat = True  # 标识该任务使用 Celery 4 兼容模式

    def __init__(self):
        if not hasattr(self, "run_every"):
            raise NotImplementedError("Periodic tasks must have a run_every attribute")
        self.run_every = maybe_schedule(self.run_every, self.relative)
        super().__init__()

    @classmethod
    def on_bound(cls, _app):
        """
        任务绑定到 app 时自动注册到 beat_schedule。

        对应 Celery 4 中 PeriodicTask 绑定 app 时的行为，
        在 Celery 5 中通过 on_bound 钩子实现等效功能。
        """
        _app.conf.beat_schedule[cls.name] = {
            "task": cls.name,
            "schedule": cls.run_every,
            "args": (),
            "kwargs": {},
            "options": cls.options or {},
            "relative": cls.relative,
        }


def periodic_task(*args, **options):
    """
    已废弃的周期任务装饰器，仅用于 Celery 4 存量代码的兼容过渡。

    兼容说明（Celery 4 → Celery 5）：
        Celery 5 已移除 @periodic_task 装饰器。
        本函数保留该接口，以减少迁移改动量。
        新代码请使用 @app.task 配合 beat_schedule 配置替代。

    .. deprecated::
        请改用 beat_schedule 配置项声明周期任务。

    示例（旧式，兼容写法）：
        @periodic_task(run_every=timedelta(seconds=30))
        def my_task():
            ...
    """
    from celery import current_app as app  # 延迟导入，避免循环依赖

    return app.task(**dict({"base": PeriodicTask}, **options))
