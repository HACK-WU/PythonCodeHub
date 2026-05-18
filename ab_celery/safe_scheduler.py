"""
safe_scheduler — 防止手动禁用的周期任务被重新启用的 DatabaseScheduler

背景：
    django_celery_beat 的 DatabaseScheduler 在每次启动时，会用代码中的 beat_schedule
    覆盖数据库中 PeriodicTask 的 enabled 字段，导致管理员手动禁用的任务被重新启用。
    这是所有使用 django_celery_beat 的项目的共同痛点。

解决方案：
    SafeModelEntry.from_entry 在任务已存在于数据库时，跳过 enabled 字段的更新，
    从而保留管理员的手动禁用操作。其余字段（schedule、args、kwargs 等）正常同步。

用法：
    # Django settings / Celery config
    beat_scheduler = "ab_celery.safe_scheduler.SafeDatabaseScheduler"

依赖：
    - django_celery_beat
    - Django

参考：
    原始实现源自 bk-monitor 的 MonitorDatabaseScheduler。
"""

from django_celery_beat.models import PeriodicTask
from django_celery_beat.schedulers import DatabaseScheduler, ModelEntry


class SafeModelEntry(ModelEntry):
    """
    安全的 ModelEntry：已存在的任务不覆盖 enabled 字段。

    当 PeriodicTask 已存在于数据库时，from_entry 会从 entry 字典中
    移除 enabled 键，避免代码部署时 beat_schedule 中的 enabled=True
    覆盖管理员手动设置的 enabled=False。
    """

    @classmethod
    def from_entry(cls, name, app=None, **entry):
        fields = dict(entry)
        if PeriodicTask.objects.filter(name=name).exists():
            # 已存在的任务：不更新 enabled 属性，保留管理员的手动操作
            fields.pop("enabled", None)
        return super().from_entry(name, app=app, **fields)


class SafeDatabaseScheduler(DatabaseScheduler):
    """
    安全的 DatabaseScheduler：使用 SafeModelEntry 替代默认 ModelEntry。

    用法：
        # Celery 配置
        beat_scheduler = "ab_celery.safe_scheduler.SafeDatabaseScheduler"

    效果：
        - 新任务：正常创建，enabled 取 beat_schedule 中的值
        - 已有任务：更新 schedule/args/kwargs 等，但 **不覆盖** enabled
        - 管理员手动禁用的任务不会被代码部署重新启用
    """

    Entry = SafeModelEntry
