"""Tests for WeChat selector fallback and stable hierarchy dumping."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "wechat_summary" / "selectors.py"
MODULE_SPEC = importlib.util.spec_from_file_location("wechat_summary.selectors", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
selectors = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(selectors)

DEFAULT_SELECTORS = selectors.DEFAULT_SELECTORS
StabilityError = selectors.StabilityError
find_all_elements = selectors.find_all_elements
find_element = selectors.find_element
stable_dump = selectors.stable_dump


class FakeUiCollection:
    """Minimal fake for uiautomator2 selector results."""

    def __init__(self, items: Sequence[object] | None = None):
        self._items = list(items or [])

    @property
    def exists(self) -> bool:
        return bool(self._items)

    @property
    def count(self) -> int:
        return len(self._items)

    def all(self) -> list[object]:
        return list(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, index: int) -> object:
        return self._items[index]


class FakeDevice:
    """Fake uiautomator2 device with deterministic selector responses."""

    def __init__(
        self,
        responses: dict[tuple, FakeUiCollection] | None = None,
        dumps: list[str] | None = None,
    ):
        self.responses = responses or {}
        self.dumps = dumps or []
        self.calls: list[tuple] = []
        self.dump_calls = 0

    def __call__(self, **kwargs):
        call = ("uiautomator", tuple(sorted(kwargs.items())))
        self.calls.append(call)
        return self.responses.get(call, FakeUiCollection())

    def xpath(self, expression: str):
        call = ("xpath", expression)
        self.calls.append(call)
        return self.responses.get(call, FakeUiCollection())

    def dump_hierarchy(self) -> str:
        if self.dump_calls >= len(self.dumps):
            raise AssertionError("No fake dumps remaining")
        value = self.dumps[self.dump_calls]
        self.dump_calls += 1
        return value


def strategy_call(strategy: dict) -> tuple:
    if strategy["type"] == "xpath":
        return ("xpath", strategy["value"])
    return ("uiautomator", tuple(sorted(strategy["params"].items())))


class TestDefaultSelectors:
    def test_default_selectors_define_required_elements_and_order(self):
        expected = {
            "message_container",
            "message_text",
            "sender_name",
            "timestamp",
            "chat_title",
            "message_input_box",
        }

        assert set(DEFAULT_SELECTORS) == expected

        for selector_name in expected:
            strategies = DEFAULT_SELECTORS[selector_name]
            assert len(strategies) == 3
            assert all(strategy["type"] in {"uiautomator", "xpath"} for strategy in strategies)
            assert any(
                strategy["type"] == "uiautomator" and "resourceId" in strategy.get("params", {})
                for strategy in strategies
            )


class TestFindElement:
    def test_returns_primary_match_without_fallback(self):
        element = SimpleNamespace(name="primary")
        primary = DEFAULT_SELECTORS["message_text"][0]
        device = FakeDevice({strategy_call(primary): FakeUiCollection([element])})

        found = find_element(device, "message_text")

        assert found is element
        assert device.calls == [strategy_call(primary)]

    def test_falls_back_to_xpath_when_primary_has_no_match(self):
        element = SimpleNamespace(name="secondary")
        primary, secondary, _ = DEFAULT_SELECTORS["sender_name"]
        device = FakeDevice(
            {
                strategy_call(primary): FakeUiCollection(),
                strategy_call(secondary): FakeUiCollection([element]),
            }
        )

        found = find_element(device, "sender_name")

        assert found is element
        assert device.calls == [strategy_call(primary), strategy_call(secondary)]

    def test_uses_resource_id_as_tertiary_fallback(self):
        element = SimpleNamespace(name="tertiary")
        primary, secondary, tertiary = DEFAULT_SELECTORS["chat_title"]
        device = FakeDevice(
            {
                strategy_call(primary): FakeUiCollection(),
                strategy_call(secondary): FakeUiCollection(),
                strategy_call(tertiary): FakeUiCollection([element]),
            }
        )

        found = find_element(device, "chat_title")

        assert found is element
        assert device.calls == [
            strategy_call(primary),
            strategy_call(secondary),
            strategy_call(tertiary),
        ]

    def test_raises_lookup_error_when_all_strategies_fail(self):
        primary, secondary, tertiary = DEFAULT_SELECTORS["timestamp"]
        device = FakeDevice(
            {
                strategy_call(primary): FakeUiCollection(),
                strategy_call(secondary): FakeUiCollection(),
                strategy_call(tertiary): FakeUiCollection(),
            }
        )

        with pytest.raises(LookupError, match="timestamp"):
            find_element(device, "timestamp")

    def test_raises_key_error_for_unknown_selector(self):
        with pytest.raises(KeyError, match="unknown_selector"):
            find_element(FakeDevice(), "unknown_selector")


class TestFindAllElements:
    def test_returns_all_primary_matches(self):
        items = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        primary = DEFAULT_SELECTORS["message_input_box"][0]
        device = FakeDevice({strategy_call(primary): FakeUiCollection(items)})

        found = find_all_elements(device, "message_input_box")

        assert found == items
        assert device.calls == [strategy_call(primary)]

    def test_falls_back_when_primary_has_no_matches(self):
        items = [SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3)]
        primary, secondary, _ = DEFAULT_SELECTORS["message_text"]
        device = FakeDevice(
            {
                strategy_call(primary): FakeUiCollection(),
                strategy_call(secondary): FakeUiCollection(items),
            }
        )

        found = find_all_elements(device, "message_text")

        assert found == items
        assert device.calls == [strategy_call(primary), strategy_call(secondary)]

    def test_returns_empty_list_when_all_strategies_fail(self):
        primary, secondary, tertiary = DEFAULT_SELECTORS["chat_title"]
        device = FakeDevice(
            {
                strategy_call(primary): FakeUiCollection(),
                strategy_call(secondary): FakeUiCollection(),
                strategy_call(tertiary): FakeUiCollection(),
            }
        )

        assert find_all_elements(device, "chat_title") == []


class TestStableDump:
    def test_returns_first_dump_when_hierarchy_is_stable(self, monkeypatch):
        monkeypatch.setattr(selectors.time, "sleep", lambda _: None)
        device = FakeDevice(dumps=["stable", "stable"])

        result = stable_dump(device)

        assert result == "stable"
        assert device.dump_calls == 2

    def test_retries_until_hierarchy_becomes_stable(self, monkeypatch):
        monkeypatch.setattr(selectors.time, "sleep", lambda _: None)
        device = FakeDevice(dumps=["first", "second", "stable", "stable"])

        result = stable_dump(device, max_retries=3, delay=0)

        assert result == "stable"
        assert device.dump_calls == 4

    def test_raises_stability_error_after_max_retries(self, monkeypatch):
        monkeypatch.setattr(selectors.time, "sleep", lambda _: None)
        device = FakeDevice(dumps=["a", "b", "c", "d", "e", "f"])

        with pytest.raises(StabilityError, match="max_retries=3"):
            stable_dump(device, max_retries=3, delay=0)

        assert device.dump_calls == 6
