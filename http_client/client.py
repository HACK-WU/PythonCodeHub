"""HTTP 客户端核心模块

提供灵活、可扩展的 HTTP 客户端基类，支持：
- 自定义认证机制
- 多种响应解析器和格式化器
- 同步/异步请求执行
- 自动重试和连接池管理
- 完善的错误处理

作者: HACK-WU
创建时间: 2025/7/24 23:36
"""

import copy
import logging
import uuid
import time
import threading
from typing import Any, TypeAlias

import requests
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase
from urllib3.util.retry import Retry
from rest_framework import serializers


# 类型别名定义
RequestConfig: TypeAlias = dict[str, Any]
ResponseDict: TypeAlias = dict[str, Any]

from http_client.constants import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_POOL_CONFIG,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_CONFIG,
    DEFAULT_TIMEOUT,
    RESPONSE_CODE_FORMATTING_ERROR,
    RESPONSE_CODE_NON_HTTP_ERROR,
    RESPONSE_CODE_UNEXPECTED_TYPE,
)
from http_client.exceptions import (
    APIClientError,
    APIClientHTTPError,
    APIClientNetworkError,
    APIClientRequestValidationError,
    APIClientTimeoutError,
    APIClientValidationError,
)
from http_client.async_executor import BaseAsyncExecutor, ThreadPoolAsyncExecutor
from http_client.formatter import BaseResponseFormatter, DefaultResponseFormatter
from http_client.parser import (
    BaseResponseParser,
    FileWriteResponseParser,
    JSONResponseParser,
    RawResponseParser,
)
from http_client.serializer import BaseRequestSerializer
from http_client.validator import BaseResponseValidator

