"""Smoke tests to verify all fixtures load correctly."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path


def test_mock_device_fixture(mock_device):
    """Verify mock_device fixture has required methods and attributes."""
    assert hasattr(mock_device, "dump_hierarchy")
    assert callable(mock_device.dump_hierarchy)
    assert mock_device.dump_hierarchy() == "<hierarchy></hierarchy>"
    assert mock_device.info is not None
    assert "currentPackageName" in mock_device.info


def test_mock_llm_client_fixture(mock_llm_client):
    """Verify mock_llm_client fixture has required methods."""
    assert hasattr(mock_llm_client, "chat")
    assert hasattr(mock_llm_client, "check_connection")
    assert callable(mock_llm_client.check_connection)
    assert mock_llm_client.check_connection() is True


def test_sample_messages_fixture(sample_messages):
    """Verify sample_messages fixture contains 10 messages with correct types."""
    assert len(sample_messages) == 10

    # Check message types
    message_types = [msg.message_type for msg in sample_messages]
    assert message_types.count("TEXT") == 7
    assert message_types.count("IMAGE") == 1
    assert message_types.count("VOICE") == 1
    assert message_types.count("SYSTEM") == 1

    # Check senders
    senders = [msg.sender for msg in sample_messages]
    assert "张三" in senders
    assert "李四" in senders
    assert "王五" in senders
    assert "我" in senders
    assert "系统" in senders

    # Check is_self
    self_messages = [msg for msg in sample_messages if msg.is_self]
    assert len(self_messages) == 2  # "我" messages


def test_sample_chat_session_fixture(sample_chat_session):
    """Verify sample_chat_session fixture is properly constructed."""
    assert sample_chat_session.chat_name == "测试群聊"
    assert sample_chat_session.chat_type == "GROUP"
    assert len(sample_chat_session.messages) == 10
    assert sample_chat_session.device_info == "Xiaomi Redmi Note 11 | Android 12"

    # Verify model_dump works
    dumped = sample_chat_session.model_dump()
    assert dumped["chat_name"] == "测试群聊"
    assert len(dumped["messages"]) == 10


def test_tmp_output_dir_fixture(tmp_output_dir):
    """Verify tmp_output_dir fixture is a valid Path."""
    assert isinstance(tmp_output_dir, Path)
    assert tmp_output_dir.exists()
    assert tmp_output_dir.is_dir()


def test_wechat_xml_fixture_valid():
    """Verify wechat_chat_hierarchy.xml is valid XML."""
    fixture_path = Path(__file__).parent / "fixtures" / "wechat_chat_hierarchy.xml"
    assert fixture_path.exists()

    # Parse XML to verify it's well-formed
    tree = ET.parse(fixture_path)
    root = tree.getroot()
    assert root.tag == "hierarchy"

    # Verify it contains expected elements
    textviews = root.findall(".//node[@class='android.widget.TextView']")
    assert len(textviews) > 0

    # Check for chat title
    titles = [tv for tv in textviews if tv.get("text") == "测试群聊"]
    assert len(titles) > 0


def test_wechat_xml_scrolled_fixture_valid():
    """Verify wechat_chat_hierarchy_scrolled.xml is valid XML."""
    fixture_path = Path(__file__).parent / "fixtures" / "wechat_chat_hierarchy_scrolled.xml"
    assert fixture_path.exists()

    # Parse XML to verify it's well-formed
    tree = ET.parse(fixture_path)
    root = tree.getroot()
    assert root.tag == "hierarchy"

    # Verify it contains expected elements
    textviews = root.findall(".//node[@class='android.widget.TextView']")
    assert len(textviews) > 0


def test_wechat_personal_xml_fixture_valid():
    """Verify wechat_personal_chat.xml matches real RecyclerView structure."""
    fixture_path = Path(__file__).parent / "fixtures" / "wechat_personal_chat.xml"
    assert fixture_path.exists()

    tree = ET.parse(fixture_path)
    root = tree.getroot()
    assert root.tag == "hierarchy"

    message_container = root.find('.//node[@resource-id="com.tencent.mm:id/bp0"]')
    assert message_container is not None
    assert message_container.get("class") == "androidx.recyclerview.widget.RecyclerView"


def test_wechat_personal_scrolled_xml_fixture_valid():
    """Verify wechat_personal_chat_scrolled.xml is valid XML."""
    fixture_path = Path(__file__).parent / "fixtures" / "wechat_personal_chat_scrolled.xml"
    assert fixture_path.exists()

    tree = ET.parse(fixture_path)
    root = tree.getroot()
    assert root.tag == "hierarchy"

    timestamps = root.findall('.//node[@resource-id="com.tencent.mm:id/br1"]')
    assert len(timestamps) > 0


def test_sample_llm_response_json_valid():
    """Verify sample_llm_response.json is valid JSON and matches schema."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_llm_response.json"
    assert fixture_path.exists()

    # Parse JSON
    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify schema
    assert "summary" in data
    assert isinstance(data["summary"], str)
    assert len(data["summary"]) > 0
    assert "总结" in data["summary"]


def test_sample_llm_response_json_fixture(sample_llm_response_json):
    """Verify sample_llm_response_json fixture works."""
    assert sample_llm_response_json.exists()

    with open(sample_llm_response_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "summary" in data
    assert data["summary"] == "这是一段总结"
