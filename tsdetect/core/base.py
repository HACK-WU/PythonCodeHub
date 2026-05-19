"""
TsDetect 数据点基类

定义了数据点和异常数据点的基类实现。
"""

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tsdetect.core.exceptions import InvalidDataPointError
from tsdetect.core.interfaces import IDataPoint

if TYPE_CHECKING:
    from tsdetect.core.algorithms import BaseAlgorithm


class BaseDataPoint(IDataPoint):
    """
    数据点基类

    提供数据点的基本实现，支持动态属性访问。
    """

    # 检测必需的属性列表
    context_fields: list[str] = ["value", "timestamp", "unit"]

    def __init__(self, data: dict[str, Any], **kwargs):
        """
        初始化数据点

        Args:
            data: 数据字典，必须包含 value, timestamp 等字段
            **kwargs: 额外属性
        """
        self._raw_data = data
        self._extra = kwargs

        # 动态设置属性
        for key, val in data.items():
            if not key.startswith("_"):
                setattr(self, key, val)

        # 设置额外属性
        for key, val in kwargs.items():
            if not key.startswith("_"):
                setattr(self, key, val)

        # 验证必需字段
        self._validate()

    def _validate(self):
        """验证数据点必需字段"""
        for field in self.context_fields:
            if field in ("unit",):  # unit 可选
                continue
            # 检查 _raw_data 中是否有该字段，且值不为 None
            val = self._raw_data.get(field)
            if val is None:
                raise InvalidDataPointError(f"DataPoint missing required field: {field}", field=field)

    @property
    def value(self) -> float:
        """获取数据点值"""
        return float(getattr(self, "_value", 0) or self._raw_data.get("value", 0))

    @value.setter
    def value(self, val):
        self._value = val

    @property
    def timestamp(self) -> int:
        """获取时间戳"""
        # 支持 timestamp 和 time 两种字段名
        ts = getattr(self, "_timestamp", None)
        if ts is None:
            ts = self._raw_data.get("timestamp") or self._raw_data.get("time")
        return int(ts) if ts else 0

    @timestamp.setter
    def timestamp(self, val):
        self._timestamp = val

    @property
    def time(self) -> int:
        """时间戳别名"""
        return self.timestamp

    @time.setter
    def time(self, val):
        self._timestamp = val

    @property
    def unit(self) -> str:
        """获取单位"""
        return getattr(self, "_unit", "") or self._raw_data.get("unit", "")

    @unit.setter
    def unit(self, val):
        self._unit = val

    @property
    def dimensions(self) -> dict[str, Any]:
        """获取维度信息"""
        return getattr(self, "_dimensions", {}) or self._raw_data.get("dimensions", {})

    @dimensions.setter
    def dimensions(self, val):
        self._dimensions = val

    @property
    def values(self) -> dict[str, Any]:
        """获取所有指标值"""
        return getattr(self, "_values", {}) or self._raw_data.get("values", {})

    @values.setter
    def values(self, val):
        self._values = val

    @property
    def record_id(self) -> str:
        """
        获取记录唯一标识

        格式：{dimensions_md5}.{timestamp}
        """
        # 优先使用预设的 record_id
        preset_id = self._raw_data.get("record_id")
        if preset_id:
            return preset_id

        # 生成 record_id
        dims_str = json.dumps(self.dimensions, sort_keys=True)
        dims_hash = hashlib.md5(dims_str.encode()).hexdigest()
        return f"{dims_hash}.{self.timestamp}"

    def as_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return dict(self._raw_data)

    def get(self, key: str, default: Any = None) -> Any:
        """获取属性值"""
        return getattr(self, key, default)

    def __str__(self) -> str:
        return f"{self.record_id}:{self.value}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} record_id={self.record_id} value={self.value}>"


class SimpleDataPoint(BaseDataPoint):
    """
    简单数据点实现

    适用于独立使用场景，无需额外依赖。
    """

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        value: float | None = None,
        timestamp: int | None = None,
        unit: str = "",
        dimensions: dict[str, Any] | None = None,
        **kwargs,
    ):
        """
        初始化简单数据点

        支持两种初始化方式：
        1. 传入 data 字典
        2. 传入独立参数

        Args:
            data: 数据字典
            value: 数据值
            timestamp: 时间戳
            unit: 单位
            dimensions: 维度信息
            **kwargs: 额外属性
        """
        if data is None:
            data = {}

        # 合并参数到 data
        if value is not None:
            data["value"] = value
        if timestamp is not None:
            data["timestamp"] = timestamp
        if unit:
            data["unit"] = unit
        if dimensions is not None:
            data["dimensions"] = dimensions

        super().__init__(data, **kwargs)


class BaseAnomalyPoint:
    """
    异常数据点基类

    包含检测到的异常信息。
    """

    def __init__(
        self,
        data_point: IDataPoint,
        detector: "BaseAlgorithm",
        anomaly_message: str = "",
        anomaly_id: str = "",
        context: dict[str, Any] | None = None,
    ):
        """
        初始化异常数据点

        Args:
            data_point: 原始数据点
            detector: 检测到异常的算法对象
            anomaly_message: 异常描述信息
            anomaly_id: 异常唯一标识
            context: 检测上下文
        """
        self.data_point = data_point
        self.detector = detector
        self.anomaly_message = anomaly_message
        self.anomaly_id = anomaly_id or self._generate_anomaly_id()
        self.anomaly_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.context = context or {}
        self.child_detectors: list[BaseAlgorithm] = []
        self.strategy_snapshot_key = ""

    def _generate_anomaly_id(self) -> str:
        """
        生成异常唯一标识

        格式：{record_id}.{detector_name}.{timestamp}
        """
        detector_name = getattr(self.detector, "__class__", type(self.detector)).__name__
        return f"{self.data_point.record_id}.{detector_name}"

    @property
    def value(self) -> float:
        """获取数据点值"""
        return self.data_point.value

    @property
    def timestamp(self) -> int:
        """获取时间戳"""
        return self.data_point.timestamp

    @property
    def dimensions(self) -> dict[str, Any]:
        """获取维度信息"""
        return self.data_point.dimensions

    @property
    def is_anomaly(self) -> bool:
        """是否为异常"""
        return True

    def add_child_detector(self, detector: "BaseAlgorithm"):
        """添加子检测器"""
        self.child_detectors.append(detector)

    def as_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "data": self.data_point.as_dict(),
            "anomaly": {
                "anomaly_id": self.anomaly_id,
                "anomaly_message": self.anomaly_message,
                "anomaly_time": self.anomaly_time,
            },
            "detector": type(self.detector).__name__,
            "context": self.context,
        }

    def __str__(self) -> str:
        return f"Anomaly({self.data_point.record_id}): {self.anomaly_message}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.anomaly_id}>"
