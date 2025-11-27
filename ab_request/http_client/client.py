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
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    LOG_FORMAT,
    POOL_CONNECTIONS,
    POOL_MAXSIZE,
    RETRY_ALLOWED_METHODS,
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_FORCELIST,
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
        authentication_class: 认证类或实例
        executor_class: 异步执行器类或实例
        response_parser_class: 响应解析器类或实例
        response_formatter_class: 响应格式化器类或实例
    """

    base_url: str = ""
    endpoint: str = ""
    method: str = "GET"
    default_timeout: int = DEFAULT_TIMEOUT
    default_retries: int = DEFAULT_RETRIES
    default_headers: dict[str, str] = {}
    max_workers: int = DEFAULT_MAX_WORKERS
    authentication_class: type[AuthBase] | AuthBase | None = None
    executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor | None = ThreadPoolAsyncExecutor
    response_parser_class: type[BaseResponseParser] | BaseResponseParser | None = JSONResponseParser
    response_formatter_class: type[BaseResponseFormatter] | BaseResponseFormatter | None = DefaultResponseFormatter

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
        retries: int | None = None,
        max_workers: int | None = None,
        authentication: AuthBase | type[AuthBase] | None = None,
        executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
        response_parser: BaseResponseParser | type[BaseResponseParser] | None = None,
        response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None = None,
        **kwargs,
    ):
        """初始化客户端"""
        self.base_url = getattr(self, "base_url", "").rstrip("/")
        if not self.base_url:
            raise APIClientValidationError("base_url must be provided as a class attribute.")
        self._class_default_endpoint = getattr(self, "endpoint", "")
        self._class_default_method = getattr(self, "method", "GET").upper()
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.retries = retries if retries is not None else self.default_retries
        if max_workers is not None:
            self.max_workers = max_workers
        self.auth_instance = self._resolve_authentication(authentication)
        self.executor_instance = self._resolve_executor(executor)
        self.response_parser_instance = self._resolve_response_parser(response_parser)
        self.response_formatter_instance = self._resolve_response_formatter(response_formatter)
        self.session_headers = {**self.default_headers, **(default_headers or {}), **kwargs.pop("headers", {})}
        self.default_request_kwargs = kwargs
        self.session = self._create_session()

    def _resolve_authentication(self, authentication: AuthBase | type[AuthBase] | None) -> AuthBase | None:
        if authentication is not None:
            if isinstance(authentication, type) and issubclass(authentication, AuthBase):
                return authentication()
            elif isinstance(authentication, AuthBase):
                return authentication
            else:
                raise APIClientValidationError("authentication must be an AuthBase subclass or instance")
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
        if executor is not None:
            if isinstance(executor, type) and issubclass(executor, BaseAsyncExecutor):
                return executor(max_workers=self.max_workers)
            elif isinstance(executor, BaseAsyncExecutor):
                return executor
            else:
                raise APIClientValidationError("executor must be a BaseAsyncExecutor subclass or instance")
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
        解析响应格式化器配置，返回格式化器实例。
        :param response_formatter: 传入的格式化器配置（类或实例）
        :return: BaseResponseFormatter 实例或 None
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
                # 可以选择抛出错误或返回默认格式化器
                return DefaultResponseFormatter()  # 返回默认格式化器
        elif isinstance(source, BaseResponseFormatter):
            return source
        else:
            logger.warning(f"Invalid response formatter item: {source}. Using DefaultResponseFormatter.")
            return DefaultResponseFormatter()  # 返回默认格式化器

    def _create_session(self) -> requests.Session:
        """创建并配置请求会话"""
        session = requests.Session()
        session.headers.update(self.session_headers)
        if self.auth_instance:
            session.auth = self.auth_instance

        if self.retries > 0:
            retry_strategy = Retry(
                total=self.retries,
                backoff_factor=RETRY_BACKOFF_FACTOR,
                status_forcelist=RETRY_STATUS_FORCELIST,
                allowed_methods=RETRY_ALLOWED_METHODS,
                raise_on_status=False,
            )
            adapter = HTTPAdapter(
                max_retries=retry_strategy, pool_connections=POOL_CONNECTIONS, pool_maxsize=POOL_MAXSIZE
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """执行单个 HTTP 请求，返回原始 Response 对象。"""
        method = request_config.get("method", self._class_default_method).upper()
        endpoint = request_config.get("endpoint", self._class_default_endpoint)
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url

        stream_flag = False
        if self.response_parser_instance:
            stream_flag = getattr(self.response_parser_instance, "is_stream", False)

        request_kwargs = {
            **self.default_request_kwargs,
            "stream": stream_flag,  # 设置 stream 参数
            **{k: v for k, v in request_config.items() if k not in ("method", "endpoint")},
        }
        logger.info(f"[{request_id}] Starting {method} request to {url}")
        logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")
        try:
            response = self.session.request(method=method, url=url, timeout=self.timeout, **request_kwargs)
            logger.info(f"[{request_id}] Received {response.status_code} response")
            logger.debug(f"[{request_id}] Response headers: {response.headers}")
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as original_exception:
            if isinstance(original_exception, requests.exceptions.Timeout):
                converted_exception = APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s")
            elif isinstance(original_exception, requests.exceptions.HTTPError):
                status_code = original_exception.response.status_code if original_exception.response else 0
                converted_exception = APIClientHTTPError(
                    f"HTTP {status_code}: "
                    f"{original_exception.response.reason if original_exception.response else 'No response'}",
                    response=original_exception.response,
                )
            else:
                converted_exception = APIClientNetworkError(f"Request to {url} failed: {original_exception}")
            logger.error(f"[{request_id}] Request failed: {converted_exception}")
            raise converted_exception

    def _make_request_and_format(self, request_id: str, request_config: dict[str, Any]) -> dict[str, Any]:
        """
        执行请求，根据配置解析响应，并根据配置格式化结果。
        :param request_id: 请求ID。
        :param request_config: 请求配置。
        :return: 格式化后的字典数据。
        """
        # 为 FileWriteResponseParser 传递文件名
        if self.response_parser_instance and isinstance(self.response_parser_instance, FileWriteResponseParser):
            filename_from_config = request_config.get("filename")
            if filename_from_config:
                self.response_parser_instance._current_filename = filename_from_config

        response_or_exception: requests.Response | APIClientError
        try:
            response = self._make_request(request_id, request_config)
            response_or_exception = response
        except APIClientError as e:
            response_or_exception = e
        # finally 块确保清理动态属性
        finally:
            if (
                self.response_parser_instance
                and isinstance(self.response_parser_instance, FileWriteResponseParser)
                and hasattr(self.response_parser_instance, "_current_filename")
            ):
                delattr(self.response_parser_instance, "_current_filename")

        # 如果配置了格式化器，则使用它格式化结果
        if self.response_formatter_instance:
            try:
                formatted_data = self.response_formatter_instance.format(self, response_or_exception, request_config)
                return formatted_data
            except Exception as format_error:
                logger.error(f"[{request_id}] Response formatting failed: {format_error}")
                # 格式化失败时的 fallback：返回一个表示格式化错误的字典
                return {"result": False, "code": -3, "message": f"Formatting failed: {format_error}", "data": None}
        # 如果没有配置格式化器，直接返回原始响应或异常对象
        # 注意：这与同步/异步返回类型不一致，通常应配置格式化器
        # 为了兼容性，可以返回一个基础字典
        elif isinstance(response_or_exception, requests.Response):
            return {
                "result": True,
                "code": response_or_exception.status_code,
                "message": "Success (No formatter)",
                "data": response_or_exception,  # 或根据解析器处理
            }
        else:  # APIClientError
            return {
                "result": False,
                "code": getattr(response_or_exception, "status_code", -1),
                "message": str(response_or_exception),
                "data": None,
            }

    @property
    def full_url(self) -> str:
        """返回当前类定义下的完整 URL"""
        if not self._class_default_endpoint:
            return self.base_url
        return f"{self.base_url}/{self._class_default_endpoint.lstrip('/')}"

    def request(
        self, request_data: dict[str, Any] | list[dict[str, Any]] | None = None, is_async: bool = False
    ) -> dict[str, Any] | list[dict[str, Any] | Exception]:  # 返回类型改为格式化后的字典或列表
        """
        执行请求。
        :param request_data: 请求配置
        :param is_async: 是否异步执行
        :return: 格式化后的数据或列表
        :raises APIClientValidationError: 输入验证失败
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

    def _execute_sync_requests(
        self, request_list: list[dict[str, Any]]
    ) -> list[dict[str, Any] | Exception]:  # 返回类型改为格式化后的字典
        """同步执行多个请求"""
        logger.info(f"Starting {len(request_list)} synchronous requests")
        results = []
        for i, config in enumerate(request_list):
            request_id = f"SYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
            # 调用封装好的方法
            result = self._make_request_and_format(request_id, config)
            results.append(result)
        return results

    def close(self):
        """关闭会话，释放资源"""
        if self.session:
            self.session.close()
            logger.info("Session closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
