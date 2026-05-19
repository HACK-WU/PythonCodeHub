# ab_celery — Celery 增强工具集

从 bk-monitor 项目中提炼的 Celery 生产级增强能力，解耦业务依赖后可独立使用。

## 模块一览

| 模块 | 用途 | 依赖 |
|------|------|------|
| `safe_scheduler` | 防止手动禁用的周期任务被重新启用 | django_celery_beat, Django |
| `redbeat_sentinel` | 修复 celery-redbeat 不支持 Redis Sentinel | celery-redbeat, redis |
| `task_timer` | Celery 任务自动计时与 MetricsRecorder 协议 | celery |
| `cron_registry` | 配置驱动的 Cron 任务注册框架 | celery, Django(可选) |
| `config` | Celery 通用配置的结构化表达与标准化构造 | celery |
| `task_base` | 通用任务基类（默认自动重试策略） | celery |
| `app_factory` | Celery 应用工厂 `create_celery_app`（统一初始化流程） | celery；可选：celery-redbeat / redis |
| `queues` | 队列声明轻量工厂 `build_queues` / `build_queue` | celery (kombu) |
| `routing` | 任务路由表生成 `RouteRule` / `build_routes` | celery |

## 模块关系图

```mermaid
flowchart LR
    A[CeleryConfig / build_celery_config] --> B[create_celery_app]
    B --> C[Celery app 实例]
    B -. 可选 .-> D[task_timer.install_task_timer]
    B -. 可选 .-> E[cron_registry.CronRegistry]
    B -. 可选 .-> F[redbeat_sentinel.apply_sentinel_patch]
    G[AutoRetryTask] --> C
    H[safe_scheduler.SafeDatabaseScheduler] -. 通过配置 .-> A
    I[queues.build_queues] -. 输入 .-> A
    J[routing.build_routes] -. 输入 .-> A
```

> 图示与设计文档第 16 章保持一致；`queues` / `routing` 作为 Batch 4 的可选输入源补充进入。

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

## 5. config — 通用配置层

**问题**：每个项目接入 Celery 都要重复书写一组样板配置项（broker、序列化、超时、队列、路由等），散落在多个文件，容易遗漏或误配置。

**解决**：
- `CeleryConfig`：以 dataclass 表达的结构化配置对象，按「基础层 / 任务与 worker 行为层 / 调度与路由层」三层组织字段；未知字段直接抛出 `TypeError`
- `build_celery_config`：把 `CeleryConfig` 或 `dict` 转为可直接喂给 `Celery.conf.update` 的扁平字典

本模块**不读取环境变量、不加载 `.env`、不引入第三方依赖**。配置来源由调用方自行决定后再传入。

### 使用方式

```python
from celery import Celery
from ab_celery.config import CeleryConfig, build_celery_config

config = CeleryConfig(
    app_name="myapp",
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/1",
    timezone="Asia/Shanghai",
    task_default_queue="default",
    task_routes={
        "myapp.tasks.heavy": {"queue": "heavy"},
    },
)

app = Celery(config.app_name)
app.conf.update(build_celery_config(config))
```

也可以直接传 `dict`（同样会被字段校验）：

```python
from ab_celery.config import build_celery_config

app.conf.update(build_celery_config({
    "app_name": "myapp",
    "broker_url": "redis://localhost:6379/0",
}))
```

> 字段命名严格采用 Celery >= 5.3 原生小写蛇形命名（`broker_url`、`task_default_queue`、`worker_prefetch_multiplier` 等）。

---

## 6. task_base — 通用任务基类

**问题**：项目里每个任务都重复声明 `autoretry_for`、`max_retries`、退避参数，重试策略不一致，失败日志风格也不统一。

**解决**：`AutoRetryTask` 提供一套保守的默认行为：

- 默认仅对通用瞬时异常重试：`ConnectionError`、`TimeoutError`、`OSError`
- `max_retries=3`、`default_retry_delay=3`
- 启用指数退避（`retry_backoff=True`，`retry_backoff_max=600`）+ 抖动（`retry_jitter=True`）
- `on_failure` 在「重试耗尽」时输出一条 `ERROR` 级日志（logger 名：`ab_celery.task_base`）

