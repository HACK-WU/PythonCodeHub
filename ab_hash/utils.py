import hashlib
from typing import Any

# 预处理基础类型（避免无效递归）
_BASE_TYPES = (str, int, float, bool, type(None))


def count_md5(
    content: Any,
    dict_sort: bool = True,
    list_sort: bool = True,
    _path_ids: tuple = None,
) -> str:
    """
    安全计算结构化数据MD5，自动处理深度嵌套与循环引用

    参数:
        content: 待计算MD5的任意类型数据（支持基础类型、字典、列表、元组、集合、函数等）
        dict_sort: 是否对字典的键进行排序，默认True（保证相同内容的字典生成相同MD5）
        list_sort: 是否对列表/元组/集合进行排序，默认True（保证相同元素的集合生成相同MD5）
        _path_ids: 内部参数，用于记录递归路径中的对象ID栈，防止循环引用导致无限递归

    返回值:
        str: 32位十六进制MD5哈希值，或特殊标识字符串（如循环引用标识、基础类型哈希）

    该方法实现完整的结构化数据MD5计算流程，包含：
    1. 循环引用检测（通过对象ID栈追踪递归路径）
    2. 基础类型快速处理（字符串、数字、布尔值、None）
    3. 字典类型递归处理（支持键排序，格式：k:键|v:值）
    4. 列表/元组/集合递归处理（支持元素排序，格式：item:值|）
    5. 可调用对象处理（使用函数名生成哈希）
    6. 其他对象类型处理（使用类型名生成哈希）
    7. 自动清理路径栈（通过finally确保栈正确回退）
    """

    # ● 步骤1：初始化路径 ID 栈（首次调用时创建空元组）
    # 用于追踪递归调用链中所有对象的内存地址，防止循环引用
    if _path_ids is None:
        _path_ids = ()

    # ● 步骤2：获取当前对象的唯一标识符（内存地址）
    obj_id = id(content)

    # ● 步骤3：循环引用检测
    # 如果当前对象ID已在路径栈中，说明出现循环引用，返回固定标识避免无限递归
    if obj_id in _path_ids:
        return "circular_ref_hash"  # 使用固定值保证一致性

    # ● 步骤4：基础类型快速处理
    # 对于不可变的基础类型（str, int, float, bool, None），直接使用内置hash函数
    if isinstance(content, _BASE_TYPES):
        return f"base:{hash(content)}"

    # ● 步骤5：初始化MD5哈希对象
    hasher = hashlib.md5()

    try:
        # ● 步骤6：将当前对象ID压入路径栈（标记正在处理此对象）
        _path_ids = _path_ids + (obj_id,)

        # ● 步骤7：字典类型处理
        if isinstance(content, dict):
            # 优化：先获取键列表避免多次keys()扫描
            # 如果dict_sort=True，对键排序以保证相同内容的字典生成相同MD5
            keys = sorted(content) if dict_sort else content.keys()
            for k in keys:
                # 格式：k:键名|v:值的MD5
                hasher.update(f"k:{k!s}|v:".encode())
                # 递归计算值的MD5，并将结果编码后更新到哈希对象
                hasher.update(
                    count_md5(content[k], dict_sort, list_sort, _path_ids).encode()
                )

        # ● 步骤8：列表/元组/集合类型处理
        elif isinstance(content, (list, tuple, set)):
            # 如果list_sort=True，对元素排序（使用稳定排序键函数）
            items = sorted(content, key=_stable_order_key) if list_sort else content
            for item in items:
                # 格式：item:值的MD5|
                hasher.update(b"item:")
                hasher.update(count_md5(item, dict_sort, list_sort, _path_ids).encode())
                hasher.update(b"|")

        # ● 步骤9：可调用对象（函数、方法等）处理
        elif callable(content):
            # 使用函数名生成哈希（格式：fn:函数名）
            hasher.update(f"fn:{content.__name__}".encode())

        # ● 步骤10：其他对象类型处理
        else:
            # 使用对象的类型名生成哈希（格式：obj:类型名）
            hasher.update(f"obj:{type(content).__name__}".encode())

        # ● 步骤11：返回32位十六进制MD5哈希值
        return hasher.hexdigest()

    finally:
        # ● 步骤12：清理路径栈（无论是否异常都要执行）
        # 将当前对象ID从栈中弹出，确保递归回退时栈状态正确
        _path_ids = _path_ids[:-1]


def _stable_order_key(x: Any) -> str:
    """
    生成类型安全的排序键（规避不同类型间的比较冲突）

    参数:
        x: 任意类型的待排序元素

    返回值:
        str: 格式化的排序键字符串，格式为 "类型标识:值的repr表示"

    该方法解决混合类型集合排序问题，包含：
    1. 为常见类型分配单字符标识（s=字符串, i=整数, f=浮点数, b=布尔值）
    2. 为其他类型生成动态标识（o_类型名首字母）
    3. 使用repr()确保值的字符串表示唯一且可比较
    4. 通过类型前缀确保不同类型元素不会因值相同而冲突（如：1 vs "1"）

    示例:
        _stable_order_key(123) -> "i:123"
        _stable_order_key("abc") -> "s:'abc'"
        _stable_order_key(True) -> "b:True"
        _stable_order_key({"a": 1}) -> "o_d:{'a': 1}"
    """
    # ● 步骤1：根据元素类型分配类型标识符
    # 常见类型使用单字符标识，其他类型使用 "o_类型名首字母" 格式
    type_flag = {str: "s", int: "i", float: "f", bool: "b"}.get(
        type(x), f"o_{type(x).__name__[0]}"
    )

    # ● 步骤2：生成排序键
    # 格式：类型标识:值的repr表示（确保类型安全且唯一）
    return f"{type_flag}:{x!r}"
