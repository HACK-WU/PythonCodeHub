"""
TsDetect 算法模块

提供各种时序检测算法实现。
"""

from tsdetect.algorithms.amplitude import RingRatioAmplitudeAlgorithm, YearRoundAmplitudeAlgorithm
from tsdetect.algorithms.intelligent import (
    BaseIntelligentAlgorithm,
    MockSDKClient,
    SimpleIntelligentAlgorithm,
)
from tsdetect.algorithms.ring_ratio import AdvancedRingRatioAlgorithm, SimpleRingRatioAlgorithm
from tsdetect.algorithms.threshold import AndThresholdAlgorithm, ThresholdAlgorithm
from tsdetect.algorithms.year_round import AdvancedYearRoundAlgorithm, SimpleYearRoundAlgorithm

# 算法注册表
ALGORITHM_REGISTRY = {
    "Threshold": ThresholdAlgorithm,
    "AndThreshold": AndThresholdAlgorithm,
    "SimpleRingRatio": SimpleRingRatioAlgorithm,
    "AdvancedRingRatio": AdvancedRingRatioAlgorithm,
    "SimpleYearRound": SimpleYearRoundAlgorithm,
    "AdvancedYearRound": AdvancedYearRoundAlgorithm,
    "RingRatioAmplitude": RingRatioAmplitudeAlgorithm,
    "YearRoundAmplitude": YearRoundAmplitudeAlgorithm,
    "IntelligentDetect": SimpleIntelligentAlgorithm,
}


def get_algorithm(name: str):
    """
    根据名称获取算法类

    Args:
        name: 算法名称

    Returns:
        算法类

    Raises:
        KeyError: 算法不存在
    """
    if name not in ALGORITHM_REGISTRY:
        raise KeyError(f"Unknown algorithm: {name}. Available: {list(ALGORITHM_REGISTRY.keys())}")
    return ALGORITHM_REGISTRY[name]


def register_algorithm(name: str, algorithm_class):
    """
    注册自定义算法

    Args:
        name: 算法名称
        algorithm_class: 算法类
    """
    ALGORITHM_REGISTRY[name] = algorithm_class


__all__ = [
    # 算法类
    "ThresholdAlgorithm",
    "AndThresholdAlgorithm",
    "SimpleRingRatioAlgorithm",
    "AdvancedRingRatioAlgorithm",
    "SimpleYearRoundAlgorithm",
    "AdvancedYearRoundAlgorithm",
    "RingRatioAmplitudeAlgorithm",
    "YearRoundAmplitudeAlgorithm",
    "BaseIntelligentAlgorithm",
    "SimpleIntelligentAlgorithm",
    "MockSDKClient",
    # 注册表
    "ALGORITHM_REGISTRY",
    "get_algorithm",
    "register_algorithm",
]
