"""Tests for Pydantic data models (TDD RED phase)."""

import json
from datetime import datetime, date
from pydantic import ValidationError
import pytest

from wechat_summary.models import (
    MessageType,
    ChatType,
    ChatMessage,
    ChatSession,
    SummaryResult,
    ExtractionConfig,
    LLMConfig,
)


class TestMessageTypeEnum:
    """Test MessageType enum."""

    def test_message_type_values(self):
        """Test all MessageType enum values exist."""
        assert MessageType.TEXT.value == "TEXT"
        assert MessageType.IMAGE.value == "IMAGE"
        assert MessageType.VOICE.value == "VOICE"
        assert MessageType.VIDEO.value == "VIDEO"
        assert MessageType.FILE.value == "FILE"
        assert MessageType.SYSTEM.value == "SYSTEM"

    def test_message_type_count(self):
        """Test MessageType has exactly 6 values."""
        assert len(MessageType) == 6


class TestChatTypeEnum:
    """Test ChatType enum."""

    def test_chat_type_values(self):
        """Test all ChatType enum values exist."""
        assert ChatType.PRIVATE.value == "PRIVATE"
        assert ChatType.GROUP.value == "GROUP"

    def test_chat_type_count(self):
        """Test ChatType has exactly 2 values."""
        assert len(ChatType) == 2


