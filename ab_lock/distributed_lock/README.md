# distributed_lock

一个**零业务耦合**的 Redis 分布式锁通用 Python 模块，通过依赖注入与 `Protocol` 接口契约，使核心锁逻辑与具体 Redis 客户端实现解耦。

## 核心特性

- ✅ **零业务耦合**：不依赖任何业务模块，仅使用 Python 标准库
- ✅ **依赖注入**：通过构造参数注入 Redis 客户端，支持 `redis-py`、自定义包装类、Mock 对象
- ✅ **接口契约化**：使用 `typing.Protocol` 显式声明客户端依赖，让接口约束可见
- ✅ **6 种锁类型**：单键互斥锁、批量锁、可重入锁、Redlock 多节点锁、读写锁、异步锁
- ✅ **看门狗续期**：长事务自动续期 TTL，业务超过 TTL 也不会丢锁
- ✅ **原子操作**：所有加锁/释放/续期均通过 Lua 脚本保证原子性

## 快速开始

### 最小示例

```python
import redis
from ab_lock.distributed_lock import RedisLock

client = redis.StrictRedis(host="127.0.0.1", port=6379, decode_responses=True)

with RedisLock("order:123", client=client, ttl=30):
    do_critical_work()
```

## 锁类型详解

### 1. RedisLock — 单键互斥锁

最基础的分布式互斥锁，基于 Redis `SET NX` + Lua 脚本原子释放。

#### with 语句（推荐）

```python
from ab_lock.distributed_lock import RedisLock

with RedisLock("order:123", client=client, ttl=30) as lock:
    # 进入此处即表示已成功加锁；with 退出时自动释放
    do_critical_work()
```

#### 手动 acquire / release

```python
lock = RedisLock("order:123", client=client, ttl=30)
if lock.acquire(wait=1.0):           # 最长等待 1 秒
    try:
        do_critical_work()
    finally:
        lock.release()
else:
    print("加锁失败，资源被占用")
```

#### 阻塞等待

```python
# wait > 0 时会自旋重试，retry_interval 控制重试间隔（含随机抖动）
lock = RedisLock("order:123", client=client, ttl=30)
if lock.acquire(wait=5.0, retry_interval=0.05):
    try:
        do_critical_work()
    finally:
        lock.release()
```

> **注意**：同一实例不可重复 `acquire()`，否则抛出 `RuntimeError`。

---

### 2. MultiRedisLock — 批量锁

对多个资源同时加锁，通过 Pipeline 批量执行 `SET NX` 减少网络往返。

```python
from ab_lock.distributed_lock import MultiRedisLock

keys = ["task:1", "task:2", "task:3", "task:4"]
batch = MultiRedisLock(keys, client=client, ttl=60)

# 批量加锁（非阻塞），返回成功加锁的 key 集合
success_keys = batch.acquire()
print(f"已锁定 {len(success_keys)} 个资源")

# 查询指定 key 是否被本实例持有
if batch.is_locked("task:1"):
    process_task("task:1")

# 释放仅删除本实例持有的 key（Lua 原子校验 token）
batch.release()
```

#### with 语句

```python
with MultiRedisLock(["task:1", "task:2"], client=client, ttl=60) as batch:
    # batch.acquire() 已自动执行
    if batch.is_locked("task:1"):
        process_task("task:1")
# with 退出时自动 release()
```

> **提示**：批量锁为"尽力而为"模式——部分 key 加锁失败不影响其他 key 的加锁结果。

---

### 3. ReentrantRedisLock — 可重入锁

同一实例可多次 `acquire`，内部维护重入计数，`release` 时计数递减，归零时才真正删除 key。

```python
from ab_lock.distributed_lock import ReentrantRedisLock

with ReentrantRedisLock("res", client=client, ttl=30) as lock:
    # 已加锁，count=1
    with lock:
        # 重入，count=2
        do_something()
    # count=1，未真正释放
# count=0，锁被彻底删除
```

#### 手动调用

