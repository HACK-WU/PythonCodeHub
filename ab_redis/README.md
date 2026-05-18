# ab_redis — Redis Key 声明式元数据管理

从 bk-monitor 项目中提炼的 Redis Key 管理模式，解耦业务依赖后可独立使用。

## 解决什么问题

在 Redis 项目中，key 的模板、TTL、后端等信息通常散落各处，以纯字符串硬编码使用，导致：

- key 命名不一致，难以维护
- TTL 和后端配置与使用处脱节，修改时容易遗漏
- 无法集中查看所有 key 的定义和用途
- 多环境/多集群部署时前缀管理混乱

`RedisKey` 提供**声明式**的 key 元数据管理，将模板、TTL、后端、前缀等集中声明，通过 `get_key()` 生成完整的 Redis key。

---

## 快速开始

### 最小示例

```python
from ab_redis.key import StringKey

USER_CACHE = StringKey(
    key_tpl="cache.user.{user_id}",
    ttl=3600,
    backend="default",
)

key = USER_CACHE.get_key(user_id=123)
# -> "cache.user.123"
```

### 带前缀管理

```python
from ab_redis.key import StringKey, KeyPrefixManager

prefix_mgr = KeyPrefixManager(
    global_prefix="myapp.ee",
    cluster_prefix="myapp.ee.cluster1",
)

USER_CACHE = StringKey(
    key_tpl="cache.user.{user_id}",
    ttl=3600,
    backend="default",
    is_global=True,
    prefix_manager=prefix_mgr,
)

key = USER_CACHE.get_key(user_id=123)
# -> "myapp.ee.cache.user.123"
```

---

## 核心概念

### 1. RedisKey — Key 元数据基类

| 属性 | 类型 | 说明 |
|------|------|------|
| `key_tpl` | `str` | key 模板，支持 `{placeholder}` 格式化 |
| `ttl` | `int` | 过期时间（秒） |
| `backend` | `str` | Redis 实例/数据库标识，如 `"default"`、`"service"` |
| `is_global` | `bool` | 是否全局 key（跨集群共享 vs 集群隔离），默认 `False` |
| `prefix_manager` | `KeyPrefixManager` | 前缀管理器，`None` 时不添加前缀 |
| `client_factory` | `Callable[[str], RedisKeyClientProtocol]` | Redis 客户端工厂，`None` 时 `expire()` 不可用 |
| `label` | `str` | 描述信息（仅文档用途） |

### 2. 类型子类

| 子类 | 数据结构 | 额外能力 |
|------|----------|----------|
| `StringKey` | String | — |
| `HashKey` | Hash | `field_tpl` + `get_field()` |
| `SetKey` | Set | — |
| `ListKey` | List | — |
| `SortedSetKey` | SortedSet | — |

### 3. KeyPrefixManager — 前缀管理器

管理全局前缀和集群隔离前缀，`is_global` 标记自动选择：

| 方法 | 说明 |
|------|------|
| `get_prefix(is_global=False)` | `True` 返回 `global_prefix`，`False` 返回 `cluster_prefix` |

---

## 使用方式

### 声明式定义（推荐）

直接用子类构造，类型安全、IDE 可补全：

```python
from ab_redis.key import StringKey, HashKey, KeyPrefixManager

prefix_mgr = KeyPrefixManager(
    global_prefix="myapp.ee",
    cluster_prefix="myapp.ee.cluster1",
)

# String Key
USER_CACHE = StringKey(
    key_tpl="cache.user.{user_id}",
    ttl=3600,
    backend="default",
    is_global=True,
    label="用户信息缓存",
    prefix_manager=prefix_mgr,
)

# Hash Key
DIMENSION_CACHE = HashKey(
    key_tpl="cache.dimension.{strategy_id}.{item_id}",
    field_tpl="{dimensions_md5}",
    ttl=1800,
    backend="service",
    label="维度信息缓存",
    prefix_manager=prefix_mgr,
)
```

#### 生成 key

```python
key = USER_CACHE.get_key(user_id=123)
# -> "myapp.ee.cache.user.123"

key = DIMENSION_CACHE.get_key(strategy_id=1, item_id=2)
# -> "myapp.ee.cluster1.cache.dimension.1.2"
```

#### 生成 Hash field

```python
field = DIMENSION_CACHE.get_field(dimensions_md5="abc123")
# -> "abc123"
```

#### 设置过期

```python
# 需要设置 client_factory
from my_redis import get_client

USER_CACHE = StringKey(
    key_tpl="cache.user.{user_id}",
    ttl=3600,
    backend="default",
    prefix_manager=prefix_mgr,
    client_factory=get_client,
)

USER_CACHE.expire(user_id=123)
```

### 配置驱动创建

从 YAML/JSON 等外部配置加载时使用 `from_config`：

#### 子类直接调用（无需 key_type）

```python
USER_CACHE = StringKey.from_config({
    "key_tpl": "cache.user.{user_id}",
    "ttl": 3600,
    "backend": "default",
})
```

#### 基类调用（通过 key_type 自动路由）

```python
from ab_redis.key import RedisKey

USER_CACHE = RedisKey.from_config({
    "key_type": "string",
    "key_tpl": "cache.user.{user_id}",
    "ttl": 3600,
    "backend": "default",
})
```

支持的 `key_type` 值：`string`、`hash`、`set`、`list`、`sorted_set`。

### 兼容旧接口

`register_key` 仍可用，内部委托给 `RedisKey.from_config`：

```python
from ab_redis.key import register_key

USER_CACHE = register_key({
    "key_type": "string",
    "key_tpl": "cache.user.{user_id}",
    "ttl": 3600,
    "backend": "default",
})
```

> 推荐迁移到 `RedisKey.from_config` 或直接使用子类构造。

---

## 前缀行为

| `is_global` | 选用前缀 | 场景 |
|-------------|----------|------|
| `True` | `global_prefix` | 跨集群共享的 key（如配置、维度） |
| `False` | `cluster_prefix` | 仅当前集群可见的 key（如缓存、计数器） |

防重复拼接：如果 key 已包含前缀，不会重复添加。

---

## 模块结构

```
ab_redis/
├── __init__.py    # 包入口
└── key.py         # RedisKey 及类型子类、KeyPrefixManager
```

## API 速查

| 类/方法 | 说明 |
|---------|------|
| `RedisKey(key_tpl, ttl, backend, ...)` | Key 元数据基类 |
| `StringKey(...)` | String 类型 Key |
| `HashKey(..., field_tpl=)` | Hash 类型 Key，支持 field 模板 |
| `SetKey(...)` | Set 类型 Key |
| `ListKey(...)` | List 类型 Key |
| `SortedSetKey(...)` | SortedSet 类型 Key |
| `KeyPrefixManager(global_prefix, cluster_prefix)` | 前缀管理器 |
| `RedisKey.from_config(config)` | 配置驱动创建（含 key_type 自动路由） |
| `register_key(config)` | 兼容旧接口，委托 `from_config` |

| 实例方法 | 说明 |
|----------|------|
| `get_key(**kwargs)` | 格式化模板 + 添加前缀，返回完整 key |
| `expire(**kwargs)` | 便捷设置过期时间（需 client_factory） |
| `client` | 延迟获取 Redis 客户端 |

## 依赖

- Python ≥ 3.10
- 仅 Python 标准库（`redis` 仅在 `client_factory` 需要时）

## 运行测试

```bash
python3 -m pytest tests/test_redis/test_key.py -v
```
