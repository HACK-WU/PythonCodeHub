"""
TsDetect 单位转换系统

提供可插拔的单位转换功能。
"""

from abc import ABC

from tsdetect.core.interfaces import IUnitConverter


class BaseUnitConverter(IUnitConverter, ABC):
    """
    单位转换器基类

    提供单位转换的基础实现框架。
    """

    # 单位乘数映射
    UNIT_MULTIPLIERS: dict[str, float] = {}

    # 单位组映射（用于自动转换）
    UNIT_GROUPS: dict[str, list] = {}

    def convert(self, value: float, from_unit: str, to_unit: str | None = None) -> float:
        """
        单位转换

        Args:
            value: 原始值
            from_unit: 原始单位
            to_unit: 目标单位，None 表示转换为最小单位

        Returns:
            转换后的值
        """
        if not from_unit:
            return value

        from_multiplier = self.UNIT_MULTIPLIERS.get(from_unit, 1.0)

        if to_unit is None:
            # 转换为最小单位（乘数为 1）
            return value * from_multiplier

        to_multiplier = self.UNIT_MULTIPLIERS.get(to_unit, 1.0)

        if to_multiplier == 0:
            return value

        return value * from_multiplier / to_multiplier

    def convert_to_min(self, value: float, unit: str, target_unit: str | None = None) -> float:
        """
        转换为最小单位

        Args:
            value: 原始值
            unit: 原始单位
            target_unit: 目标单位类型（可选）

        Returns:
            转换后的值
        """
        return self.convert(value, unit, None)


class NoOpUnitConverter(BaseUnitConverter):
    """
    无操作单位转换器

    直接返回原值，不做任何转换。
    用于不需要单位转换的场景。
    """

    def convert(self, value: float, from_unit: str, to_unit: str | None = None) -> float:
        """直接返回原值"""
        return value

    def auto_convert(self, value: float, unit: str, decimal: int = 2) -> tuple[float, str]:
        """直接返回原值和单位"""
        return round(value, decimal), unit

    def convert_to_min(self, value: float, unit: str, target_unit: str | None = None) -> float:
        """直接返回原值"""
        return value


class SimpleUnitConverter(BaseUnitConverter):
    """
    简单单位转换器

    支持常见的单位转换（字节、时间、百分比等）。
    """

    # 字节单位乘数
    BYTE_MULTIPLIERS = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "PB": 1024**5,
        # SI 前缀（十进制，1000 倍数）
        "kB": 1000,
        "MB_SI": 1000**2,
        "GB_SI": 1000**3,
    }

    # 时间单位乘数（转换为秒）
    TIME_MULTIPLIERS = {
        "ns": 1e-9,
        "us": 1e-6,
        "µs": 1e-6,
        "ms": 1e-3,
        "s": 1,
        "m": 60,
        "min": 60,
        "h": 3600,
        "d": 86400,
    }

    # 百分比单位
    PERCENT_MULTIPLIERS = {
        "%": 1,
        "percent": 1,
        "ratio": 100,  # 0-1 比例转换为百分比
    }

    # 带宽单位（转换为 bps）
    BANDWIDTH_MULTIPLIERS = {
        "bps": 1,
        "Kbps": 1000,
        "Mbps": 1000**2,
        "Gbps": 1000**3,
        "Bps": 8,
        "KBps": 8 * 1024,
        "MBps": 8 * 1024**2,
        "GBps": 8 * 1024**3,
    }

    # 合并所有单位乘数
    UNIT_MULTIPLIERS = {
        **BYTE_MULTIPLIERS,
        **TIME_MULTIPLIERS,
        **PERCENT_MULTIPLIERS,
        **BANDWIDTH_MULTIPLIERS,
    }

    # 单位组（用于自动转换时选择合适的单位）
    UNIT_GROUPS = {
        "bytes": ["B", "KB", "MB", "GB", "TB", "PB"],
        "time": ["ns", "µs", "ms", "s", "m", "h", "d"],
        "percent": ["%"],
        "bandwidth": ["bps", "Kbps", "Mbps", "Gbps"],
    }

    def __init__(self, default_decimal: int = 2):
        """
        初始化简单单位转换器

        Args:
            default_decimal: 默认小数位数
        """
        self.default_decimal = default_decimal

    def auto_convert(self, value: float, unit: str, decimal: int = None) -> tuple[float, str]:
        """
        自动选择最佳单位进行转换

        Args:
            value: 原始值
            unit: 原始单位
            decimal: 小数位数

        Returns:
            (转换后的值, 单位后缀)
        """
        if decimal is None:
            decimal = self.default_decimal

        if not unit:
            return round(value, decimal), ""

        # 查找单位所属的组
        unit_group = None
        for _group_name, units in self.UNIT_GROUPS.items():
            if unit in units:
                unit_group = units
                break

        if not unit_group:
            return round(value, decimal), unit

        # 先转换为最小单位
        min_value = self.convert(value, unit, None)

        # 找到最合适的单位
        best_unit = unit_group[0]
        best_value = min_value

        for target_unit in unit_group:
            multiplier = self.UNIT_MULTIPLIERS.get(target_unit, 1)
            converted = min_value / multiplier if multiplier else min_value

            # 选择使值在 1-1000 范围内的单位
            if 1 <= abs(converted) < 1000 or target_unit == unit_group[-1]:
                best_unit = target_unit
                best_value = converted
                break

        return round(best_value, decimal), best_unit

    def get_unit_suffix(self, unit: str) -> str:
        """
        获取单位后缀（用于显示）

        Args:
            unit: 单位

        Returns:
            单位后缀字符串
        """
        # 移除可能的前缀
        suffixes = {
            "B": "B",
            "KB": "KB",
            "MB": "MB",
            "GB": "GB",
            "TB": "TB",
            "s": "s",
            "ms": "ms",
            "µs": "µs",
            "%": "%",
        }
        return suffixes.get(unit, unit)