class TestChatMessage:
    """Test ChatMessage model."""

    def test_chat_message_basic(self):
        """Test basic ChatMessage creation."""
        msg = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        assert msg.sender == "张三"
        assert msg.content == "明天开会"
        assert msg.message_type == MessageType.TEXT
        assert msg.is_self is False

    def test_chat_message_with_timestamp(self):
        """Test ChatMessage with optional timestamp."""
        ts = datetime(2026, 3, 17, 14, 30, 0)
        msg = ChatMessage(
            sender="李四",
            content="好的",
            timestamp=ts,
            message_type=MessageType.TEXT,
            is_self=True,
        )
        assert msg.timestamp == ts

    def test_chat_message_without_timestamp(self):
        """Test ChatMessage without timestamp (optional)."""
        msg = ChatMessage(
            sender="王五",
            content="收到",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        assert msg.timestamp is None

    def test_chat_message_image_type(self):
        """Test ChatMessage with IMAGE type."""
        msg = ChatMessage(
            sender="张三",
            content="[图片]",
            message_type=MessageType.IMAGE,
            is_self=False,
        )
        assert msg.message_type == MessageType.IMAGE

    def test_chat_message_voice_type(self):
        """Test ChatMessage with VOICE type."""
        msg = ChatMessage(
            sender="李四",
            content="[语音]",
            message_type=MessageType.VOICE,
            is_self=True,
        )
        assert msg.message_type == MessageType.VOICE

    def test_chat_message_system_type(self):
        """Test ChatMessage with SYSTEM type."""
        msg = ChatMessage(
            sender="system",
            content="张三加入了群聊",
            message_type=MessageType.SYSTEM,
            is_self=False,
        )
        assert msg.message_type == MessageType.SYSTEM

    def test_chat_message_validation_missing_sender(self):
        """Test ChatMessage validation fails without sender."""
        with pytest.raises(ValidationError):
            ChatMessage(
                content="test",
                message_type=MessageType.TEXT,
                is_self=False,
            )

    def test_chat_message_validation_missing_content(self):
        """Test ChatMessage validation fails without content."""
        with pytest.raises(ValidationError):
            ChatMessage(
                sender="张三",
                message_type=MessageType.TEXT,
                is_self=False,
            )

    def test_chat_message_validation_missing_message_type(self):
        """Test ChatMessage validation fails without message_type."""
        with pytest.raises(ValidationError):
            ChatMessage(
                sender="张三",
                content="test",
                is_self=False,
            )

    def test_chat_message_validation_missing_is_self(self):
        """Test ChatMessage validation fails without is_self."""
        with pytest.raises(ValidationError):
            ChatMessage(
                sender="张三",
                content="test",
                message_type=MessageType.TEXT,
            )

    def test_chat_message_validation_invalid_sender_type(self):
        """Test ChatMessage validation fails with non-string sender."""
        with pytest.raises(ValidationError):
            ChatMessage(
                sender=123,
                content="test",
                message_type=MessageType.TEXT,
                is_self=False,
            )

    def test_chat_message_validation_invalid_is_self_type(self):
        """Test ChatMessage coerces string to bool (Pydantic v2 behavior)."""
        # Pydantic v2 coerces types by default, so "yes" becomes True
        msg = ChatMessage(
            sender="张三",
            content="test",
            message_type=MessageType.TEXT,
            is_self="yes",
        )
        assert msg.is_self is True

    def test_chat_message_json_serialization(self):
        """Test ChatMessage serializes to JSON."""
        msg = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        json_str = msg.model_dump_json(ensure_ascii=False)
        assert isinstance(json_str, str)
        assert "张三" in json_str
        assert "明天开会" in json_str

    def test_chat_message_json_deserialization(self):
        """Test ChatMessage deserializes from JSON."""
        json_str = '{"sender":"张三","content":"明天开会","message_type":"TEXT","is_self":false}'
        msg = ChatMessage.model_validate_json(json_str)
        assert msg.sender == "张三"
        assert msg.content == "明天开会"
        assert msg.message_type == MessageType.TEXT
        assert msg.is_self is False

    def test_chat_message_round_trip(self):
        """Test ChatMessage round-trip: create -> dump -> validate -> compare."""
        original = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        json_str = original.model_dump_json(ensure_ascii=False)
        restored = ChatMessage.model_validate_json(json_str)
        assert restored.sender == original.sender
        assert restored.content == original.content
        assert restored.message_type == original.message_type
        assert restored.is_self == original.is_self


class TestChatSession:
    """Test ChatSession model."""

    def test_chat_session_basic(self):
        """Test basic ChatSession creation."""
        msg = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        session = ChatSession(
            chat_name="测试群聊",
            chat_type=ChatType.GROUP,
            messages=[msg],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        assert session.chat_name == "测试群聊"
        assert session.chat_type == ChatType.GROUP
        assert len(session.messages) == 1
        assert session.device_info == "Pixel 6 Android 13"

    def test_chat_session_multiple_messages(self):
        """Test ChatSession with multiple messages."""
        messages = [
            ChatMessage(
                sender="张三",
                content="明天开会",
                message_type=MessageType.TEXT,
                is_self=False,
            ),
            ChatMessage(
                sender="李四",
                content="好的",
                message_type=MessageType.TEXT,
                is_self=True,
            ),
            ChatMessage(
                sender="王五",
                content="[图片]",
                message_type=MessageType.IMAGE,
                is_self=False,
            ),
        ]
        session = ChatSession(
            chat_name="测试群聊",
            chat_type=ChatType.GROUP,
            messages=messages,
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        assert len(session.messages) == 3

    def test_chat_session_private_chat(self):
        """Test ChatSession with PRIVATE chat type."""
        msg = ChatMessage(
            sender="张三",
            content="你好",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        session = ChatSession(
            chat_name="张三",
            chat_type=ChatType.PRIVATE,
            messages=[msg],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        assert session.chat_type == ChatType.PRIVATE

    def test_chat_session_empty_messages(self):
        """Test ChatSession with empty messages list."""
        session = ChatSession(
            chat_name="空群聊",
            chat_type=ChatType.GROUP,
            messages=[],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        assert len(session.messages) == 0

    def test_chat_session_validation_missing_chat_name(self):
        """Test ChatSession validation fails without chat_name."""
        with pytest.raises(ValidationError):
            ChatSession(
                chat_type=ChatType.GROUP,
                messages=[],
                extracted_at=datetime(2026, 3, 17, 14, 30, 0),
                device_info="Pixel 6 Android 13",
            )

    def test_chat_session_validation_missing_chat_type(self):
        """Test ChatSession validation fails without chat_type."""
        with pytest.raises(ValidationError):
            ChatSession(
                chat_name="测试群聊",
                messages=[],
                extracted_at=datetime(2026, 3, 17, 14, 30, 0),
                device_info="Pixel 6 Android 13",
            )

    def test_chat_session_validation_missing_messages(self):
        """Test ChatSession validation fails without messages."""
        with pytest.raises(ValidationError):
            ChatSession(
                chat_name="测试群聊",
                chat_type=ChatType.GROUP,
                extracted_at=datetime(2026, 3, 17, 14, 30, 0),
                device_info="Pixel 6 Android 13",
            )

    def test_chat_session_validation_missing_extracted_at(self):
        """Test ChatSession validation fails without extracted_at."""
        with pytest.raises(ValidationError):
            ChatSession(
                chat_name="测试群聊",
                chat_type=ChatType.GROUP,
                messages=[],
                device_info="Pixel 6 Android 13",
            )

    def test_chat_session_validation_missing_device_info(self):
        """Test ChatSession validation fails without device_info."""
        with pytest.raises(ValidationError):
            ChatSession(
                chat_name="测试群聊",
                chat_type=ChatType.GROUP,
                messages=[],
                extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            )

    def test_chat_session_json_serialization(self):
        """Test ChatSession serializes to JSON."""
        msg = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        session = ChatSession(
            chat_name="测试群聊",
            chat_type=ChatType.GROUP,
            messages=[msg],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        json_str = session.model_dump_json(ensure_ascii=False)
        assert isinstance(json_str, str)
        assert "测试群聊" in json_str
        assert "张三" in json_str

    def test_chat_session_json_deserialization(self):
        """Test ChatSession deserializes from JSON."""
        json_str = """{
            "chat_name": "测试群聊",
            "chat_type": "GROUP",
            "messages": [
                {
                    "sender": "张三",
                    "content": "明天开会",
                    "message_type": "TEXT",
                    "is_self": false
                }
            ],
            "extracted_at": "2026-03-17T14:30:00",
            "device_info": "Pixel 6 Android 13"
        }"""
        session = ChatSession.model_validate_json(json_str)
        assert session.chat_name == "测试群聊"
        assert session.chat_type == ChatType.GROUP
        assert len(session.messages) == 1

    def test_chat_session_round_trip(self):
        """Test ChatSession round-trip: create -> dump -> validate -> compare."""
        msg = ChatMessage(
            sender="张三",
            content="明天开会",
            message_type=MessageType.TEXT,
            is_self=False,
        )
        original = ChatSession(
            chat_name="测试群聊",
            chat_type=ChatType.GROUP,
            messages=[msg],
            extracted_at=datetime(2026, 3, 17, 14, 30, 0),
            device_info="Pixel 6 Android 13",
        )
        json_str = original.model_dump_json(ensure_ascii=False)
        restored = ChatSession.model_validate_json(json_str)
        assert restored.chat_name == original.chat_name
        assert restored.chat_type == original.chat_type
        assert len(restored.messages) == len(original.messages)
        assert restored.device_info == original.device_info


class TestSummaryResult:
    """Test SummaryResult model."""

    def test_summary_result_basic(self):
        """Test basic SummaryResult creation."""
        result = SummaryResult(summary="这是一段总结")
        assert result.summary == "这是一段总结"

    def test_summary_result_empty_summary(self):
        """Test SummaryResult with empty summary."""
        result = SummaryResult(summary="")
        assert result.summary == ""

    def test_summary_result_long_summary(self):
        """Test SummaryResult with long summary."""
        long_text = "这是一段很长的总结。" * 100
        result = SummaryResult(summary=long_text)
        assert result.summary == long_text

    def test_summary_result_validation_missing_summary(self):
        """Test SummaryResult validation fails without summary."""
        with pytest.raises(ValidationError):
            SummaryResult()

    def test_summary_result_validation_invalid_summary_type(self):
        """Test SummaryResult validation fails with non-string summary."""
        with pytest.raises(ValidationError):
            SummaryResult(summary=123)

    def test_summary_result_json_serialization(self):
        """Test SummaryResult serializes to JSON."""
        result = SummaryResult(summary="这是一段总结")
        json_str = result.model_dump_json(ensure_ascii=False)
        assert isinstance(json_str, str)
        assert "这是一段总结" in json_str

    def test_summary_result_json_deserialization(self):
        """Test SummaryResult deserializes from JSON."""
        json_str = '{"summary":"这是一段总结"}'
        result = SummaryResult.model_validate_json(json_str)
        assert result.summary == "这是一段总结"

    def test_summary_result_round_trip(self):
        """Test SummaryResult round-trip: create -> dump -> validate -> compare."""
        original = SummaryResult(summary="这是一段总结")
        json_str = original.model_dump_json(ensure_ascii=False)
        restored = SummaryResult.model_validate_json(json_str)
        assert restored.summary == original.summary


class TestExtractionConfig:
    """Test ExtractionConfig model."""

    def test_extraction_config_basic(self):
        """Test basic ExtractionConfig creation."""
        config = ExtractionConfig(since_date=date(2026, 3, 10))
        assert config.since_date == date(2026, 3, 10)
        assert config.scroll_delay == 1.0

    def test_extraction_config_custom_scroll_delay(self):
        """Test ExtractionConfig with custom scroll_delay."""
        config = ExtractionConfig(since_date=date(2026, 3, 10), scroll_delay=2.5)
        assert config.scroll_delay == 2.5

    def test_extraction_config_validation_missing_since_date(self):
        """Test ExtractionConfig validation fails without since_date."""
        with pytest.raises(ValidationError):
            ExtractionConfig()

    def test_extraction_config_validation_invalid_since_date_type(self):
        """Test ExtractionConfig validation fails with non-coercible since_date."""
        with pytest.raises(ValidationError):
            ExtractionConfig(since_date="not-a-date")

    def test_extraction_config_validation_invalid_scroll_delay_type(self):
        """Test ExtractionConfig validation fails with non-coercible scroll_delay."""
        with pytest.raises(ValidationError):
            ExtractionConfig(since_date=date(2026, 3, 10), scroll_delay="not-a-number")

    def test_extraction_config_json_serialization(self):
        """Test ExtractionConfig serializes to JSON."""
        config = ExtractionConfig(since_date=date(2026, 3, 10))
        json_str = config.model_dump_json()
        assert isinstance(json_str, str)
        assert "2026-03-10" in json_str

    def test_extraction_config_json_deserialization(self):
        """Test ExtractionConfig deserializes from JSON."""
        json_str = '{"since_date":"2026-03-10","scroll_delay":1.0}'
        config = ExtractionConfig.model_validate_json(json_str)
        assert config.since_date == date(2026, 3, 10)
        assert config.scroll_delay == 1.0

    def test_extraction_config_round_trip(self):
        """Test ExtractionConfig round-trip: create -> dump -> validate -> compare."""
        original = ExtractionConfig(since_date=date(2026, 3, 10), scroll_delay=2.5)
        json_str = original.model_dump_json()
        restored = ExtractionConfig.model_validate_json(json_str)
        assert restored.since_date == original.since_date
        assert restored.scroll_delay == original.scroll_delay


class TestLLMConfig:
    """Test LLMConfig model."""

    def test_llm_config_defaults(self):
        """Test LLMConfig with default values."""
        config = LLMConfig()
        assert config.base_url == "http://localhost:11434/v1"
        assert config.api_key == "ollama"
        assert config.model == "qwen2.5"
        assert config.temperature == 0.3
        assert config.max_tokens == 4096

    def test_llm_config_custom_values(self):
        """Test LLMConfig with custom values."""
        config = LLMConfig(
            base_url="http://example.com/v1",
            api_key="custom-key",
            model="gpt-4",
            temperature=0.7,
            max_tokens=2048,
        )
        assert config.base_url == "http://example.com/v1"
        assert config.api_key == "custom-key"
        assert config.model == "gpt-4"
        assert config.temperature == 0.7
        assert config.max_tokens == 2048

    def test_llm_config_validation_invalid_base_url_type(self):
        """Test LLMConfig validation fails with non-string base_url."""
        with pytest.raises(ValidationError):
            LLMConfig(base_url=123)

    def test_llm_config_validation_invalid_api_key_type(self):
        """Test LLMConfig validation fails with non-string api_key."""
        with pytest.raises(ValidationError):
            LLMConfig(api_key=123)

    def test_llm_config_validation_invalid_model_type(self):
        """Test LLMConfig validation fails with non-string model."""
        with pytest.raises(ValidationError):
            LLMConfig(model=123)

    def test_llm_config_validation_invalid_temperature_type(self):
        """Test LLMConfig validation fails with non-coercible temperature."""
        with pytest.raises(ValidationError):
            LLMConfig(temperature="not-a-number")

    def test_llm_config_validation_invalid_max_tokens_type(self):
        """Test LLMConfig validation fails with non-coercible max_tokens."""
        with pytest.raises(ValidationError):
            LLMConfig(max_tokens="not-a-number")

    def test_llm_config_json_serialization(self):
        """Test LLMConfig serializes to JSON."""
        config = LLMConfig()
        json_str = config.model_dump_json()
        assert isinstance(json_str, str)
        assert "http://localhost:11434/v1" in json_str

    def test_llm_config_json_deserialization(self):
        """Test LLMConfig deserializes from JSON."""
        json_str = """{
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
            "model": "qwen2.5",
            "temperature": 0.3,
            "max_tokens": 4096
        }"""
        config = LLMConfig.model_validate_json(json_str)
        assert config.base_url == "http://localhost:11434/v1"
        assert config.api_key == "ollama"
        assert config.model == "qwen2.5"

    def test_llm_config_round_trip(self):
        """Test LLMConfig round-trip: create -> dump -> validate -> compare."""
        original = LLMConfig(
            base_url="http://example.com/v1",
            api_key="custom-key",
            model="gpt-4",
            temperature=0.7,
            max_tokens=2048,
        )
        json_str = original.model_dump_json()
        restored = LLMConfig.model_validate_json(json_str)
        assert restored.base_url == original.base_url
        assert restored.api_key == original.api_key
        assert restored.model == original.model
        assert restored.temperature == original.temperature
        assert restored.max_tokens == original.max_tokens
