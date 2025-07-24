import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

# from typing import Any,Optional,Union,Callable,Type,List
# from typing import Any,Optional,Union,Callable,Type,List
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


# --- 新增：定义异常处理器基类 ---
class BaseExceptionHandler:
    """
    异常处理器基类，定义处理特定异常或状态码的接口。
    子类应实现 handle 方法。
    """

    def handle(
        self, client_instance: "BaseClient", request_id: str, request_config: dict[str, Any], exception: Exception
    ) -> None:
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


class DefaultExceptionHandler(BaseExceptionHandler):
    """示例：根据状态码决定是记录日志还是抑制异常"""
    def __init__(self, handled_status_codes: list[int] | None = None, log_only_status_codes: list[int] | None = None):
        self.handled_status_codes = handled_status_codes or []
        self.log_only_status_codes = log_only_status_codes or []

    def handle(self, client_instance: 'BaseClient', request_id: str, request_config: dict[str, Any], exception: Exception) -> None:
        url = f"{client_instance.base_url}/{request_config.get('endpoint', '').lstrip('/')}" if request_config.get('endpoint') else client_instance.base_url

        if isinstance(exception, requests.exceptions.HTTPError):
            status_code = exception.response.status_code if exception.response else 0
            if status_code in self.handled_status_codes:
                logger.info(f"[{request_id}] Handler suppressed HTTP {status_code} for {url}.")
                # 正常返回表示已处理
                return
            elif status_code in self.log_only_status_codes:
                logger.warning(f"[{request_id}] Handler logged HTTP {status_code} for {url}. Exception will be re-raised.")
                # 不返回，让调用者决定是否继续

        # 对于未处理的情况，可以选择抛出原始异常或让它正常返回（如果调用者逻辑允许）
        # 这里我们选择不主动抛出，让调用 _resolve_exception_handler 的逻辑决定是否继续下一个处理器
        logger.debug(f"[{request_id}] DefaultExceptionHandler did not suppress the exception for {url}.")

class RetryOnSpecificError(BaseExceptionHandler):
    """示例：对特定错误尝试重试逻辑（简化版，实际可能需要更复杂的状态管理）"""
    def __init__(self, retryable_status_codes: list[int] | None = None, max_retries: int = 1):
        self.retryable_status_codes = retryable_status_codes or [502, 503, 504]
        self.max_retries = max_retries

    def handle(self, client_instance: 'BaseClient', request_id: str, request_config: dict[str, Any], exception: Exception) -> None:
        # 注意：在当前同步 _make_request 结构中直接重试比较复杂且可能阻塞。
        # 更好的做法可能是在更高层（如 request 方法）或异步执行器中处理重试。
        # 这里仅作概念演示：记录日志并表明希望重试（但实际不执行）。
        if isinstance(exception, requests.exceptions.HTTPError):
            status_code = exception.response.status_code if exception.response else 0
            if status_code in self.retryable_status_codes:
                logger.info(f"[{request_id}] RetryOnSpecificError: Detected retryable status {status_code}. "
                            f"In a full implementation, this would trigger a retry (max {self.max_retries}).")
                # 在当前结构下，我们可以通过不抑制异常来表明需要（在上层）处理重试或失败。
                # 或者，如果这个处理器认为它“处理”了（例如，记录了重试意图），它可以正常返回。
                # 这取决于具体的设计意图。这里我们选择不抑制，让调用者决定。
        # 对于其他异常，不处理，正常返回让调用者决定
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

    def execute(
        self, client_instance: "BaseClient", request_list: list[dict[str, Any]]
    ) -> list[requests.Response | Exception]:
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

    def execute(
        self, client_instance: "BaseClient", request_list: list[dict[str, Any]]
    ) -> list[requests.Response | Exception]:
        """异步执行多个请求"""
        logger.info(f"Starting {len(request_list)} asynchronous requests with {self.max_workers} workers")
        responses: list[requests.Response | Exception | None] = [None] * len(request_list)
        futures: dict[Future, int] = {}
        # 使用传入的 max_workers 或默认值
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers
        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            # 提交所有任务
            for i, config in enumerate(request_list):
                request_id = f"ASYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
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
        return responses  # type: ignore


