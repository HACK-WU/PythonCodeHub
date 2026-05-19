"""
ab_celery — Celery 增强工具集

本模块提供 Celery 项目中常用的增强能力：

- safe_scheduler: 防止手动禁用的周期任务被重新启用的 DatabaseScheduler
- redbeat_sentinel: 修复 celery-redbeat 不支持 Redis Sentinel 的问题
- task_timer: Celery 任务自动计时与 MetricsRecorder 协议
- cron_registry: 配置驱动的 Cron 任务注册框架
- config: Celery 通用配置的结构化表达与标准化构造
- task_base: 通用任务基类（带默认自动重试策略）
- app_factory: Celery 应用工厂 create_celery_app（按设计文档第 9.2 节顺序装配）
- queues: 队列声明轻量工厂 build_queues / build_queue
- routing: 任务路由表生成 RouteRule / build_routes（精确匹配 + 前缀匹配）
- dead_letter: 死信队列声明、显式失败转发与显式重投递辅助
- idempotency: 任务幂等去重后端、显式占用释放与最小装饰器辅助
- throttling: 单 worker `rate_limit` 透传、全局限流后端与三种处理路径辅助
- config_source: 配置源协议、内存实现与一次性加载 CeleryConfig 的辅助
- utils: Celery 4 → 5 兼容性工具（PeriodicTask、periodic_task）

模块使用统一通过完整包路径导入，例如：
    from ab_celery.config import CeleryConfig, build_celery_config
    from ab_celery.config_source import (
        MemoryConfigSource,
        build_celery_config_from_source,
        load_celery_config,
    )
    from ab_celery.task_base import AutoRetryTask
    from ab_celery.app_factory import create_celery_app
    from ab_celery.queues import build_queue, build_queues
    from ab_celery.routing import RouteRule, build_routes
    from ab_celery.dead_letter import (
        DeadLetterBinding,
        DeadLetterRecord,
        build_dead_letter_queues,
        build_dead_letter_routes,
        forward_to_dead_letter,
        redrive_dead_letter,
    )
    from ab_celery.idempotency import (
        IdempotencyConflictError,
        IdempotencyLease,
        MemoryIdempotencyBackend,
        RedisIdempotencyBackend,
        acquire_idempotency,
        idempotent_task,
        release_idempotency,
    )
    from ab_celery.throttling import (
        MemoryThrottleBackend,
        RedisThrottleBackend,
        ThrottleExceededError,
        ThrottleLease,
        acquire_throttle,
        build_rate_limited_task_options,
        throttled_task,
    )
    from ab_celery.task_timer import install_task_timer, task_timer, MetricsRecorder
    from ab_celery.cron_registry import CronRegistry, get_crontab_expires
    from ab_celery.redbeat_sentinel import apply_sentinel_patch
    # safe_scheduler 通常通过 Django settings 字符串引用：
    #   CELERY_BEAT_SCHEDULER = "ab_celery.safe_scheduler.SafeDatabaseScheduler"

顶层不裸导出 config / app_factory / task_base 等通用名称，避免与项目内同名模块混淆
（参见设计文档第 7.4 节）。
"""