### 使用方式

```python
from ab_celery.task_base import AutoRetryTask

@app.task(base=AutoRetryTask, bind=True)
def fetch_remote(self, url):
    ...
```

子类化以定制策略：

```python
from ab_celery.task_base import AutoRetryTask

class HttpTask(AutoRetryTask):
    autoretry_for = (ConnectionError, TimeoutError)
    max_retries = 5
    default_retry_delay = 10
```

> ⚠️ **重要警示**：自动重试的前提是任务**幂等或可接受重复执行**。非幂等任务请显式覆盖 `autoretry_for` 或不要使用本基类，避免造成数据重复写入等副作用。

本模块不导入 `task_timer` / `redis` / `django` / `redbeat`，与 `task_timer.install_task_timer` 协同时不会产生重复计时。

---

## 7. app_factory — 应用工厂

**问题**：项目接入 Celery 时会重复拼装「补丁 → 创建 app → 加载配置 → 安装计时 → 任务发现 → 注册周期任务」这条顺序敏感的初始化流程，易错位、易遗漏。

**解决**：`create_celery_app` 提供一个统一入口，按设计文档第 9.2 节顺序严格执行：

1. （需要时）应用 RedBeat Sentinel 补丁（**顺序敏感**：必须先于 Celery app 创建）
2. 创建 Celery app
3. 加载标准化配置（`build_celery_config`）
4. （需要时）安装 `task_timer`（**顺序敏感**：必须先于任务注册）
5. 处理 `task_modules` / `task_packages`
6. （需要时）调用 `CronRegistry.register_all`
7. 返回 app

### 使用方式

```python
from ab_celery.app_factory import create_celery_app
from ab_celery.config import CeleryConfig
from ab_celery.task_base import AutoRetryTask

app = create_celery_app(
    config=CeleryConfig(
        app_name="myapp",
        broker_url="redis://localhost:6379/0",
        result_backend="redis://localhost:6379/1",
        timezone="Asia/Shanghai",
    ),
    task_packages=["myapp"],          # 触发 autodiscover_tasks
    default_task_base=AutoRetryTask,  # 可选：作为默认任务基类
    enable_task_timer=True,           # 可选：启用任务计时
    task_timer_recorder=my_recorder,  # 需配合 enable_task_timer=True
)
```

### 设计要点

- **默认不启用任何具环境依赖的副作用**：RedBeat Sentinel 补丁与 `task_timer` 均需显式开启
- **缺少可选依赖时不静默**：如启用 `apply_redbeat_sentinel_patch=True` 但未安装 `celery-redbeat` / `redis`，会招出带提示的 `ModuleNotFoundError`
- **不重复实现现有能力**：计时仍由 `task_timer` 负责，周期任务仍由 `cron_registry` 负责，调度器安全语义仍由 `safe_scheduler` 负责，补丁仍由 `redbeat_sentinel` 负责

---

## 8. queues — 队列声明工厂

**问题**：多队列项目中反复手写 `kombu.Queue(...)`，容易拼写错、选项不一致。

**解决**：
- `build_queue`：轻量包装 `kombu.Queue`，仅做名称校验
- `build_queues`：接受「字符串列表」或「(名称, 选项 dict) 元组列表」，返回 `list[Queue]`，可直接赋给 `CeleryConfig.task_queues`
- 重复名称会报 `ValueError`，避免静默覆盖

### 使用方式

```python
from ab_celery.config import CeleryConfig
from ab_celery.queues import build_queues

queues = build_queues([
    "default",
    ("heavy", {"routing_key": "heavy.#"}),
    "cron",
])

config = CeleryConfig(
    app_name="myapp",
    broker_url="redis://localhost:6379/0",
    task_queues=queues,
)
```

> 本模块不预设任何项目命名约定。需要交换机、routing_key 等完整语义请直接使用 `(name, options)` 元组形式透传给 `kombu.Queue`。

---

## 9. routing — 任务路由表生成

**问题**：`task_routes` 在多队列项目中容易变成一堆压在一起的原生 dict，精确/前缀规则缺乏优先级与去重保护。

