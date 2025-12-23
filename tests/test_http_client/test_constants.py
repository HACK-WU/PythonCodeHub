"""
测试 http_client.constants 模块

测试常量定义和配置
"""

import pytest
from http_client import constants


class TestHTTPMethodConstants:
    """测试 HTTP 方法常量"""

    @pytest.mark.unit
    def test_http_method_constants_defined(self):
        """UT-CONST-001: HTTP 方法常量定义"""
        assert constants.HTTP_METHOD_GET == "GET"
        assert constants.HTTP_METHOD_POST == "POST"
        assert constants.HTTP_METHOD_PUT == "PUT"
        assert constants.HTTP_METHOD_DELETE == "DELETE"
        assert constants.HTTP_METHOD_PATCH == "PATCH"
        assert constants.HTTP_METHOD_HEAD == "HEAD"
        assert constants.HTTP_METHOD_OPTIONS == "OPTIONS"
        assert constants.HTTP_METHOD_TRACE == "TRACE"


class TestCacheableMethodsSet:
    """测试可缓存方法集合"""

    @pytest.mark.unit
    def test_cacheable_methods_set(self):
        """UT-CONST-002: 可缓存方法集合"""
        assert isinstance(constants.CACHEABLE_METHODS, set)
        assert constants.HTTP_METHOD_GET in constants.CACHEABLE_METHODS
        assert constants.HTTP_METHOD_HEAD in constants.CACHEABLE_METHODS
        assert constants.HTTP_METHOD_POST not in constants.CACHEABLE_METHODS


class TestDefaultConfigurations:
    """测试默认配置值"""

    @pytest.mark.unit
    def test_default_timeout(self):
        """UT-CONST-003: 默认超时配置"""
        assert constants.DEFAULT_TIMEOUT == 30
        assert isinstance(constants.DEFAULT_TIMEOUT, int)

    @pytest.mark.unit
    def test_default_retries(self):
        """默认重试次数"""
        assert constants.DEFAULT_RETRIES == 3
        assert isinstance(constants.DEFAULT_RETRIES, int)

    @pytest.mark.unit
    def test_default_max_workers(self):
        """默认最大工作线程数"""
        assert constants.DEFAULT_MAX_WORKERS == 10
        assert isinstance(constants.DEFAULT_MAX_WORKERS, int)

    @pytest.mark.unit
    def test_default_cache_expire(self):
        """默认缓存过期时间"""
        assert constants.DEFAULT_CACHE_EXPIRE == 300
        assert isinstance(constants.DEFAULT_CACHE_EXPIRE, int)


class TestRetryConfiguration:
    """测试重试策略配置"""

    @pytest.mark.unit
    def test_retry_config_dict(self):
        """UT-CONST-004: 重试策略配置字典"""
        assert isinstance(constants.DEFAULT_RETRY_CONFIG, dict)
        assert 'total' in constants.DEFAULT_RETRY_CONFIG
        assert 'backoff_factor' in constants.DEFAULT_RETRY_CONFIG
        assert 'status_forcelist' in constants.DEFAULT_RETRY_CONFIG
        assert 'allowed_methods' in constants.DEFAULT_RETRY_CONFIG

    @pytest.mark.unit
    def test_retry_status_forcelist(self):
        """重试状态码列表"""
        assert isinstance(constants.RETRY_STATUS_FORCELIST, list)
        assert 429 in constants.RETRY_STATUS_FORCELIST
        assert 500 in constants.RETRY_STATUS_FORCELIST
        assert 502 in constants.RETRY_STATUS_FORCELIST
        assert 503 in constants.RETRY_STATUS_FORCELIST
        assert 504 in constants.RETRY_STATUS_FORCELIST

    @pytest.mark.unit
    def test_retry_allowed_methods(self):
        """允许重试的方法"""
        assert isinstance(constants.RETRY_ALLOWED_METHODS, list)
        assert constants.HTTP_METHOD_GET in constants.RETRY_ALLOWED_METHODS
        assert constants.HTTP_METHOD_HEAD in constants.RETRY_ALLOWED_METHODS


class TestPoolConfiguration:
    """测试连接池配置"""

    @pytest.mark.unit
    def test_pool_config_dict(self):
        """连接池配置字典"""
        assert isinstance(constants.DEFAULT_POOL_CONFIG, dict)
        assert 'pool_connections' in constants.DEFAULT_POOL_CONFIG
        assert 'pool_maxsize' in constants.DEFAULT_POOL_CONFIG

    @pytest.mark.unit
    def test_pool_values(self):
        """连接池配置值"""
        assert constants.POOL_CONNECTIONS == 100
        assert constants.POOL_MAXSIZE == 100


class TestFileDownloadConfiguration:
    """测试文件下载配置"""

    @pytest.mark.unit
    def test_download_constants(self):
        """文件下载常量"""
        assert constants.DEFAULT_DOWNLOAD_PATH == "./downloads"
        assert constants.DEFAULT_CHUNK_SIZE == 8192
        assert constants.DEFAULT_FILENAME == "downloaded_file"


class TestRedisConfiguration:
    """测试 Redis 配置"""

    @pytest.mark.unit
    def test_redis_defaults(self):
        """Redis 默认配置"""
        assert constants.REDIS_DEFAULT_HOST == "localhost"
        assert constants.REDIS_DEFAULT_PORT == 6379
        assert constants.REDIS_DEFAULT_DB == 0
        assert constants.REDIS_MAX_CONNECTIONS == 10


class TestResponseCodes:
    """测试响应错误代码"""

    @pytest.mark.unit
    def test_error_codes(self):
        """响应格式化器错误代码"""
        assert constants.RESPONSE_CODE_NON_HTTP_ERROR == -1
        assert constants.RESPONSE_CODE_UNEXPECTED_TYPE == -2
        assert constants.RESPONSE_CODE_FORMATTING_ERROR == -3
