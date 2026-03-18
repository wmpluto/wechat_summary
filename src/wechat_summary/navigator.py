"""Navigate WeChat message list and manage chat traversal."""

from __future__ import annotations

import re
import random
import time
from datetime import date, timedelta
from typing import Any
import xml.etree.ElementTree as ET

import click

from wechat_summary.config import SelectorConfig
from wechat_summary.models import ChatListItem
from wechat_summary.selectors import stable_dump


BLACKLIST = frozenset(
    {
        "公众号",
        "服务号",
        "服务通知",
        "微信支付",
        "文件传输助手",
        "微信团队",
        "腾讯新闻",
    }
)


def parse_chat_time(text: str) -> date | None:
    """Parse WeChat message list time text to a date."""

    text = text.strip()
    if not text:
        return None

    today = date.today()

    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        return today

    if text == "昨天":
        return today - timedelta(days=1)

    if text == "前天":
        return today - timedelta(days=2)

    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    weekday_match = re.fullmatch(r"(?:周|星期)([一二三四五六日天])", text)
    if weekday_match:
        target_weekday = weekday_map[weekday_match.group(1)]
        current_weekday = today.weekday()
        days_diff = (current_weekday - target_weekday) % 7
        if days_diff == 0:
            days_diff = 7
        return today - timedelta(days=days_diff)

    md_match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", text)
    if md_match:
        try:
            return date(today.year, int(md_match.group(1)), int(md_match.group(2)))
        except ValueError:
            return None

    full_match = re.fullmatch(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if full_match:
        try:
            return date(
                int(full_match.group(1)), int(full_match.group(2)), int(full_match.group(3))
            )
        except ValueError:
            return None

    return None


class ChatListNavigator:
    """Parse and navigate the WeChat message list."""

    def __init__(self, config: SelectorConfig | None = None):
        self.config = config or SelectorConfig.default()
        self._processed: set[str] = set()
        self._in_folded: bool = False

    def parse_chat_list(self, device: Any) -> list[ChatListItem]:
        """Parse visible chat items from the message list screen."""

        xml_text = stable_dump(device)
        return self.parse_chat_list_xml(xml_text, source="main")

    def parse_chat_list_xml(self, xml_text: str, source: str = "main") -> list[ChatListItem]:
        """Parse chat items from XML text. Testable without device."""

        root = ET.fromstring(xml_text)
        ml = self.config.message_list

        container = None
        for selector in (
            f'.//*[@resource-id="{ml.container}"]',
            './/*[@class="android.widget.ListView"][@scrollable="true"]',
        ):
            container = root.find(selector)
            if container is not None:
                break

        if container is None:
            return []

        item_id = self._id_tail(ml.chat_item)
        name_id = self._id_tail(ml.chat_name)
        time_id = self._id_tail(ml.last_time)
        preview_id = self._id_tail(ml.last_preview)

        items: list[ChatListItem] = []
        for child in container:
            child_rid_tail = self._id_tail(child.get("resource-id", ""))
            is_clickable = child.get("clickable") == "true"
            if not (child_rid_tail == item_id or is_clickable):
                continue

            name = ""
            time_text = ""
            preview = ""
            for descendant in child.iter():
                rid_tail = self._id_tail(descendant.get("resource-id", ""))
                if rid_tail == name_id:
                    name = (descendant.get("text") or "").strip()
                elif rid_tail == time_id:
                    time_text = (descendant.get("text") or "").strip()
                elif rid_tail == preview_id:
                    preview = (descendant.get("text") or "").strip()

            if not name:
                continue

            parsed_date = parse_chat_time(time_text)
            is_folded = name == "折叠的聊天"
            is_blacklisted = name in BLACKLIST

            items.append(
                ChatListItem(
                    name=name,
                    last_time_text=time_text,
                    last_time=parsed_date,
                    preview=preview,
                    is_folded=is_folded,
                    is_blacklisted=is_blacklisted,
                    source=source,
                )
            )

        return items

    def parse_folded_list(self, device: Any) -> list[ChatListItem]:
        """Parse visible chat items from the folded chats screen."""

        xml_text = stable_dump(device)
        return self.parse_folded_list_xml(xml_text)

    def parse_folded_list_xml(self, xml_text: str) -> list[ChatListItem]:
        """Parse folded chat items from XML text. Testable without device."""

        root = ET.fromstring(xml_text)
        fc = self.config.folded_chats
        ml = self.config.message_list

        container = None
        for selector in (
            f'.//*[@resource-id="{fc.container}"]',
            './/*[@class="android.widget.ListView"][@scrollable="true"]',
        ):
            container = root.find(selector)
            if container is not None:
                break

        if container is None:
            return []

        item_id = self._id_tail(fc.chat_item)
        name_id = self._id_tail(ml.chat_name)
        time_id = self._id_tail(ml.last_time)
        preview_id = self._id_tail(ml.last_preview)

        items: list[ChatListItem] = []
        for child in container:
            child_rid_tail = self._id_tail(child.get("resource-id", ""))
            is_clickable = child.get("clickable") == "true"
            if not (child_rid_tail == item_id or is_clickable):
                continue

            name = ""
            time_text = ""
            preview = ""
            for descendant in child.iter():
                rid_tail = self._id_tail(descendant.get("resource-id", ""))
                if rid_tail == name_id:
                    name = (descendant.get("text") or descendant.get("content-desc") or "").strip()
                elif rid_tail == time_id:
                    time_text = (descendant.get("text") or "").strip()
                elif rid_tail == preview_id:
                    preview = (descendant.get("text") or "").strip()

            if not name:
                continue

            parsed_date = parse_chat_time(time_text)
            items.append(
                ChatListItem(
                    name=name,
                    last_time_text=time_text,
                    last_time=parsed_date,
                    preview=preview,
                    is_folded=False,
                    is_blacklisted=name in BLACKLIST,
                    source="folded",
                )
            )

        return items

    def filter_items(
        self,
        items: list[ChatListItem],
        since: date,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[ChatListItem]:
        """Filter chat items by blacklist, time, include/exclude rules."""

        result = []
        for item in items:
            if item.is_blacklisted:
                continue
            if item.last_time is not None and item.last_time < since:
                continue
            if include and not any(pattern in item.name for pattern in include):
                continue
            if exclude and any(pattern in item.name for pattern in exclude):
                continue
            result.append(item)
        return result

    def enter_chat(self, device: Any, item: ChatListItem) -> bool:
        """Click on a chat item to enter the conversation."""

        try:
            ml = self.config.message_list

            click.echo(
                f'  🔍 查找聊天项: resourceId={self._id_tail(ml.chat_name)}, text="{item.name}"'
            )
            name_element = device(resourceId=ml.chat_name, text=item.name)
            if name_element.exists(timeout=2):
                click.echo(f"  👆 点击: {item.name} (by resourceId+text)")
                name_element.click()
                time.sleep(1.0)
                result = self._verify_chat_view(device)
                click.echo(f"  {'✅' if result else '❌'} 进入聊天视图: {result}")
                return result

            click.echo(f'  🔍 回退: 按 text="{item.name}" 查找')
            text_element = device(text=item.name)
            if text_element.exists(timeout=2):
                click.echo(f"  👆 点击: {item.name} (by text)")
                text_element.click()
                time.sleep(1.0)
                result = self._verify_chat_view(device)
                click.echo(f"  {'✅' if result else '❌'} 进入聊天视图: {result}")
                return result

            click.echo(f"  ❌ 未找到聊天项: {item.name}")
            return False
        except Exception as exc:
            click.echo(f"  ❌ enter_chat 异常: {exc}")
            return False

    def exit_chat(self, device: Any) -> bool:
        """Press back button to return to the message list."""

        try:
            nav = self.config.navigation
            click.echo(
                f"  🔙 查找返回按钮: resourceId={self._id_tail(nav.back_button)} (in_folded={self._in_folded})"
            )
            back = device(resourceId=nav.back_button)
            if back.exists(timeout=2):
                click.echo("  👆 点击: 返回按钮 (actionbar_up_indicator)")
                back.click()
                time.sleep(0.8)
            else:
                click.echo("  👆 按键: device.press('back') (返回按钮未找到)")
                device.press("back")
                time.sleep(0.8)

            if self._in_folded:
                # In folded mode: back goes to folded list (no wechat tab there)
                result = self._verify_folded_view(device)
                click.echo(f"  {'✅' if result else '❌'} 返回折叠列表: {result}")
            else:
                # Main mode: tap wechat tab for safety, verify main list
                self._tap_wechat_tab(device)
                result = self._verify_list_view(device)
                click.echo(f"  {'✅' if result else '❌'} 返回消息列表: {result}")
            return result
        except Exception as exc:
            click.echo(f"  ❌ exit_chat 异常: {exc}")
            return False

    def enter_folded_chats(self, device: Any) -> bool:
        """Click on folded chats entry and verify folded view."""

        try:
            click.echo('  🔍 查找: text="折叠的聊天"')
            element = device(text="折叠的聊天")
            if element.exists(timeout=2):
                click.echo("  👆 点击: 折叠的聊天")
                element.click()
                time.sleep(1.0)
                result = self._verify_folded_view(device)
                if result:
                    self._in_folded = True
                click.echo(f"  {'✅' if result else '❌'} 进入折叠视图: {result}")
                return result
            click.echo("  ❌ 未找到 '折叠的聊天'")
            return False
        except Exception as exc:
            click.echo(f"  ❌ enter_folded_chats 异常: {exc}")
            return False

    def exit_folded_chats(self, device: Any) -> bool:
        """Return from folded chats to main list."""

        self._in_folded = False
        try:
            nav = self.config.navigation
            click.echo(f"  🔙 退出折叠: 查找返回按钮 resourceId={self._id_tail(nav.back_button)}")
            back = device(resourceId=nav.back_button)
            if back.exists(timeout=2):
                click.echo("  👆 点击: 返回按钮 (from 折叠)")
                back.click()
                time.sleep(0.8)
            else:
                click.echo("  👆 按键: device.press('back') (from 折叠)")
                device.press("back")
                time.sleep(0.8)

            # Back to main list now, tap wechat tab for safety
            self._tap_wechat_tab(device)
            result = self._verify_list_view(device)
            click.echo(f"  {'✅' if result else '❌'} 返回消息列表 (from 折叠): {result}")
            return result
        except Exception as exc:
            click.echo(f"  ❌ exit_folded_chats 异常: {exc}")
            return False

    def scroll_chat_list(self, device: Any) -> bool:
        """Scroll message list down to reveal older conversations."""

        try:
            info = device.info or {}
            width = int(info.get("displayWidth", 1080))
            height = int(info.get("displayHeight", 1920))
            x = width // 2
            y_start = int(height * 0.7)
            y_end = int(height * 0.3)
            device.swipe(x, y_start, x, y_end, duration=0.3)
            time.sleep(random.uniform(0.8, 1.5))
            return True
        except Exception:
            return False

    def should_stop_scrolling(self, items: list[ChatListItem], since: date) -> bool:
        """Return True when visible dated items are all older than since."""

        if not items:
            return True

        dated_items = [item for item in items if item.last_time is not None]
        if not dated_items:
            return False

        for item in dated_items:
            last_time = item.last_time
            if last_time is None or last_time >= since:
                return False
        return True

    def mark_processed(self, name: str) -> None:
        """Mark a chat as processed."""

        self._processed.add(name)

    def is_processed(self, name: str) -> bool:
        """Check if a chat has been processed."""

        return name in self._processed

    def _id_tail(self, resource_id: str) -> str:
        if "/" in resource_id:
            return resource_id.rsplit("/", maxsplit=1)[-1]
        return resource_id

    def _tap_wechat_tab(self, device: Any) -> None:
        """Tap the bottom '微信' tab to ensure we land on the message list.

        Uses the icon_tv TextView with text="微信". Falls back to doing nothing
        if the tab is not found (already on list or different screen layout).
        """
        try:
            nav = self.config.navigation
            click.echo(
                f'  🏠 安全回归: 查找微信标签 resourceId={self._id_tail(nav.wechat_tab)}, text="微信"'
            )
            tab = device(resourceId=nav.wechat_tab, text="微信")
            if tab.exists(timeout=1):
                click.echo("  👆 点击: 微信标签 (底部导航)")
                tab.click()
                time.sleep(0.5)
            else:
                click.echo("  ⚠️  微信标签未找到 (可能已在消息列表)")
        except Exception as exc:
            click.echo(f"  ⚠️  _tap_wechat_tab 异常: {exc}")

    def _verify_chat_view(self, device: Any) -> bool:
        """Verify we're in a chat conversation view."""

        cv = self.config.chat_view
        try:
            if device(resourceId=cv.message_container).exists(timeout=2):
                return True
            if device(resourceId=cv.input_box).exists(timeout=1):
                return True
            return False
        except Exception:
            return False

    def _verify_list_view(self, device: Any) -> bool:
        """Verify we're back on the message list."""

        ml = self.config.message_list
        try:
            return device(resourceId=ml.container).exists(timeout=2)
        except Exception:
            return False

    def _verify_folded_view(self, device: Any) -> bool:
        """Verify we're in the folded chats view."""

        fc = self.config.folded_chats
        try:
            if device(text="折叠的聊天").exists(timeout=1):
                return True
            if device(resourceId=fc.container).exists(timeout=2):
                return True
            return False
        except Exception:
            return False
