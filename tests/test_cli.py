"""Tests for Click CLI commands and wiring."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from wechat_summary.models import ChatType, SummaryResult
from wechat_summary.cli import cli


def test_cli_help():
    """Main help should list available subcommands."""
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "extract" in result.output
    assert "calibrate" in result.output
    assert "summarize" in result.output


def test_extract_help():
    """Extract help should expose expected options."""
    runner = CliRunner()

    result = runner.invoke(cli, ["extract", "--help"])

    assert result.exit_code == 0
    assert "--since" in result.output
    assert "--device" in result.output
    assert "--chat-name" in result.output
    assert "--output-dir" in result.output
    assert "--summarize" in result.output
    assert "--config" in result.output
    assert "--base-url" in result.output
    assert "--model" in result.output
    assert "--max-scrolls" in result.output


def test_extract_all_help():
    """Extract-all help should expose expected options."""
    runner = CliRunner()

    result = runner.invoke(cli, ["extract-all", "--help"])

    assert result.exit_code == 0
    assert "--since" in result.output
    assert "--max-chats" in result.output
    assert "--max-scrolls" in result.output
    assert "--max-list-scrolls" in result.output
    assert "--include" in result.output
    assert "--exclude" in result.output
    assert "--exclude-file" in result.output
    assert "--summarize" in result.output


def test_summarize_all_help():
    """Summarize-all help should expose expected options."""
    runner = CliRunner()

    result = runner.invoke(cli, ["summarize-all", "--help"])

    assert result.exit_code == 0
    assert "--input-dir" in result.output
    assert "--base-url" in result.output
    assert "--model" in result.output
    assert "--api-key" in result.output
    assert "--system-prompt" in result.output
    assert "--user-template" in result.output


def test_summarize_help():
    """Summarize help should expose expected options."""
    runner = CliRunner()

    result = runner.invoke(cli, ["summarize", "--help"])

    assert result.exit_code == 0
    assert "--input" in result.output
    assert "--output-dir" in result.output
    assert "--base-url" in result.output
    assert "--model" in result.output


def test_extract_with_mock_device(mock_device, sample_messages, tmp_path):
    """Extract command should run end-to-end extraction pipeline."""
    runner = CliRunner()
    output_dir = str(tmp_path)
    saved_path = str(tmp_path / "chat_session.json")

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
        patch("wechat_summary.orchestrator.ChatSessionStore") as mock_store_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Xiaomi | Android 12"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.scroll_and_extract.return_value = sample_messages

        mock_store = mock_store_cls.return_value
        mock_store.save.return_value = saved_path

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                output_dir,
                "--chat-name",
                "手动会话",
            ],
        )

    assert result.exit_code == 0
    mock_device_manager.connect.assert_called_once_with(serial=None)
    mock_device_manager.check_wechat.assert_called_once_with(mock_device)
    mock_extractor.detect_chat_info.assert_not_called()
    mock_extractor.scroll_and_extract.assert_called_once_with(mock_device, date(2026, 3, 10))
    mock_store.save.assert_called_once()
    _, save_kwargs = mock_store.save.call_args
    assert save_kwargs["output_dir"] == output_dir
    assert "正在连接设备..." in result.output
    assert "正在检查微信..." in result.output
    assert "正在检测聊天信息..." in result.output
    assert "提取完成，共" in result.output
    assert f"数据已保存至: {saved_path}" in result.output


def test_extract_with_summarize_flag(mock_device, sample_messages, tmp_path):
    """Extract --summarize should create markdown and JSON summary outputs."""
    runner = CliRunner()
    output_dir = str(tmp_path)
    saved_path = str(tmp_path / "family_chat.json")

    with (
        patch("wechat_summary.cli.DeviceManager") as mock_device_manager_cls,
        patch("wechat_summary.orchestrator.MessageExtractor") as mock_extractor_cls,
        patch("wechat_summary.orchestrator.ChatSessionStore") as mock_store_cls,
        patch("wechat_summary.orchestrator.LLMClient") as mock_llm_client_cls,
        patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls,
    ):
        mock_device_manager = mock_device_manager_cls.return_value
        mock_device_manager.connect.return_value = mock_device
        mock_device_manager.get_device_info.return_value = "Xiaomi | Android 12"

        mock_extractor = mock_extractor_cls.return_value
        mock_extractor.scroll_and_extract.return_value = sample_messages

        mock_store = mock_store_cls.return_value
        mock_store.save.return_value = saved_path

        mock_llm_client = MagicMock()
        mock_llm_client_cls.return_value = mock_llm_client

        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="这是自动总结")

        result = runner.invoke(
            cli,
            [
                "extract",
                "--since",
                "2026-03-10",
                "--output-dir",
                output_dir,
                "--chat-name",
                "家人群",
                "--summarize",
            ],
        )

    assert result.exit_code == 0
    mock_llm_client_cls.assert_called_once_with("http://localhost:11434/v1", "ollama", "qwen2.5")
    mock_summarizer_cls.assert_called_once_with(mock_llm_client)

    md_path = tmp_path / "family_chat_summary.md"
    json_path = tmp_path / "family_chat_summary.json"
    assert md_path.exists()
    assert json_path.exists()
    assert "# 聊天记录总结: 家人群" in md_path.read_text(encoding="utf-8")
    assert "这是自动总结" in md_path.read_text(encoding="utf-8")
    assert '"summary": "这是自动总结"' in json_path.read_text(encoding="utf-8")


def test_summarize_with_mock_llm(sample_chat_session, tmp_path):
    """Summarize command should load session, call LLM summarizer, and save outputs."""
    runner = CliRunner()
    input_file = tmp_path / "session_data.json"
    input_file.write_text("{}", encoding="utf-8")

    with (
        patch("wechat_summary.orchestrator.ChatSessionStore") as mock_store_cls,
        patch("wechat_summary.orchestrator.LLMClient") as mock_llm_client_cls,
        patch("wechat_summary.orchestrator.ChatSummarizer") as mock_summarizer_cls,
    ):
        mock_store = mock_store_cls.return_value
        mock_store.load.return_value = sample_chat_session

        mock_llm_client = MagicMock()
        mock_llm_client_cls.return_value = mock_llm_client

        mock_summarizer = mock_summarizer_cls.return_value
        mock_summarizer.summarize.return_value = SummaryResult(summary="这是一段总结")

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
    mock_store.load.assert_called_once_with(str(input_file))
    mock_llm_client_cls.assert_called_once_with("http://localhost:11434/v1", "ollama", "qwen2.5")
    mock_summarizer_cls.assert_called_once_with(mock_llm_client)

    md_path = tmp_path / "session_data_summary.md"
    json_path = tmp_path / "session_data_summary.json"
    assert md_path.exists()
    assert json_path.exists()
    assert "# 聊天记录总结" in md_path.read_text(encoding="utf-8")
    assert '"summary": "这是一段总结"' in json_path.read_text(encoding="utf-8")
    assert f"总结已保存至: {md_path}" in result.output
    assert f"JSON已保存至: {json_path}" in result.output


def test_extract_since_required():
    """Extract should fail without required --since option."""
    runner = CliRunner()

    result = runner.invoke(cli, ["extract"])

    assert result.exit_code != 0
    assert "Missing option '--since'" in result.output


def test_summarize_input_required():
    """Summarize should fail without required --input option."""
    runner = CliRunner()

    result = runner.invoke(cli, ["summarize"])

    assert result.exit_code != 0
    assert "Missing option '--input'" in result.output


def test_main_module():
    """`python -m wechat_summary --help` should work."""
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "wechat_summary", "--help"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "extract" in result.stdout
    assert "summarize" in result.stdout
