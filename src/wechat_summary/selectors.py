"""Default WeChat UI selectors with fallback lookup helpers."""

from __future__ import annotations

import time
from typing import Any

from wechat_summary.config import SelectorConfig
from wechat_summary.exceptions import StabilityError


def _build_default_selectors(
    config: SelectorConfig | None = None,
) -> dict[str, list[dict[str, Any]]]:
    cfg = config or SelectorConfig.default()
    cv = cfg.chat_view

    return {
        "message_container": [
            {
                "type": "uiautomator",
                "params": {"resourceId": cv.message_container},
            },
            {
                "type": "uiautomator",
                "params": {
                    "className": "androidx.recyclerview.widget.RecyclerView",
                    "scrollable": True,
                },
            },
            {
                "type": "uiautomator",
                "params": {"resourceId": "com.tencent.mm:id/message_list"},
            },
        ],
        "message_text": [
            {
                "type": "uiautomator",
                "params": {"resourceId": cv.message_text},
            },
            {
                "type": "xpath",
                "value": f'//*[@resource-id="{cv.message_text}"]',
            },
            {
                "type": "uiautomator",
                "params": {
                    "className": "android.widget.TextView",
                    "textMatches": r".+",
                },
            },
        ],
        "sender_name": [
            {
                "type": "uiautomator",
                "params": {"resourceId": cv.sender_name},
            },
            {
                "type": "xpath",
                "value": f'//*[@resource-id="{cv.sender_name}"]',
            },
            {
                "type": "uiautomator",
                "params": {
                    "className": "android.widget.TextView",
                    "textMatches": r".+",
                },
            },
        ],
        "timestamp": [
            {
                "type": "uiautomator",
                "params": {"resourceId": cv.timestamp},
            },
            {
                "type": "xpath",
                "value": f'//*[@resource-id="{cv.timestamp}"]',
            },
            {
                "type": "uiautomator",
                "params": {
                    "className": "android.widget.TextView",
                    "textMatches": (
                        r"^\d{1,2}:\d{2}$"
                        r"|^(?:周|星期)[一二三四五六日天]\s*\d{1,2}:\d{2}$"
                        r"|^(?:昨天|前天)\s*\d{1,2}:\d{2}$"
                    ),
                },
            },
        ],
        "chat_title": [
            {
                "type": "uiautomator",
                "params": {"resourceId": "com.tencent.mm:id/obq"},
            },
            {
                "type": "xpath",
                "value": (
                    '//*[@resource-id="com.tencent.mm:id/obq"]'
                    "//*[@text and string-length(@text) > 0]"
                ),
            },
            {
                "type": "uiautomator",
                "params": {
                    "className": "android.widget.TextView",
                    "textMatches": r".+",
                },
            },
        ],
        "message_input_box": [
            {
                "type": "uiautomator",
                "params": {
                    "className": "android.widget.EditText",
                    "textMatches": r".*",
                },
            },
            {
                "type": "xpath",
                "value": "//android.widget.EditText",
            },
            {
                "type": "uiautomator",
                "params": {"resourceId": cv.input_box},
            },
        ],
    }


DEFAULT_SELECTORS: dict[str, list[dict[str, Any]]] = _build_default_selectors()


def find_element(device: Any, selector_name: str, config: SelectorConfig | None = None) -> Any:
    """Find the first matching element using the configured fallback chain."""

    strategies = _get_strategies(selector_name, config=config)
    for strategy in strategies:
        collection = _run_strategy(device, strategy)
        elements = _coerce_elements(collection)
        if elements:
            return elements[0]
        if getattr(collection, "exists", False):
            return collection

    raise LookupError(f"No element found for selector '{selector_name}'")


def find_all_elements(
    device: Any, selector_name: str, config: SelectorConfig | None = None
) -> list[Any]:
    """Find all matching elements using the configured fallback chain."""

    strategies = _get_strategies(selector_name, config=config)
    for strategy in strategies:
        collection = _run_strategy(device, strategy)
        elements = _coerce_elements(collection)
        if elements:
            return elements
        if getattr(collection, "exists", False):
            return [collection]

    return []


def stable_dump(device: Any, max_retries: int = 3, delay: float = 0.5) -> str:
    """Return a stable hierarchy dump by comparing consecutive snapshots."""

    if max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    for _ in range(max_retries):
        first = device.dump_hierarchy()
        time.sleep(delay)
        second = device.dump_hierarchy()
        if first == second:
            return first

    raise StabilityError(f"UI hierarchy did not stabilize after max_retries={max_retries}")


def _get_strategies(
    selector_name: str,
    config: SelectorConfig | None = None,
) -> list[dict[str, Any]]:
    selectors = DEFAULT_SELECTORS if config is None else _build_default_selectors(config)
    try:
        return selectors[selector_name]
    except KeyError as exc:
        raise KeyError(f"Unknown selector: {selector_name}") from exc


def _run_strategy(device: Any, strategy: dict[str, Any]) -> Any:
    strategy_type = strategy["type"]
    if strategy_type == "xpath":
        return device.xpath(strategy["value"])
    if strategy_type == "uiautomator":
        return device(**strategy["params"])
    raise ValueError(f"Unsupported selector strategy: {strategy_type}")


def _coerce_elements(collection: Any) -> list[Any]:
    if hasattr(collection, "all"):
        try:
            items = list(collection.all())
        except TypeError:
            items = []
        if items:
            return items

    if hasattr(collection, "count") and hasattr(collection, "__getitem__"):
        try:
            count = int(collection.count)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            return [collection[index] for index in range(count)]

    try:
        items = list(collection)
    except TypeError:
        items = []

    return items


__all__ = [
    "DEFAULT_SELECTORS",
    "StabilityError",
    "find_all_elements",
    "find_element",
    "stable_dump",
]
