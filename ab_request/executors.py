import base64
import logging
import pickle  # 用于序列化，但请注意安全性
import uuid
from typing import Any

import requests

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from celery import Celery, group


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


celery_app = Celery("api_client_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")


# 2. 定义 Celery 任务
# 注意：这个任务需要能够访问到客户端实例的 _make_request 方法的相关逻辑。
# 由于 Celery worker 运行在不同进程中，直接传递实例方法很困难。
# 一个更健壮的方法是将执行所需的所有信息（如 session 配置、认证信息等）序列化并传递给任务。
# 这里采用一种简化方式：序列化整个请求配置和客户端的部分配置。
# ***警告***: 使用 pickle 序列化可能存在安全风险，尤其是在处理不受信任的数据时。
@celery_app.task(bind=True)  # bind=True 使 task 能访问到 self
def make_request_task(self, serialized_client_config: str, request_config: dict[str, Any]) -> str:
    """
    Celery 任务函数，用于执行单个 API 请求。
    :param serialized_client_config: Base64 编码的 Pickle 序列化的客户端配置字典。
    :param request_config: 单个请求的配置字典。
    :return: Base64 编码的 Pickle 序列化的 (响应数据字典 或 异常信息字典)。
    """
    logger_task = logging.getLogger(__name__ + ".celery_task")
    try:
        # 反序列化客户端配置
        client_config_bytes = base64.b64decode(serialized_client_config)
        client_config = pickle.loads(client_config_bytes)

        # 从配置重建一个临时的客户端实例（仅用于 _make_request）
        # 注意：这不会复用原始客户端的 Session，但会使用相同的配置（headers, auth logic, timeout 等）
        # 如果认证是动态的或依赖于 session 状态，这可能不完全等效。
        temp_client = _ReconstructedClient(client_config)

        request_id = f"CELERY-TASK-{self.request.id}-{uuid.uuid4().hex[:4]}"
        logger_task.info(f"[{request_id}] Task starting for {request_config}")

        # 执行请求
        response = temp_client._make_request_internal(request_id, request_config)

        # 序列化成功响应的关键信息以便返回
        # 注意：不能直接序列化 requests.Response 对象
        response_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": response.content,  # bytes
            "url": response.url,
            "reason": response.reason,
            # 可以根据需要添加更多字段
        }
        logger_task.info(f"[{request_id}] Task completed with status {response.status_code}")
        return base64.b64encode(pickle.dumps({"success": True, "data": response_data})).decode("utf-8")

    except Exception as e:  # 捕获所有异常，包括 APIClientError 及其子类
        logger_task.error(f"[Task {self.request.id}] Task failed: {e}", exc_info=True)
        # 序列化异常信息
        error_info = {
            "type": type(e).__name__,
            "message": str(e),
            # 可以添加更多异常属性，如果需要
        }
        # 如果是自定义异常，可以尝试获取更多细节
        if isinstance(e, APIClientHTTPError):
            error_info["status_code"] = getattr(e, "status_code", None)
            # 注意：原始 response 对象无法序列化，这里不包含它
        elif isinstance(e, APIClientTimeoutError | APIClientNetworkError):
            pass  # 这些异常主要信息在 message 里

        return base64.b64encode(pickle.dumps({"success": False, "error": error_info})).decode("utf-8")


