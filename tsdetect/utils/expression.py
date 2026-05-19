"""
TsDetect 工具模块 - 表达式处理

提供表达式构建和安全执行功能。
"""

import ast
import logging
from typing import Any

logger = logging.getLogger(__name__)


# 允许的内置函数
ALLOWED_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "round",
    "str",
    "sum",
    "True",
    "False",
    "None",
}

# 允许的操作符
ALLOWED_OPS = {
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.FloorDiv,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.UAdd,
    ast.USub,
}


class ExpressionValidator(ast.NodeVisitor):
    """
    表达式安全验证器

    检查表达式是否包含不安全的操作。
    """

    def __init__(self, allowed_names: set[str] | None = None):
        """
        初始化验证器

        Args:
            allowed_names: 允许的变量名集合
        """
        self.allowed_names = allowed_names or set()
        self.errors = []

    def validate(self, expr: str) -> bool:
        """
        验证表达式

        Args:
            expr: 表达式字符串

        Returns:
            是否安全
        """
        try:
            tree = ast.parse(expr, mode="eval")
            self.visit(tree)
            return len(self.errors) == 0
        except SyntaxError as e:
            self.errors.append(f"Syntax error: {e}")
            return False

    def visit_Name(self, node):  # noqa: N802
        """检查变量名"""
        name = node.id
        if name not in self.allowed_names and name not in ALLOWED_BUILTINS:
            self.errors.append(f"Undefined variable: {name}")
        self.generic_visit(node)

    def visit_Call(self, node):  # noqa: N802
        """检查函数调用"""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name not in self.allowed_names and func_name not in ALLOWED_BUILTINS:
                self.errors.append(f"Undefined function: {func_name}")
        elif isinstance(node.func, ast.Attribute):
            # 允许属性访问的方法调用
            pass
        else:
            self.errors.append("Invalid function call")
        self.generic_visit(node)

    def visit_Import(self, node):  # noqa: N802
        """禁止 import"""
        self.errors.append("Import statements are not allowed")

    def visit_ImportFrom(self, node):  # noqa: N802
        """禁止 from import"""
        self.errors.append("Import statements are not allowed")

    def visit_Attribute(self, node):  # noqa: N802
        """检查属性访问"""
        # 禁止访问私有属性
        if node.attr.startswith("_"):
            self.errors.append(f"Access to private attribute is not allowed: {node.attr}")
        self.generic_visit(node)


def safe_eval(expr: str, context: dict[str, Any], validate: bool = True) -> Any:
    """
    安全执行表达式

    Args:
        expr: 表达式字符串
        context: 执行上下文
        validate: 是否验证表达式安全性

    Returns:
        执行结果

    Raises:
        ValueError: 表达式不安全或执行失败
    """
    if validate:
        validator = ExpressionValidator(allowed_names=set(context.keys()))
        if not validator.validate(expr):
            raise ValueError(f"Unsafe expression: {'; '.join(validator.errors)}")

    try:
        # 编译并执行
        code = compile(expr, "<string>", "eval")
        return eval(code, {"__builtins__": {}}, context)
    except Exception as e:
        raise ValueError(f"Expression evaluation failed: {e}") from None


class ExpressionBuilder:
    """
    表达式构建器

    提供链式 API 构建检测表达式。
    """

    def __init__(self):
        """初始化表达式构建器"""
        self._parts = []
        self._logic_op = "and"

    def value(self, var: str = "value") -> "ExpressionBuilder":
        """添加值变量"""
        self._parts.append(var)
        return self

    def gt(self, threshold: float) -> "ExpressionBuilder":
        """大于比较"""
        self._parts.append(f"> {threshold}")
        return self

    def gte(self, threshold: float) -> "ExpressionBuilder":
        """大于等于比较"""
        self._parts.append(f">= {threshold}")
        return self

    def lt(self, threshold: float) -> "ExpressionBuilder":
        """小于比较"""
        self._parts.append(f"< {threshold}")
        return self

    def lte(self, threshold: float) -> "ExpressionBuilder":
        """小于等于比较"""
        self._parts.append(f"<= {threshold}")
        return self

    def eq(self, threshold: float) -> "ExpressionBuilder":
        """等于比较"""
        self._parts.append(f"== {threshold}")
        return self

    def neq(self, threshold: float) -> "ExpressionBuilder":
        """不等于比较"""
        self._parts.append(f"!= {threshold}")
        return self

    def and_(self) -> "ExpressionBuilder":
        """AND 连接"""
        self._logic_op = "and"
        self._parts.append(" and ")
        return self

    def or_(self) -> "ExpressionBuilder":
        """OR 连接"""
        self._logic_op = "or"
        self._parts.append(" or ")
        return self

    def paren_open(self) -> "ExpressionBuilder":
        """左括号"""
        self._parts.append("(")
        return self

    def paren_close(self) -> "ExpressionBuilder":
        """右括号"""
        self._parts.append(")")
        return self

    def raw(self, expr: str) -> "ExpressionBuilder":
        """添加原始表达式"""
        self._parts.append(expr)
        return self

    def build(self) -> str:
        """
        构建表达式字符串

        Returns:
            表达式字符串
        """
        return "".join(str(p) for p in self._parts)

    def __str__(self) -> str:
        return self.build()


def build_threshold_expr(
    threshold: float, method: str = "gt", value_var: str = "value", with_unit_convert: bool = True
) -> str:
    """
    构建阈值表达式

    Args:
        threshold: 阈值
        method: 比较方法 (gt, gte, lt, lte, eq, neq)
        value_var: 值变量名
        with_unit_convert: 是否包含单位转换

    Returns:
        表达式字符串
    """
    method_symbols = {
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "eq": "==",
        "neq": "!=",
    }

    symbol = method_symbols.get(method, ">")

    if with_unit_convert:
        return f"unit_convert_min({value_var}, unit) {symbol} unit_convert_min({threshold}, unit, algorithm_unit)"
    else:
        return f"{value_var} {symbol} {threshold}"


def build_ratio_expr(
    ratio: float, direction: str = "ceil", value_var: str = "value", history_var: str = "history_value"
) -> str:
    """
    构建比例表达式（用于环比/同比）

    Args:
        ratio: 百分比阈值
        direction: 方向 ("ceil" 上升, "floor" 下降)
        value_var: 当前值变量名
        history_var: 历史值变量名

    Returns:
        表达式字符串
    """
    if direction == "ceil":
        # 上升检测
        return f"({value_var} or {history_var}) and ({value_var} >= {history_var} * (100 + {ratio}) * 0.01)"
    else:
        # 下降检测
        return f"({value_var} or {history_var}) and ({value_var} <= {history_var} * (100 - {ratio}) * 0.01)"
