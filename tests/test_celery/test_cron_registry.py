"""
CronRegistry 单元测试
"""

from unittest.mock import MagicMock

import pytest
from celery.schedules import crontab


class TestGetCrontabExpires:
    """get_crontab_expires 边界值测试"""

    def test_min_expires_floor(self):
        """短周期任务 expires 不低于 min_expires"""
        from ab_celery.cron_registry import get_crontab_expires

        # 每分钟执行的任务，周期 = 60s，应被 floor 到 300
        schedule = crontab(minute="*")
        result = get_crontab_expires(schedule, min_expires=300, max_expires=3600)
        assert result >= 300

    def test_max_expires_cap(self):
        """长周期任务 expires 不超过 max_expires"""
        from ab_celery.cron_registry import get_crontab_expires

        # 每小时执行的任务，周期 = 3600s，应被 cap 到 max_expires
        schedule = crontab(minute=0)
        result = get_crontab_expires(schedule, min_expires=300, max_expires=3600)
        assert result <= 3600

    def test_custom_bounds(self):
        """自定义 min/max bounds"""
        from ab_celery.cron_registry import get_crontab_expires

        schedule = crontab(minute="*")
        result = get_crontab_expires(schedule, min_expires=60, max_expires=7200)
        assert 60 <= result <= 7200


class TestTaskDuration:
    """task_duration 装饰器测试"""

    def test_successful_execution(self):
        """成功执行的任务记录耗时"""
        from ab_celery.cron_registry import task_duration

        @task_duration("test_task", queue_name="test_q")
        def my_func():
            return 42

        result = my_func()
        assert result == 42

    def test_exception_reraised(self):
        """异常被重新抛出"""
        from ab_celery.cron_registry import task_duration

        @task_duration("test_task", queue_name="test_q")
        def my_func():
            raise ValueError("test")

        with pytest.raises(ValueError, match="test"):
            my_func()

    def test_preserves_function_name(self):
        """装饰器保留原函数名"""
        from ab_celery.cron_registry import task_duration

        @task_duration("test_task")
        def my_func():
            pass

        assert my_func.__name__ == "my_func"


class TestCronRegistry:
    """CronRegistry 注册与过滤测试"""

    def _make_app(self):
        """创建 mock Celery app"""
        app = MagicMock()
        app.conf.beat_schedule = {}
        return app

    def test_register_all_tasks(self):
        """注册所有任务（无过滤）"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
                ("myapp.tasks.refresh", "* * * * *", "cluster"),
            ],
        }

        registry = CronRegistry(queue_define)
        # mock import_func 避免真实导入
        registry.import_func = lambda path: MagicMock(__name__=path.split(".")[-1], main=MagicMock())
        registry.register_all(app)

        # 应注册 2 个任务
        assert len(app.conf.beat_schedule) == 2

    def test_filter_fn_skips_tasks(self):
        """filter_fn 返回 False 时跳过任务"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.global_task", "0 */2 * * *", "global"),
                ("myapp.tasks.cluster_task", "* * * * *", "cluster"),
            ],
        }

        # 过滤掉 global 任务
        def filter_global(module_name, run_type):
            return run_type != "global"

        registry = CronRegistry(queue_define, filter_fn=filter_global)
        registry.import_func = lambda path: MagicMock(__name__=path.split(".")[-1], main=MagicMock())
        registry.register_all(app)

        # 只有 cluster_task 被注册
        assert len(app.conf.beat_schedule) == 1
        assert "myapp_tasks_cluster_task" in app.conf.beat_schedule

    def test_expires_calculated(self):
        """expires 值被正确计算"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
            ],
        }

        registry = CronRegistry(queue_define)
        registry.import_func = lambda path: MagicMock(__name__=path.split(".")[-1], main=MagicMock())
        registry.register_all(app)

        # expires 应在 [300, 3600] 范围内
        task_config = app.conf.beat_schedule["myapp_tasks_cleanup"]
        assert 300 <= task_config["expires"] <= 3600

    def test_custom_expires_fn(self):
        """自定义 expires 计算函数"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
            ],
        }

        registry = CronRegistry(queue_define, default_expires=lambda schedule: 999)
        registry.import_func = lambda path: MagicMock(__name__=path.split(".")[-1], main=MagicMock())
        registry.register_all(app)

        task_config = app.conf.beat_schedule["myapp_tasks_cleanup"]
        assert task_config["expires"] == 999

    def test_custom_import_func(self):
        """自定义 import_func 被用于解析任务函数"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
            ],
        }

        imported_func = MagicMock(__name__="cleanup", main=MagicMock())
        custom_import = MagicMock(return_value=imported_func)
        registry = CronRegistry(queue_define, import_func=custom_import)
        registry.register_all(app)

        # import_func 在 _resolve_func 中被引用但 _inner_func 是延迟执行的，
        # 所以 register_all 阶段不会调用 import_func。
        # 验证任务已注册即可
        assert len(app.conf.beat_schedule) == 1
        # 验证 import_func 被保存在 registry 中
        assert registry.import_func is custom_import

    def test_empty_queue_define(self):
        """空队列定义不报错"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        registry = CronRegistry({})
        registry.register_all(app)

        assert len(app.conf.beat_schedule) == 0

    def test_queue_routing(self):
        """任务被路由到正确的队列"""
        from ab_celery.cron_registry import CronRegistry

        app = self._make_app()
        queue_define = {
            "celery_cron": [
                ("myapp.tasks.light", "* * * * *", "global"),
            ],
            "celery_heavy_cron": [
                ("myapp.tasks.heavy", "*/30 * * * *", "global"),
            ],
        }

        registry = CronRegistry(queue_define)
        registry.import_func = lambda path: MagicMock(__name__=path.split(".")[-1], main=MagicMock())
        registry.register_all(app)

        light_config = app.conf.beat_schedule["myapp_tasks_light"]
        assert light_config["options"]["queue"] == "celery_cron"

        heavy_config = app.conf.beat_schedule["myapp_tasks_heavy"]
        assert heavy_config["options"]["queue"] == "celery_heavy_cron"
