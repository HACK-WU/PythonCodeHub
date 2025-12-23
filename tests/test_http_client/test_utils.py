"""
测试 http_client.utils 模块

测试敏感信息脱敏功能：
- sanitize_headers: 请求头脱敏
- sanitize_url: URL 参数脱敏
- sanitize_dict: 字典字段脱敏
- mask_string: 正则表达式脱敏
"""

import pytest
from http_client.utils import sanitize_headers, sanitize_url, sanitize_dict, mask_string


class TestSanitizeHeaders:
    """测试 sanitize_headers 函数"""

    @pytest.mark.unit
    def test_sanitize_default_sensitive_headers(self):
        """UT-UTIL-001: 脱敏默认敏感头"""
        headers = {'Authorization': 'Bearer token123', 'Cookie': 'session=abc'}
        result = sanitize_headers(headers)
        
        assert result['Authorization'] == '***'
        assert result['Cookie'] == '***'

    @pytest.mark.unit
    def test_preserve_non_sensitive_headers(self):
        """UT-UTIL-002: 保留非敏感头"""
        headers = {'Content-Type': 'application/json', 'User-Agent': 'Mozilla'}
        result = sanitize_headers(headers)
        
        assert result['Content-Type'] == 'application/json'
        assert result['User-Agent'] == 'Mozilla'

    @pytest.mark.unit
    def test_custom_sensitive_keys(self):
        """UT-UTIL-003: 自定义敏感键集合"""
        headers = {'X-Custom-Token': 'secret123', 'Content-Type': 'application/json'}
        result = sanitize_headers(headers, sensitive_keys={'X-Custom-Token'})
        
        assert result['X-Custom-Token'] == '***'
        assert result['Content-Type'] == 'application/json'

    @pytest.mark.unit
    def test_case_insensitive_matching(self):
        """UT-UTIL-004: 大小写不敏感"""
        headers = {'authorization': 'Bearer token', 'COOKIE': 'session=abc'}
        result = sanitize_headers(headers)
        
        assert result['authorization'] == '***'
        assert result['COOKIE'] == '***'

    @pytest.mark.unit
    def test_empty_headers(self):
        """UT-UTIL-005: 空字典输入"""
        headers = {}
        result = sanitize_headers(headers)
        
        assert result == {}

    @pytest.mark.unit
    def test_custom_mask_character(self):
        """UT-UTIL-006: 自定义 mask 字符"""
        headers = {'Authorization': 'Bearer token123'}
        result = sanitize_headers(headers, mask='[REDACTED]')
        
        assert result['Authorization'] == '[REDACTED]'

    @pytest.mark.unit
    def test_mixed_sensitive_and_non_sensitive(self):
        """边界测试：混合敏感和非敏感头"""
        headers = {
            'Authorization': 'Bearer token',
            'Content-Type': 'application/json',
            'X-API-Key': 'key123',
            'Accept': 'application/json'
        }
        result = sanitize_headers(headers)
        
        assert result['Authorization'] == '***'
        assert result['X-API-Key'] == '***'
        assert result['Content-Type'] == 'application/json'
        assert result['Accept'] == 'application/json'