**解决**：`RouteRule` + `build_routes`，仅覆盖两类最常见场景：
- **精确匹配**：完整任务名 → 队列
- **前缀匹配**：任务名前缀 → 队列，输出为 Celery 原生的 `"<prefix>*"` glob 形式

输出顺序：精确匹配在前，前缀匹配按「最长前缀」降序，避免短前缀抢先命中。

### 使用方式

```python
from ab_celery.config import CeleryConfig
from ab_celery.routing import RouteRule, build_routes

routes = build_routes([
    RouteRule(queue="mail", match="myapp.tasks.send_mail"),
    RouteRule(queue="heavy", prefix="myapp.heavy."),
    RouteRule(
        queue="cron",
        prefix="myapp.cron.",
        options={"routing_key": "cron.#"},
    ),
])

config = CeleryConfig(
    app_name="myapp",
    broker_url="redis://localhost:6379/0",
    task_routes=routes,
)
```

### 不覆盖的场景

- **正则匹配 / 通配符**：请直接写原生 `task_routes`。本模块不在公共层引入这些易误用能力。
- **动态路由函数（`Router` 实例）**：超出“声明式”范畴，不为其提供抽象。

---

## 10. orchestration — 任务编排封装

对 Celery Canvas 的三种声明式编排原语 `chain` / `group` / `chord` 提供薄封装：

- **可读命名**：通过 `name=` 参数为编排单元附加可读标识，便于日志与排障
- **统一异常**：成员为空 / 非 `Signature` / `body` 类型错误时给出清晰报错
- **失败传播策略与 Celery 默认完全一致**：不做任何隐式覆盖
- **完全可降级**：返回对象就是原生 Canvas 类型，可直接传给任何接受原生 `Signature` 的 API

### 使用方式

```python
from ab_celery.orchestration import (
    build_chain, build_group, build_chord, log_orchestration_apply,
)

# chain：串行
flow = build_chain(fetch.s(url), parse.s(), save.s(), name="ingest")
ar = flow.apply_async()
log_orchestration_apply(flow, ar)  # INFO: kind=chain name=ingest members=3 root_id=...

# group：并行
batch = build_group(*[fetch.s(u) for u in urls], name="batch-fetch")
batch.apply_async()

# chord：并行 + 汇聚
agg = build_chord(
    [score.s(item) for item in items],
    summarize.s(),
    name="score-and-summarize",
)
agg.apply_async()
```

### 与 `AutoRetryTask` 协同

封装层**不**叠加任何重试逻辑，成员任务的重试策略完全由 `AutoRetryTask`（或显式 `Signature.set(retry=...)`）决定：

- `chain` / `group` / `chord` 中的 `AutoRetryTask` 成员：自动重试照常生效，不会被编排层放大或抑制
- `chord` 的 `header` 中存在重试中的 `AutoRetryTask`：不会被误判为失败，`body` 仍按原生 chord 语义在 header 全部成功后触发

### 失败传播

完全沿用 Celery 原生 Canvas 默认行为：

- **chain**：节点失败 → 终止后续节点 → 异常向 `AsyncResult` 传播
- **group**：部分成员失败不影响其他成员，整体结果反映各成员状态
- **chord**：`header` 任一失败 → `body` 不被触发

如需自定义错误处理，使用 Celery 原生 `link_error` / `Signature.set(...)`，封装层不提供独立捷径。

### 降级到原生 Canvas

封装层未覆盖的能力（`starmap` / `chunks` / `map`、动态运行时编排、复杂错误链等），**直接使用原生 API**：

```python
from celery import chain, group, chord  # 原生 API
```

`build_*` 的返回对象与原生 Canvas 类型完全互通，混用不需要任何转换。

### 不覆盖的场景

- **动态运行时编排**：仅支持声明式编排，不替代 `chain.apply_async(args=...)` 等动态拼装
- **失败传播策略覆盖**：不提供编排级开关，需通过 `link_error` 等原生方式表达
- **编排级独立重试**：仅暴露 `Signature.set(retry=...)` 等原生机制，不提供独立参数

---

## 11. dead_letter — 死信队列管理

