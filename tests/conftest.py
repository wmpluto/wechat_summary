"""Shared pytest fixtures for wechat_summary tests."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Import real Pydantic models from Task 2
from wechat_summary.models import (
    ChatMessage,
    ChatSession,
    ChatType,
    MessageType,
)


@pytest.fixture
def mock_device():
    """
    Mock uiautomator2 device with dump_hierarchy method.

    Returns a MagicMock that simulates a connected Android device.
    """
    device = MagicMock()
    device.dump_hierarchy = MagicMock(return_value="<hierarchy></hierarchy>")
    device.info = {
        "currentPackageName": "com.tencent.mm",
        "displayHeight": 1920,
        "displayWidth": 1080,
        "displayRotation": 0,
    }
    device.app_list = MagicMock(return_value=["com.tencent.mm", "com.android.settings"])
    device.swipe = MagicMock()
    device.click = MagicMock()
    return device


@pytest.fixture
def mock_llm_client():
    """
    Mock OpenAI-compatible LLM client.

    Returns a MagicMock that simulates an LLM API client.
    """
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = MagicMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="这是一段总结"))])
    )
    client.check_connection = MagicMock(return_value=True)
    return client


@pytest.fixture
def sample_messages():
    """
    Generate 10 sample ChatMessage objects with mixed types.

    Returns:
        list[ChatMessage]: 7 text, 1 image, 1 voice, 1 system message
    """
    base_time = datetime(2026, 3, 17, 10, 0, 0)
    messages = [
        ChatMessage(
            sender="张三",
            content="早上好，大家",
            timestamp=base_time,
            message_type=MessageType.TEXT,
            is_self=False,
        ),
        ChatMessage(
            sender="李四",
            content="早上好！",
            timestamp=base_time + timedelta(minutes=1),
            message_type=MessageType.TEXT,
            is_self=False,
        ),
        ChatMessage(
            sender="王五",
            content="今天天气真好",
            timestamp=base_time + timedelta(minutes=2),
            message_type=MessageType.TEXT,
            is_self=False,
        ),
        ChatMessage(
            sender="我",
            content="[图片]",
            timestamp=base_time + timedelta(minutes=3),
            message_type=MessageType.IMAGE,
            is_self=True,
        ),
        ChatMessage(
            sender="张三",
            content="[语音]",
            timestamp=base_time + timedelta(minutes=4),
            message_type=MessageType.VOICE,
            is_self=False,
        ),
        ChatMessage(
            sender="李四",
            content="明天开会讨论项目进度",
            timestamp=base_time + timedelta(minutes=5),
            message_type=MessageType.TEXT,
            is_self=False,
        ),
        ChatMessage(
            sender="王五",
            content="好的，我会准时参加",
            timestamp=base_time + timedelta(minutes=6),
            message_type=MessageType.TEXT,
            is_self=False,
        ),
        ChatMessage(
            sender="系统",
            content="张三 邀请了 赵六 加入群聊",
            timestamp=base_time + timedelta(minutes=7),
            message_type=MessageType.SYSTEM,
            is_self=False,
        ),
        ChatMessage(
            sender="我",
            content="欢迎加入！",
            timestamp=base_time + timedelta(minutes=8),
            message_type=MessageType.TEXT,
            is_self=True,
        ),
        ChatMessage(
            sender="赵六",
            content="谢谢邀请！",
            timestamp=base_time + timedelta(minutes=9),
            message_type=MessageType.TEXT,
            is_self=False,
        ),
    ]
    return messages


@pytest.fixture
def sample_chat_session(sample_messages):
    """
    Create a sample ChatSession with test messages.

    Returns:
        ChatSession: A chat session with chat_name="测试群聊"
    """
    return ChatSession(
        chat_name="测试群聊",
        chat_type=ChatType.GROUP,
        messages=sample_messages,
        extracted_at=datetime(2026, 3, 17, 14, 30, 0),
        device_info="Xiaomi Redmi Note 11 | Android 12",
    )


@pytest.fixture
def tmp_output_dir(tmp_path):
    """
    Wrapper around pytest's tmp_path for output directory.

    Returns:
        Path: A temporary directory for test output files
    """
    return tmp_path


@pytest.fixture
def sample_llm_response_json(tmp_path):
    """
    Create a sample LLM response JSON file matching SummaryResult schema.

    Returns:
        Path: Path to the JSON file
    """
    response = {"summary": "这是一段总结"}
    response_file = tmp_path / "sample_llm_response.json"
    with open(response_file, "w", encoding="utf-8") as f:
        json.dump(response, f, ensure_ascii=False, indent=2)
    return response_file


@pytest.fixture
def message_list_dump_xml_path() -> Path:
    """Path to real message-list XML dump in project root."""

    path = Path(__file__).resolve().parents[1] / "wechat_dump_消息列表界面.xml"
    if not path.exists():
        pytest.skip("Message list dump not found")
    return path


@pytest.fixture
def personal_chat_dump_xml_path() -> Path:
    """Path to real personal-chat XML dump in project root."""

    path = Path(__file__).resolve().parents[1] / "wechat_dump_个人对话灭面.xml"
    if not path.exists():
        pytest.skip("Personal chat dump not found")
    return path


@pytest.fixture
def message_list_dump_xml_text(message_list_dump_xml_path: Path) -> str:
    """Real message-list XML dump content."""

    return message_list_dump_xml_path.read_text(encoding="utf-8")


@pytest.fixture
def personal_chat_dump_xml_text(personal_chat_dump_xml_path: Path) -> str:
    """Real personal-chat XML dump content."""

    return personal_chat_dump_xml_path.read_text(encoding="utf-8")


@pytest.fixture
def message_list_xml() -> str:
    """Real message-list dump XML (skip if unavailable)."""

    path = Path(__file__).parent.parent / "wechat_dump_消息列表界面.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    pytest.skip("Message list dump not found")


@pytest.fixture
def folded_chat_xml() -> str:
    """Real folded-chat dump XML (skip if unavailable)."""

    path = Path(__file__).parent.parent / "wechat_dump_折叠的聊天.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    pytest.skip("Folded chat dump not found")
