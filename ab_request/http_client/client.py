"""
HTTP 客户端核心模块

提供灵活、可扩展的 HTTP 客户端基类，支持：
- 自定义认证机制
- 多种响应解析器和格式化器
- 同步/异步请求执行
- 自动重试和连接池管理
- 完善的错误处理

作者: HACK-WU
创建时间: 2025/7/24 23:36
"""

import logging
import uuid
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase
from urllib3.util.retry import Retry

from ab_request.http_client.constants import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_POOL_CONFIG,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_CONFIG,
    DEFAULT_TIMEOUT,
    LOG_FORMAT,
    RESPONSE_CODE_FORMATTING_ERROR,
    RESPONSE_CODE_NON_HTTP_ERROR,
)
from ab_request.http_client.exceptions import (
    APIClientError,
    APIClientHTTPError,
    APIClientNetworkError,
    APIClientTimeoutError,
    APIClientValidationError,
)
from ab_request.http_client.async_executor import BaseAsyncExecutor, ThreadPoolAsyncExecutor
from ab_request.http_client.formatter import BaseResponseFormatter, DefaultResponseFormatter
from ab_request.http_client.parser import (
    BaseResponseParser,
    FileWriteResponseParser,
    JSONResponseParser,
    RawResponseParser,
)

# 配置日志
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


class _RequestMethodDescriptor:
    """
    自定义描述符：实现 request 方法的"重载"效果

    该描述符允许 request 方法根据调用方式自动切换行为：
    - 实例调用（client.request()）：执行实例方法逻辑
    - 类调用（MyClient.request()）：自动创建临时实例并执行

    实现原理:
        1. 通过 __get__ 方法拦截属性访问
        2. 判断是从实例访问还是从类访问
        3. 返回不同的可调用对象
    """

    def __init__(self, instance_method):
        """
        初始化描述符

        参数:
            instance_method: 原始的实例方法
        """
        self.instance_method = instance_method

    def __get__(self, instance, owner):
        """
        描述符协议：拦截属性访问

        参数:
            instance: 实例对象（如果是实例调用）或 None（如果是类调用）
            owner: 类对象

        返回:
            可调用对象（绑定方法或包装函数）

        执行步骤:
            1. 判断是实例调用还是类调用
            2. 实例调用：返回绑定的实例方法
            3. 类调用：返回包装函数，自动创建临时实例
        """
        # 情况1: 实例调用（client.request()）
        if instance is not None:
            # 返回绑定到实例的方法
            return self.instance_method.__get__(instance, owner)

        # 情况2: 类调用（MyClient.request()）
        # 返回一个包装函数，自动创建临时实例并执行
        def class_method_wrapper(
            request_data: dict[str, Any] | list[dict[str, Any]] | None = None,
            is_async: bool = False,
            **client_kwargs,
        ) -> dict[str, Any] | list[dict[str, Any] | Exception]:
            """
            类方法调用的包装函数

            参数:
                request_data: 请求配置字典或配置列表
                is_async: 是否使用异步执行器并发执行
                **client_kwargs: 传递给客户端构造函数的额外参数

            返回:
                格式化后的响应字典或响应字典列表

            执行步骤:
                1. 使用传入的参数创建临时客户端实例
                2. 调用实例的 request 方法执行请求
                3. 自动关闭会话并清理资源
                4. 返回请求结果
            """
            # 创建临时实例并自动管理生命周期
            with owner(**client_kwargs) as temp_instance:
                return temp_instance.request(request_data=request_data, is_async=is_async)

        return class_method_wrapper

    def __set_name__(self, owner, name):
        """
        描述符协议：记录属性名称

        参数:
            owner: 类对象
            name: 属性名称
        """
        self.name = name


