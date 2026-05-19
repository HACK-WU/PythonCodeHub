"""
TsDetect - 时序数据异常检测库

一个通用的时序数据异常检测库，提供多种检测算法：
- 静态阈值检测
- 同比/环比检测
- 智能检测
- 离群检测

使用示例：
    from tsdetect import ThresholdAlgorithm, SimpleDataPoint

    dp = SimpleDataPoint({"value": 95.0, "timestamp": 1234567890, "unit": "%"})
    algo = ThresholdAlgorithm({"threshold": 90, "method": "gt"})
    result = algo.detect(dp)
"""

from tsdetect.algorithms.amplitude import (
    RingRatioAmplitudeAlgorithm,
    YearRoundAmplitudeAlgorithm,
    create_ring_ratio_amplitude,
    create_year_round_amplitude,
)
from tsdetect.algorithms.intelligent import (
    SimpleIntelligentAlgorithm,
    create_intelligent_algorithm,
)
from tsdetect.algorithms.ring_ratio import (
    AdvancedRingRatioAlgorithm,
    SimpleRingRatioAlgorithm,
    create_advanced_ring_ratio,
    create_simple_ring_ratio,
)

# 导入具体算法实现
from tsdetect.algorithms.threshold import (
    AndThresholdAlgorithm,
    ThresholdAlgorithm,
    create_threshold_algorithm,
)
from tsdetect.algorithms.year_round import (
    AdvancedYearRoundAlgorithm,
    SimpleYearRoundAlgorithm,
    create_advanced_year_round,
    create_simple_year_round,
)
from tsdetect.core.algorithms import (
    BaseAlgorithm,
    BaseAlgorithmCollection,
    ExpressionDetector,
    RangeRatioAlgorithm,
)
from tsdetect.core.base import BaseAnomalyPoint, BaseDataPoint, SimpleDataPoint
from tsdetect.core.exceptions import (
    DetectionError,
    InvalidAlgorithmConfigError,
    InvalidDataPointError,
    TsDetectError,
)
from tsdetect.core.interfaces import (
    IDataPoint,
    IHistoryFetcher,
    ITemplateEngine,
    IUnitConverter,
)

__version__ = "0.1.0"
__all__ = [
    # 版本
    "__version__",
    # 基类
    "BaseDataPoint",
    "SimpleDataPoint",
    "BaseAnomalyPoint",
    "BaseAlgorithm",
    "BaseAlgorithmCollection",
    "ExpressionDetector",
    "RangeRatioAlgorithm",
    # 接口
    "IDataPoint",
    "IHistoryFetcher",
    "ITemplateEngine",
    "IUnitConverter",
    # 异常
    "TsDetectError",
    "InvalidAlgorithmConfigError",
    "InvalidDataPointError",
    "DetectionError",
    # 阈值算法
    "ThresholdAlgorithm",
    "AndThresholdAlgorithm",
    "create_threshold_algorithm",
    # 环比算法
    "SimpleRingRatioAlgorithm",
    "AdvancedRingRatioAlgorithm",
    "create_simple_ring_ratio",
    "create_advanced_ring_ratio",
    # 同比算法
    "SimpleYearRoundAlgorithm",
    "AdvancedYearRoundAlgorithm",
    "create_simple_year_round",
    "create_advanced_year_round",
    # 振幅算法
    "RingRatioAmplitudeAlgorithm",
    "YearRoundAmplitudeAlgorithm",
    "create_ring_ratio_amplitude",
    "create_year_round_amplitude",
    # 智能检测算法
    "SimpleIntelligentAlgorithm",
    "create_intelligent_algorithm",
]