class TestSanitizeUrl:
    """测试 sanitize_url 函数"""

    @pytest.mark.unit
    def test_sanitize_default_sensitive_params(self):
        """UT-UTIL-007: 脱敏默认敏感参数"""
        url = 'https://api.example.com/users?token=abc123&key=secret'
        result = sanitize_url(url)
        
        # URL 编码后 *** 变为 %2A%2A%2A
        assert ('token=***' in result or 'token=%2A%2A%2A' in result)
        assert ('key=***' in result or 'key=%2A%2A%2A' in result)
        assert 'abc123' not in result
        assert 'secret' not in result

    @pytest.mark.unit
    def test_preserve_non_sensitive_params(self):
        """UT-UTIL-008: 保留非敏感参数"""
        url = 'https://api.example.com/users?page=1&limit=20'
        result = sanitize_url(url)
        
        assert 'page=1' in result
        assert 'limit=20' in result

    @pytest.mark.unit
    def test_url_without_query_params(self):
        """UT-UTIL-009: 无查询参数 URL"""
        url = 'https://api.example.com/users'
        result = sanitize_url(url)
        
        assert result == url

    @pytest.mark.unit
    def test_multiple_value_params(self):
        """UT-UTIL-010: 多值参数脱敏"""
        url = 'https://api.example.com/api?token=a&token=b&page=1'
        result = sanitize_url(url)
        
        # 检查 token 参数被脱敏
        assert ('token=***' in result or 'token=%2A%2A%2A' in result)
        # 检查原始值不存在
        assert 'token=a' not in result
        assert 'token=b' not in result

    @pytest.mark.unit
    def test_case_insensitive_params(self):
        """UT-UTIL-011: 大小写不敏感"""
        url = 'https://api.example.com/api?TOKEN=abc&Password=123'
        result = sanitize_url(url)
        
        assert ('TOKEN=***' in result or 'TOKEN=%2A%2A%2A' in result)
        assert ('Password=***' in result or 'Password=%2A%2A%2A' in result)

    @pytest.mark.unit
    def test_complex_url_structure(self):
        """UT-UTIL-012: 复杂 URL 结构"""
        url = 'https://api.example.com:8080/users?token=abc#section'
        result = sanitize_url(url)
        
        assert 'https://api.example.com:8080/users' in result
        assert ('token=***' in result or 'token=%2A%2A%2A' in result)
        assert '#section' in result

    @pytest.mark.unit
    @pytest.mark.parametrize('url,expected_check', [
        ('https://api.com?token=abc', lambda r: 'token=***' in r or 'token=%2A%2A%2A' in r),
        ('https://api.com?page=1', lambda r: 'page=1' in r),
        ('https://api.com', lambda r: r == 'https://api.com'),
    ])
    def test_sanitize_url_parametrized(self, url, expected_check):
        """参数化测试：多种 URL 场景"""
        result = sanitize_url(url)
        assert expected_check(result)


class TestSanitizeDict:
    """测试 sanitize_dict 函数"""

    @pytest.mark.unit
    def test_first_level_dict_sanitization(self):
        """UT-UTIL-013: 一级字典脱敏"""
        data = {'password': '123456', 'username': 'john'}
        result = sanitize_dict(data)
        
        assert result['password'] == '***'
        assert result['username'] == 'john'

    @pytest.mark.unit
    def test_recursive_nested_dict_sanitization(self):
        """UT-UTIL-014: 递归脱敏嵌套字典"""
        data = {
            'username': 'john',
            'credentials': {
                'password': 'secret',
                'api_key': 'key123'
            }
        }
        result = sanitize_dict(data, recursive=True)
        
        assert result['username'] == 'john'
        assert result['credentials']['password'] == '***'
        assert result['credentials']['api_key'] == '***'

    @pytest.mark.unit
    def test_non_recursive_mode(self):
        """UT-UTIL-015: 关闭递归模式"""
        data = {
            'password': 'secret',
            'nested': {'api_key': 'key123'}
        }
        result = sanitize_dict(data, recursive=False)
        
        assert result['password'] == '***'
        # 嵌套字典不应该被处理
        assert result['nested']['api_key'] == 'key123'

    @pytest.mark.unit
    def test_mixed_data_types(self):
        """UT-UTIL-016: 混合数据类型"""
        data = {
            'username': 'john',
            'password': 'secret',
            'age': 25,
            'tags': ['admin', 'user'],
            'meta': {'api_key': 'key123'}
        }
        result = sanitize_dict(data, recursive=True)
        
        assert result['username'] == 'john'
        assert result['password'] == '***'
        assert result['age'] == 25
        assert result['tags'] == ['admin', 'user']
        assert result['meta']['api_key'] == '***'

    @pytest.mark.unit
    def test_empty_dict(self):
        """边界测试：空字典"""
        data = {}
        result = sanitize_dict(data)
        
        assert result == {}

    @pytest.mark.unit
    def test_custom_sensitive_keys_in_dict(self):
        """测试自定义敏感键"""
        data = {'custom_field': 'value', 'normal_field': 'data'}
        result = sanitize_dict(data, sensitive_keys={'custom_field'})
        
        assert result['custom_field'] == '***'
        assert result['normal_field'] == 'data'


