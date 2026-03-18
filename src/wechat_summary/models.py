"""Pydantic v2 data models for WeChat chat summary tool."""

from dataclasses import dataclass
from enum import Enum
from datetime import datetime, date
from typing import Optional, List

from pydantic import BaseModel, Field


@dataclass
class ChatListItem:
    """A single chat entry in the WeChat message list."""

    name: str
    last_time_text: str
    last_time: date | None
    preview: str
    is_folded: bool = False
    is_blacklisted: bool = False
    source: str = "main"


class MessageType(str, Enum):
    """Enum for message types."""

    TEXT = "TEXT"
    IMAGE = "IMAGE"
    VOICE = "VOICE"
    VIDEO = "VIDEO"
    FILE = "FILE"
    SYSTEM = "SYSTEM"


class ChatType(str, Enum):
    """Enum for chat types."""

    PRIVATE = "PRIVATE"
    GROUP = "GROUP"


class ChatMessage(BaseModel):
    """Model for a single chat message."""

    sender: str = Field(..., description="Sender name")
    content: str = Field(..., description="Message content")
    timestamp: Optional[datetime] = Field(None, description="Message timestamp")
    message_type: MessageType = Field(..., description="Type of message")
    is_self: bool = Field(..., description="Whether message is from self")

    class Config:
        """Pydantic config."""

        use_enum_values = False


class ChatSession(BaseModel):
    """Model for a chat session with multiple messages."""

    chat_name: str = Field(..., description="Name of the chat")
    chat_type: ChatType = Field(..., description="Type of chat (PRIVATE or GROUP)")
    messages: List[ChatMessage] = Field(..., description="List of messages")
    extracted_at: datetime = Field(..., description="When the chat was extracted")
    device_info: str = Field(..., description="Device information")

    class Config:
        """Pydantic config."""

        use_enum_values = False


class SummaryResult(BaseModel):
    """Model for summary results (MVP: overall summary only)."""

    summary: str = Field(..., description="Overall summary of the chat")

    class Config:
        """Pydantic config."""

        use_enum_values = False


class ExtractionConfig(BaseModel):
    """Model for extraction configuration."""

    since_date: date = Field(..., description="Extract messages since this date")
    scroll_delay: float = Field(1.0, description="Delay between scrolls in seconds")

    class Config:
        """Pydantic config."""

        use_enum_values = False


class LLMConfig(BaseModel):
    """Model for LLM configuration."""

    base_url: str = Field("http://localhost:11434/v1", description="LLM API base URL")
    api_key: str = Field("ollama", description="LLM API key")
    model: str = Field("qwen2.5", description="LLM model name")
    temperature: float = Field(0.3, description="LLM temperature")
    max_tokens: int = Field(4096, description="Maximum tokens for LLM response")

    class Config:
        """Pydantic config."""

        use_enum_values = False
