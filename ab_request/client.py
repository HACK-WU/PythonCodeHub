# api_client_v6_optimized.py
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
from requests.adapters import HTTPAdapter
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

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        timeout: int | None = None,
        retries: int | None = None,
        max_workers: int | None = None,
        **kwargs,
    ):
        """
        初始化客户端。

        :param default_headers: 默认请求头
        :param timeout: 超时时间 (秒)
        :param retries: 重试次数
        :param max_workers: 异步请求最大线程数
        :param kwargs: 其他传递给 requests.Session.request 的默认参数
        """
        # 确定 base_url (必须来自类属性)
        self.base_url = getattr(self, "base_url", "").rstrip("/")
        if not self.base_url:
            raise APIClientValidationError("base_url must be provided as a class attribute.")

        # 确定 endpoint 和 method (来自类属性)
        self._class_default_endpoint = getattr(self, "endpoint", "")
        self._class_default_method = getattr(self, "method", "GET").upper()

        # 运行时配置
        self.timeout = timeout if timeout is not None else self.default_timeout
        self.retries = retries if retries is not None else self.default_retries

        if max_workers is not None:
            self.max_workers = max_workers

        # 合并类默认头、实例化时给的头和 kwargs 中可能的 headers
        self.session_headers = {
            **self.default_headers,
            **(default_headers or {}),
            **kwargs.pop("headers", {}),  # 从 kwargs 中取出 headers
        }

        # 存储其他可能的默认 requests 参数
        self.default_request_kwargs = kwargs

        # 创建并配置 Session
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建并配置请求会话"""
        session = requests.Session()
        session.headers.update(self.session_headers)

        # 配置重试策略
        if self.retries > 0:
            retry_strategy = Retry(
                total=self.retries,
                backoff_factor=0.5,  # 增加退避因子
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=[
                    "HEAD",
                    "GET",
                    "PUT",
                    "DELETE",
                    "OPTIONS",
                    "TRACE",
                    "POST",
                ],
                raise_on_status=False,
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
        method = request_config.get("method", self._class_default_method).upper()
        endpoint = request_config.get("endpoint", self._class_default_endpoint)

        # 构建完整 URL
        url = f"{self.base_url}/{endpoint.lstrip('/')}" if endpoint else self.base_url

        # 合并默认请求参数和本次调用的参数
        request_kwargs = {
            **self.default_request_kwargs,
            **{k: v for k, v in request_config.items() if k not in ("method", "endpoint")},
        }

        logger.info(f"[{request_id}] Starting {method} request to {url}")
        logger.debug(f"[{request_id}] Request kwargs: {request_kwargs}")

        try:
            # 使用 Session 发起请求
            response = self.session.request(method=method, url=url, timeout=self.timeout, **request_kwargs)

            # 记录响应摘要信息
            logger.info(f"[{request_id}] Received {response.status_code} response")
            logger.debug(f"[{request_id}] Response headers: {response.headers}")

            return response

        except requests.exceptions.Timeout as e:
            logger.error(f"[{request_id}] Request timed out: {e}")
            raise APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s") from e

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "Unknown"
            logger.error(f"[{request_id}] HTTP error {status_code}: {e}")
            raise APIClientHTTPError(
                f"HTTP {status_code}: {e.response.reason if e.response else 'No response'}",
                response=e.response,
            ) from e

        except requests.exceptions.RequestException as e:
            logger.error(f"[{request_id}] Network error: {e}")
            raise APIClientNetworkError(f"Request to {url} failed: {e}") from e

    @property
    def full_url(self) -> str:
        """返回当前类定义下的完整 URL"""
        if not self._class_default_endpoint:
            return self.base_url
        return f"{self.base_url}/{self._class_default_endpoint.lstrip('/')}"

    def request(
        self,
        request_data: dict[str, Any] | list[dict[str, Any]] | None = None,
        is_async: bool = False,
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
                return self._execute_async_requests(request_data)

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

    def _execute_async_requests(self, request_list: list[dict[str, Any]]) -> list[requests.Response | Exception]:
        """异步执行多个请求"""
        logger.info(f"Starting {len(request_list)} asynchronous requests with {self.max_workers} workers")
        responses = [None] * len(request_list)
        futures = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            for i, config in enumerate(request_list):
                request_id = f"ASYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
                future = executor.submit(self._make_request, request_id, config)
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


class BaiduClient(BaseClient):
    """用于访问百度的客户端基类"""

    base_url = "https://www.baidu.com"


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
    print("--- 1. 单次请求 (字典) ---")
    httpbin_get = HttpbinClient()
    try:
        response = httpbin_get.request(
            request_data={
                "method": "GET",
                "endpoint": "/get",
                "params": {"key": "value1"},
            }
        )
        print("Single GET Status:", response.status_code)
        print("Single GET JSON:", response.json())
    except APIClientError as e:
        print(f"Single GET Error: {e}")

    print("\n--- 2. 多次同步请求 (列表) ---")
    httpbin_multi = HttpbinClient()
    multi_data_sync = [
        {"method": "GET", "endpoint": "/get", "params": {"req": "1"}},
        {"method": "GET", "endpoint": "/get", "params": {"req": "2"}},
        {"method": "GET", "endpoint": "/delay/2", "params": {"req": "3"}},
        {"method": "POST", "endpoint": "/post", "json": {"data": "testA"}},
    ]
    start_time = time.time()
    try:
        responses_sync = httpbin_multi.request(request_data=multi_data_sync, is_async=False)
        end_time = time.time()
        print(f"Sync requests completed in {end_time - start_time:.2f} seconds.")
        for i, res in enumerate(responses_sync):
            if isinstance(res, requests.Response):
                print(f"  Sync Response {i + 1} Status: {res.status_code}")
            else:
                print(f"  Sync Response {i + 1} Error: {res}")
    except APIClientError as e:
        print(f"Multi Sync Error: {e}")

    print("\n--- 3. 多次异步 (并行) 请求 (列表) ---")
    # 使用自定义线程数
    httpbin_async = HttpbinClient(max_workers=4)
    start_time = time.time()
    try:
        responses_async = httpbin_async.request(request_data=multi_data_sync, is_async=True)
        end_time = time.time()
        print(f"Async requests completed in {end_time - start_time:.2f} seconds.")
        for i, res in enumerate(responses_async):
            if isinstance(res, requests.Response):
                print(f"  Async Response {i + 1} Status: {res.status_code}")
            else:
                print(f"  Async Response {i + 1} Error: {res}")
    except APIClientError as e:
        print(f"Multi Async Error: {e}")

    print("\n--- 4. 错误处理示例 ---")
    error_client = HttpbinClient()
    error_data = [
        {"method": "GET", "endpoint": "/status/200"},
        {"method": "GET", "endpoint": "/status/404"},
        {"method": "GET", "endpoint": "/status/500"},
        {"method": "GET", "endpoint": "/delay/5"},  # 会超时
    ]
    try:
        responses_with_errors = error_client.request(request_data=error_data, is_async=True)
        print("Responses with errors (async):")
        for i, res in enumerate(responses_with_errors):
            if isinstance(res, requests.Response):
                print(f"  Response {i + 1} Status: {res.status_code}")
            elif isinstance(res, APIClientHTTPError):
                print(f"  Response {i + 1} HTTP Error: {res} (Status: {res.status_code})")
            elif isinstance(res, APIClientTimeoutError):
                print(f"  Response {i + 1} Timeout Error: {res}")
            else:
                print(f"  Response {i + 1} Other Error: {res}")

    except APIClientError as e:
        print(f"Error in error handling example: {e}")

    print("\n--- 5. 使用上下文管理器 ---")
    with HttpbinClient() as client:
        response = client.request(request_data={"endpoint": "/get"})
        print("Context manager request status:", response.status_code)

    print("\n--- 6. 使用类默认值 ---")

    class CustomClient(HttpbinClient):
        endpoint = "/get"
        method = "GET"

    custom_client = CustomClient()
    try:
        res_default = custom_client.request()
        print("Default config request Status:", res_default.status_code)
    except APIClientError as e:
        print(f"Default request Error: {e}")
