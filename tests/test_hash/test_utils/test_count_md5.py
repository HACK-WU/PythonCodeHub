import unittest

from ab_hash.utils import count_md5, _stable_order_key


class TestCountMd5(unittest.TestCase):
    """测试 count_md5 函数"""

    def test_base_types_string(self):
        """测试基础类型：字符串"""
        result1 = count_md5("hello")
        result2 = count_md5("hello")
        result3 = count_md5("world")

        # 相同字符串应生成相同哈希
        assert result1 == result2
        # 不同字符串应生成不同哈希
        assert result1 != result3
        # 应返回 base: 前缀格式
        assert result1.startswith("base:")

    def test_base_types_integer(self):
        """测试基础类型：整数"""
        result1 = count_md5(123)
        result2 = count_md5(123)
        result3 = count_md5(456)

        assert result1 == result2
        assert result1 != result3
        assert result1.startswith("base:")

    def test_base_types_float(self):
        """测试基础类型：浮点数"""
        result1 = count_md5(3.14)
        result2 = count_md5(3.14)
        result3 = count_md5(2.71)

        assert result1 == result2
        assert result1 != result3
        assert result1.startswith("base:")

    def test_base_types_boolean(self):
        """测试基础类型：布尔值"""
        result_true1 = count_md5(True)
        result_true2 = count_md5(True)
        result_false = count_md5(False)

        assert result_true1 == result_true2
        assert result_true1 != result_false
        assert result_true1.startswith("base:")

    def test_base_types_none(self):
        """测试基础类型：None"""
        result1 = count_md5(None)
        result2 = count_md5(None)

        assert result1 == result2
        assert result1.startswith("base:")

    def test_dict_sorted(self):
        """测试字典类型：键排序模式"""
        dict1 = {"b": 2, "a": 1, "c": 3}
        dict2 = {"a": 1, "c": 3, "b": 2}
        dict3 = {"a": 1, "b": 2, "c": 4}

        result1 = count_md5(dict1, dict_sort=True)
        result2 = count_md5(dict2, dict_sort=True)
        result3 = count_md5(dict3, dict_sort=True)

        # 相同内容不同顺序的字典应生成相同MD5
        assert result1 == result2
        # 不同内容的字典应生成不同MD5
        assert result1 != result3
        # 应返回32位十六进制MD5
        assert len(result1) == 32
        assert all(c in "0123456789abcdef" for c in result1)

    def test_dict_unsorted(self):
        """测试字典类型：不排序模式"""
        dict1 = {"a": 1, "b": 2}
        dict2 = {"b": 2, "a": 1}

        result1 = count_md5(dict1, dict_sort=False)
        result2 = count_md5(dict2, dict_sort=False)

        # 不排序模式下，顺序不同可能生成不同MD5（取决于Python版本）
        # 这里只验证能正常执行
        assert len(result1) == 32
        assert len(result2) == 32

    def test_dict_nested(self):
        """测试嵌套字典"""
        nested1 = {"outer": {"inner": {"deep": "value"}}}
        nested2 = {"outer": {"inner": {"deep": "value"}}}
        nested3 = {"outer": {"inner": {"deep": "other"}}}

        result1 = count_md5(nested1)
        result2 = count_md5(nested2)
        result3 = count_md5(nested3)

        # 相同嵌套结构应生成相同MD5
        assert result1 == result2
        # 不同内容应生成不同MD5
        assert result1 != result3

    def test_list_sorted(self):
        """测试列表类型：排序模式"""
        list1 = [3, 1, 2]
        list2 = [1, 2, 3]
        list3 = [1, 2, 4]

        result1 = count_md5(list1, list_sort=True)
        result2 = count_md5(list2, list_sort=True)
        result3 = count_md5(list3, list_sort=True)

        # 排序模式下，相同元素不同顺序应生成相同MD5
        assert result1 == result2
        # 不同元素应生成不同MD5
        assert result1 != result3

    def test_list_unsorted(self):
        """测试列表类型：不排序模式"""
        list1 = [1, 2, 3]
        list2 = [3, 2, 1]

        result1 = count_md5(list1, list_sort=False)
        result2 = count_md5(list2, list_sort=False)

        # 不排序模式下，顺序不同应生成不同MD5
        assert result1 != result2

    def test_tuple_sorted(self):
        """测试元组类型：排序模式"""
        tuple1 = (3, 1, 2)
        tuple2 = (1, 2, 3)

        result1 = count_md5(tuple1, list_sort=True)
        result2 = count_md5(tuple2, list_sort=True)

        # 排序模式下应生成相同MD5
        assert result1 == result2

    def test_set_sorted(self):
        """测试集合类型：排序模式"""
        set1 = {3, 1, 2}
        set2 = {1, 2, 3}
        set3 = {1, 2, 4}

        result1 = count_md5(set1, list_sort=True)
        result2 = count_md5(set2, list_sort=True)
        result3 = count_md5(set3, list_sort=True)

        # 集合无序，排序后应生成相同MD5
        assert result1 == result2
        # 不同元素应生成不同MD5
        assert result1 != result3

    def test_mixed_types_list(self):
        """测试混合类型列表"""
        mixed_list = [1, "two", 3.0, True, None]
        result = count_md5(mixed_list, list_sort=True)

        # 应能正常处理混合类型
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_callable_function(self):
        """测试可调用对象：函数"""

        def test_func():
            pass

        result = count_md5(test_func)

        # 应返回32位MD5
        assert len(result) == 32

    def test_callable_lambda(self):
        """测试可调用对象：lambda"""
        lambda_func = lambda x: x + 1  # noqa: E731

        result = count_md5(lambda_func)

        # 应返回32位MD5
        assert len(result) == 32

    def test_custom_object(self):
        """测试自定义对象"""

        class CustomClass:
            def __init__(self, value):
                self.value = value

        obj = CustomClass(42)
        result = count_md5(obj)

        # 应返回32位MD5
        assert len(result) == 32

    def test_circular_reference_list(self):
        """测试循环引用：列表"""
        circular_list = [1, 2, 3]
        circular_list.append(circular_list)  # 创建循环引用

        result = count_md5(circular_list)

        # 应能处理循环引用，不会无限递归
        assert len(result) == 32

    def test_circular_reference_dict(self):
        """测试循环引用：字典"""
        circular_dict = {"a": 1, "b": 2}
        circular_dict["self"] = circular_dict  # 创建循环引用

        result = count_md5(circular_dict)

        # 应能处理循环引用
        assert len(result) == 32

    def test_deep_nested_structure(self):
        """测试深度嵌套结构"""
        deep_structure = {
            "level1": {"level2": {"level3": {"level4": {"level5": "deep"}}}}
        }

        result = count_md5(deep_structure)

        # 应能处理深度嵌套
        assert len(result) == 32

    def test_complex_nested_structure(self):
        """测试复杂嵌套结构"""
        complex_data = {
            "users": [
                {"id": 1, "name": "Alice", "tags": ["admin", "user"]},
                {"id": 2, "name": "Bob", "tags": ["user"]},
            ],
            "settings": {"theme": "dark", "language": "zh-CN"},
            "metadata": {"version": "1.0", "count": 100},
        }

        result1 = count_md5(complex_data)
        result2 = count_md5(complex_data)

        # 相同复杂结构应生成相同MD5
        assert result1 == result2
        assert len(result1) == 32

    def test_empty_containers(self):
        """测试空容器"""
        empty_dict = {}
        empty_list = []
        empty_tuple = ()
        empty_set = set()

        result_dict = count_md5(empty_dict)
        result_list = count_md5(empty_list)
        result_tuple = count_md5(empty_tuple)
        result_set = count_md5(empty_set)

        # 所有空容器应能正常处理
        assert len(result_dict) == 32
        assert len(result_list) == 32
        assert len(result_tuple) == 32
        assert len(result_set) == 32

        # 空容器生成相同MD5是合理的（因为都没有内容）
        # 这里只验证能正常处理即可

    def test_consistency_multiple_calls(self):
        """测试多次调用一致性"""
        test_data = {"key": [1, 2, 3], "nested": {"a": "b"}}

        results = [count_md5(test_data) for _ in range(10)]

        # 多次调用应生成相同结果
        assert len(set(results)) == 1

    def test_dict_sort_parameter_effect(self):
        """测试 dict_sort 参数效果"""
        data = {"z": 1, "a": 2, "m": 3}

        result_sorted = count_md5(data, dict_sort=True)
        result_unsorted = count_md5(data, dict_sort=False)

        # 两种模式都应返回有效MD5
        assert len(result_sorted) == 32
        assert len(result_unsorted) == 32

    def test_list_sort_parameter_effect(self):
        """测试 list_sort 参数效果"""
        data = [5, 2, 8, 1, 9]

        result_sorted = count_md5(data, list_sort=True)
        result_unsorted = count_md5(data, list_sort=False)

        # 两种模式都应返回有效MD5
        assert len(result_sorted) == 32
        assert len(result_unsorted) == 32
        # 排序与不排序应产生不同结果
        assert result_sorted != result_unsorted

    def test_unicode_strings(self):
        """测试 Unicode 字符串"""
        unicode_data = {
            "中文": "你好世界",
            "emoji": "😀🎉🚀",
            "mixed": "Hello世界123",
        }

        result = count_md5(unicode_data)

        # 应能正确处理 Unicode
        assert len(result) == 32

    def test_special_characters(self):
        """测试特殊字符"""
        special_data = {
            "newline": "line1\nline2",
            "tab": "col1\tcol2",
            "quote": 'He said "Hello"',
            "backslash": "path\\to\\file",
        }

        result = count_md5(special_data)

        # 应能正确处理特殊字符
        assert len(result) == 32

    def test_large_numbers(self):
        """测试大数字"""
        large_int = 123456789012345678901234567890
        large_float = 1.23456789e100

        result_int = count_md5(large_int)
        result_float = count_md5(large_float)

        # 应能处理大数字
        assert result_int.startswith("base:")
        assert result_float.startswith("base:")

    def test_negative_numbers(self):
        """测试负数"""
        negative_data = [-1, -3.14, {"neg": -100}]

        result = count_md5(negative_data)

        # 应能处理负数
        assert len(result) == 32


