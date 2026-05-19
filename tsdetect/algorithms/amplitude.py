"""
TsDetect 振幅检测算法

提供环比振幅和同比振幅检测功能。
"""

from collections.abc import Generator
from typing import Any

from tsdetect.core.algorithms import (
    ExpressionDetector,
    RangeRatioAlgorithm,
)
from tsdetect.core.exceptions import InvalidAlgorithmConfigError
from tsdetect.core.interfaces import IDataPoint


class RingRatioAmplitudeAlgorithm(RangeRatioAlgorithm):
    """
    环比振幅检测算法

    检测当前值与前一时刻值的差值振幅。

    配置示例：
        {
            "threshold": 100,   # 最小值阈值
            "ratio": 0.2,       # 振幅比例
            "shock": 10         # 振幅基数
        }

    检测逻辑：
        1. 当前值 >= threshold AND 历史值 >= threshold
        2. |当前值 - 历史值| >= 历史值 * ratio + shock
    """

    # 使用 AND 逻辑（两个条件都必须满足）
    expr_op: str = "and"

    # 描述模板
    desc_tpl: str = "amplitude exceeds threshold: |value - history_value| >= history_value * {ratio} + {shock}"

    # 默认聚合间隔（秒）
    default_agg_interval: int = 60

    def __init__(self, config: dict[str, Any] | None = None, agg_interval: int | None = None, **kwargs):
        """
        初始化环比振幅算法

        Args:
            config: 算法配置
            agg_interval: 聚合间隔（秒）
            **kwargs: 额外参数
        """
        self.agg_interval = agg_interval or self.default_agg_interval
        super().__init__(config=config, **kwargs)

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        threshold = config.get("threshold", 0)
        ratio = config.get("ratio", 0)
        shock = config.get("shock", 0)

        try:
            validated = {
                "threshold": float(threshold),
                "ratio": float(ratio),
                "shock": float(shock),
            }
        except (TypeError, ValueError) as e:
            raise InvalidAlgorithmConfigError(
                f"Invalid amplitude config: {e}", errors={"config": "Values must be numeric"}
            ) from None

        return validated

    def get_history_offsets(self, **kwargs) -> list[int]:
        """获取历史数据偏移量"""
        return [self.agg_interval]

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加配置参数到上下文"""
        context = super().extra_context(data_point)
        context.update(self.validated_config)
        return context

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成振幅检测器"""
        threshold = self.validated_config["threshold"]
        ratio = self.validated_config["ratio"]
        shock = self.validated_config["shock"]

        # 条件1：当前值和历史值都 >= threshold（需要先检查 history_value 存在）
        threshold_expr = (
            f"(history_value is not None) and "
            f"unit_convert_min(value, unit) >= unit_convert_min({threshold}, unit, algorithm_unit) and "
            f"unit_convert_min(history_value, unit) >= unit_convert_min({threshold}, unit, algorithm_unit)"
        )
        yield ExpressionDetector(
            expr=threshold_expr,
            desc_tpl="",
            unit=self.unit,
            unit_converter=self.unit_converter,
            template_engine=self.template_engine,
        )

        # 条件2：振幅检测（需要先检查 history_value 存在）
        amplitude_expr = (
            f"(history_value is not None) and "
            f"unit_convert_min(abs(history_value - value), unit) >= "
            f"unit_convert_min(history_value, unit) * {ratio} + unit_convert_min({shock}, unit, algorithm_unit)"
        )
        yield ExpressionDetector(
            expr=amplitude_expr,
            desc_tpl=self.desc_tpl,
            unit=self.unit,
            unit_converter=self.unit_converter,
            template_engine=self.template_engine,
        )


