"""
redbeat_sentinel — 修复 celery-redbeat 不支持 Redis Sentinel 的问题

背景：
    celery-redbeat 原生的 get_redis 函数不支持 sentinel_kwargs 参数，
    导致使用 Redis Sentinel 的生产环境无法正确连接。此外，云 Redis 的
    pipeline 在取回数据时存在 bug，from_key 方法需要改用普通 hget 替代
    pipeline 以确保数据能正确返回。

解决方案：
    1. RedBeatSchedulerEntry.from_key：用 hget 替代 pipeline，修复云 Redis
       pipeline 无法取回数据的问题
    2. sentinel_kwargs_get_redis：重写 get_redis，支持 sentinel_kwargs，
       使 RedBeat 能正确连接 Redis Sentinel 集群
    3. apply_sentinel_patch()：显式调用入口，替换 redbeat.schedulers.get_redis
       并注入自定义 Entry

用法：
    # 在 Celery beat 启动前调用（通常在 settings.py 或 app 初始化时）
    from ab_celery.redbeat_sentinel import apply_sentinel_patch
    apply_sentinel_patch()

    # Celery 配置（使用 Sentinel 时）
    redbeat_redis_url = "redis-sentinel://redis-sentinel:26379/0"
    redbeat_redis_options = {
        "sentinels": [("host1", 26379), ("host2", 26379)],
        "password": "your-password",
        "service_name": "mymaster",
        "socket_timeout": 10,
        "retry_period": 60,
        "sentinel_kwargs": {"password": "sentinel-password"},  # Sentinel 节点认证
    }

依赖：
    - celery-redbeat
    - redis

参考：
    原始实现源自 bk-monitor 的 patches/redbeat/schedulers.py。
"""

from celery.app import app_or_default
from celery.utils.log import get_logger
from redbeat import schedulers
from redbeat.schedulers import (
    RedBeatJSONEncoder,
    RedBeatScheduler,
    RedBeatSchedulerEntry as _RedBeatSchedulerEntry,
    RetryingConnection,
    ScheduleEntry,
    ensure_conf,
    get_redis,
    json,
)
from redis.client import StrictRedis


class RedBeatSchedulerEntry(_RedBeatSchedulerEntry):
    """
    修复版 RedBeatSchedulerEntry：

    1. from_key 使用 hget 替代 pipeline，解决云 Redis pipeline 无法取回数据的问题
    2. _next_instance 保留 pipeline 写入（写入方向无此 bug）
    """

    def __init__(self, name=None, task=None, schedule=None, args=None, kwargs=None, enabled=True, **clsargs):
        ScheduleEntry.__init__(self, name=name, task=task, schedule=schedule, args=args, kwargs=kwargs, **clsargs)
        self.enabled = enabled
        ensure_conf(self.app)

    @classmethod
    def from_key(cls, key, app=None):
        """
        从 Redis 读取任务定义，使用 hget 替代 pipeline。

        原版使用 pipeline 批量读取 definition 和 meta，但部分云 Redis
        实现的 pipeline 取回数据为 None，导致 KeyError。改用两次独立
        hget 调用可规避此问题。
        """
        ensure_conf(app)
        client = get_redis(app)
        # 使用 hget 替代 pipeline，解决云 Redis pipeline 未能取回数据的问题
        definition = client.hget(key, "definition")
        meta = client.hget(key, "meta")

        if not definition:
            raise KeyError(key)

        definition = cls.decode_definition(definition)
        meta = cls.decode_meta(meta)
        definition.update(meta)

        entry = cls(app=app, **definition)
        # celery.ScheduleEntry sets last_run_at = utcnow(), which is confusing and wrong
        entry.last_run_at = meta["last_run_at"]

        return entry

    def _next_instance(self, last_run_at=None, only_update_last_run_at=False):
        entry = ScheduleEntry._next_instance(self, last_run_at=last_run_at)

        if only_update_last_run_at:
            # rollback the update to total_run_count
            entry.total_run_count = self.total_run_count

        meta = {
            "last_run_at": entry.last_run_at,
            "total_run_count": entry.total_run_count,
        }

        with get_redis(self.app).pipeline() as pipe:
            pipe.hset(self.key, "meta", json.dumps(meta, cls=RedBeatJSONEncoder))
            pipe.zadd(self.app.redbeat_conf.schedule_key, {entry.key: entry.score})
            pipe.execute()

        return entry

    __next__ = next = _next_instance


def sentinel_kwargs_get_redis(app=None):
    """
    支持 sentinel_kwargs 的 get_redis 替换实现。

    原版 get_redis 不支持 sentinel_kwargs，导致 Sentinel 节点需要密码认证时
    连接失败。本函数在检测到 redis-sentinel URL 且配置中包含 sentinels 时，
    使用 redis.sentinel.Sentinel 创建连接，并正确传递 sentinel_kwargs。

    Args:
        app: Celery 应用实例，为 None 时使用默认 app。

    Returns:
        Redis 连接实例（或 RetryingConnection 包装）。
    """
    app = app_or_default(app)
    conf = ensure_conf(app)
    if not hasattr(app, "redbeat_redis") or app.redbeat_redis is None:
        redis_options = conf.app.conf.get("REDBEAT_REDIS_OPTIONS", conf.app.conf.get("BROKER_TRANSPORT_OPTIONS", {}))
        retry_period = redis_options.get("retry_period")
        if conf.redis_url.startswith("redis-sentinel") and "sentinels" in redis_options:
            from redis.sentinel import Sentinel

            sentinel = Sentinel(
                redis_options["sentinels"],
                socket_timeout=redis_options.get("socket_timeout"),
                password=redis_options.get("password"),
                decode_responses=True,
                sentinel_kwargs=redis_options.get("sentinel_kwargs", None),
            )
            connection = sentinel.master_for(redis_options.get("service_name", "master"))
        else:
            connection = StrictRedis.from_url(conf.redis_url, decode_responses=True)

        if retry_period is None:
            app.redbeat_redis = connection
        else:
            app.redbeat_redis = RetryingConnection(retry_period, connection)

    return app.redbeat_redis


def apply_sentinel_patch():
    """
    应用 RedBeat Sentinel 补丁。

    执行以下操作：
    1. 替换 RedBeatScheduler.Entry 为修复版 RedBeatSchedulerEntry
    2. 替换 redbeat.schedulers.get_redis 为支持 sentinel_kwargs 的版本
    3. 替换 redbeat.schedulers.logger 为 celery.beat logger

    调用时机：在 Celery beat 启动前调用（通常在 settings.py 或 app 初始化时）。
    注意：此函数应仅在 beat 进程启动时调用，不要在 worker 或 web 进程中调用。

    用法：
        # settings.py 或 app 初始化
        if "redbeat.RedBeatScheduler" in sys.argv:
            from ab_celery.redbeat_sentinel import apply_sentinel_patch
            apply_sentinel_patch()
    """
    RedBeatScheduler.Entry = RedBeatSchedulerEntry
    schedulers.get_redis = sentinel_kwargs_get_redis
    schedulers.logger = get_logger("celery.beat")