**问题**：任务失败后若仅依赖 worker 日志排查，容易丢失上下文；而不同 broker 的死信能力差异又较大，调用方往往需要重复声明 DLQ 队列、转发格式和重投递入口。

**解决**：`DeadLetterBinding` + `DeadLetterRecord` + 三类最小辅助函数：

- `build_dead_letter_queues`：按声明批量构造业务队列与 DLQ 队列
- `build_dead_letter_routes`：为显式死信转发场景生成 `task_routes`
- `forward_to_dead_letter` / `redrive_dead_letter`：显式转发与显式重投递

### 使用方式

```python
from ab_celery.config import CeleryConfig
from ab_celery.dead_letter import (
    DeadLetterBinding,
    DeadLetterRecord,
    build_dead_letter_queues,
    build_dead_letter_routes,
    forward_to_dead_letter,
    redrive_dead_letter,
)

bindings = [
    DeadLetterBinding(
        source_queue="mail",
        dead_letter_queue="mail.dlq",
        match="myapp.tasks.send_mail",
    ),
    DeadLetterBinding(
        source_queue="heavy",
        dead_letter_queue="heavy.dlq",
        prefix="myapp.heavy.",
    ),
]

config = CeleryConfig(
    app_name="myapp",
    broker_url="amqp://guest:guest@localhost:5672//",
    task_queues=build_dead_letter_queues(bindings, broker_kind="rabbitmq"),
    task_routes=build_dead_letter_routes(bindings),
)

record = DeadLetterRecord(
    task_name="myapp.tasks.send_mail",
    queue="mail",
    payload={"user_id": 1, "force": True},
    reason="retry-exhausted",
    task_id="task-1",
)

forward_to_dead_letter(dead_letter_task, record, dead_letter_queue="mail.dlq")
redrive_dead_letter(send_mail, record)  # 显式回投到原队列
```

### broker 差异

- **RabbitMQ**：源队列自动补齐原生 `x-dead-letter-exchange` / `x-dead-letter-routing-key` 参数，DLQ 绑定到独立 `direct` exchange
- **Redis**：不支持原生 DLX，因此仅声明普通队列；失败任务需要调用方显式执行 `forward_to_dead_letter`

### 设计边界

- **不内置死信判定策略**：什么异常算死信，由调用方自行决定
- **不提供隐式自动重投**：所有重投递都必须显式调用 `redrive_dead_letter`
- **不统一 broker 语义**：仅抽象共同的声明/转发入口，保留 RabbitMQ 与 Redis 的差异
- **不负责持久化治理**：死信保存时长、归档、清理策略属于调用方或监控系统职责

### 推荐接入方式

- **RabbitMQ 项目**：优先使用 `build_dead_letter_queues(..., broker_kind="rabbitmq")`，把原生 DLX 声明固化到 `task_queues`
- **Redis 项目**：把 `dead_letter` 当作显式失败转发工具，而非原生 DLQ 抽象
- **重投递操作**：始终通过显式后台任务或运维脚本触发，不要在 worker 内自动重投，避免故障放大

---

## 12. idempotency — 任务幂等去重

**问题**：任务被重复入队时，业务方往往只能在任务函数里手写去重逻辑；而自动重试、人工补投、broker 抖动又会让“重复”和“合法重试”混在一起，容易误拦或漏拦。

**解决**：`idempotency` 模块只解决“同一个幂等键当前是否允许执行”这一最小问题：

- `MemoryIdempotencyBackend`：单进程 / 单测场景
- `RedisIdempotencyBackend`：生产场景，可选依赖 `redis`
- `acquire_idempotency` / `release_idempotency`：显式占用与释放
- `idempotent_task`：为普通函数添加最小幂等包装

### 使用方式

```python
from ab_celery.idempotency import (
    MemoryIdempotencyBackend,
    acquire_idempotency,
    idempotent_task,
)

backend = MemoryIdempotencyBackend()

@idempotent_task(
    backend=backend,
    key_getter=lambda payload, task_id: payload["order_id"],
    owner_getter=lambda payload, task_id: task_id,
    ttl_seconds=60,
)
def submit_order(payload, task_id):
    return payload["order_id"]

result = submit_order({"order_id": "order-1"}, "task-1")

lease = acquire_idempotency(
    backend,
    key="invoice-1",
    owner="task-2",
    ttl_seconds=120,
)
```

