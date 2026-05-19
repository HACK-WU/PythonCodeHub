"""
config 单元测试

覆盖 CeleryConfig 的字段默认值/覆盖/未知字段拒绝/类型校验，
以及 build_celery_config 的标准化输出，确保产物可被原生 Celery 接受。
"""

import pytest


class TestCeleryConfigDefaults:
    """CeleryConfig 默认值与字段表达"""

    def test_default_instance_creatable(self):
        """不传任何字段即可创建实例"""
        from ab_celery.config import CeleryConfig

        config = CeleryConfig()
        assert config.app_name == "celery"
        assert config.broker_url == "memory://"
        assert config.result_backend is None
        assert config.timezone == "UTC"
        assert config.enable_utc is True
        assert config.task_serializer == "json"
        assert config.accept_content == ["json"]
        assert config.task_default_queue == "celery"
        assert config.worker_prefetch_multiplier == 1

    def test_accept_content_default_not_shared(self):
        """可变默认值不应在多个实例间共享"""
        from ab_celery.config import CeleryConfig

        a = CeleryConfig()
        b = CeleryConfig()
        a.accept_content.append("yaml")
        assert b.accept_content == ["json"]

    def test_explicit_overrides(self):
        """显式覆盖某字段不影响其它字段默认值"""
        from ab_celery.config import CeleryConfig

        config = CeleryConfig(
            app_name="myapp",
            broker_url="redis://localhost:6379/0",
            timezone="Asia/Shanghai",
        )
        assert config.app_name == "myapp"
        assert config.broker_url == "redis://localhost:6379/0"
        assert config.timezone == "Asia/Shanghai"
        # 其它字段保持默认
        assert config.task_serializer == "json"
        assert config.task_default_queue == "celery"


class TestCeleryConfigValidation:
    """CeleryConfig 字段校验"""

    def test_unknown_field_rejected(self):
        """未在数据类中定义的字段必须抛出 TypeError"""
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(unknown_field="x")

    def test_invalid_app_name(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(app_name="")
        with pytest.raises(TypeError):
            CeleryConfig(app_name=123)

    def test_invalid_broker_url(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(broker_url="")
        with pytest.raises(TypeError):
            CeleryConfig(broker_url=None)

    def test_invalid_result_backend_type(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(result_backend=123)

    def test_invalid_accept_content(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(accept_content="json")
        with pytest.raises(TypeError):
            CeleryConfig(accept_content=[1, 2])

    def test_invalid_int_field(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(task_default_max_retries="3")
        # bool 不应被当作 int
        with pytest.raises(TypeError):
            CeleryConfig(worker_prefetch_multiplier=True)

    def test_invalid_optional_int_field(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(task_time_limit="60")

    def test_invalid_queues_routes_type(self):
        from ab_celery.config import CeleryConfig

        with pytest.raises(TypeError):
            CeleryConfig(task_queues={"q": "wrong"})
        with pytest.raises(TypeError):
            CeleryConfig(task_routes=["wrong"])


class TestBuildCeleryConfig:
    """build_celery_config 转换行为"""

    def test_accepts_celery_config(self):
        from ab_celery.config import CeleryConfig, build_celery_config

        config = CeleryConfig(app_name="myapp", broker_url="memory://")
        conf = build_celery_config(config)
        assert isinstance(conf, dict)
        assert conf["broker_url"] == "memory://"
        # 元字段不应出现
        assert "app_name" not in conf

    def test_accepts_dict(self):
        from ab_celery.config import build_celery_config

        conf = build_celery_config({"app_name": "x", "broker_url": "memory://"})
        assert conf["broker_url"] == "memory://"
        assert "app_name" not in conf

    def test_dict_unknown_field_rejected(self):
        from ab_celery.config import build_celery_config

        with pytest.raises(TypeError):
            build_celery_config({"unknown": 1})

    def test_invalid_input_type(self):
        from ab_celery.config import build_celery_config

        with pytest.raises(TypeError):
            build_celery_config(42)
        with pytest.raises(TypeError):
            build_celery_config(None)

    def test_skip_none_optional_fields(self):
        """None 值的可选字段不应出现在产物中，避免覆盖 Celery 自身默认值"""
        from ab_celery.config import CeleryConfig, build_celery_config

        config = CeleryConfig()
        conf = build_celery_config(config)
        assert "result_backend" not in conf
        assert "task_time_limit" not in conf
        assert "task_soft_time_limit" not in conf
        assert "beat_scheduler" not in conf
        assert "task_queues" not in conf
        assert "task_routes" not in conf

    def test_no_result_backend_mode(self):
        """无结果后端配置仍可生成，且不输出 result_backend 键"""
        from ab_celery.config import CeleryConfig, build_celery_config

        conf = build_celery_config(CeleryConfig(result_backend=None))
        assert "result_backend" not in conf

    def test_single_queue_mode(self):
        from ab_celery.config import CeleryConfig, build_celery_config

        conf = build_celery_config(CeleryConfig(task_default_queue="default"))
        assert conf["task_default_queue"] == "default"
        assert "task_queues" not in conf

    def test_multi_queue_with_routes(self):
        from ab_celery.config import CeleryConfig, build_celery_config

        config = CeleryConfig(
            task_queues=[
                {"name": "default"},
                {"name": "heavy"},
            ],
            task_routes={"myapp.tasks.heavy": {"queue": "heavy"}},
        )
        conf = build_celery_config(config)
        assert conf["task_queues"] == [{"name": "default"}, {"name": "heavy"}]
        assert conf["task_routes"] == {"myapp.tasks.heavy": {"queue": "heavy"}}


class TestBuildCeleryConfigCompatWithCelery:
    """产物可被原生 Celery 接受"""

    def test_conf_update_accepts_output(self):
        from celery import Celery

        from ab_celery.config import CeleryConfig, build_celery_config

        app = Celery("test", broker="memory://")
        config = CeleryConfig(
            app_name="test",
            broker_url="memory://",
            task_default_queue="default",
            task_routes={"a.b": {"queue": "default"}},
        )
        # 不抛异常即视为通过
        app.conf.update(build_celery_config(config))
        assert app.conf.task_default_queue == "default"
        assert app.conf.broker_url == "memory://"
