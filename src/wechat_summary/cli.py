"""Click CLI for WeChat chat extraction and summarization."""

from __future__ import annotations

from datetime import date, datetime
import sys
from pathlib import Path

import click

from wechat_summary.calibrator import Calibrator
from wechat_summary.config import ChatViewConfig, SelectorConfig, load_config
from wechat_summary.device import DeviceManager
from wechat_summary.exceptions import (
    CalibrationError,
    DeviceNotFoundError,
    ExtractionError,
    LLMConnectionError,
    StabilityError,
    WeChatNotFoundError,
    WeChatSummaryError,
)
from wechat_summary.models import LLMConfig
from wechat_summary.orchestrator import extract_all_chats, extract_single, summarize_file
from wechat_summary.selectors import stable_dump


def _id_tail(resource_id: str) -> str:
    if "/" in resource_id:
        return resource_id.rsplit("/", maxsplit=1)[-1]
    return resource_id


class CLICallbacks:
    def log(self, message: str) -> None:
        click.echo(message)

    def should_stop(self) -> bool:
        return False


@click.group()
def cli():
    """WeChat chat extraction and summarization tool."""


@cli.command()
@click.option(
    "--since",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Extract messages since date (YYYY-MM-DD)",
)
@click.option("--device", default=None, help="Device serial number (auto-detect if not specified)")
@click.option("--chat-name", default=None, help="Chat name (required if auto-detect fails)")
@click.option("--output-dir", default="./output", help="Output directory")
@click.option("--summarize", is_flag=True, help="Also summarize after extraction")
@click.option(
    "--base-url",
    default="http://localhost:11434/v1",
    envvar="WECHAT_LLM_BASE_URL",
    help="LLM API base URL",
)
@click.option(
    "--model",
    default="qwen2.5",
    envvar="WECHAT_LLM_MODEL",
    help="LLM model name",
)
@click.option(
    "--api-key",
    default="ollama",
    envvar="WECHAT_LLM_API_KEY",
    help="LLM API key (default: 'ollama')",
)
@click.option("--config", "config_path", default=None, help="Selector config YAML file")
@click.option(
    "--max-scrolls",
    default=None,
    type=int,
    help="Max scroll pages per chat (default: unlimited)",
)
def extract(
    since: datetime,
    device: str | None,
    chat_name: str | None,
    output_dir: str,
    summarize: bool,
    base_url: str,
    model: str,
    api_key: str,
    config_path: str | None,
    max_scrolls: int | None,
):
    """Extract chat messages from WeChat on connected device."""
    filepath: str | None = None
    callbacks = CLICallbacks()

    try:
        since_date = since.date()
        llm_config = LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.3,
            max_tokens=4096,
        )

        callbacks.log("正在连接设备...")
        device_manager = DeviceManager()
        connected_device = device_manager.connect(serial=device)
        device_info = device_manager.get_device_info(connected_device)

        callbacks.log("正在检查微信...")
        device_manager.check_wechat(connected_device)

        config = load_config(config_path)
        _, filepath = extract_single(
            connected_device,
            config,
            since_date,
            chat_name,
            output_dir,
            device_info,
            callbacks,
            max_scrolls=max_scrolls,
            summarize=summarize,
            llm_config=llm_config,
        )
    except KeyboardInterrupt:
        sys.exit(130)
    except DeviceNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        callbacks.log(f"错误: {exc}")
        if filepath:
            callbacks.log(f"原始数据已保存至: {filepath}")
        sys.exit(1)
    except (StabilityError, ExtractionError, CalibrationError) as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        callbacks.log(f"错误: {exc}")
        sys.exit(1)


