"""
RedBeat Sentinel 补丁单元测试

注意：celery-redbeat 可能未安装，使用 sys.modules mock 替代。
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _setup_redbeat_mocks():
    """在 sys.modules 中注入 mock 的 redbeat 模块"""
    if "redbeat" not in sys.modules:
        mock_schedulers = MagicMock()
        mock_schedulers.RedBeatSchedulerEntry = type(
            "RedBeatSchedulerEntry",
            (),
            {
                "__init__": lambda self, **kw: None,
                "from_key": classmethod(lambda cls, key, app=None: MagicMock()),
                "decode_definition": classmethod(lambda cls, data: {}),
                "decode_meta": classmethod(lambda cls, data: {}),
            },
        )
        mock_schedulers.RedBeatScheduler = type("RedBeatScheduler", (), {})
        mock_schedulers.ScheduleEntry = type(
            "ScheduleEntry",
            (),
            {
                "__init__": lambda self, **kw: None,
            },
        )
        mock_schedulers.RedBeatJSONEncoder = MagicMock
        mock_schedulers.RetryingConnection = MagicMock
        mock_schedulers.ensure_conf = MagicMock()
        mock_schedulers.get_redis = MagicMock()
        mock_schedulers.json = MagicMock()

        mock_redbeat = MagicMock(schedulers=mock_schedulers)
        sys.modules["redbeat"] = mock_redbeat
        sys.modules["redbeat.schedulers"] = mock_schedulers

    # 清除缓存
    for mod in list(sys.modules.keys()):
        if mod.startswith("ab_celery.redbeat_sentinel"):
            del sys.modules[mod]


_setup_redbeat_mocks()


class TestRedBeatSchedulerEntry:
    """RedBeatSchedulerEntry.from_key 使用 hget 替代 pipeline"""

    def test_from_key_uses_hget_not_pipeline(self):
        """from_key 应使用 hget 而非 pipeline"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import RedBeatSchedulerEntry

        mock_client = MagicMock()
        mock_client.hget.side_effect = [
            b'{"name": "test"}',
            b'{"last_run_at": "2025-01-01", "total_run_count": 5}',
        ]

        with (
            patch("ab_celery.redbeat_sentinel.get_redis", return_value=mock_client),
            patch("ab_celery.redbeat_sentinel.ensure_conf"),
            patch.object(
                RedBeatSchedulerEntry,
                "decode_definition",
                return_value={"name": "test", "task": "my_task", "schedule": MagicMock(), "args": [], "kwargs": {}},
            ),
            patch.object(
                RedBeatSchedulerEntry, "decode_meta", return_value={"last_run_at": MagicMock(), "total_run_count": 5}
            ),
        ):
            try:
                RedBeatSchedulerEntry.from_key("test_key", app=MagicMock())
            except Exception:
                pass

        assert mock_client.hget.call_count == 2
        mock_client.pipeline.assert_not_called()

    def test_from_key_raises_key_error_on_missing_definition(self):
        """definition 不存在时抛出 KeyError"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import RedBeatSchedulerEntry

        mock_client = MagicMock()
        mock_client.hget.return_value = None

        with (
            patch("ab_celery.redbeat_sentinel.get_redis", return_value=mock_client),
            patch("ab_celery.redbeat_sentinel.ensure_conf"),
        ):
            with pytest.raises(KeyError):
                RedBeatSchedulerEntry.from_key("missing_key", app=MagicMock())


class TestSentinelKwargsGetRedis:
    """sentinel_kwargs_get_redis 支持 Sentinel 连接"""

    def test_non_sentinel_url_uses_strict_redis(self):
        """非 Sentinel URL 使用 StrictRedis"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import sentinel_kwargs_get_redis

        app = MagicMock()
        app.redbeat_redis = None
        conf = MagicMock()
        conf.redis_url = "redis://localhost:6379/0"
        conf.app.conf.get.return_value = {}

        with (
            patch("ab_celery.redbeat_sentinel.ensure_conf", return_value=conf),
            patch("ab_celery.redbeat_sentinel.StrictRedis") as mock_strict_redis,
        ):
            sentinel_kwargs_get_redis(app)
            mock_strict_redis.from_url.assert_called_once()

    def test_sentinel_url_creates_sentinel_connection(self):
        """Sentinel URL 创建 Sentinel 连接并传递 sentinel_kwargs"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import sentinel_kwargs_get_redis

        app = MagicMock()
        app.redbeat_redis = None
        conf = MagicMock()
        conf.redis_url = "redis-sentinel://sentinel:26379/0"
        redis_options = {
            "sentinels": [("host1", 26379), ("host2", 26379)],
            "password": "test-password",
            "service_name": "mymaster",
            "socket_timeout": 10,
            "sentinel_kwargs": {"password": "sentinel-pass"},
        }
        conf.app.conf.get.return_value = redis_options

        mock_sentinel_instance = MagicMock()
        mock_sentinel_cls = MagicMock(return_value=mock_sentinel_instance)

        with (
            patch("ab_celery.redbeat_sentinel.ensure_conf", return_value=conf),
            patch.dict("sys.modules", {"redis.sentinel": MagicMock(Sentinel=mock_sentinel_cls)}),
        ):
            sentinel_kwargs_get_redis(app)

            # 验证 Sentinel 被创建且传入了 sentinel_kwargs
            mock_sentinel_cls.assert_called_once()
            call_kwargs = mock_sentinel_cls.call_args[1]
            assert call_kwargs["sentinel_kwargs"] == {"password": "sentinel-pass"}

    def test_cached_connection_reused(self):
        """已有连接时直接返回缓存"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import sentinel_kwargs_get_redis

        cached_conn = MagicMock()
        app = MagicMock()
        app.redbeat_redis = cached_conn

        result = sentinel_kwargs_get_redis(app)
        assert result is cached_conn


class TestApplySentinelPatch:
    """apply_sentinel_patch 测试"""

    def test_patches_applied(self):
        """补丁正确应用"""
        _setup_redbeat_mocks()
        from ab_celery.redbeat_sentinel import (
            RedBeatSchedulerEntry,
            apply_sentinel_patch,
            sentinel_kwargs_get_redis,
        )
        from redbeat import schedulers
        from redbeat.schedulers import RedBeatScheduler

        apply_sentinel_patch()

        assert RedBeatScheduler.Entry is RedBeatSchedulerEntry
        assert schedulers.get_redis is sentinel_kwargs_get_redis
