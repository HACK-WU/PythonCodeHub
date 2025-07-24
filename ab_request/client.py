import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.auth import AuthBase
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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

# --- 新增：定义异常处理器基类 ---
class BaseExceptionHandler:
    """
    异常处理器基类，定义处理特定异常或状态码的接口。
    子类应实现 handle 方法。
    """
    def handle(self, client_instance: 'BaseClient', request_id: str, request_config: dict[str, Any], exception: Exception) -> None:
        """
        处理捕获到的异常。此方法可以记录日志、修改请求配置后重试、
        转换异常类型或执行其他自定义逻辑。
        如果此方法不引发异常，原始异常将被重新引发（除非逻辑中处理了）。
        如果此方法引发新的异常，则新异常会被传播。
        :param client_instance: 调用此处理器的 BaseClient 实例。
        :param request_id: 请求唯一标识符。
        :param request_config: 请求配置字典。
        :param exception: 捕获到的原始异常 (requests.exceptions.RequestException 或其子类)。
        :raises Exception: 可以选择性地引发新异常或重新引发原始异常。
        """
        raise NotImplementedError("Subclasses must implement the 'handle' method.")

# --- 新增：实现一个示例异常处理器 ---
class DefaultExceptionHandler(BaseExceptionHandler):
    """一个默认的异常处理器示例，可以根据状态码进行不同处理"""
    def __init__(self, handled_status_codes: list[int] | None = None, log_only_status_codes: list[int] | None = None):
        """
        :param handled_status_codes: 一组状态码，如果匹配则记录警告日志并抑制异常。
        :param log_only_status_codes: 一组状态码，如果匹配则记录警告日志但不抑制异常。
        """
        self.handled_status_codes = handled_status_codes or []
        self.log_only_status_codes = log_only_status_codes or []

    def handle(self, client_instance: 'BaseClient', request_id: str, request_config: dict[str, Any], exception: Exception) -> None:
        """
        处理异常。
        """
        url = f"{client_instance.base_url}/{request_config.get('endpoint', '').lstrip('/')}" if request_config.get('endpoint') else client_instance.base_url

        # 处理 HTTP 错误
        if isinstance(exception, requests.exceptions.HTTPError):
            status_code = exception.response.status_code if exception.response else 0
            if status_code in self.handled_status_codes:
                logger.warning(f"[{request_id}] Handled HTTP {status_code} for {url}. Suppressing exception.")
                return # 抑制异常
            elif status_code in self.log_only_status_codes:
                logger.warning(f"[{request_id}] Logged HTTP {status_code} for {url}. Re-raising exception.")
                # 不返回，继续传播异常

        # 处理超时
        # elif isinstance(exception, requests.exceptions.Timeout):
        #     logger.warning(f"[{request_id}] Request to {url} timed out. Handling...")
        #     # 可以在这里实现重试逻辑等

        # 处理其他网络错误
        # elif isinstance(exception, requests.exceptions.RequestException):
        #     logger.warning(f"[{request_id}] Network error for {url}: {exception}. Handling...")
        #     # 可以在这里实现特定逻辑

        # 如果没有特定处理，或者需要传播，则不执行任何操作，让原始异常继续传播
        logger.debug(f"[{request_id}] Exception handler did not suppress the exception for {url}.")

# --- 新增：定义异步执行器基类 ---
class BaseAsyncExecutor:
    """
    异步执行器基类，定义执行多个请求的接口。
    子类应实现 execute 方法。
    """
    def __init__(self, max_workers: int | None = None, **kwargs):
        """
        初始化执行器。
        :param max_workers: 最大工作线程/进程数。
        :param kwargs: 其他传递给具体执行器的参数。
        """
        self.max_workers = max_workers
        self.executor_kwargs = kwargs

    def execute(self, client_instance: 'BaseClient', request_list: list[dict[str, Any]]) -> list[requests.Response | Exception]:
        """
        执行多个请求。
        :param client_instance: 调用此执行器的 BaseClient 实例。
        :param request_list: 请求配置列表。
        :return: 响应对象或异常的列表。
        """
        raise NotImplementedError("Subclasses must implement the 'execute' method.")

