"""Tkinter GUI for WeChat summary workflows."""

from __future__ import annotations

import contextlib
import io
import os
from datetime import date, datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from wechat_summary.calibrator import Calibrator
from wechat_summary.config import ChatViewConfig, SelectorConfig, load_config
from wechat_summary.device import DeviceManager
from wechat_summary.models import LLMConfig
from wechat_summary.orchestrator import extract_all_chats, extract_single, summarize_file
from wechat_summary.selectors import stable_dump


class _GUILogWriter(io.TextIOBase):
    """Redirect stdout to GUI log."""

    def __init__(self, log_func):
        self._log = log_func

    def write(self, text: str) -> int:
        if text and text.strip():
            self._log(text.rstrip())
        return len(text)

    def flush(self) -> None:
        return


class GUICallbacks:
    def __init__(self, log_func, stop_event: threading.Event):
        self._log = log_func
        self._stop = stop_event

    def log(self, message: str) -> None:
        self._log(message)

    def should_stop(self) -> bool:
        return self._stop.is_set()


class WeChatSummaryGUI:
    """Single-page GUI for calibration, extraction, and summarization."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WeChat Summary Tool")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)

        self.device_var = tk.StringVar(value="")
        self.config_var = tk.StringVar(value="./wechat_selectors.yaml")
        self.since_var = tk.StringVar(value=date.today().isoformat())
        self.chat_name_var = tk.StringVar(value="")
        self.output_dir_var = tk.StringVar(value="./output")
        self.exclude_file_var = tk.StringVar(value="./exclude.txt")
        self.max_chats_var = tk.StringVar(value="")
        self.include_var = tk.StringVar(value="")
        self.exclude_var = tk.StringVar(value="")
        self.max_scrolls_var = tk.StringVar(value="")
        self.max_list_scrolls_var = tk.StringVar(value="1000")
        self.base_url_var = tk.StringVar(
            value=os.environ.get("WECHAT_LLM_BASE_URL", "http://localhost:8080/v1")
        )
        self.model_var = tk.StringVar(value=os.environ.get("WECHAT_LLM_MODEL", "Qwen3.5-35B-A3B"))
        self.api_key_var = tk.StringVar(value=os.environ.get("WECHAT_LLM_API_KEY", "no-key"))
        self.summarize_var = tk.BooleanVar(value=True)
        self.system_prompt_var = tk.StringVar(value="")
        self.user_template_var = tk.StringVar(value="")

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._calibrate_event = threading.Event()
        self._running_thread: threading.Thread | None = None

        self._action_buttons: list[ttk.Button] = []
        self._next_btn: ttk.Button | None = None

        self._build_ui()
        self.root.after(100, self._poll_log_queue)

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

        conn_frame = ttk.LabelFrame(main_frame, text="连接设置", padding=10)
        conn_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        conn_frame.columnconfigure(1, weight=1)

        ttk.Label(conn_frame, text="设备序列号:").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(conn_frame, textvariable=self.device_var).grid(
            row=0, column=1, sticky="ew", pady=4
        )

        ttk.Label(conn_frame, text="配置文件:").grid(
            row=0, column=2, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(conn_frame, textvariable=self.config_var).grid(
            row=0, column=3, sticky="ew", pady=4
        )
        conn_frame.columnconfigure(3, weight=1)
        ttk.Button(conn_frame, text="浏览", command=self._browse_config).grid(
            row=0, column=4, sticky="w", padx=(6, 0), pady=4
        )

        extract_frame = ttk.LabelFrame(main_frame, text="提取设置", padding=10)
        extract_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        extract_frame.columnconfigure(1, weight=1)
        extract_frame.columnconfigure(3, weight=1)
        extract_frame.columnconfigure(5, weight=1)

        ttk.Label(extract_frame, text="起始日期:").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.since_var, width=16).grid(
            row=0, column=1, sticky="w", pady=4
        )
        ttk.Label(extract_frame, text="聊天名称:").grid(
            row=0, column=2, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.chat_name_var).grid(
            row=0, column=3, sticky="ew", pady=4
        )

        ttk.Label(extract_frame, text="输出目录:").grid(
            row=1, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.output_dir_var).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Button(extract_frame, text="浏览", command=self._browse_output_dir).grid(
            row=1, column=2, sticky="w", padx=(6, 0), pady=4
        )
        ttk.Label(extract_frame, text="排除名单:").grid(
            row=1, column=3, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.exclude_file_var).grid(
            row=1, column=4, sticky="ew", pady=4
        )
        ttk.Button(extract_frame, text="浏览", command=self._browse_exclude_file).grid(
            row=1, column=5, sticky="w", padx=(6, 0), pady=4
        )

        ttk.Label(extract_frame, text="最大数量:").grid(
            row=2, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.max_chats_var, width=8).grid(
            row=2, column=1, sticky="w", pady=4
        )
        ttk.Label(extract_frame, text="聊天页数上限:").grid(
            row=2, column=2, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.max_scrolls_var, width=8).grid(
            row=2, column=3, sticky="w", pady=4
        )
        ttk.Label(extract_frame, text="列表滚动上限:").grid(
            row=2, column=4, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.max_list_scrolls_var, width=8).grid(
            row=2, column=5, sticky="w", pady=4
        )

        ttk.Label(extract_frame, text="仅包含:").grid(
            row=3, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.include_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=4
        )
        ttk.Label(extract_frame, text="排除:").grid(
            row=3, column=3, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(extract_frame, textvariable=self.exclude_var).grid(
            row=3, column=4, columnspan=2, sticky="ew", pady=4
        )

        # LLM 设置: 6 columns — label(0) entry(1) btn(2) label(3) entry(4) btn(5)
        llm_frame = ttk.LabelFrame(main_frame, text="LLM 设置", padding=10)
        llm_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        llm_frame.columnconfigure(1, weight=1)
        llm_frame.columnconfigure(4, weight=1)

        ttk.Label(llm_frame, text="Base URL:").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(llm_frame, textvariable=self.base_url_var).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Label(llm_frame, text="API Key:").grid(
            row=0, column=3, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(llm_frame, textvariable=self.api_key_var).grid(
            row=0, column=4, sticky="ew", pady=4
        )

        ttk.Label(llm_frame, text="Model:").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        ttk.Entry(llm_frame, textvariable=self.model_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Entry(llm_frame, textvariable=self.base_url_var).grid(
            row=0, column=1, columnspan=5, sticky="ew", pady=4
        )

        ttk.Label(llm_frame, text="Model:").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=4)
        ttk.Entry(llm_frame, textvariable=self.model_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(llm_frame, text="API Key:").grid(
            row=1, column=3, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(llm_frame, textvariable=self.api_key_var).grid(
            row=1, column=4, sticky="ew", pady=4
        )

        ttk.Label(llm_frame, text="系统提示词:").grid(
            row=2, column=0, sticky="e", padx=(0, 6), pady=4
        )
        ttk.Entry(llm_frame, textvariable=self.system_prompt_var).grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Button(llm_frame, text="浏览", command=self._browse_system_prompt).grid(
            row=2, column=2, sticky="w", padx=(6, 0), pady=4
        )
        ttk.Label(llm_frame, text="用户模板:").grid(
            row=2, column=3, sticky="e", padx=(16, 6), pady=4
        )
        ttk.Entry(llm_frame, textvariable=self.user_template_var).grid(
            row=2, column=4, sticky="ew", pady=4
        )
        ttk.Button(llm_frame, text="浏览", command=self._browse_user_template).grid(
            row=2, column=5, sticky="w", padx=(6, 0), pady=4
        )

        ttk.Checkbutton(llm_frame, text="提取后自动总结", variable=self.summarize_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        action_frame = ttk.LabelFrame(main_frame, text="操作", padding=10)
        action_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        for col in range(4):
            action_frame.columnconfigure(col, weight=1)

        calibrate_btn = ttk.Button(action_frame, text="🔧 校准", command=self._on_calibrate)
        extract_btn = ttk.Button(action_frame, text="💬 单聊提取", command=self._on_extract)
        extract_all_btn = ttk.Button(action_frame, text="📋 全量提取", command=self._on_extract_all)
        summarize_btn = ttk.Button(action_frame, text="📝 总结", command=self._on_summarize)

        calibrate_btn.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        extract_btn.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        extract_all_btn.grid(row=0, column=2, padx=4, pady=4, sticky="ew")
        summarize_btn.grid(row=0, column=3, padx=4, pady=4, sticky="ew")

        self._action_buttons = [calibrate_btn, extract_btn, extract_all_btn, summarize_btn]

        self.stop_btn = ttk.Button(
            action_frame,
            text="⏹ 停止",
            command=self._on_stop,
            state="disabled",
        )
        self.stop_btn.grid(row=1, column=3, padx=4, pady=4, sticky="e")

        self._next_btn = ttk.Button(action_frame, text="下一步", command=self._on_next_step)
        self._next_btn.grid(row=1, column=2, padx=4, pady=4, sticky="e")
        self._next_btn.grid_remove()

        log_frame = ttk.LabelFrame(main_frame, text="日志输出", padding=10)
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _browse_config(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择配置文件",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            initialdir=str(Path(self.config_var.get()).parent),
        )
        if file_path:
            self.config_var.set(file_path)

    def _browse_output_dir(self) -> None:
        folder = filedialog.askdirectory(
            title="选择输出目录",
            initialdir=self.output_dir_var.get().strip() or "./output",
        )
        if folder:
            self.output_dir_var.set(folder)

    def _browse_exclude_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择排除名单文件",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(Path(self.exclude_file_var.get()).parent),
        )
        if file_path:
            self.exclude_file_var.set(file_path)

    def _browse_system_prompt(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择系统提示词文件",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if file_path:
            self.system_prompt_var.set(file_path)

    def _browse_user_template(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择用户模板文件",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if file_path:
            self.user_template_var.set(file_path)

    def _run_in_thread(self, target, *args) -> None:
        if self._running_thread and self._running_thread.is_alive():
            self.log("⚠️ 操作正在进行中...")
            return
        self._stop_event.clear()
        self._disable_action_buttons()
        self._running_thread = threading.Thread(target=target, args=args, daemon=True)
        self._running_thread.start()

    def _disable_action_buttons(self) -> None:
        for btn in self._action_buttons:
            btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def _restore_action_buttons(self) -> None:
        def _restore():
            for btn in self._action_buttons:
                btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            if self._next_btn is not None:
                self._next_btn.grid_remove()

        self.root.after(0, _restore)

    def _show_next_step_button(self) -> None:
        if self._next_btn is not None:
            self.root.after(0, self._next_btn.grid)

    def _on_stop(self) -> None:
        self._stop_event.set()
        self._calibrate_event.set()
        self.log("⏹ 正在请求停止...")

    def _on_next_step(self) -> None:
        self._calibrate_event.set()

    def _on_calibrate(self) -> None:
        self._show_next_step_button()
        self._run_in_thread(self._do_calibrate)

    def _wait_calibrate_step(self) -> bool:
        self._calibrate_event.clear()
        self._calibrate_event.wait()
        return not self._stop_event.is_set()

    def _do_calibrate(self) -> None:
        try:
            device_serial = self.device_var.get().strip() or None
            config_path = self.config_var.get().strip() or "./wechat_selectors.yaml"

            self.log("正在连接设备...")
            dm = DeviceManager()
            connected = dm.connect(serial=device_serial)
            device_info = dm.get_device_info(connected)
            self.log(f"设备: {device_info}")

            self.log("")
            self.log('[1/3] 请打开微信消息列表界面（确保"公众号"可见），然后点击 [下一步]...')
            if not self._wait_calibrate_step():
                self.log("⏹ 已停止")
                return

            self.log("  → 正在 dump UI 层级...")
            message_list_xml = stable_dump(connected)
            calibrator = Calibrator()
            msg_list_config = calibrator.calibrate_message_list(message_list_xml)
            self.log("  ✅ 消息列表 IDs 检测完成")

            self.log('[2/3] 请进入任意个人聊天，发送"谢谢"两字，然后点击 [下一步]...')
            if not self._wait_calibrate_step():
                self.log("⏹ 已停止")
                return

            self.log("  → 正在 dump UI 层级...")
            personal_xml = stable_dump(connected)
            chat_view_config = calibrator.calibrate_chat_view(personal_xml, anchor_text="谢谢")
            self.log("  ✅ 个人聊天 IDs 检测完成")

            self.log('[3/3] 请进入任意群聊，发送"谢谢"两字，然后点击 [下一步]...')
            if not self._wait_calibrate_step():
                self.log("⏹ 已停止")
                return

            self.log("  → 正在 dump UI 层级...")
            group_xml = stable_dump(connected)
            group_config = calibrator.calibrate_chat_view(group_xml, anchor_text="谢谢")
            if group_config.sender_name != ChatViewConfig().sender_name:
                chat_view_config.sender_name = group_config.sender_name

            nav_config = calibrator.calibrate_navigation(message_list_xml, personal_xml)

            config = SelectorConfig(
                message_list=msg_list_config,
                chat_view=chat_view_config,
                navigation=nav_config,
                device_info=device_info,
                calibrated_at=datetime.now().isoformat(timespec="seconds"),
            )
            saved = config.save(config_path)
            self.log(f"\n✅ 配置已保存至: {saved}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"❌ 校准失败: {exc}")
        finally:
            self._restore_action_buttons()

    def _on_extract(self) -> None:
        self._run_in_thread(self._do_extract)

    def _do_extract(self) -> None:
        callbacks = GUICallbacks(self.log, self._stop_event)
        try:
            since_str = self.since_var.get().strip()
            since_date = date.fromisoformat(since_str)
            chat_name = self.chat_name_var.get().strip() or None
            output_dir = self.output_dir_var.get().strip() or "./output"
            config_path = self.config_var.get().strip() or None

            config = load_config(config_path if config_path else None)

            llm_config = LLMConfig(
                base_url=self.base_url_var.get().strip(),
                api_key=self.api_key_var.get().strip(),
                model=self.model_var.get().strip(),
                temperature=0.3,
                max_tokens=4096,
            )

            system_prompt_file = self.system_prompt_var.get().strip() or None
            user_template_file = self.user_template_var.get().strip() or None

            callbacks.log("正在连接设备...")
            dm = DeviceManager()
            connected = dm.connect(serial=self.device_var.get().strip() or None)
            device_info = dm.get_device_info(connected)
            dm.check_wechat(connected)

            max_scrolls_str = self.max_scrolls_var.get().strip()
            max_scrolls = int(max_scrolls_str) if max_scrolls_str else None

            should_summarize = self.summarize_var.get() and not self._stop_event.is_set()
            extract_single(
                connected,
                config,
                since_date,
                chat_name,
                output_dir,
                device_info,
                callbacks,
                max_scrolls=max_scrolls,
                summarize=should_summarize,
                llm_config=llm_config,
                system_prompt_file=system_prompt_file,
                user_template_file=user_template_file,
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"❌ 提取失败: {exc}")
        finally:
            self._restore_action_buttons()

    def _on_extract_all(self) -> None:
        self._run_in_thread(self._do_extract_all)

    def _do_extract_all(self) -> None:
        writer = _GUILogWriter(self.log)
        with contextlib.redirect_stdout(writer):
            callbacks = GUICallbacks(self.log, self._stop_event)
            try:
                since_date = date.fromisoformat(self.since_var.get().strip())
                today = date.today()
                config = load_config(self.config_var.get().strip() or None)

                include_str = self.include_var.get().strip()
                exclude_str = self.exclude_var.get().strip()
                include_list = (
                    [s.strip() for s in include_str.split(",") if s.strip()]
                    if include_str
                    else None
                )
                exclude_list = (
                    [s.strip() for s in exclude_str.split(",") if s.strip()] if exclude_str else []
                )

                exclude_file = self.exclude_file_var.get().strip()
                if exclude_file:
                    ep = Path(exclude_file)
                    if ep.is_file():
                        lines = ep.read_text(encoding="utf-8").splitlines()
                        file_patterns = [
                            line.strip()
                            for line in lines
                            if line.strip() and not line.strip().startswith("#")
                        ]
                        exclude_list.extend(file_patterns)
                        self.log(f"已加载排除名单: {ep} ({len(file_patterns)} 条)")

                exclude_list = exclude_list or None

                max_chats_str = self.max_chats_var.get().strip()
                max_chats = int(max_chats_str) if max_chats_str else None

                dm = DeviceManager()
                connected = dm.connect(serial=self.device_var.get().strip() or None)
                device_info = dm.get_device_info(connected)
                dm.check_wechat(connected)
                callbacks.log("正在启动微信...")
                dm.launch_wechat(connected)

                folder_name = f"{since_date.isoformat()}_{today.isoformat()}"
                batch_dir = Path(self.output_dir_var.get().strip() or "./output") / folder_name
                batch_dir.mkdir(parents=True, exist_ok=True)
                callbacks.log(f"输出目录: {batch_dir}")

                max_scrolls_str = self.max_scrolls_var.get().strip()
                max_scrolls = int(max_scrolls_str) if max_scrolls_str else None

                max_list_scrolls_str = self.max_list_scrolls_var.get().strip()
                max_list_scrolls = int(max_list_scrolls_str) if max_list_scrolls_str else 1000

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
            except Exception as exc:  # noqa: BLE001
                self.log(f"❌ 全量提取失败: {exc}")
            finally:
                self._restore_action_buttons()

    def _on_summarize(self) -> None:
        input_file = filedialog.askopenfilename(
            title="选择聊天记录 JSON 文件",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=self.output_dir_var.get().strip() or "./output",
        )
        if not input_file:
            return
        self._disable_action_buttons()
        self._run_in_thread(self._do_summarize, input_file)

    def _do_summarize(self, input_file: str) -> None:
        callbacks = GUICallbacks(self.log, self._stop_event)
        try:
            llm_config = LLMConfig(
                base_url=self.base_url_var.get().strip(),
                api_key=self.api_key_var.get().strip(),
                model=self.model_var.get().strip(),
                temperature=0.3,
                max_tokens=4096,
            )
            output_dir = self.output_dir_var.get().strip() or "./output"
            summarize_file(
                input_file,
                output_dir,
                llm_config,
                callbacks,
                system_prompt_file=self.system_prompt_var.get().strip() or None,
                user_template_file=self.user_template_var.get().strip() or None,
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"❌ 总结失败: {exc}")
        finally:
            self._restore_action_buttons()

    def log(self, message: str) -> None:
        self._log_queue.put(message)

    def _poll_log_queue(self) -> None:
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.root.after(100, self._poll_log_queue)

    def run(self) -> None:
        self.root.mainloop()


__all__ = ["WeChatSummaryGUI"]
