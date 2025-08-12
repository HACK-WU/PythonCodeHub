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
    安全计算结构化数据的MD5哈希值，自动处理深度嵌套与循环引用
    """

    # 初始化路径ID栈
    if _path_ids is None:
        _path_ids = ()

    obj_id = id(content)

    # 检测当前递归路径上的循环引用
    if obj_id in _path_ids:
        loop_depth = _path_ids.index(obj_id)
        return f"loop-{len(_path_ids) - loop_depth}"

    # 基础类型直接返回短路哈希
    if isinstance(content, _BASE_TYPES):
        # 增加空字符串隔离符，防'12'+'3' = '1'+'23'碰撞
        return f"val:{str(content)}|"

    # 初始化MD5哈希计算器
    hasher = hashlib.md5()

    try:
        # 更新递归路径ID栈
        _path_ids = _path_ids + (obj_id,)

        # 处理字典类型数据
        if isinstance(content, dict):
            # 获取排序后的键列表（根据dict_sort参数）
            keys = sorted(content) if dict_sort else content.keys()
            for k in keys:
                hasher.update(f"k:{k!s}|v:".encode())
                hasher.update(
                    count_md5(content[k], dict_sort, list_sort, _path_ids).encode()
                )

        # 处理列表/元组/set类型数据
        elif isinstance(content, (list, tuple, set)):
            # 获取排序后的迭代器（根据list_sort参数）
            items = sorted(content, key=_stable_order_key) if list_sort else content
            for item in items:
                # 流式更新列表项哈希
                hasher.update(b"item:")
                hasher.update(count_md5(item, dict_sort, list_sort, _path_ids).encode())
                hasher.update(b"|")

        # 处理可调用对象
        elif callable(content):
            # 使用函数名称进行哈希
            hasher.update(f"fn:{content.__name__}".encode())

        # 处理其他自定义对象
        else:
            # 使用类型名称进行哈希
            hasher.update(f"obj:{type(content).__name__}".encode())

        return hasher.hexdigest()

    finally:
        # 清理当前递归路径ID
        _path_ids = _path_ids[:-1]


def _stable_order_key(x: Any) -> str:
    """ 优先用序列化安全方式生成排序键（覆盖 repr 的缺陷） """
    try:
        # 首选JSON-safe类型标准化
        if isinstance(x, (int, float, bool)):
            return f"n:{x}"  # 数字型单独处理
        elif isinstance(x, str):
            return f"s:{x}"
        else:  # 兜底方案：用类型名+哈希（非base64为防非法字符）
            return f"o:{hashlib.md5(repr(x).encode()).hexdigest()[:6]}"
    except Exception:
        # 极端情况下用内存ID（避免崩溃，但需接受可能不稳定）
        return f"id:{id(x)}"
