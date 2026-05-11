# distributed_lock

一个**零业务耦合**的 Redis 分布式锁通用 Python 模块，通过依赖注入与 `Protocol` 接口契约，使核心锁逻辑与具体 Redis 客户端实现解耦。

## 设计目标

- ✅ **零业务耦合**：不依赖任何业务模块，仅使用 Python 标准库
- ✅ **依赖注入**：通过构造参数注入 Redis 客户端，支持 `redis-py`、自定义包装类、Mock 对象
- ✅ **接口契约化**：使用 `typing.Protocol` 显式声明客户端依赖，让接口约束可见
- ✅ **行为兼容**：核心算法（`SET NX` 互斥、token 所有权校验、Pipeline 批量）与 bk-monitor 原实现等价
- ✅ **可测试**：通过 Mock client 即可完成单元测试，无需真实 Redis

## 模块结构

```
distributed_lock/
├── __init__.py            # 包入口，统一导出公共 API
├── base.py                # BaseLock 抽象基类
├── redis_lock.py          # RedisLock 单键锁
├── multi_redis_lock.py    # MultiRedisLock 批量锁
├── protocols.py           # RedisClientProtocol / PipelineProtocol
├── constants.py           # DEFAULT_TTL = 60
└── tests/                 # 单元测试
```

## 客户端协议（RedisClientProtocol）

任何 client 只要实现以下方法，即可作为参数注入：

| 方法 | 用途 |
|------|------|
| `set(name, value, ex, nx)` | SET NX 加锁 |
| `get(name)`                | 读取 token 用于所有权校验 |
| `delete(*names)`           | 释放锁 |
| `mget(keys)`               | 批量读取 token（MultiRedisLock） |
| `pipeline(transaction)`    | 创建 Pipeline 用于批量加锁（MultiRedisLock） |

`PipelineProtocol` 仅需实现 `set` 与 `execute`。

## 快速开始

### 1. RedisLock（单键互斥锁）

#### 使用 with 语句（推荐）

```python
import redis
from distributed_lock import RedisLock

client = redis.StrictRedis(host="127.0.0.1", port=6379)

with RedisLock("order:123", client=client, ttl=30) as lock:
    # 进入此处即表示已成功加锁；with 退出时自动释放
    do_critical_work()
```

#### 手动 acquire / release

```python
lock = RedisLock("order:123", client=client, ttl=30)
if lock.acquire(_wait=1.0):           # 最长等待 1 秒
    try:
        do_critical_work()
    finally:
        lock.release()
else:
    print("加锁失败，资源被占用")
```

### 2. MultiRedisLock（批量锁）

```python
from distributed_lock import MultiRedisLock

keys = ["task:1", "task:2", "task:3", "task:4"]
batch = MultiRedisLock(keys, client=client, ttl=60)

success_keys = batch.acquire()         # 返回成功加锁的 key 集合
print(f"已锁定 {len(success_keys)} 个资源")

if batch.is_locked("task:1"):
    process_task("task:1")

batch.release()                        # 仅释放本实例持有的 key
```

## 接入示例

### redis-py 客户端

```python
import redis
from distributed_lock import RedisLock

client = redis.StrictRedis(host="127.0.0.1", port=6379, decode_responses=True)
lock = RedisLock("my-resource", client=client, ttl=30)
```

> **注意**：`decode_responses=True` 会让 `get` 返回 `str`，与 token（`uuid.uuid4().hex`）类型一致；若使用 `bytes` 模式，请确保自行解码后再比较，或保持默认（False）以避免类型不匹配。本模块的 token 为 `str`，建议开启 `decode_responses=True`。

### 自定义 Cache 包装类

只要包装类实现了协议方法，即可直接注入：

```python
class MyCache:
    def set(self, name, value, ex=None, nx=False): ...
    def get(self, name): ...
    def delete(self, *names): ...
    def mget(self, keys): ...
    def pipeline(self, transaction=True): ...

lock = RedisLock("my-resource", client=MyCache())
```

### 单元测试中使用 Mock

```python
from unittest.mock import MagicMock
from distributed_lock import RedisLock

client = MagicMock()
client.set.return_value = True

lock = RedisLock("test-key", client=client)
assert lock.acquire() is True
```

## API 参考

### `RedisLock(name, client, ttl=None)`

| 方法 | 说明 |
|------|------|
| `acquire(_wait=0.001)` | 加锁；`_wait` 秒内自旋重试。成功返回 `True`，超时返回 `False` |
| `release()`            | 仅释放本实例持有的锁（token 校验） |
| `__enter__/__exit__`   | 支持 with 语句自动加解锁 |

### `MultiRedisLock(keys, client, ttl=None)`

| 方法 | 说明 |
|------|------|
| `acquire()`           | 通过 Pipeline 批量 SET NX，返回成功加锁的 key 集合 |
| `release()`           | 通过 MGET 批量校验 token，仅删除本实例持有的 key |
| `is_locked(key)`      | 查询 key 是否被本实例成功持有 |

### 常量

- `DEFAULT_TTL = 60`：默认锁过期时间（秒）

## 与 bk-monitor 原实现的差异

本模块抽离自 `bkmonitor/alarm_backends/core/lock/__init__.py`，**不修改原代码**，仅作通用化改造：

| 维度 | 原实现 | 本模块 |
|------|--------|--------|
| Redis 客户端 | 硬编码 `Cache("service-lock")` | 通过 `client` 参数注入 |
| 默认 TTL    | `alarm_backends.constants.CONST_MINUTES` | 内置 `DEFAULT_TTL = 60` |
| Token 生成  | `bkmonitor.utils.common_utils.uniqid4` | 标准库 `uuid.uuid4().hex` |
| 类型注解    | 无 | 使用 `RedisClientProtocol` |
| 业务依赖    | 依赖 `alarm_backends.*` / `bkmonitor.*` | 仅依赖 Python 标准库 |

核心算法（`SET NX` + token 所有权校验 + Pipeline 批量）保持完全一致。

## 运行测试

```bash
cd /root/bk-monitor
python3 -m unittest distributed_lock.tests.test_redis_lock distributed_lock.tests.test_multi_redis_lock -v
```

## 依赖

- Python ≥ 3.10（使用了 `X | None` 类型语法）
- 仅 Python 标准库（`typing`、`uuid`、`time`、`unittest.mock`）
- **不强依赖** `redis-py`，使用方自行选择客户端实现
