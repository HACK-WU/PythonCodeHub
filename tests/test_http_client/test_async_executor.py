"""
异步执行器测试

测试异步执行器功能:
- ThreadPoolAsyncExecutor 测试
- CeleryAsyncExecutor 测试
- BaseAsyncExecutor 接口测试
- execute_request_task Celery 任务测试
"""

import pytest
import responses
from unittest.mock import MagicMock, patch
from celery.result import AsyncResult

from http_client.async_executor import (
    BaseAsyncExecutor,
    ThreadPoolAsyncExecutor,
    CeleryAsyncExecutor,
    execute_request_task,
)
from http_client.client import BaseClient
from http_client.constants import RESPONSE_CODE_NON_HTTP_ERROR


class SimpleTestClient(BaseClient):
    """测试用的简单客户端"""

    base_url = "https://api.example.com"
    endpoint = "/users/{user_id}"
    method = "GET"


class TestBaseAsyncExecutor:
    """测试 BaseAsyncExecutor 基类"""

    @pytest.mark.unit
    def test_base_executor_initialization(self):
        """测试基类初始化"""
        # Arrange & Act
        executor = BaseAsyncExecutor(max_workers=5, custom_param="value")

        # Assert
        assert executor.max_workers == 5
        assert executor.executor_kwargs == {"custom_param": "value"}

    @pytest.mark.unit
    def test_base_executor_execute_not_implemented(self):
        """测试基类 execute 方法未实现"""
        # Arrange
        executor = BaseAsyncExecutor()
        client = SimpleTestClient()

        # Act & Assert
        with pytest.raises(NotImplementedError):
            executor.execute(client, {})


