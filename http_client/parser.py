"""
响应解析器模块

提供多种响应解析器，支持 JSON、字节流、文件下载等不同的响应处理方式
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import requests

from http_client.constants import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DOWNLOAD_PATH,
    DEFAULT_FILENAME,
)

logger = logging.getLogger(__name__)


class BaseResponseParser(ABC):
    """响应解析器基类，定义解析 requests.Response 的接口。"""

    # 新增类变量，用于控制是否使用流式响应
    is_stream: bool = False

    @abstractmethod
    def parse(self, client_instance: BaseClient, response: requests.Response) -> Any:  # noqa: F821
        """解析 requests.Response 对象并返回所需格式的数据。"""


class JSONResponseParser(BaseResponseParser):
    """解析响应为 JSON 数据"""

    # 设置 is_stream 为 False，因为需要完整读取响应体才能解析为 JSON
    is_stream: bool = False

    def parse(self, client_instance: BaseClient, response: requests.Response) -> Any:  # noqa: F821
        logger.debug("Parsing response as JSON")
        return response.json()


class ContentResponseParser(BaseResponseParser):
    """解析响应为 Content 字节数据"""

    # 设置 is_stream 为 False，因为需要完整读取响应体内容
    is_stream: bool = False

    def parse(self, client_instance: BaseClient, response: requests.Response) -> bytes:  # noqa: F821
        logger.debug("Parsing response as content bytes")
        # 确保响应内容被完全读取（非流式）
        # response.content 会处理 stream
        return response.content


class RawResponseParser(BaseResponseParser):
    """返回原始响应对象"""

    is_stream: bool = False

    def parse(self, client_instance: BaseClient, response: requests.Response) -> requests.Response:  # noqa: F821
        logger.debug("Returning raw response object")
        return response


class StreamResponseParser(BaseResponseParser):
    """
    流式响应解析器

    返回原始响应对象，但启用流式读取模式。
    适用于需要逐块处理响应内容的场景，如大文件下载、实时数据流等。

    注意:
        - 响应内容不会自动加载到内存
        - 需要使用 response.iter_content() 或 response.iter_lines() 逐块读取
        - Session 关闭后将无法读取响应内容
        - 适合处理大型响应或需要边接收边处理的场景

    使用示例:
        >>> client = MyClient(response_parser=StreamResponseParser())
        >>> result = client.request({"endpoint": "/large-file"})
        >>> response = result["data"]
        >>> for chunk in response.iter_content(chunk_size=8192):
        >>>     process_chunk(chunk)
    """

    is_stream: bool = True

    def parse(self, client_instance: BaseClient, response: requests.Response) -> requests.Response:  # noqa: F821
        logger.debug("Returning raw response object with streaming enabled")
        return response


class FileWriteResponseParser(BaseResponseParser):
    """
    文件写入响应解析器

    将响应内容以流式方式写入文件，适用于大文件下载

    参数:
        base_path: 文件保存的基础路径
        chunk_size: 分块读取大小（字节）
        default_filename: 默认文件名
    """

    is_stream: bool = True
    chunk_size: int = DEFAULT_CHUNK_SIZE
    base_path: str = DEFAULT_DOWNLOAD_PATH
    default_filename = DEFAULT_FILENAME
    suffix: str = ""

    def __init__(self, base_path=None, chunk_size=None, default_filename=None):
        self.base_path = base_path or self.base_path
        self.chunk_size = chunk_size or self.chunk_size
        self.default_filename = default_filename or self.default_filename
        os.makedirs(self.base_path, exist_ok=True)

    def parse(self, client_instance: BaseClient, response: requests.Response) -> str:  # noqa: F821
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
