# HTTP Client 模块

一个功能强大、高度可扩展的 HTTP 客户端框架，提供统一的 API 请求接口和完善的可插拔组件体系。

## 特性

- 🚀 **高性能并发**：支持线程池和 Celery 分布式任务队列
- 🔌 **可插拔架构**：解析器、格式化器、验证器、执行器均可自定义
- 💾 **多级缓存**：内存缓存（LRU）和 Redis 分布式缓存
- 🔒 **安全可靠**：自动重试、超时控制、敏感信息脱敏
- 🎯 **DRF 集成**：原生支持 Django REST Framework Serializer 验证
- 🪝 **钩子机制**：请求前后可注入自定义逻辑
- 📝 **完善日志**：详细的请求追踪和错误记录

## 目录

- [快速开始](#快速开始)
- [基础使用](#基础使用)
  - [定义客户端](#定义客户端)
  - [发送请求](#发送请求)
  - [批量请求](#批量请求)
- [高级功能](#高级功能)
  - [请求参数验证](#请求参数验证)
  - [响应验证](#响应验证)
  - [缓存机制](#缓存机制)
  - [异步执行器](#异步执行器)
  - [钩子机制](#钩子机制)
- [组件详解](#组件详解)
  - [响应解析器](#响应解析器)
  - [响应格式化器](#响应格式化器)
  - [认证机制](#认证机制)
- [最佳实践](#最佳实践)
- [API 参考](#api-参考)

## 快速开始

### 安装依赖

```bash
uv sync
```

### 最简示例

```python
from http_client import BaseClient, JSONResponseParser

class GitHubClient(BaseClient):
    base_url = "https://api.github.com"
    endpoint = "/users/{username}"
    response_parser_class = JSONResponseParser

# 方式1: 实例化使用
client = GitHubClient()
result = client.request({"username": "octocat"})
print(result["data"])  # 用户信息

# 方式2: 类方法直接调用（自动管理生命周期）
result = GitHubClient.request({"username": "octocat"})
```

## 基础使用

### 定义客户端

继承 `BaseClient` 并配置类属性：

```python
from http_client import BaseClient, JSONResponseParser

class MyAPIClient(BaseClient):
    # 必填：API 基础 URL
    base_url = "https://api.example.com"
    
    # 可选：默认端点路径
    endpoint = "/api/v1/users"
    
    # 可选：默认 HTTP 方法
    method = "GET"
    
    # 可选：响应解析器
    response_parser_class = JSONResponseParser
    
    # 可选：默认请求头
    default_headers = {
        "User-Agent": "MyApp/1.0",
        "Accept": "application/json"
    }
    
    # 可选：超时设置（秒）
    default_timeout = 30
    
    # 可选：启用重试机制
    enable_retry = True
    max_retries = 3
```

### 发送请求

#### 1. GET 请求

```python
class UserAPIClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "GET"

client = UserAPIClient()

# 查询参数会自动添加到 URL
result = client.request({"page": 1, "limit": 10})
# 实际请求: GET https://api.example.com/users?page=1&limit=10
```

#### 2. POST 请求

```python
class CreateUserClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"

client = CreateUserClient()

# 数据会自动以 JSON 格式发送
result = client.request({
    "username": "john",
    "email": "john@example.com"
})
```

#### 3. 动态 Endpoint

支持在 endpoint 中使用 `{变量名}` 占位符：

```python
class UserDetailClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}/posts/{post_id}"
    method = "GET"

client = UserDetailClient()
result = client.request({
    "user_id": 123,
    "post_id": 456,
    "include_comments": True  # 剩余参数作为查询参数
})
# 实际请求: GET https://api.example.com/users/123/posts/456?include_comments=True
```

### 批量请求

#### 1. 并发批量请求（使用线程池）

```python
class PostsClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/posts"
    method = "GET"

client = PostsClient()

# 自动并发执行多个请求
results = client.request([
    {"post_id": 1},
    {"post_id": 2},
    {"post_id": 3},
], is_async=True)

# 结果按原始顺序返回
for result in results:
    if result["result"]:
        print(result["data"])
```

#### 2. 分布式批量请求（使用 Celery）

```python
from http_client import BaseClient
from http_client.async_executor import CeleryAsyncExecutor

class PostsClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/posts"
    
    # 配置 Celery 执行器
    async_executor_class = CeleryAsyncExecutor

client = PostsClient()

# 请求会分发到 Celery worker 执行
results = client.request([
    {"post_id": i} for i in range(100)
], is_async=True)
```

## 高级功能

### 请求参数验证

#### 方式1: 使用 DRF Serializer

```python
from http_client import DRFClient
from rest_framework import serializers

class UserCreateClient(DRFClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    method = "POST"
    
    class RequestSerializer(serializers.Serializer):
        username = serializers.CharField(max_length=50, required=True)
        email = serializers.EmailField(required=True)
        age = serializers.IntegerField(min_value=1, max_value=120)
        role = serializers.ChoiceField(choices=["admin", "user"])

client = UserCreateClient()

# 验证通过
result = client.request({
    "username": "john",
    "email": "john@example.com",
    "age": 25,
    "role": "user"
})

# 验证失败会抛出 APIClientRequestValidationError
try:
    result = client.request({"username": "john"})  # 缺少 email
except Exception as e:
    print(e)  # Request validation failed: {'email': ['This field is required.']}
```

#### 方式2: 自定义验证器

```python
from http_client import BaseClient
from http_client.serializer import BaseRequestSerializer
from http_client.exceptions import APIClientRequestValidationError

class UserRequestSerializer(BaseRequestSerializer):
    def validate(self, data):
        errors = {}
        
        if not data.get("username"):
            errors["username"] = ["用户名不能为空"]
        
        if data.get("age") and data["age"] < 18:
            errors["age"] = ["用户必须年满18岁"]
        
        if errors:
            raise APIClientRequestValidationError(
                f"请求参数验证失败: {errors}", 
                errors=errors
            )
        
        return data

class UserClient(BaseClient):
    base_url = "https://api.example.com"
    request_serializer_class = UserRequestSerializer
```

### 响应验证

#### 状态码验证

```python
from http_client import BaseClient
from http_client.validator import StatusCodeValidator

class StrictAPIClient(BaseClient):
    base_url = "https://api.example.com"
    
    # 只允许 200, 201, 204 状态码
    response_validator_class = StatusCodeValidator(
        allowed_codes=[200, 201, 204],
        strict_mode=True
    )

client = StrictAPIClient()

# 如果返回 404 或其他状态码，会抛出 APIClientResponseValidationError
```

#### 自定义响应验证

```python
from http_client.validator import BaseResponseValidator
from http_client.exceptions import APIClientResponseValidationError

class BusinessValidator(BaseResponseValidator):
    def validate(self, client_instance, response, parsed_data):
        # 在解析后验证业务逻辑
        if parsed_data is not None:
            if parsed_data.get("error_code") != 0:
                raise APIClientResponseValidationError(
                    f"业务错误: {parsed_data.get('error_msg')}",
                    response=response,
                    validation_result=parsed_data
                )

class MyClient(BaseClient):
    base_url = "https://api.example.com"
    response_validator_class = BusinessValidator
```

### 缓存机制

#### 1. 内存缓存（LRU）

```python
from http_client.cache import CacheClient, InMemoryCacheBackend

class CachedPostsClient(CacheClient):
    base_url = "https://api.example.com"
    endpoint = "/posts"
    method = "GET"
    
    # 配置内存缓存
    cache_backend_class = InMemoryCacheBackend
    default_cache_expire = 300  # 缓存5分钟

client = CachedPostsClient()

# 第一次请求：从服务器获取
result1 = client.request({"post_id": 1})

# 第二次请求：从缓存获取（速度快）
result2 = client.request({"post_id": 1})

# 手动清除缓存
client.clear_cache()
```

#### 2. Redis 分布式缓存

```python
from http_client.cache import CacheClient, RedisCacheBackend

class DistributedCachedClient(CacheClient):
    base_url = "https://api.example.com"
    endpoint = "/users"
    
    # 配置 Redis 缓存
    cache_backend_class = RedisCacheBackend
    cache_backend_kwargs = {
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "password": "your_password",
        "key_prefix": "myapp_cache"  # 键前缀，避免冲突
    }
    default_cache_expire = 600

client = DistributedCachedClient()
result = client.request({"user_id": 1})
```

#### 3. 用户级缓存隔离

```python
from http_client.cache import CacheClient, InMemoryCacheBackend

class UserCachedClient(CacheClient):
    base_url = "https://api.example.com"
    cache_backend_class = InMemoryCacheBackend
    is_user_specific = True  # 启用用户级缓存

# 不同用户的缓存相互隔离
user1_client = UserCachedClient(user_identifier="user_123")
user2_client = UserCachedClient(user_identifier="user_456")

user1_client.request({"action": "profile"})  # 缓存在 user_123 命名空间
user2_client.request({"action": "profile"})  # 缓存在 user_456 命名空间
```

#### 4. 自定义缓存键

```python
from http_client.cache import CacheClient

class CustomCacheClient(CacheClient):
    base_url = "https://api.example.com"
    
    # 方式1: 使用前缀字符串
    cache_key_prefix = "myapp:api"
    
    # 方式2: 使用回调函数
    @staticmethod
    def cache_key_prefix():
        # 动态生成前缀
        return "dynamic_prefix"
```

#### 5. 批量请求缓存

```python
from http_client.cache import CacheClient, InMemoryCacheBackend

class BatchCachedClient(CacheClient):
    base_url = "https://api.example.com"
    cache_backend_class = InMemoryCacheBackend

client = BatchCachedClient()

# 第一次批量请求：全部从服务器获取
results1 = client.request([
    {"page": 1},
    {"page": 2},
    {"page": 3}
], is_async=True)

# 第二次批量请求：部分命中缓存，部分发送请求
results2 = client.request([
    {"page": 1},  # 缓存命中
    {"page": 2},  # 缓存命中
    {"page": 4}   # 新请求
], is_async=True)
# 只会发送 page=4 的请求，顺序保持不变
```

### 异步执行器

#### 1. 线程池执行器（默认）

```python
from http_client import BaseClient
from http_client.async_executor import ThreadPoolAsyncExecutor

class ConcurrentClient(BaseClient):
    base_url = "https://api.example.com"
    
    # 配置线程池
    max_workers = 10  # 最多10个并发线程
    async_executor_class = ThreadPoolAsyncExecutor

client = ConcurrentClient()

# 并发执行100个请求，最多10个线程同时运行
results = client.request([
    {"item_id": i} for i in range(100)
], is_async=True)
```

#### 2. Celery 分布式执行器

```python
from http_client.async_executor import CeleryAsyncExecutor
from celery import Celery

# 配置 Celery
celery_app = Celery(
    "myapp",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1"
)

class DistributedClient(BaseClient):
    base_url = "https://api.example.com"
    
    # 配置 Celery 执行器
    async_executor_class = CeleryAsyncExecutor

# 方式1: 使用默认 Celery 配置
client1 = DistributedClient()

# 方式2: 使用自定义 Celery 实例
client2 = DistributedClient(
    executor=CeleryAsyncExecutor(
        celery_app=celery_app,
        wait_timeout=60,  # 等待60秒
        revoke_on_timeout=True  # 超时自动撤销任务
    )
)

results = client2.request([
    {"task": i} for i in range(1000)
], is_async=True)
```

### 钩子机制

#### 注册全局钩子

```python
from http_client import BaseClient
import time

class MyClient(BaseClient):
    base_url = "https://api.example.com"

client = MyClient()

# 请求前钩子：添加签名
def add_signature(client, request_id, request_data):
    request_data["timestamp"] = int(time.time())
    request_data["signature"] = calculate_signature(request_data)
    return request_data

client.register_hook("before_request", add_signature)

# 请求后钩子：记录响应时间
def log_response_time(client, request_id, response):
    elapsed = response.elapsed.total_seconds()
    print(f"请求 {request_id} 耗时: {elapsed:.2f}秒")
    return response

client.register_hook("after_request", log_response_time)

# 错误钩子：发送告警
def send_alert(client, request_id, error):
    print(f"请求失败: {request_id}, 错误: {error}")

client.register_hook("on_request_error", send_alert)

result = client.request({"action": "test"})
```

#### 继承重写钩子方法

```python
class CustomClient(BaseClient):
    base_url = "https://api.example.com"
    
    def before_request(self, request_id, request_data):
        # 添加自定义逻辑
        print(f"准备发送请求: {request_id}")
        request_data = super().before_request(request_id, request_data)
        
        # 添加通用参数
        request_data["app_version"] = "1.0.0"
        return request_data
    
    def after_request(self, request_id, response):
        response = super().after_request(request_id, response)
        
        # 记录日志
        print(f"收到响应: {request_id}, 状态码: {response.status_code}")
        return response
    
    def on_request_error(self, request_id, error):
        super().on_request_error(request_id, error)
        
        # 发送告警
        send_alert_to_monitoring(request_id, str(error))
```

## 组件详解

### 响应解析器

#### 1. JSONResponseParser（默认）

解析 JSON 响应：

```python
from http_client import BaseClient, JSONResponseParser

class APIClient(BaseClient):
    base_url = "https://api.example.com"
    response_parser_class = JSONResponseParser

client = APIClient()
result = client.request()
# result["data"] 自动解析为 Python 字典或列表
```

#### 2. ContentResponseParser

获取响应文本内容：

```python
from http_client import ContentResponseParser

class HTMLClient(BaseClient):
    base_url = "https://example.com"
    response_parser_class = ContentResponseParser

client = HTMLClient()
result = client.request()
# result["data"] 包含 HTML 文本
```

#### 3. RawResponseParser

获取原始响应对象：

```python
from http_client import RawResponseParser

class RawClient(BaseClient):
    base_url = "https://api.example.com"
    response_parser_class = RawResponseParser

client = RawClient()
result = client.request()
# result["data"] 是 requests.Response 对象
response = result["data"]
print(response.status_code)
print(response.headers)
```

#### 4. FileWriteResponseParser

下载文件：

```python
from http_client import FileWriteResponseParser

class FileDownloadClient(BaseClient):
    base_url = "https://example.com"
    endpoint = "/files/{file_id}"
    response_parser_class = FileWriteResponseParser

client = FileDownloadClient()

# 下载文件到指定路径
result = client.request({
    "file_id": "123",
    "_file_path": "/tmp/downloaded_file.pdf"
})

if result["result"]:
    print(f"文件已保存到: {result['data']['file_path']}")
```

#### 5. StreamResponseParser

流式下载大文件：

```python
from http_client import StreamResponseParser

class StreamClient(BaseClient):
    base_url = "https://example.com"
    response_parser_class = StreamResponseParser

client = StreamClient()
result = client.request()

# result["data"] 是生成器，可逐块读取
for chunk in result["data"]:
    process_chunk(chunk)
```

#### 6. 自定义解析器

```python
from http_client.parser import BaseResponseParser
import xml.etree.ElementTree as ET

class XMLResponseParser(BaseResponseParser):
    def parse(self, response, request_id):
        try:
            root = ET.fromstring(response.content)
            return self._xml_to_dict(root)
        except Exception as e:
            raise Exception(f"XML 解析失败: {e}")
    
    def _xml_to_dict(self, element):
        # XML 转字典逻辑
        return {element.tag: element.text}

class XMLClient(BaseClient):
    base_url = "https://api.example.com"
    response_parser_class = XMLResponseParser
```

### 响应格式化器

所有响应统一格式化为：

```python
{
    "result": True,         # 请求是否成功
    "code": 200,           # HTTP 状态码或错误代码
    "message": "OK",       # 响应消息
    "data": {...}          # 解析后的数据
}
```

#### 自定义格式化器

```python
from http_client.formatter import BaseResponseFormatter

class CustomFormatter(BaseResponseFormatter):
    def format(self, formated_response, parsed_data, request_id, 
               request_data, response_or_exception, parse_error, 
               base_client_instance):
        # 添加自定义字段
        formated_response["request_id"] = request_id
        formated_response["timestamp"] = time.time()
        
        # 修改数据结构
        if formated_response["result"]:
            formated_response["status"] = "success"
        else:
            formated_response["status"] = "failed"
        
        return formated_response

class MyClient(BaseClient):
    base_url = "https://api.example.com"
    response_formatter_class = CustomFormatter
```

### 认证机制

#### 1. Bearer Token 认证

```python
from requests.auth import AuthBase

class BearerAuth(AuthBase):
    def __init__(self, token):
        self.token = token
    
    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

class SecureClient(BaseClient):
    base_url = "https://api.example.com"
    authentication_class = BearerAuth

client = SecureClient(authentication=BearerAuth("your_token_here"))
```

#### 2. API Key 认证

```python
class APIKeyAuth(AuthBase):
    def __init__(self, api_key):
        self.api_key = api_key
    
    def __call__(self, request):
        request.headers["X-API-Key"] = self.api_key
        return request

client = MyClient(authentication=APIKeyAuth("your_api_key"))
```

#### 3. Basic Auth

```python
from requests.auth import HTTPBasicAuth

class BasicAuthClient(BaseClient):
    base_url = "https://api.example.com"

client = BasicAuthClient(
    authentication=HTTPBasicAuth("username", "password")
)
```

## 最佳实践

### 1. 使用上下文管理器

```python
# 推荐：自动管理 Session 生命周期
with MyAPIClient() as client:
    result = client.request({"action": "test"})
# Session 自动关闭

# 或使用类方法（自动管理）
result = MyAPIClient.request({"action": "test"})
```

### 2. 错误处理

```python
from http_client.exceptions import (
    APIClientError,
    APIClientHTTPError,
    APIClientTimeoutError,
    APIClientNetworkError,
    APIClientRequestValidationError,
)

try:
    result = client.request({"action": "test"})
    
    if result["result"]:
        # 处理成功响应
        data = result["data"]
    else:
        # 处理业务错误
        print(f"业务错误: {result['message']}")
        
except APIClientRequestValidationError as e:
    # 请求参数验证失败
    print(f"参数错误: {e.errors}")
    
except APIClientTimeoutError:
    # 请求超时
    print("请求超时，请稍后重试")
    
except APIClientHTTPError as e:
    # HTTP 错误（4xx, 5xx）
    print(f"HTTP 错误: {e.status_code}")
    
except APIClientNetworkError:
    # 网络连接错误
    print("网络连接失败")
    
except APIClientError as e:
    # 其他客户端错误
    print(f"请求失败: {e}")
```

### 3. 生产环境配置

```python
class ProductionClient(BaseClient):
    base_url = "https://api.production.com"
    
    # 启用重试
    enable_retry = True
    max_retries = 3
    retry_config = {
        "total": 3,
        "backoff_factor": 0.5,  # 指数退避
        "status_forcelist": [500, 502, 503, 504],
    }
    
    # 连接池优化
    pool_config = {
        "pool_connections": 10,
        "pool_maxsize": 20,
    }
    
    # 超时控制
    default_timeout = 30
    
    # 启用 SSL 验证
    verify = True
    
    # 敏感信息脱敏
    enable_sanitization = True
    sensitive_headers = {"Authorization", "X-API-Key"}
    sensitive_params = {"token", "password"}
```

### 4. 批量请求优化

```python
from http_client.cache import CacheClient, RedisCacheBackend
from http_client.async_executor import ThreadPoolAsyncExecutor

# 使用缓存 + 异步执行
class OptimizedClient(CacheClient):
    base_url = "https://api.example.com"
    
    # 缓存配置
    cache_backend_class = RedisCacheBackend
    default_cache_expire = 300
    
    # 并发配置
    max_workers = 20
    async_executor_class = ThreadPoolAsyncExecutor

client = OptimizedClient()

# 大批量请求：自动去重、缓存复用、并发执行
results = client.request([
    {"item_id": i} for i in range(1000)
], is_async=True)
```

## API 参考

### BaseClient 类属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `base_url` | str | 必填 | API 基础 URL |
| `endpoint` | str | "" | 默认端点路径 |
| `method` | str | "GET" | 默认 HTTP 方法 |
| `default_timeout` | int | 10 | 超时时间（秒） |
| `enable_retry` | bool | False | 是否启用重试 |
| `max_retries` | int | 3 | 最大重试次数 |
| `verify` | bool | True | SSL 证书验证 |
| `default_headers` | dict | {} | 默认请求头 |
| `max_workers` | int | 5 | 并发线程数 |

### BaseClient 方法

#### request()

```python
def request(
    request_data: dict | list[dict] = None,
    is_async: bool = False
) -> dict | list[dict]
```

发送 HTTP 请求。

**参数:**
- `request_data`: 请求配置字典或列表
- `is_async`: 是否使用异步执行器并发执行

**返回:**
- 单个请求：返回响应字典
- 批量请求：返回响应字典列表

#### register_hook()

```python
def register_hook(hook_name: str, callback: callable) -> None
```

注册钩子函数。

**参数:**
- `hook_name`: 钩子名称（"before_request", "after_request", "on_request_error"）
- `callback`: 回调函数

### CacheClient 类属性

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_backend_class` | class | InMemoryCacheBackend | 缓存后端类 |
| `default_cache_expire` | int | 300 | 缓存过期时间（秒） |
| `cacheable_methods` | set | {"GET", "HEAD"} | 可缓存的 HTTP 方法 |
| `is_user_specific` | bool | False | 是否启用用户级缓存 |
| `cache_key_prefix` | str/callable | "" | 缓存键前缀 |
| `cache_backend_kwargs` | dict | {} | 缓存后端初始化参数 |

### CacheClient 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `cache_expire` | int | None | 实例级缓存过期时间 |
| `user_identifier` | str | None | 用户标识（启用 is_user_specific 时必填） |
| `should_cache_response_func` | callable | None | 自定义响应缓存判断函数 |

### CacheClient 方法

#### clear_cache()

```python
def clear_cache() -> None
```

清除所有缓存。

#### delete_cache()

```python
def delete_cache(request_data: dict) -> None
```

删除特定请求的缓存。

## 异常类型

| 异常 | 说明 |
|------|------|
| `APIClientError` | 基础异常类 |
| `APIClientHTTPError` | HTTP 错误（4xx, 5xx） |
| `APIClientTimeoutError` | 请求超时 |
| `APIClientNetworkError` | 网络连接错误 |
| `APIClientValidationError` | 验证错误 |
| `APIClientRequestValidationError` | 请求参数验证失败 |
| `APIClientResponseValidationError` | 响应验证失败 |

## 常见问题

### Q: 如何禁用 SSL 证书验证？

```python
class InsecureClient(BaseClient):
    base_url = "https://self-signed.example.com"
    verify = False  # 仅用于开发环境
```

### Q: 如何设置代理？

```python
client = MyClient(
    proxies={
        "http": "http://proxy.example.com:8080",
        "https": "https://proxy.example.com:8080"
    }
)
```

### Q: 如何处理大文件上传？

```python
class FileUploadClient(BaseClient):
    base_url = "https://api.example.com"
    endpoint = "/upload"
    method = "POST"

client = FileUploadClient()

with open("large_file.zip", "rb") as f:
    # 使用 files 参数上传
    result = client.request({}, files={"file": f})
```

### Q: 批量请求如何保证顺序？

批量请求的结果始终按照输入顺序返回，即使内部并发执行：

```python
results = client.request([
    {"id": 1},
    {"id": 2},
    {"id": 3}
], is_async=True)

# results[0] 对应 id=1
# results[1] 对应 id=2
# results[2] 对应 id=3
```

### Q: 如何动态切换缓存后端？

```python
# 开发环境使用内存缓存
dev_client = MyClient(cache_backend=InMemoryCacheBackend(maxsize=100))

# 生产环境使用 Redis
prod_client = MyClient(
    cache_backend=RedisCacheBackend(
        host="redis.example.com",
        password="secret"
    )
)
```

## 许可证

本模块遵循项目主许可证。

## 作者

HACK-WU

## 更新日志

### v1.0.0
- 初始版本发布
- 支持基础 HTTP 请求功能
- 集成 DRF Serializer 验证
- 提供内存和 Redis 缓存
- 支持线程池和 Celery 异步执行
