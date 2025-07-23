import unittest

from ab_string.utils import strip_outer_quotes


class TestStripOuterQuotes(unittest.TestCase):
    def test_no_quotes(self):
        assert strip_outer_quotes("hello") == "hello"
        assert strip_outer_quotes("test string") == "test string"

    def test_single_quotes(self):
        assert strip_outer_quotes("'hello'") == "hello"
        assert strip_outer_quotes("'test'") == "test"

    def test_double_quotes(self):
        assert strip_outer_quotes('"hello"') == "hello"
        assert strip_outer_quotes('"test"') == "test"

    def test_nested_quotes(self):
        assert strip_outer_quotes("\"'mixed'\"") == "mixed"
        assert strip_outer_quotes("'\"double\"'") == "double"

    def test_multiple_layers(self):
        assert strip_outer_quotes('""""deep""""') == "deep"
        assert strip_outer_quotes("''''nest''''") == "nest"

    def test_empty_string(self):
        assert strip_outer_quotes("") == ""
        assert strip_outer_quotes('""') == '""'
        assert strip_outer_quotes("''") == "''"

    def test_non_string_input(self):
        assert strip_outer_quotes(123) == 123
        assert strip_outer_quotes(None) is None
        assert strip_outer_quotes(True) is True

    def test_with_whitespace(self):
        assert strip_outer_quotes(" ''trim'   ' ") == "trim"
        assert strip_outer_quotes('\n"newline"\t') == "newline"

    def test_mixed_quotes(self):
        assert strip_outer_quotes("\"'mixed'\"") == "mixed"
        assert strip_outer_quotes("'\"reverse\"'") == "reverse"


if __name__ == "__main__":
    unittest.main()
