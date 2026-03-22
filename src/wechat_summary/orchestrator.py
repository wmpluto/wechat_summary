from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from pathlib import Path
from queue import Queue
from typing import Any, Protocol

from wechat_summary.config import SelectorConfig
from wechat_summary.exceptions import LLMConnectionError
from wechat_summary.extractor import MessageExtractor
from wechat_summary.llm_client import LLMClient
from wechat_summary.models import ChatListItem, ChatSession, ChatType, LLMConfig, SummaryResult
from wechat_summary.navigator import ChatListNavigator
from wechat_summary.persistence import ChatSessionStore
from wechat_summary.summarizer import ChatSummarizer


class OrchestratorCallbacks(Protocol):
    def log(self, message: str) -> None: ...

    def should_stop(self) -> bool: ...


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


def _sanitize_filename(name: str) -> str:
    """Sanitize chat name for use as filename."""

    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = sanitized.strip(". ")
    return sanitized or "unknown"


def _message_content_hash(msg: Any) -> str:
    """Hash a message by sender+content+type for deduplication."""
    sender = getattr(msg, "sender", "") or ""
    content = getattr(msg, "content", "") or ""
    mtype_raw = getattr(msg, "message_type", "")
    mtype = str(getattr(mtype_raw, "value", mtype_raw))
    return f"{sender}|{content}|{mtype}"


def _save_chat_json(
    chat_name: str,
    messages: list,
    device_info: str,
    batch_dir: Path,
    callbacks: OrchestratorCallbacks,
    *,
    partial: bool = False,
) -> Path:
    """Save messages as a ChatSession JSON file with incremental merge."""
    sanitized = _sanitize_filename(chat_name)
    suffix = "_partial" if partial else ""
    filepath = batch_dir / f"{sanitized}{suffix}.json"

    merged_messages = list(messages)
    if filepath.exists():
        try:
            old_session = ChatSession.model_validate_json(filepath.read_text(encoding="utf-8"))
            new_hashes = {_message_content_hash(m) for m in messages}
            old_unique = [
                m for m in old_session.messages if _message_content_hash(m) not in new_hashes
            ]
            if old_unique:
                merged_messages = old_unique + list(messages)
                callbacks.log(
                    f"  📎 增量合并: 旧={len(old_session.messages)} "
                    f"新={len(messages)} → 合计={len(merged_messages)}"
                )
        except Exception:  # noqa: BLE001
            pass

    session = ChatSession(
        chat_name=chat_name,
        chat_type=ChatType.PRIVATE,
        messages=merged_messages,
        extracted_at=datetime.now(),
        device_info=device_info,
    )
    filepath.write_text(
        session.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )
    callbacks.log(f"  💾 已保存: {filepath}")
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
    callbacks: OrchestratorCallbacks,
) -> tuple[bool, int, Path | None]:
    """Enter chat, extract messages, save JSON, and exit chat."""

    _ = store
    messages: list = []
    try:
        callbacks.log(f"  📥 enter_chat: {item.name}")
        if not navigator.enter_chat(device, item):
            callbacks.log(f"  ❌ 进入聊天失败: {item.name}")
            return False, 0, None

        callbacks.log(f"  📜 scroll_and_extract: since={since_date}")
        messages = extractor.scroll_and_extract(device, since_date)
        callbacks.log(f"  📊 提取结果: {len(messages)} 条消息")

        if messages:
            filepath = _save_chat_json(item.name, messages, device_info, batch_dir, callbacks)
        else:
            filepath = None
            callbacks.log("  ⚠️  无消息（可能该时间范围内无聊天记录）")

        navigator.exit_chat(device)
        return True, len(messages), filepath
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        callbacks.log(f"  ❌ 提取异常: {type(exc).__name__}: {exc}")
        filepath: Path | None = None
        if messages:
            callbacks.log(f"  💾 正在保存已提取的 {len(messages)} 条消息...")
            filepath = _save_chat_json(
                item.name,
                messages,
                device_info,
                batch_dir,
                callbacks,
                partial=True,
            )
        try:
            navigator.exit_chat(device)
        except Exception:  # noqa: BLE001
            callbacks.log("  ❌ exit_chat 也失败了")
        return False, len(messages), filepath


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
    callbacks: OrchestratorCallbacks,
    summary_queue: Queue | None = None,
) -> tuple[int, int, list[str]]:
    """Process all qualifying chats inside the folded chats view."""

    chats = 0
    messages = 0
    failed: list[str] = []

    items = navigator.parse_folded_list(device)
    filtered = navigator.filter_items(items, since_date, include_list, exclude_list)

    for item in filtered:
        if callbacks.should_stop():
            callbacks.log("⏹ 已停止")
            break
        if navigator.is_processed(item.name):
            continue
        if max_chats_remaining is not None and chats >= max_chats_remaining:
            break

        chats += 1
        callbacks.log(f"  📂 折叠 ({chats}) {item.name}...")
        success, count, filepath = _process_single_chat(
            device,
            navigator,
            extractor,
            store,
            item,
            since_date,
            batch_dir,
            device_info,
            callbacks,
        )
        if success:
            messages += count
            callbacks.log(f"    ✅ {count} 条消息")
            if summary_queue is not None and filepath is not None and count > 0:
                summary_queue.put(filepath)
        else:
            failed.append(item.name)
            callbacks.log("    ❌ 提取失败")
        navigator.mark_processed(item.name)

    return chats, messages, failed