class TestStableOrderKey(unittest.TestCase):
    """测试 _stable_order_key 辅助函数"""

    def test_string_type(self):
        """测试字符串类型"""
        result = _stable_order_key("hello")
        assert result.startswith("s:")
        assert "'hello'" in result

    def test_integer_type(self):
        """测试整数类型"""
        result = _stable_order_key(123)
        assert result.startswith("i:")
        assert "123" in result

    def test_float_type(self):
        """测试浮点数类型"""
        result = _stable_order_key(3.14)
        assert result.startswith("f:")
        assert "3.14" in result

    def test_boolean_type(self):
        """测试布尔类型"""
        result_true = _stable_order_key(True)
        result_false = _stable_order_key(False)

        assert result_true.startswith("b:")
        assert result_false.startswith("b:")
        assert "True" in result_true
        assert "False" in result_false

    def test_dict_type(self):
        """测试字典类型"""
        result = _stable_order_key({"a": 1})
        assert result.startswith("o_d:")

    def test_list_type(self):
        """测试列表类型"""
        result = _stable_order_key([1, 2, 3])
        assert result.startswith("o_l:")

    def test_tuple_type(self):
        """测试元组类型"""
        result = _stable_order_key((1, 2))
        assert result.startswith("o_t:")

    def test_set_type(self):
        """测试集合类型"""
        result = _stable_order_key({1, 2, 3})
        assert result.startswith("o_s:")

    def test_sorting_mixed_types(self):
        """测试混合类型排序"""
        mixed_list = [1, "two", 3.0, True, {"key": "value"}]

        # 应能对混合类型列表排序而不抛出异常
        sorted_list = sorted(mixed_list, key=_stable_order_key)

        # 验证排序后列表长度不变
        assert len(sorted_list) == len(mixed_list)

    def test_type_prefix_uniqueness(self):
        """测试类型前缀唯一性"""
        # 相同值不同类型应有不同的排序键
        key_int = _stable_order_key(1)
        key_str = _stable_order_key("1")
        key_float = _stable_order_key(1.0)
        key_bool = _stable_order_key(True)

        # 类型前缀应不同
        assert key_int.split(":")[0] != key_str.split(":")[0]
        assert key_int.split(":")[0] != key_float.split(":")[0]
        assert key_int.split(":")[0] != key_bool.split(":")[0]

    def test_consistency(self):
        """测试一致性"""
        value = "test"
        result1 = _stable_order_key(value)
        result2 = _stable_order_key(value)

        # 相同值应生成相同排序键
        assert result1 == result2


