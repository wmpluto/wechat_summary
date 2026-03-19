# pyright: reportMissingImports=false
"""Tests for the OpenAI-compatible LLM client wrapper."""

from unittest.mock import MagicMock, call, patch

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

from wechat_summary.llm_client import LLMClient, LLMConnectionError


def make_request(url: str) -> httpx.Request:
    """Create a reusable HTTP request object for OpenAI errors."""
    return httpx.Request("POST", url)


class TestLLMClient:
    """Test suite for LLMClient."""

    def test_init_creates_openai_client(self, mock_llm_client):
        """Test OpenAI client is initialized with base_url and api_key."""
        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client) as mock_openai:
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        mock_openai.assert_called_once_with(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )
        assert client.client is mock_llm_client
        assert client.model == "qwen2.5"

    def test_chat_returns_response_text(self, mock_llm_client):
        """Test chat returns the content from the first completion choice."""
        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client):
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        messages = [{"role": "user", "content": "请总结今天的聊天"}]
        result = client.chat(messages)

        assert result == "这是一段总结"
        mock_llm_client.chat.completions.create.assert_called_once_with(
            model="qwen2.5",
            messages=messages,
        )

    def test_chat_raises_llm_connection_error_on_connection_failure(self, mock_llm_client):
        """Test chat wraps connection failures with a helpful Ollama message."""
        mock_llm_client.chat.completions.create.side_effect = APIConnectionError(
            message="Connection error.",
            request=make_request("http://localhost:11434/v1/chat/completions"),
        )

        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client):
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        with pytest.raises(LLMConnectionError) as exc_info:
            client.chat([{"role": "user", "content": "你好"}])

        assert "Cannot connect to http://localhost:11434/v1" in str(exc_info.value)

    def test_chat_retries_timeout_then_succeeds(self, mock_llm_client):
        """Test chat retries timeout errors with exponential backoff."""
        timeout_request = make_request("http://localhost:11434/v1/chat/completions")
        success_response = MagicMock(choices=[MagicMock(message=MagicMock(content="第三次成功"))])
        mock_llm_client.chat.completions.create.side_effect = [
            APITimeoutError(request=timeout_request),
            APITimeoutError(request=timeout_request),
            success_response,
        ]

        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client):
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        with patch("wechat_summary.llm_client.time.sleep") as mock_sleep:
            result = client.chat([{"role": "user", "content": "重试测试"}])

        assert result == "第三次成功"
        assert mock_llm_client.chat.completions.create.call_count == 3
        mock_sleep.assert_has_calls([call(1), call(2)])

    def test_check_connection_returns_true_when_server_is_reachable(self, mock_llm_client):
        """Test check_connection returns True when a completion succeeds."""
        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client):
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        assert client.check_connection() is True
        mock_llm_client.chat.completions.create.assert_called_once()

    def test_check_connection_returns_false_when_server_is_unreachable(self, mock_llm_client):
        """Test check_connection returns False when the server cannot be reached."""
        mock_llm_client.chat.completions.create.side_effect = APIConnectionError(
            message="Connection error.",
            request=make_request("http://localhost:11434/v1/chat/completions"),
        )

        with patch("wechat_summary.llm_client.OpenAI", return_value=mock_llm_client):
            client = LLMClient(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                model="qwen2.5",
            )

        assert client.check_connection() is False
        assert mock_llm_client.chat.completions.create.call_count == 1
