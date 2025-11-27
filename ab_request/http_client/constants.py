"""
HTTP 客户端常量配置模块

定义客户端使用的常量、默认配置等
"""

# HTTP 方法常量
HTTP_METHOD_GET = "GET"
HTTP_METHOD_POST = "POST"
HTTP_METHOD_PUT = "PUT"
HTTP_METHOD_DELETE = "DELETE"
HTTP_METHOD_PATCH = "PATCH"
HTTP_METHOD_HEAD = "HEAD"
HTTP_METHOD_OPTIONS = "OPTIONS"
HTTP_METHOD_TRACE = "TRACE"

# 可缓存的 HTTP 方法集合
CACHEABLE_METHODS = {HTTP_METHOD_GET, HTTP_METHOD_HEAD}

# 默认配置
DEFAULT_TIMEOUT = 30  # 默认超时时间（秒）
DEFAULT_RETRIES = 3  # 默认重试次数
DEFAULT_MAX_WORKERS = 10  # 默认最大工作线程数
DEFAULT_CACHE_EXPIRE = 300  # 默认缓存过期时间（秒）
DEFAULT_CACHE_MAXSIZE = 128  # 默认内存缓存最大条目数

# 重试策略配置
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]  # 需要重试的 HTTP 状态码
RETRY_BACKOFF_FACTOR = 0.5  # 重试退避因子
RETRY_ALLOWED_METHODS = [
    HTTP_METHOD_HEAD,
    HTTP_METHOD_GET,
    HTTP_METHOD_PUT,
    HTTP_METHOD_DELETE,
    HTTP_METHOD_OPTIONS,
    HTTP_METHOD_TRACE,
    HTTP_METHOD_POST,
]

# 连接池配置
POOL_CONNECTIONS = 100  # 连接池大小
POOL_MAXSIZE = 100  # 连接池最大连接数

# 默认重试策略和连接池配置字典
DEFAULT_RETRY_CONFIG = {
    "total": DEFAULT_RETRIES,  # 重试总次数
    "backoff_factor": RETRY_BACKOFF_FACTOR,  # 重试退避因子
    "status_forcelist": RETRY_STATUS_FORCELIST,  # 需要重试的状态码列表
    "allowed_methods": RETRY_ALLOWED_METHODS,  # 允许重试的HTTP方法
    "raise_on_status": False,  # 不在重试时抛出状态异常
}

DEFAULT_POOL_CONFIG = {
    "pool_connections": POOL_CONNECTIONS,  # 连接池大小
    "pool_maxsize": POOL_MAXSIZE,  # 连接池最大连接数
}

# 文件下载配置
DEFAULT_DOWNLOAD_PATH = "./downloads"  # 默认下载路径
DEFAULT_CHUNK_SIZE = 8192  # 默认分块大小（字节）
DEFAULT_FILENAME = "downloaded_file"  # 默认文件名

# Redis 配置
REDIS_DEFAULT_HOST = "localhost"
REDIS_DEFAULT_PORT = 6379
REDIS_DEFAULT_DB = 0
REDIS_MAX_CONNECTIONS = 10

# 日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 响应格式化器状态码
RESPONSE_CODE_NON_HTTP_ERROR = -1  # 非HTTP错误代码（如网络超时、连接失败等）
RESPONSE_CODE_UNEXPECTED_TYPE = -2  # 未预期的响应/异常类型错误代码
RESPONSE_CODE_FORMATTING_ERROR = -3  # 响应格式化失败错误代码