### 核心语义

- **幂等键完全由调用方提供**：公共层不做参数 hash，也不猜测业务唯一键
- **同一 owner 视为重入**：同一个 `key + owner` 的再次获取会返回 `reentrant=True`，用于表达合法重试
- **不同 owner 才算冲突**：只有 `key` 相同但 `owner` 不同时，才抛出 `IdempotencyConflictError`
- **TTL 由调用方决定**：公共层不内置默认窗口，避免误导不同业务场景

### 与 `AutoRetryTask` 的协同

推荐把 Celery 的 `task_id` 作为 `owner`。这样同一个任务在自动重试时会沿用相同 owner，从而满足“**重试不视为重复**”的验收要求。

```python
from ab_celery.idempotency import MemoryIdempotencyBackend, acquire_idempotency
from ab_celery.task_base import AutoRetryTask

backend = MemoryIdempotencyBackend()

@app.task(base=AutoRetryTask, bind=True)
def sync_order(self, order_id):
    acquire_idempotency(
        backend,
        key=order_id,
        owner=self.request.id,
        ttl_seconds=300,
    )
    ...
```

### 后端说明

- **MemoryIdempotencyBackend**：仅用于单进程测试或极简场景，不适用于多 worker 生产部署
- **RedisIdempotencyBackend**：需要调用方自行安装 `redis`；未安装时会抛出明确异常，不做静默退化

### 设计边界

- **不缓存任务结果**：本模块只负责“能否执行”，不负责返回历史执行结果
- **不内置业务唯一键策略**：订单号、消息 ID 等唯一键由业务层提供
- **不自动释放成功任务**：默认保留 TTL 窗口；是否提前释放由调用方显式决定
- **不替代业务级幂等**：数据库约束、状态机校验等仍应在业务层兜底

### 推荐接入方式

- **测试或单进程场景**：使用 `MemoryIdempotencyBackend`
- **多 worker 生产场景**：使用 `RedisIdempotencyBackend`，并显式安装 `redis`
- **Celery 任务场景**：优先使用 `self.request.id` 作为 `owner`
- **TTL 配置**：按业务窗口设置，不要在公共层追求“一刀切”的默认值

---

## 13. throttling — 任务限流

**问题**：Celery 原生 `rate_limit` 只能解决单 worker 维度的限流；一旦任务分散到多个 worker，调用方通常会在业务代码里手写 Redis 计数或 sleep 逻辑，既分散又难统一约束“限流后到底是拒绝、延迟还是排队”。

**解决**：`throttling` 模块把限流拆成两层：

- `build_rate_limited_task_options`：只负责透传 Celery 原生 `rate_limit`
- `ThrottleBackend`：定义全局限流后端协议
- `MemoryThrottleBackend`：单进程 / 单测场景
- `RedisThrottleBackend`：生产场景，可选依赖 `redis`
- `acquire_throttle`：显式限流检查
- `throttled_task`：为普通函数添加最小限流包装

### 使用方式

```python
from ab_celery.throttling import (
    MemoryThrottleBackend,
    acquire_throttle,
    build_rate_limited_task_options,
    throttled_task,
)

backend = MemoryThrottleBackend()

@throttled_task(
    backend=backend,
    bucket_getter=lambda payload: payload["bucket"],
    limit=10,
    window_seconds=60,
    on_throttled="reject",
)
def sync_remote(payload):
    return payload["bucket"]

lease = acquire_throttle(
    backend,
    bucket="report:daily",
    limit=1,
    window_seconds=60,
)

task_options = build_rate_limited_task_options(rate_limit="20/m", bind=True)
```

### 核心语义

- **单 worker 限流只做透传**：`build_rate_limited_task_options` 只负责把 `rate_limit` 放进任务选项，不引入额外语义
- **全局限流通过后端实现**：公共层不固定令牌桶、漏桶或滑动窗口算法，只提供最小默认后端
- **处理路径必须显式选择**：触发限流后只能走 `reject`、`delay`、`queue` 三种显式路径之一
- **bucket 完全由调用方提供**：公共层不猜测用户维度、租户维度或业务分组策略

