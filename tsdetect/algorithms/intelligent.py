"""
TsDetect 智能检测算法接口

提供智能检测（SDK 调用）的抽象接口和基础实现。
"""

import copy
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any

from tsdetect.core.algorithms import (
    ExpressionDetector,
    RangeRatioAlgorithm,
)
from tsdetect.core.base import BaseAnomalyPoint
from tsdetect.core.exceptions import SDKError
from tsdetect.core.interfaces import IDataPoint, ISDKClient

logger = logging.getLogger(__name__)


class BaseIntelligentAlgorithm(RangeRatioAlgorithm, ABC):
    """
    智能检测算法基类

    提供 SDK 调用的抽象框架，具体的 SDK 实现由子类或适配器提供。
    """

    # 描述模板
    desc_tpl: str = "Intelligent detection triggered: anomaly_score={anomaly_score}"

    # 默认聚合间隔（秒）
    default_agg_interval: int = 60

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        agg_interval: int | None = None,
        sdk_client: ISDKClient | None = None,
        **kwargs,
    ):
        """
        初始化智能检测算法

        Args:
            config: 算法配置
            agg_interval: 聚合间隔（秒）
            sdk_client: SDK 客户端（可选）
            **kwargs: 额外参数
        """
        self.agg_interval = agg_interval or self.default_agg_interval
        self.sdk_client = sdk_client
        self._pre_detect_results: dict[str, dict[str, Any]] = {}

        super().__init__(config=config, **kwargs)

    def _validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """验证配置"""
        args = config.get("args", {})

        validated = {
            "args": args,
            "use_sdk": config.get("use_sdk", False),
        }

        return validated

    def get_history_offsets(self, **kwargs) -> list[int]:
        """获取历史数据偏移量"""
        return [self.agg_interval]

    def extra_context(self, data_point: IDataPoint) -> dict[str, Any]:
        """添加 SDK 结果到上下文"""
        context = super().extra_context(data_point)

        # 获取 values 字段（SDK 返回的结果）
        values = getattr(data_point, "values", {})
        if hasattr(data_point, "original"):
            values = getattr(data_point.original, "values", values)

        env = copy.deepcopy(values)

        # 解析 extra_info
        if "extra_info" in env:
            try:
                if isinstance(env["extra_info"], str):
                    env["extra_info"] = json.loads(env["extra_info"])
            except Exception as e:
                logger.debug(f"Failed to parse extra_info: {e}")
                env["extra_info"] = {}
        else:
            env["extra_info"] = {}

        # 提取常用字段
        if "anomaly_score" in env.get("extra_info", {}):
            env["anomaly_score"] = env["extra_info"]["anomaly_score"]

        if "anomaly_score" in env:
            env["anomaly_score"] = round(env.get("anomaly_score", 0), 2)

        if "alert_msg" in env.get("extra_info", {}):
            env["alert_msg"] = env["extra_info"]["alert_msg"]

        # 获取前一时刻数据
        env["previous_point"] = self.history_point_fetcher(data_point)

        context.update(env)
        return context

    def _gen_detectors(self) -> Generator[ExpressionDetector, None, None]:
        """生成智能检测器"""
        # 检测 is_anomaly > 0
        expr = "is_anomaly > 0"
        yield ExpressionDetector(
            expr=expr,
            desc_tpl=self.desc_tpl,
            unit=self.unit,
            unit_converter=self.unit_converter,
            template_engine=self.template_engine,
        )

    def detect(self, data_point: IDataPoint) -> list[BaseAnomalyPoint]:
        """
        执行检测

        如果配置了 SDK，则调用 SDK 进行检测。

        Args:
            data_point: 数据点

        Returns:
            异常数据点列表
        """
        use_sdk = self.validated_config.get("use_sdk", False)

        if use_sdk and self.sdk_client:
            # 检查是否有预检测结果
            if self._pre_detect_results:
                predict_result = self._pre_detect_results.get(data_point.record_id)
                if predict_result:
                    # 使用预检测结果
                    return self._detect_by_result(data_point, predict_result)

            # 单独调用 SDK
            return self._detect_by_sdk(data_point)

        # 不使用 SDK，直接检测 data_point 中的结果
        return super().detect(data_point)

    def _detect_by_sdk(self, data_point: IDataPoint) -> list[BaseAnomalyPoint]:
        """
        通过 SDK 进行检测

        Args:
            data_point: 数据点

        Returns:
            异常数据点列表
        """
        if not self.sdk_client:
            raise SDKError("SDK client not configured", sdk_name="intelligent") from None

        try:
            # 准备 SDK 参数
            data = [{"value": data_point.value, "timestamp": data_point.timestamp * 1000}]
            dimensions = self._generate_dimensions(data_point)
            params = self._generate_sdk_params()

            # 调用 SDK
            result = self.sdk_client.predict(data, dimensions, **params)

            return self._detect_by_result(data_point, result[0] if result else {})
        except Exception as e:
            logger.warning(f"SDK prediction failed: {e}")
            raise SDKError(str(e), sdk_name="intelligent") from None

    def _detect_by_result(self, data_point: IDataPoint, result: dict[str, Any]) -> list[BaseAnomalyPoint]:
        """
        基于 SDK 结果进行检测

        Args:
            data_point: 原始数据点
            result: SDK 返回的结果

        Returns:
            异常数据点列表
        """
        # 创建带有 SDK 结果的数据点
        from tsdetect.core.base import SimpleDataPoint

        result_point = SimpleDataPoint(
            value=data_point.value,
            timestamp=data_point.timestamp,
            unit=data_point.unit,
            dimensions=data_point.dimensions,
            values=result,
        )

        # 使用父类的检测逻辑
        return super().detect(result_point)

    def pre_detect(self, data_points: list[IDataPoint]):
        """
        批量预检测

        调用 SDK 的批量预测接口，缓存结果供后续检测使用。

        Args:
            data_points: 数据点列表
        """
        if not self.sdk_client:
            return

        use_sdk = self.validated_config.get("use_sdk", False)
        if not use_sdk:
            return

        self._pre_detect_results.clear()

        # 按维度分组
        predict_inputs = {}
        for dp in data_points:
            dimension_key = dp.record_id.split(".")[0]
            if dimension_key not in predict_inputs:
                predict_inputs[dimension_key] = {
                    "dimensions": self._generate_dimensions(dp),
                    "data": [],
                }

            predict_inputs[dimension_key]["data"].append(
                {
                    "__index__": dp.record_id,
                    "value": dp.value,
                    "timestamp": dp.timestamp * 1000,
                }
            )

        # 批量预测
        params = self._generate_sdk_params()

        try:
            for predict_input in predict_inputs.values():
                results = self.sdk_client.batch_predict([predict_input], **params)
                for result in results:
                    if "__index__" in result:
                        self._pre_detect_results[result["__index__"]] = result
        except Exception as e:
            logger.warning(f"Batch prediction failed: {e}")

    @abstractmethod
    def _generate_dimensions(self, data_point: IDataPoint) -> dict[str, Any]:
        """
        生成维度字典

        子类必须实现此方法。

        Args:
            data_point: 数据点

        Returns:
            维度字典
        """
        pass

    def _generate_sdk_params(self) -> dict[str, Any]:
        """
        生成 SDK 参数

        Args:

        Returns:
            SDK 参数字典
        """
        args = self.validated_config.get("args", {})
        return {"predict_args": {key.lstrip("$"): value for key, value in args.items()}}


