"""
TsDetect 阈值检测算法

提供静态阈值检测功能。
"""

import operator
from collections.abc import Generator
from typing import Any

from tsdetect.core.algorithms import (
    BaseAlgorithmCollection,
    ExpressionDetector,
)
from tsdetect.core.exceptions import InvalidAlgorithmConfigError
from tsdetect.core.interfaces import IDataPoint

# 比较方法映射
THRESHOLD_METHODS = {
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "eq": "==",
    "neq": "!=",
}

# 操作符映射
OPERATORS = {
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
    "eq": operator.eq,
    "neq": operator.ne,
}


class AndThresholdAlgorithm(BaseAlgorithmCollection):
    """
    AND 阈值检测算法

    多个阈值条件必须同时满足才触发异常。

    配置示例：
        {
            "thresholds": [
                {"method": "gte", "threshold": 90},
                {"method": "lte", "threshold": 100}
            ]
        }
    """

    # 使用 AND 逻辑
    expr_op: str = "and"

    # 描述模板
    desc_tpl: str = "value {method} {threshold}"

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        thresholds = config.get("thresholds", [])

        if not thresholds:
            raise InvalidAlgorithmConfigError(
                "Threshold config must have at least one threshold", errors={"thresholds": "Required field"}
            )

        validated = []
        for idx, item in enumerate(thresholds):
            if not isinstance(item, dict):
                raise InvalidAlgorithmConfigError(
                    f"Invalid threshold item at index {idx}", errors={f"thresholds[{idx}]": "Must be dict"}
                )

            method = item.get("method")
            threshold = item.get("threshold")

            if method not in THRESHOLD_METHODS:
                raise InvalidAlgorithmConfigError(
                    f"Invalid method '{method}' at index {idx}",
                    errors={f"thresholds[{idx}].method": f"Must be one of {list(THRESHOLD_METHODS.keys())}"},
                )

            if threshold is None:
                raise InvalidAlgorithmConfigError(
                    f"Missing threshold at index {idx}", errors={f"thresholds[{idx}].threshold": "Required field"}
                )

            try:
                threshold = float(threshold)
            except (TypeError, ValueError):
                raise InvalidAlgorithmConfigError(
                    f"Invalid threshold value at index {idx}",
                    errors={f"thresholds[{idx}].threshold": "Must be numeric"},
                ) from None

            validated.append(
                {
                    "method": method,
                    "threshold": threshold,
                }
            )

        return {"thresholds": validated}

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成阈值检测器"""
        thresholds = self.validated_config.get("thresholds", [])

        for item in thresholds:
            method = item["method"]
            threshold = item["threshold"]
            method_symbol = THRESHOLD_METHODS[method]

            # 生成表达式
            expr = f"unit_convert_min(value, unit) {method_symbol} unit_convert_min({threshold}, unit, algorithm_unit)"

            # 生成描述模板
            desc_tpl = f"value {method_symbol} {threshold}"

            yield ExpressionDetector(
                expr=expr,
                desc_tpl=desc_tpl,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
                config=item,
            )

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加阈值到上下文"""
        context = super().extra_context(data_point)

        thresholds = self.validated_config.get("thresholds", [])
        if thresholds:
            context["threshold"] = thresholds[0].get("threshold")
            context["method"] = thresholds[0].get("method")

        return context


