import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class BaseResponseParser(ABC):
    """响应解析器基类，定义解析 requests.Response 的接口。"""

    # 新增类变量，用于控制是否使用流式响应
    is_stream: bool = False

    @abstractmethod
    def parse(self, client_instance, response: requests.Response) -> Any:
        """解析 requests.Response 对象并返回所需格式的数据。"""


class JSONResponseParser(BaseResponseParser):
    """解析响应为 JSON 数据"""

    # 设置 is_stream 为 False，因为需要完整读取响应体才能解析为 JSON
    is_stream: bool = False

    def parse(self, client_instance, response: requests.Response) -> Any:  # noqa: ARG002
        logger.debug("Parsing response as JSON")
        return response.json()


class ContentResponseParser(BaseResponseParser):
    """解析响应为 Content 字节数据"""

    # 设置 is_stream 为 False，因为需要完整读取响应体内容
    is_stream: bool = False

    def parse(self, client_instance, response: requests.Response) -> bytes:  # noqa: ARG002
        logger.debug("Parsing response as content bytes")
        # 确保响应内容被完全读取（非流式）
        # response.content 会处理 stream
        return response.content


class RawResponseParser(BaseResponseParser):
    """返回原始响应对象以支持流式处理"""

    is_stream: bool = True

    def parse(self, client_instance, response: requests.Response) -> requests.Response:  # noqa: ARG002
        logger.debug("Returning raw response object for streaming")
        # 流式处理，直接返回响应对象
        return response


class FileWriteResponseParser(BaseResponseParser):
    """将响应内容写入文件"""

    is_stream: bool = True
    chunk_size: int = 8192
    base_path: str = "./downloads"
    default_filename = "downloaded_file"
    suffix: str = ""

    def __init__(self, base_path=None, chunk_size=None, default_filename=None):
        self.base_path = base_path or self.base_path
        self.chunk_size = chunk_size or self.chunk_size
        self.default_filename = default_filename or self.default_filename
        os.makedirs(self.base_path, exist_ok=True)

    def parse(self, client_instance, response: requests.Response) -> str:  # noqa: ARG002
        default_filename = self.default_filename
        if response.url:
            url_path = response.url.split("?")[0]
            parts = url_path.rstrip("/").split("/")
            if parts:
                default_filename = parts[-1]
        filename = getattr(self, "_current_filename", None) or default_filename
        if self.suffix:
            filename += self.suffix

        file_path = os.path.join(self.base_path, filename)
        logger.debug(f"Writing response content to file: {file_path}")

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=self.chunk_size):
                if chunk:
                    f.write(chunk)
        return file_path
