"""
HTTP 客户端使用示例

演示如何使用 ab_request.http_client 模块的各种功能
"""

from requests.auth import AuthBase

from ab_request.http_client import (
    BaseClient,
    ContentResponseParser,
    JSONResponseParser,
)


class PizzaAuth(AuthBase):
    """
    自定义认证示例

    在请求头中添加自定义认证信息
    """

    def __init__(self, username: str):
        self.username = username

    def __call__(self, r):
        r.headers["X-Pizza"] = self.username
        return r


class HttpbinClient(BaseClient):
    """
    Httpbin 测试客户端

    用于演示基本的 HTTP 请求功能
    """

    base_url = "https://httpbin.org"


class BaiduClient(BaseClient):
    """
    百度客户端示例

    演示如何配置认证和基础 URL
    """

    base_url = "https://www.baidu.com"
    authentication_class = PizzaAuth("默认用户")


class BaiduUser(BaiduClient):
    """
    百度用户客户端

    演示如何继承和扩展客户端
    """

    endpoint = "/user"
    method = "GET"


class BaiduUserDetail(BaiduUser):
    """
    百度用户详情客户端

    演示多层继承
    """

    endpoint = "/detail"
    method = "GET"


def example_basic_request():
    """示例 1: 基本请求"""
    print("--- 1. 基本请求 (返回格式化后的字典) ---")
    client = HttpbinClient()
    result = client.request({"endpoint": "/get", "params": {"key": "value"}})
    print(f"  结果: {result}")
    print()


def example_json_parser():
    """示例 2: 使用 JSON 解析器"""
    print("--- 2. 使用 JSON 解析器 ---")
    client = HttpbinClient(response_parser=JSONResponseParser())
    result = client.request({"endpoint": "/get", "params": {"key": "value"}})
    print(f"  JSON 结果: {result}")
    print()


def example_content_parser():
    """示例 3: 获取字节内容"""
    print("--- 3. 获取字节内容 ---")
    client = HttpbinClient(response_parser=ContentResponseParser())
    result = client.request({"endpoint": "/get", "params": {"key": "value"}})
    data_type = type(result["data"])
    data_length = len(result["data"]) if result["data"] else 0
    print(f"  内容类型: {data_type}, 长度: {data_length} 字节")
    print()


def example_error_handling():
    """示例 4: 错误处理"""
    print("--- 4. 错误处理 ---")
    client = HttpbinClient()
    result = client.request({"endpoint": "/status/404", "method": "GET"})
    print(f"  错误结果: {result}")
    print()


def example_class_level_config():
    """示例 5: 类级别配置"""
    print("--- 5. 类级别配置 ---")

    class HttpbinJSONClient(HttpbinClient):
        response_parser_class = JSONResponseParser

    client = HttpbinJSONClient()
    result = client.request({"endpoint": "/json"})
    print(f"  类级别配置结果: {result}")
    print()


def example_async_requests():
    """示例 6: 异步请求"""
    print("--- 6. 异步请求 ---")
    client = HttpbinClient(response_parser=JSONResponseParser())
    results = client.request(
        [
            {"endpoint": "/get", "params": {"id": 1}},
            {"endpoint": "/status/404", "method": "GET"},
            {"endpoint": "/uuid"},
        ],
        is_async=True,
    )
    print("  异步请求结果:")
    for i, res in enumerate(results):
        if isinstance(res, dict):
            print(f"    请求 {i + 1}: {res}")
        elif isinstance(res, Exception):
            print(f"    请求 {i + 1}: 异常 - {type(res).__name__}: {res}")
        else:
            print(f"    请求 {i + 1}: 未知类型 {type(res)}: {res}")
    print()


def example_custom_auth():
    """示例 7: 自定义认证"""
    print("--- 7. 自定义认证 ---")
    client = BaiduClient()
    print(f"  客户端基础 URL: {client.base_url}")
    print(f"  认证类: {client.auth_instance}")
    print()


def example_context_manager():
    """示例 8: 使用上下文管理器"""
    print("--- 8. 使用上下文管理器 ---")
    with HttpbinClient() as client:
        result = client.request({"endpoint": "/get", "params": {"test": "context"}})
        print(f"  上下文管理器结果: {result}")
    print("  会话已自动关闭")
    print()


def main():
    """运行所有示例"""
    print("=" * 60)
    print("AB Request HTTP Client 使用示例")
    print("=" * 60)
    print()

    try:
        example_basic_request()
        example_json_parser()
        example_content_parser()
        example_error_handling()
        example_class_level_config()
        example_async_requests()
        example_custom_auth()
        example_context_manager()
    except Exception as e:
        print(f"示例执行出错: {e}")
        import traceback

        traceback.print_exc()

    print("=" * 60)
    print("所有示例执行完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
