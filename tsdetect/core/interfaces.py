"""
TsDetect 核心接口定义

定义了数据点、历史数据获取器、单位转换器和模板引擎的抽象接口。
"""

from abc import ABC, abstractmethod
from typing import Any


class IDataPoint(ABC):
    """
    数据点抽象接口

    定义了检测算法所需的数据点最小接口。
    任何实现此接口的类都可以被检测算法处理。
    """

    @property
    @abstractmethod
    def value(self) -> float:
        """
        获取数据点的值

        Returns:
            数据点的数值
        """
        pass

    @property
    @abstractmethod
    def timestamp(self) -> int:
        """
        获取时间戳

        Returns:
            Unix 时间戳（秒）
        """
        pass

    @property
    @abstractmethod
    def unit(self) -> str:
        """
        获取单位

        Returns:
            单位字符串，可为空
        """
        pass

    @property
    @abstractmethod
    def dimensions(self) -> dict[str, Any]:
        """
        获取维度信息

        Returns:
            维度字典，如 {"ip": "127.0.0.1", "bk_cloud_id": 0}
        """
        pass

    @property
    @abstractmethod
    def record_id(self) -> str:
        """
        获取记录唯一标识

        Returns:
            记录ID，格式通常为 "{dimensions_md5}.{timestamp}"
        """
        pass

    @abstractmethod
    def as_dict(self) -> dict[str, Any]:
        """
        转换为字典

        Returns:
            数据点的字典表示
        """
        pass


class IHistoryFetcher(ABC):
    """
    历史数据获取器抽象接口

    定义了获取历史数据点的接口，用于同比/环比等需要历史数据的算法。
    """

    @abstractmethod
    def fetch(self, data_point: IDataPoint, offsets: list[int]) -> list[IDataPoint | None]:
        """
        获取历史数据点

        Args:
            data_point: 当前数据点
            offsets: 时间偏移量列表（秒），正数表示过去的时间点

        Returns:
            历史数据点列表，与 offsets 一一对应，不存在的点为 None
        """
        pass

    @abstractmethod
    def batch_fetch(self, data_points: list[IDataPoint], offsets: list[int]) -> dict[str, list[IDataPoint | None]]:
        """
        批量获取历史数据点

        Args:
            data_points: 当前数据点列表
            offsets: 时间偏移量列表

        Returns:
            字典，key 为 record_id，value 为历史数据点列表
        """
        pass


class IUnitConverter(ABC):
    """
    单位转换器抽象接口

    定义了单位转换的接口，支持值转换和自动单位选择。
    """

    @abstractmethod
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
        pass

    @abstractmethod
    def auto_convert(self, value: float, unit: str, decimal: int = 2) -> tuple[float, str]:
        """
        自动选择最佳单位进行转换

        Args:
            value: 原始值
            unit: 原始单位
            decimal: 小数位数

        Returns:
            (转换后的值, 单位后缀)
        """
        pass

    @abstractmethod
    def convert_to_min(self, value: float, unit: str, target_unit: str | None = None) -> float:
        """
        转换为最小单位（用于数值比较）

        Args:
            value: 原始值
            unit: 原始单位
            target_unit: 目标单位类型（可选）

        Returns:
            转换后的值
        """
        pass


class ITemplateEngine(ABC):
    """
    模板引擎抽象接口

    定义了消息模板渲染的接口，支持多种模板后端。
    """

    @abstractmethod
    def render(self, template: str, context: dict[str, Any]) -> str:
        """
        渲染模板

        Args:
            template: 模板字符串
            context: 上下文变量字典

        Returns:
            渲染后的字符串
        """
        pass

    @abstractmethod
    def compile(self, template: str) -> Any:
        """
        编译模板（可选优化）

        Args:
            template: 模板字符串

        Returns:
            编译后的模板对象
        """
        pass


class ISDKClient(ABC):
    """
    SDK 客户端抽象接口

    定义了与外部智能检测服务交互的接口。
    """

    @abstractmethod
    def predict(self, data: list[dict[str, Any]], dimensions: dict[str, Any], **params) -> list[dict[str, Any]]:
        """
        单点预测

        Args:
            data: 数据点列表
            dimensions: 维度信息
            **params: 额外参数

        Returns:
            预测结果列表
        """
        pass

    @abstractmethod
    def batch_predict(self, data_groups: list[dict[str, Any]], **params) -> list[dict[str, Any]]:
        """
        批量预测

        Args:
            data_groups: 数据组列表
            **params: 额外参数

        Returns:
            预测结果列表
        """
        pass


class IConfigValidator(ABC):
    """
    配置验证器抽象接口

    定义了算法配置验证的接口。
    """

    @abstractmethod
    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        """
            验证配置

            Args:
                config: 原始配置

            Returns:
                验证后的配置

            Raises:
        InvalidAlgorithmConfigError: 配置无效
        """
        pass