class BaseClient:
    """
    API 客户端基类

    提供统一的 HTTP 请求接口和配置管理，支持高度定制化

    类属性:
        base_url: API 基础 URL（必须在子类中设置）
        endpoint: 默认端点路径
        method: 默认 HTTP 方法
        default_timeout: 默认超时时间（秒）
        default_retries: 默认重试次数
        default_headers: 默认请求头
        max_workers: 异步执行时的最大工作线程数
        retry_config: 重试策略配置字典
        pool_config: 连接池配置字典
        verify: SSL 证书验证开关（默认 False，不验证证书）
        authentication_class: 认证类或实例
        executor_class: 异步执行器类或实例
        response_parser_class: 响应数据解析器类或实例
        response_formatter_class: 响应格式化器类或实例
    """

    # ========== 基础配置 ==========
    # API 基础 URL，必须在子类中设置，所有请求将基于此 URL 构建完整路径
    base_url: str = ""

    # 默认端点路径，可在请求时覆盖，用于构建完整的请求 URL
    endpoint: str = ""

    # 默认 HTTP 请求方法，支持 GET/POST/PUT/DELETE/PATCH 等标准方法
    method: str = "GET"

    # SSL 证书验证开关，False 表示不验证证书（适用于开发环境或自签名证书）
    verify: bool = False

    # ========== 超时和重试配置 ==========
    # 默认请求超时时间（秒），防止请求无限期挂起
    default_timeout: int = DEFAULT_TIMEOUT

    # 默认失败重试次数，0 表示不重试，适用于幂等性请求
    default_retries: int = DEFAULT_RETRIES

    # 重试策略配置字典，包含重试次数、退避因子、状态码列表等详细配置
    # 可在子类或实例化时覆盖，支持精细化控制重试行为
    # 配置项: total(重试次数), backoff_factor(退避因子), status_forcelist(重试状态码),
    #         allowed_methods(允许重试的方法), raise_on_status(是否抛出状态异常)
    retry_config: dict[str, Any] = DEFAULT_RETRY_CONFIG

    # 连接池配置字典，控制 HTTP 连接池的大小和行为
    # 配置项: pool_connections(连接池大小), pool_maxsize(连接池最大连接数)
    # 合理配置可提升并发性能和连接复用效率
    pool_config: dict[str, Any] = DEFAULT_POOL_CONFIG

    # ========== 请求头和并发配置 ==========
    # 默认请求头字典，所有请求都会携带这些请求头（可在请求时合并或覆盖）
    # 常用于设置 Content-Type, Authorization, User-Agent 等通用头部
    default_headers: dict[str, str] = {}

    # 异步执行时的最大工作线程数，控制并发请求的线程池大小
    # 适用于批量请求场景，避免创建过多线程导致资源耗尽
    max_workers: int = DEFAULT_MAX_WORKERS

    # ========== 可插拔组件配置 ==========
    # 认证类或实例，用于处理请求认证逻辑（如 Bearer Token, Basic Auth 等）
    # 可传入 requests.auth.AuthBase 的子类或实例，None 表示无需认证
    authentication_class: type[AuthBase] | AuthBase | None = None

    # 异步执行器类或实例，用于处理批量异步请求的执行策略
    # 默认使用线程池执行器，可替换为进程池或协程执行器
    executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor | None = ThreadPoolAsyncExecutor

    # 响应数据解析器类或实例，用于解析 HTTP 响应体为 Python 对象
    # 默认使用 JSON 解析器，可替换为 XML、HTML 或自定义解析器
    response_parser_class: type[BaseResponseParser] | BaseResponseParser | None = JSONResponseParser

    # 响应格式化器类或实例，用于将响应统一格式化为标准结构
    # 默认格式化为 {result, code, message, data} 结构，便于统一处理
    response_formatter_class: type[BaseResponseFormatter] | BaseResponseFormatter | None = DefaultResponseFormatter

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
        verify: bool | None = None,
        retries: int | None = None,
        max_workers: int | None = None,
        retry_config: dict[str, Any] | None = None,
        pool_config: dict[str, Any] | None = None,
        authentication: AuthBase | type[AuthBase] | None = None,
        executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
        response_parser: BaseResponseParser | type[BaseResponseParser] | None = None,
        response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None = None,
        **kwargs,
    ):
        """
        初始化 API 客户端实例

        参数:
            default_headers: 默认请求头字典
            timeout: 请求超时时间（秒）
            retries: 失败重试次数
            max_workers: 异步执行的最大工作线程数
            retry_config: 重试策略配置字典（覆盖类级别配置）
            pool_config: 连接池配置字典（覆盖类级别配置）
            verify: SSL 证书验证开关（None 时使用类属性，默认 False）
            authentication: 认证类或实例
            executor: 异步执行器类或实例
            response_parser: 响应解析器类或实例
            response_formatter: 响应格式化器类或实例
            **kwargs: 其他传递给 requests 的参数

        执行步骤:
            1. 验证并规范化 base_url
            2. 解析并初始化认证、执行器、解析器、格式化器
            3. 合并请求头配置（类级别 + 实例级别）
            4. 合并重试策略和连接池配置
            5. 创建并配置 requests.Session 对象

        异常:
            APIClientValidationError: 当 base_url 未设置或配置无效时抛出
        """
        # ========== 步骤1: 验证并规范化 base_url ==========
        # 从类属性获取 base_url，并移除末尾的斜杠，确保 URL 格式统一
        self.base_url = getattr(self, "base_url", "").rstrip("/")
        # 验证 base_url 是否已设置，未设置则抛出异常（base_url 是必需的）
        if not self.base_url:
            raise APIClientValidationError("base_url must be provided as a class attribute.")

        # 保存类级别的默认端点和方法，用于后续请求时的默认值
        self._class_default_endpoint = getattr(self, "endpoint", "")
        self._class_default_method = getattr(self, "method", "GET").upper()

        # ========== 步骤2: 初始化实例级别的配置参数 ==========
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.retries = retries if retries is not None else self.default_retries
        self.verify = verify if verify is not None else self.verify
        if max_workers is not None:
            self.max_workers = max_workers

        # 合并重试策略配置：实例级别配置覆盖类级别配置
        self.retry_config = {**self.retry_config, **(retry_config or {})}
        # 如果实例化时指定了 retries，更新重试配置中的 total 字段
        if retries is not None:
            self.retry_config["total"] = retries

        # 合并连接池配置：实例级别配置覆盖类级别配置
        self.pool_config = {**self.pool_config, **(pool_config or {})}

        # ========== 步骤3: 解析并初始化各个组件实例 ==========
        self.auth_instance = self._resolve_authentication(authentication)

        # 解析异步执行器：用于并发请求的执行
        self.executor_instance = self._resolve_executor(executor)

        # 解析响应解析器：用于解析 HTTP 响应内容（如 JSON、XML 等）
        self.response_parser_instance = self._resolve_response_parser(response_parser)

        # 解析响应格式化器：用于格式化解析后的响应数据
        self.response_formatter_instance = self._resolve_response_formatter(response_formatter)

        # ========== 步骤4: 合并请求头配置 ==========
        # 合并顺序：类级别默认请求头 -> 实例级别请求头 -> kwargs 中的请求头
        # 后者会覆盖前者，实现灵活的请求头配置
        self.session_headers = {**self.default_headers, **(default_headers or {}), **kwargs.pop("headers", {})}

        # ========== 步骤5: 配置默认请求参数 ==========
        # 如果 kwargs 中没有显式设置 verify，则使用实例的 verify 属性
        # 这确保 SSL 验证配置能够传递到每个请求中
        if "verify" not in kwargs:
            kwargs["verify"] = self.verify
        # 保存所有额外的请求参数（如 proxies、cert 等），用于每次请求时合并
        self.default_request_kwargs = kwargs

        # ========== 步骤6: 创建并配置 requests.Session 对象 ==========
        # Session 对象用于连接池管理和持久化配置（如 cookies、认证等）
        self.session = self._create_session()

    def _resolve_authentication(self, authentication: AuthBase | type[AuthBase] | None) -> AuthBase | None:
        """
        解析认证配置，返回认证实例

        参数:
            authentication: 传入的认证配置（类或实例）

        返回:
            AuthBase 实例或 None

        执行步骤:
            1. 优先使用实例级别传入的 authentication 参数
            2. 如果未传入，则使用类级别的 authentication_class
            3. 如果是类，则实例化；如果是实例，则直接使用
            4. 验证配置的有效性

        异常:
            APIClientValidationError: 当认证配置类型无效时抛出
        """
        # 优先使用实例级别配置
        if authentication is not None:
            if isinstance(authentication, type) and issubclass(authentication, AuthBase):
                return authentication()
            elif isinstance(authentication, AuthBase):
                return authentication
            else:
                raise APIClientValidationError("authentication must be an AuthBase subclass or instance")

        # 使用类级别配置
        class_auth = getattr(self, "authentication_class", None)
        if class_auth is None:
            return None

        if isinstance(class_auth, type) and issubclass(class_auth, AuthBase):
            return class_auth()
        elif isinstance(class_auth, AuthBase):
            return class_auth
        else:
            raise APIClientValidationError("authentication_class must be an AuthBase subclass or instance")

    def _resolve_executor(self, executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None) -> BaseAsyncExecutor:
        """
        解析异步执行器配置，返回执行器实例

        参数:
            executor: 传入的执行器配置（类或实例）

        返回:
            BaseAsyncExecutor 实例

        执行步骤:
            1. 优先使用实例级别传入的 executor 参数
            2. 如果未传入，则使用类级别的 executor_class
            3. 如果都未配置，则使用默认的 ThreadPoolAsyncExecutor
            4. 如果是类，则实例化并传入 max_workers；如果是实例，则直接使用

        异常:
            APIClientValidationError: 当执行器配置类型无效时抛出
        """
        # 优先使用实例级别配置
        if executor is not None:
            if isinstance(executor, type) and issubclass(executor, BaseAsyncExecutor):
                return executor(max_workers=self.max_workers)
            elif isinstance(executor, BaseAsyncExecutor):
                return executor
            else:
                raise APIClientValidationError("executor must be a BaseAsyncExecutor subclass or instance")

        # 使用类级别配置
        class_executor = getattr(self, "executor_class", None)
        if class_executor is None:
            return ThreadPoolAsyncExecutor(max_workers=self.max_workers)

        if isinstance(class_executor, type) and issubclass(class_executor, BaseAsyncExecutor):
            return class_executor(max_workers=self.max_workers)
        elif isinstance(class_executor, BaseAsyncExecutor):
            return class_executor
        else:
            raise APIClientValidationError("executor_class must be a BaseAsyncExecutor subclass or instance")

    def _resolve_response_parser(
        self, response_parser: BaseResponseParser | type[BaseResponseParser] | None
    ) -> BaseResponseParser | None:
        """
        解析响应解析器配置，返回解析器实例

        参数:
            response_parser: 传入的解析器配置（类或实例）

        返回:
            BaseResponseParser 实例或 None

        执行步骤:
            1. 优先使用实例级别传入的 response_parser 参数
            2. 如果未传入，则使用类级别的 response_parser_class
            3. 如果是类，则尝试实例化；如果是实例，则直接使用
            4. 实例化失败时，降级使用 RawResponseParser
        """
        source = response_parser if response_parser is not None else getattr(self, "response_parser_class", None)
        if source is None:
            return None

        if isinstance(source, type) and issubclass(source, BaseResponseParser):
            try:
                return source()
            except Exception as e:
                logger.error(f"Failed to instantiate response parser class {source.__name__}: {e}")
                return RawResponseParser()
        elif isinstance(source, BaseResponseParser):
            return source
        else:
            logger.warning(f"Invalid response parser item: {source}. Using RawResponseParser.")
            return RawResponseParser()

    def _resolve_response_formatter(
        self, response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None
    ) -> BaseResponseFormatter | None:
        """
        解析响应格式化器配置，返回格式化器实例

        参数:
            response_formatter: 传入的格式化器配置（类或实例）

        返回:
            BaseResponseFormatter 实例或 None

        执行步骤:
            1. 优先使用实例级别传入的 response_formatter 参数
            2. 如果未传入，则使用类级别的 response_formatter_class
            3. 如果是类，则尝试实例化；如果是实例，则直接使用
            4. 实例化失败时，降级使用 DefaultResponseFormatter
        """
        source = (
            response_formatter if response_formatter is not None else getattr(self, "response_formatter_class", None)
        )
        if source is None:
            return None

        if isinstance(source, type) and issubclass(source, BaseResponseFormatter):
            try:
                return source()
            except Exception as e:
                logger.error(f"Failed to instantiate response formatter class {source.__name__}: {e}")
                return DefaultResponseFormatter()
        elif isinstance(source, BaseResponseFormatter):
            return source
        else:
            logger.warning(f"Invalid response formatter item: {source}. Using DefaultResponseFormatter.")
            return DefaultResponseFormatter()

    def _create_session(self) -> requests.Session:
        """
        创建并配置 requests.Session 对象

        返回:
            配置好的 requests.Session 实例

        执行步骤:
            1. 创建新的 Session 对象
            2. 设置默认请求头
            3. 配置认证信息（如果有）
            4. 配置重试策略和连接池（如果启用重试）
            5. 为 HTTP 和 HTTPS 协议挂载适配器
        """
        session = requests.Session()
        session.headers.update(self.session_headers)
        if self.auth_instance:
            session.auth = self.auth_instance

        if self.retries > 0:
            # 使用配置字典创建重试策略
            retry_strategy = Retry(**self.retry_config)
            # 使用配置字典创建 HTTP 适配器
            adapter = HTTPAdapter(max_retries=retry_strategy, **self.pool_config)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """
        执行单个 HTTP 请求，返回原始 Response 对象

        参数:
            request_id: 请求唯一标识符，用于日志追踪
            request_config: 请求配置字典，包含 method、endpoint、params 等

        返回:
            requests.Response 对象

        执行步骤:
            1. 从配置中提取 HTTP 方法和端点路径
            2. 构建完整的请求 URL
            3. 根据解析器配置决定是否使用流式响应
            4. 合并默认参数和请求特定参数
            5. 执行 HTTP 请求
            6. 检查响应状态码，抛出 HTTP 错误
            7. 捕获并转换各类异常为自定义异常

        异常:
            APIClientTimeoutError: 请求超时
            APIClientHTTPError: HTTP 错误响应（4xx, 5xx）
            APIClientNetworkError: 网络连接错误
        """
        # 步骤1: 解析请求方法和端点
        method = request_config.get("method", self._class_default_method).upper()
        endpoint = request_config.get("endpoint", self._class_default_endpoint)
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url

        # 步骤2: 确定是否需要流式响应
        stream_flag = False
        # 如果配置了响应解析器，检查解析器是否需要流式响应（如文件下载场景）
        if self.response_parser_instance:
            stream_flag = getattr(self.response_parser_instance, "is_stream", False)

        # 步骤3: 构建请求参数字典
        request_kwargs = {
            **self.default_request_kwargs,
            "stream": stream_flag,
            **{k: v for k, v in request_config.items() if k not in ("method", "endpoint")},
        }

        # 步骤4: 记录请求开始日志
        # INFO 级别：记录请求的基本信息（方法和 URL），生产环境可见
        logger.info(f"[{request_id}] Starting {method} request to {url}")

        # DEBUG 级别：记录完整的请求参数（包含 headers、params 等），仅调试时可见
        logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")

        try:
            response = self.session.request(method=method, url=url, timeout=self.timeout, **request_kwargs)
            logger.info(f"[{request_id}] Received {response.status_code} response")
            logger.debug(f"[{request_id}] Response headers: {response.headers}")
            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as original_exception:
            # 情况1: 超时异常
            if isinstance(original_exception, requests.exceptions.Timeout):
                converted_exception = APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s")

            # 情况2: HTTP 错误响应（4xx/5xx 状态码）
            elif isinstance(original_exception, requests.exceptions.HTTPError):
                # 提取状态码和错误原因
                status_code = original_exception.response.status_code if original_exception.response else 0
                converted_exception = APIClientHTTPError(
                    f"HTTP {status_code}: "
                    f"{original_exception.response.reason if original_exception.response else 'No response'}",
                    response=original_exception.response,
                )

            # 情况3: 其他网络异常（连接失败、DNS 解析失败等）
            else:
                converted_exception = APIClientNetworkError(f"Request to {url} failed: {original_exception}")

            # 步骤10: 记录错误日志并抛出转换后的异常
            # ERROR 级别：记录请求失败信息，生产环境可见
            logger.error(f"[{request_id}] Request failed: {converted_exception}")
            raise converted_exception

    def _make_request_and_format(self, request_id: str, request_config: dict[str, Any]) -> dict[str, Any]:
        """
        执行请求、解析响应并格式化结果的完整流程

        参数:
            request_id: 请求唯一标识符
            request_config: 请求配置字典

        返回:
            格式化后的响应字典，包含 result、code、message、data 字段

        执行步骤:
            1. 为 FileWriteResponseParser 设置文件名（如果需要）
            2. 执行 HTTP 请求，捕获响应或异常
            3. 解析响应数据（如果请求成功且配置了解析器）
            4. 清理临时属性（finally 块）
            5. 使用格式化器格式化响应或异常
            6. 处理格式化失败的情况，返回降级响应
        """
        # 步骤1: 为 FileWriteResponseParser 传递文件名
        if self.response_parser_instance and isinstance(self.response_parser_instance, FileWriteResponseParser):
            filename_from_config = request_config.get("filename")
            if filename_from_config:
                self.response_parser_instance._current_filename = filename_from_config

        # 步骤2: 执行请求并捕获响应或异常
        parsed_data: Any = None
        parse_error: Exception | None = None

        try:
            response = self._make_request(request_id, request_config)
            response_or_exception = response

            # 步骤3: 解析响应数据（仅在请求成功时）
            if self.response_parser_instance:
                try:
                    logger.debug(f"[{request_id}] Parsing response data")
                    parsed_data = self.response_parser_instance.parse(self, response)
                    logger.debug(f"[{request_id}] Response data parsed successfully")
                except Exception as e:
                    # 捕获解析错误，但不立即抛出，交给格式化器处理
                    parse_error = e
                    logger.error(f"[{request_id}] Response parsing failed: {e}")
        except APIClientError as e:
            response_or_exception = e
        finally:
            # 步骤4: 清理临时属性，避免状态污染
            if (
                self.response_parser_instance
                and isinstance(self.response_parser_instance, FileWriteResponseParser)
                and hasattr(self.response_parser_instance, "_current_filename")
            ):
                delattr(self.response_parser_instance, "_current_filename")

        # 步骤5: 使用格式化器格式化结果
        if self.response_formatter_instance:
            try:
                formatted_data = self.response_formatter_instance.format(
                    self, response_or_exception, request_config, parsed_data, parse_error
                )
                return formatted_data
            except Exception as format_error:
                logger.error(f"[{request_id}] Response formatting failed: {format_error}")
                # 格式化失败时的降级处理
                return {
                    "result": False,
                    "code": RESPONSE_CODE_FORMATTING_ERROR,
                    "message": f"Formatting failed: {format_error}",
                    "data": None,
                }

        # 步骤6: 未配置格式化器时的降级处理
        if isinstance(response_or_exception, requests.Response):
            # 如果有解析错误，标记为失败
            if parse_error:
                return {
                    "result": False,
                    "code": response_or_exception.status_code,
                    "message": f"Parsing failed: {parse_error}",
                    "data": None,
                }
            return {
                "result": True,
                "code": response_or_exception.status_code,
                "message": "Success (No formatter)",
                "data": parsed_data if parsed_data is not None else response_or_exception,
            }
        else:  # APIClientError
            return {
                "result": False,
                "code": getattr(response_or_exception, "status_code", RESPONSE_CODE_NON_HTTP_ERROR),
                "message": str(response_or_exception),
                "data": None,
            }

    @_RequestMethodDescriptor
    def request(
        self, request_data: dict[str, Any] | list[dict[str, Any]] | None = None, is_async: bool = False
    ) -> dict[str, Any] | list[dict[str, Any] | Exception]:
        """
        执行 HTTP 请求的统一入口方法（支持实例调用和类调用）

        该方法支持两种调用方式：
        1. 实例方法调用：client.request(request_data) - 复用已有实例和连接
        2. 类方法调用：MyClient.request(request_data, **client_kwargs) - 自动创建临时实例

        参数:
            request_data: 请求配置字典或配置列表
            is_async: 是否使用异步执行器并发执行（仅对列表有效）
            **client_kwargs: 仅类方法调用时有效，传递给客户端构造函数的额外参数

        返回:
            单个请求: 格式化后的响应字典
            多个请求: 格式化后的响应字典列表（可能包含异常对象）

        执行步骤（实例方法调用）:
            1. 验证 request_data 类型
            2. 单个请求: 直接调用 _make_request_and_format
            3. 多个请求 + 异步: 使用异步执行器并发执行
            4. 多个请求 + 同步: 顺序执行所有请求

        执行步骤（类方法调用）:
            1. 自动创建临时客户端实例
            2. 调用实例方法执行请求
            3. 自动清理资源并返回结果

        使用示例:
            # 方式1: 实例方法调用（适合多次请求，复用连接）
            with MyClient() as client:
                result1 = client.request({"endpoint": "/api/users"})
                result2 = client.request({"endpoint": "/api/posts"})

            # 方式2: 类方法调用（适合一次性请求，自动管理生命周期）
            result = MyClient.request(
                {"endpoint": "/api/users"},
                timeout=30,
                headers={"Authorization": "Bearer token"}
            )

            # 批量异步请求（类方法调用）
            results = MyClient.request([
                {"endpoint": "/api/users/1"},
                {"endpoint": "/api/users/2"}
            ], is_async=True)

        异常:
            APIClientValidationError: 当 request_data 类型无效时抛出
        """
        if request_data is None:
            request_data = {}
        if isinstance(request_data, dict):
            request_id = f"REQ-{uuid.uuid4().hex[:6]}"
            # 调用封装好的方法，它会处理解析和格式化
            return self._make_request_and_format(request_id, request_data)

        if isinstance(request_data, list):
            if not request_data:
                logger.warning("Empty request list provided")
                return []
            if is_async:
                # 异步执行器现在返回格式化后的数据
                return self.executor_instance.execute(self, request_data)
            return self._execute_sync_requests(request_data)
        raise APIClientValidationError("request_data must be a dictionary or a list of dictionaries")

    def _execute_sync_requests(self, request_list: list[dict[str, Any]]) -> list[dict[str, Any] | Exception]:
        """
        同步顺序执行多个请求

        参数:
            request_list: 请求配置列表

        返回:
            格式化后的响应字典列表，顺序与输入一致

        执行步骤:
            1. 遍历请求列表
            2. 为每个请求生成唯一 ID
            3. 顺序调用 _make_request_and_format
            4. 收集所有结果并返回
        """
        logger.info(f"Starting {len(request_list)} synchronous requests")
        results = []
        for i, config in enumerate(request_list):
            request_id = f"SYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
            # 调用封装好的方法
            result = self._make_request_and_format(request_id, config)
            results.append(result)
        return results

    def close(self):
        """
        关闭 Session 会话，释放连接池资源

        执行步骤:
            1. 检查 session 是否存在
            2. 调用 session.close() 关闭连接
            3. 记录日志
        """
        if self.session:
            self.session.close()
            logger.info("Session closed")

    def __enter__(self):
        """
        上下文管理器入口

        返回:
            self: 客户端实例
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        上下文管理器退出，自动关闭会话

        参数:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        self.close()
