"""
TsDetect 算法基类

定义了检测算法的基类和集合类。
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any

from tsdetect.core.base import BaseAnomalyPoint
from tsdetect.core.exceptions import (
    ExpressionError,
)
from tsdetect.core.interfaces import (
    IDataPoint,
    IHistoryFetcher,
    ITemplateEngine,
    IUnitConverter,
)

logger = logging.getLogger(__name__)


class DetectContext(dict):
    """
    检测上下文

    支持属性访问的字典，用于表达式执行环境。
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"Context has no attribute '{name}'") from None

    def __setattr__(self, name: str, value: Any):
        self[name] = value


class BaseAlgorithm(ABC):
    """
    检测算法基类

    所有检测算法都应该继承此类。
    """

    # 异常描述模板
    desc_tpl: str = ""

    # 检测表达式
    expr: str = "None"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        unit: str = "",
        unit_converter: IUnitConverter | None = None,
        template_engine: ITemplateEngine | None = None,
        **kwargs,
    ):
        """
        初始化算法

        Args:
            config: 算法配置
            unit: 单位前缀
            unit_converter: 单位转换器
            template_engine: 模板引擎
            **kwargs: 额外参数
        """
        self.config = config or {}
        self.unit = unit
        self.unit_converter = unit_converter
        self.template_engine = template_engine
        self.extra_config = kwargs.get("extra_config", {})

        # 验证配置
        self.validated_config = self._validate_config(self.config)

        # 生成并编译表达式
        self.expr = self.gen_expr()
        if self.expr and self.expr != "None":
            try:
                self._byte_code = compile(self.expr, "<string>", "eval")
            except SyntaxError as e:
                raise ExpressionError(f"Failed to compile expression: {e}", expression=self.expr) from None
        else:
            self._byte_code = None

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        验证配置

        子类可以重写此方法实现配置验证。

        Args:
            config: 原始配置

        Returns:
            验证后的配置

        Raises:
            InvalidAlgorithmConfigError: 配置无效
        """
        return config

    @abstractmethod
    def gen_expr(self) -> str:
        """
        生成检测表达式

        子类必须实现此方法。

        Returns:
            检测表达式字符串
        """
        return "None"

    def get_context(self, data_point: IDataPoint) -> DetectContext:
        """
        构建检测上下文

        Args:
            data_point: 数据点

        Returns:
            检测上下文
        """
        context = DetectContext()

        # 基础属性
        context["data_point"] = data_point
        context["value"] = data_point.value
        context["timestamp"] = data_point.timestamp
        context["unit"] = data_point.unit
        context["dimensions"] = data_point.dimensions

        # 单位转换函数
        if self.unit_converter:
            context["unit_convert_min"] = self.unit_converter.convert_to_min
            context["unit_auto_convert"] = self.unit_converter.auto_convert
        else:
            # 默认的无操作转换
            context["unit_convert_min"] = lambda v, *args, **kwargs: v
            context["unit_auto_convert"] = lambda v, u, d=2: (v, u)

        # 算法单位
        context["algorithm_unit"] = self.unit

        # 添加额外上下文
        extra = self.extra_context(data_point)
        context.update(extra)

        return context

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """
        额外上下文

        子类可以重写此方法添加额外的上下文变量。

        Args:
            data_point: 数据点

        Returns:
            额外上下文字典
        """
        return {}

    def _detect(self, data_point: IDataPoint) -> bool:
        """
        执行检测

        Args:
            data_point: 数据点

        Returns:
            是否异常
        """
        if self._byte_code is None:
            return False

        context = self.get_context(data_point)

        try:
            result = eval(self._byte_code, {"__builtins__": {}}, context)
            return bool(result)
        except Exception as e:
            logger.warning(f"Expression evaluation failed: {e}, expr={self.expr}, record_id={data_point.record_id}")
            return False

    def detect(self, data_point: IDataPoint) -> list[BaseAnomalyPoint]:
        """
        检测数据点

        Args:
            data_point: 数据点

        Returns:
            异常数据点列表（空列表表示正常）
        """
        if not self._detect(data_point):
            return []

        # 生成异常点
        anomaly = self._create_anomaly_point(data_point)
        return [anomaly]

    def detect_records(self, data_points: list[IDataPoint], level: int = 1) -> list[BaseAnomalyPoint]:
        """
        批量检测

        Args:
            data_points: 数据点列表
            level: 告警级别

        Returns:
            异常数据点列表
        """
        anomalies = []
        for dp in data_points:
            result = self.detect(dp)
            for anomaly in result:
                anomaly.level = level
                anomalies.append(anomaly)
        return anomalies

    def _create_anomaly_point(self, data_point: IDataPoint) -> BaseAnomalyPoint:
        """
        创建异常数据点

        Args:
            data_point: 数据点

        Returns:
            异常数据点
        """
        message = self._format_message(data_point)
        context = self.get_context(data_point)

        return BaseAnomalyPoint(
            data_point=data_point,
            detector=self,
            anomaly_message=message,
            context=dict(context),
        )

    def _format_message(self, data_point: IDataPoint) -> str:
        """
        格式化异常消息

        Args:
            data_point: 数据点

        Returns:
            异常消息字符串
        """
        if not self.desc_tpl:
            return f"Anomaly detected: value={data_point.value}"

        context = self.get_context(data_point)

        # 使用模板引擎渲染
        if self.template_engine:
            try:
                return self.template_engine.render(self.desc_tpl, dict(context))
            except Exception as e:
                logger.warning(f"Template render failed: {e}")

        # 回退到简单的字符串格式化
        try:
            return self.desc_tpl.format(**context)
        except Exception:
            return self.desc_tpl


class ExpressionDetector(BaseAlgorithm):
    """
    表达式检测器

    支持自定义表达式的简单检测器。
    """

    def __init__(self, expr: str, desc_tpl: str = "", **kwargs):
        """
        初始化表达式检测器

        Args:
            expr: 检测表达式
            desc_tpl: 异常描述模板
            **kwargs: 额外参数
        """
        self._custom_expr = expr
        self.desc_tpl = desc_tpl
        super().__init__(**kwargs)

    def gen_expr(self) -> str:
        """返回自定义表达式"""
        return self._custom_expr


class BaseAlgorithmCollection(BaseAlgorithm):
    """
    算法集合基类

    支持多个检测表达式的组合。
    """

    # 表达式间的逻辑操作符："and" 或 "or"
    expr_op: str = "and"

    def __init__(self, config: dict[str, Any] | None = None, unit: str = "", **kwargs):
        """
        初始化算法集合

        Args:
            config: 算法配置
            unit: 单位前缀
            **kwargs: 额外参数
        """
        # 先设置 detectors 为空列表，避免在 super().__init__ 中访问
        self.detectors: list[ExpressionDetector] = []

        super().__init__(config=config, unit=unit, **kwargs)

        # 生成检测器列表
        self.detectors = list(self._gen_detectors())

    def gen_expr(self) -> str:
        """生成组合表达式"""
        # 返回占位符，实际检测由 detectors 完成
        return "None"

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """
        生成检测器

        子类应该重写此方法生成具体的检测器。

        Yields:
            检测器对象
        """
        # 默认生成一个空检测器
        yield ExpressionDetector(
            expr="None",
            desc_tpl=self.desc_tpl,
            unit=self.unit,
            unit_converter=self.unit_converter,
            template_engine=self.template_engine,
        )

    def detect(self, data_point: IDataPoint) -> list[BaseAnomalyPoint]:
        """
        检测数据点

        根据 expr_op 组合多个检测器的结果。

        Args:
            data_point: 数据点

        Returns:
            异常数据点列表
        """
        if not self.detectors:
            return []

        all_anomalies = []
        triggered_detectors = []

        for detector in self.detectors:
            anomalies = detector.detect(data_point)
            if anomalies:
                all_anomalies.extend(anomalies)
                triggered_detectors.append(detector)

        # 根据 expr_op 判断是否返回异常
        if self.expr_op == "and":
            # 所有检测器都必须触发
            if len(triggered_detectors) == len(self.detectors):
                return self._merge_anomalies(data_point, all_anomalies, triggered_detectors)
        else:  # "or"
            # 任一检测器触发即可
            if triggered_detectors:
                return self._merge_anomalies(data_point, all_anomalies, triggered_detectors)

        return []

    def _merge_anomalies(
        self, data_point: IDataPoint, anomalies: list[BaseAnomalyPoint], detectors: list[ExpressionDetector]
    ) -> list[BaseAnomalyPoint]:
        """
        合并异常结果

        Args:
            data_point: 数据点
            anomalies: 所有异常点
            detectors: 触发的检测器

        Returns:
            合并后的异常点列表
        """
        if not anomalies:
            return []

        # 创建主异常点
        main_anomaly = self._create_anomaly_point(data_point)

        # 添加子检测器
        for detector in detectors:
            main_anomaly.add_child_detector(detector)

        # 合并消息
        messages = [a.anomaly_message for a in anomalies if a.anomaly_message]
        if messages:
            main_anomaly.anomaly_message = "; ".join(messages)

        return [main_anomaly]


class RangeRatioAlgorithm(BaseAlgorithmCollection):
    """
    同比/环比算法基类

    需要历史数据支持的算法基类。
    """

    # 下降告警模板
    floor_desc_tpl: str = ""

    # 上升告警模板
    ceil_desc_tpl: str = ""

    # 使用 or 逻辑（下降或上升任一触发）
    expr_op: str = "or"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        unit: str = "",
        history_fetcher: IHistoryFetcher | None = None,
        **kwargs,
    ):
        """
        初始化同比/环比算法

        Args:
            config: 算法配置
            unit: 单位前缀
            history_fetcher: 历史数据获取器
            **kwargs: 额外参数
        """
        self.history_fetcher = history_fetcher
        self._history_cache: dict[str, list[IDataPoint | None]] = {}

        super().__init__(config=config, unit=unit, **kwargs)

    @abstractmethod
    def get_history_offsets(self, **kwargs) -> list[int]:
        """
        获取历史数据偏移量

        子类必须实现此方法。

        Returns:
            偏移量列表（秒）
        """
        pass

    def query_history_points(self, data_points: list[IDataPoint]):
        """
        批量查询历史数据

        Args:
            data_points: 数据点列表
        """
        if not self.history_fetcher:
            return

        offsets = self.get_history_offsets()

        # 使用批量接口获取历史数据
        history_data = self.history_fetcher.batch_fetch(data_points, offsets)
        self._history_cache.update(history_data)

    def fetch_history_point(self, data_point: IDataPoint, offset: int) -> IDataPoint | None:
        """
        获取单个历史数据点

        Args:
            data_point: 当前数据点
            offset: 时间偏移（秒）

        Returns:
            历史数据点，不存在返回 None
        """
        record_id = data_point.record_id

        # 先从缓存获取
        if record_id in self._history_cache:
            offsets = self.get_history_offsets()
            if offset in offsets:
                idx = offsets.index(offset)
                cached = self._history_cache[record_id]
                if idx < len(cached):
                    return cached[idx]

        # 缓存未命中，单独获取
        if self.history_fetcher:
            results = self.history_fetcher.fetch(data_point, [offset])
            return results[0] if results else None

        return None

    def history_point_fetcher(self, data_point: IDataPoint, **kwargs) -> IDataPoint | None:
        """
        获取默认历史数据点

        默认返回第一个偏移对应的历史数据。

        Args:
            data_point: 当前数据点
            **kwargs: 额外参数

        Returns:
            历史数据点
        """
        offsets = self.get_history_offsets(**kwargs)
        if offsets:
            return self.fetch_history_point(data_point, offsets[0])
        return None

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加历史数据到上下文"""
        context = super().extra_context(data_point)

        # 获取历史数据点
        history_point = self.history_point_fetcher(data_point)
        context["history_data_point"] = history_point

        if history_point:
            context["history_value"] = history_point.value
            context["floor_history_value"] = history_point.value
            context["ceil_history_value"] = history_point.value
        else:
            context["history_value"] = None
            context["floor_history_value"] = None
            context["ceil_history_value"] = None

        # 添加配置参数
        config = self.validated_config or self.config
        context["floor"] = config.get("floor", 0)
        context["ceil"] = config.get("ceil", 0)

        return context

    def detect_records(self, data_points: list[IDataPoint], level: int = 1) -> list[BaseAnomalyPoint]:
        """
        批量检测（带历史数据预加载）

        Args:
            data_points: 数据点列表
            level: 告警级别

        Returns:
            异常数据点列表
        """
        # 预加载历史数据
        self.query_history_points(data_points)

        # 执行检测
        return super().detect_records(data_points, level)
