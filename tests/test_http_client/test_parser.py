"""
parser.py 模块的单元测试

测试用例:
- UT-PARSER-001 到 UT-PARSER-019: 测试各种解析器的功能
"""

import os
import tempfile
import pytest
from abc import ABC
from unittest.mock import Mock
from http_client.parser import (
    BaseResponseParser,
    JSONResponseParser,
    ContentResponseParser,
    RawResponseParser,
    StreamResponseParser,
    FileWriteResponseParser,
)


class TestBaseResponseParser:
    """测试 BaseResponseParser 抽象基类"""

    @pytest.mark.unit
    def test_is_abstract_class(self):
        """验证 BaseResponseParser 是抽象类"""
        # Arrange & Act & Assert
        assert issubclass(BaseResponseParser, ABC)

        # 验证不能直接实例化
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseResponseParser()

    @pytest.mark.unit
    def test_has_abstract_parse_method(self):
        """验证 BaseResponseParser 有抽象 parse 方法"""
        # Arrange & Act & Assert
        assert hasattr(BaseResponseParser, "parse")
        assert getattr(BaseResponseParser.parse, "__isabstractmethod__", False)

    @pytest.mark.unit
    def test_has_is_stream_attribute(self):
        """验证 BaseResponseParser 有 is_stream 类变量"""
        # Arrange & Act & Assert
        assert hasattr(BaseResponseParser, "is_stream")
        assert BaseResponseParser.is_stream is False


class TestJSONResponseParser:
    """测试 JSONResponseParser 解析器"""

    @pytest.fixture
    def parser(self):
        """提供 JSONResponseParser 实例"""
        return JSONResponseParser()

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.fixture
    def mock_response(self):
        """Mock Response 对象"""
        response = Mock()
        response.json = Mock(return_value={"result": True, "data": "test"})
        return response

    @pytest.mark.unit
    def test_initialization(self, parser):
        """验证 JSONResponseParser 初始化"""
        # Arrange & Act & Assert
        assert isinstance(parser, JSONResponseParser)
        assert isinstance(parser, BaseResponseParser)
        assert parser.is_stream is False

    @pytest.mark.unit
    def test_parse_json_response(self, parser, mock_client, mock_response):
        """UT-PARSER-001: 解析 JSON 响应"""
        # Arrange & Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result == {"result": True, "data": "test"}
        mock_response.json.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "json_data",
        [
            {"key": "value"},
            {"nested": {"data": [1, 2, 3]}},
            [],
            [{"id": 1}, {"id": 2}],
            {"result": True, "code": 200, "message": "OK", "data": None},
        ],
    )
    def test_parse_various_json_formats(self, parser, mock_client, json_data):
        """参数化测试: 解析各种 JSON 格式"""
        # Arrange
        mock_response = Mock()
        mock_response.json = Mock(return_value=json_data)

        # Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result == json_data

    @pytest.mark.unit
    def test_is_stream_is_false(self, parser):
        """UT-PARSER-002: 验证 is_stream 为 False"""
        # Arrange & Act & Assert
        assert parser.is_stream is False


class TestContentResponseParser:
    """测试 ContentResponseParser 解析器"""

    @pytest.fixture
    def parser(self):
        """提供 ContentResponseParser 实例"""
        return ContentResponseParser()

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.mark.unit
    def test_initialization(self, parser):
        """验证 ContentResponseParser 初始化"""
        # Arrange & Act & Assert
        assert isinstance(parser, ContentResponseParser)
        assert isinstance(parser, BaseResponseParser)
        assert parser.is_stream is False

    @pytest.mark.unit
    def test_parse_content_response(self, parser, mock_client):
        """UT-PARSER-003: 解析字节内容响应"""
        # Arrange
        mock_response = Mock()
        mock_response.content = b"binary data content"

        # Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result == b"binary data content"
        assert isinstance(result, bytes)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "content",
        [
            b"simple text",
            b"\x00\x01\x02\x03",
            b"",
            b"UTF-8: \xe4\xb8\xad\xe6\x96\x87",
        ],
    )
    def test_parse_various_byte_content(self, parser, mock_client, content):
        """参数化测试: 解析各种字节内容"""
        # Arrange
        mock_response = Mock()
        mock_response.content = content

        # Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result == content
        assert isinstance(result, bytes)