@cli.command("extract-all")
@click.option(
    "--since",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Extract messages since date (YYYY-MM-DD)",
)
@click.option("--device", default=None, help="Device serial (auto-detect if not specified)")
@click.option("--output-dir", default="./output", help="Output directory")
@click.option("--max-chats", default=None, type=int, help="Maximum number of chats to process")
@click.option(
    "--include", default=None, help="Only process these chats (comma-separated, partial match)"
)
@click.option("--exclude", default=None, help="Skip these chats (comma-separated, partial match)")
@click.option(
    "--exclude-file",
    default="./exclude.txt",
    type=click.Path(),
    help="File with exclude patterns, one per line (default: ./exclude.txt)",
)
@click.option("--summarize", is_flag=True, help="Also summarize each chat after extraction")
@click.option(
    "--base-url",
    default="http://localhost:11434/v1",
    envvar="WECHAT_LLM_BASE_URL",
    help="LLM API base URL",
)
@click.option("--model", default="qwen2.5", envvar="WECHAT_LLM_MODEL", help="LLM model name")
@click.option("--api-key", default="ollama", envvar="WECHAT_LLM_API_KEY", help="LLM API key")
@click.option("--config", "config_path", default=None, help="Selector config YAML file")
@click.option(
    "--max-scrolls",
    default=None,
    type=int,
    help="Max scroll pages per chat (default: unlimited)",
)
@click.option(
    "--max-list-scrolls",
    default=1000,
    type=int,
    help="Max scroll rounds for the message list (default: 1000)",
)
def extract_all(
    since: datetime,
    device: str | None,
    output_dir: str,
    max_chats: int | None,
    include: str | None,
    exclude: str | None,
    exclude_file: str,
    summarize: bool,
    base_url: str,
    model: str,
    api_key: str,
    config_path: str | None,
    max_scrolls: int | None,
    max_list_scrolls: int,
):
    """Extract messages from all chats in the message list."""

    _ = (base_url, model, api_key)
    callbacks = CLICallbacks()
    batch_dir = Path(output_dir)

    try:
        since_date = since.date()
        today = date.today()
        config = load_config(config_path)

        include_list = [s.strip() for s in include.split(",") if s.strip()] if include else None
        exclude_list = [s.strip() for s in exclude.split(",") if s.strip()] if exclude else []

        # Load exclude patterns from file
        exclude_file_path = Path(exclude_file) if exclude_file else None
        if exclude_file_path is not None and exclude_file_path.is_file():
            lines = exclude_file_path.read_text(encoding="utf-8").splitlines()
            file_patterns = [
                line.strip() for line in lines if line.strip() and not line.startswith("#")
            ]
            exclude_list.extend(file_patterns)
            callbacks.log(f"已加载排除名单: {exclude_file_path} ({len(file_patterns)} 条规则)")
        elif exclude_file and exclude_file != "./exclude.txt":
            # Only warn if user explicitly specified a file that doesn't exist
            callbacks.log(f"⚠️  排除名单文件不存在: {exclude_file}")

        exclude_list = exclude_list or None

        callbacks.log("正在连接设备...")
        device_manager = DeviceManager()
        connected = device_manager.connect(serial=device)
        device_info = device_manager.get_device_info(connected)
        device_manager.check_wechat(connected)

        callbacks.log("正在启动微信...")
        if device_manager.launch_wechat(connected):
            callbacks.log("✅ 微信已启动")
        else:
            callbacks.log("⚠️  微信启动失败，请手动打开微信")

        folder_name = f"{since_date.isoformat()}_{today.isoformat()}"
        batch_dir = Path(output_dir) / folder_name
        batch_dir.mkdir(parents=True, exist_ok=True)
        callbacks.log(f"输出目录: {batch_dir}")

        extract_all_chats(
            connected,
            config,
            since_date,
            str(batch_dir),
            device_info,
            callbacks,
            max_chats=max_chats,
            include_list=include_list,
            exclude_list=exclude_list,
            max_scrolls=max_scrolls,
            max_list_scrolls=max_list_scrolls,
        )

        if summarize:
            callbacks.log("提示: --summarize 将在后续版本支持。")

    except KeyboardInterrupt:
        sys.exit(130)
    except DeviceNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except (StabilityError, ExtractionError, CalibrationError) as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        callbacks.log(f"错误: {exc}")
        sys.exit(1)


