"""
通用测试 Fixture 定义

提供测试所需的 Mock 对象、Fixture 和工具函数
"""

import pytest
import fakeredis
from unittest.mock import MagicMock, Mock


@pytest.fixture
def mock_response():
    """标准 Mock Response 对象"""
    response = Mock()
    response.status_code = 200
    response.headers = {'Content-Type': 'application/json'}
    response.json.return_value = {'result': True}
    response.content = b'{"result": true}'
    response.text = '{"result": true}'
    response.url = 'https://api.example.com/test'
    response.reason = 'OK'
    return response


@pytest.fixture
def mock_error_response():
    """Mock 错误 Response 对象（404）"""
    response = Mock()
    response.status_code = 404
    response.headers = {'Content-Type': 'application/json'}
    response.json.return_value = {'error': 'Not Found'}
    response.content = b'{"error": "Not Found"}'
    response.text = '{"error": "Not Found"}'
    response.url = 'https://api.example.com/notfound'
    response.reason = 'Not Found'
    return response


@pytest.fixture
def mock_session(mocker):
    """Mock requests.Session"""
    session = MagicMock()
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {'result': True}
    session.request.return_value = mock_resp
    return session


@pytest.fixture
def base_client_class():
    """返回 BaseClient 类（用于需要导入的测试）"""
    from http_client import BaseClient
    return BaseClient


@pytest.fixture
def base_client(requests_mock):
    """基础配置的 BaseClient 实例"""
    from http_client import BaseClient
    
    # Mock 默认 URL
    requests_mock.get('https://api.example.com/test', json={'result': True})
    requests_mock.post('https://api.example.com/test', json={'result': True})
    
    client = BaseClient(base_url='https://api.example.com')
    return client


@pytest.fixture(scope='module')
def fake_redis():
    """FakeRedis 实例（模块级，提升性能）"""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeStrictRedis(server=server, decode_responses=False)
    yield client
    client.flushall()


@pytest.fixture
def mock_celery_app():
    """Mock Celery app"""
    app = MagicMock()
    result = MagicMock()
    result.get.return_value = {'result': True, 'data': None}
    app.send_task.return_value = result
    return app


@pytest.fixture
def mock_celery_executor(mock_celery_app):
    """Mock CeleryAsyncExecutor"""
    from http_client.async_executor import CeleryAsyncExecutor
    executor = CeleryAsyncExecutor(celery_app=mock_celery_app)
    return executor


@pytest.fixture
def client_with_validator(requests_mock):
    """含状态码验证器的客户端"""
    from http_client import BaseClient
    from http_client.validator import StatusCodeValidator
    
    requests_mock.get('https://api.example.com/test', json={'result': True})
    
    client = BaseClient(
        base_url='https://api.example.com',
        response_validator=StatusCodeValidator(allowed_codes=[200, 201])
    )
    return client
