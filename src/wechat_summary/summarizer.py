"""Chat summarizer with single-pass and hierarchical chunking."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

import tiktoken

from wechat_summary.models import SummaryResult


class LLMClientLike(Protocol):
    """Protocol for LLM client expected by ChatSummarizer."""

    def chat(self, messages: list[dict[str, str]]) -> str: ...


class ChatSummarizer:
    """Generate an overall Chinese summary for a chat session."""

    TOKEN_LIMIT = 3000
    SYSTEM_PROMPT = (
        "你是一个聊天记录分析助手。请阅读以下微信聊天记录，并生成一段简洁的中文总结。"
        "总结应涵盖主要讨论内容、关键决定和重要信息。"
    )

    _NON_TEXT_PLACEHOLDERS = {
        "IMAGE": "[图片]",
        "VOICE": "[语音]",
        "VIDEO": "[视频]",
        "FILE": "[文件]",
        "SYSTEM": "[系统消息]",
    }

    def __init__(self, llm_client: LLMClientLike):
        self.llm_client = llm_client
        self._encoding = tiktoken.get_encoding("cl100k_base")

    def summarize(self, session: Any) -> SummaryResult:
        """Summarize a chat session into one overall summary."""
        formatted = self._format_messages(session.messages)
        if self._estimate_tokens(formatted) <= self.TOKEN_LIMIT:
            prompt = self._build_prompt(formatted, session.chat_name)
            return SummaryResult(summary=self.llm_client.chat(prompt))

        chunk_texts = self._chunk_formatted_text(formatted)
        chunk_summaries: list[str] = []

        for index, chunk_text in enumerate(chunk_texts, start=1):
            chunk_prompt = self._build_prompt(chunk_text, f"{session.chat_name}（第{index}段）")
            chunk_summaries.append(self.llm_client.chat(chunk_prompt))

        merged = "\n".join(
            f"第{index}段总结：{summary}" for index, summary in enumerate(chunk_summaries, start=1)
        )
        meta_prompt = self._build_prompt(merged, f"{session.chat_name}（分段总结汇总）")
        return SummaryResult(summary=self.llm_client.chat(meta_prompt))

    def _format_messages(self, messages: Sequence[Any]) -> str:
        """Format messages as `[HH:MM] 张三: 内容` for prompt input."""
        lines: list[str] = []
        for message in messages:
            time_str = self._format_time(getattr(message, "timestamp", None))
            sender = getattr(message, "sender", "未知")
            content = self._normalize_content(message)
            lines.append(f"[{time_str}] {sender}: {content}")
        return "\n".join(lines)

    def _build_prompt(self, formatted_msgs: str, chat_name: str) -> list[dict[str, str]]:
        """Build Chinese prompt for the LLM."""
        user_prompt = (
            f"聊天名称：{chat_name}\n"
            "以下是聊天记录：\n"
            f"{formatted_msgs}\n\n"
            "请输出一段中文总结。"
        )
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _chunk_formatted_text(self, formatted_text: str) -> list[str]:
        """Split formatted chat text into token-limited chunks."""
        lines = formatted_text.splitlines()
        chunks: list[str] = []
        current_lines: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = self._estimate_tokens(line + "\n")

            if current_lines and current_tokens + line_tokens > self.TOKEN_LIMIT:
                chunks.append("\n".join(current_lines))
                current_lines = [line]
                current_tokens = line_tokens
                continue

            current_lines.append(line)
            current_tokens += line_tokens

        if current_lines:
            chunks.append("\n".join(current_lines))

        return chunks

    def _estimate_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def _format_time(self, timestamp: Any) -> str:
        if isinstance(timestamp, datetime):
            return timestamp.strftime("%H:%M")
        return "00:00"

    def _normalize_content(self, message: Any) -> str:
        raw_content = str(getattr(message, "content", "")).strip()
        message_type = getattr(message, "message_type", "TEXT")

        if isinstance(message_type, Enum):
            message_type = message_type.value

        placeholder = self._NON_TEXT_PLACEHOLDERS.get(str(message_type).upper())
        if placeholder and str(message_type).upper() != "TEXT":
            return placeholder

        return raw_content or "[空消息]"


__all__ = ["ChatSummarizer"]
