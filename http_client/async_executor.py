"""
异步执行器模块

提供多种异步执行策略，用于并发执行多个 HTTP 请求
当前支持线程池执行方式
"""

import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from copy import deepcopy
from importlib import import_module
from typing import Any

from celery import Celery, current_app, shared_task
from celery.exceptions import TimeoutError as CeleryTimeoutError
from celery.result import AsyncResult

from http_client.constants import LOG_FORMAT
from http_client.exceptions import APIClientError

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


CELERY_REQUEST_TASK_NAME = "http_client.execute_request_task"


@shared_task(name=CELERY_REQUEST_TASK_NAME, bind=True)
def execute_request_task(
    self, client_path: str, request_config: dict[str, Any], client_kwargs: dict[str, Any] | None = None
) -> dict[str, Any]:
    """使用 Celery 执行单个请求"""
    module_name, class_name = client_path.rsplit(".", 1)
    client_module = import_module(module_name)
    client_cls = getattr(client_module, class_name)
    # 这里延迟导入以避免循环依赖
    with client_cls(**(client_kwargs or {})) as client:  # type: ignore[call-arg]
        return client._execute_single_request(request_config)  # type: ignore[attr-defined]


class BaseAsyncExecutor:
    """
    异步执行器基类

    定义执行多个请求的统一接口，子类需实现具体的执行策略

    参数:
        max_workers: 最大工作线程/进程数
        **kwargs: 其他传递给具体执行器的参数
    """

    def __init__(self, max_workers: int | None = None, **kwargs):
        """
        初始化执行器

        参数:
            max_workers: 最大工作线程/进程数
            kwargs: 其他传递给具体执行器的参数
        """
        self.max_workers = max_workers
        self.executor_kwargs = kwargs

    def execute(
        self,
        client_instance: "BaseClient",  # noqa: F821
        request_list: list[dict[str, Any]],
    ) -> list[dict[str, Any] | Exception]:
        """
        执行多个请求

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            request_list: 请求配置列表

        返回:
            格式化后的响应字典或异常的列表
        """
        raise NotImplementedError("Subclasses must implement the 'execute' method.")


class ThreadPoolAsyncExecutor(BaseAsyncExecutor):
    """
    线程池异步执行器

    使用 ThreadPoolExecutor 实现并发请求执行
    适用于 I/O 密集型任务，可显著提升多请求场景的性能

    执行流程:
        1. 创建线程池，提交所有请求任务
        2. 并发执行请求，每个请求在独立线程中运行
        3. 收集所有结果，保持原始顺序返回
        4. 自动处理异常，确保不会因单个请求失败而中断整体执行
    """

    def execute(self, client_instance: "BaseClient", request_list: list[dict]) -> list[dict]:  # noqa: F821
        """
        使用线程池异步执行多个请求

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            request_list: 请求配置列表

        返回:
            格式化后的响应字典或异常的列表，顺序与输入一致

        执行步骤:
            1. 初始化结果列表，预分配空间
            2. 创建线程池，提交所有请求任务
            3. 等待所有任务完成，收集结果
            4. 处理异常情况，确保返回完整结果
        """
        logger.info(f"Starting {len(request_list)} asynchronous requests with {self.max_workers} workers")

        # 初始化结果列表，保持与请求列表相同的顺序
        results: list[dict[str, Any] | Exception | None] = [None] * len(request_list)
        futures: dict[Future, int] = {}

        # 确定实际使用的工作线程数
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers

        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            # 提交所有请求任务
            for i, config in enumerate(request_list):
                request_id = f"ASYNC-{i + 1}-{uuid.uuid4().hex[:4]}"
                # 直接调用 _make_request_and_format 方法，返回格式化后的数据
                future = executor.submit(client_instance._make_request_and_format, request_id, config)
                futures[future] = i

            # 收集所有任务结果
            for future in as_completed(futures):
                index = futures[future]
                try:
                    result = future.result()  # 获取格式化后的数据
                    results[index] = result
                except APIClientError as e:
                    # 捕获客户端错误
                    logger.error(f"Async request {index + 1} failed: {e}")
                    results[index] = e
                except Exception as e:
                    # 捕获其他意外错误
                    logger.error(f"Unexpected error in async request {index + 1}: {e}")
                    results[index] = APIClientError(f"Unexpected error: {e}")

        return results  # type: ignore