class MappedUnitConverter(BaseUnitConverter):
    """
    映射型单位转换器

    支持自定义单位映射，用于适配不同系统的单位定义。
    """

    def __init__(
        self,
        unit_multipliers: dict[str, float] | None = None,
        unit_groups: dict[str, list] | None = None,
        default_decimal: int = 2,
    ):
        """
        初始化映射型单位转换器

        Args:
            unit_multipliers: 单位乘数映射
            unit_groups: 单位组映射
            default_decimal: 默认小数位数
        """
        self.UNIT_MULTIPLIERS = unit_multipliers or {}
        self.UNIT_GROUPS = unit_groups or {}
        self.default_decimal = default_decimal

    def add_unit(self, unit: str, multiplier: float, group: str | None = None):
        """
        添加单位定义

        Args:
            unit: 单位名称
            multiplier: 乘数
            group: 所属组（可选）
        """
        self.UNIT_MULTIPLIERS[unit] = multiplier

        if group:
            if group not in self.UNIT_GROUPS:
                self.UNIT_GROUPS[group] = []
            if unit not in self.UNIT_GROUPS[group]:
                self.UNIT_GROUPS[group].append(unit)

    def auto_convert(self, value: float, unit: str, decimal: int = None) -> tuple[float, str]:
        """
        自动选择最佳单位进行转换
        """
        if decimal is None:
            decimal = self.default_decimal

        if not unit or unit not in self.UNIT_MULTIPLIERS:
            return round(value, decimal), unit

        # 查找单位所属的组
        unit_group = None
        for _group_name, units in self.UNIT_GROUPS.items():
            if unit in units:
                unit_group = units
                break

        if not unit_group:
            return round(value, decimal), unit

        # 先转换为最小单位
        min_value = self.convert(value, unit, None)

        # 找到最合适的单位
        best_unit = unit_group[0]
        best_value = min_value

        for target_unit in unit_group:
            multiplier = self.UNIT_MULTIPLIERS.get(target_unit, 1)
            converted = min_value / multiplier if multiplier else min_value

            if 1 <= abs(converted) < 1000 or target_unit == unit_group[-1]:
                best_unit = target_unit
                best_value = converted
                break

        return round(best_value, decimal), best_unit