class _ReconstructedClient:
    """一个简化版的客户端，用于在 Celery Worker 中重建请求环境"""

    def __init__(self, config: dict[str, Any]):
        self.base_url = config.get("base_url", "")
        self.timeout = config.get("timeout", 30)
        self.session_headers = config.get("session_headers", {})
        self.default_request_kwargs = config.get("default_request_kwargs", {})
        self._class_default_endpoint = config.get("_class_default_endpoint", "")
        self._class_default_method = config.get("_class_default_method", "GET")

        # 重建 Session 和 Auth (这部分逻辑从 BaseClient._create_session 和认证解析中提取)
        self.session = requests.Session()
        self.session.headers.update(self.session_headers)

        if auth_instance := config.get("auth_instance"):
            # 假设 auth_instance 是可调用的或 requests.auth.AuthBase 实例
            # 如果是类，需要实例化；如果是实例，直接使用。
            # 这里简化处理，假设传入的是可以直接用于 session.auth 的对象
            # ***注意***: 如果 auth_instance 是复杂的对象（如包含数据库连接），序列化/反序列化会失败。
            # 更好的方式是在 worker 端重新构建 auth 实例，或传递构建 auth 所需的参数。
            # 当前实现假设 auth_instance 本身是可序列化的或已处理成可序列化形式。
            self.session.auth = auth_instance

        # 注意：这里没有重建重试策略，可以根据需要添加

    def _make_request_internal(self, request_id: str, request_config: dict[str, Any]) -> requests.Response:
        """
        内部方法，执行单个 HTTP 请求。逻辑复制自 BaseClient._make_request。
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

        logger_task = logging.getLogger(__name__ + ".celery_task._make_request_internal")
        logger_task.info(f"[{request_id}] Starting {method} request to {url}")
        logger_task.debug(f"[{request_id}] Request kwargs: {request_kwargs}")

        try:
            # 使用 Session 发起请求
            response = self.session.request(method=method, url=url, timeout=self.timeout, **request_kwargs)

            # 记录响应摘要信息
            logger_task.info(f"[{request_id}] Received {response.status_code} response")
            logger_task.debug(f"[{request_id}] Response headers: {response.headers}")
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout as e:
            logger_task.error(f"[{request_id}] Request timed out: {e}")
            # 在 worker 中，我们抛出原始异常或自定义异常，Celery 会处理
            raise APIClientTimeoutError(f"Request to {url} timed out after {self.timeout}s") from e

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "Unknown"
            logger_task.error(f"[{request_id}] HTTP error {status_code}: {e}")
            raise APIClientHTTPError(
                f"HTTP {status_code}: {e.response.reason if e.response else 'No response'}",
                # response=e.response # 不传递原始 response 对象
            ) from e

        except requests.exceptions.RequestException as e:
            logger_task.error(f"[{request_id}] Network error: {e}")
            raise APIClientNetworkError(f"Request to {url} failed: {e}") from e


class CeleryAsyncExecutor(BaseAsyncExecutor):
    """
    使用 Celery 实现异步请求的执行器。
    """

    def __init__(self, app: Celery | None = None, **kwargs):
        """
        初始化 Celery 执行器。
        :param app: Celery 应用实例。如果为 None，则尝试使用全局的 celery_app。
        :param kwargs: 传递给 BaseAsyncExecutor 的其他参数。
        """
        super().__init__(**kwargs)  # 调用基类初始化
        self.app = app or celery_app
        if not self.app:
            raise APIClientValidationError("A Celery app instance is required for CeleryAsyncExecutor.")

    def _serialize_client_config(self, client_instance: "BaseClient") -> str:
        """序列化客户端配置以便传递给 Celery 任务"""
        config = {
            "base_url": client_instance.base_url,
            "timeout": client_instance.timeout,
            "session_headers": client_instance.session_headers,
            "default_request_kwargs": client_instance.default_request_kwargs,
            "_class_default_endpoint": client_instance._class_default_endpoint,
            "_class_default_method": client_instance._class_default_method,
            "auth_instance": client_instance.auth_instance,  # ***警告***: 序列化 auth 实例可能不安全或不可行
            # 可以根据需要添加更多配置
        }
        pickled_config = pickle.dumps(config)
        return base64.b64encode(pickled_config).decode("utf-8")

    def execute(
        self, client_instance: "BaseClient", request_list: list[dict[str, Any]]
    ) -> list[requests.Response | Exception]:
        """使用 Celery 异步执行多个请求"""
        if not self.app:
            raise APIClientError("Celery application is not configured.")

        logger.info(f"Starting {len(request_list)} asynchronous requests via Celery")

        # 序列化客户端配置
        serialized_config = self._serialize_client_config(client_instance)

        # 创建 Celery 任务签名 (signatures)
        job_signatures = [make_request_task.s(serialized_config, config) for config in request_list]

        # 使用 group 并发执行任务
        job_group = group(job_signatures)
        result_group = job_group.apply_async()

        # 等待所有任务完成 (阻塞当前线程/进程)
        # Celery 的 AsyncResult.join() 或 get() 可以等待结果
        # get() 返回的是任务结果的列表
        try:
            # timeout 参数可以设置总等待时间
            task_results = result_group.get(timeout=client_instance.timeout * len(request_list) + 60)  # 简单的超时计算
        except Exception as e:  # 捕获 Celery 相关的超时或其他错误
            logger.error(f"Celery group execution failed or timed out: {e}")
            # 可以选择抛出异常或返回部分结果/错误
            raise APIClientError(f"Celery execution error: {e}") from e

        # 反序列化任务结果
        final_responses: list[requests.Response | Exception] = []
        for i, serialized_result in enumerate(task_results):
            try:
                result_bytes = base64.b64decode(serialized_result)
                result_data = pickle.loads(result_bytes)

                if result_data["success"]:
                    # 从序列化的数据重建一个类似 Response 的对象或直接使用数据
                    # 这里创建一个简单的 Mock 响应对象
                    data = result_data["data"]
                    mock_response = requests.Response()
                    mock_response.status_code = data["status_code"]
                    mock_response._content = data["content"]  # bytes
                    mock_response.headers = requests.structures.CaseInsensitiveDict(data["headers"])
                    mock_response.url = data["url"]
                    mock_response.reason = data["reason"]
                    # 注意：其他属性如 encoding, cookies, history 等可能需要手动设置
                    # 如果需要完全模拟 requests.Response，这会更复杂
                    final_responses.append(mock_response)
                else:
                    # 根据序列化的错误信息重建异常
                    error_info = result_data["error"]
                    error_type = error_info["type"]
                    error_message = error_info["message"]
                    status_code = error_info.get("status_code")

                    # 尝试重建原始异常类型
                    exception_class = globals().get(error_type, APIClientError)  # 默认回退到基类
                    if issubclass(exception_class, APIClientHTTPError):
                        exc = exception_class(message=error_message)
                        exc.status_code = status_code  # 手动设置
                    else:
                        exc = exception_class(message=error_message)

                    final_responses.append(exc)

            except Exception as deser_e:  # 反序列化或重建对象时出错
                logger.error(f"Failed to deserialize result for task {i}: {deser_e}")
                final_responses.append(APIClientError(f"Deserialization error for task result: {deser_e}"))

        return final_responses