class BaseClient:
    """
    API 客户端基类，定义通用接口和配置。
    子类应定义 base_url, 可选 endpoint 和 method。
    """

    base_url: str = ""  # 必须在子类中定义
    endpoint: str = ""  # 子路径，可选
    method: str = "GET"  # 默认方法
    default_timeout: int = 30
    default_retries: int = 3
    default_headers: dict[str, str] = {}
    max_workers: int = 10  # 异步请求最大线程数
    authentication_class: type[AuthBase] | AuthBase | None = None  # 认证类或实例
    # --- 新增：定义异步执行器类或实例 ---
    executor_class: type[BaseAsyncExecutor] | BaseAsyncExecutor | None = ThreadPoolAsyncExecutor  # 默认使用线程池
    # --- 新增：定义异常处理器类或实例 ---
    exception_handler_class: type[BaseExceptionHandler] | BaseExceptionHandler | list[type[BaseExceptionHandler] | BaseExceptionHandler] | None = None

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
        retries: int | None = None,
        max_workers: int | None = None,
        authentication: AuthBase | type[AuthBase] | None = None,
        executor: BaseAsyncExecutor | type[BaseAsyncExecutor] | None = None,
        # --- 修改：exception_handler 参数类型 ---
        exception_handler: BaseExceptionHandler | type[BaseExceptionHandler] | list[BaseExceptionHandler | type[BaseExceptionHandler]] | None = None,
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
        # --- 修改：解析异常处理器列表 ---
        self.exception_handler_instances = self._resolve_exception_handler(exception_handler)
        self.session_headers = {**self.default_headers, **(default_headers or {}), **kwargs.pop("headers", {})}
        self.default_request_kwargs = kwargs
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
        class_auth = getattr(self, "authentication_class", None)
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
        class_executor = getattr(self, "executor_class", None)
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
    def _resolve_exception_handler(
        self,
        exception_handler: BaseExceptionHandler | type[BaseExceptionHandler] | list[BaseExceptionHandler | type[BaseExceptionHandler]] | None,
    ) -> list[BaseExceptionHandler]:
        """
        解析异常处理器配置，返回处理器实例列表。
        :param exception_handler: 传入的处理器配置（类、实例或列表）
        :return: BaseExceptionHandler 实例列表
        """
        handlers_to_resolve = []
        resolved_handlers = []

        # 1. 确定要解析的处理器源：优先使用传入的，否则使用类属性
        source = exception_handler if exception_handler is not None else getattr(self, "exception_handler_class", None)

        # 2. 标准化为列表形式
        if source is None:
            return []  # 没有配置处理器
        if not isinstance(source, list):
            handlers_to_resolve = [source]  # 包装成列表
        else:
            handlers_to_resolve = source

        # 3. 遍历列表，解析每个元素为实例
        for handler in handlers_to_resolve:
            if isinstance(handler, type) and issubclass(handler, BaseExceptionHandler):
                try:
                    # 尝试实例化，不带参数。如果需要参数，应传入实例。
                    resolved_handlers.append(handler())
                except Exception as e:
                    logger.error(f"Failed to instantiate exception handler class {handler.__name__}: {e}")
                    # 可以选择跳过或抛出错误，这里选择跳过
            elif isinstance(handler, BaseExceptionHandler):
                resolved_handlers.append(handler)
            else:
                logger.warning(f"Invalid exception handler item (skipped): {handler}")
                # 可以选择抛出 APIClientValidationError

        return resolved_handlers

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
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        return session

    def _make_request(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """
        执行单个 HTTP 请求。
        """

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
        except requests.exceptions.RequestException as original_exception: # 捕获所有 requests 异常
            # --- 修改：循环处理异常 ---
            converted_exception: APIClientError # 用于存储最终可能抛出的转换后异常
            if isinstance(original_exception, requests.exceptions.Timeout):
                converted_exception = APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s")
            elif isinstance(original_exception, requests.exceptions.HTTPError):
                status_code = original_exception.response.status_codle if original_exception.response else 0
                converted_exception = APIClientHTTPError(
                    f"HTTP {status_code}: {original_exception.response.reason if original_exception.response else 'No response'}",
                    response=original_exception.response
                )

            else:
                converted_exception = APIClientNetworkError(f"Request to {url} failed: {original_exception}")

            logger.error(f"[{request_id}] Request failed: {converted_exception}")

            # 如果有配置的异常处理器，则尝试依次调用
            if self.exception_handler_instances:
                for i, handler_instance in enumerate(self.exception_handler_instances):
                    try:
                        logger.debug(f"[{request_id}] Trying exception handler {i+1}: {type(handler_instance).__name__}")
                        handler_instance.handle(self, request_id, request_config, original_exception)
                        # 如果 handle 正常返回，认为异常已被处理
                        logger.info(f"[{request_id}] Exception handled successfully by {type(handler_instance).__name__}.")

                        break # 处理器正常返回，认为已处理（至少介入），停止尝试其他处理器

                    except (requests.exceptions.RequestException, APIClientError) as handler_raised_exception:
                        # 如果处理器抛出原始异常或 API 客户端异常，视为未处理，继续下一个处理器
                        # 区分是原始异常还是转换后的异常可能有用，但为简化，统一对待
                        if handler_raised_exception is original_exception:
                             logger.debug(f"[{request_id}] Handler {type(handler_instance).__name__} re-raised the original exception. Trying next handler.")
                        else:
                             logger.debug(f"[{request_id}] Handler {type(handler_instance).__name__} raised an APIClientError. Trying next handler.")
                        continue # 继续循环，尝试下一个处理器

                # 循环正常结束或 break 后，执行到这里
                # 根据上面的逻辑，总是会抛出 converted_exception
                # （除非在 break 后有特殊处理，但按标准语义，我们抛出）
            # 如果没有配置处理器，或所有处理器都尝试过（没有 break），则抛出转换后的异常
            raise converted_exception # 抛出最初转换的异常

    @property
    def full_url(self) -> str:
        """返回当前类定义下的完整 URL"""
        if not self._class_default_endpoint:
            return self.base_url
        return f"{self.base_url}/{self._class_default_endpoint.lstrip('/')}"

    def request(
        self, request_data: dict[str, Any] | list[dict[str, Any]] | None = None, is_async: bool = False
    ) -> requests.Response | list[requests.Response | Exception]:
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
            request_id = f"SYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
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

    base_url = "https://www.baidu.com"
    authentication_class = PizzaAuth("默认用户")  # 类级别认证


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


# --- 使用示例：结合异常处理器 ---

if __name__ == "__main__":
    print("--- 9. 使用类级别异常处理器列表 ---")
    # 定义一个组合处理器：先尝试抑制 404，再记录 500
    class HttpbinClientWithHandlerList(HttpbinClient):
        """使用异常处理器列表的客户端"""
        # 处理器列表：先用 DefaultExceptionHandler 抑制 404，再用另一个实例记录 500
        exception_handler_class = [
            DefaultExceptionHandler(handled_status_codes=[404]), # 抑制 404
            DefaultExceptionHandler(log_only_status_codes=[500]), # 记录 500
            # 可以添加更多处理器
        ]

    httpbin_with_handler_list = HttpbinClientWithHandlerList()

    print("  a. 测试 404 (应被第一个处理器抑制日志，但仍抛出异常):")
    try:
        response = httpbin_with_handler_list.request(request_data={'endpoint': '/status/404', 'method': 'GET'})
        print("    Unexpected: Got a response for 404")
    except APIClientHTTPError as e:
        print(f"    Expected: Got APIClientHTTPError for 404: {e}. Note: Exception was processed (suppressed logging) but still raised.")

    print("\n  b. 测试 500 (应被第二个处理器记录，但仍抛出异常):")
    try:
        response = httpbin_with_handler_list.request(request_data={'endpoint': '/status/500', 'method': 'GET'})
        print("    Unexpected: Got a response for 500")
    except APIClientHTTPError as e:
         print(f"    Expected: Got APIClientHTTPError for 500: {e}. Note: Exception was processed (logged) but still raised.")


    print("\n--- 10. 使用实例级别异常处理器列表覆盖 ---")
    # 创建一个实例级别的处理器列表，只处理 500 和超时
    instance_handler_list = [
        DefaultExceptionHandler(handled_status_codes=[500]), # 抑制 500
        # 假设我们有一个处理超时的处理器
        type('TimeoutHandler', (BaseExceptionHandler,), {
            'handle': lambda self, client, rid, req, exc: (
                logger.info(f"[{rid}] TimeoutHandler: Notifying for timeout.") if isinstance(exc, requests.exceptions.Timeout) else None
            )
        })()
    ]
    httpbin_with_instance_handler_list = HttpbinClient(exception_handler=instance_handler_list) # 基类，实例级别覆盖

    print("  a. 测试 500 (应被实例列表的第一个处理器抑制):")
    try:
        response = httpbin_with_instance_handler_list.request(request_data={'endpoint': '/status/500', 'method': 'GET'})
        print("    Unexpected: Got a response for 500")
    except APIClientHTTPError as e:
        print(f"    Expected: Got APIClientHTTPError for 500: {e}. Note: Exception was processed (suppressed) by instance handler.")

    print("\n  b. 测试 404 (实例列表不处理，应直接抛出):")
    try:
        response = httpbin_with_instance_handler_list.request(request_data={'endpoint': '/status/404', 'method': 'GET'})
        print("    Unexpected: Got a response for 404")
    except APIClientHTTPError as e:
         print(f"    Expected: Got APIClientHTTPError for 404 (not handled by instance handler list): {e}")


    print("\n--- 11. 异步请求中使用异常处理器列表 ---")
    httpbin_async_with_handler_list = HttpbinClientWithHandlerList() # 使用上面定义的带处理器列表的类
    try:
        responses = httpbin_async_with_handler_list.request(
            request_data=[
                {'endpoint': '/status/200', 'method': 'GET'},
                {'endpoint': '/status/404', 'method': 'GET'}, # 应该被第一个处理器处理
                {'endpoint': '/status/500', 'method': 'GET'}  # 应该被第二个处理器处理
            ],
            is_async=True
        )
        print(f"  Received {len(responses)} async responses (with handler list):")
        for i, res_or_exc in enumerate(responses):
            if isinstance(res_or_exc, requests.Response):
                print(f"    Response {i+1}: Status {res_or_exc.status_code}")
            elif isinstance(res_or_exc, APIClientError):
                 print(f"    Response {i+1}: Exception - {type(res_or_exc).__name__}: {res_or_exc}")
            else:
                 print(f"    Response {i+1}: Unexpected type {type(res_or_exc)}")
    except APIClientError as e:
        print(f"  Async test with handler list failed unexpectedly: {e}")

    # --- 额外示例：展示处理器顺序和中断 ---
    print("\n--- 12. 展示处理器列表顺序和中断 ---")
    class FirstHandler(BaseExceptionHandler):
        def handle(self, client_instance, request_id, request_config, exception):
            print(f"    [{request_id}] FirstHandler: Called")
            if isinstance(exception, requests.exceptions.HTTPError) and exception.response and exception.response.status_code == 418:
                print(f"    [{request_id}] FirstHandler: I know how to handle 418, but I will raise the original exception to let the next handler try.")
                raise exception # 抛出原异常，让下一个处理器处理
            print(f"    [{request_id}] FirstHandler: I don't know how to handle this, raising a generic APIClientError to stop the chain.")
            raise APIClientError("FirstHandler could not process") # 抛出 APIClientError，停止链

    class SecondHandler(BaseExceptionHandler):
        def handle(self, client_instance, request_id, request_config, exception):
            print(f"    [{request_id}] SecondHandler: Called")
            if isinstance(exception, requests.exceptions.HTTPError) and exception.response and exception.response.status_code == 418:
                print(f"    [{request_id}] SecondHandler: I will handle 418. Logging and suppressing (by returning normally).")
                # 正常返回，表示已处理，中断处理器链
                return
            print(f"    [{request_id}] SecondHandler: I don't handle this.")
            raise exception # 或者 raise APIClientError("...")

    class HttpClientForOrderTest(HttpbinClient):
         exception_handler_class = [FirstHandler(), SecondHandler()]

    order_test_client = HttpClientForOrderTest()
    print("  a. 测试 418:")
    try:
        # httpbin /status/418 返回 418 I'm a teapot
        response = order_test_client.request(request_data={'endpoint': '/status/418', 'method': 'GET'})
        print("    Unexpected: Got a response for 418")
    except APIClientHTTPError as e:
        # 尽管 SecondHandler 正常返回，但根据当前 _make_request 实现，converted_exception 仍会被抛出
        # 因为处理器正常返回只是中断了链，但不改变 _make_request 必须抛出的结果
        print(f"    Got APIClientHTTPError for 418: {e}")
        print("    (Note: SecondHandler handled it internally, but _make_request still reports the original failure)")
