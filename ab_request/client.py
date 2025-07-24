# Time: 2025/7/24 23:36
# name: test
# author: HACK-WU
import logging
import os
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class APIClientError(Exception):
    """自定义 API 客户端异常基类"""

class APIClientHTTPError(APIClientError):
    """表示 HTTP 错误响应的异常"""
    def __init__(self, message, response: requests.Response | None = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response else None

class APIClientNetworkError(APIClientError):
    """表示网络问题导致的异常"""

class APIClientTimeoutError(APIClientError):
    """表示请求超时的异常"""

class APIClientValidationError(APIClientError):
    """表示输入验证失败的异常"""

# --- 新增：定义响应解析器基类 ---
from abc import ABC, abstractmethod


class BaseResponseParser(ABC):
    """响应解析器基类，定义解析 requests.Response 的接口。"""
    @abstractmethod
    def parse(self, client_instance: "BaseClient", response: requests.Response) -> Any:
        """解析 requests.Response 对象并返回所需格式的数据。"""

# --- 新增：实现具体的响应解析器 ---
class JSONResponseParser(BaseResponseParser):
    """解析响应为 JSON 数据"""
    def parse(self, client_instance: "BaseClient", response: requests.Response) -> Any:
        logger.debug("Parsing response as JSON")
        return response.json()

class ContentResponseParser(BaseResponseParser):
    """解析响应为 Content 字节数据"""
    def parse(self, client_instance: "BaseClient", response: requests.Response) -> bytes:
        logger.debug("Parsing response as content bytes")
        return response.content

class RawResponseParser(BaseResponseParser):
    """返回原始响应对象"""
    def parse(self, client_instance: "BaseClient", response: requests.Response) -> requests.Response:
        logger.debug("Returning raw response object")
        return response

class FileWriteResponseParser(BaseResponseParser):
    """将响应内容写入文件"""
    def __init__(self, base_path: str = "./downloads", filename_template: str = "{request_id}_{endpoint}.dat"):
        self.base_path = base_path
        self.filename_template = filename_template
        os.makedirs(self.base_path, exist_ok=True)

    def parse(self, client_instance: "BaseClient", response: requests.Response) -> str:
        default_filename = "downloaded_file"
        if response.url:
             url_path = response.url.split("?")[0]
             parts = url_path.rstrip("/").split("/")
             if parts:
                 default_filename = parts[-1]

        filename = getattr(self, '_current_filename', None) or default_filename
        if not filename or filename == default_filename:
             content_type = response.headers.get('content-type', '')
             if 'json' in content_type:
                 filename += '.json'
             elif 'xml' in content_type:
                 filename += '.xml'

        file_path = os.path.join(self.base_path, filename)
        logger.debug(f"Writing response content to file: {file_path}")
        with open(file_path, 'wb') as f:
            f.write(response.content)
        return file_path

# --- 新增：定义响应格式化器基类 ---
class BaseResponseFormatter(ABC):
    """响应格式化器基类，定义如何格式化响应和异常。"""
    @abstractmethod
    def format(
        self,
        client_instance: "BaseClient",
        response_or_exception: requests.Response | APIClientError,
        request_config: dict[str, Any] # 传入请求配置，可能需要其中的信息
    ) -> dict[str, Any]:
        """
        格式化响应或异常为统一的字典结构。
        :param client_instance: 调用此格式化器的 BaseClient 实例。
        :param response_or_exception: 成功的 requests.Response 对象或捕获到的 APIClientError 异常。
        :param request_config: 原始请求配置。
        :return: 格式化后的字典。
        """

# --- 新增：实现默认的响应格式化器 ---
class DefaultResponseFormatter(BaseResponseFormatter):
    """默认响应格式化器，生成 {result, code, message, data} 结构。"""
    def format(
        self,
        client_instance: "BaseClient",
        response_or_exception: requests.Response | APIClientError,
        request_config: dict[str, Any]
    ) -> dict[str, Any]:
        formatted_response: dict[str, Any] = {
            "result": False,
            "code": None,
            "message": "",
            "data": None
        }

        if isinstance(response_or_exception, requests.Response):
            # 请求成功
            formatted_response["result"] = True
            formatted_response["code"] = response_or_exception.status_code
            formatted_response["message"] = "Success"

            data = None
            if client_instance.response_parser_instance:
                try:
                    data = client_instance.response_parser_instance.parse(client_instance, response_or_exception)
                except Exception as parse_error:
                     logger.error(f"Response parsing failed during formatting: {parse_error}")
                     formatted_response["result"] = False # 可选：将解析错误也标记为失败
                     formatted_response["message"] = f"Parsing failed: {parse_error}"
            formatted_response["data"] = data

        elif isinstance(response_or_exception, APIClientError):
            # 请求失败
            formatted_response["result"] = False
            if hasattr(response_or_exception, 'status_code') and response_or_exception.status_code:
                formatted_response["code"] = response_or_exception.status_code
            else:
                # 对于非 HTTP 错误，可以定义一个通用代码或留空
                formatted_response["code"] = -1 # 或者 0, None 等
            formatted_response["message"] = str(response_or_exception)
            formatted_response["data"] = None # 失败时数据为 None

        else:
            # 理论上不应该到达这里，但为了健壮性
            formatted_response["result"] = False
            formatted_response["code"] = -2
            formatted_response["message"] = f"Unexpected response/exception type: {type(response_or_exception)}"
            formatted_response["data"] = None

        return formatted_response


class BaseAsyncExecutor:
    """异步执行器基类，定义执行多个请求的接口。"""
    def __init__(self, max_workers: int | None = None, **kwargs):
        self.max_workers = max_workers
        self.executor_kwargs = kwargs

    def execute(
        self, client_instance: "BaseClient", request_list: list[dict[str, Any]]
    ) -> list[dict[str, Any] | Exception]: # 返回类型改为格式化后的字典或 Exception
        """执行多个请求。"""
        raise NotImplementedError("Subclasses must implement the 'execute' method.")

# --- 新增：实现一个基于 ThreadPoolExecutor 的异步执行器 ---
class ThreadPoolAsyncExecutor(BaseAsyncExecutor):
    """使用 ThreadPoolExecutor 实现异步请求的执行器。"""
    def execute(
        self, client_instance: "BaseClient", request_list: list[dict[str, Any]]
    ) -> list[dict[str, Any] | Exception]: # 返回类型改为格式化后的字典
        """异步执行多个请求"""
        logger.info(f"Starting {len(request_list)} asynchronous requests with {self.max_workers} workers")
        results: list[dict[str, Any] | Exception | None] = [None] * len(request_list) # 存储格式化后的数据
        futures: dict[Future, int] = {}
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers
        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            for i, config in enumerate(request_list):
                request_id = f"ASYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
                # 直接传递 _make_request_and_format 方法和参数
                future = executor.submit(client_instance._make_request_and_format, request_id, config)
                futures[future] = i
            for future in as_completed(futures):
                index = futures[future]
                try:
                    result = future.result() # 获取格式化后的数据
                    results[index] = result
                except APIClientError as e: # 捕获未处理的客户端错误
                    logger.error(f"Async request failed unexpectedly: {e}")
                    results[index] = e # 或者格式化这个错误?
                except Exception as e: # 捕获其他意外错误
                    logger.error(f"Unexpected error in async request: {e}")
                    results[index] = APIClientError(f"Unexpected error: {e}") # 包装成客户端错误
        return results # type: ignore

class BaseClient:
    """API 客户端基类，定义通用接口和配置。"""
    base_url: str = ""
    endpoint: str = ""
    method: str = "GET"
    default_timeout: int = 30
    default_retries: int = 3
    default_headers: dict[str, str] = {}
    max_workers: int = 10
    authentication_class: type[AuthBase] | AuthBase | None = None
    executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor | None = ThreadPoolAsyncExecutor
    # --- 新增：定义响应解析器类或实例 ---
    response_parser_class: type[BaseResponseParser] | BaseResponseParser | None = RawResponseParser # 默认返回原始 Response 对象
    # --- 新增：定义响应格式化器类或实例 ---
    response_formatter_class: type[BaseResponseFormatter] | BaseResponseFormatter | None = DefaultResponseFormatter # 默认使用格式化器

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
        retries: int | None = None,
        max_workers: int | None = None,
        authentication: AuthBase | type[AuthBase] | None = None,
        executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
        response_parser: BaseResponseParser | type[BaseResponseParser] | None = None,
        # --- 新增：response_formatter 参数 ---
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
        # --- 新增：解析响应解析器配置 ---
        self.response_parser_instance = self._resolve_response_parser(response_parser)
        # --- 新增：解析响应格式化器配置 ---
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

    def _resolve_response_parser(self, response_parser: BaseResponseParser | type[BaseResponseParser] | None) -> BaseResponseParser | None:
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

    # --- 新增：解析响应格式化器配置 ---
    def _resolve_response_formatter(self, response_formatter: BaseResponseFormatter | type[BaseResponseFormatter] | None) -> BaseResponseFormatter | None:
        """
        解析响应格式化器配置，返回格式化器实例。
        :param response_formatter: 传入的格式化器配置（类或实例）
        :return: BaseResponseFormatter 实例或 None
        """
        # 1. 确定要解析的格式化器源：优先使用传入的，否则使用类属性
        source = response_formatter if response_formatter is not None else getattr(self, "response_formatter_class", None)
        # 2. 如果源是 None，则返回 None (表示不进行额外格式化)
        if source is None:
            return None
        # 3. 解析为实例
        if isinstance(source, type) and issubclass(source, BaseResponseFormatter):
            try:
                return source()
            except Exception as e:
                logger.error(f"Failed to instantiate response formatter class {source.__name__}: {e}")
                # 可以选择抛出错误或返回默认格式化器
                return DefaultResponseFormatter() # 返回默认格式化器
        elif isinstance(source, BaseResponseFormatter):
            return source
        else:
            logger.warning(f"Invalid response formatter item: {source}. Using DefaultResponseFormatter.")
            return DefaultResponseFormatter() # 返回默认格式化器

    def _create_session(self) -> requests.Session:
        """创建并配置请求会话"""
        session = requests.Session()
        session.headers.update(self.session_headers)
        if self.auth_instance:
            session.auth = self.auth_instance
        if self.retries > 0:
            retry_strategy = Retry(
                total=self.retries,
                backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """执行单个 HTTP 请求，返回原始 Response 对象。"""
        method = request_config.get('method', self._class_default_method).upper()
        endpoint = request_config.get('endpoint', self._class_default_endpoint)
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url
        request_kwargs = {
            **self.default_request_kwargs,
            **{k: v for k, v in request_config.items() if k not in ('method', 'endpoint')}
        }
        logger.info(f"[{request_id}] Starting {method} request to {url}")
        logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")
        try:
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **request_kwargs
            )
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
                    f"HTTP {status_code}: {original_exception.response.reason if original_exception.response else 'No response'}",
                    response=original_exception.response
                )
            else:
                converted_exception = APIClientNetworkError(f"Request to {url} failed: {original_exception}")
            logger.error(f"[{request_id}] Request failed: {converted_exception}")
            raise converted_exception

    # --- 新增：封装请求、解析和格式化逻辑 ---
    def _make_request_and_format(self, request_id: str, request_config: dict[str, Any]) -> dict[str, Any]:
        """
        执行请求，根据配置解析响应，并根据配置格式化结果。
        :param request_id: 请求ID。
        :param request_config: 请求配置。
        :return: 格式化后的字典数据。
        """
        # 为 FileWriteResponseParser 传递文件名
        if self.response_parser_instance and isinstance(self.response_parser_instance, FileWriteResponseParser):
             filename_from_config = request_config.get('filename')
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
            if (self.response_parser_instance and
                isinstance(self.response_parser_instance, FileWriteResponseParser) and
                hasattr(self.response_parser_instance, '_current_filename')):
                delattr(self.response_parser_instance, '_current_filename')

        # 如果配置了格式化器，则使用它格式化结果
        if self.response_formatter_instance:
            try:
                formatted_data = self.response_formatter_instance.format(self, response_or_exception, request_config)
                return formatted_data
            except Exception as format_error:
                 logger.error(f"[{request_id}] Response formatting failed: {format_error}")
                 # 格式化失败时的 fallback：返回一个表示格式化错误的字典
                 return {
                     "result": False,
                     "code": -3,
                     "message": f"Formatting failed: {format_error}",
                     "data": None
                 }
        # 如果没有配置格式化器，直接返回原始响应或异常对象
        # 注意：这与同步/异步返回类型不一致，通常应配置格式化器
        # 为了兼容性，可以返回一个基础字典
        elif isinstance(response_or_exception, requests.Response):
            return {
                "result": True,
                "code": response_or_exception.status_code,
                "message": "Success (No formatter)",
                "data": response_or_exception # 或根据解析器处理
            }
        else: # APIClientError
            return {
                "result": False,
                "code": getattr(response_or_exception, 'status_code', -1),
                "message": str(response_or_exception),
                "data": None
            }


    @property
    def full_url(self) -> str:
        """返回当前类定义下的完整 URL"""
        if not self._class_default_endpoint:
            return self.base_url
        return f"{self.base_url}/{self._class_default_endpoint.lstrip('/')}"

    def request(
        self, request_data: dict[str, Any] | list[dict[str, Any]] | None = None, is_async: bool = False
    ) -> dict[str, Any] | list[dict[str, Any] | Exception]: # 返回类型改为格式化后的字典或列表
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

    def _execute_sync_requests(self, request_list: list[dict[str, Any]]) -> list[dict[str, Any] | Exception]: # 返回类型改为格式化后的字典
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

