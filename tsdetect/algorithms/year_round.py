"""
TsDetect 同比检测算法

提供简易同比和高级同比检测功能。
"""

from collections.abc import Generator
from typing import Any

from tsdetect.core.algorithms import (
    ExpressionDetector,
    RangeRatioAlgorithm,
)
from tsdetect.core.exceptions import InvalidAlgorithmConfigError
from tsdetect.core.interfaces import IDataPoint

# 常量定义
CONST_ONE_DAY = 86400  # 一天（秒）
CONST_ONE_WEEK = 604800  # 一周（秒）


class SimpleYearRoundAlgorithm(RangeRatioAlgorithm):
    """
    简易同比检测算法

    当前值与上周同一时刻进行对比。

    配置示例：
        {
            "floor": 20,    # 下降超过 20% 告警
            "ceil": 20,     # 上升超过 20% 告警
        }

    检测逻辑：
        - 下降：value <= history_value * (100 - floor) / 100
        - 上升：value >= history_value * (100 + ceil) / 100
    """

    # 下降告警模板
    floor_desc_tpl: str = (
        "decreased by more than {floor}% compared to same time last week (history: {floor_history_value})"
    )

    # 上升告警模板
    ceil_desc_tpl: str = (
        "increased by more than {ceil}% compared to same time last week (history: {ceil_history_value})"
    )

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        floor = config.get("floor")
        ceil = config.get("ceil")

        if floor is None and ceil is None:
            raise InvalidAlgorithmConfigError(
                "At least one of 'floor' or 'ceil' must be specified", errors={"floor/ceil": "At least one required"}
            )

        validated = {}

        if floor is not None:
            try:
                validated["floor"] = float(floor)
            except (TypeError, ValueError):
                raise InvalidAlgorithmConfigError(
                    "Invalid 'floor' value", errors={"floor": "Must be numeric"}
                ) from None

        if ceil is not None:
            try:
                validated["ceil"] = float(ceil)
            except (TypeError, ValueError):
                raise InvalidAlgorithmConfigError("Invalid 'ceil' value", errors={"ceil": "Must be numeric"}) from None

        return validated

    def get_history_offsets(self, **kwargs) -> list[int]:
        """获取历史数据偏移量（上周同一时刻）"""
        return [CONST_ONE_WEEK]

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成同比检测器"""
        floor = self.validated_config.get("floor")
        ceil = self.validated_config.get("ceil")

        # 下降检测
        if floor is not None:
            floor_expr = (
                f"(floor_history_value is not None) and (value <= floor_history_value * (100 - {floor}) * 0.01)"
            )
            yield ExpressionDetector(
                expr=floor_expr,
                desc_tpl=self.floor_desc_tpl,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
                config={"floor": floor},
            )

        # 上升检测
        if ceil is not None:
            ceil_expr = f"(ceil_history_value is not None) and (value >= ceil_history_value * (100 + {ceil}) * 0.01)"
            yield ExpressionDetector(
                expr=ceil_expr,
                desc_tpl=self.ceil_desc_tpl,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
                config={"ceil": ceil},
            )


class AdvancedYearRoundAlgorithm(RangeRatioAlgorithm):
    """
    高级同比检测算法

    对比过去 N 天同一时刻的平均值或瞬时值。

    配置示例：
        {
            "floor": 20,
            "ceil": 20,
            "floor_interval": 7,    # 对比前 7 天
            "ceil_interval": 7,
            "fetch_type": "avg"     # "avg" 或 "last"
        }
    """

    # 下降告警模板
    floor_desc_tpl: str = "decreased by more than {floor}% compared to {fetch_desc} of same time in last {floor_interval} days (history: {floor_history_value})"

    # 上升告警模板
    ceil_desc_tpl: str = "increased by more than {ceil}% compared to {fetch_desc} of same time in last {ceil_interval} days (history: {ceil_history_value})"

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        floor = config.get("floor")
        ceil = config.get("ceil")
        floor_interval = config.get("floor_interval", 7)
        ceil_interval = config.get("ceil_interval", 7)
        fetch_type = config.get("fetch_type", "avg")

        if floor is None and ceil is None:
            raise InvalidAlgorithmConfigError(
                "At least one of 'floor' or 'ceil' must be specified", errors={"floor/ceil": "At least one required"}
            )

        if fetch_type not in ("avg", "last"):
            raise InvalidAlgorithmConfigError(
                f"Invalid fetch_type '{fetch_type}'", errors={"fetch_type": "Must be 'avg' or 'last'"}
            )

        validated = {
            "fetch_type": fetch_type,
        }

        if floor is not None:
            try:
                validated["floor"] = float(floor)
                validated["floor_interval"] = int(floor_interval)
            except (TypeError, ValueError) as e:
                raise InvalidAlgorithmConfigError(
                    f"Invalid floor config: {e}", errors={"floor": "Must be numeric"}
                ) from None

        if ceil is not None:
            try:
                validated["ceil"] = float(ceil)
                validated["ceil_interval"] = int(ceil_interval)
            except (TypeError, ValueError) as e:
                raise InvalidAlgorithmConfigError(
                    f"Invalid ceil config: {e}", errors={"ceil": "Must be numeric"}
                ) from None

        return validated

    def get_history_offsets(self, **kwargs) -> list[int]:
        """获取历史数据偏移量"""
        floor_interval = self.validated_config.get("floor_interval", 7)
        ceil_interval = self.validated_config.get("ceil_interval", 7)
        max_interval = max(floor_interval, ceil_interval)

        # 返回过去 N 天同一时刻的偏移量
        return [CONST_ONE_DAY * i for i in range(1, max_interval + 1)]

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加历史数据到上下文"""
        context = super().extra_context(data_point)

        fetch_type = self.validated_config.get("fetch_type", "avg")
        floor_interval = self.validated_config.get("floor_interval", 7)
        ceil_interval = self.validated_config.get("ceil_interval", 7)

        # 获取历史数据
        offsets = self.get_history_offsets()
        history_values = []

        for offset in offsets:
            hp = self.fetch_history_point(data_point, offset)
            if hp:
                history_values.append(hp.value)

        # 计算历史基准值
        if history_values:
            if fetch_type == "avg":
                # 下降检测使用前 floor_interval 天的平均值
                floor_values = history_values[:floor_interval]
                ceil_values = history_values[:ceil_interval]

                context["floor_history_value"] = sum(floor_values) / len(floor_values) if floor_values else None
                context["ceil_history_value"] = sum(ceil_values) / len(ceil_values) if ceil_values else None
            else:  # last
                # 使用最近一天的值
                context["floor_history_value"] = history_values[0] if history_values else None
                context["ceil_history_value"] = history_values[0] if history_values else None

        context["fetch_type"] = fetch_type
        context["floor_interval"] = floor_interval
        context["ceil_interval"] = ceil_interval
        context["fetch_desc"] = "average" if fetch_type == "avg" else "instant value"

        return context

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成高级同比检测器"""
        floor = self.validated_config.get("floor")
        ceil = self.validated_config.get("ceil")

        # 下降检测
        if floor is not None:
            floor_expr = (
                "(value is not None and floor_history_value is not None) and "
                f"(value <= floor_history_value * (100 - {floor}) * 0.01)"
            )
            yield ExpressionDetector(
                expr=floor_expr,
                desc_tpl=self.floor_desc_tpl,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
                config={"floor": floor},
            )

        # 上升检测
        if ceil is not None:
            ceil_expr = (
                "(value is not None and ceil_history_value is not None) and "
                f"(value >= ceil_history_value * (100 + {ceil}) * 0.01)"
            )
            yield ExpressionDetector(
                expr=ceil_expr,
                desc_tpl=self.ceil_desc_tpl,
                unit=self.unit,
                unit_converter=self.unit_converter,
                template_engine=self.template_engine,
                config={"ceil": ceil},
            )


def create_simple_year_round(
    floor: float | None = None, ceil: float | None = None, **kwargs
) -> SimpleYearRoundAlgorithm:
    """
    快捷创建简易同比算法

    Args:
        floor: 下降百分比阈值
        ceil: 上升百分比阈值
        **kwargs: 额外参数

    Returns:
        简易同比算法实例
    """
    config = {}
    if floor is not None:
        config["floor"] = floor
    if ceil is not None:
        config["ceil"] = ceil

    return SimpleYearRoundAlgorithm(config=config, **kwargs)


def create_advanced_year_round(
    floor: float | None = None,
    ceil: float | None = None,
    floor_interval: int = 7,
    ceil_interval: int = 7,
    fetch_type: str = "avg",
    **kwargs,
) -> AdvancedYearRoundAlgorithm:
    """
    快捷创建高级同比算法

    Args:
        floor: 下降百分比阈值
        ceil: 上升百分比阈值
        floor_interval: 下降对比天数
        ceil_interval: 上升对比天数
        fetch_type: 取值方式 ("avg" 或 "last")
        **kwargs: 额外参数

    Returns:
        高级同比算法实例
    """
    config = {
        "floor_interval": floor_interval,
        "ceil_interval": ceil_interval,
        "fetch_type": fetch_type,
    }
    if floor is not None:
        config["floor"] = floor
    if ceil is not None:
        config["ceil"] = ceil

    return AdvancedYearRoundAlgorithm(config=config, **kwargs)
