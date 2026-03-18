"""Integration tests for the extract-all CLI command."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from click.testing import CliRunner

from wechat_summary.cli import _sanitize_filename, cli
from wechat_summary.models import ChatListItem


def _item(name: str, *, is_folded: bool = False, is_blacklisted: bool = False) -> ChatListItem:
    return ChatListItem(
        name=name,
        last_time_text="10:00",
        last_time=date(2026, 3, 18),
        preview="preview",
        is_folded=is_folded,
        is_blacklisted=is_blacklisted,
    )


class TestExtractAllCommand:
    def test_help_shows_options(self):
        """extract-all --help should show all options."""
        runner = CliRunner()

        result = runner.invoke(cli, ["extract-all", "--help"])

        assert result.exit_code == 0
        assert "--since" in result.output
        assert "--device" in result.output
        assert "--output-dir" in result.output
        assert "--max-chats" in result.output
        assert "--include" in result.output
        assert "--exclude" in result.output
        assert "--summarize" in result.output
        assert "--config" in result.output

    def test_basic_flow_with_mocked_chats(self, mock_device, sample_messages, tmp_path):
        """Full flow: 2 chats on list, both extracted successfully."""
        runner = CliRunner()
        list_items = [_item("王五"), _item("张三")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
            patch("wechat_summary.cli.load_config") as mock_load_config,
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Pixel 8 | Android 14"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = list_items
            mock_nav.filter_items.return_value = list_items
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.side_effect = [sample_messages, sample_messages]

            mock_load_config.return_value = object()

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        out_dir = tmp_path / f"2026-03-10_{date.today().isoformat()}"
        assert out_dir.exists()
        assert (out_dir / "王五.json").exists()
        assert (out_dir / "张三.json").exists()
        assert "完成！共处理 2 个会话" in result.output
        assert "输出目录:" in result.output

    def test_creates_date_range_folder(self, mock_device, tmp_path):
        """Output folder should be named since_today."""
        runner = CliRunner()
        list_items = [_item("单聊")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = list_items
            mock_nav.filter_items.return_value = list_items
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = []

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        expected = tmp_path / f"2026-03-10_{date.today().isoformat()}"
        assert expected.exists()

    def test_skips_blacklisted_chats(self, mock_device):
        """Blacklisted items like '公众号' should be skipped."""
        runner = CliRunner()

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor"),
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = [_item("公众号", is_blacklisted=True)]
            mock_nav.filter_items.return_value = []
            mock_nav.should_stop_scrolling.return_value = True

            result = runner.invoke(cli, ["extract-all", "--since", "2026-03-10"])

        assert result.exit_code == 0
        mock_nav.enter_chat.assert_not_called()
        assert "完成！共处理 0 个会话" in result.output

    def test_respects_max_chats(self, mock_device, sample_messages, tmp_path):
        """Should stop after max_chats processed."""
        runner = CliRunner()
        items = [_item("A"), _item("B"), _item("C")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = items
            mock_nav.filter_items.return_value = items
            mock_nav.should_stop_scrolling.return_value = False
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = sample_messages

            result = runner.invoke(
                cli,
                [
                    "extract-all",
                    "--since",
                    "2026-03-10",
                    "--output-dir",
                    str(tmp_path),
                    "--max-chats",
                    "1",
                ],
            )

        assert result.exit_code == 0
        assert "已达到最大数量 (1)" in result.output
        assert "完成！共处理 1 个会话" in result.output

    def test_include_filter(self, mock_device):
        """Only matching chats should be processed."""
        runner = CliRunner()
        items = [_item("项目群"), _item("家人群")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = items
            mock_nav.filter_items.return_value = [_item("项目群")]
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = []

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--include", "项目", "--exclude-file", ""],
            )

        assert result.exit_code == 0
        args = mock_nav.filter_items.call_args[0]
        assert args[2] == ["项目"]
        assert args[3] is None

    def test_exclude_filter(self, mock_device):
        """Matching chats should be skipped."""
        runner = CliRunner()

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = [_item("项目群")]
            mock_nav.filter_items.return_value = []
            mock_nav.should_stop_scrolling.return_value = True

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = []

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--exclude", "项目", "--exclude-file", ""],
            )

        assert result.exit_code == 0
        args = mock_nav.filter_items.call_args[0]
        assert args[2] is None
        assert args[3] == ["项目"]

    def test_handles_enter_chat_failure(self, mock_device, sample_messages):
        """Failed chat entry should be logged and skipped."""
        runner = CliRunner()
        items = [_item("A"), _item("B")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = items
            mock_nav.filter_items.return_value = items
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_chat.side_effect = [False, True]
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = sample_messages

            result = runner.invoke(cli, ["extract-all", "--since", "2026-03-10"])

        assert result.exit_code == 0
        assert "⚠️  1 个会话处理失败: A" in result.output

    def test_handles_extraction_error(self, mock_device, sample_messages):
        """Extraction error should be caught, logged, and continue."""
        runner = CliRunner()
        items = [_item("A"), _item("B")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = items
            mock_nav.filter_items.return_value = items
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.side_effect = [RuntimeError("boom"), sample_messages]

            result = runner.invoke(cli, ["extract-all", "--since", "2026-03-10"])

        assert result.exit_code == 0
        assert "⚠️  1 个会话处理失败: A" in result.output
        assert "完成！共处理 2 个会话" in result.output

    def test_folded_chats_processing(self, mock_device, sample_messages, tmp_path):
        """Should enter folded chats, process items, and return."""
        runner = CliRunner()
        main_items = [_item("折叠的聊天", is_folded=True)]
        folded_items = [_item("技术交流群")]

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor") as mock_extractor_cls,
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.return_value = main_items
            mock_nav.parse_folded_list.return_value = folded_items
            mock_nav.filter_items.side_effect = [main_items, folded_items]
            mock_nav.should_stop_scrolling.return_value = True
            mock_nav.enter_folded_chats.return_value = True
            mock_nav.exit_folded_chats.return_value = True
            mock_nav.enter_chat.return_value = True
            mock_nav.exit_chat.return_value = True
            mock_nav.is_processed.return_value = False

            mock_extractor = mock_extractor_cls.return_value
            mock_extractor.scroll_and_extract.return_value = sample_messages

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 0
        mock_nav.enter_folded_chats.assert_called_once_with(mock_device)
        mock_nav.exit_folded_chats.assert_called_once_with(mock_device)
        assert "进入折叠的聊天" in result.output
        assert "折叠 (1) 技术交流群" in result.output

    def test_keyboard_interrupt_prints_summary(self, mock_device, tmp_path):
        """Ctrl+C should print summary and exit 130."""
        runner = CliRunner()

        with (
            patch("wechat_summary.cli.DeviceManager") as mock_dm_cls,
            patch("wechat_summary.cli.ChatListNavigator") as mock_nav_cls,
            patch("wechat_summary.cli.MessageExtractor"),
            patch("wechat_summary.cli.ChatSessionStore"),
        ):
            mock_dm = mock_dm_cls.return_value
            mock_dm.connect.return_value = mock_device
            mock_dm.get_device_info.return_value = "Device"

            mock_nav = mock_nav_cls.return_value
            mock_nav.parse_chat_list.side_effect = KeyboardInterrupt()

            result = runner.invoke(
                cli,
                ["extract-all", "--since", "2026-03-10", "--output-dir", str(tmp_path)],
            )

        assert result.exit_code == 130
        assert "已中断。已处理 0 个会话，提取 0 条消息。" in result.output
        assert "输出目录:" in result.output

    def test_since_required(self):
        """extract-all without --since should fail."""
        runner = CliRunner()

        result = runner.invoke(cli, ["extract-all"])

        assert result.exit_code != 0
        assert "Missing option '--since'" in result.output


class TestSanitizeFilename:
    def test_removes_invalid_chars(self):
        assert _sanitize_filename("a/b:c") == "a_b_c"

    def test_preserves_chinese(self):
        assert _sanitize_filename("张三") == "张三"

    def test_handles_empty(self):
        assert _sanitize_filename("") == "unknown"

    def test_strips_dots_and_spaces(self):
        assert _sanitize_filename(" .chat. ") == "chat"