# 配置日志
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
            request_data: RequestConfig = None,
            is_async: bool = False,
            **client_kwargs,
        ) -> ResponseDict | list[ResponseDict | Exception]:
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
        enable_retry: 是否启用重试机制（默认 False）
        default_retries: 默认重试次数
        default_headers: 默认请求头
        max_workers: 异步执行时的最大工作线程数
        retry_config: 重试策略配置字典
        pool_config: 连接池配置字典
        verify: SSL 证书验证开关（默认 False，不验证证书）
        authentication_class: 认证类或实例
        async_executor_class: 异步执行器类或实例
        response_parser_class: 响应数据解析器类或实例
        response_formatter_class: 响应格式化器类或实例
        response_validator_class: 响应验证器类或实例
        request_serializer_class: 请求序列化器类或实例
    """

    # ========== 基础配置 ==========
    # API 基础 URL，必须在子类中设置，所有请求将基于此 URL 构建完整路径
    base_url: str = ""

    # 默认端点路径，可在请求时覆盖，用于构建完整的请求 URL
    endpoint: str = ""

    # 默认 HTTP 请求方法，支持 GET/POST/PUT/DELETE/PATCH 等标准方法
    method: str = "GET"

    # SSL 证书验证开关，True 表示验证证书（生产环境推荐），False 表示不验证（仅用于开发环境或自签名证书）
    verify: bool = True

    # ========== 安全性配置 ==========
    # 敏感请求头名称集合，这些头在日志中会被脱敏
    sensitive_headers: set[str] = {
        "Authorization",
        "Cookie",
        "X-API-Key",
        "X-Auth-Token",
        "X-Access-Token",
    }

    # 敏感 URL 参数名称集合，这些参数在日志中会被脱敏
    sensitive_params: set[str] = {
        "token",
        "password",
        "secret",
        "key",
        "api_key",
        "access_token",
    }

    # 是否启用敏感信息脱敏，默认启用以提高安全性
    enable_sanitization: bool = True

    # ========== 超时和重试配置 ==========
    # 默认请求超时时间（秒），防止请求无限期挂起
    default_timeout: int = DEFAULT_TIMEOUT

    # 是否启用重试机制，默认不启用
    enable_retry: bool = False

    # 默认最大重试次数，0 表示不重试，适用于幂等性请求
    max_retries: int = DEFAULT_RETRIES

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
    async_executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor = ThreadPoolAsyncExecutor

    # 响应数据解析器类或实例，用于解析 HTTP 响应体为 Python 对象
    # 默认使用 JSON 解析器，可替换为 XML、HTML 或自定义解析器
    response_parser_class: type[BaseResponseParser] | BaseResponseParser = JSONResponseParser

    # 响应格式化器类或实例，用于将响应统一格式化为标准结构
    # 默认格式化为 {result, code, message, data} 结构，便于统一处理
    response_formatter_class: type[BaseResponseFormatter] | BaseResponseFormatter = DefaultResponseFormatter

    # 请求序列化器类或实例，用于在发送请求前验证请求参数
    # None 表示不进行请求参数验证
    # 支持两种方式定义:
    # 1. 类属性: request_serializer_class = MyRequestSerializer
    # 2. 内嵌类: 在子类中定义 class RequestSerializer(BaseRequestSerializer)
    request_serializer_class: type[BaseRequestSerializer] | BaseRequestSerializer | None = None

    # 响应验证器类或实例，用于验证响应是否符合预期
    # None 表示不进行响应验证，可设置为自定义验证器进行业务逻辑验证
    response_validator_class: type[BaseResponseValidator] | BaseResponseValidator | None = None

    def __init__(
        self,
        url: str = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
        verify: bool | None = None,
        enable_retry: bool | None = None,
        max_retries: int | None = None,
        max_workers: int | None = None,
        retry_config: dict[str, Any] | None = None,
        pool_config: dict[str, Any] | None = None,
        authentication: AuthBase | type[AuthBase] | None = None,
        executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
        response_parser: BaseResponseParser | type[BaseResponseParser] | None = None,
        response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None = None,
        response_validator: BaseResponseValidator | type[BaseResponseValidator] | None = None,
        request_serializer: BaseRequestSerializer | type[BaseRequestSerializer] | None = None,
        **kwargs,
    ):
        """
        初始化 API 客户端实例

        参数:
            default_headers: 默认请求头字典
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retries: (废弃) 使用 max_retries 替代
            max_workers: 异步执行的最大工作线程数
            retry_config: 重试策略配置字典（覆盖类级别配置）
            pool_config: 连接池配置字典（覆盖类级别配置）
            verify: SSL 证书验证开关（None 时使用类属性，默认 True）
            authentication: 认证类或实例
            executor: 异步执行器类或实例
            response_parser: 响应解析器类或实例
            response_formatter: 响应格式化器类或实例
            response_validator: 响应验证器类或实例
            request_serializer: 请求序列化器类或实例
            **kwargs: 其他传递给 requests 的参数

        执行步骤:
            1. 验证并规范化 base_url
            2. 解析并初始化认证、执行器、解析器、格式化器、验证器
            3. 合并请求头配置（类级别 + 实例级别）
            4. 合并重试策略和连接池配置
            5. 创建并配置 requests.Session 对象

        异常:
            APIClientValidationError: 当 base_url 未设置或配置无效时抛出
        """

        # ========== 步骤1: 验证并规范化 base_url ==========
        self.base_url = self.base_url.rstrip("/") if self.base_url else ""
        if not url and not self.base_url:
            raise APIClientValidationError("base_url or url must be provided as a class attribute.")

        # 保存类级别的默认端点和方法，用于后续请求时的默认值
        self._class_default_endpoint = self.endpoint
        self._class_default_method = self.method.upper()
        self.url = url or self._build_url(self.endpoint)

        # ========== 步骤2: 初始化实例级别的配置参数 ==========
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.enable_retry = enable_retry if enable_retry is not None else self.enable_retry
        self.max_retries = max_retries if max_retries is not None else self.max_retries
        self.verify = verify if verify is not None else self.verify
        self.max_workers = max_workers if max_workers is not None else self.max_workers

        # 合并重试策略和连接池配置
        self.retry_config = self._merge_config(self.retry_config, retry_config, max_retries_override=max_retries)
        self.pool_config = self._merge_config(self.pool_config, pool_config)

        # ========== 步骤3: 解析并初始化各个组件实例 ==========
        self.auth_instance = self._resolve_authentication(authentication)

        # 解析异步执行器：用于并发请求的执行
        self.async_executor_instance = self._resolve_async_executor(executor)

        # 解析响应解析器：用于解析 HTTP 响应内容（如 JSON、XML 等）
        self.response_parser_instance = self._resolve_response_parser(response_parser)

        # 解析响应格式化器：用于格式化解析后的响应数据
        self.response_formatter_instance = self._resolve_response_formatter(response_formatter)

        # 解析响应验证器：用于验证响应是否符合预期
        self.response_validator_instance = self._resolve_response_validator(response_validator)

        # 解析请求序列化器：用于在发送请求前验证请求参数
        self.request_serializer_instance = self._resolve_request_serializer(request_serializer)

        # ========== 步骤4: 合并请求头配置 ==========
        # 合并顺序：类级别默认请求头 -> 实例级别请求头 -> kwargs 中的请求头
        # 后者会覆盖前者，实现灵活的请求头配置
        self.session_headers = {**self.default_headers, **(headers or {})}

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

        # 默认不启用缓存。
        # 继承CacheClientMixin后，会自动启用缓存
        self.enable_cache = False
        self.user_identifier = None
        self.cache_key_prefix = ""
        # request_id -> request_config
        self.request_mapping = {}

        # ========== 步骤7: 初始化线程安全相关的锁 ==========
        # 为关键共享状态添加线程锁，支持多线程并发使用
        self._request_mapping_lock = threading.RLock()
        self._session_lock = threading.RLock()

        # ========== 步骤8: 初始化流式响应追踪 ==========
        # 用于追踪未关闭的流式响应，防止资源泄漏
        self._stream_responses = []
        self._stream_responses_lock = threading.RLock()

        # ========== 步骤9: 初始化请求钩子 ==========
        # 用于存储注册的钩子函数，支持请求前后的自定义处理
        self._hooks = {
            "before_request": [],
            "after_request": [],
            "on_request_error": [],
        }

    # 继承CacheClientMixin后，会重写_get_cache_key方法
    def _get_cache_key(self, request_config, **kwargs) -> str | None:
        """
        获取缓存键
        """
        if self.enable_cache:
            raise NotImplementedError
        return None

    # ========== 钩子机制 ==========

    def register_hook(self, hook_name: str, callback: callable) -> None:
        """
        注册钩子函数

        参数:
            hook_name: 钩子名称，可选值："before_request", "after_request", "on_request_error"
            callback: 钩子回调函数

        异常:
            ValueError: 当钩子名称不合法时抛出
        """
        if hook_name not in self._hooks:
            raise ValueError(f"Invalid hook name: {hook_name}. Must be one of: {list(self._hooks.keys())}")
        self._hooks[hook_name].append(callback)
        logger.debug(f"Registered hook: {hook_name}")

    def before_request(self, request_id: str, request_config: RequestConfig) -> RequestConfig:
        """
        请求发送前的钩子方法

        子类可以重写此方法以实现自定义逻辑，例如：
        - 添加请求签名
        - 修改请求头
        - 记录请求日志

        参数:
            request_id: 请求唯一标识符
            request_config: 请求配置字典

        返回:
            修改后的请求配置字典
        """
        # 执行所有注册的 before_request 钩子
        for hook in self._hooks["before_request"]:
            try:
                request_config = hook(self, request_id, request_config)
            except Exception:
                logger.exception(f"[{request_id}] before_request hook failed")
        return request_config

    def after_request(self, request_id: str, response: requests.Response) -> requests.Response:
        """
        请求成功后的钩子方法

        子类可以重写此方法以实现自定义逻辑，例如：
        - 记录响应日志
        - 统计响应时间
        - 处理响应头

        参数:
            request_id: 请求唯一标识符
            response: HTTP 响应对象

        返回:
            修改后的响应对象
        """
        # 执行所有注册的 after_request 钩子
        for hook in self._hooks["after_request"]:
            try:
                response = hook(self, request_id, response)
            except Exception:
                logger.exception(f"[{request_id}] after_request hook failed")
        return response

    def on_request_error(self, request_id: str, error: Exception) -> None:
        """
        请求失败时的钩子方法

        子类可以重写此方法以实现自定义逻辑，例如：
        - 记录错误日志
        - 发送告警
        - 收集错误指标

        参数:
            request_id: 请求唯一标识符
            error: 异常对象
        """
        # 执行所有注册的 on_request_error 钩子
        for hook in self._hooks["on_request_error"]:
            try:
                hook(self, request_id, error)
            except Exception:
                logger.exception(f"[{request_id}] on_request_error hook failed")

    def _resolve_component(self, component, class_attr_name, base_class, fallback_class, **init_kwargs):
        """
        统一的组件解析方法

        参数:
            component: 传入的组件配置（类或实例）
            class_attr_name: 类属性名称
            base_class: 基类类型
            fallback_class: 失败时的降级类
            **init_kwargs: 实例化时的额外参数

        返回:
            组件实例
        """
        # 优先使用传入配置，否则使用类级别配置
        source = component if component is not None else getattr(self, class_attr_name, fallback_class)

        if source is None:
            return None

        # 处理类：尝试实例化
        if isinstance(source, type) and issubclass(source, base_class):
            try:
                return source(**init_kwargs)
            except Exception as e:
                logger.error(f"Failed to instantiate {source.__name__}: {e}")
                if fallback_class and fallback_class != source:
                    return fallback_class(**init_kwargs) if init_kwargs else fallback_class()
                raise APIClientValidationError(f"{class_attr_name} instantiation failed: {e}")

        # 处理实例：直接返回
        if isinstance(source, base_class):
            return source

        # 无效类型：尝试降级或抛出异常
        if fallback_class:
            logger.warning(f"Invalid {class_attr_name}: {source}. Using {fallback_class.__name__}.")
            return fallback_class(**init_kwargs) if init_kwargs else fallback_class()

        raise APIClientValidationError(f"{class_attr_name} must be a {base_class.__name__} subclass or instance")

    def _resolve_authentication(self, authentication: AuthBase | type[AuthBase] | None) -> AuthBase | None:
        """
        解析认证配置，返回认证实例

        参数:
            authentication: 传入的认证配置（类或实例）

        返回:
            AuthBase 实例或 None
        """
        return self._resolve_component(authentication, "authentication_class", AuthBase, fallback_class=None)

    def _resolve_async_executor(
        self, executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None
    ) -> BaseAsyncExecutor:
        """
        解析异步执行器配置，返回执行器实例

        参数:
            executor: 传入的执行器配置（类或实例）

        返回:
            BaseAsyncExecutor 实例
        """
        return self._resolve_component(
            executor, "async_executor_class", BaseAsyncExecutor, ThreadPoolAsyncExecutor, max_workers=self.max_workers
        )

    def _resolve_response_parser(
        self, response_parser: BaseResponseParser | type[BaseResponseParser] | None
    ) -> BaseResponseParser:
        """
        解析响应解析器配置，返回解析器实例

        参数:
            response_parser: 传入的解析器配置（类或实例）

        返回:
            BaseResponseParser 实例（失败时返回 RawResponseParser）
        """
        return self._resolve_component(response_parser, "response_parser_class", BaseResponseParser, RawResponseParser)

    def _resolve_response_formatter(
        self, response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None
    ) -> BaseResponseFormatter:
        """
        解析响应格式化器配置，返回格式化器实例

        参数:
            response_formatter: 传入的格式化器配置（类或实例）

        返回:
            BaseResponseFormatter 实例（失败时返回 DefaultResponseFormatter）
        """
        return self._resolve_component(
            response_formatter, "response_formatter_class", BaseResponseFormatter, DefaultResponseFormatter
        )

    def _resolve_response_validator(
        self, response_validator: BaseResponseValidator | type[BaseResponseValidator] | None
    ) -> BaseResponseValidator | None:
        """
        解析响应验证器配置，返回验证器实例

        参数:
            response_validator: 传入的验证器配置（类或实例）

        返回:
            BaseResponseValidator 实例或 None
        """
        return self._resolve_component(response_validator, "response_validator_class", BaseResponseValidator, None)

    def _resolve_request_serializer(
        self, request_serializer: BaseRequestSerializer | type[BaseRequestSerializer] | None
    ) -> BaseRequestSerializer | None:
        """
        解析请求序列化器配置，返回序列化器实例

        解析优先级（从高到低）:
            1. 构造函数传入的 request_serializer 参数
            2. 类属性 request_serializer_class
            3. 内嵌类 RequestSerializer（在子类中定义）

        参数:
            request_serializer: 传入的序列化器配置（类或实例）

        返回:
            BaseRequestSerializer 实例或 None
        """
        # 优先使用传入的参数
        if request_serializer is not None:
            return self._resolve_component(request_serializer, "request_serializer_class", BaseRequestSerializer, None)

        # 其次使用类属性
        if self.request_serializer_class is not None:
            return self._resolve_component(None, "request_serializer_class", BaseRequestSerializer, None)

        # 最后检查是否有内嵌的 RequestSerializer 类
        request_serializer_cls = getattr(self.__class__, "RequestSerializer", None)
        if request_serializer_cls is not None and isinstance(request_serializer_cls, type):
            if issubclass(request_serializer_cls, BaseRequestSerializer):
                try:
                    return request_serializer_cls()
                except Exception as e:
                    logger.error(f"Failed to instantiate RequestSerializer: {e}")
                    raise APIClientValidationError(f"RequestSerializer instantiation failed: {e}")

        return None

    def _validate_request(
        self, request_config: RequestConfig | list[RequestConfig]
    ) -> RequestConfig | list[RequestConfig]:
        """
        使用序列化器验证请求参数

        参数:
            request_id: 请求唯一标识符
            request_config: 请求配置字典

        返回:
            验证并可能转换后的请求配置

        异常:
            APIClientRequestValidationError: 当验证失败时抛出
        """
        if self.request_serializer_instance is None:
            return request_config

        if isinstance(request_config, list):
            return [self._validate_request(config) for config in request_config]

        return self.request_serializer_instance.validate(request_config)

    def _merge_config(self, base_config: dict, override_config: dict | None, **extra_updates) -> dict:
        """
        合并配置字典

        参数:
            base_config: 基础配置（类级别）
            override_config: 覆盖配置（实例级别）
            **extra_updates: 额外的更新项（如 max_retries_override）

        返回:
            合并后的配置字典
        """
        merged = {**base_config, **(override_config or {})}

        # 处理特殊更新逻辑
        if max_retries_override := extra_updates.get("max_retries_override"):
            merged["total"] = max_retries_override

        return merged

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

        if self.enable_retry and self.max_retries > 0:
            # 使用配置字典创建重试策略
            retry_strategy = Retry(**self.retry_config)
            # 使用配置字典创建 HTTP 适配器
            adapter = HTTPAdapter(max_retries=retry_strategy, **self.pool_config)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: RequestConfig) -> requests.Response:
        """
        执行单个 HTTP 请求，返回原始 Response 对象

        参数:
            request_id: 请求唯一标识符，用于日志追踪
            request_config: 请求配置字典，包含 method、endpoint、params 等

        返回:
            requests.Response 对象

        执行步骤:
            1. 调用 before_request 钩子
            2. 从配置中提取 HTTP 方法和端点路径
            3. 构建完整的请求 URL
            4. 根据解析器配置决定是否使用流式响应
            5. 合并默认参数和请求特定参数
            6. 执行 HTTP 请求
            7. 调用 after_request 钩子
            8. 检查响应状态码，抛出 HTTP 错误
            9. 捕获并转换各类异常为自定义异常

        异常:
            APIClientTimeoutError: 请求超时
            APIClientHTTPError: HTTP 错误响应（4xx, 5xx）
            APIClientNetworkError: 网络连接错误
        """
        # 步骤0: 调用 before_request 钩子
        request_config = self.before_request(request_id, request_config)

        # 步骤1: 解析请求方法和端点
        method = request_config.get("method", self._class_default_method).upper()
        url = self.url

        # 步骤2: 确定是否需要流式响应（检查解析器的 is_stream 属性）
        stream_flag = getattr(self.response_parser_instance, "is_stream", False)

        # 步骤3: 构建请求参数字典
        request_kwargs = self._build_request_kwargs(request_config, stream_flag)

        # 步骤4: 记录请求开始日志
        # INFO 级别：记录请求的基本信息（方法和 URL），生产环境可见
        if self.enable_sanitization:
            from http_client.utils import sanitize_url

            safe_url = sanitize_url(url, self.sensitive_params)
        else:
            safe_url = url
        logger.info(f"[{request_id}] Starting {method} request to {safe_url}")

        # DEBUG 级别：记录完整的请求参数（包含 headers、params 等），仅调试时可见
        if logger.isEnabledFor(logging.DEBUG):
            if self.enable_sanitization:
                from http_client.utils import sanitize_dict, sanitize_headers

                safe_kwargs = sanitize_dict(request_kwargs.copy(), self.sensitive_params)
                if "headers" in safe_kwargs:
                    safe_kwargs["headers"] = sanitize_headers(safe_kwargs["headers"], self.sensitive_headers)
                logger.debug(f"[{request_id}] Request kwargs: {safe_kwargs}")
            else:
                logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")

        try:
            with self._session_lock:
                response = self.session.request(method=method, url=url, timeout=self.timeout, **request_kwargs)

            # 步骤5: 调用 after_request 钩子
            response = self.after_request(request_id, response)

            logger.info(f"[{request_id}] Received {response.status_code} response")
            logger.debug(f"[{request_id}] Response headers: {response.headers}")
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            # 情况1: 超时异常
            error = APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s")
            logger.error(f"[{request_id}] Request failed: {error}")
            self.on_request_error(request_id, error)
            raise error
        except requests.exceptions.HTTPError as e:
            # 情况2: HTTP 错误响应（4xx/5xx 状态码）
            status_code = e.response.status_code if e.response else 0
            reason = e.response.reason if e.response else "No response"
            error = APIClientHTTPError(f"HTTP {status_code}: {reason}", response=e.response)
            logger.error(f"[{request_id}] Request failed: {error}")
            self.on_request_error(request_id, error)
            raise error
        except requests.exceptions.RequestException as e:
            # 情况3: 其他网络异常（连接失败、DNS 解析失败等）
            error = APIClientNetworkError(f"Request to {url} failed: {e}")
            logger.error(f"[{request_id}] Request failed: {error}")
            self.on_request_error(request_id, error)
            raise error

    def _build_url(self, endpoint: str) -> str:
        """
        构建完整的请求 URL

        参数:
            endpoint: 端点路径

        返回:
            完整的 URL
        """
        return f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url

    def _build_request_kwargs(self, request_config: RequestConfig, stream: bool) -> dict[str, Any]:
        """
        构建请求参数字典

        参数:
            request_config: 请求配置字典
            stream: 是否使用流式响应

        返回:
            合并后的请求参数字典
        """
        # 过滤掉 method 和 endpoint，其他配置都传递给 requests
        config_kwargs = {k: v for k, v in request_config.items() if k not in ("method", "endpoint")}
        return {**self.default_request_kwargs, "stream": stream, **config_kwargs}

    def _make_request_and_format(self, request_id: str, request_config: RequestConfig) -> ResponseDict:
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
        self._set_parser_context(request_config)

        # 步骤2: 执行请求并捕获响应或异常
        parsed_data: Any = None
        parse_error: Exception | None = None

        try:
            response = self._make_request(request_id, request_config)
            response_or_exception = response

            # 步骤3: 解析响应数据（仅在请求成功时）
            parsed_data, parse_error = self._parse_response(request_id, response)
        except APIClientError as e:
            response_or_exception = e
        finally:
            # 步骤4: 清理临时属性，避免状态污染
            self._clear_parser_context()

        formated_response = self.default_format_response(response_or_exception, parsed_data, parse_error)

        try:
            formated_response = self.response_formatter_instance.format(
                **{
                    "formatted_response": formated_response,
                    "parsed_data": parsed_data,
                    "request_id": request_id,
                    "request_config": request_config,
                    "response_or_exception": response_or_exception,
                    "parse_error": parse_error,
                    "base_client_instance": self,
                }
            )
            # 如果启用了缓存，则添加缓存键
            if self.enable_cache and self.request_mapping.get(request_id):
                cache_key = self._get_cache_key(self.request_mapping[request_id])
                if cache_key is not None:
                    formated_response["cache_key"] = f"{self.cache_key_prefix}_{cache_key}"

            return formated_response
        except Exception as format_error:
            logger.error(f"[{request_id}] Response formatting failed: {format_error}")
            # 格式化失败时的降级处理
            return {
                "result": False,
                "code": RESPONSE_CODE_FORMATTING_ERROR,
                "message": f"Formatting failed: {format_error}",
                "data": None,
            }

    def generate_request_id(self, suffix=None) -> str:
        """生成全局唯一的请求 ID"""
        if suffix is not None:
            suffix = str(suffix)

        timestamp = int(time.time() * 1000)  # 毫秒级时间戳
        short_uuid = uuid.uuid4().hex[:8]
        return f"REQ-{timestamp}-{short_uuid}-{suffix}"

    def default_format_response(
        self,
        response_or_exception: requests.Response | APIClientError,
        parsed_data: Any = None,
        parse_error: Exception | None = None,
    ) -> dict[str, Any]:
        """
        将HTTP响应或异常格式化为统一的标准字典结构

        参数:
            response_or_exception: 请求结果，可能是成功的Response对象或失败的APIClientError异常
            parsed_data: 已解析的响应数据（由 response_parser 在 client 中解析）
            parse_error: 解析过程中发生的异常（如果有）

        返回值:
            dict[str, Any]: 标准化的响应字典，包含以下字段：
                - result (bool): 请求是否成功的标志
                - code (int|None): HTTP状态码或错误代码
                - message (str): 响应消息或错误描述
                - data (Any): 解析后的响应数据或None

        该方法实现完整的响应格式化流程，包含：
        1. 初始化标准响应结构（默认失败状态）
        2. 处理成功响应：提取状态码、使用已解析的数据
        3. 处理解析错误：标记为失败并记录错误信息
        4. 处理异常响应：提取错误信息和状态码
        5. 处理异常类型：兜底处理未预期的响应类型
        """
        # 初始化标准响应结构，默认为失败状态
        formatted_response: dict[str, Any] = {"result": False, "code": None, "message": "", "data": None}

        if isinstance(response_or_exception, requests.Response):
            # ========== 处理成功的HTTP响应 ==========
            # 检查是否有解析错误
            if parse_error:
                # 虽然HTTP请求成功，但数据解析失败，标记为失败
                formatted_response["result"] = False
                formatted_response["code"] = response_or_exception.status_code
                formatted_response["message"] = f"Parsing failed: {parse_error}"
                formatted_response["data"] = None
            else:
                # HTTP请求成功且数据解析成功（或无需解析）
                formatted_response["result"] = True
                formatted_response["code"] = response_or_exception.status_code
                formatted_response["message"] = "Success"
                # 使用已解析的数据（可能为None，表示无需解析或解析器未配置）
                formatted_response["data"] = parsed_data

        elif isinstance(response_or_exception, APIClientError):
            # ========== 处理API客户端异常 ==========
            formatted_response["result"] = False
            if hasattr(response_or_exception, "status_code") and response_or_exception.status_code:
                # HTTP错误：使用响应的状态码
                formatted_response["code"] = response_or_exception.status_code
            else:
                # 非HTTP错误（如网络超时、连接失败等），使用通用错误代码
                formatted_response["code"] = RESPONSE_CODE_NON_HTTP_ERROR
            formatted_response["message"] = str(response_or_exception)
            formatted_response["data"] = None

        else:
            # ========== 处理未预期的响应类型（兜底逻辑） ==========
            formatted_response["result"] = False
            # 使用特殊错误代码标识未知类型错误
            formatted_response["code"] = RESPONSE_CODE_UNEXPECTED_TYPE
            formatted_response["message"] = f"Unexpected response/exception type: {type(response_or_exception)}"
            formatted_response["data"] = None

        return formatted_response

    def _set_parser_context(self, request_config: RequestConfig):
        """为 FileWriteResponseParser 设置上下文"""
        parser = self.response_parser_instance
        if isinstance(parser, FileWriteResponseParser) and (filename := request_config.get("filename")):
            parser._current_filename = filename

    def _clear_parser_context(self):
        """清理 FileWriteResponseParser 的上下文"""
        parser = self.response_parser_instance
        if isinstance(parser, FileWriteResponseParser) and hasattr(parser, "_current_filename"):
            delattr(parser, "_current_filename")

    def _parse_response(self, request_id: str, response: requests.Response) -> tuple[Any, Exception | None]:
        """
        解析响应数据并执行验证

        参数:
            request_id: 请求唯一标识符
            response: HTTP 响应对象

        返回:
            (解析后的数据, 解析错误)
        """
        try:
            # 步骤1: 解析响应数据
            logger.debug(f"[{request_id}] Parsing response data")
            parsed_data = self.response_parser_instance.parse(self, response)
            logger.debug(f"[{request_id}] Response data parsed successfully")

            # 步骤2: 执行解析后数据的验证
            if self.response_validator_instance:
                logger.debug(f"[{request_id}] Validating parsed response data")
                self.response_validator_instance.validate(self, response, parsed_data)
                logger.debug(f"[{request_id}] Parsed data validation passed")

            return parsed_data, None
        except Exception as e:
            logger.error(f"[{request_id}] Response validation/parsing failed: {e}")
            return None, e

    @_RequestMethodDescriptor
    def request(
        self, request_data: RequestConfig = None, is_async: bool = False
    ) -> ResponseDict | list[ResponseDict | Exception]:
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
        try:
            # 处理单个请求
            if request_data is None or isinstance(request_data, dict):
                return self._execute_single_request(request_data or {})

            # 处理批量请求
            if isinstance(request_data, list):
                return self._execute_batch_requests(request_data, is_async)

            raise APIClientValidationError("request_data must be a dictionary or a list of dictionaries")
        finally:
            # 清空请求映射
            with self._request_mapping_lock:
                self.request_mapping = {}

    def _execute_single_request(self, request_config: RequestConfig) -> ResponseDict:
        """
        执行单个请求

        参数:
            request_config: 请求配置字典

        返回:
            格式化后的响应字典

        执行步骤:
            1. 生成请求 ID
            2. 使用序列化器验证请求参数（如果配置了序列化器）
            3. 执行 HTTP 请求并格式化结果
        """
        request_id = self.generate_request_id()
        if self.enable_cache:
            with self._request_mapping_lock:
                self.request_mapping[request_id] = copy.deepcopy(request_config)

        # 验证请求参数
        validated_config = self._validate_request(request_config)

        return self._make_request_and_format(request_id, validated_config)

    def _execute_batch_requests(
        self, request_list: list[RequestConfig], is_async: bool
    ) -> list[ResponseDict | Exception]:
        """
        执行批量请求

        参数:
            request_list: 请求配置列表
            is_async: 是否异步执行

        返回:
            格式化后的响应字典列表
        """
        if not request_list:
            logger.warning("Empty request list provided")
            return []

        validated_request_mapping = {}
        for i, request_config in enumerate(request_list):
            request_id = self.generate_request_id(i)
            if self.enable_cache:
                with self._request_mapping_lock:
                    self.request_mapping[request_id] = copy.deepcopy(request_config)
            validated_request_mapping[request_id] = self._validate_request(request_config)

        return (
            self.async_executor_instance.execute(self, validated_request_mapping)
            if is_async
            else self._execute_sync_requests(validated_request_mapping)
        )

    def _execute_sync_requests(
        self, validated_request_mapping: dict[str, RequestConfig]
    ) -> list[ResponseDict | Exception]:
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
        logger.info(f"Starting {len(validated_request_mapping)} synchronous requests")
        return [
            self._make_request_and_format(request_id, request_data)
            for request_id, request_data in validated_request_mapping.items()
        ]

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


class DRFClient(BaseClient):
    """
    支持 DRF 序列化器的 HTTP 客户端

    继承自 BaseClient，直接使用 Django REST Framework 序列化器进行请求参数验证。
    可以将 DRF 的 Serializer 类直接赋值给 request_serializer_class。

    使用示例:
        from rest_framework import serializers

        class CreateUserSerializer(serializers.Serializer):
            username = serializers.CharField(max_length=100, required=True)
            email = serializers.EmailField(required=True)
            age = serializers.IntegerField(min_value=0, max_value=150, required=False)

        class UserAPIClient(DRFClient):
            base_url = "https://api.example.com"
            endpoint = "/users"
            method = "POST"
            request_serializer_class = CreateUserSerializer

        # 发送请求（会自动验证 json 中的数据）
        result = UserAPIClient.request({
            "json": {
                "username": "john_doe",
                "email": "john@example.com",
                "age": 25
            }
        })
    """

    request_serializer_instance: type[serializers.Serializer] | None = None

    def _resolve_request_serializer(self, request_serializer):
        """
        解析请求序列化器，直接返回 DRF Serializer 类

        参数:
            request_serializer: 传入的序列化器类

        返回:
            DRF Serializer 类或 None

        异常:
            APIClientValidationError: 当传入的不是 DRF Serializer 类时抛出
        """

        source = request_serializer
        if source is None:
            source = self.request_serializer_class
        if source is None:
            source = getattr(self.__class__, "RequestSerializer", None)

        # 如果没有配置序列化器，直接返回 None
        if source is None:
            return None

        # 类型校验：必须是 DRF Serializer 的子类
        if isinstance(source, type) and issubclass(source, serializers.Serializer):
            return source

        # 如果是实例，检查是否是 DRF Serializer 的实例
        if isinstance(source, serializers.Serializer):
            return source.__class__

        # 类型不匹配，抛出异常
        raise APIClientValidationError(
            f"request_serializer must be a DRF Serializer class or instance, got {type(source).__name__}"
        )

    def _validate_request(
        self, request_config: RequestConfig | list[RequestConfig]
    ) -> RequestConfig | list[RequestConfig]:
        """
        使用 DRF 序列化器验证请求参数

        参数:
            request_id: 请求唯一标识符
            request_config: 请求配置字典或字典列表

        返回:
            验证并转换后的请求配置

        异常:
            APIClientRequestValidationError: 当验证失败时抛出
        """
        if self.request_serializer_instance is None:
            return request_config

        # 判断是否为列表，使用 many=True 进行批量验证
        is_many = isinstance(request_config, list)
        serializer = self.request_serializer_instance(data=request_config, many=is_many)

        if not serializer.is_valid():
            raise APIClientRequestValidationError("请求参数验证失败", errors=serializer.errors)

        request_config = serializer.data

        return request_config