# --- 新增：实现一个基于 ThreadPoolExecutor 的异步执行器 ---
class ThreadPoolAsyncExecutor(BaseAsyncExecutor):
    """
    使用 ThreadPoolExecutor 实现异步请求的执行器。
    """
    def execute(self, client_instance: 'BaseClient', request_list: list[dict[str, Any]]) -> list[requests.Response | Exception]:
        """异步执行多个请求"""
        logger.info(f"Starting {len(request_list)} asynchronous requests with {self.max_workers} workers")
        responses: list[requests.Response | Exception | None] = [None] * len(request_list)
        futures: dict[Future, int] = {}
        # 使用传入的 max_workers 或默认值
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers
        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            # 提交所有任务
            for i, config in enumerate(request_list):
                request_id = f"ASYNC-{i+1}-{uuid.uuid4().hex[:4]}"
                # 直接传递 _make_request 方法和参数
                future = executor.submit(client_instance._make_request, request_id, config)
                futures[future] = i
            # 收集结果
            for future in as_completed(futures):
                index = futures[future]
                try:
                    response = future.result()
                    responses[index] = response
                except APIClientError as e:
                    logger.error(f"Async request failed: {e}")
                    responses[index] = e
        # 确保返回列表类型匹配
        return responses # type: ignore