class YearRoundAmplitudeAlgorithm(RangeRatioAlgorithm):
    """
    同比振幅检测算法

    当前时刻与前一时刻的差值 vs 过去 N 天同一时刻的差值。

    配置示例：
        {
            "ratio": 0.2,       # 振幅比例
            "shock": 10,        # 振幅基数
            "days": 7,          # 对比天数
            "method": "avg"     # 取值方式 ("avg" 或 "max")
        }
    """

    # 使用 AND 逻辑
    expr_op: str = "and"

    # 描述模板
    desc_tpl: str = "year-round amplitude exceeds threshold: current amplitude >= history amplitude * {ratio} + {shock}"

    # 默认聚合间隔（秒）
    default_agg_interval: int = 60

    # 一天的秒数
    CONST_ONE_DAY: int = 86400

    def __init__(self, config: dict[str, Any] | None = None, agg_interval: int | None = None, **kwargs):
        """
        初始化同比振幅算法

        Args:
            config: 算法配置
            agg_interval: 聚合间隔（秒）
            **kwargs: 额外参数
        """
        self.agg_interval = agg_interval or self.default_agg_interval
        super().__init__(config=config, **kwargs)

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        ratio = config.get("ratio", 0)
        shock = config.get("shock", 0)
        days = config.get("days", 7)
        method = config.get("method", "avg")

        if method not in ("avg", "max"):
            raise InvalidAlgorithmConfigError(
                f"Invalid method '{method}'", errors={"method": "Must be 'avg' or 'max'"}
            ) from None

        try:
            validated = {
                "ratio": float(ratio),
                "shock": float(shock),
                "days": int(days),
                "method": method,
            }
        except (TypeError, ValueError) as e:
            raise InvalidAlgorithmConfigError(
                f"Invalid amplitude config: {e}", errors={"config": "Values must be numeric"}
            ) from None

        return validated

    def get_history_offsets(self, **kwargs) -> list[int]:
        """获取历史数据偏移量"""
        days = self.validated_config.get("days", 7)
        offsets = []

        # 当前时刻的前一个周期
        offsets.append(self.agg_interval)

        # 过去 N 天的同一时刻及其前一个周期
        for day in range(1, days + 1):
            day_offset = self.CONST_ONE_DAY * day
            offsets.append(day_offset)  # 当天同一时刻
            offsets.append(day_offset + self.agg_interval)  # 当天前一周期

        return offsets

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加历史数据和配置到上下文"""
        context = super().extra_context(data_point)

        days = self.validated_config.get("days", 7)
        method = self.validated_config.get("method", "avg")

        # 获取当前振幅
        prev_point = self.fetch_history_point(data_point, self.agg_interval)
        if prev_point:
            current_amplitude = abs(data_point.value - prev_point.value)
            context["current_amplitude"] = current_amplitude
            context["previous_point"] = prev_point
        else:
            context["current_amplitude"] = None
            context["previous_point"] = None

        # 获取历史振幅列表
        history_amplitudes = []
        for day in range(1, days + 1):
            day_offset = self.CONST_ONE_DAY * day
            day_point = self.fetch_history_point(data_point, day_offset)
            day_prev_point = self.fetch_history_point(data_point, day_offset + self.agg_interval)

            if day_point and day_prev_point:
                amplitude = abs(day_point.value - day_prev_point.value)
                history_amplitudes.append(amplitude)

        # 计算历史基准振幅
        if history_amplitudes:
            if method == "avg":
                context["history_amplitude"] = sum(history_amplitudes) / len(history_amplitudes)
            else:  # max
                context["history_amplitude"] = max(history_amplitudes)
        else:
            context["history_amplitude"] = None

        context.update(self.validated_config)
        return context

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成同比振幅检测器"""
        ratio = self.validated_config["ratio"]
        shock = self.validated_config["shock"]

        # 振幅检测表达式（需要先检查 current_amplitude 和 history_amplitude 存在）
        amplitude_expr = (
            f"(current_amplitude is not None and history_amplitude is not None) and "
            f"current_amplitude >= history_amplitude * {ratio} + {shock}"
        )
        yield ExpressionDetector(
            expr=amplitude_expr,
            desc_tpl=self.desc_tpl,
            unit=self.unit,
            unit_converter=self.unit_converter,
            template_engine=self.template_engine,
        )


def create_ring_ratio_amplitude(
    threshold: float = 0, ratio: float = 0, shock: float = 0, agg_interval: int = 60, **kwargs
) -> RingRatioAmplitudeAlgorithm:
    """
    快捷创建环比振幅算法

    Args:
        threshold: 最小值阈值
        ratio: 振幅比例
        shock: 振幅基数
        agg_interval: 聚合间隔（秒）
        **kwargs: 额外参数

    Returns:
        环比振幅算法实例
    """
    config = {
        "threshold": threshold,
        "ratio": ratio,
        "shock": shock,
    }
    return RingRatioAmplitudeAlgorithm(config=config, agg_interval=agg_interval, **kwargs)


def create_year_round_amplitude(
    ratio: float = 0, shock: float = 0, days: int = 7, method: str = "avg", agg_interval: int = 60, **kwargs
) -> YearRoundAmplitudeAlgorithm:
    """
    快捷创建同比振幅算法

    Args:
        ratio: 振幅比例
        shock: 振幅基数
        days: 对比天数
        method: 取值方式 ("avg" 或 "max")
        agg_interval: 聚合间隔（秒）
        **kwargs: 额外参数

    Returns:
        同比振幅算法实例
    """
    config = {
        "ratio": ratio,
        "shock": shock,
        "days": days,
        "method": method,
    }
    return YearRoundAmplitudeAlgorithm(config=config, agg_interval=agg_interval, **kwargs)