class SimpleIntelligentAlgorithm(BaseIntelligentAlgorithm):
    """
    简单智能检测算法

    提供默认的维度生成实现。
    """

    def _generate_dimensions(self, data_point: IDataPoint) -> dict[str, Any]:
        """生成维度字典"""
        dimensions = copy.deepcopy(data_point.dimensions)
        return dimensions


class MockSDKClient(ISDKClient):
    """
    模拟 SDK 客户端

    用于测试场景。
    """

    def __init__(self, anomaly_threshold: float = 0.8, always_anomaly: bool = False):
        """
        初始化模拟 SDK

        Args:
            anomaly_threshold: 异常阈值（值超过此阈值判定为异常）
            always_anomaly: 是否总是返回异常
        """
        self.anomaly_threshold = anomaly_threshold
        self.always_anomaly = always_anomaly

    def predict(self, data: list[dict[str, Any]], dimensions: dict[str, Any], **params) -> list[dict[str, Any]]:
        """模拟预测"""
        results = []
        for item in data:
            value = item.get("value", 0)
            is_anomaly = 1 if (self.always_anomaly or value > self.anomaly_threshold) else 0

            results.append(
                {
                    "value": value,
                    "timestamp": item.get("timestamp", 0),
                    "is_anomaly": is_anomaly,
                    "anomaly_score": value / 100 if is_anomaly else 0,
                    "extra_info": json.dumps(
                        {
                            "anomaly_score": value / 100,
                            "alert_msg": "mock anomaly" if is_anomaly else "",
                        }
                    ),
                }
            )

        return results

    def batch_predict(self, data_groups: list[dict[str, Any]], **params) -> list[dict[str, Any]]:
        """模拟批量预测"""
        results = []
        for group in data_groups:
            for item in group.get("data", []):
                value = item.get("value", 0)
                is_anomaly = 1 if (self.always_anomaly or value > self.anomaly_threshold) else 0

                results.append(
                    {
                        "__index__": item.get("__index__", ""),
                        "value": value,
                        "timestamp": item.get("timestamp", 0),
                        "is_anomaly": is_anomaly,
                        "anomaly_score": value / 100 if is_anomaly else 0,
                    }
                )

        return results


def create_intelligent_algorithm(
    use_sdk: bool = False,
    args: dict[str, Any] | None = None,
    sdk_client: ISDKClient | None = None,
    agg_interval: int = 60,
    **kwargs,
) -> SimpleIntelligentAlgorithm:
    """
    快捷创建智能检测算法

    Args:
        use_sdk: 是否使用 SDK
        args: SDK 参数
        sdk_client: SDK 客户端
        agg_interval: 聚合间隔（秒）
        **kwargs: 额外参数

    Returns:
        智能检测算法实例
    """
    config = {
        "use_sdk": use_sdk,
        "args": args or {},
    }
    return SimpleIntelligentAlgorithm(config=config, agg_interval=agg_interval, sdk_client=sdk_client, **kwargs)
