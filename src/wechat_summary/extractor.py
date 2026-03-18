"""WeChat chat message extraction with scrolling and deduplication."""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta
import random
import re
import time
from typing import Any
import xml.etree.ElementTree as ET

import click

from wechat_summary.config import SelectorConfig
from wechat_summary.models import ChatMessage, ChatType, MessageType
from wechat_summary.selectors import find_all_elements, find_element, stable_dump


_TIME_RE = re.compile(
    r"^(?:"
    r"\d{1,2}:\d{2}"
    r"|(?:周|星期)[一二三四五六日天]\s*\d{1,2}:\d{2}"
    r"|(?:昨天|前天)\s*\d{1,2}:\d{2}"
    r"|\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日\s+\d{1,2}:\d{2}"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}"
    r")$"
)
_PLACEHOLDER_TO_TYPE: dict[str, MessageType] = {
    "[图片]": MessageType.IMAGE,
    "[语音]": MessageType.VOICE,
    "[视频]": MessageType.VIDEO,
    "[文件]": MessageType.FILE,
}


class MessageExtractor:
    """Extract chat messages from WeChat UI hierarchy XML."""

    def __init__(
        self,
        config: SelectorConfig | None = None,
        overlap_window: int = 5,
        max_scrolls: int = 50,
    ):
        self.config = config or SelectorConfig.default()
        self.overlap_window = overlap_window
        self.max_scrolls = max_scrolls
        self._current_timestamp: datetime | None = None
        self.unrecognized_count: int = 0

    def extract_visible_messages(self, device: Any) -> list[ChatMessage]:
        """Parse current screen and return visible messages in screen order (top→bottom)."""

        xml_text = stable_dump(device)
        root = ET.fromstring(xml_text)
        cv = self.config.chat_view

        message_container: ET.Element | None = None
        for selector in (
            f'.//*[@resource-id="{cv.message_container}"]',
            './/*[@class="androidx.recyclerview.widget.RecyclerView"][@scrollable="true"]',
            './/*[@resource-id="com.tencent.mm:id/message_list"]',
            './/*[@class="android.widget.ListView"][@scrollable="true"]',
        ):
            message_container = root.find(selector)
            if message_container is not None:
                break
        if message_container is None:
            return []

        candidate_nodes = [
            child
            for child in list(message_container)
            if self._resource_matches(child, self._id_tail(cv.message_wrapper))
            or child.get("class") == "android.widget.RelativeLayout"
        ]

        messages: list[ChatMessage] = []
        self._current_timestamp = None
        for node in candidate_nodes:
            message = self._parse_message_node(node)
            if message is not None:
                messages.append(message)

        # No sorting — screen order (top to bottom) IS chronological order
        return messages

    def scroll_and_extract(self, device: Any, since_date: date) -> list[ChatMessage]:
        """Scroll upward to see older messages and extract until `since_date`."""

        all_messages: list[ChatMessage] = []
        boundary_hashes: set[str] = set()
        self.unrecognized_count = 0

        for scroll_round in range(self.max_scrolls):
            click.echo(f"  📖 第{scroll_round + 1}页提取...")
            visible_messages = self.extract_visible_messages(device)
            click.echo(f"  📖 可见消息: {len(visible_messages)} 条")
            if not visible_messages:
                click.echo("  📖 无可见消息，停止")
                break

            has_older = False
            new_messages_this_round: list[ChatMessage] = []
            skipped_old = 0
            skipped_dup = 0

            for msg in visible_messages:
                if msg.timestamp is not None and msg.timestamp.date() < since_date:
                    has_older = True
                    skipped_old += 1
                    continue

                msg_hash = self._message_hash(msg)
                if msg_hash in boundary_hashes:
                    skipped_dup += 1
                    continue

                new_messages_this_round.append(msg)

            click.echo(
                f"  📖 新增={len(new_messages_this_round)} "
                f"跳过(旧)={skipped_old} 跳过(重复)={skipped_dup}"
            )

            # Prepend: each scroll reveals OLDER messages that go BEFORE existing ones
            all_messages = new_messages_this_round + all_messages

            page_hashes = [self._message_hash(msg) for msg in visible_messages]
            boundary_hashes = self._build_boundary_hashes(page_hashes)

            if has_older:
                click.echo("  📖 发现更旧消息，停止滑动")
                break
            if not new_messages_this_round:
                click.echo("  📖 无新消息，停止滑动")
                break

            self._scroll_up(device)
            time.sleep(random.uniform(0.8, 1.5))

        # No timestamp sort — order is maintained by screen position + prepend logic
        return all_messages

    def detect_chat_info(self, device: Any) -> tuple[str, ChatType]:
        """Detect chat title and whether current chat is private or group."""

        xml_text = stable_dump(device)
        root = ET.fromstring(xml_text)

        chat_name = ""
        try:
            title_element = find_element(device, "chat_title", config=self.config)
        except LookupError:
            title_element = None

        if title_element is not None:
            chat_name = self._element_text(title_element).strip()

        if not chat_name:
            for candidate in (
                root.find('.//*[@resource-id="com.tencent.mm:id/ko4"]'),
                root.find('.//*[@resource-id="com.tencent.mm:id/title"]'),
                root.find('.//*[@resource-id="com.tencent.mm:id/obq"]//*[@text]'),
            ):
                if candidate is None:
                    continue
                value = (candidate.get("text") or "").strip()
                if value:
                    chat_name = value
                    break

        if not chat_name:
            chat_name = "未知会话"

        has_group_sender = any(
            self._resource_matches(node, self._id_tail(self.config.chat_view.sender_name))
            and (node.get("text") or "").strip()
            for node in root.iter()
        )
        if has_group_sender:
            return chat_name, ChatType.GROUP

        sender_elements = find_all_elements(device, "sender_name", config=self.config)
        sender_names = {
            self._element_text(element).strip()
            for element in sender_elements
            if self._element_text(element).strip()
        }
        if len(sender_names) > 1:
            return chat_name, ChatType.GROUP
        return chat_name, ChatType.PRIVATE

    def _parse_message_node(self, node: ET.Element) -> ChatMessage | None:
        cv = self.config.chat_view
        timestamp_node = self._find_first_by_resource(node, self._id_tail(cv.timestamp))
        message_layout = self._find_first_by_resource(node, self._id_tail(cv.message_layout))

        # Always update _current_timestamp when br1 is present,
        # regardless of whether bkj exists.  In real WeChat dumps, br1 often
        # lives INSIDE the same bn1 as the message (br1 + bkj siblings).
        if timestamp_node is not None:
            timestamp_text = (timestamp_node.get("text") or "").strip()
            parsed_timestamp = self._parse_time(timestamp_text)
            if parsed_timestamp is not None:
                self._current_timestamp = parsed_timestamp

        if message_layout is None:
            return None

        sender = "未知"
        # Priority: brc (group sender name) > avatar content-desc > "未知"
        group_sender_node = self._find_first_by_resource(
            message_layout, self._id_tail(cv.sender_name)
        )
        avatar_node = self._find_first_by_resource(message_layout, self._id_tail(cv.avatar_image))

        if group_sender_node is not None:
            sender = (group_sender_node.get("text") or "").strip() or "未知"
        elif avatar_node is not None:
            sender = self._extract_sender_from_avatar(avatar_node)

        is_self = self._detect_is_self(message_layout, sender)

        content_node = self._find_first_by_resource(message_layout, self._id_tail(cv.message_text))
        content_class = ""
        content = ""
        message_type: MessageType | None = None

        if content_node is not None:
            content = (content_node.get("text") or "").strip()
            content_class = (content_node.get("class") or "").strip()
            message_type = self._detect_message_type(sender, content, content_class)
        else:
            image_node = self._find_first_by_resource(
                message_layout, self._id_tail(cv.image_message)
            )
            if image_node is not None:
                content = "[图片]"
                content_class = (image_node.get("class") or "").strip()
                message_type = MessageType.IMAGE
            else:
                file_node = self._find_first_by_resource(
                    message_layout, self._id_tail(cv.file_name)
                )
                if file_node is not None:
                    file_name = (file_node.get("text") or "").strip()
                    content = f"[文件] {file_name}" if file_name else "[文件]"
                    content_class = (file_node.get("class") or "").strip()
                    message_type = MessageType.FILE
                else:
                    emoticon_node = self._find_emoticon_node(message_layout)
                    if emoticon_node is not None:
                        content = "[表情]"
                        content_class = (emoticon_node.get("class") or "").strip()
                        message_type = MessageType.IMAGE

        if not content:
            if avatar_node is not None:
                # Node has a valid avatar but content type is unrecognized
                content = "[未识别消息]"
                message_type = MessageType.SYSTEM
                self.unrecognized_count += 1
            else:
                return None

        timestamp = self._current_timestamp
        if timestamp_node is not None and message_layout is not None:
            inline_timestamp = self._parse_time((timestamp_node.get("text") or "").strip())
            if inline_timestamp is not None:
                timestamp = inline_timestamp
                self._current_timestamp = inline_timestamp

        if message_type is None:
            message_type = self._detect_message_type(sender, content, content_class)

        return ChatMessage(
            sender=sender,
            content=content,
            timestamp=timestamp,
            message_type=message_type,
            is_self=is_self,
        )

    def _parse_time(self, text: str) -> datetime | None:
        if not _TIME_RE.match(text):
            return None

        text = text.strip()
        today = date.today()

        plain_match = re.fullmatch(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})", text)
        if plain_match:
            return self._build_datetime(
                today, plain_match.group("hour"), plain_match.group("minute")
            )

        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        weekday_match = re.fullmatch(
            r"(?:周|星期)(?P<day>[一二三四五六日天])\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            text,
        )
        if weekday_match:
            target_weekday = weekday_map[weekday_match.group("day")]
            current_weekday = today.weekday()
            days_diff = (current_weekday - target_weekday) % 7
            if days_diff == 0:
                days_diff = 7  # "周X" always means a past day, not today
            target_day = today - timedelta(days=days_diff)
            return self._build_datetime(
                target_day, weekday_match.group("hour"), weekday_match.group("minute")
            )

        relative_match = re.fullmatch(
            r"(?P<label>昨天|前天)\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            text,
        )
        if relative_match:
            delta_days = 1 if relative_match.group("label") == "昨天" else 2
            target_day = today - timedelta(days=delta_days)
            return self._build_datetime(
                target_day,
                relative_match.group("hour"),
                relative_match.group("minute"),
            )

        year_month_day_match = re.fullmatch(
            r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            text,
        )
        if year_month_day_match:
            try:
                target_day = date(
                    int(year_month_day_match.group("year")),
                    int(year_month_day_match.group("month")),
                    int(year_month_day_match.group("day")),
                )
            except ValueError:
                return None
            return self._build_datetime(
                target_day,
                year_month_day_match.group("hour"),
                year_month_day_match.group("minute"),
            )

        month_day_match = re.fullmatch(
            r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            text,
        )
        if month_day_match:
            try:
                target_day = date(
                    today.year,
                    int(month_day_match.group("month")),
                    int(month_day_match.group("day")),
                )
            except ValueError:
                return None
            return self._build_datetime(
                target_day,
                month_day_match.group("hour"),
                month_day_match.group("minute"),
            )

        full_date_match = re.fullmatch(
            r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})",
            text,
        )
        if full_date_match:
            try:
                target_day = date(
                    int(full_date_match.group("year")),
                    int(full_date_match.group("month")),
                    int(full_date_match.group("day")),
                )
            except ValueError:
                return None
            return self._build_datetime(
                target_day,
                full_date_match.group("hour"),
                full_date_match.group("minute"),
            )

        return None

    def _detect_message_type(self, sender: str, content: str, content_class: str) -> MessageType:
        if sender in {"系统", "system", "SYSTEM"}:
            return MessageType.SYSTEM
        if content in _PLACEHOLDER_TO_TYPE:
            return _PLACEHOLDER_TO_TYPE[content]
        if content_class == "android.widget.ImageView":
            return MessageType.IMAGE
        return MessageType.TEXT

    def _detect_is_self(self, message_layout: ET.Element, sender: str) -> bool:
        avatar_container_tail = self._id_tail(self.config.chat_view.avatar_container)
        children = list(message_layout)
        avatar_index: int | None = None
        content_index: int | None = None
        avatar_bounds = ""

        for idx, child in enumerate(children):
            if self._resource_matches(child, avatar_container_tail):
                avatar_index = idx
                avatar_bounds = child.get("bounds") or ""
            if content_index is None and self._contains_content_node(child):
                content_index = idx

        if avatar_index is not None and content_index is not None:
            return avatar_index > content_index

        avatar_x = self._bounds_left_x(avatar_bounds)
        if avatar_x is not None:
            if avatar_x > 800:
                return True
            if avatar_x < 200:
                return False

        return sender in {"我", "自己", "Me"}

    def _contains_content_node(self, node: ET.Element) -> bool:
        cv = self.config.chat_view
        content_resource_ids = {
            self._id_tail(cv.message_text),
            self._id_tail(cv.image_message),
            self._id_tail(cv.file_name),
            "bk_",
        }
        for element in node.iter():
            resource_id = element.get("resource-id") or ""
            if any(self._resource_id_tail(resource_id) == rid for rid in content_resource_ids):
                return True
            if self._resource_id_tail(resource_id).startswith("bk_"):
                return True
        return False

    def _find_emoticon_node(self, node: ET.Element) -> ET.Element | None:
        for element in node.iter():
            tail = self._resource_id_tail(element.get("resource-id") or "")
            if tail.startswith("bk_"):
                return element
        return None

    def _find_first_by_resource(self, node: ET.Element, resource_tail: str) -> ET.Element | None:
        for element in node.iter():
            if self._resource_matches(element, resource_tail):
                return element
        return None

    def _resource_matches(self, node: ET.Element, resource_tail: str) -> bool:
        return self._resource_id_tail(node.get("resource-id") or "") == resource_tail

    def _resource_id_tail(self, resource_id: str) -> str:
        return self._id_tail(resource_id)

    def _id_tail(self, resource_id: str) -> str:
        """Extract tail ID like 'bkl' from a full resource-id."""

        if "/" in resource_id:
            return resource_id.rsplit("/", maxsplit=1)[-1]
        if ":id/" in resource_id:
            return resource_id.rsplit(":id/", maxsplit=1)[-1]
        return resource_id

    def _extract_sender_from_avatar(self, avatar_node: ET.Element) -> str:
        """Extract sender from avatar content-desc like '张三头像' -> '张三'."""

        content_desc = (avatar_node.get("content-desc") or "").strip()
        if content_desc.endswith("头像"):
            return content_desc[:-2] or "未知"
        return content_desc or "未知"

    def _bounds_left_x(self, bounds: str) -> int | None:
        if not bounds:
            return None
        match = re.match(r"\[(?P<x>\d+),\d+\]\[\d+,\d+\]", bounds)
        if not match:
            return None
        return int(match.group("x"))

    def _build_datetime(self, target_day: date, hour_str: str, minute_str: str) -> datetime | None:
        hour = int(hour_str)
        minute = int(minute_str)
        if hour > 23 or minute > 59:
            return None
        return datetime.combine(target_day, datetime.min.time()).replace(hour=hour, minute=minute)

    def _message_hash(self, message: ChatMessage) -> str:
        return f"{message.sender}|{message.content}|{message.message_type.value}"

    def _build_boundary_hashes(self, hashes: list[str]) -> set[str]:
        if self.overlap_window <= 0:
            return set(hashes)

        window = min(self.overlap_window, len(hashes))
        head = deque(hashes[:window])
        tail = deque(hashes[-window:])
        return set(head) | set(tail)

    def _scroll_up(self, device: Any) -> None:
        """Scroll UP to reveal older messages above.

        In WeChat the newest messages sit at the bottom.  To see older messages
        the user drags their finger **downward** (from top toward bottom) which
        scrolls the list **up**.  uiautomator2.swipe(x, y_start, x, y_end)
        moves the finger from y_start to y_end, so y_start < y_end = finger
        moves down = content scrolls up = older messages revealed.
        """
        info = getattr(device, "info", {}) or {}
        width = int(info.get("displayWidth", 1080))
        height = int(info.get("displayHeight", 1920))
        x = width // 2
        y_start = int(height * 0.3)
        y_end = int(height * 0.7)
        device.swipe(x, y_start, x, y_end, duration=0.15)

    def _element_text(self, element: Any) -> str:
        if element is None:
            return ""

        text = getattr(element, "text", None)
        if isinstance(text, str):
            return text

        info = getattr(element, "info", None)
        if isinstance(info, dict):
            value = info.get("text", "")
            if isinstance(value, str):
                return value

        get_text = getattr(element, "get_text", None)
        if callable(get_text):
            value = get_text()
            if isinstance(value, str):
                return value

        return ""


__all__ = ["MessageExtractor"]
