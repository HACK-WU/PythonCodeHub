import unittest

from ab_elasticsearch.utils import escape_query_string


class TestEscapeQueryString(unittest.TestCase):
    """测试 escape_query_string 函数"""

    # 标记不进行ruff 检查
    # noinspection PyMethodMayBeStatic
    def test_non_string_input(self):
        """测试非字符串输入"""
        assert escape_query_string(None) is None
        assert escape_query_string(123) == 123
        assert escape_query_string(True) is True

    def test_empty_string(self):
        """测试空字符串"""
        assert escape_query_string("") == ""

    def test_no_special_chars(self):
        """测试无特殊字符的字符串"""
        assert escape_query_string("abc", many=True) == ["abc"]
        assert escape_query_string("hello_world") == "hello_world"

    def test_single_special_char(self):
        """测试单个特殊字符转义"""
        assert escape_query_string("a+b", many=True) == ["a\\+b"]
        assert escape_query_string("c?d", many=True) == ["c\\?d"]
        assert escape_query_string("e/f") == "e\\/f"
        assert escape_query_string("g^h") == "g\\^h"

    def test_multiple_special_chars(self):
        """测试多个特殊字符组合"""
        assert escape_query_string("[a||b]"), "\\[a\\|\\|b\\]"
        assert escape_query_string("a&&b||c"), "a\\&\\&b\\|\\|c"
        assert escape_query_string("{x:y}"), "\\{x\\:y\\}"

    def test_pre_escaped_chars(self):
        """测试已转义字符处理(避免双重转义)"""
        assert escape_query_string("\\+\\-") == "\\+\\-"
        assert escape_query_string("a\\*b\\?c") == "a\\*b\\?c"
        assert escape_query_string("\\[test\\]") == "\\[test\\]"

    def test_edge_cases(self):
        """测试边界情况"""
        # 连续特殊字符
        assert escape_query_string("|||") == "\\|\\|\\|"
        # 特殊字符开头/结尾
        assert escape_query_string("+abc") == "\\+abc"
        assert escape_query_string("xyz!") == "xyz\\!"

        # 混合内容
        assert escape_query_string("a\\+b?c") == "a\\+b\\?c"
        assert escape_query_string("file\\/path") == "file\\/path"

        assert escape_query_string("a\\+b?c") == "a\\+b\\?c"
        assert escape_query_string("file\\/path") == "file\\/path"

    def test_backslash_handling(self):
        """测试反斜杠特殊处理"""
        # 单独反斜杠(非转义用途)
        assert escape_query_string("a\\b") == "a\\\\b"
        # 组合情
        assert escape_query_string("\\\\x") == "\\\\x"
        assert escape_query_string("C:\\\\path") == "C\\:\\\\path"


if __name__ == "__main__":
    unittest.main()
