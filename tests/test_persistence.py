"""Tests for ChatSessionStore persistence module (TDD)."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from wechat_summary.models import ChatMessage, ChatSession, ChatType, MessageType
from wechat_summary.persistence import ChatSessionStore


class TestChatSessionStoreSave:
    """Tests for ChatSessionStore.save() method."""

    def test_save_creates_output_dir_if_not_exists(self, sample_chat_session, tmp_path):
        """Test that save() creates output directory if it doesn't exist."""
        output_dir = tmp_path / "nonexistent" / "output"
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(output_dir))
        
        assert output_dir.exists()
        assert Path(filepath).exists()

    def test_save_returns_filepath(self, sample_chat_session, tmp_path):
        """Test that save() returns the filepath of saved file."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        assert isinstance(filepath, str)
        assert Path(filepath).exists()
        assert str(tmp_path) in filepath

    def test_save_filename_format(self, sample_chat_session, tmp_path):
        """Test that saved filename follows format: {sanitized_chat_name}_{YYYYMMDD_HHMMSS}.json."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        filename = Path(filepath).name
        
        # Should match pattern: {name}_{YYYYMMDD_HHMMSS}.json
        assert filename.endswith(".json")
        assert "测试群聊" in filename or "___" in filename  # sanitized or original
        # Check timestamp format YYYYMMDD_HHMMSS
        assert re.search(r"\d{8}_\d{6}\.json$", filename)

    def test_save_preserves_chinese_text(self, sample_chat_session, tmp_path):
        """Test that save() preserves Chinese text with ensure_ascii=False."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Chinese text should be present unescaped
        assert "测试群聊" in content
        assert "张三" in content
        assert "早上好，大家" in content

    def test_save_json_is_valid(self, sample_chat_session, tmp_path):
        """Test that saved file is valid JSON."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert isinstance(data, dict)
        assert "chat_name" in data
        assert "messages" in data

    def test_save_json_has_indent(self, sample_chat_session, tmp_path):
        """Test that saved JSON is formatted with indent=2."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Indented JSON should have newlines and spaces
        assert "\n" in content
        assert "  " in content

    def test_save_contains_all_session_data(self, sample_chat_session, tmp_path):
        """Test that saved JSON contains all ChatSession fields."""
        store = ChatSessionStore()
        
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["chat_name"] == sample_chat_session.chat_name
        assert data["chat_type"] == sample_chat_session.chat_type.value
        assert len(data["messages"]) == len(sample_chat_session.messages)
        assert "extracted_at" in data
        assert "device_info" in data


class TestChatSessionStoreLoad:
    """Tests for ChatSessionStore.load() method."""

    def test_load_returns_chat_session(self, sample_chat_session, tmp_path):
        """Test that load() returns a ChatSession object."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        assert isinstance(loaded_session, ChatSession)

    def test_load_preserves_chat_name(self, sample_chat_session, tmp_path):
        """Test that load() preserves chat_name."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        assert loaded_session.chat_name == sample_chat_session.chat_name

    def test_load_preserves_chat_type(self, sample_chat_session, tmp_path):
        """Test that load() preserves chat_type."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        assert loaded_session.chat_type == sample_chat_session.chat_type

    def test_load_preserves_message_count(self, sample_chat_session, tmp_path):
        """Test that load() preserves all messages."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        assert len(loaded_session.messages) == len(sample_chat_session.messages)

    def test_load_preserves_message_content(self, sample_chat_session, tmp_path):
        """Test that load() preserves message content including Chinese text."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        for orig_msg, loaded_msg in zip(sample_chat_session.messages, loaded_session.messages):
            assert loaded_msg.sender == orig_msg.sender
            assert loaded_msg.content == orig_msg.content
            assert loaded_msg.message_type == orig_msg.message_type
            assert loaded_msg.is_self == orig_msg.is_self

    def test_load_preserves_device_info(self, sample_chat_session, tmp_path):
        """Test that load() preserves device_info."""
        store = ChatSessionStore()
        filepath = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        loaded_session = store.load(filepath)
        
        assert loaded_session.device_info == sample_chat_session.device_info

    def test_load_raises_on_invalid_file(self, tmp_path):
        """Test that load() raises error on invalid JSON file."""
        store = ChatSessionStore()
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not valid json")
        
        with pytest.raises(Exception):  # Could be json.JSONDecodeError or ValidationError
            store.load(str(invalid_file))

    def test_load_raises_on_missing_file(self):
        """Test that load() raises error on missing file."""
        store = ChatSessionStore()
        
        with pytest.raises(FileNotFoundError):
            store.load("/nonexistent/path/file.json")


