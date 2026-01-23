# 条件匹配器 (Condition Matcher)

一个基于 JsonLogic 的通用条件匹配引擎，提供简洁易用的 API 来进行条件匹配和数据过滤。

## 特性

- ✅ **简洁的配置格式** - JSON 配置，易读易写
- ✅ **丰富的操作符** - 支持等于、包含、正则、数值比较等
- ✅ **逻辑组合** - 支持 AND/OR 逻辑组合
- ✅ **嵌套字段** - 自动支持 `host.os_type` 等嵌套路径
- ✅ **高性能** - 基于 json-logic-qubit，性能优秀
- ✅ **零业务依赖** - 纯粹的匹配逻辑，可用于任何场景


## 快速开始

### 基本匹配

```python
from matcher import ConditionMatcher

# 定义条件
conditions = [
    {"field": "ip", "op": "eq", "value": "10.0.0.1"},
    {"field": "env", "op": "eq", "value": "prod"},
]

# 创建匹配器
matcher = ConditionMatcher(conditions)

# 测试数据
data = {"ip": "10.0.0.1", "env": "prod"}
print(matcher.match(data))  # True
```

### OR 条件

```python
conditions = [
    {"field": "level", "op": "eq", "value": "error"},
    {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
]
matcher = ConditionMatcher(conditions)

# level=error OR level=critical
matcher.match({"level": "error"})     # True
matcher.match({"level": "critical"})  # True
matcher.match({"level": "info"})      # False
```

### 混合 AND/OR

```python
conditions = [
    {"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2"]},
    {"field": "env", "op": "eq", "value": "prod"},
    {"field": "force", "op": "eq", "value": True, "logic": "or"},
]
# (ip IN [10.0.0.1, 10.0.0.2] AND env=prod) OR force=True
```

## 支持的操作符

| 操作符 | 说明 | 示例 |
|--------|------|------|
| `eq` | 等于 | `{"field": "status", "op": "eq", "value": "active"}` |
| `neq` | 不等于 | `{"field": "status", "op": "neq", "value": "disabled"}` |
| `in` | 包含在列表 | `{"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2"]}` |
| `not_in` | 不在列表 | `{"field": "env", "op": "not_in", "value": ["test", "dev"]}` |
| `include` | 子串包含 | `{"field": "message", "op": "include", "value": "error"}` |
| `exclude` | 子串不包含 | `{"field": "message", "op": "exclude", "value": "success"}` |
| `regex` | 正则匹配 | `{"field": "name", "op": "regex", "value": "CPU.*"}` |
| `gt` | 大于 | `{"field": "cpu", "op": "gt", "value": 80}` |
| `gte` | 大于等于 | `{"field": "cpu", "op": "gte", "value": 80}` |
| `lt` | 小于 | `{"field": "memory", "op": "lt", "value": 90}` |
| `lte` | 小于等于 | `{"field": "memory", "op": "lte", "value": 90}` |
| `startswith` | 前缀匹配 | `{"field": "path", "op": "startswith", "value": "/api/"}` |
| `endswith` | 后缀匹配 | `{"field": "file", "op": "endswith", "value": ".log"}` |

## 高级用法

### 嵌套字段

```python
conditions = [
    {"field": "host.os_type", "op": "eq", "value": "linux"},
    {"field": "tags.env", "op": "eq", "value": "prod"},
]

data = {
    "host": {"os_type": "linux"},
    "tags": {"env": "prod"}
}
matcher.match(data)  # True
```

### 过滤列表

```python
from matcher import filter_items

alerts = [
    {"id": 1, "level": "error"},
    {"id": 2, "level": "info"},
    {"id": 3, "level": "error"},
]

conditions = [{"field": "level", "op": "eq", "value": "error"}]
result = filter_items(alerts, conditions)
# [{"id": 1, "level": "error"}, {"id": 3, "level": "error"}]
```

### 便捷函数

```python
from matcher import match

# 快速匹配单条数据
result = match(
    {"ip": "10.0.0.1"},
    [{"field": "ip", "op": "eq", "value": "10.0.0.1"}]
)  # True
```

### 获取 JsonLogic 规则

```python
matcher = ConditionMatcher(conditions)
jsonlogic_rule = matcher.get_jsonlogic_rule()
print(jsonlogic_rule)  # 查看转换后的 JsonLogic 格式
```

## 实际场景示例

### 告警分派

```python
# 分派规则: (IP在白名单 AND 环境是生产) OR (告警级别是致命)
conditions = [
    {"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2"]},
    {"field": "env", "op": "eq", "value": "prod"},
    {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
]

matcher = ConditionMatcher(conditions)

# 批量分派告警
alerts = get_pending_alerts()
for alert in alerts:
    if matcher.match(alert):
        dispatch_to_team_a(alert)
    else:
        dispatch_to_default_team(alert)
```

### 日志过滤

```python
conditions = [
    {"field": "level", "op": "in", "value": ["error", "critical"]},
    {"field": "message", "op": "regex", "value": "(timeout|failed)"},
]

matcher = ConditionMatcher(conditions)
error_logs = matcher.filter(all_logs)
```

### CMDB 主机筛选

```python
conditions = [
    {"field": "host.os_type", "op": "eq", "value": "linux"},
    {"field": "host.cpu_cores", "op": "gte", "value": 8},
    {"field": "tags.env", "op": "in", "value": ["prod", "staging"]},
]

hosts = get_all_hosts()
filtered_hosts = ConditionMatcher(conditions).filter(hosts)
```

## API 参考

### ConditionMatcher

主要的匹配器类。

#### 构造函数

```python
ConditionMatcher(conditions: list[dict] | None = None)
```

#### 方法

- `match(data: dict) -> bool` - 判断单条数据是否匹配
- `filter(items: list[dict]) -> list[dict]` - 过滤列表，返回匹配项
- `first(items: list[dict]) -> dict | None` - 返回第一个匹配项
- `get_jsonlogic_rule() -> dict` - 获取 JsonLogic 规则（用于调试）

### 便捷函数

```python
match(data: dict, conditions: list[dict]) -> bool
filter_items(items: list[dict], conditions: list[dict]) -> list[dict]
```

## 测试

运行测试：

```bash
cd /root/bk-monitor/bkmonitor
python -m pytest bkmonitor/utils/matcher/tests.py -v
```

运行示例：

```python
python bkmonitor/utils/matcher/examples.py
```

## 底层实现

本模块是对 [json-logic-qubit](https://github.com/QubitProducts/json-logic-py) 的封装，提供了更友好的 API：

- 将简洁的条件配置转换为 JsonLogic 格式
- 自动处理嵌套字段路径
- 注册自定义操作符（如 regex、startswith）
- 提供便捷的匹配和过滤方法

## 性能考虑

- JsonLogic 规则在初始化时一次性构建，后续匹配不需要重复解析
- 对于大批量数据过滤，考虑复用 `ConditionMatcher` 实例
- 嵌套字段访问使用简单的字典查找，性能良好

## License

MIT License - 与 bk-monitor 项目保持一致