def summarize_session(
    session: ChatSession,
    llm_config: LLMConfig,
    callbacks: OrchestratorCallbacks,
    *,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> SummaryResult:
    callbacks.log("正在连接LLM...")
    llm_client = LLMClient(llm_config.base_url, llm_config.api_key, llm_config.model)

    callbacks.log("正在生成总结...")
    if system_prompt_file or user_template_file:
        summarizer = ChatSummarizer.from_prompt_files(
            llm_client,
            system_prompt_file=system_prompt_file,
            user_template_file=user_template_file,
        )
    else:
        summarizer = ChatSummarizer(llm_client)
    return summarizer.summarize(session)


def summarize_file(
    input_file: str,
    output_dir: str,
    llm_config: LLMConfig,
    callbacks: OrchestratorCallbacks,
    *,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> tuple[Path, Path]:
    callbacks.log(f"正在加载: {input_file}")
    store = ChatSessionStore()
    session = store.load(input_file)
    summary = summarize_session(
        session,
        llm_config,
        callbacks,
        system_prompt_file=system_prompt_file,
        user_template_file=user_template_file,
    )

    input_stem = Path(input_file).stem
    md_path, json_path = _write_summary_outputs(session, summary.summary, output_dir, input_stem)
    callbacks.log(f"总结已保存至: {md_path}")
    callbacks.log(f"JSON已保存至: {json_path}")
    return md_path, json_path


def summarize_one(
    json_path: str | Path,
    summary_dir: str | Path,
    llm_config: LLMConfig,
    callbacks: OrchestratorCallbacks,
    *,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> tuple[Path, Path] | None:
    """Summarize a single chat JSON file.

    Writes to summary_dir/{stem}_summary.md and summary_dir/{stem}_summary.json.
    Returns (md_path, json_path) on success, None if skipped or failed.
    Skips if summary_dir/{stem}_summary.md already exists.
    Never raises — logs errors and returns None.
    """
    json_path = Path(json_path)
    summary_dir = Path(summary_dir)
    summary_dir.mkdir(parents=True, exist_ok=True)

    stem = json_path.stem
    md_path = summary_dir / f"{stem}_summary.md"
    if md_path.exists():
        callbacks.log(f"  ⏭ 跳过 (已有总结): {stem}")
        return None

    try:
        callbacks.log(f"  📝 正在总结: {stem}...")
        session = ChatSession.model_validate_json(json_path.read_text(encoding="utf-8"))
        result = summarize_session(
            session,
            llm_config,
            callbacks,
            system_prompt_file=system_prompt_file,
            user_template_file=user_template_file,
        )
        md_p, json_p = _write_summary_outputs(session, result.summary, str(summary_dir), stem)
        callbacks.log(f"  ✅ 总结完成: {stem}")
        return md_p, json_p
    except Exception as exc:  # noqa: BLE001
        callbacks.log(f"  ⚠️ 总结失败 ({stem}): {exc}")
        return None


def summarize_folder(
    input_dir: str | Path,
    llm_config: LLMConfig,
    callbacks: OrchestratorCallbacks,
    *,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> tuple[int, int, int]:
    """Summarize all chat JSONs in a directory.

    Writes summaries to input_dir/summary/.
    Skips files already summarized and *_partial.json files.
    Returns (succeeded, skipped, failed).
    """
    input_dir = Path(input_dir)
    summary_dir = input_dir / "summary"

    json_files = sorted(
        [f for f in input_dir.glob("*.json") if not f.name.endswith("_partial.json")],
        key=lambda f: f.stat().st_mtime,
    )

    if not json_files:
        callbacks.log("未找到聊天记录 JSON 文件")
        return 0, 0, 0

    succeeded = 0
    skipped = 0
    failed = 0

    callbacks.log(f"扫描到 {len(json_files)} 个聊天记录")

    for json_file in json_files:
        if callbacks.should_stop():
            callbacks.log("⏹ 已停止")
            break
        stem = json_file.stem
        md_check = summary_dir / f"{stem}_summary.md"
        if md_check.exists():
            callbacks.log(f"  ⏭ 跳过 (已有总结): {stem}")
            skipped += 1
            continue
        result = summarize_one(
            json_file,
            summary_dir,
            llm_config,
            callbacks,
            system_prompt_file=system_prompt_file,
            user_template_file=user_template_file,
        )
        if result is not None:
            succeeded += 1
        else:
            failed += 1

    callbacks.log(f"\n{'=' * 40}")
    callbacks.log(f"总结完成: {succeeded} 成功, {skipped} 跳过, {failed} 失败")
    return succeeded, skipped, failed


def _summarize_worker(
    summary_queue: Queue,
    summary_dir: Path,
    llm_config: LLMConfig,
    callbacks: OrchestratorCallbacks,
    *,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> None:
    """Background worker that consumes filepaths from queue and summarizes them."""
    while True:
        filepath = summary_queue.get()
        if filepath is None:
            summary_queue.task_done()
            break
        try:
            summarize_one(
                filepath,
                summary_dir,
                llm_config,
                callbacks,
                system_prompt_file=system_prompt_file,
                user_template_file=user_template_file,
            )
        except Exception as exc:  # noqa: BLE001
            callbacks.log(f"  ⚠️ 总结异常: {exc}")
        finally:
            summary_queue.task_done()


def extract_single(
    device: Any,
    config: SelectorConfig,
    since_date: date,
    chat_name: str | None,
    output_dir: str,
    device_info: str,
    callbacks: OrchestratorCallbacks,
    *,
    max_scrolls: int | None = None,
    summarize: bool = False,
    llm_config: LLMConfig | None = None,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> tuple[ChatSession | None, str | None]:
    store = ChatSessionStore()
    messages: list = []
    resolved_chat_name = "未知会话"
    chat_type = ChatType.PRIVATE

    try:
        callbacks.log("正在检测聊天信息...")
        extractor_kwargs: dict[str, Any] = {"config": config}
        if max_scrolls is not None:
            extractor_kwargs["max_scrolls"] = max_scrolls
        extractor = MessageExtractor(**extractor_kwargs)

        if chat_name:
            resolved_chat_name = chat_name.strip() or "未知会话"
        else:
            resolved_chat_name, chat_type = extractor.detect_chat_info(device)
            resolved_chat_name = resolved_chat_name.strip() or "未知会话"

        callbacks.log(f"正在提取消息 (从 {since_date.strftime('%Y-%m-%d')} 至今)...")
        messages = extractor.scroll_and_extract(device, since_date)
        callbacks.log(f"提取完成，共 {len(messages)} 条消息")

        try:
            unrecognized = int(extractor.unrecognized_count)
        except (TypeError, ValueError):
            unrecognized = 0
        if unrecognized > 0:
            callbacks.log(f"⚠️  有 {unrecognized} 条消息无法识别类型，已标记为 [未识别消息]")

        session = ChatSession(
            chat_name=resolved_chat_name,
            chat_type=chat_type if isinstance(chat_type, ChatType) else ChatType(chat_type),
            messages=messages,
            extracted_at=datetime.now(),
            device_info=device_info,
        )

        filepath = store.save(session, output_dir=output_dir)
        callbacks.log(f"数据已保存至: {filepath}")

        if summarize:
            if llm_config is None:
                raise ValueError("llm_config is required when summarize=True")
            try:
                summary = summarize_session(
                    session,
                    llm_config,
                    callbacks,
                    system_prompt_file=system_prompt_file,
                    user_template_file=user_template_file,
                )
            except LLMConnectionError:
                callbacks.log(f"原始数据已保存至: {filepath}")
                raise
            target_stem = Path(filepath).stem
            md_path, json_path = _write_summary_outputs(
                session,
                summary.summary,
                output_dir,
                target_stem,
            )
            callbacks.log(f"总结已保存至: {md_path}")
            callbacks.log(f"JSON已保存至: {json_path}")

        return session, filepath
    except KeyboardInterrupt:
        callbacks.log("\n正在保存已提取的数据...")
        if messages:
            partial_session = ChatSession(
                chat_name=resolved_chat_name,
                chat_type=chat_type if isinstance(chat_type, ChatType) else ChatType(chat_type),
                messages=messages,
                extracted_at=datetime.now(),
                device_info=device_info,
            )
            partial_path = store.save_partial(partial_session, output_dir=output_dir)
            callbacks.log(f"\n提取已中断。已提取的 {len(messages)} 条消息已保存至: {partial_path}")
        else:
            callbacks.log("没有已提取的消息可保存。")
        raise


def extract_all_chats(
    device: Any,
    config: SelectorConfig,
    since_date: date,
    output_dir: str,
    device_info: str,
    callbacks: OrchestratorCallbacks,
    *,
    max_chats: int | None = None,
    include_list: list[str] | None = None,
    exclude_list: list[str] | None = None,
    max_scrolls: int | None = None,
    max_list_scrolls: int = 1000,
    summarize: bool = False,
    llm_config: LLMConfig | None = None,
    system_prompt_file: str | None = None,
    user_template_file: str | None = None,
) -> tuple[int, int, list[str]]:
    total_chats = 0
    total_messages = 0
    batch_dir = Path(output_dir)
    failed_chats: list[str] = []

    batch_dir.mkdir(parents=True, exist_ok=True)

    navigator = ChatListNavigator(config=config)
    extractor_kwargs: dict[str, Any] = {"config": config}
    if max_scrolls is not None:
        extractor_kwargs["max_scrolls"] = max_scrolls
    extractor = MessageExtractor(**extractor_kwargs)
    store = ChatSessionStore()

    summary_queue: Queue | None = None
    summary_thread: threading.Thread | None = None
    summary_stopped = False

    def _stop_summary_thread() -> None:
        nonlocal summary_stopped
        if summary_stopped:
            return
        if summary_queue is not None and summary_thread is not None:
            summary_queue.put(None)
            callbacks.log("⏳ 等待总结线程完成...")
            summary_thread.join()
            callbacks.log("✅ 总结线程已结束")
        summary_stopped = True

    if summarize:
        if llm_config is None:
            raise ValueError("llm_config is required when summarize=True")
        summary_dir = batch_dir / "summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_queue = Queue()
        summary_thread = threading.Thread(
            target=_summarize_worker,
            args=(summary_queue, summary_dir, llm_config, callbacks),
            kwargs={
                "system_prompt_file": system_prompt_file,
                "user_template_file": user_template_file,
            },
            daemon=True,
        )
        summary_thread.start()
        callbacks.log(f"📝 总结输出目录: {summary_dir}")

    try:
        reached_max = False
        for _ in range(max_list_scrolls):
            if callbacks.should_stop():
                callbacks.log("⏹ 已停止")
                break

            items = navigator.parse_chat_list(device)
            if not items:
                break

            filtered = navigator.filter_items(items, since_date, include_list, exclude_list)
            stop_scrolling = navigator.should_stop_scrolling(items, since_date)

            for item in filtered:
                if callbacks.should_stop():
                    callbacks.log("⏹ 已停止")
                    reached_max = True
                    break

                if navigator.is_processed(item.name):
                    continue

                if max_chats is not None and total_chats >= max_chats:
                    callbacks.log(f"\n已达到最大数量 ({max_chats})，停止处理。")
                    reached_max = True
                    break

                if item.is_folded:
                    callbacks.log("\n📂 进入折叠的聊天...")
                    if navigator.enter_folded_chats(device):
                        remaining = None if max_chats is None else max_chats - total_chats
                        folded_chats, folded_messages, folded_failed = _process_folded_chats(
                            device,
                            navigator,
                            extractor,
                            store,
                            since_date,
                            batch_dir,
                            device_info,
                            include_list,
                            exclude_list,
                            remaining,
                            callbacks,
                            summary_queue=summary_queue,
                        )
                        total_chats += folded_chats
                        total_messages += folded_messages
                        failed_chats.extend(folded_failed)
                        navigator.exit_folded_chats(device)
                    navigator.mark_processed(item.name)
                    continue

                total_chats += 1
                callbacks.log(f"\n💬 ({total_chats}) {item.name}...")
                success, msg_count, filepath = _process_single_chat(
                    device,
                    navigator,
                    extractor,
                    store,
                    item,
                    since_date,
                    batch_dir,
                    device_info,
                    callbacks,
                )
                if success:
                    total_messages += msg_count
                    callbacks.log(f"  ✅ {msg_count} 条消息")
                    if summary_queue is not None and filepath is not None and msg_count > 0:
                        summary_queue.put(filepath)
                else:
                    failed_chats.append(item.name)
                    callbacks.log("  ❌ 提取失败")
                navigator.mark_processed(item.name)

            if reached_max:
                break
            if stop_scrolling:
                break
            if not navigator.scroll_chat_list(device):
                break
    except KeyboardInterrupt:
        _stop_summary_thread()
        callbacks.log(f"\n\n已中断。已处理 {total_chats} 个会话，提取 {total_messages} 条消息。")
        callbacks.log(f"输出目录: {batch_dir}")
        raise
    finally:
        _stop_summary_thread()

    callbacks.log(f"\n{'=' * 40}")
    callbacks.log(f"完成！共处理 {total_chats} 个会话，提取 {total_messages} 条消息")
    callbacks.log(f"输出目录: {batch_dir}")
    if failed_chats:
        callbacks.log(f"⚠️  {len(failed_chats)} 个会话处理失败: {', '.join(failed_chats)}")

    return total_chats, total_messages, failed_chats


__all__ = [
    "OrchestratorCallbacks",
    "extract_all_chats",
    "extract_single",
    "summarize_folder",
    "summarize_file",
    "summarize_one",
    "summarize_session",
]