class TestEdgeCases(unittest.TestCase):
    """测试边界情况和异常场景"""

    def test_very_large_dict(self):
        """测试大型字典"""
        large_dict = {f"key_{i}": i for i in range(1000)}
        result = count_md5(large_dict)

        # 应能处理大型字典
        assert len(result) == 32

    def test_very_large_list(self):
        """测试大型列表"""
        large_list = list(range(1000))
        result = count_md5(large_list)

        # 应能处理大型列表
        assert len(result) == 32

    def test_deeply_nested_circular_reference(self):
        """测试深度嵌套的循环引用"""
        level1 = {"data": "level1"}
        level2 = {"data": "level2", "parent": level1}
        level3 = {"data": "level3", "parent": level2}
        level1["child"] = level3  # 创建循环

        result = count_md5(level1)

        # 应能处理复杂循环引用
        assert len(result) == 32

    def test_multiple_circular_references(self):
        """测试多个循环引用"""
        obj1 = {"name": "obj1"}
        obj2 = {"name": "obj2"}
        obj1["ref"] = obj2
        obj2["ref"] = obj1  # 相互引用

        result1 = count_md5(obj1)
        result2 = count_md5(obj2)

        # 应能处理相互引用
        assert len(result1) == 32
        assert len(result2) == 32

    def test_same_object_multiple_references(self):
        """测试同一对象的多次引用"""
        shared_obj = {"shared": "data"}
        container = {"ref1": shared_obj, "ref2": shared_obj, "ref3": shared_obj}

        result = count_md5(container)

        # 应能正确处理同一对象的多次引用
        assert len(result) == 32

    def test_class_with_slots(self):
        """测试使用 __slots__ 的类"""

        class SlottedClass:
            __slots__ = ["value"]

            def __init__(self, value):
                self.value = value

        obj = SlottedClass(42)
        result = count_md5(obj)

        # 应能处理 __slots__ 类
        assert len(result) == 32

    def test_bytes_in_dict(self):
        """测试字典中的字节类型"""
        data = {"bytes": b"binary data", "string": "text data"}

        result = count_md5(data)

        # 应能处理包含字节的字典
        assert len(result) == 32


if __name__ == "__main__":
    unittest.main()
