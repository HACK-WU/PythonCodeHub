from typing import Any
from json_logic import jsonLogic


class ConditionMatcher:
    """
    条件匹配器

    将简洁的条件配置转换为 JsonLogic 格式并执行匹配。

    条件配置格式:
        [
            {"field": "字段名", "op": "操作符", "value": "值"},
            {"field": "字段名", "op": "操作符", "value": "值", "logic": "or"},
            ...
        ]

    支持的操作符:
        - eq: 等于
        - neq: 不等于
        - in: 包含在列表中
        - not_in: 不包含在列表中
        - include: 子串包含
        - exclude: 子串不包含
        - regex: 正则匹配
        - gt/gte/lt/lte: 数值比较
        - startswith: 前缀匹配
        - endswith: 后缀匹配

    逻辑连接:
        - 默认为 "and" 连接
        - 使用 "logic": "or" 来分割 OR 组
    """

    # 操作符映射表
    OP_MAP = {
        "eq": "==",
        "neq": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "in": "in",
        "not_in": "not_in",
        "include": "include",
        "exclude": "exclude",
        "regex": "regex",
        "startswith": "startswith",
        "endswith": "endswith",
    }

    def __init__(self, conditions: list[dict] | None = None):
        """
        初始化匹配器

        Args:
            conditions: 条件配置列表
        """
        self.conditions = conditions or []
        self._jsonlogic_rule = self._convert_to_jsonlogic(self.conditions)

    def _convert_to_jsonlogic(self, conditions: list[dict]) -> dict:
        """
        将简洁格式转换为 JsonLogic 格式

        Args:
            conditions: 简洁格式的条件列表

        Returns:
            JsonLogic 格式的规则
        """
        if not conditions:
            return {}

        # 按 logic 字段分组
        or_groups = []
        current_and_group = []

        for cond in conditions:
            logic = cond.get("logic", "and").lower()

            # 遇到 OR 时，保存当前 AND 组
            if logic == "or" and current_and_group:
                or_groups.append(current_and_group)
                current_and_group = []

            # 转换单个条件
            jl_cond = self._convert_condition(cond)
            if jl_cond:
                current_and_group.append(jl_cond)

        # 添加最后一个 AND 组
        if current_and_group:
            or_groups.append(current_and_group)

        # 构建最终规则
        if not or_groups:
            return {}

        if len(or_groups) == 1:
            # 只有一个 AND 组
            and_group = or_groups[0]
            if len(and_group) == 1:
                return and_group[0]
            return {"and": and_group}

        # 多个 OR 组
        formatted_groups = []
        for group in or_groups:
            if len(group) == 1:
                formatted_groups.append(group[0])
            else:
                formatted_groups.append({"and": group})

        return {"or": formatted_groups}

    def _convert_condition(self, cond: dict) -> dict | None:
        """
        转换单个条件为 JsonLogic 格式

        Args:
            cond: 单个条件配置

        Returns:
            JsonLogic 条件对象
        """
        field = cond.get("field")
        op = cond.get("op", "eq")
        value = cond.get("value")

        if not field:
            return None

        # 获取 JsonLogic 操作符
        jl_op = self.OP_MAP.get(op, op)

        # 处理特殊操作符
        if op in ("include", "exclude"):
            # 子串包含需要特殊处理
            return self._build_include_logic(field, value, op == "include")
        elif op == "regex":
            # 正则匹配需要特殊处理
            return self._build_regex_logic(field, value)
        elif op == "startswith":
            return self._build_startswith_logic(field, value)
        elif op == "endswith":
            return self._build_endswith_logic(field, value)
        elif op == "not_in":
            # not_in 需要转换为 !in
            return {"!": {"in": [{"var": field}, value]}}
        else:
            # 标准操作符
            return {jl_op: [{"var": field}, value]}

    def _build_include_logic(self, field: str, value: Any, is_include: bool) -> dict:
        """构建子串包含逻辑（使用自定义操作）"""
        # JsonLogic 原生不支持 include，需要通过扩展或转换
        # 这里使用简化方式，实际可能需要注册自定义操作
        logic = {"in": [value, {"var": field}]} if isinstance(value, str) else {"in": [value[0], {"var": field}]}
        return logic if is_include else {"!": logic}

    def _build_regex_logic(self, field: str, pattern: Any) -> dict:
        """构建正则匹配逻辑（需要注册自定义操作）"""
        # JsonLogic 需要通过扩展支持正则
        # 这里返回一个标记，实际执行时需要处理
        return {"regex": [{"var": field}, pattern]}

    def _build_startswith_logic(self, field: str, prefix: Any) -> dict:
        """构建前缀匹配逻辑"""
        return {"startswith": [{"var": field}, prefix]}

    def _build_endswith_logic(self, field: str, suffix: Any) -> dict:
        """构建后缀匹配逻辑"""
        return {"endswith": [{"var": field}, suffix]}

    def match(self, data: dict) -> bool:
        """
        判断数据是否匹配条件

        Args:
            data: 待匹配的数据字典

        Returns:
            是否匹配
        """
        if not self._jsonlogic_rule:
            return True

        try:
            # 注册自定义操作
            self._register_custom_operations()
            return bool(jsonLogic(self._jsonlogic_rule, data))
        except Exception:
            return False

    def filter(self, items: list[dict]) -> list[dict]:
        """
        过滤列表，返回匹配的项

        Args:
            items: 数据列表

        Returns:
            匹配的数据列表
        """
        return [item for item in items if self.match(item)]

    def first(self, items: list[dict]) -> dict | None:
        """
        返回第一个匹配的项

        Args:
            items: 数据列表

        Returns:
            第一个匹配的项，如果没有则返回 None
        """
        for item in items:
            if self.match(item):
                return item
        return None

    def _register_custom_operations(self):
        """注册自定义操作到 JsonLogic"""
        import re

        from json_logic import add_operation

        # 注册 regex 操作
        def regex_op(a, b):
            if not a or not b:
                return False
            try:
                return bool(re.search(b, str(a)))
            except Exception:
                return False

        # 注册 startswith 操作
        def startswith_op(a, b):
            if not a:
                return False
            return str(a).startswith(str(b))

        # 注册 endswith 操作
        def endswith_op(a, b):
            if not a:
                return False
            return str(a).endswith(str(b))

        # 使用 add_operation 注册自定义操作
        add_operation("regex", regex_op)
        add_operation("startswith", startswith_op)
        add_operation("endswith", endswith_op)

    def get_jsonlogic_rule(self) -> dict:
        """
        获取转换后的 JsonLogic 规则（用于调试）

        Returns:
            JsonLogic 格式的规则
        """
        return self._jsonlogic_rule


# ============== 便捷函数 ==============


def match(data: dict, conditions: list[dict]) -> bool:
    """
    快速匹配单条数据

    Args:
        data: 待匹配的数据
        conditions: 条件配置列表

    Returns:
        是否匹配

    Example:
        >>> match({"ip": "10.0.0.1"}, [{"field": "ip", "op": "eq", "value": "10.0.0.1"}])
        True
    """
    return ConditionMatcher(conditions).match(data)


def filter_items(items: list[dict], conditions: list[dict]) -> list[dict]:
    """
    根据条件过滤数据列表

    Args:
        items: 数据列表
        conditions: 条件配置列表

    Returns:
        匹配的数据列表

    Example:
        >>> items = [{"level": "error"}, {"level": "info"}]
        >>> filter_items(items, [{"field": "level", "op": "eq", "value": "error"}])
        [{"level": "error"}]
    """
    return ConditionMatcher(conditions).filter(items)
