"""
异步执行器模块

提供多种异步执行策略，用于并发执行多个 HTTP 请求
当前支持线程池执行方式
"""

import logging
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any

from ab_request.http_client.constants import LOG_FORMAT
from ab_request.http_client.exceptions import APIClientError

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)


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

    def execute(self, client_instance, request_list: list[dict[str, Any]]) -> list[dict[str, Any] | Exception]:
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

    def execute(self, client_instance, request_list: list[dict[str, Any]]) -> list[dict[str, Any] | Exception]:
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
