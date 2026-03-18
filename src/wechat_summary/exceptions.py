"""Centralized exceptions for wechat-summary tool."""


class WeChatSummaryError(Exception):
    """Base exception for all wechat-summary errors."""


class DeviceNotFoundError(WeChatSummaryError):
    """No Android device found or connection failed."""


class WeChatNotFoundError(WeChatSummaryError):
    """WeChat (com.tencent.mm) not installed on device."""


class StabilityError(WeChatSummaryError):
    """UI hierarchy did not stabilize after retries."""


class LLMConnectionError(WeChatSummaryError):
    """Cannot connect to LLM endpoint."""


class ExtractionError(WeChatSummaryError):
    """Error during message extraction."""


class CalibrationError(WeChatSummaryError):
    """Auto-calibration failed."""


__all__ = [
    "WeChatSummaryError",
    "DeviceNotFoundError",
    "WeChatNotFoundError",
    "StabilityError",
    "LLMConnectionError",
    "ExtractionError",
    "CalibrationError",
]