class TestMaskString:
    """测试 mask_string 函数"""

    @pytest.mark.unit
    def test_basic_regex_matching(self):
        """UT-UTIL-017: 基础正则匹配脱敏"""
        text = 'Bearer token_abc123xyz'
        result = mask_string(text, pattern=r'token_\w+')
        
        assert result == 'Bearer ***'
        assert 'token_abc123xyz' not in result

    @pytest.mark.unit
    def test_keep_prefix(self):
        """UT-UTIL-018: 保留前缀"""
        text = 'Bearer token_abc123xyz'
        result = mask_string(text, pattern=r'token_\w+', keep_prefix=6)
        
        assert 'token_' in result
        assert '***' in result
        assert 'abc123xyz' not in result

    @pytest.mark.unit
    def test_keep_suffix(self):
        """UT-UTIL-019: 保留后缀"""
        text = 'Bearer token_abc123xyz'
        result = mask_string(text, pattern=r'token_\w+', keep_suffix=4)
        
        assert '***' in result
        # 后缀 4 个字符应该是 '3xyz'
        assert '3xyz' in result

    @pytest.mark.unit
    def test_keep_both_prefix_and_suffix(self):
        """UT-UTIL-020: 前后缀同时保留"""
        text = 'Bearer token_abc123xyz'
        result = mask_string(text, pattern=r'token_\w+', keep_prefix=6, keep_suffix=3)
        
        assert 'token_' in result
        assert '***' in result
        assert result.endswith('xyz') or 'xyz' in result

    @pytest.mark.unit
    def test_no_match(self):
        """UT-UTIL-021: 无匹配内容"""
        text = 'No sensitive data here'
        result = mask_string(text, pattern=r'token_\w+')
        
        assert result == text

    @pytest.mark.unit
    def test_multiple_matches(self):
        """边界测试：多个匹配"""
        text = 'token_123 and token_456'
        result = mask_string(text, pattern=r'token_\d+')
        
        assert 'token_123' not in result
        assert 'token_456' not in result
        assert '***' in result

    @pytest.mark.unit
    def test_custom_mask_in_mask_string(self):
        """测试自定义 mask"""
        text = 'Bearer token_abc123'
        result = mask_string(text, pattern=r'token_\w+', mask='[HIDDEN]')
        
        assert result == 'Bearer [HIDDEN]'


class TestBoundaryConditions:
    """边界条件测试"""

    @pytest.mark.unit
    @pytest.mark.parametrize('headers', [
        {},  # 空字典
        {'Key': ''},  # 空值
        {'Key': 'x' * 10000},  # 超长值
    ])
    def test_sanitize_headers_boundary(self, headers):
        """测试 sanitize_headers 边界条件"""
        result = sanitize_headers(headers)
        assert isinstance(result, dict)

    @pytest.mark.unit
    @pytest.mark.parametrize('url', [
        'https://api.com',
        'https://api.com?',
        'https://api.com?key=',
    ])
    def test_sanitize_url_boundary(self, url):
        """测试 sanitize_url 边界条件"""
        result = sanitize_url(url)
        assert isinstance(result, str)

    @pytest.mark.unit
    def test_sanitize_dict_with_none_values(self):
        """测试字典包含 None 值"""
        data = {'password': None, 'username': 'john'}
        result = sanitize_dict(data)
        
        assert result['password'] == '***'
        assert result['username'] == 'john'