class CeleryAsyncExecutor(BaseAsyncExecutor):
    """
    基于 Celery 的异步执行器

    通过分布式任务队列调度 HTTP 请求，适合跨进程或跨主机的高并发场景。

    参数:
        celery_app: Celery 实例，默认使用 current_app
        task_name: Celery 任务名称，默认 http_client.execute_request_task
        client_kwargs: 构造客户端实例时使用的参数
        wait_timeout: 等待任务结果的超时时间（秒），None 表示不限制
        propagate_error: 是否将任务异常原样抛出
    """

    def __init__(
        self,
        celery_app: Celery | None = None,
        task_name: str | None = None,
        client_kwargs: dict[str, Any] | None = None,
        wait_timeout: int | None = None,
        propagate_error: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.celery_app = celery_app or current_app
        self.task_name = task_name or CELERY_REQUEST_TASK_NAME
        self.client_kwargs_template = client_kwargs or {}
        self.wait_timeout = wait_timeout
        self.propagate_error = propagate_error

    def execute(
        self,
        client_instance: "BaseClient",  # noqa: F821
        request_list: list[dict[str, Any]],
    ) -> list[dict[str, Any] | Exception]:
        """提交任务到 Celery 并收集结果"""
        if not request_list:
            return []

        client_path = f"{client_instance.__class__.__module__}.{client_instance.__class__.__name__}"
        client_kwargs = self._build_client_kwargs(client_instance)

        logger.info(f"Dispatching {len(request_list)} requests via Celery task '{self.task_name}'")
        async_results: list[AsyncResult] = []
        for index, config in enumerate(request_list):
            payload = deepcopy(config)
            request_id = f"CELERY-{index + 1}-{uuid.uuid4().hex[:4]}"
            result = self.celery_app.send_task(
                self.task_name,
                args=[client_path, payload, client_kwargs, request_id],
            )
            async_results.append(result)

        results: list[dict[str, Any] | Exception] = []
        for index, async_result in enumerate(async_results):
            try:
                response = async_result.get(timeout=self.wait_timeout)
                results.append(response)
            except CeleryTimeoutError as timeout_error:
                logger.error(f"Celery task timeout for request {index + 1}: {timeout_error}")
                results.append(APIClientError(f"Celery task timeout: {timeout_error}"))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(f"Celery task failed for request {index + 1}: {exc}")
                error = exc if self.propagate_error else APIClientError(f"Celery task error: {exc}")
                results.append(error)

        return results

    def _build_client_kwargs(self, client_instance: "BaseClient") -> dict[str, Any]:  # noqa: F821
        """从客户端实例中提取可序列化的初始化参数"""
        if self.client_kwargs_template:
            return deepcopy(self.client_kwargs_template)

        base_kwargs = {
            "default_headers": deepcopy(getattr(client_instance, "default_headers", {})),
            "timeout": getattr(client_instance, "timeout", None),
            "verify": getattr(client_instance, "verify", None),
            "enable_retry": getattr(client_instance, "enable_retry", None),
            "retries": getattr(client_instance, "retries", None),
            "max_workers": getattr(client_instance, "max_workers", None),
            "retry_config": deepcopy(getattr(client_instance, "retry_config", {})),
            "pool_config": deepcopy(getattr(client_instance, "pool_config", {})),
        }

        extra_kwargs = deepcopy(getattr(client_instance, "default_request_kwargs", {}))
        base_kwargs.update(extra_kwargs)
        return {k: v for k, v in base_kwargs.items() if v is not None}