# --- 具体实现 ---
class PizzaAuth(AuthBase):
    """Pizza 认证示例"""
    def __init__(self, username):
        self.username = username

    def __call__(self, r):
        r.headers["X-Pizza"] = self.username
        return r

class BaiduClient(BaseClient):
    """用于访问百度的客户端基类"""
    base_url = "https://www.baidu.com"
    authentication_class = PizzaAuth("默认用户")

class BaiduUser(BaiduClient):
    """用于访问百度用户的客户端"""
    endpoint = "/user"
    method = "GET"

class BaiduUserDetail(BaiduUser):
    """用于访问百度用户详情的客户端"""
    endpoint = "/detail"
    method = "GET"

class HttpbinClient(BaseClient):
    """用于测试的 httpbin.org 客户端"""
    base_url = "https://httpbin.org"

# --- 使用示例 ---
if __name__ == "__main__":
    print("--- 1. 默认行为 (返回格式化后的字典) ---")
    client_default = HttpbinClient()
    result = client_default.request({'endpoint': '/get', 'params': {'key': 'value'}})
    print(f"  Formatted Result: {result}")

    print("\n--- 2. 返回 JSON 数据并格式化 ---")
    client_json = HttpbinClient(response_parser=JSONResponseParser())
    json_result = client_json.request({'endpoint': '/get', 'params': {'key': 'value'}})
    print(f"  Formatted JSON Result: {json_result}")

    print("\n--- 3. 返回 Content 字节数据并格式化 ---")
    client_content = HttpbinClient(response_parser=ContentResponseParser())
    content_result = client_content.request({'endpoint': '/get', 'params': {'key': 'value'}})
    print(f"  Formatted Content Result (Data type): {type(content_result['data'])}, Length: {len(content_result['data']) if content_result['data'] else 0} bytes")

    print("\n--- 4. 处理错误并格式化 ---")
    client_error = HttpbinClient()
    error_result = client_error.request({'endpoint': '/status/404', 'method': 'GET'})
    print(f"  Formatted Error Result: {error_result}")

    print("\n--- 5. 类级别设置 JSON 解析和默认格式化 ---")
    class HttpbinJSONFormattedClient(HttpbinClient):
        response_parser_class = JSONResponseParser
        # response_formatter_class = DefaultResponseFormatter # 默认已设置

    client_class_json = HttpbinJSONFormattedClient()
    json_class_result = client_class_json.request({'endpoint': '/json'})
    print(f"  Class-Level Formatted JSON Result: {json_class_result}")

    print("\n--- 6. 异步请求返回格式化数据 ---")
    client_async = HttpbinClient(response_parser=JSONResponseParser())
    async_results = client_async.request([
        {'endpoint': '/get', 'params': {'id': 1}},
        {'endpoint': '/status/404', 'method': 'GET'},
        {'endpoint': '/uuid'},
    ], is_async=True)
    print("  Async Formatted Results:")
    for i, res in enumerate(async_results):
        # 注意：异步执行器 execute 中已处理意外异常，这里主要是格式化后的 dict 或 Exception
        if isinstance(res, dict):
             print(f"    Async Result {i+1}: {res}")
        elif isinstance(res, Exception):
             print(f"    Async Result {i+1}: Exception - {type(res).__name__}: {res}")
        else:
             print(f"    Async Result {i+1}: Unexpected type {type(res)}: {res}")

    print("\n--- 7. 不使用格式化器 (直接返回原始响应/异常对象，但为了兼容性仍会格式化) ---")
    # 通过传递 None 来禁用格式化器
    client_no_format = HttpbinClient(response_formatter=None)
    no_format_result = client_no_format.request({'endpoint': '/get', 'params': {'key': 'value'}})
    print(f"  No Formatter Result (Fallback): {no_format_result}")
    no_format_error_result = client_no_format.request({'endpoint': '/status/500', 'method': 'GET'})
    print(f"  No Formatter Error Result (Fallback): {no_format_error_result}")
