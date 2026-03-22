"""Integration tests for end-to-end CLI pipeline wiring and errors."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from wechat_summary.cli import cli
from wechat_summary.exceptions import DeviceNotFoundError, LLMConnectionError
from wechat_summary.models import ChatSession, ChatType, SummaryResult


def test_full_extract_chain(mock_device, sample_messages, tmp_path):
    """Full extract pipeline: connect → detect → scroll → save JSON."""
    runner = CliRunner()

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Pixel 8 | Android 14"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.detect_chat_info.return_value = ("项目群", ChatType.GROUP)
        mock_extractor.scroll_and_extract.return_value = sample_messages

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    saved_files = list(Path(tmp_path).glob("项目群_*.json"))
    assert len(saved_files) == 1
    content = saved_files[0].read_text(encoding="utf-8")
    assert '"chat_name": "项目群"' in content
    assert '"messages": [' in content


def test_full_summarize_chain(sample_chat_session, tmp_path):
    """Full summarize pipeline: load → LLM → save MD + JSON."""
    runner = CliRunner()
    input_file = tmp_path / "session_input.json"
    input_file.write_text(
        sample_chat_session.model_dump_json(ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (
        patch("wechat_summary.orchestrator.LLMClient") as mock_llm_client_cls,
        patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls,
    ):
        mock_llm_client = MagicMock()
        mock_llm_client_cls.return_value = mock_llm_client

        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="总结内容")

        result = runner.invoke(
            cli,
            [
                "summarize",
                "--input",
                str(input_file),
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    md_path = tmp_path / "session_input_summary.md"
    json_path = tmp_path / "session_input_summary.json"
    assert md_path.exists()
    assert json_path.exists()
    assert "# 聊天记录总结:" in md_path.read_text(encoding="utf-8")
    assert '"summary": "总结内容"' in json_path.read_text(encoding="utf-8")


def test_full_extract_and_summarize_chain(mock_device, sample_messages, tmp_path):
    """Full extract+summarize: extract → save → summarize → MD + JSON."""
    runner = CliRunner()

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
        patch("wechat_summary.orchestrator.LLMClient") as mock_llm_client_cls,
        patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Pixel 8 | Android 14"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.detect_chat_info.return_value = ("家人群", ChatType.GROUP)
        mock_extractor.scroll_and_extract.return_value = sample_messages

        mock_llm_client = MagicMock()
        mock_llm_client_cls.return_value = mock_llm_client

        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="链路总结")

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                str(tmp_path),
                "--summarize",
            ],
        )

    assert result.exit_code == 0
    raw_files = list(Path(tmp_path).glob("家人群_*.json"))
    assert any(not file.name.endswith("_summary.json") for file in raw_files)
    assert (tmp_path / "家人群_summary.md").exists() is False
    summary_md = list(Path(tmp_path).glob("家人群_*_summary.md"))
    summary_json = list(Path(tmp_path).glob("家人群_*_summary.json"))
    assert len(summary_md) == 1
    assert len(summary_json) == 1


def test_device_error_message():
    """No device connected should show helpful error with USB/adb mention."""
    runner = CliRunner()

    with patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls:
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.side_effect = DeviceNotFoundError("连接失败")

        result = runner.invoke(cli, ["extract", "--since", "2026-03-10"])

    assert result.exit_code == 1
    assert "USB" in result.output
    assert "adb" in result.output


def test_llm_error_preserves_raw_data(mock_device, sample_messages, tmp_path):
    """LLM failure during extract+summarize should still save extraction data."""
    runner = CliRunner()

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
        patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Pixel 8 | Android 14"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.detect_chat_info.return_value = ("异常群", ChatType.GROUP)
        mock_extractor.scroll_and_extract.return_value = sample_messages

        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.side_effect = LLMConnectionError("LLM unavailable")

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                str(tmp_path),
                "--summarize",
            ],
        )

    assert result.exit_code == 1
    raw_files = [
        f for f in Path(tmp_path).glob("异常群_*.json") if not f.name.endswith("_summary.json")
    ]
    assert len(raw_files) == 1
    assert f"原始数据已保存至: {raw_files[0]}" in result.output


def test_interrupt_saves_partial(mock_device, sample_messages, tmp_path):
    """Ctrl+C should save partial extraction results."""
    runner = CliRunner()

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
        patch("wechat_summary.orchestrator.ChatSessionStore") as mock_store_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Pixel 8 | Android 14"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.detect_chat_info.return_value = ("中断群", ChatType.GROUP)
        mock_extractor.scroll_and_extract.return_value = sample_messages

        mock_store = mock_store_cls.return_value
        mock_store.save.side_effect = KeyboardInterrupt()
        mock_store.save_partial.return_value = str(tmp_path / "中断群_20260317_120000_partial.json")

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 130
    mock_store.save_partial.assert_called_once()
    assert "提取已中断" in result.output
    assert "partial" in result.output


def test_summarize_markdown_format(sample_chat_session, tmp_path):
    """Verify markdown output has Chinese headers and correct structure."""
    runner = CliRunner()
    input_file = tmp_path / "for_markdown.json"
    input_file.write_text(
        sample_chat_session.model_dump_json(ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls:
        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="这是结构化总结")

        result = runner.invoke(
            cli,
            [
                "summarize",
                "--input",
                str(input_file),
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    md_path = tmp_path / "for_markdown_summary.md"
    md_content = md_path.read_text(encoding="utf-8")
    assert "# 聊天记录总结:" in md_content
    assert "**提取时间**" in md_content
    assert "## 总结" in md_content
    assert "这是结构化总结" in md_content


def test_summarize_empty_chat(tmp_path):
    """Summarize with empty message list should handle gracefully."""
    runner = CliRunner()
    empty_session = ChatSession(
        chat_name="空会话",
        chat_type=ChatType.GROUP,
        messages=[],
        extracted_at=datetime(2026, 3, 17, 12, 0, 0),
        device_info="Pixel 8 | Android 14",
    )
    input_file = tmp_path / "empty_session.json"
    input_file.write_text(
        empty_session.model_dump_json(ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls:
        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="没有可总结内容")

        result = runner.invoke(
            cli,
            [
                "summarize",
                "--input",
                str(input_file),
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0
    md_path = tmp_path / "empty_session_summary.md"
    assert md_path.exists()
    assert "没有可总结内容" in md_path.read_text(encoding="utf-8")
