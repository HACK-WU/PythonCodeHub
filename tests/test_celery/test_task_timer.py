"""
task_timer 单元测试
"""

from unittest.mock import MagicMock

import pytest


class TestMetricsRecorder:
    """MetricsRecorder 协议测试"""

    def test_custom_recorder(self):
        """自定义 recorder 实现 MetricsRecorder 协议"""

        class MyRecorder:
            def __init__(self):
                self.records = []

            def record_time(self, task_name, queue, exception_name, duration):
                self.records.append((task_name, queue, exception_name, duration))

        from ab_celery.task_timer import task_timer

        recorder = MyRecorder()

        def my_task():
            return 42

        func = task_timer(queue="test_q", recorder=recorder)(my_task)
        result = func()

        assert result == 42
        assert len(recorder.records) == 1
        assert recorder.records[0][0] == "my_task"
        assert recorder.records[0][1] == "test_q"
        assert recorder.records[0][2] == "None"
        assert recorder.records[0][3] >= 0

    def test_recorder_captures_exception(self):
        """recorder 记录异常信息"""

        class MyRecorder:
            def __init__(self):
                self.records = []

            def record_time(self, task_name, queue, exception_name, duration):
                self.records.append((task_name, queue, exception_name, duration))

        from ab_celery.task_timer import task_timer

        recorder = MyRecorder()

        def failing_func():
            raise ValueError("test error")

        wrapped = task_timer(queue="q", recorder=recorder)(failing_func)
        with pytest.raises(ValueError, match="test error"):
            wrapped()

        assert len(recorder.records) == 1
        assert recorder.records[0][2] == "ValueError"


class TestTaskTimer:
    """task_timer 装饰器测试"""

    def test_default_queue(self):
        """默认队列为 celery"""
        from ab_celery.task_timer import task_timer

        recorder = MagicMock()
        func = task_timer(recorder=recorder)(lambda: None)
        func()
        recorder.record_time.assert_called_once()
        assert recorder.record_time.call_args[1]["queue"] == "celery"

    def test_preserves_function_name(self):
        """装饰器保留原函数名"""
        from ab_celery.task_timer import task_timer

        @task_timer(recorder=MagicMock())
        def my_func():
            pass

        assert my_func.__name__ == "my_func"

    def test_return_value_preserved(self):
        """装饰器保留原函数返回值"""
        from ab_celery.task_timer import task_timer

        @task_timer(recorder=MagicMock())
        def my_func():
            return "hello"

        assert my_func() == "hello"

    def test_exception_reraised(self):
        """异常被重新抛出"""
        from ab_celery.task_timer import task_timer

        @task_timer(recorder=MagicMock())
        def my_func():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            my_func()


class TestInstallTaskTimer:
    """install_task_timer 测试"""

    def test_installs_timer_on_app(self):
        """install_task_timer 应 monkey-patch app.task"""
        from ab_celery.task_timer import install_task_timer

        app = MagicMock()
        original_task = app.task

        recorder = MagicMock()
        install_task_timer(app, recorder=recorder)

        # app._old_task 应保存原始 task 方法
        assert app._old_task is original_task
        # app.task 应被替换
        assert app.task is not original_task

    def test_default_recorder_used_when_none(self):
        """recorder=None 时使用默认 logging recorder"""
        from ab_celery.task_timer import install_task_timer

        app = MagicMock()
        install_task_timer(app, recorder=None)

        # 验证 _old_task 被保存
        assert hasattr(app, "_old_task")
