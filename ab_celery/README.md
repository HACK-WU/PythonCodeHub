# ab_celery — Celery 增强工具集

从 bk-monitor 项目中提炼的 Celery 生产级增强能力，解耦业务依赖后可独立使用。

## 模块一览

| 模块 | 用途 | 依赖 |
|------|------|------|
| `safe_scheduler` | 防止手动禁用的周期任务被重新启用 | django_celery_beat, Django |
| `redbeat_sentinel` | 修复 celery-redbeat 不支持 Redis Sentinel | celery-redbeat, redis |
| `task_timer` | Celery 任务自动计时与 MetricsRecorder 协议 | celery |
| `cron_registry` | 配置驱动的 Cron 任务注册框架 | celery, Django(可选) |

---

## 1. safe_scheduler — 安全的 DatabaseScheduler

**问题**：`django_celery_beat` 的 `DatabaseScheduler` 每次启动会用代码中的 `beat_schedule` 覆盖数据库中 `PeriodicTask` 的 `enabled` 字段，导致管理员手动禁用的任务被重新启用。

**解决**：`SafeModelEntry.from_entry` 在任务已存在时跳过 `enabled` 字段更新。

### 使用方式

```python
# Django settings / Celery config
CELERY_BEAT_SCHEDULER = "ab_celery.safe_scheduler.SafeDatabaseScheduler"
```

无需其他代码改动，替换 scheduler 类名即可。

---

## 2. redbeat_sentinel — RedBeat Sentinel 补丁

**问题**：
1. `celery-redbeat` 的 `get_redis` 不支持 `sentinel_kwargs`，Sentinel 节点需要密码认证时连接失败
2. 云 Redis 的 pipeline 取回数据为 None，导致 `from_key` 抛出 KeyError

**解决**：
1. `sentinel_kwargs_get_redis`：重写 `get_redis`，支持 `sentinel_kwargs`
2. `RedBeatSchedulerEntry.from_key`：用 `hget` 替代 `pipeline`

### 使用方式

```python
# 在 Celery beat 启动前调用（settings.py 或 app 初始化时）
from ab_celery.redbeat_sentinel import apply_sentinel_patch
apply_sentinel_patch()

# Celery 配置（使用 Sentinel 时）
CELERY_REDBEAT_REDIS_URL = "redis-sentinel://redis-sentinel:26379/0"
CELERY_REDBEAT_REDIS_OPTIONS = {
    "sentinels": [("host1", 26379), ("host2", 26379)],
    "password": "your-password",
    "service_name": "mymaster",
    "socket_timeout": 10,
    "retry_period": 60,
    "sentinel_kwargs": {"password": "sentinel-password"},  # Sentinel 节点认证
}
```

> **注意**：仅在 beat 进程中调用，不要在 worker 或 web 进程中调用。

---

## 3. task_timer — 任务自动计时

**问题**：为 Celery 任务添加执行计时是常见需求，手动为每个任务添加计时代码繁琐且易遗漏。

**解决**：
- `install_task_timer`：monkey-patch `app.task`，自动为所有注册任务包裹计时器
- `task_timer`：装饰器，为单个函数添加计时
- `MetricsRecorder`：Protocol 接口，解耦指标后端（Prometheus / StatsD / OpenTelemetry 等）

### 使用方式

#### 3.1 实现 MetricsRecorder

```python
class MyRecorder:
    def record_time(self, task_name, queue, exception_name, duration):
        my_metrics.histogram("task_duration", duration, labels={
            "task": task_name, "queue": queue, "exception": exception_name,
        })
```

#### 3.2 安装自动计时（推荐）

```python
from celery import Celery
from ab_celery.task_timer import install_task_timer

app = Celery("myapp")
install_task_timer(app, recorder=MyRecorder())

# 之后注册的所有任务都会自动计时
@app.task
def my_task():
    ...
```

#### 3.3 单个任务装饰器

```python
from ab_celery.task_timer import task_timer

@task_timer(queue="celery", recorder=MyRecorder())
def my_task():
    ...
```

不传 `recorder` 时默认使用 logging 输出：

```
[task_timer] task=my_task queue=celery exception=None duration=0.123s
```

---

## 4. cron_registry — 配置驱动的 Cron 任务注册

**问题**：大量周期任务硬编码在 `beat_schedule` 中，队列映射散落各处，无法按条件过滤，expires 手动计算易出错。

**解决**：
- 任务声明为 `(module_path, cron_expression, run_type)` 元组
- 按队列分组，不同队列走不同 Worker
- `filter_fn` 回调支持按条件过滤（集群角色、环境变量等）
- `get_crontab_expires` 自动计算 expires（5min~1h）
- `task_duration` 装饰器统一记录执行耗时和异常

### 使用方式

```python
from celery import Celery
from ab_celery.cron_registry import CronRegistry, get_crontab_expires

# 1. 定义队列 -> 任务列表映射
queue_define = {
    "celery_cron": [
        ("myapp.tasks.cleanup", "0 */2 * * *", "global"),
        ("myapp.tasks.refresh_cache", "* * * * *", "cluster"),
    ],
    "celery_heavy_cron": [
        ("myapp.tasks.bulk_process", "*/30 * * * *", "global"),
    ],
}

# 2. 定义过滤函数（可选）
def my_filter(module_name: str, run_type: str) -> bool:
    # 全局任务仅在主节点执行
    if run_type == "global" and not is_primary_node():
        return False
    return True

# 3. 创建注册器并注册所有任务
app = Celery("myapp")
registry = CronRegistry(queue_define, filter_fn=my_filter)
registry.register_all(app)
```

#### 自定义模块导入（非 Django 项目）

```python
# 默认使用 Django 的 import_string，非 Django 项目可替换
def my_import(module_path: str):
    from importlib import import_module
    module_name, func_name = module_path.rsplit(".", 1)
    return getattr(import_module(module_name), func_name)

registry = CronRegistry(queue_define, import_func=my_import)
```

#### 单独使用 get_crontab_expires

```python
from celery.schedules import crontab
from ab_celery.cron_registry import get_crontab_expires

run_every = crontab(minute="*/10")
expires = get_crontab_expires(run_every)  # 约 600
```

---

## 组合使用示例

一个完整的 Celery 项目可以同时使用以上模块：

```python
# settings.py / app.py

from celery import Celery
from ab_celery.task_timer import install_task_timer
from ab_celery.cron_registry import CronRegistry

# 1. RedBeat Sentinel 补丁（beat 进程中）
if "redbeat" in sys.argv[0]:
    from ab_celery.redbeat_sentinel import apply_sentinel_patch
    apply_sentinel_patch()

# 2. 创建 app
app = Celery("myapp")

# 3. 安装任务自动计时
install_task_timer(app, recorder=MyRecorder())

# 4. 注册 Cron 任务
registry = CronRegistry(QUEUE_DEFINE, filter_fn=my_filter)
registry.register_all(app)

# 5. Safe Scheduler（Django + django_celery_beat 项目）
# CELERY_BEAT_SCHEDULER = "ab_celery.safe_scheduler.SafeDatabaseScheduler"
```
