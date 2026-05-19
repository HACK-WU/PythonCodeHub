"""
task_base 单元测试

覆盖：
- AutoRetryTask 默认参数与子类覆盖
- 成功路径不重试
- 可重试异常配置生效（autoretry_for、max_retries 被 Celery 应用）
- on_failure 在重试耗尽时输出一条 ERROR 日志
- 不可重试异常（业务异常）直接抛出
- 与 task_timer.install_task_timer 协同时不会重复或漏计时

均通过 Celery("test", broker="memory://") 在内存模式中验证，不依赖真实 broker。
"""

import logging
from types import SimpleNamespace

import pytest
from celery import Celery


@pytest.fixture
def eager_app():
    """构造一个内存 broker 的 Celery app，避免外部依赖"""
    app = Celery("test_task_base", broker="memory://")
    app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        broker_url="memory://",
    )
    return app


class TestAutoRetryTaskDefaults:
    """默认参数与字段表达"""

    def test_default_attributes(self):
        from ab_celery.task_base import AutoRetryTask

        assert AutoRetryTask.max_retries == 3
        assert AutoRetryTask.default_retry_delay == 3
        assert AutoRetryTask.retry_backoff is True
        assert AutoRetryTask.retry_backoff_max == 600
        assert AutoRetryTask.retry_jitter is True
        # 默认仅覆盖通用瞬时异常
        assert ConnectionError in AutoRetryTask.autoretry_for
        assert TimeoutError in AutoRetryTask.autoretry_for
        assert OSError in AutoRetryTask.autoretry_for
        # 不应默认包含 Exception 等过宽类型
        assert Exception not in AutoRetryTask.autoretry_for

    def test_subclass_overrides(self):
        from ab_celery.task_base import AutoRetryTask

        class MyTask(AutoRetryTask):
            max_retries = 7
            default_retry_delay = 30
            autoretry_for = (ValueError,)

        assert MyTask.max_retries == 7
        assert MyTask.default_retry_delay == 30
        assert MyTask.autoretry_for == (ValueError,)


class TestAutoRetryTaskSuccess:
    """任务成功不应触发重试"""

    def test_success_no_retry(self, eager_app):
        from ab_celery.task_base import AutoRetryTask

        call_count = {"n": 0}

        @eager_app.task(base=AutoRetryTask, bind=True)
        def ok_task(self):
            call_count["n"] += 1
            return "ok"

        result = ok_task.apply().get()
        assert result == "ok"
        assert call_count["n"] == 1


class TestAutoRetryTaskConfigApplied:
    """验证基类参数被 Celery 注册到任务上"""

    def test_task_inherits_retry_attributes(self, eager_app):
        from ab_celery.task_base import AutoRetryTask

        @eager_app.task(base=AutoRetryTask, bind=True)
        def t(self):
            pass

        # 注册到 Celery 后，任务应继承 autoretry_for 与重试参数
        assert ConnectionError in t.autoretry_for
        assert t.max_retries == 3
        assert t.retry_backoff is True
        assert t.retry_jitter is True

    def test_task_overrides_in_decorator(self, eager_app):
        from ab_celery.task_base import AutoRetryTask

        @eager_app.task(
            base=AutoRetryTask,
            bind=True,
            max_retries=7,
            autoretry_for=(ValueError,),
        )
        def t(self):
            pass

        assert t.max_retries == 7
        assert t.autoretry_for == (ValueError,)


class TestAutoRetryTaskOnFailure:
    """on_failure 在重试耗尽时输出一条 ERROR 日志"""

    def test_logs_error_only_when_retries_exhausted(self, eager_app, caplog):
        from ab_celery.task_base import AutoRetryTask

        @eager_app.task(base=AutoRetryTask, bind=True, max_retries=2)
        def t(self):
            pass

        einfo = SimpleNamespace(exception=ConnectionError("x"))
        # 模拟「未达上限」：不应打 ERROR
        t.push_request(retries=1)
        try:
            caplog.set_level(logging.ERROR, logger="ab_celery.task_base")
            t.on_failure(ConnectionError("x"), "task-id-1", (), {}, einfo)
        finally:
            t.pop_request()
        not_yet = [r for r in caplog.records if r.name == "ab_celery.task_base" and r.levelno == logging.ERROR]
        assert not_yet == []

        caplog.clear()

        # 模拟「已达上限」：应打 ERROR 一次
        t.push_request(retries=2)
        try:
            t.on_failure(ConnectionError("x"), "task-id-2", (), {}, einfo)
        finally:
            t.pop_request()
        exhausted = [r for r in caplog.records if r.name == "ab_celery.task_base" and r.levelno == logging.ERROR]
        assert len(exhausted) == 1
        assert "任务最终失败" in exhausted[0].getMessage()


class TestAutoRetryTaskNonRetryable:
    """业务异常（不在 autoretry_for 中）应直接抛出，不重试"""

    def test_non_retryable_exception_not_retried(self, eager_app):
        from ab_celery.task_base import AutoRetryTask

        attempts = {"n": 0}

        @eager_app.task(base=AutoRetryTask, bind=True)
        def biz_fail(self):
            attempts["n"] += 1
            raise ValueError("business error")

        with pytest.raises(ValueError):
            biz_fail.apply().get()
        assert attempts["n"] == 1


class TestAutoRetryTaskWithTaskTimer:
    """与 task_timer.install_task_timer 协同：不重复、不漏计时"""

    def test_success_records_once(self, eager_app):
        from ab_celery.task_base import AutoRetryTask
        from ab_celery.task_timer import install_task_timer

        records: list[tuple] = []

        class FakeRecorder:
            def record_time(self, task_name, queue, exception_name, duration):
                records.append((task_name, queue, exception_name, duration))

        install_task_timer(eager_app, recorder=FakeRecorder())

        @eager_app.task(base=AutoRetryTask, bind=True)
        def ok_task(self):
            return 1

        assert ok_task.apply().get() == 1
        assert len(records) == 1
        assert records[0][2] == "None"

    def test_failure_records_once_with_exception_name(self, eager_app):
        from ab_celery.task_base import AutoRetryTask
        from ab_celery.task_timer import install_task_timer

        records: list[tuple] = []

        class FakeRecorder:
            def record_time(self, task_name, queue, exception_name, duration):
                records.append((task_name, queue, exception_name, duration))

        install_task_timer(eager_app, recorder=FakeRecorder())

        @eager_app.task(base=AutoRetryTask, bind=True)
        def boom(self):
            raise ValueError("x")

        with pytest.raises(ValueError):
            boom.apply().get()

        # 业务异常不重试 → 仅一条计时记录
        assert len(records) == 1
        assert records[0][2] == "ValueError"