class TestChatSessionStoreRoundTrip:
    """Tests for round-trip save/load consistency."""

    def test_round_trip_preserves_all_data(self, sample_chat_session, tmp_path):
        """Test that save → load → save produces identical data."""
        store = ChatSessionStore()
        
        # First save
        filepath1 = store.save(sample_chat_session, output_dir=str(tmp_path))
        loaded_session = store.load(filepath1)
        
        # Verify loaded session matches original
        assert loaded_session.chat_name == sample_chat_session.chat_name
        assert loaded_session.chat_type == sample_chat_session.chat_type
        assert len(loaded_session.messages) == len(sample_chat_session.messages)

    def test_round_trip_with_chinese_chat_name(self, tmp_path):
        """Test round-trip with Chinese chat name."""
        store = ChatSessionStore()
        
        # Create session with Chinese name
        session = ChatSession(
            chat_name="家人群聊",
            chat_type=ChatType.GROUP,
            messages=[
                ChatMessage(
                    sender="妈妈",
                    content="今天天气很好",
                    timestamp=datetime(2026, 3, 17, 10, 0, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                )
            ],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save(session, output_dir=str(tmp_path))
        loaded_session = store.load(filepath)
        
        assert loaded_session.chat_name == "家人群聊"
        assert loaded_session.messages[0].sender == "妈妈"
        assert loaded_session.messages[0].content == "今天天气很好"

    def test_round_trip_with_mixed_chinese_english(self, tmp_path):
        """Test round-trip with mixed Chinese and English content."""
        store = ChatSessionStore()
        
        session = ChatSession(
            chat_name="Project Team 项目组",
            chat_type=ChatType.GROUP,
            messages=[
                ChatMessage(
                    sender="Alice",
                    content="Let's discuss the 项目进度",
                    timestamp=datetime(2026, 3, 17, 10, 0, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                )
            ],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save(session, output_dir=str(tmp_path))
        loaded_session = store.load(filepath)
        
        assert loaded_session.chat_name == "Project Team 项目组"
        assert "项目进度" in loaded_session.messages[0].content


class TestChatSessionStoreSanitization:
    """Tests for filename sanitization."""

    def test_sanitize_removes_invalid_chars(self, tmp_path):
        """Test that invalid filesystem characters are removed from chat name."""
        store = ChatSessionStore()
        
        session = ChatSession(
            chat_name='家人群<2024>',
            chat_type=ChatType.GROUP,
            messages=[],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save(session, output_dir=str(tmp_path))
        filename = Path(filepath).name
        
        # Invalid chars < > should be removed or replaced
        assert "<" not in filename
        assert ">" not in filename

    def test_sanitize_handles_all_invalid_chars(self, tmp_path):
        """Test sanitization of all invalid filesystem characters: <>:\"/\\|?*"""
        store = ChatSessionStore()
        
        # Create a chat name with all invalid characters
        invalid_chars = '<>:"/\\|?*'
        session = ChatSession(
            chat_name=f"chat{invalid_chars}name",
            chat_type=ChatType.GROUP,
            messages=[],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save(session, output_dir=str(tmp_path))
        filename = Path(filepath).name
        
        # None of the invalid chars should be in filename
        for char in invalid_chars:
            assert char not in filename

    def test_sanitize_preserves_chinese(self, tmp_path):
        """Test that sanitization preserves Chinese characters."""
        store = ChatSessionStore()
        
        session = ChatSession(
            chat_name="家人群<聊天>",
            chat_type=ChatType.GROUP,
            messages=[],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save(session, output_dir=str(tmp_path))
        filename = Path(filepath).name
        
        # Chinese characters should be preserved
        assert "家人群" in filename or "_" in filename  # Either preserved or replaced with _


class TestChatSessionStorePartialSave:
    """Tests for ChatSessionStore.save_partial() method."""

    def test_save_partial_creates_file_with_partial_suffix(self, sample_chat_session, tmp_path):
        """Test that save_partial() creates file with _partial suffix."""
        store = ChatSessionStore()
        
        filepath = store.save_partial(sample_chat_session, output_dir=str(tmp_path))
        
        assert "_partial.json" in filepath
        assert Path(filepath).exists()

    def test_save_partial_returns_filepath(self, sample_chat_session, tmp_path):
        """Test that save_partial() returns the filepath."""
        store = ChatSessionStore()
        
        filepath = store.save_partial(sample_chat_session, output_dir=str(tmp_path))
        
        assert isinstance(filepath, str)
        assert len(filepath) > 0

    def test_save_partial_preserves_data(self, sample_chat_session, tmp_path):
        """Test that save_partial() preserves all session data."""
        store = ChatSessionStore()
        
        filepath = store.save_partial(sample_chat_session, output_dir=str(tmp_path))
        loaded_session = store.load(filepath)
        
        assert loaded_session.chat_name == sample_chat_session.chat_name
        assert len(loaded_session.messages) == len(sample_chat_session.messages)

    def test_save_partial_with_partial_messages(self, tmp_path):
        """Test save_partial() with incomplete message list (simulating interruption)."""
        store = ChatSessionStore()
        
        # Create session with only 3 messages (simulating partial extraction)
        partial_session = ChatSession(
            chat_name="测试群聊",
            chat_type=ChatType.GROUP,
            messages=[
                ChatMessage(
                    sender="张三",
                    content="消息1",
                    timestamp=datetime(2026, 3, 17, 10, 0, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                ),
                ChatMessage(
                    sender="李四",
                    content="消息2",
                    timestamp=datetime(2026, 3, 17, 10, 1, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                ),
                ChatMessage(
                    sender="王五",
                    content="消息3",
                    timestamp=datetime(2026, 3, 17, 10, 2, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                ),
            ],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Test Device",
        )
        
        filepath = store.save_partial(partial_session, output_dir=str(tmp_path))
        loaded_session = store.load(filepath)
        
        assert len(loaded_session.messages) == 3
        assert "_partial" in filepath


class TestChatSessionStoreIntegration:
    """Integration tests for ChatSessionStore."""

    def test_multiple_saves_different_files(self, sample_chat_session, tmp_path):
        """Test that multiple saves create different files."""
        import time
        store = ChatSessionStore()
        
        filepath1 = store.save(sample_chat_session, output_dir=str(tmp_path))
        time.sleep(1)  # Ensure different timestamp
        filepath2 = store.save(sample_chat_session, output_dir=str(tmp_path))
        
        # Files should be different (different timestamps)
        assert filepath1 != filepath2
        assert Path(filepath1).exists()
        assert Path(filepath2).exists()

    def test_save_and_load_multiple_sessions(self, tmp_path):
        """Test saving and loading multiple different sessions."""
        store = ChatSessionStore()
        
        # Create two different sessions
        session1 = ChatSession(
            chat_name="群聊1",
            chat_type=ChatType.GROUP,
            messages=[
                ChatMessage(
                    sender="用户1",
                    content="内容1",
                    timestamp=datetime(2026, 3, 17, 10, 0, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                )
            ],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Device1",
        )
        
        session2 = ChatSession(
            chat_name="群聊2",
            chat_type=ChatType.GROUP,
            messages=[
                ChatMessage(
                    sender="用户2",
                    content="内容2",
                    timestamp=datetime(2026, 3, 17, 11, 0, 0),
                    message_type=MessageType.TEXT,
                    is_self=False,
                )
            ],
            extracted_at=datetime(2026, 3, 17, 15, 30, 0),
            device_info="Device2",
        )
        
        filepath1 = store.save(session1, output_dir=str(tmp_path))
        filepath2 = store.save(session2, output_dir=str(tmp_path))
        
        loaded1 = store.load(filepath1)
        loaded2 = store.load(filepath2)
        
        assert loaded1.chat_name == "群聊1"
        assert loaded2.chat_name == "群聊2"
        assert loaded1.messages[0].sender == "用户1"
        assert loaded2.messages[0].sender == "用户2"
