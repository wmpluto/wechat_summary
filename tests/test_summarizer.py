"""Tests for chat summarizer (TDD RED phase)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from wechat_summary.summarizer import ChatSummarizer


def _make_message(sender: str, content: str, minute: int, message_type: str = "TEXT"):
    return MagicMock(
        sender=sender,
        content=content,
        timestamp=datetime(2026, 3, 17, 14, minute, 0),
        message_type=message_type,
    )


class TestChatSummarizer:
    def test_format_messages_uses_hh_mm_sender_and_content(self):
        messages = [
            _make_message("张三", "明天开会", 30, "TEXT"),
            _make_message("李四", "原始图片内容", 31, "IMAGE"),
        ]
        summarizer = ChatSummarizer(llm_client=MagicMock())

        formatted = summarizer._format_messages(messages)

        lines = formatted.splitlines()
        assert lines[0] == "[14:30] 张三: 明天开会"
        assert lines[1] == "[14:31] 李四: [图片]"

    def test_build_prompt_uses_chinese_instruction(self):
        summarizer = ChatSummarizer(llm_client=MagicMock())

        prompt = summarizer._build_prompt("[14:30] 张三: 明天开会", "测试群聊")

        assert len(prompt) == 2
        assert prompt[0]["role"] == "system"
        assert (
            "你是一个聊天记录分析助手。请阅读以下微信聊天记录，并生成一段简洁的中文总结。"
            in prompt[0]["content"]
        )
        assert "测试群聊" in prompt[1]["content"]
        assert "[14:30] 张三: 明天开会" in prompt[1]["content"]

    def test_summarize_short_chat_single_pass(self, sample_chat_session, mock_llm_client):
        mock_llm_client.chat = MagicMock(return_value="单次总结")
        summarizer = ChatSummarizer(llm_client=mock_llm_client)

        result = summarizer.summarize(sample_chat_session)

        assert result.summary == "单次总结"
        assert mock_llm_client.chat.call_count == 1

    def test_summarize_long_chat_uses_hierarchical_chunking(self, mock_llm_client):
        base_time = datetime(2026, 3, 17, 9, 0, 0)
        long_messages = []
        for i in range(1200):
            long_messages.append(
                MagicMock(
                    sender="张三" if i % 2 == 0 else "李四",
                    content=f"第{i}条消息，讨论项目进度与安排",
                    timestamp=base_time + timedelta(minutes=i),
                    message_type="TEXT",
                )
            )

        long_session = MagicMock(chat_name="超长群聊", messages=long_messages)

        call_counter = {"n": 0}

        def _fake_chat(_messages):
            call_counter["n"] += 1
            return f"第{call_counter['n']}次总结"

        mock_llm_client.chat = MagicMock(side_effect=_fake_chat)
        summarizer = ChatSummarizer(llm_client=mock_llm_client)
        summarizer.TOKEN_LIMIT = 600

        result = summarizer.summarize(long_session)

        assert result.summary.startswith("第")
        assert mock_llm_client.chat.call_count >= 4