class TestRawResponseParser:
    """测试 RawResponseParser 解析器"""

    @pytest.fixture
    def parser(self):
        """提供 RawResponseParser 实例"""
        return RawResponseParser()

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.mark.unit
    def test_initialization(self, parser):
        """验证 RawResponseParser 初始化"""
        # Arrange & Act & Assert
        assert isinstance(parser, RawResponseParser)
        assert isinstance(parser, BaseResponseParser)
        assert parser.is_stream is False

    @pytest.mark.unit
    def test_parse_returns_raw_response(self, parser, mock_client):
        """UT-PARSER-005: 返回原始响应对象"""
        # Arrange
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}

        # Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result is mock_response
        assert result.status_code == 200
        assert result.headers == {"Content-Type": "application/json"}


class TestStreamResponseParser:
    """测试 StreamResponseParser 解析器"""

    @pytest.fixture
    def parser(self):
        """提供 StreamResponseParser 实例"""
        return StreamResponseParser()

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.mark.unit
    def test_initialization(self, parser):
        """验证 StreamResponseParser 初始化"""
        # Arrange & Act & Assert
        assert isinstance(parser, StreamResponseParser)
        assert isinstance(parser, BaseResponseParser)
        assert parser.is_stream is True

    @pytest.mark.unit
    def test_is_stream_is_true(self, parser):
        """UT-PARSER-006: 验证 is_stream 为 True"""
        # Arrange & Act & Assert
        assert parser.is_stream is True

    @pytest.mark.unit
    def test_parse_returns_raw_response_with_stream(self, parser, mock_client):
        """UT-PARSER-007: 返回原始响应对象（流模式）"""
        # Arrange
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=iter([b"chunk1", b"chunk2"]))

        # Act
        result = parser.parse(mock_client, mock_response)

        # Assert
        assert result is mock_response
        # 验证 iter_content 方法存在
        assert hasattr(result, "iter_content")