@cli.command()
@click.option("--device", default=None, help="Device serial (auto-detect if not specified)")
@click.option(
    "--config",
    "config_path",
    default="./wechat_selectors.yaml",
    help="Output config file path",
)
def calibrate(device: str | None, config_path: str):
    """Auto-detect WeChat resource IDs and save to config file."""

    try:
        click.echo("正在连接设备...")
        device_manager = DeviceManager()
        connected = device_manager.connect(serial=device)
        device_info = device_manager.get_device_info(connected)

        click.echo()
        click.echo('[1/3] 请打开微信消息列表界面（确保"公众号"可见），然后按回车...')
        input()

        click.echo("  → 正在 dump UI 层级...")
        message_list_xml = stable_dump(connected)

        calibrator = Calibrator()
        msg_list_config = calibrator.calibrate_message_list(message_list_xml)

        click.echo(f"  ✅ 会话容器 (container): {_id_tail(msg_list_config.container)}")
        click.echo(f"  ✅ 会话项 (chat_item): {_id_tail(msg_list_config.chat_item)}")
        click.echo(f"  ✅ 会话名称 (chat_name): {_id_tail(msg_list_config.chat_name)}")
        click.echo(f"  ✅ 时间标签 (last_time): {_id_tail(msg_list_config.last_time)}")
        click.echo(f"  ✅ 预览文本 (last_preview): {_id_tail(msg_list_config.last_preview)}")
        click.echo(f"  ✅ 徽标图标 (badge): {_id_tail(msg_list_config.badge)}")
        click.echo(f"  ✅ 微信标签 (wechat_tab): {_id_tail(msg_list_config.chat_name)}")

        click.echo()
        click.echo('[2/3] 请进入任意个人聊天，发送"谢谢"两字，然后按回车...')
        input()

        click.echo("  → 正在 dump UI 层级...")
        personal_chat_xml = stable_dump(connected)
        chat_view_config = calibrator.calibrate_chat_view(personal_chat_xml, anchor_text="谢谢")

        click.echo(
            f"  ✅ 消息容器 (message_container): {_id_tail(chat_view_config.message_container)}"
        )
        click.echo(f"  ✅ 消息包装 (message_wrapper): {_id_tail(chat_view_config.message_wrapper)}")
        click.echo(f"  ✅ 消息布局 (message_layout): {_id_tail(chat_view_config.message_layout)}")
        click.echo(f"  ✅ 消息文本 (message_text): {_id_tail(chat_view_config.message_text)}")
        click.echo(
            f"  ✅ 头像容器 (avatar_container): {_id_tail(chat_view_config.avatar_container)}"
        )
        click.echo(f"  ✅ 头像图片 (avatar_image): {_id_tail(chat_view_config.avatar_image)}")
        click.echo(f"  ✅ 时间戳 (timestamp): {_id_tail(chat_view_config.timestamp)}")
        click.echo(f"  ✅ 输入框 (input_box): {_id_tail(chat_view_config.input_box)}")
        click.echo(
            f"  ✅ 返回按钮 (back_button): {_id_tail('com.tencent.mm:id/actionbar_up_indicator')}"
        )

        click.echo()
        click.echo('[3/3] 请进入任意群聊，发送"谢谢"两字，然后按回车...')
        input()

        click.echo("  → 正在 dump UI 层级...")
        group_chat_xml = stable_dump(connected)
        group_view_config = calibrator.calibrate_chat_view(group_chat_xml, anchor_text="谢谢")

        # Merge: use personal chat IDs as base, overlay group-specific IDs
        if group_view_config.sender_name != ChatViewConfig().sender_name:
            chat_view_config.sender_name = group_view_config.sender_name
            click.echo(f"  ✅ 群发送者 (sender_name): {_id_tail(chat_view_config.sender_name)}")
        else:
            click.echo("  ⚠️  未检测到群发送者 ID，请确认在群聊中发送了消息")

        # Cross-validate: key IDs should match between personal and group
        mismatches = []
        for field_name in ("message_container", "message_text", "avatar_image", "input_box"):
            personal_val = getattr(chat_view_config, field_name)
            group_val = getattr(group_view_config, field_name)
            if personal_val != group_val:
                mismatches.append(
                    f"  {field_name}: 个人={_id_tail(personal_val)} 群聊={_id_tail(group_val)}"
                )
        if mismatches:
            click.echo("  ⚠️  个人/群聊 ID 不一致:")
            for m in mismatches:
                click.echo(m)

        # Navigation: detect from both XMLs
        nav_config = calibrator.calibrate_navigation(message_list_xml, personal_chat_xml)

        config = SelectorConfig(
            message_list=msg_list_config,
            chat_view=chat_view_config,
            navigation=nav_config,
            device_info=device_info,
            calibrated_at=datetime.now().isoformat(timespec="seconds"),
        )
        saved_path = config.save(config_path)
        click.echo(f"\n配置已保存至: {saved_path}")
        click.echo("如需微调，可直接编辑该文件。")
    except (CalibrationError, StabilityError, DeviceNotFoundError, WeChatSummaryError) as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\n已取消校准。")
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"错误: {exc}")
        sys.exit(1)


@cli.command()
@click.option(
    "--input",
    "input_file",
    required=True,
    type=click.Path(exists=True),
    help="Path to JSON chat session file",
)
@click.option("--output-dir", default="./output", help="Output directory")
@click.option(
    "--base-url",
    default="http://localhost:11434/v1",
    envvar="WECHAT_LLM_BASE_URL",
    help="LLM API base URL",
)
@click.option(
    "--model",
    default="qwen2.5",
    envvar="WECHAT_LLM_MODEL",
    help="LLM model name",
)
@click.option(
    "--api-key",
    default="ollama",
    envvar="WECHAT_LLM_API_KEY",
    help="LLM API key (default: 'ollama')",
)
@click.option(
    "--system-prompt",
    default=None,
    type=click.Path(exists=True),
    help="Custom system prompt file (plain text)",
)
@click.option(
    "--user-template",
    default=None,
    type=click.Path(exists=True),
    help="Custom user template file (use {chat_name} and {messages} placeholders)",
)
def summarize(
    input_file: str,
    output_dir: str,
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str | None,
    user_template: str | None,
):
    """Summarize a previously extracted chat session."""
    callbacks = CLICallbacks()
    try:
        llm_config = LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.3,
            max_tokens=4096,
        )

        summarize_file(
            input_file,
            output_dir,
            llm_config,
            callbacks,
            system_prompt_file=system_prompt,
            user_template_file=user_template,
        )
    except DeviceNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        callbacks.log(f"错误: {exc}")
        callbacks.log("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except (StabilityError, ExtractionError) as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        callbacks.log(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        callbacks.log(f"错误: {exc}")
        sys.exit(1)


@cli.command()
def gui():
    """Launch the graphical user interface."""
    from wechat_summary.gui import WeChatSummaryGUI

    app = WeChatSummaryGUI()
    app.run()


__all__ = ["calibrate", "cli", "extract", "extract_all", "gui", "summarize"]
