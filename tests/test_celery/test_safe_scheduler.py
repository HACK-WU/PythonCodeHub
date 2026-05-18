"""
SafeDatabaseScheduler 单元测试

策略：测试 SafeModelEntry.from_entry 的核心逻辑——
在调用 super().from_entry 之前，enabled 字段是否被正确处理。
通过 patch 父类的 from_entry 来捕获实际传入的参数。
"""

import sys
from unittest.mock import MagicMock, patch


def _setup_mocks():
    """确保 django_celery_beat mock 已注入"""
    if "django_celery_beat" not in sys.modules:
        mock_models = MagicMock()
        mock_schedulers = MagicMock()
        mock_schedulers.DatabaseScheduler = type("DatabaseScheduler", (), {})
        mock_schedulers.ModelEntry = type(
            "ModelEntry", (), {"from_entry": classmethod(lambda cls, *a, **kw: MagicMock())}
        )
        sys.modules["django_celery_beat"] = MagicMock(models=mock_models, schedulers=mock_schedulers)
        sys.modules["django_celery_beat.models"] = mock_models
        sys.modules["django_celery_beat.schedulers"] = mock_schedulers

    # 清除缓存
    for mod in list(sys.modules.keys()):
        if mod.startswith("ab_celery.safe_scheduler"):
            del sys.modules[mod]


_setup_mocks()


class TestSafeModelEntryLogic:
    """
    测试 SafeModelEntry.from_entry 的核心逻辑：
    已存在的任务不覆盖 enabled 字段。
    """

    def test_existing_task_pops_enabled(self):
        """已存在任务：from_entry 在调用 super 前移除 enabled"""
        _setup_mocks()
        from ab_celery.safe_scheduler import SafeModelEntry

        with patch("ab_celery.safe_scheduler.PeriodicTask") as mock_pt:
            mock_pt.objects.filter.return_value.exists.return_value = True

            # patch 父类的 from_entry 来捕获实际传入的参数
            parent_cls = SafeModelEntry.__bases__[0]
            with patch.object(parent_cls, "from_entry", return_value=MagicMock()) as mock_super:
                SafeModelEntry.from_entry("my_task", app=MagicMock(), enabled=True, schedule="*/5 * * * *")

                call_kwargs = mock_super.call_args[1]
                assert "enabled" not in call_kwargs, f"enabled should be removed, got keys: {list(call_kwargs.keys())}"

    def test_new_task_keeps_enabled(self):
        """新任务：from_entry 保留 enabled 字段"""
        _setup_mocks()
        from ab_celery.safe_scheduler import SafeModelEntry

        with patch("ab_celery.safe_scheduler.PeriodicTask") as mock_pt:
            mock_pt.objects.filter.return_value.exists.return_value = False

            parent_cls = SafeModelEntry.__bases__[0]
            with patch.object(parent_cls, "from_entry", return_value=MagicMock()) as mock_super:
                SafeModelEntry.from_entry("my_task", app=MagicMock(), enabled=True, schedule="*/5 * * * *")

                call_kwargs = mock_super.call_args[1]
                assert "enabled" in call_kwargs, "enabled should be preserved for new task"
                assert call_kwargs["enabled"] is True

    def test_existing_task_no_enabled_key_no_error(self):
        """已存在任务且 entry 中无 enabled 键：pop 不报错"""
        _setup_mocks()
        from ab_celery.safe_scheduler import SafeModelEntry

        with patch("ab_celery.safe_scheduler.PeriodicTask") as mock_pt:
            mock_pt.objects.filter.return_value.exists.return_value = True

            parent_cls = SafeModelEntry.__bases__[0]
            with patch.object(parent_cls, "from_entry", return_value=MagicMock()) as mock_super:
                SafeModelEntry.from_entry("my_task", app=MagicMock(), schedule="*/5 * * * *")
                mock_super.assert_called_once()

    def test_existing_task_enabled_false_not_overwritten(self):
        """已存在任务：数据库中 enabled=False 不被代码中 enabled=True 覆盖"""
        _setup_mocks()
        from ab_celery.safe_scheduler import SafeModelEntry

        with patch("ab_celery.safe_scheduler.PeriodicTask") as mock_pt:
            mock_pt.objects.filter.return_value.exists.return_value = True

            parent_cls = SafeModelEntry.__bases__[0]
            with patch.object(parent_cls, "from_entry", return_value=MagicMock()) as mock_super:
                SafeModelEntry.from_entry("disabled_task", app=MagicMock(), enabled=True, schedule="* * * * *")

                call_kwargs = mock_super.call_args[1]
                assert "enabled" not in call_kwargs


class TestSafeDatabaseScheduler:
    """SafeDatabaseScheduler 使用 SafeModelEntry"""

    def test_entry_class(self):
        _setup_mocks()
        from ab_celery.safe_scheduler import SafeDatabaseScheduler, SafeModelEntry

        assert SafeDatabaseScheduler.Entry is SafeModelEntry
