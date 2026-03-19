"""Tests for WeChat message extraction and scroll deduplication (TDD RED phase)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

from wechat_summary.extractor import MessageExtractor
from wechat_summary.models import ChatMessage, ChatType, MessageType


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class FakeElement:
    text: str


class FakeDevice:
    def __init__(self):
        self.swipes: list[tuple[int, int, int, int, float]] = []
        self.dump_calls = 0

    def dump_hierarchy(self) -> str:
        self.dump_calls += 1
        return "<hierarchy/>"

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.15):
        self.swipes.append((x1, y1, x2, y2, duration))


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _build_messages(start_idx: int, count: int, base_time: datetime) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for i in range(count):
        idx = start_idx + i
        messages.append(
            ChatMessage(
                sender=f"用户{idx % 3}",
                content=f"消息-{idx}",
                timestamp=base_time + timedelta(minutes=idx),
                message_type=MessageType.TEXT,
                is_self=idx % 2 == 0,
            )
        )
    return messages


class TestMaxScrollsDefault:
    def test_default_max_scrolls_is_unlimited(self):
        extractor = MessageExtractor()
        assert extractor.max_scrolls == 0xFFFFFFFF

    def test_custom_max_scrolls_is_respected(self):
        extractor = MessageExtractor(max_scrolls=100)
        assert extractor.max_scrolls == 100


class TestExtractVisibleMessages:
    def test_parses_visible_messages_from_fixture_with_correct_types_and_order(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()
        fixture_xml = _read_fixture("wechat_personal_chat.xml")

        calls: list[FakeDevice] = []

        def fake_stable_dump(arg_device):
            calls.append(arg_device)
            return fixture_xml

        monkeypatch.setattr("wechat_summary.extractor.stable_dump", fake_stable_dump)

        messages = extractor.extract_visible_messages(device)

        assert len(messages) == 7
        assert calls == [device]

        assert messages[0].sender == "张三"
        assert messages[0].content == "好的，明白"
        assert messages[0].message_type == MessageType.TEXT
        assert messages[0].is_self is False

        assert messages[1].sender == "李四"
        assert messages[1].content == "会议记录我整理好了"
        assert messages[1].is_self is True

        assert messages[2].content == "[图片]"
        assert messages[2].message_type == MessageType.IMAGE
        assert messages[2].is_self is False

        assert messages[3].content == "[文件] filename.sal"
        assert messages[3].message_type == MessageType.FILE
        assert messages[3].is_self is True

        ordered = [msg.timestamp or datetime.min for msg in messages]
        assert ordered == sorted(ordered)

    def test_parses_scrolled_fixture_message_count(self, monkeypatch):
        extractor = MessageExtractor()
        fixture_xml = _read_fixture("wechat_personal_chat_scrolled.xml")

        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: fixture_xml)
        messages = extractor.extract_visible_messages(FakeDevice())

        assert len(messages) == 5

    def test_extracts_sender_from_avatar_content_desc(self):
        extractor = MessageExtractor()
        avatar = ET.fromstring(
            '<node resource-id="com.tencent.mm:id/bk1" content-desc="张三头像"/>'
        )

        sender = extractor._extract_sender_from_avatar(avatar)  # noqa: SLF001

        assert sender == "张三"

    def test_timestamp_nodes_apply_to_following_messages(self, monkeypatch):
        extractor = MessageExtractor()
        fixture_xml = _read_fixture("wechat_personal_chat.xml")
        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: fixture_xml)

        messages = extractor.extract_visible_messages(FakeDevice())

        assert messages[0].timestamp is not None
        assert messages[1].timestamp == messages[0].timestamp
        assert messages[4].timestamp is not None
        assert messages[4].timestamp.hour == 10
        assert messages[4].timestamp.minute == 50

    def test_detects_self_message_by_avatar_position(self, monkeypatch):
        extractor = MessageExtractor()
        fixture_xml = _read_fixture("wechat_personal_chat.xml")
        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: fixture_xml)

        messages = extractor.extract_visible_messages(FakeDevice())
        by_content = {msg.content: msg for msg in messages}

        assert by_content["会议记录我整理好了"].is_self is True
        assert by_content["好的，明白"].is_self is False

    def test_detects_image_message_placeholder(self, monkeypatch):
        extractor = MessageExtractor()
        fixture_xml = _read_fixture("wechat_personal_chat.xml")
        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: fixture_xml)

        messages = extractor.extract_visible_messages(FakeDevice())

        image_messages = [msg for msg in messages if msg.message_type == MessageType.IMAGE]
        assert len(image_messages) == 1
        assert image_messages[0].content == "[图片]"


class TestDetectChatInfo:
    def test_detect_chat_info_group(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()

        monkeypatch.setattr(
            "wechat_summary.extractor.find_element",
            lambda d, selector, **kwargs: FakeElement(text="测试群聊"),
        )
        monkeypatch.setattr(
            "wechat_summary.extractor.find_all_elements",
            lambda d, selector, **kwargs: [FakeElement(text="张三"), FakeElement(text="李四")],
        )

        chat_name, chat_type = extractor.detect_chat_info(device)

        assert chat_name == "测试群聊"
        assert chat_type == ChatType.GROUP

    def test_detect_chat_info_private(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()

        monkeypatch.setattr(
            "wechat_summary.extractor.find_element",
            lambda d, selector, **kwargs: FakeElement(text="张三"),
        )
        monkeypatch.setattr(
            "wechat_summary.extractor.find_all_elements",
            lambda d, selector, **kwargs: [FakeElement(text="张三")],
        )

        chat_name, chat_type = extractor.detect_chat_info(device)

        assert chat_name == "张三"
        assert chat_type == ChatType.PRIVATE

    def test_detect_chat_info_falls_back_to_unknown_when_title_not_accessible(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()
        fixture_xml = _read_fixture("wechat_personal_chat.xml")

        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: fixture_xml)
        monkeypatch.setattr(
            "wechat_summary.extractor.find_element",
            lambda d, selector, **kwargs: FakeElement(text=""),
        )
        monkeypatch.setattr(
            "wechat_summary.extractor.find_all_elements",
            lambda d, selector, **kwargs: [FakeElement(text="")],
        )

        chat_name, chat_type = extractor.detect_chat_info(device)

        assert chat_name == "未知会话"
        assert chat_type == ChatType.PRIVATE


class TestScrollAndExtract:
    def test_deduplication_from_real_fixtures_with_overlap(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()
        page_newer = _read_fixture("wechat_personal_chat.xml")
        page_older = _read_fixture("wechat_personal_chat_scrolled.xml")
        pages = [page_newer, page_older, page_older]

        monkeypatch.setattr("wechat_summary.extractor.stable_dump", lambda _: pages.pop(0))
        monkeypatch.setattr("wechat_summary.extractor.random.uniform", lambda a, b: 1.0)
        monkeypatch.setattr("wechat_summary.extractor.time.sleep", lambda _: None)

        # Use a date far in the past so no messages are filtered by since_date
        messages = extractor.scroll_and_extract(device, since_date=date(2020, 1, 1))

        assert len(messages) == 9

    def test_scroll_stops_when_message_older_than_since_date(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()

        page_new = [
            ChatMessage(
                sender="张三",
                content="最新消息",
                timestamp=datetime(2026, 3, 17, 10, 0, 0),
                message_type=MessageType.TEXT,
                is_self=False,
            )
        ]
        page_old = [
            ChatMessage(
                sender="李四",
                content="历史消息",
                timestamp=datetime(2026, 3, 14, 9, 0, 0),
                message_type=MessageType.TEXT,
                is_self=False,
            )
        ]

        pages = [page_new, page_old]
        monkeypatch.setattr(extractor, "extract_visible_messages", lambda _: pages.pop(0))
        monkeypatch.setattr("wechat_summary.extractor.random.uniform", lambda a, b: 0.8)
        monkeypatch.setattr("wechat_summary.extractor.time.sleep", lambda _: None)

        result = extractor.scroll_and_extract(device, since_date=date(2026, 3, 15))

        assert len(device.swipes) == 1
        assert all(
            msg.timestamp is not None and msg.timestamp.date() >= date(2026, 3, 15)
            for msg in result
        )

    def test_scroll_uses_human_like_delay(self, monkeypatch):
        extractor = MessageExtractor()
        device = FakeDevice()

        page = [
            ChatMessage(
                sender="张三",
                content="一条消息",
                timestamp=datetime(2026, 3, 17, 10, 0, 0),
                message_type=MessageType.TEXT,
                is_self=False,
            )
        ]
        pages = [page, page]

        sleeps: list[float] = []
        monkeypatch.setattr(extractor, "extract_visible_messages", lambda _: pages.pop(0))
        monkeypatch.setattr("wechat_summary.extractor.random.uniform", lambda a, b: 1.23)
        monkeypatch.setattr(
            "wechat_summary.extractor.time.sleep",
            lambda value: sleeps.append(value),
        )

        extractor.scroll_and_extract(device, since_date=date(2026, 3, 17))

        assert sleeps == [1.23]