### 三种处理路径

- **`reject`**：直接抛出 `ThrottleExceededError`，适合调用方显式感知失败
- **`delay`**：按 `retry_after_seconds` 调用休眠函数后再执行，适合极简脚本或同步场景
- **`queue`**：交给调用方提供的 `queue_handler`，适合显式重新入队、投递延迟任务或记录待处理状态

### 与 `AutoRetryTask` 的协同

单 worker 场景推荐直接复用 Celery 原生 `rate_limit`，不要重复发明第二套单机限流语义。

```python
from ab_celery.task_base import AutoRetryTask
from ab_celery.throttling import build_rate_limited_task_options

@app.task(
    base=AutoRetryTask,
    bind=True,
    **build_rate_limited_task_options(rate_limit="5/m"),
)
def sync_inventory(self):
    ...
```

### 后端说明

- **MemoryThrottleBackend**：仅用于单进程测试或极简场景，不适用于多 worker 生产部署
- **RedisThrottleBackend**：需要调用方自行安装 `redis`；未安装时会抛出明确异常，不做静默退化

### 设计边界

- **不做用户级 / 租户级限流抽象**：bucket 的划分由业务层决定
- **不固定全局限流算法**：调用方可自行替换为令牌桶、滑动窗口等后端实现
- **不隐式自动重试**：限流后的处理路径必须显式指定
- **不替代下游系统保护**：网关、数据库、第三方 API 的保护策略仍应由各自边界负责

### 推荐接入方式

- **只需要单 worker 限流**：优先使用 `build_rate_limited_task_options(rate_limit=...)`
- **需要多 worker 全局限流**：使用 `RedisThrottleBackend`，并显式安装 `redis`
- **希望快速失败**：选择 `on_throttled="reject"`
- **希望显式重排队**：选择 `on_throttled="queue"` 并提供 `queue_handler`

---

## 14. config_source — 配置中心适配

**问题**：不同项目往往已经有自己的配置中心或配置加载方式，但 `ab_celery.config` 故意只负责结构化配置对象，不直接接入任何外部配置系统。这样虽然边界清晰，却会让每个项目都重复写一层“拉配置 → 转 `CeleryConfig`”的薄胶水。

**解决**：`config_source` 模块只补最小约定：

- `ConfigSource`：配置源协议
- `MemoryConfigSource`：测试 / 简单场景的内存实现
- `load_celery_config`：从配置源显式加载一次 `CeleryConfig`
- `build_celery_config_from_source`：直接构造可用于 `Celery.conf.update` 的扁平配置字典

### 使用方式

```python
from ab_celery.config_source import (
    MemoryConfigSource,
    build_celery_config_from_source,
    load_celery_config,
)

source = MemoryConfigSource(
    {
        "app_name": "myapp",
        "broker_url": "redis://localhost:6379/0",
        "timezone": "Asia/Shanghai",
    }
)

config = load_celery_config(source)
conf_dict = build_celery_config_from_source(source)
```

### 核心语义

- **只加载一次**：公共层不处理配置热更新，也不保活任何长连接客户端
- **只接收 `dict` / `CeleryConfig`**：配置源最终必须返回这两类之一，避免协议失真
- **兜底策略必须显式提供**：配置拉取失败时，只有调用方传入 `fallback` 才会执行降级
- **配置校验仍由 `CeleryConfig` 负责**：公共层不额外复制一套字段校验逻辑

### 显式兜底方式

```python
from ab_celery.config_source import MemoryConfigSource, load_celery_config

source = MemoryConfigSource(lambda: fetch_remote_config())

config = load_celery_config(
    source,
    fallback=lambda exc: {
        "app_name": "myapp",
        "broker_url": "memory://",
    },
)
```

### 后端说明

- **MemoryConfigSource**：仅用于测试、示例或极简场景
- **真实配置中心接入**：由调用方自行实现 `ConfigSource` 协议，公共层不导入任何具体客户端