class ThresholdAlgorithm(BaseAlgorithmCollection):
    """
    阈值检测算法

    支持多组 AND 条件，组间使用 OR 逻辑。

    配置示例：
        [
            [{"method": "gte", "threshold": 90}, {"method": "lte", "threshold": 100}],  # 组1: 90 <= value <= 100
            [{"method": "gte", "threshold": 200}]  # 组2: value >= 200
        ]

    任一组条件满足则触发异常。
    """

    # 使用 OR 逻辑（组间）
    expr_op: str = "or"

    def _validate_config(self, config: dict[str, Any] | list) -> dict[str, Any]:
        """验证配置"""
        # 配置可以是列表（多组）或字典（单组）
        if isinstance(config, dict):
            thresholds = config.get("thresholds", [])
        elif isinstance(config, list):
            thresholds = config
        else:
            raise InvalidAlgorithmConfigError(
                "Invalid config format", errors={"config": "Must be list or dict"}
            ) from None

        if not thresholds:
            raise InvalidAlgorithmConfigError(
                "Threshold config must have at least one group", errors={"thresholds": "Required field"}
            )

        # 确保是嵌套列表格式
        if thresholds and not isinstance(thresholds[0], list):
            thresholds = [thresholds]

        validated_groups = []
        for group_idx, group in enumerate(thresholds):
            if not isinstance(group, list):
                raise InvalidAlgorithmConfigError(
                    f"Invalid threshold group at index {group_idx}", errors={f"thresholds[{group_idx}]": "Must be list"}
                )

            validated_items = []
            for idx, item in enumerate(group):
                if not isinstance(item, dict):
                    raise InvalidAlgorithmConfigError(
                        f"Invalid threshold item at [{group_idx}][{idx}]",
                        errors={f"thresholds[{group_idx}][{idx}]": "Must be dict"},
                    )

                method = item.get("method")
                threshold = item.get("threshold")

                if method not in THRESHOLD_METHODS:
                    raise InvalidAlgorithmConfigError(
                        f"Invalid method '{method}' at [{group_idx}][{idx}]",
                        errors={
                            f"thresholds[{group_idx}][{idx}].method": f"Must be one of {list(THRESHOLD_METHODS.keys())}"
                        },
                    )

                if threshold is None:
                    raise InvalidAlgorithmConfigError(
                        f"Missing threshold at [{group_idx}][{idx}]",
                        errors={f"thresholds[{group_idx}][{idx}].threshold": "Required field"},
                    )

                try:
                    threshold = float(threshold)
                except (TypeError, ValueError):
                    raise InvalidAlgorithmConfigError(
                        f"Invalid threshold value at [{group_idx}][{idx}]",
                        errors={f"thresholds[{group_idx}][{idx}].threshold": "Must be numeric"},
                    ) from None

                validated_items.append(
                    {
                        "method": method,
                        "threshold": threshold,
                    }
                )

            if validated_items:
                validated_groups.append(validated_items)

        return {"thresholds": validated_groups}

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成阈值检测器组"""
        threshold_groups = self.validated_config.get("thresholds", [])

        for group in threshold_groups:
            # 为每组创建一个 AND 检测器
            and_detector = _AndGroupDetector(
                thresholds=group,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
            )
            yield and_detector


class _AndGroupDetector(ExpressionDetector):
    """
    AND 条件组检测器

    内部使用，用于处理单个 AND 条件组。
    """

    def __init__(self, thresholds: list[dict[str, Any]], **kwargs):
        self.thresholds = thresholds

        # 生成组合表达式
        conditions = []
        descriptions = []

        for item in thresholds:
            method = item["method"]
            threshold = item["threshold"]
            method_symbol = THRESHOLD_METHODS[method]

            conditions.append(
                f"unit_convert_min(value, unit) {method_symbol} unit_convert_min({threshold}, unit, algorithm_unit)"
            )
            descriptions.append(f"value {method_symbol} {threshold}")

        expr = " and ".join(conditions) if conditions else "None"
        desc_tpl = " AND ".join(descriptions) if descriptions else ""

        super().__init__(expr=expr, desc_tpl=desc_tpl, **kwargs)


def create_threshold_algorithm(threshold: float, method: str = "gt", unit: str = "", **kwargs) -> ThresholdAlgorithm:
    """
    快捷创建阈值算法

    Args:
        threshold: 阈值
        method: 比较方法 (gt, gte, lt, lte, eq, neq)
        unit: 单位
        **kwargs: 额外参数

    Returns:
        阈值算法实例
    """
    config = [[{"method": method, "threshold": threshold}]]
    return ThresholdAlgorithm(config=config, unit=unit, **kwargs)