class TestThreadPoolAsyncExecutor:
    """测试 ThreadPoolAsyncExecutor"""

    @pytest.mark.unit
    @responses.activate
    def test_thread_pool_executor_basic(self):
        """测试线程池执行器基本功能"""
        # Arrange
        for i in range(1, 6):
            responses.add(responses.GET, f"https://api.example.com/users/{i}", json={"id": i}, status=200)

        client = SimpleTestClient(max_workers=3)
        executor = ThreadPoolAsyncExecutor(max_workers=3)

        validated_requests = {f"req_{i}": {"user_id": i} for i in range(1, 6)}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 5
        assert all(r["result"] is True for r in results)
        assert all(r["data"]["id"] in range(1, 6) for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_thread_pool_executor_preserves_order(self):
        """测试线程池执行器保持请求顺序"""
        # Arrange
        for i in range(1, 11):
            responses.add(responses.GET, f"https://api.example.com/users/{i}", json={"id": i}, status=200)

        client = SimpleTestClient()
        executor = ThreadPoolAsyncExecutor(max_workers=5)

        validated_requests = {f"req_{i}": {"user_id": i} for i in range(1, 11)}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert - 结果顺序应该与请求顺序一致
        assert len(results) == 10
        for i, result in enumerate(results, 1):
            assert result["data"]["id"] == i

    @pytest.mark.unit
    @responses.activate
    def test_thread_pool_executor_handles_errors(self):
        """测试线程池执行器处理错误"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1}, status=200)
        responses.add(responses.GET, "https://api.example.com/users/2", json={"error": "Not found"}, status=404)
        responses.add(responses.GET, "https://api.example.com/users/3", json={"id": 3}, status=200)

        client = SimpleTestClient()
        executor = ThreadPoolAsyncExecutor(max_workers=2)

        validated_requests = {"req_1": {"user_id": 1}, "req_2": {"user_id": 2}, "req_3": {"user_id": 3}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 3
        assert results[0]["result"] is True
        assert results[1]["result"] is False  # 404 错误
        assert results[2]["result"] is True

    @pytest.mark.unit
    @responses.activate
    def test_thread_pool_executor_uses_client_max_workers(self):
        """测试线程池执行器使用客户端的 max_workers"""
        # Arrange
        for i in range(1, 6):
            responses.add(responses.GET, f"https://api.example.com/users/{i}", json={"id": i}, status=200)

        client = SimpleTestClient(max_workers=10)
        executor = ThreadPoolAsyncExecutor()  # 没有指定 max_workers

        validated_requests = {f"req_{i}": {"user_id": i} for i in range(1, 6)}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 5
        assert all(r["result"] is True for r in results)


class TestCeleryAsyncExecutor:
    """测试 CeleryAsyncExecutor"""

    @pytest.mark.unit
    def test_celery_executor_initialization(self):
        """测试 Celery 执行器初始化"""
        # Arrange
        mock_app = MagicMock()

        # Act
        executor = CeleryAsyncExecutor(
            celery_app=mock_app, task_name="custom.task", client_kwargs={"timeout": 30}, wait_timeout=60
        )

        # Assert
        assert executor.celery_app == mock_app
        assert executor.task_name == "custom.task"
        assert executor.client_kwargs_template == {"timeout": 30}
        assert executor.wait_timeout == 60
        assert executor.revoke_on_timeout is True

    @pytest.mark.unit
    def test_celery_executor_submits_tasks(self):
        """测试 Celery 执行器提交任务"""
        # Arrange
        mock_app = MagicMock()
        mock_result = MagicMock(spec=AsyncResult)
        mock_result.successful.return_value = True
        mock_result.result = {"result": True, "data": {"id": 1}, "code": 200, "message": "Success"}
        mock_app.send_task.return_value = mock_result

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app)

        validated_requests = {"req_1": {"user_id": 1}, "req_2": {"user_id": 2}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 2
        assert mock_app.send_task.call_count == 2
        # 验证任务名称
        call_args = mock_app.send_task.call_args_list[0]
        assert call_args[0][0] == "http_client.execute_request_task"

    @pytest.mark.unit
    def test_celery_executor_handles_successful_tasks(self):
        """测试 Celery 执行器处理成功的任务"""
        # Arrange
        mock_app = MagicMock()
        mock_result_1 = MagicMock(spec=AsyncResult)
        mock_result_1.successful.return_value = True
        mock_result_1.result = {"result": True, "data": {"id": 1}, "code": 200, "message": "Success"}

        mock_result_2 = MagicMock(spec=AsyncResult)
        mock_result_2.successful.return_value = True
        mock_result_2.result = {"result": True, "data": {"id": 2}, "code": 200, "message": "Success"}

        mock_app.send_task.side_effect = [mock_result_1, mock_result_2]

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app)

        validated_requests = {"req_1": {"user_id": 1}, "req_2": {"user_id": 2}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 2
        assert results[0]["result"] is True
        assert results[0]["data"]["id"] == 1
        assert results[1]["result"] is True
        assert results[1]["data"]["id"] == 2

    @pytest.mark.unit
    def test_celery_executor_handles_failed_tasks(self):
        """测试 Celery 执行器处理失败的任务"""
        # Arrange
        mock_app = MagicMock()
        mock_result = MagicMock(spec=AsyncResult)
        mock_result.successful.return_value = False
        mock_result.failed.return_value = True
        mock_result.result = Exception("Task failed")

        mock_app.send_task.return_value = mock_result

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app)

        validated_requests = {"req_1": {"user_id": 1}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 1
        assert results[0]["result"] is False
        assert results[0]["code"] == RESPONSE_CODE_NON_HTTP_ERROR
        assert "Celery task error" in results[0]["message"]

    @pytest.mark.unit
    def test_celery_executor_handles_pending_tasks(self):
        """测试 Celery 执行器处理未完成的任务"""
        # Arrange
        mock_app = MagicMock()
        mock_result = MagicMock(spec=AsyncResult)
        mock_result.successful.return_value = False
        mock_result.failed.return_value = False
        mock_result.state = "PENDING"
        mock_result.ready.return_value = False

        mock_app.send_task.return_value = mock_result

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app, wait_timeout=1)

        validated_requests = {"req_1": {"user_id": 1}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 1
        assert results[0]["result"] is False
        assert "not completed" in results[0]["message"].lower()

    @pytest.mark.unit
    def test_celery_executor_timeout_revokes_tasks(self):
        """测试 Celery 执行器超时后撤销任务"""
        # Arrange
        mock_app = MagicMock()
        mock_result = MagicMock(spec=AsyncResult)
        mock_result.successful.return_value = False
        mock_result.failed.return_value = False
        mock_result.ready.return_value = False
        mock_result.state = "STARTED"

        mock_app.send_task.return_value = mock_result

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app, wait_timeout=1, revoke_on_timeout=True)

        validated_requests = {"req_1": {"user_id": 1}}

        # Act
        with patch("http_client.async_executor.ResultSet") as mock_result_set:
            from celery.exceptions import TimeoutError as CeleryTimeoutError

            mock_result_set.return_value.get.side_effect = CeleryTimeoutError()
            executor.execute(client, validated_requests)

        # Assert
        mock_result.revoke.assert_called_once_with(terminate=True)

    @pytest.mark.unit
    def test_celery_executor_builds_client_kwargs(self):
        """测试 Celery 执行器构建客户端参数"""
        # Arrange
        mock_app = MagicMock()
        client = SimpleTestClient(timeout=30, max_retries=3)
        executor = CeleryAsyncExecutor(celery_app=mock_app)

        # Act
        client_kwargs = executor._build_client_kwargs(client)

        # Assert
        assert "timeout" in client_kwargs
        assert "max_retries" in client_kwargs
        assert client_kwargs["timeout"] == 30

    @pytest.mark.unit
    def test_celery_executor_uses_custom_client_kwargs(self):
        """测试 Celery 执行器使用自定义客户端参数"""
        # Arrange
        mock_app = MagicMock()
        custom_kwargs = {"timeout": 60, "verify": False}
        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app, client_kwargs=custom_kwargs)

        # Act
        client_kwargs = executor._build_client_kwargs(client)

        # Assert
        assert client_kwargs["timeout"] == 60
        assert client_kwargs["verify"] is False

    @pytest.mark.unit
    def test_celery_executor_preserves_request_order(self):
        """测试 Celery 执行器保持请求顺序"""
        # Arrange
        mock_app = MagicMock()
        results_data = [
            {"result": True, "data": {"id": 1}, "code": 200, "message": "Success"},
            {"result": True, "data": {"id": 2}, "code": 200, "message": "Success"},
            {"result": True, "data": {"id": 3}, "code": 200, "message": "Success"},
        ]

        mock_results = []
        for data in results_data:
            mock_result = MagicMock(spec=AsyncResult)
            mock_result.successful.return_value = True
            mock_result.result = data
            mock_results.append(mock_result)

        mock_app.send_task.side_effect = mock_results

        client = SimpleTestClient()
        executor = CeleryAsyncExecutor(celery_app=mock_app)

        validated_requests = {"req_1": {"user_id": 1}, "req_2": {"user_id": 2}, "req_3": {"user_id": 3}}

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 3
        for i, result in enumerate(results, 1):
            assert result["data"]["id"] == i


class TestExecuteRequestTask:
    """测试 execute_request_task Celery 任务"""

    @pytest.mark.unit
    @responses.activate
    def test_execute_request_task_success(self):
        """测试 Celery 任务成功执行"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/123", json={"id": 123, "name": "John"}, status=200)

        client_path = "tests.test_http_client.test_async_executor.SimpleTestClient"
        request_id = "req_123"
        request_config = {"user_id": 123}
        client_kwargs = {}

        # Act - Celery 任务第一个参数是 self
        result = execute_request_task(client_path, request_id, request_config, client_kwargs)

        # Assert
        assert result["result"] is True
        assert result["data"]["id"] == 123

    @pytest.mark.unit
    def test_execute_request_task_imports_client(self):
        """测试 Celery 任务正确导入客户端类"""
        # Arrange
        client_path = "tests.test_http_client.test_async_executor.SimpleTestClient"

        # Act
        module_name, class_name = client_path.rsplit(".", 1)
        from importlib import import_module

        client_module = import_module(module_name)
        client_cls = getattr(client_module, class_name)

        # Assert
        assert client_cls == SimpleTestClient

    @pytest.mark.unit
    @responses.activate
    def test_execute_request_task_with_client_kwargs(self):
        """测试 Celery 任务使用客户端参数"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/456", json={"id": 456}, status=200)

        client_path = "tests.test_http_client.test_async_executor.SimpleTestClient"
        request_id = "req_456"
        request_config = {"user_id": 456}
        client_kwargs = {"timeout": 60}

        # Act
        result = execute_request_task(client_path, request_id, request_config, client_kwargs)

        # Assert
        assert result["result"] is True


class TestAsyncExecutorIntegration:
    """测试异步执行器集成"""

    @pytest.mark.unit
    @responses.activate
    def test_client_uses_custom_executor(self):
        """测试客户端使用自定义执行器"""
        # Arrange
        for i in range(1, 4):
            responses.add(responses.GET, f"https://api.example.com/users/{i}", json={"id": i}, status=200)

        custom_executor = ThreadPoolAsyncExecutor(max_workers=2)

        client = SimpleTestClient(executor=custom_executor)

        # Act
        results = client.request([{"user_id": 1}, {"user_id": 2}, {"user_id": 3}], is_async=True)

        # Assert
        assert len(results) == 3
        assert all(r["result"] is True for r in results)

    @pytest.mark.unit
    @responses.activate
    def test_executor_handles_mixed_success_and_failure(self):
        """测试执行器处理混合的成功和失败请求"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1}, status=200)
        responses.add(responses.GET, "https://api.example.com/users/2", json={"error": "Not found"}, status=404)
        responses.add(responses.GET, "https://api.example.com/users/3", json={"id": 3}, status=200)
        responses.add(responses.GET, "https://api.example.com/users/4", json={"error": "Server error"}, status=500)

        client = SimpleTestClient()
        executor = ThreadPoolAsyncExecutor(max_workers=4)

        validated_requests = {
            "req_1": {"user_id": 1},
            "req_2": {"user_id": 2},
            "req_3": {"user_id": 3},
            "req_4": {"user_id": 4},
        }

        # Act
        results = executor.execute(client, validated_requests)

        # Assert
        assert len(results) == 4
        assert results[0]["result"] is True
        assert results[1]["result"] is False  # 404
        assert results[2]["result"] is True
        assert results[3]["result"] is False  # 500


class TestAsyncExecutorErrorHandling:
    """测试异步执行器错误处理"""

    @pytest.mark.unit
    @responses.activate
    def test_executor_handles_unexpected_exception(self):
        """测试执行器处理意外异常"""
        # Arrange
        responses.add(responses.GET, "https://api.example.com/users/1", json={"id": 1}, status=200)

        client = SimpleTestClient()
        executor = ThreadPoolAsyncExecutor(max_workers=2)

        # Mock 一个会抛出异常的请求
        with patch.object(client, "_make_request_and_format") as mock_method:
            mock_method.side_effect = [
                {"result": True, "data": {"id": 1}, "code": 200, "message": "Success"},
                Exception("Unexpected error"),
            ]

            validated_requests = {"req_1": {"user_id": 1}, "req_2": {"user_id": 2}}

            # Act
            results = executor.execute(client, validated_requests)

            # Assert
            assert len(results) == 2
            assert results[0]["result"] is True
            assert results[1]["result"] is False
            assert "Unexpected error" in results[1]["message"]