### 设计边界

- **不绑定任何具体配置中心**：Nacos、Apollo、Consul 等都不在公共层内置
- **不支持运行期热更新**：本模块只负责启动时或显式触发时的一次性加载
- **不内置失败兜底策略**：回退到本地默认值、终止启动还是重试，全部由调用方决定
- **不替代 `config` 模块**：字段定义、默认值与合法性校验仍以 `CeleryConfig` 为准

### 推荐接入方式

- **测试或简单场景**：使用 `MemoryConfigSource`
- **已有配置中心客户端**：在项目侧实现 `ConfigSource.load()`，返回 `dict` 或 `CeleryConfig`
- **需要失败降级**：显式传入 `fallback`
- **只想直接得到 conf 字典**：使用 `build_celery_config_from_source`

---

## 最小使用场景

按调用方对接深度的不同，本工具集支持三类典型最小用法。可以按需选用，不强制全量接入。

### 场景 A：仅使用 `task_base`

适用于「希望统一重试策略，但 app 创建与配置仍由项目自管」的场景。

```python
from celery import Celery
from ab_celery.task_base import AutoRetryTask

app = Celery("myapp", broker="redis://localhost:6379/0")

@app.task(base=AutoRetryTask, bind=True)
def fetch_remote(self, url):
    ...
```

### 场景 B：仅使用 `config` + 原生 `Celery`

适用于「想要标准化配置组织，但仍希望自己控制 app 装配顺序」的场景。

```python
from celery import Celery
from ab_celery.config import CeleryConfig, build_celery_config

config = CeleryConfig(
    app_name="myapp",
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/1",
    timezone="Asia/Shanghai",
)

app = Celery(config.app_name)
app.conf.update(build_celery_config(config))
```

### 场景 C：使用 `create_celery_app` 完整接入

适用于「希望一次完成基础接入」的新项目。统一封装了「补丁 → app → 配置 → 计时 → 任务发现 → 周期任务」这条顺序敏感流程。

```python
from ab_celery.app_factory import create_celery_app
from ab_celery.config import CeleryConfig
from ab_celery.task_base import AutoRetryTask
from ab_celery.queues import build_queues
from ab_celery.routing import RouteRule, build_routes

app = create_celery_app(
    config=CeleryConfig(
        app_name="myapp",
        broker_url="redis://localhost:6379/0",
        result_backend="redis://localhost:6379/1",
        timezone="Asia/Shanghai",
        task_queues=build_queues(["default", "heavy", "cron"]),
        task_routes=build_routes([
            RouteRule(queue="heavy", prefix="myapp.heavy."),
            RouteRule(queue="cron", prefix="myapp.cron."),
        ]),
    ),
    task_packages=["myapp"],
    default_task_base=AutoRetryTask,
    enable_task_timer=True,
    task_timer_recorder=my_recorder,        # 调用方实现的 MetricsRecorder
    apply_redbeat_sentinel_patch=False,     # 仅在 beat 进程使用 Sentinel 时启用
)
```

> Django 项目若使用 `django_celery_beat`，可在 settings 中追加：
> `CELERY_BEAT_SCHEDULER = "ab_celery.safe_scheduler.SafeDatabaseScheduler"`，
> 防止管理员手动禁用的周期任务被启动时重新启用。

---

## 推荐导入路径

参考设计文档第 7.4 节，所有通用名称均通过完整包路径导入，避免与项目内同名模块混淆：

```python
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
# Django settings 中字符串引用：
#   CELERY_BEAT_SCHEDULER = "ab_celery.safe_scheduler.SafeDatabaseScheduler"
```

顶层 `ab_celery/__init__.py` **不裸导出** `config`、`app_factory`、`task_base` 等通用名称，仅在文档中给出推荐导入方式。

---

## 测试边界

- 所有模块测试统一位于 `tests/test_celery/`，全部为纯单元测试 + mock
- 不依赖真实 broker / 真实 Redis / 真实 Sentinel
- 涉及 `redbeat`、`django_celery_beat` 的能力均通过 mock 覆盖
- 集成测试请由调用方在自身项目中补齐，本工具集不承诺替代
