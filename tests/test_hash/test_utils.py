import unittest

from ab_hash.utils import count_md5


class TestCountMd5(unittest.TestCase):
    """测试 count_md5 函数"""

    def test_basic_types(self):
        """测试基础类型"""
        # 测试字符串
        result = count_md5("hello")
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

        # 测试整数
        result = count_md5(123)
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

        # 测试浮点数
        result = count_md5(123.45)
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

        # 测试布尔值
        result = count_md5(True)
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

        result = count_md5(False)
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

        # 测试None
        result = count_md5(None)
        self.assertTrue(result.startswith("val:"))
        self.assertTrue(result.endswith("|"))

    def test_dict_type(self):
        """测试字典类型"""
        # 测试空字典
        result = count_md5({})
        # 确保返回有效的MD5字符串
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

        # 测试简单字典
        simple_dict = {"a": 1, "b": 2}
        result = count_md5(simple_dict)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

        # 测试嵌套字典
        nested_dict = {"a": {"b": 2}}
        result = count_md5(nested_dict)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_list_type(self):
        """测试列表类型"""
        # 测试空列表
        result = count_md5([])
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

        # 测试简单列表
        simple_list = [1, 2, 3]
        result = count_md5(simple_list)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

        # 测试嵌套列表
        nested_list = [1, [2, 3]]
        result = count_md5(nested_list)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_tuple_and_set_types(self):
        """测试元组和集合类型"""
        # 测试元组
        test_tuple = (1, 2, 3)
        result = count_md5(test_tuple)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

        # 测试集合
        test_set = {1, 2, 3}
        # 集合排序后应与列表结果一致
        result = count_md5(test_set)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_callable_type(self):
        """测试可调用对象"""

        def test_func():
            pass

        # 测试函数对象
        result = count_md5(test_func)
        # 函数对象应该返回MD5哈希值
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_circular_reference(self):
        """测试循环引用"""
        # 创建真正的循环引用结构
        circular_list = []
        circular_list.append(circular_list)

        # 应该返回特定的循环引用标识
        result = count_md5(circular_list)
        # 检查返回值是否为字符串
        self.assertIsInstance(result, str)

    def test_dict_sorting(self):
        """测试字典排序参数"""
        # 两个键值相同的字典，顺序不同
        dict1 = {"a": 1, "b": 2}
        dict2 = {"b": 2, "a": 1}

        # 当启用排序时，应该返回相同结果
        self.assertEqual(count_md5(dict1, dict_sort=True), count_md5(dict2, dict_sort=True))

        # 当禁用排序时，测试不会引发异常
        result1 = count_md5(dict1, dict_sort=False)
        result2 = count_md5(dict2, dict_sort=False)
        self.assertEqual(len(result1), 32)
        self.assertEqual(len(result2), 32)

    def test_list_sorting(self):
        """测试列表排序参数"""
        # 两个元素相同的列表，顺序不同
        list1 = [1, 2, 3]
        list2 = [3, 2, 1]

        # 当启用排序时，应该返回相同结果
        self.assertEqual(count_md5(list1, list_sort=True), count_md5(list2, list_sort=True))

        # 当禁用排序时，测试不会引发异常
        result1 = count_md5(list1, list_sort=False)
        result2 = count_md5(list2, list_sort=False)
        self.assertEqual(len(result1), 32)
        self.assertEqual(len(result2), 32)

    def test_complex_nested_structure(self):
        """测试复杂嵌套结构"""
        complex_structure = {
            "list": [1, 2, {"nested": "value"}],
            "tuple": (3, 4),
            "set": {5, 6},
            "dict": {"inner": [7, 8]},
        }

        result = count_md5(complex_structure)
        # 确保返回有效的MD5字符串
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_custom_object(self):
        """测试自定义对象"""

        class CustomObject:
            pass

        obj = CustomObject()
        result = count_md5(obj)
        # 自定义对象应该返回MD5哈希值
        self.assertEqual(len(result), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))


if __name__ == "__main__":
    unittest.main()