class TestFileWriteResponseParser:
    """测试 FileWriteResponseParser 解析器"""

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def parser(self, temp_dir):
        """提供 FileWriteResponseParser 实例"""
        return FileWriteResponseParser(base_path=temp_dir)

    @pytest.fixture
    def mock_client(self):
        """Mock BaseClient 实例"""
        return Mock()

    @pytest.mark.unit
    def test_initialization_default(self):
        """UT-PARSER-008: 默认参数初始化"""
        # Arrange & Act
        parser = FileWriteResponseParser()

        # Assert
        assert isinstance(parser, FileWriteResponseParser)
        assert isinstance(parser, BaseResponseParser)
        assert parser.is_stream is True
        assert parser.base_path is not None
        assert parser.chunk_size > 0
        assert parser.default_filename is not None

    @pytest.mark.unit
    def test_initialization_custom_params(self, temp_dir):
        """UT-PARSER-009: 自定义参数初始化"""
        # Arrange & Act
        parser = FileWriteResponseParser(base_path=temp_dir, chunk_size=4096, default_filename="custom_file.txt")

        # Assert
        assert parser.base_path == temp_dir
        assert parser.chunk_size == 4096
        assert parser.default_filename == "custom_file.txt"
        assert os.path.exists(temp_dir)

    @pytest.mark.unit
    def test_parse_writes_file(self, parser, mock_client, temp_dir):
        """UT-PARSER-010: 解析响应并写入文件"""
        # Arrange
        mock_response = Mock()
        mock_response.url = "https://api.example.com/download/testfile.txt"
        mock_response.iter_content = Mock(return_value=iter([b"chunk1", b"chunk2", b"chunk3"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert file_path.startswith(temp_dir)
        assert "testfile.txt" in file_path

        # 验证文件内容
        with open(file_path, "rb") as f:
            content = f.read()
        assert content == b"chunk1chunk2chunk3"

    @pytest.mark.unit
    def test_parse_uses_default_filename(self, parser, mock_client, temp_dir):
        """UT-PARSER-011: 使用默认文件名"""
        # Arrange
        mock_response = Mock()
        mock_response.url = None
        mock_response.iter_content = Mock(return_value=iter([b"data"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert parser.default_filename in file_path

    @pytest.mark.unit
    def test_parse_extracts_filename_from_url(self, parser, mock_client, temp_dir):
        """UT-PARSER-012: 从 URL 提取文件名"""
        # Arrange
        mock_response = Mock()
        mock_response.url = "https://api.example.com/files/document.pdf?token=123"
        mock_response.iter_content = Mock(return_value=iter([b"pdf data"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert "document.pdf" in file_path

    @pytest.mark.unit
    def test_parse_handles_url_with_trailing_slash(self, parser, mock_client, temp_dir):
        """UT-PARSER-013: 处理带尾随斜杠的 URL"""
        # Arrange
        mock_response = Mock()
        mock_response.url = "https://api.example.com/download/file.txt/"
        mock_response.iter_content = Mock(return_value=iter([b"content"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert "file.txt" in file_path

    @pytest.mark.unit
    def test_parse_with_suffix(self, parser, mock_client, temp_dir):
        """UT-PARSER-014: 使用后缀"""
        # Arrange
        parser.suffix = ".backup"
        mock_response = Mock()
        mock_response.url = "https://api.example.com/file.txt"
        mock_response.iter_content = Mock(return_value=iter([b"data"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert file_path.endswith(".backup")
        assert "file.txt.backup" in file_path

    @pytest.mark.unit
    def test_parse_handles_empty_chunks(self, parser, mock_client, temp_dir):
        """UT-PARSER-015: 处理空块"""
        # Arrange
        mock_response = Mock()
        mock_response.url = "https://api.example.com/file.txt"
        mock_response.iter_content = Mock(return_value=iter([b"data1", b"", b"data2", None, b"data3"]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            content = f.read()
        # 空块和 None 应该被跳过
        assert content == b"data1data2data3"

    @pytest.mark.unit
    def test_parse_creates_directory_if_not_exists(self, temp_dir, mock_client):
        """UT-PARSER-016: 目录不存在时创建"""
        # Arrange
        non_existent_path = os.path.join(temp_dir, "subdir", "nested")
        parser = FileWriteResponseParser(base_path=non_existent_path)

        mock_response = Mock()
        mock_response.url = "https://api.example.com/file.txt"
        mock_response.iter_content = Mock(return_value=iter([b"content"]))

        # Assert - 目录应该在初始化时创建
        assert os.path.exists(non_existent_path)

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        assert os.path.exists(file_path)
        assert file_path.startswith(non_existent_path)

    @pytest.mark.unit
    def test_parse_overwrites_existing_file(self, parser, mock_client, temp_dir):
        """UT-PARSER-017: 覆盖已存在的文件"""
        # Arrange
        file_name = "existing.txt"
        file_path = os.path.join(temp_dir, file_name)

        # 创建已存在的文件
        with open(file_path, "wb") as f:
            f.write(b"old content")

        mock_response = Mock()
        mock_response.url = f"https://api.example.com/{file_name}"
        mock_response.iter_content = Mock(return_value=iter([b"new content"]))

        # Act
        result_path = parser.parse(mock_client, mock_response)

        # Assert
        assert result_path == file_path
        with open(result_path, "rb") as f:
            content = f.read()
        assert content == b"new content"

    @pytest.mark.unit
    def test_parse_with_custom_chunk_size(self, temp_dir, mock_client):
        """UT-PARSER-018: 自定义块大小"""
        # Arrange
        custom_chunk_size = 2048
        parser = FileWriteResponseParser(base_path=temp_dir, chunk_size=custom_chunk_size)

        mock_response = Mock()
        mock_response.url = "https://api.example.com/file.bin"
        mock_response.iter_content = Mock(return_value=iter([b"x" * 100]))

        # Act
        file_path = parser.parse(mock_client, mock_response)

        # Assert
        mock_response.iter_content.assert_called_once_with(chunk_size=custom_chunk_size)
        assert os.path.exists(file_path)

    @pytest.mark.unit
    def test_is_stream_is_true(self, parser):
        """UT-PARSER-019: 验证 is_stream 为 True"""
        # Arrange & Act & Assert
        assert parser.is_stream is True
