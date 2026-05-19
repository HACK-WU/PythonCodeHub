"""
TsDetect 异常定义

定义了库专用的异常类。
"""


class TsDetectError(Exception):
    """TsDetect 基础异常类"""

    def __init__(self, message: str = "", code: str = ""):
        self.message = message
        self.code = code
        super().__init__(self.message)

    def __str__(self):
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message


class InvalidAlgorithmConfigError(TsDetectError):
    """
    算法配置无效异常

    当算法配置验证失败时抛出。
    """

    def __init__(self, message: str = "", errors: dict = None):
        self.errors = errors or {}
        super().__init__(message, code="INVALID_CONFIG")


class InvalidDataPointError(TsDetectError):
    """
    数据点无效异常

    当数据点缺少必要字段或数据格式错误时抛出。
    """

    def __init__(self, message: str = "", field: str = ""):
        self.field = field
        super().__init__(message, code="INVALID_DATA_POINT")


class DetectionError(TsDetectError):
    """
    检测执行异常

    当检测过程中发生错误时抛出。
    """

    def __init__(self, message: str = "", algorithm: str = ""):
        self.algorithm = algorithm
        super().__init__(message, code="DETECTION_ERROR")


class HistoryDataError(TsDetectError):
    """
    历史数据获取异常

    当获取历史数据失败时抛出。
    """

    def __init__(self, message: str = "", offset: int = 0):
        self.offset = offset
        super().__init__(message, code="HISTORY_DATA_ERROR")


class UnitConversionError(TsDetectError):
    """
    单位转换异常

    当单位转换失败时抛出。
    """

    def __init__(self, message: str = "", from_unit: str = "", to_unit: str = ""):
        self.from_unit = from_unit
        self.to_unit = to_unit
        super().__init__(message, code="UNIT_CONVERSION_ERROR")


class ExpressionError(TsDetectError):
    """
    表达式执行异常

    当检测表达式执行失败时抛出。
    """

    def __init__(self, message: str = "", expression: str = ""):
        self.expression = expression
        super().__init__(message, code="EXPRESSION_ERROR")


class SDKError(TsDetectError):
    """
    SDK 调用异常

    当调用外部 SDK 失败时抛出。
    """

    def __init__(self, message: str = "", sdk_name: str = ""):
        self.sdk_name = sdk_name
        super().__init__(message, code="SDK_ERROR")