class BaseClient:
    """
    API 客户端基类，定义通用接口和配置。
    子类应定义 base_url, 可选 endpoint 和 method。
    """
    base_url: str = ""  # 必须在子类中定义
    endpoint: str = ""  # 子路径，可选
    method: str = "GET" # 默认方法
    default_timeout: int = 30
    default_retries: int = 3
    default_headers: dict[str, str] = {}
    max_workers: int = 10  # 异步请求最大线程数
    authentication_class: type[AuthBase] | AuthBase | None = None  # 认证类或实例
    # --- 新增：定义异步执行器类或实例 ---
    executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor | None = ThreadPoolAsyncExecutor # 默认使用线程池
    # --- 新增：定义异常处理器类或实例 ---
    exception_handler_class: type[BaseExceptionHandler] | BaseExceptionHandler | None = None # 默认不处理

    def __init__(self, default_headers: dict[str, str] | None = None,
                 timeout: int | None = None, retries: int | None = None,
                 max_workers: int | None = None,
                 authentication: AuthBase | type[AuthBase] | None = None,
                 executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None, # --- 新增：executor 参数 ---
                 exception_handler: BaseExceptionHandler | type[BaseExceptionHandler] | None = None, # --- 新增：exception_handler 参数 ---
                 **kwargs):
        """
        初始化客户端。
        :param default_headers: 默认请求头
        :param timeout: 超时时间 (秒)
        :param retries: 重试次数
        :param max_workers: 异步请求最大线程数
        :param authentication: 认证类或实例，覆盖类属性
        :param executor: 异步执行器类或实例，覆盖类属性 --- 新增 ---
        :param exception_handler: 异常处理器类或实例，覆盖类属性 --- 新增 ---
        :param kwargs: 其他传递给 requests.Session.request 的默认参数
        """
        # 确定 base_url (必须来自类属性)
        self.base_url = getattr(self, 'base_url', "").rstrip('/')
        if not self.base_url:
            raise APIClientValidationError("base_url must be provided as a class attribute.")
        # 确定 endpoint 和 method (来自类属性)
        self._class_default_endpoint = getattr(self, 'endpoint', "")
        self._class_default_method = getattr(self, 'method', "GET").upper()
        # 运行时配置
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.retries = retries if retries is not None else self.default_retries
        if max_workers is not None:
            self.max_workers = max_workers
        # 处理认证
        self.auth_instance = self._resolve_authentication(authentication)
        # --- 新增：处理异步执行器 ---
        self.executor_instance = self._resolve_executor(executor)
        # --- 新增：处理异常处理器 ---
        self.exception_handler_instance = self._resolve_exception_handler(exception_handler)

        # 合并类默认头、实例化时给的头和 kwargs 中可能的 headers
        self.session_headers = {
            **self.default_headers,
            **(default_headers or {}),
            **kwargs.pop('headers', {})  # 从 kwargs 中取出 headers
        }
        # 存储其他可能的默认 requests 参数
        self.default_request_kwargs = kwargs
        # 创建并配置 Session
        self.session = self._create_session()

    def _resolve_authentication(self, authentication: AuthBase | type[AuthBase] | None) -> AuthBase | None:
        """解析认证配置，返回认证实例或None"""
        # 优先使用传入的认证
        if authentication is not None:
            if isinstance(authentication, type) and issubclass(authentication, AuthBase):
                return authentication()  # 实例化认证类
            elif isinstance(authentication, AuthBase):
                return authentication
            else:
                raise APIClientValidationError("authentication must be an AuthBase subclass or instance")
        # 检查类属性
        class_auth = getattr(self, 'authentication_class', None)
        if class_auth is None:
            return None
        if isinstance(class_auth, type) and issubclass(class_auth, AuthBase):
            return class_auth()  # 实例化认证类
        elif isinstance(class_auth, AuthBase):
            return class_auth
        else:
            raise APIClientValidationError("authentication_class must be an AuthBase subclass or instance")

    # --- 新增：解析异步执行器配置 ---
    def _resolve_executor(self, executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None) -> BaseAsyncExecutor:
        """解析异步执行器配置，返回执行器实例"""
        # 优先使用传入的执行器
        if executor is not None:
            if isinstance(executor, type) and issubclass(executor, BaseAsyncExecutor):
                # 如果传入的是类，需要实例化。这里传递 max_workers
                return executor(max_workers=self.max_workers)
            elif isinstance(executor, BaseAsyncExecutor):
                return executor
            else:
                raise APIClientValidationError("executor must be a BaseAsyncExecutor subclass or instance")
        # 检查类属性
        class_executor = getattr(self, 'executor_class', None)
        if class_executor is None:
             # 如果没有默认执行器类，可以返回默认实现的实例或抛出异常
             # 这里我们实例化默认的 ThreadPoolAsyncExecutor
             return ThreadPoolAsyncExecutor(max_workers=self.max_workers)
        if isinstance(class_executor, type) and issubclass(class_executor, BaseAsyncExecutor):
            # 实例化类属性定义的执行器类
            return class_executor(max_workers=self.max_workers)
        elif isinstance(class_executor, BaseAsyncExecutor):
            return class_executor
        else:
            raise APIClientValidationError("executor_class must be a BaseAsyncExecutor subclass or instance")

    # --- 新增：解析异常处理器配置 ---
    def _resolve_exception_handler(self, exception_handler: BaseExceptionHandler | type[BaseExceptionHandler] | None) -> BaseExceptionHandler | None:
        """解析异常处理器配置，返回处理器实例"""
        # 优先使用传入的处理器
        if exception_handler is not None:
            if isinstance(exception_handler, type) and issubclass(exception_handler, BaseExceptionHandler):
                # 如果传入的是类，需要实例化。
                return exception_handler() # 可以根据需要传递参数
            elif isinstance(exception_handler, BaseExceptionHandler):
                return exception_handler
            else:
                raise APIClientValidationError("exception_handler must be a BaseExceptionHandler subclass or instance")
        # 检查类属性
        class_exception_handler = getattr(self, 'exception_handler_class', None)
        if class_exception_handler is None:
            return None # 没有默认处理器
        if isinstance(class_exception_handler, type) and issubclass(class_exception_handler, BaseExceptionHandler):
            # 实例化类属性定义的处理器类
            return class_exception_handler() # 可以根据需要传递参数
        elif isinstance(class_exception_handler, BaseExceptionHandler):
            return class_exception_handler
        else:
            raise APIClientValidationError("exception_handler_class must be a BaseExceptionHandler subclass or instance")


    def _create_session(self) -> requests.Session:
        """创建并配置请求会话"""
        session = requests.Session()
        session.headers.update(self.session_headers)
        # 设置认证
        if self.auth_instance:
            session.auth = self.auth_instance
        # 配置重试策略
        if self.retries > 0:
            retry_strategy = Retry(
                total=self.retries,
                backoff_factor=0.5,  # 增加退避因子
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],
                raise_on_status=False
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """
        执行单个 HTTP 请求。
        :param request_id: 请求唯一标识符
        :param request_config: 请求配置字典
        :return: requests.Response 对象
        """
        # 从配置中提取参数，未提供则使用类默认值
        method = request_config.get('method', self._class_default_method).upper()
        endpoint = request_config.get('endpoint', self._class_default_endpoint)
        # 构建完整 URL
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url
        # 合并默认请求参数和本次调用的参数
        request_kwargs = {
            **self.default_request_kwargs,
            **{k: v for k, v in request_config.items() if k not in ('method', 'endpoint')}
        }
        logger.info(f"[{request_id}] Starting {method} request to {url}")
        logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")
        try:
            # 使用 Session 发起请求
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout,
                **request_kwargs
            )
            # 记录响应摘要信息
            logger.info(f"[{request_id}] Received {response.status_code} response")
            logger.debug(f"[{request_id}] Response headers: {response.headers}")
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout as e:
            logger.error(f"[{request_id}] Request timed out: {e}")
            # --- 新增：调用异常处理器 ---
            if self.exception_handler_instance:
                try:
                    self.exception_handler_instance.handle(self, request_id, request_config, e)
                except Exception as handler_exception:
                    # 如果处理器本身抛出异常，则传播处理器异常
                    logger.error(f"[{request_id}] Exception handler raised an error: {handler_exception}")
                    raise handler_exception
            # 如果处理器没有引发新异常或抑制原异常，则传播原始超时异常
            raise APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s") from e

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else 0
            logger.error(f"[{request_id}] HTTP error {status_code}: {e}")
            # --- 新增：调用异常处理器 ---
            if self.exception_handler_instance:
                try:
                    self.exception_handler_instance.handle(self, request_id, request_config, e)
                except Exception as handler_exception:
                    # 如果处理器本身抛出异常，则传播处理器异常
                    logger.error(f"[{request_id}] Exception handler raised an error: {handler_exception}")
                    raise handler_exception
            # 如果处理器没有引发新异常或抑制原异常，则传播原始 HTTP 异常
            raise APIClientHTTPError(
                f"HTTP {status_code}: {e.response.reason if e.response else 'No response'}",
                response=e.response
            ) from e

        except requests.exceptions.RequestException as e: # 捕获其他网络相关异常
            logger.error(f"[{request_id}] Network error: {e}")
            # --- 新增：调用异常处理器 ---
            if self.exception_handler_instance:
                try:
                    self.exception_handler_instance.handle(self, request_id, request_config, e)
                except Exception as handler_exception:
                    # 如果处理器本身抛出异常，则传播处理器异常
                    logger.error(f"[{request_id}] Exception handler raised an error: {handler_exception}")
                    raise handler_exception
            # 如果处理器没有引发新异常或抑制原异常，则传播原始网络异常
            raise APIClientNetworkError(f"Request to {url} failed: {e}") from e

    @property
    def full_url(self) -> str:
        """返回当前类定义下的完整 URL"""
        if not self._class_default_endpoint:
            return self.base_url
        return f"{self.base_url}/{self._class_default_endpoint.lstrip('/')}"

    def request(self, request_data: dict[str, Any] | list[dict[str, Any]] | None = None,
                is_async: bool = False) -> requests.Response | list[requests.Response | Exception]:
        """
        执行请求。
        :param request_data: 请求配置
        :param is_async: 是否异步执行
        :return: 响应对象或列表
        :raises APIClientValidationError: 输入验证失败
        """
        # 处理空请求配置
        if request_data is None:
            request_data = {}
        # 单次请求处理
        if isinstance(request_data, dict):
            request_id = f"REQ-{uuid.uuid4().hex[:6]}"
            try:
                return self._make_request(request_id, request_data)
            except APIClientError as e:
                if is_async:
                    return e  # 异步模式下返回异常对象
                raise  # 同步模式下重新抛出异常
        # 多次请求处理
        if isinstance(request_data, list):
            if not request_data:
                logger.warning("Empty request list provided")
                return []
            if is_async:
                return self.executor_instance.execute(self, request_data)
            return self._execute_sync_requests(request_data)
        raise APIClientValidationError("request_data must be a dictionary or a list of dictionaries")

    def _execute_sync_requests(self, request_list: list[dict[str, Any]]) -> list[requests.Response | Exception]:
        """同步执行多个请求"""
        logger.info(f"Starting {len(request_list)} synchronous requests")
        responses = []
        for i, config in enumerate(request_list):
            request_id = f"SYNC-{i+1}-{uuid.uuid4().hex[:4]}"
            try:
                response = self._make_request(request_id, config)
                responses.append(response)
            except APIClientError as e:
                logger.error(f"[{request_id}] Request failed: {e}")
                responses.append(e)
        return responses

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
        # 添加自定义头部
        r.headers["X-Pizza"] = self.username
        return r

