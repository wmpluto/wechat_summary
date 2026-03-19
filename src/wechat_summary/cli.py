"""Click CLI for WeChat chat extraction and summarization."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
import sys
from pathlib import Path
from typing import Any

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
from wechat_summary.extractor import MessageExtractor
from wechat_summary.llm_client import LLMClient
from wechat_summary.models import ChatListItem, ChatSession, ChatType, ExtractionConfig, LLMConfig
from wechat_summary.navigator import ChatListNavigator
from wechat_summary.persistence import ChatSessionStore
from wechat_summary.selectors import stable_dump
from wechat_summary.summarizer import ChatSummarizer


def _format_metadata_time(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _write_summary_outputs(
    session: ChatSession,
    summary_text: str,
    output_dir: str,
    target_stem: str,
) -> tuple[Path, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    first_ts = _format_metadata_time(session.messages[0].timestamp) if session.messages else "N/A"
    last_ts = _format_metadata_time(session.messages[-1].timestamp) if session.messages else "N/A"

    md_content = (
        f"# 聊天记录总结: {session.chat_name}\n\n"
        f"**提取时间**: {session.extracted_at.strftime('%Y-%m-%d %H:%M:%S')}  |  "
        f"**消息数量**: {len(session.messages)}  |  "
        f"**时间范围**: {first_ts} ~ {last_ts}\n\n"
        "## 总结\n\n"
        f"{summary_text}\n"
    )

    md_path = output_path / f"{target_stem}_summary.md"
    json_path = output_path / f"{target_stem}_summary.json"

    md_path.write_text(md_content, encoding="utf-8")
    json_path.write_text(
        json.dumps({"summary": summary_text}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return md_path, json_path


def _id_tail(resource_id: str) -> str:
    if "/" in resource_id:
        return resource_id.rsplit("/", maxsplit=1)[-1]
    return resource_id


def _sanitize_filename(name: str) -> str:
    """Sanitize chat name for use as filename."""

    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = sanitized.strip(". ")
    return sanitized or "unknown"


def _save_chat_json(
    chat_name: str,
    messages: list,
    device_info: str,
    batch_dir: Path,
    *,
    partial: bool = False,
) -> Path:
    """Save messages as a ChatSession JSON file. Returns the saved path."""
    session = ChatSession(
        chat_name=chat_name,
        chat_type=ChatType.PRIVATE,
        messages=messages,
        extracted_at=datetime.now(),
        device_info=device_info,
    )
    sanitized = _sanitize_filename(chat_name)
    suffix = "_partial" if partial else ""
    filepath = batch_dir / f"{sanitized}{suffix}.json"
    filepath.write_text(
        session.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )
    click.echo(f"  💾 已保存: {filepath}")
    return filepath


def _process_single_chat(
    device: Any,
    navigator: ChatListNavigator,
    extractor: MessageExtractor,
    store: ChatSessionStore,
    item: ChatListItem,
    since_date: date,
    batch_dir: Path,
    device_info: str,
) -> tuple[bool, int]:
    """Enter chat, extract messages, save JSON, and exit chat."""

    _ = store
    messages: list = []
    try:
        click.echo(f"  📥 enter_chat: {item.name}")
        if not navigator.enter_chat(device, item):
            click.echo(f"  ❌ 进入聊天失败: {item.name}")
            return False, 0

        click.echo(f"  📜 scroll_and_extract: since={since_date}")
        messages = extractor.scroll_and_extract(device, since_date)
        click.echo(f"  📊 提取结果: {len(messages)} 条消息")

        if messages:
            _save_chat_json(item.name, messages, device_info, batch_dir)
        else:
            click.echo("  ⚠️  无消息（可能该时间范围内无聊天记录）")

        navigator.exit_chat(device)
        return True, len(messages)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        click.echo(f"  ❌ 提取异常: {type(exc).__name__}: {exc}")
        # Save whatever we collected before the error
        if messages:
            click.echo(f"  💾 正在保存已提取的 {len(messages)} 条消息...")
            _save_chat_json(item.name, messages, device_info, batch_dir, partial=True)
        try:
            navigator.exit_chat(device)
        except Exception:  # noqa: BLE001
            click.echo("  ❌ exit_chat 也失败了")
        return False, len(messages)


def _process_folded_chats(
    device: Any,
    navigator: ChatListNavigator,
    extractor: MessageExtractor,
    store: ChatSessionStore,
    since_date: date,
    batch_dir: Path,
    device_info: str,
    include_list: list[str] | None,
    exclude_list: list[str] | None,
    max_chats_remaining: int | None,
) -> tuple[int, int, list[str]]:
    """Process all qualifying chats inside the folded chats view."""

    chats = 0
    messages = 0
    failed: list[str] = []

    items = navigator.parse_folded_list(device)
    filtered = navigator.filter_items(items, since_date, include_list, exclude_list)

    for item in filtered:
        if navigator.is_processed(item.name):
            continue
        if max_chats_remaining is not None and chats >= max_chats_remaining:
            break

        chats += 1
        click.echo(f"  📂 折叠 ({chats}) {item.name}...")
        success, count = _process_single_chat(
            device,
            navigator,
            extractor,
            store,
            item,
            since_date,
            batch_dir,
            device_info,
        )
        if success:
            messages += count
            click.echo(f"    ✅ {count} 条消息")
        else:
            failed.append(item.name)
            click.echo("    ❌ 提取失败")
        navigator.mark_processed(item.name)

    return chats, messages, failed


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
    store = ChatSessionStore()
    messages = []
    resolved_chat_name = "未知会话"
    chat_type = ChatType.PRIVATE
    connected_device = None
    device_info = "Unknown"
    filepath: str | None = None

    try:
        extraction_config = ExtractionConfig(since_date=since.date(), scroll_delay=1.0)
        llm_config = LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.3,
            max_tokens=4096,
        )

        click.echo("正在连接设备...")
        device_manager = DeviceManager()
        connected_device = device_manager.connect(serial=device)
        device_info = device_manager.get_device_info(connected_device)

        click.echo("正在检查微信...")
        device_manager.check_wechat(connected_device)

        click.echo("正在检测聊天信息...")
        config = load_config(config_path)
        extractor_kwargs: dict[str, Any] = {"config": config}
        if max_scrolls is not None:
            extractor_kwargs["max_scrolls"] = max_scrolls
        extractor = MessageExtractor(**extractor_kwargs)
        if chat_name:
            resolved_chat_name = chat_name.strip() or "未知会话"
        else:
            resolved_chat_name, chat_type = extractor.detect_chat_info(connected_device)
            resolved_chat_name = resolved_chat_name.strip() or "未知会话"

        click.echo(f"正在提取消息 (从 {since.strftime('%Y-%m-%d')} 至今)...")
        since_date = extraction_config.since_date
        messages = extractor.scroll_and_extract(connected_device, since_date)
        click.echo(f"提取完成，共 {len(messages)} 条消息")
        try:
            unrecognized = int(extractor.unrecognized_count)
        except (TypeError, ValueError):
            unrecognized = 0
        if unrecognized > 0:
            click.echo(f"⚠️  有 {unrecognized} 条消息无法识别类型，已标记为 [未识别消息]")

        session = ChatSession(
            chat_name=resolved_chat_name,
            chat_type=chat_type if isinstance(chat_type, ChatType) else ChatType(chat_type),
            messages=messages,
            extracted_at=datetime.now(),
            device_info=device_info,
        )

        filepath = store.save(session, output_dir=output_dir)
        click.echo(f"数据已保存至: {filepath}")

        if summarize:
            llm_client = LLMClient(llm_config.base_url, llm_config.api_key, llm_config.model)
            summary = ChatSummarizer(llm_client).summarize(session)
            target_stem = Path(filepath).stem
            md_path, json_path = _write_summary_outputs(
                session,
                summary.summary,
                output_dir,
                target_stem,
            )
            click.echo(f"总结已保存至: {md_path}")
            click.echo(f"JSON已保存至: {json_path}")
    except KeyboardInterrupt:
        click.echo("\n正在保存已提取的数据...")
        if messages:
            partial_session = ChatSession(
                chat_name=resolved_chat_name,
                chat_type=chat_type if isinstance(chat_type, ChatType) else ChatType(chat_type),
                messages=messages,
                extracted_at=datetime.now(),
                device_info=device_info,
            )
            partial_path = store.save_partial(partial_session, output_dir=output_dir)
            click.echo(f"\n提取已中断。已提取的 {len(messages)} 条消息已保存至: {partial_path}")
        else:
            click.echo("没有已提取的消息可保存。")
        sys.exit(130)
    except DeviceNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        click.echo(f"错误: {exc}")
        if filepath:
            click.echo(f"原始数据已保存至: {filepath}")
        sys.exit(1)
    except (StabilityError, ExtractionError, CalibrationError) as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"错误: {exc}")
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
    total_chats = 0
    total_messages = 0
    batch_dir = Path(output_dir)
    failed_chats: list[str] = []

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
            click.echo(f"已加载排除名单: {exclude_file_path} ({len(file_patterns)} 条规则)")
        elif exclude_file and exclude_file != "./exclude.txt":
            # Only warn if user explicitly specified a file that doesn't exist
            click.echo(f"⚠️  排除名单文件不存在: {exclude_file}")

        exclude_list = exclude_list or None

        click.echo("正在连接设备...")
        device_manager = DeviceManager()
        connected = device_manager.connect(serial=device)
        device_info = device_manager.get_device_info(connected)
        device_manager.check_wechat(connected)

        click.echo("正在启动微信...")
        if device_manager.launch_wechat(connected):
            click.echo("✅ 微信已启动")
        else:
            click.echo("⚠️  微信启动失败，请手动打开微信")

        folder_name = f"{since_date.isoformat()}_{today.isoformat()}"
        batch_dir = Path(output_dir) / folder_name
        batch_dir.mkdir(parents=True, exist_ok=True)
        click.echo(f"输出目录: {batch_dir}")

        navigator = ChatListNavigator(config=config)
        extractor_kwargs: dict[str, Any] = {"config": config}
        if max_scrolls is not None:
            extractor_kwargs["max_scrolls"] = max_scrolls
        extractor = MessageExtractor(**extractor_kwargs)
        store = ChatSessionStore()

        reached_max = False

        for _ in range(max_list_scrolls):
            items = navigator.parse_chat_list(connected)
            if not items:
                break

            filtered = navigator.filter_items(items, since_date, include_list, exclude_list)
            stop_scrolling = navigator.should_stop_scrolling(items, since_date)

            for item in filtered:
                if navigator.is_processed(item.name):
                    continue

                if max_chats and total_chats >= max_chats:
                    click.echo(f"\n已达到最大数量 ({max_chats})，停止处理。")
                    reached_max = True
                    break

                if item.is_folded:
                    click.echo("\n📂 进入折叠的聊天...")
                    if navigator.enter_folded_chats(connected):
                        remaining = None if max_chats is None else max_chats - total_chats
                        folded_chats, folded_messages, folded_failed = _process_folded_chats(
                            connected,
                            navigator,
                            extractor,
                            store,
                            since_date,
                            batch_dir,
                            device_info,
                            include_list,
                            exclude_list,
                            remaining,
                        )
                        total_chats += folded_chats
                        total_messages += folded_messages
                        failed_chats.extend(folded_failed)
                        navigator.exit_folded_chats(connected)
                    navigator.mark_processed(item.name)
                    continue

                total_chats += 1
                click.echo(f"\n💬 ({total_chats}) {item.name}...")
                success, msg_count = _process_single_chat(
                    connected,
                    navigator,
                    extractor,
                    store,
                    item,
                    since_date,
                    batch_dir,
                    device_info,
                )
                if success:
                    total_messages += msg_count
                    click.echo(f"  ✅ {msg_count} 条消息")
                else:
                    failed_chats.append(item.name)
                    click.echo("  ❌ 提取失败")
                navigator.mark_processed(item.name)

            if reached_max:
                break
            if stop_scrolling:
                break
            if not navigator.scroll_chat_list(connected):
                break

        if summarize:
            click.echo("提示: --summarize 将在后续版本支持。")

        click.echo(f"\n{'=' * 40}")
        click.echo(f"完成！共处理 {total_chats} 个会话，提取 {total_messages} 条消息")
        click.echo(f"输出目录: {batch_dir}")
        if failed_chats:
            click.echo(f"⚠️  {len(failed_chats)} 个会话处理失败: {', '.join(failed_chats)}")

    except KeyboardInterrupt:
        click.echo(f"\n\n已中断。已处理 {total_chats} 个会话，提取 {total_messages} 条消息。")
        click.echo(f"输出目录: {batch_dir}")
        sys.exit(130)
    except DeviceNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except (StabilityError, ExtractionError, CalibrationError) as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"错误: {exc}")
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
    try:
        llm_config = LLMConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=0.3,
            max_tokens=4096,
        )

        click.echo(f"正在加载: {input_file}")
        store = ChatSessionStore()
        session = store.load(input_file)

        click.echo("正在连接LLM...")
        llm_client = LLMClient(llm_config.base_url, llm_config.api_key, llm_config.model)

        click.echo("正在生成总结...")
        if system_prompt or user_template:
            summarizer = ChatSummarizer.from_prompt_files(
                llm_client,
                system_prompt_file=system_prompt,
                user_template_file=user_template,
            )
        else:
            summarizer = ChatSummarizer(llm_client)
        summary = summarizer.summarize(session)

        input_stem = Path(input_file).stem
        md_path, json_path = _write_summary_outputs(
            session,
            summary.summary,
            output_dir,
            input_stem,
        )
        click.echo(f"总结已保存至: {md_path}")
        click.echo(f"JSON已保存至: {json_path}")
    except DeviceNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请检查 USB 连接，并运行 'adb devices' 确认设备是否在线。")
        sys.exit(1)
    except WeChatNotFoundError as exc:
        click.echo(f"错误: {exc}")
        click.echo("请确认设备已安装微信 (com.tencent.mm) 并可正常启动。")
        sys.exit(1)
    except LLMConnectionError as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except (StabilityError, ExtractionError) as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except WeChatSummaryError as exc:
        click.echo(f"错误: {exc}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"错误: {exc}")
        sys.exit(1)


@cli.command()
def gui():
    """Launch the graphical user interface."""
    from wechat_summary.gui import WeChatSummaryGUI

    app = WeChatSummaryGUI()
    app.run()


__all__ = ["calibrate", "cli", "extract", "extract_all", "gui", "summarize"]
