"""异步执行器模块

提供多种异步执行策略，用于并发执行多个 HTTP 请求
当前支持线程池执行方式
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from importlib import import_module
from typing import Any

from celery import Celery, current_app, shared_task
from celery.exceptions import TimeoutError as CeleryTimeoutError
from celery.result import AsyncResult

from http_client.constants import RESPONSE_CODE_NON_HTTP_ERROR
from http_client.exceptions import APIClientError

logger = logging.getLogger(__name__)


CELERY_REQUEST_TASK_NAME = "http_client.execute_request_task"


@shared_task(name=CELERY_REQUEST_TASK_NAME, bind=True)
def execute_request_task(
    self, client_path: str, request_id: str, request_config: dict[str, Any], client_kwargs: dict[str, Any] | None = None
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
        client_instance: BaseClient,  # noqa: F821
        validated_request_mapping: dict[str, dict],
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

    def execute(self, client_instance: BaseClient, validated_request_mapping: dict[str, dict]) -> list[dict]:  # noqa: F821
        """
        使用线程池异步执行多个请求

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            validated_request_mapping: 请求配置字典，key 为 request_id，value 为请求配置

        返回:
            格式化后的响应字典列表，顺序与输入一致
        """
        logger.info(f"Starting {len(validated_request_mapping)} asynchronous requests with {self.max_workers} workers")

        # 确定实际使用的工作线程数
        executor_max_workers = self.max_workers if self.max_workers is not None else client_instance.max_workers

        # 使用字典维护 future 与 request_id 的映射关系
        future_to_request_id: dict = {}
        request_id_list = list(validated_request_mapping.keys())

        with ThreadPoolExecutor(max_workers=executor_max_workers, **self.executor_kwargs) as executor:
            # 提交所有请求任务
            for request_id, config in validated_request_mapping.items():
                future = executor.submit(client_instance._make_request_and_format, request_id, config)
                future_to_request_id[future] = request_id

            # 收集所有任务结果，使用字典暂存
            results_dict: dict[str, dict] = {}
            for future in as_completed(future_to_request_id):
                request_id = future_to_request_id[future]
                try:
                    result = future.result()
                    results_dict[request_id] = result
                except APIClientError as e:
                    logger.exception(f"Request {request_id} failed with APIClientError")
                    results_dict[request_id] = {
                        "result": False,
                        "code": getattr(e, "status_code", RESPONSE_CODE_NON_HTTP_ERROR),
                        "message": str(e),
                        "data": None,
                    }
                except Exception as e:
                    logger.exception(f"Request {request_id} failed with unexpected error")
                    results_dict[request_id] = {
                        "result": False,
                        "code": RESPONSE_CODE_NON_HTTP_ERROR,
                        "message": f"Unexpected error: {str(e)}",
                        "data": None,
                    }

        # 按原始顺序返回结果
        return [results_dict[request_id] for request_id in request_id_list]


class CeleryAsyncExecutor(BaseAsyncExecutor):
    """
    基于 Celery 的异步执行器

    通过分布式任务队列调度 HTTP 请求，适合跨进程或跨主机的高并发场景。

    执行流程:
        1. 提交所有请求任务到 Celery 队列
        2. 并发执行请求，每个请求由 Celery worker 处理
        3. 收集所有结果，保持原始顺序返回
        4. 自动处理异常，确保不会因单个请求失败而中断整体执行

    参数:
        celery_app: Celery 实例，默认使用 current_app
        task_name: Celery 任务名称，默认 http_client.execute_request_task
        client_kwargs: 构造客户端实例时使用的参数
        wait_timeout: 等待任务结果的超时时间（秒），None 表示不限制
    """

    def __init__(
        self,
        celery_app: Celery | None = None,
        task_name: str | None = None,
        client_kwargs: dict[str, Any] | None = None,
        wait_timeout: int | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.celery_app = celery_app or current_app
        self.task_name = task_name or CELERY_REQUEST_TASK_NAME
        self.client_kwargs_template = client_kwargs or {}
        self.wait_timeout = wait_timeout

    def execute(
        self,
        client_instance: BaseClient,  # noqa: F821
        validated_request_mapping: dict[str, dict],
    ) -> list[dict]:
        """
        提交任务到 Celery 并收集结果

        参数:
            client_instance: 调用此执行器的 BaseClient 实例
            validated_request_mapping: 请求配置字典，key 为 request_id，value 为请求配置

        返回:
            格式化后的响应字典列表，顺序与输入一致
        """
        logger.info(
            f"Starting {len(validated_request_mapping)} asynchronous requests via Celery task '{self.task_name}'"
        )

        client_path = f"{client_instance.__class__.__module__}.{client_instance.__class__.__name__}"
        client_kwargs = self._build_client_kwargs(client_instance)

        # 使用字典维护 async_result 与 request_id 的映射关系
        async_result_to_request_id: dict[AsyncResult, str] = {}
        request_id_list = list(validated_request_mapping.keys())

        # 提交所有请求任务
        for request_id, config in validated_request_mapping.items():
            payload = deepcopy(config)
            async_result = self.celery_app.send_task(
                self.task_name,
                args=[client_path, request_id, payload, client_kwargs],
            )
            async_result_to_request_id[async_result] = request_id

        # 收集所有任务结果，使用字典暂存
        results_dict: dict[str, dict] = {}
        for async_result, request_id in async_result_to_request_id.items():
            try:
                result = async_result.get(timeout=self.wait_timeout)
                results_dict[request_id] = result
            except CeleryTimeoutError as e:
                logger.exception(f"Request {request_id} timeout")
                results_dict[request_id] = {
                    "result": False,
                    "code": RESPONSE_CODE_NON_HTTP_ERROR,
                    "message": f"Celery task timeout: {e}",
                    "data": None,
                }
            except Exception as e:  # pylint: disable=broad-except
                logger.exception(f"Request {request_id} failed")
                results_dict[request_id] = {
                    "result": False,
                    "code": RESPONSE_CODE_NON_HTTP_ERROR,
                    "message": f"Celery task error: {e}",
                    "data": None,
                }

        # 按原始顺序返回结果
        return [results_dict[request_id] for request_id in request_id_list]

    def _build_client_kwargs(self, client_instance: BaseClient) -> dict[str, Any]:  # noqa: F821
        """从客户端实例中提取可序列化的初始化参数"""
        if self.client_kwargs_template:
            return deepcopy(self.client_kwargs_template)

        base_kwargs = {
            "default_headers": deepcopy(getattr(client_instance, "default_headers", {})),
            "timeout": getattr(client_instance, "timeout", None),
            "verify": getattr(client_instance, "verify", None),
            "enable_retry": getattr(client_instance, "enable_retry", None),
            "max_retries": getattr(client_instance, "max_retries", None),
            "max_workers": getattr(client_instance, "max_workers", None),
            "retry_config": deepcopy(getattr(client_instance, "retry_config", {})),
            "pool_config": deepcopy(getattr(client_instance, "pool_config", {})),
        }

        extra_kwargs = deepcopy(getattr(client_instance, "default_request_kwargs", {}))
        base_kwargs.update(extra_kwargs)
        return {k: v for k, v in base_kwargs.items() if v is not None}