class BaiduClient(BaseClient):
    """用于访问百度的客户端基类"""
    base_url = 'https://www.baidu.com'
    authentication_class = PizzaAuth("默认用户")  # 类级别认证

class BaiduUser(BaiduClient):
    """用于访问百度用户的客户端"""
    endpoint = '/user'
    method = 'GET'

class BaiduUserDetail(BaiduUser):
    """用于访问百度用户详情的客户端"""
    endpoint = '/detail'
    method = 'GET'

class HttpbinClient(BaseClient):
    """用于测试的 httpbin.org 客户端"""
    base_url = 'https://httpbin.org'

# --- 使用示例：结合异常处理器 ---
if __name__ == "__main__":
    print("--- 9. 使用类级别异常处理器 (处理 404) ---")
    class HttpbinClientWithHandler(HttpbinClient):
        """使用自定义异常处理器的客户端"""
        exception_handler_class = DefaultExceptionHandler(handled_status_codes=[404], log_only_status_codes=[500])

    httpbin_with_handler = HttpbinClientWithHandler()

    try:
        # 这个请求会返回 404，应该被处理器抑制
        response = httpbin_with_handler.request(request_data={'endpoint': '/status/404', 'method': 'GET'})
        print("Unexpected: Got a response for 404")
    except APIClientHTTPError as e:
        print(f"Expected: Got APIClientHTTPError for 404: {e}")
    except Exception as e:
         print(f"Unexpected exception type: {e}")

    print("\n--- 10. 使用实例级别异常处理器覆盖 (处理 500) ---")
    # 创建一个实例级别的处理器，只处理 500
    instance_handler = DefaultExceptionHandler(handled_status_codes=[500])
    httpbin_with_instance_handler = HttpbinClient(exception_handler=instance_handler) # 使用基类，实例级别覆盖

    try:
        # 这个请求会返回 500，应该被实例处理器抑制
        response = httpbin_with_instance_handler.request(request_data={'endpoint': '/status/500', 'method': 'GET'})
        print("Unexpected: Got a response for 500")
    except APIClientHTTPError as e:
        print(f"Expected: Got APIClientHTTPError for 500: {e}")
    except Exception as e:
         print(f"Unexpected exception type: {e}")

    try:
        # 这个请求会返回 404，实例处理器不处理，应该抛出异常
        response = httpbin_with_instance_handler.request(request_data={'endpoint': '/status/404', 'method': 'GET'})
        print("Unexpected: Got a response for 404")
    except APIClientHTTPError as e:
         print(f"Expected: Got APIClientHTTPError for 404 (not handled by instance handler): {e}")
    except Exception as e:
         print(f"Unexpected exception type: {e}")

    print("\n--- 11. 异步请求中使用异常处理器 ---")
    httpbin_async_with_handler = HttpbinClientWithHandler() # 使用上面定义的带处理器的类
    try:
        responses = httpbin_async_with_handler.request(
            request_data=[
                {'endpoint': '/status/200', 'method': 'GET'},
                {'endpoint': '/status/404', 'method': 'GET'}, # 应该被抑制
                {'endpoint': '/status/500', 'method': 'GET'}  # 应该被记录但不抑制
            ],
            is_async=True
        )
        print(f"Received {len(responses)} async responses (with handler):")
        for i, res_or_exc in enumerate(responses):
            if isinstance(res_or_exc, requests.Response):
                print(f"  Response {i+1}: Status {res_or_exc.status_code}")
            elif isinstance(res_or_exc, APIClientError):
                 # 500 应该在这里，因为只记录不抑制
                 print(f"  Response {i+1}: Exception - {type(res_or_exc).__name__}: {res_or_exc}")
            else:
                 print(f"  Response {i+1}: Unexpected type {type(res_or_exc)}")
    except APIClientError as e:
        print(f"Async test with handler failed unexpectedly: {e}")
