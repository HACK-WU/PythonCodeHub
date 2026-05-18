"""
ab_celery — Celery 增强工具集

本模块提供 Celery 项目中常用的增强能力：

- safe_scheduler: 防止手动禁用的周期任务被重新启用的 DatabaseScheduler
- redbeat_sentinel: 修复 celery-redbeat 不支持 Redis Sentinel 的问题
- task_timer: Celery 任务自动计时与 MetricsRecorder 协议
- cron_registry: 配置驱动的 Cron 任务注册框架
- utils: Celery 4 → 5 兼容性工具（PeriodicTask、periodic_task）
"""