```python
lock = ReentrantRedisLock("res", client=client, ttl=30)
lock.acquire()            # count=1
lock.acquire()            # count=2（重入成功）
lock.release()            # count=1
lock.release()            # count=0，锁被删除
```

#### 查询状态

```python
lock = ReentrantRedisLock("res", client=client, ttl=30)
lock.acquire()
print(lock.lock_count)    # 1
print(lock.is_locked())   # True
```

> **注意**：必须配对调用 `acquire` / `release`，否则锁会残留到 TTL 过期。

---

### 4. Redlock — 多节点高可用锁

基于 [Redlock 算法](https://redis.io/docs/manual/patterns/distributed-locks/)，在 N 个独立 Redis 实例上加锁，需**多数派（N/2 + 1）** 成功才认为加锁成功。

```python
import redis
from ab_lock.distributed_lock import Redlock

# 建议 3 / 5 / 7 个独立实例（非主从复制）
clients = [
    redis.StrictRedis(host="10.0.0.1", decode_responses=True),
    redis.StrictRedis(host="10.0.0.2", decode_responses=True),
    redis.StrictRedis(host="10.0.0.3", decode_responses=True),
]

with Redlock("order:123", clients=clients, ttl=10) as lock:
    do_critical_work()
```

#### 重试与指数退避

```python
lock = Redlock(
    "order:123",
    clients=clients,
    ttl=10,
    retry_times=5,        # 总重试次数
    retry_delay=0.2,      # 重试间隔基数（秒），实际会加入随机抖动
)
if lock.acquire():
    try:
        do_critical_work()
    finally:
        lock.release()
```

#### 查询有效期

```python
import time
lock = Redlock("order:123", clients=clients, ttl=10)
if lock.acquire():
    remaining = lock.valid_until - time.monotonic()
    print(f"锁剩余有效时间: {remaining:.2f}s")
    lock.release()
```

> **前提**：各实例之间必须独立部署、无主从关系、独立故障域。

---

### 5. RWLock — 读写锁

- **读锁（共享锁）**：多个持有者可同时获取；只要存在读锁，写锁无法加锁
- **写锁（独占锁）**：同一时刻只能一个持有者；持有写锁时任何读/写锁都被阻塞
- **降级**：写锁 → 读锁（原子，无锁空窗）
- **升级**：读锁 → 写锁（仅当本实例是唯一读者时成功）

#### 基本用法

```python
from ab_lock.distributed_lock import RWLock

rw = RWLock("resource", client=client, ttl=30)

# 读锁
with rw.read_lock():
    read_data()

# 写锁
with rw.write_lock():
    write_data()
```

#### 写锁降级为读锁

降级是原子操作，中间无无锁窗口期，写后读可读到自己刚写入的值。

```python
rw = RWLock("resource", client=client, ttl=30)

with rw.write_lock():
    write_data()
    rw.downgrade_to_read()   # 原子降级，无需先释放写锁再加读锁
    read_data()               # 此时持有读锁，其他读者也可进入
# with 退出时自动 release_read()
```

#### 读锁升级为写锁

仅当本实例是**唯一读者**时才会成功；否则返回 `False`。

```python
rw = RWLock("resource", client=client, ttl=30)

with rw.read_lock():
    data = read_data()
    if rw.try_upgrade_to_write(wait=2.0):   # 等待其他读者释放，最长 2 秒
        write_data()
    # 升级失败：仍持有读锁，可选择先 release_read 再 acquire_write
```

> ⚠ **升级活锁警告**：若两个实例同时持有读锁并都调用 `try_upgrade_to_write` 等待，将出现互相等待的活锁。建议：升级失败时先 `release_read` 再 `acquire_write`，接受短暂无锁窗口。

---

### 6. AsyncRedisLock — 异步锁

适用于 `redis.asyncio` 的异步项目，所有方法均为协程，配合 `async with` 使用。

```python
import redis.asyncio as aioredis
from ab_lock.distributed_lock import AsyncRedisLock

client = aioredis.Redis(host="127.0.0.1", decode_responses=True)

async def main():
    async with AsyncRedisLock("my-resource", client=client, ttl=30) as lock:
        await do_async_work()
```

#### 手动 await

```python
lock = AsyncRedisLock("my-resource", client=client, ttl=30)
if await lock.acquire(wait=1.0):
    try:
        await do_async_work()
    finally:
        await lock.release()
```

## 看门狗（Watchdog）自动续期

### 适用场景

当业务执行时间可能超过锁的 TTL 时，看门狗会在后台自动续期，确保持锁方仍在运行期间锁不会过期。

### 启用方式

在构造锁时传入 `enable_watchdog=True`：

```python
from ab_lock.distributed_lock import RedisLock

with RedisLock("res", client=client, ttl=30, enable_watchdog=True):
    long_running_business()   # 即使超过 30 秒也不会丢锁
# with 退出时自动停止看门狗并释放锁
```

异步锁同样支持：

```python
from ab_lock.distributed_lock import AsyncRedisLock

async with AsyncRedisLock("res", client=client, ttl=30, enable_watchdog=True):
    await long_running_async_business()
```

Redlock 也支持看门狗（多节点多数派续期）：

```python
with Redlock("res", clients=clients, ttl=10, enable_watchdog=True):
    long_running_business()
```

### on_lock_lost 回调

当续期发现 token 不匹配（锁已被他人抢占或已过期），会触发回调通知业务方：

```python
def handle_lock_lost(key: str):
    print(f"锁 {key} 已丢失，请停止当前业务！")

with RedisLock(
    "res", client=client, ttl=30,
    enable_watchdog=True,
    on_lock_lost=handle_lock_lost,
):
    long_running_business()
```

### 续期策略

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `watchdog_interval` | `ttl / 3` | 续期间隔（秒），必须 < ttl |
| `max_renew_failures` | 3 | 连续续期 RPC 失败的容忍次数，超过视为锁丢失 |
| `on_lock_lost` | None | 锁丢失时的回调函数，参数为锁 key |

## 客户端协议

### RedisClientProtocol（同步）

任何 client 只要实现以下方法，即可作为参数注入：

| 方法 | 用途 |
|------|------|
| `set(name, value, ex, nx)` | SET NX 加锁 |
| `get(name)` | 读取 token 用于所有权校验 |
| `delete(*names)` | 释放锁 |
| `mget(keys)` | 批量读取 token（MultiRedisLock） |
| `eval(script, numkeys, *keys_and_args)` | 执行 Lua 脚本 |
| `pipeline(transaction)` | 创建 Pipeline |

### AsyncRedisClientProtocol（异步）

| 方法 | 用途 |
|------|------|
| `set(name, value, ex, nx)` → Awaitable | 异步 SET NX |
| `get(name)` → Awaitable | 异步 GET |
| `delete(*names)` → Awaitable | 异步 DEL |
| `eval(script, numkeys, *keys_and_args)` → Awaitable | 异步 EVAL |

### PipelineProtocol

仅需实现 `set` 与 `execute`。

### 接入示例

#### redis-py 客户端

```python
import redis
from ab_lock.distributed_lock import RedisLock

client = redis.StrictRedis(host="127.0.0.1", port=6379, decode_responses=True)
lock = RedisLock("my-resource", client=client, ttl=30)
```

> **提示**：建议开启 `decode_responses=True`，使 `get` 返回 `str`，与 token（`uuid.uuid4().hex`）类型一致。

#### 自定义 Cache 包装类

只要包装类实现了协议方法，即可直接注入：

```python
class MyCache:
    def set(self, name, value, ex=None, nx=False): ...
    def get(self, name): ...
    def delete(self, *names): ...
    def mget(self, keys): ...
    def eval(self, script, numkeys, *keys_and_args): ...
    def pipeline(self, transaction=True): ...

lock = RedisLock("my-resource", client=MyCache())
```

#### 单元测试中使用 Mock

```python
from unittest.mock import MagicMock
from ab_lock.distributed_lock import RedisLock

client = MagicMock()
client.set.return_value = True

lock = RedisLock("test-key", client=client)
assert lock.acquire() is True
```

## 模块结构

```
distributed_lock/
├── __init__.py            # 包入口，统一导出公共 API
├── base.py                # BaseLock 抽象基类
├── redis_lock.py          # RedisLock 单键互斥锁
├── multi_redis_lock.py    # MultiRedisLock 批量锁
├── reentrant_lock.py      # ReentrantRedisLock 可重入锁
├── redlock.py             # Redlock 多节点高可用锁
├── rw_lock.py             # RWLock 读写锁
├── async_redis_lock.py    # AsyncRedisLock 异步锁
├── watchdog.py            # SyncWatchdog / AsyncWatchdog 看门狗
├── protocols.py           # RedisClientProtocol / AsyncRedisClientProtocol / PipelineProtocol
├── lua_scripts.py         # Lua 脚本集中存放
└── constants.py           # DEFAULT_TTL = 60
```

## API 速查表

### 构造参数

| 锁类型 | 关键参数 |
|--------|----------|
| `RedisLock` | `name, client, ttl=None, enable_watchdog=False, watchdog_interval=None, on_lock_lost=None` |
| `MultiRedisLock` | `keys, client, ttl=None` |
| `ReentrantRedisLock` | `name, client, ttl=None` |
| `Redlock` | `name, clients, ttl=None, retry_times=3, retry_delay=0.2, enable_watchdog=False, watchdog_interval=None, on_lock_lost=None` |
| `RWLock` | `name, client, ttl=None` |
| `AsyncRedisLock` | `name, client, ttl=None, enable_watchdog=False, watchdog_interval=None, on_lock_lost=None` |

### 核心方法

| 锁类型 | 方法 | 说明 |
|--------|------|------|
| `RedisLock` | `acquire(wait=0, retry_interval=0.01)` | 加锁；`wait` 秒内自旋重试 |
| | `release()` → int | 释放锁（Lua 原子），返回 1 成功 / 0 未持锁 |
| | `is_locked()` → bool | 本实例是否持锁 |
| `MultiRedisLock` | `acquire()` → set[str] | 批量 SET NX，返回成功加锁的 key 集合 |
| | `release()` | Lua 原子释放本实例持有的 key |
| | `is_locked(key)` → bool | 指定 key 是否被本实例持有 |
| `ReentrantRedisLock` | `acquire(wait=0, retry_interval=0.01)` | 加锁或重入 |
| | `release()` → int | 计数 -1；返回 >0 仍重入 / 0 彻底释放 / -1 异常 |
| | `lock_count` → int | 当前重入计数 |
| | `is_locked()` → bool | 本实例是否持锁 |
| `Redlock` | `acquire(wait=0)` | 多数派加锁 |
| | `release()` → int | 向所有节点释放，返回成功节点数 |
| | `valid_until` → float \| None | 锁有效截止时间（monotonic） |
| | `is_locked()` → bool | 本实例是否持锁 |
| `RWLock` | `acquire_read(wait=0)` / `release_read()` | 读锁获取/释放 |
| | `acquire_write(wait=0)` / `release_write()` | 写锁获取/释放 |
| | `downgrade_to_read()` → bool | 写→读原子降级 |
| | `try_upgrade_to_write(wait=0)` → bool | 读→写原子升级（需唯一读者） |
| | `read_lock()` / `write_lock()` | with 上下文管理器 |
| | `read_count` → int | 读锁重入计数 |
| | `holds_write` → bool | 是否持有写锁 |
| `AsyncRedisLock` | `await acquire(wait=0, retry_interval=0.01)` | 异步加锁 |
| | `await release()` → int | 异步释放 |
| | `is_locked()` → bool | 本实例是否持锁 |

### 常量

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TTL` | 60 | 默认锁过期时间（秒） |

## 依赖与环境

- Python ≥ 3.10（使用了 `X | None` 类型语法）
- 仅 Python 标准库（`typing`、`uuid`、`time`、`threading`、`asyncio`）
- **不强依赖** `redis-py`，使用方自行选择客户端实现

## 运行测试

```bash
python3 -m pytest tests/test_distributed_lock/ -v
```
