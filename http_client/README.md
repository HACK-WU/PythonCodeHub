# AB Request HTTP Client

功能强大、易于扩展的 Python HTTP 客户端框架。

## 📁 模块结构

```
ab_request/http_client/
├── __init__.py          # 模块导出接口
├── client.py            # 核心客户端基类
├── exceptions.py        # 异常定义
├── constants.py         # 常量配置
├── parser.py            # 响应解析器
├── formatter.py         # 响应格式化器
├── executor.py          # 异步执行器
├── cache.py             # 缓存支持
├── examples.py          # 使用示例
└── README.md            # 本文档
```

## 🎯 核心组件

### 1. 客户端基类 (client.py)
- **BaseClient**: 提供统一的 HTTP 请求接口
- 支持自定义认证、重试策略、连接池管理
- 灵活的配置系统，支持类级别和实例级别配置

### 2. 异常管理 (exceptions.py)
- **APIClientError**: 异常基类
- **APIClientHTTPError**: HTTP 错误（4xx, 5xx）
- **APIClientNetworkError**: 网络连接错误
- **APIClientTimeoutError**: 请求超时
- **APIClientValidationError**: 参数验证错误

### 3. 响应解析器 (parser.py)
- **JSONResponseParser**: 解析 JSON 响应
- **ContentResponseParser**: 获取字节内容
- **RawResponseParser**: 返回原始响应对象
- **FileWriteResponseParser**: 流式下载文件

### 4. 响应格式化器 (formatter.py)
- **DefaultResponseFormatter**: 统一格式化响应为 `{result, code, message, data}` 结构
- 支持自定义格式化逻辑

### 5. 异步执行器 (executor.py)
- **ThreadPoolAsyncExecutor**: 线程池并发执行
- 支持自定义执行策略

### 6. 缓存支持 (cache.py)
- **InMemoryCacheBackend**: 内存 LRU 缓存
- **RedisCacheBackend**: Redis 分布式缓存
- **CacheClientMixin**: 缓存混入类，提供透明缓存功能

### 7. 常量配置 (constants.py)
- 集中管理默认配置、HTTP 方法、重试策略等常量
- 便于统一修改和维护

## 🚀 快速开始

### 基本使用

```python
from http_client import BaseClient, JSONResponseParser


class MyAPIClient(BaseClient):
    base_url = "https://api.example.com"
    response_parser_class = JSONResponseParser


# 创建客户端实例
client = MyAPIClient()

# 发送请求
result = client.request({
    "endpoint": "/users",
    "params": {"page": 1}
})

print(result)
# 输出: {'result': True, 'code': 200, 'message': 'Success', 'data': {...}}
```

### 异步请求

```python
# 并发执行多个请求
results = client.request([
    {"endpoint": "/users/1"},
    {"endpoint": "/users/2"},
    {"endpoint": "/users/3"},
], is_async=True)
```

### 使用缓存

```python
from http_client import CacheClientMixin


class CachedAPIClient(CacheClientMixin, BaseClient):
    base_url = "https://api.example.com"
    default_cache_expire = 300  # 5分钟


client = CachedAPIClient()

# 第一次请求会缓存
result1 = client.request({"endpoint": "/users"})

# 第二次请求直接从缓存获取
result2 = client.request({"endpoint": "/users"})

# 强制刷新缓存
result3 = client.refresh({"endpoint": "/users"})

# 绕过缓存
result4 = client.cacheless({"endpoint": "/users"})
```

### 自定义认证

```python
from requests.auth import AuthBase

class TokenAuth(AuthBase):
    def __init__(self, token):
        self.token = token
    
    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r

class AuthenticatedClient(BaseClient):
    base_url = "https://api.example.com"
    authentication_class = TokenAuth("your-token-here")
```

## 📚 更多示例

查看 [examples.py](examples.py) 获取更多使用示例。

运行示例：
```bash
python -m ab_request.http_client.examples
```

## 🔧 配置选项

### 类级别配置

```python
class MyClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/default"
    method = "GET"
    default_timeout = 30
    default_retries = 3
    max_workers = 10
    authentication_class = MyAuth
    executor_class = ThreadPoolAsyncExecutor
    response_parser_class = JSONResponseParser
    response_formatter_class = DefaultResponseFormatter
```

### 实例级别配置

```python
client = MyClient(
    timeout=60,
    retries=5,
    max_workers=20,
    authentication=MyAuth("token"),
    response_parser=JSONResponseParser(),
    default_headers={"User-Agent": "MyApp/1.0"}
)
```

## 🎨 设计原则

1. **单一职责**: 每个模块专注于特定功能
2. **开闭原则**: 易于扩展，无需修改核心代码
3. **依赖倒置**: 依赖抽象而非具体实现
4. **DRY**: 避免代码重复，统一管理配置
5. **清晰的接口**: 通过 `__init__.py` 提供明确的导出接口

## 📝 最佳实践

1. **使用类级别配置**: 为常用配置定义客户端子类
2. **合理使用缓存**: 对幂等的 GET 请求启用缓存
3. **异步处理批量请求**: 使用 `is_async=True` 提升性能
4. **自定义解析器**: 根据 API 特点实现专用解析器
5. **错误处理**: 捕获并处理特定的异常类型

## 🔄 版本历史

- **v1.0.0**: 初始版本，重构优化模块结构

## 👤 作者

HACK-WU

## 📄 许可证

MIT License
