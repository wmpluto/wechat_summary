# wechat-summary

Android WeChat chat extraction and summarization tool. Connects to a phone via USB, reads chat messages through UI automation, and optionally summarizes them using a local LLM.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│  calibrate  │     │   extract    │     │ extract-all  │     │ summarize  │
│  (CLI cmd)  │     │  (CLI cmd)   │     │  (CLI cmd)   │     │ (CLI cmd)  │
└──────┬──────┘     └──────┬───────┘     └──────┬───────┘     └─────┬──────┘
       │                   │                    │                    │
       v                   v                    v                    v
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│ calibrator  │     │  extractor   │     │  navigator   │     │ summarizer │
│ (auto-detect│     │ (parse XML,  │     │ (list parse, │     │ (LLM call, │
│  WeChat IDs)│     │  extract msg)│     │  enter/exit) │     │  chunking) │
└──────┬──────┘     └──────┬───────┘     └──────┬───────┘     └─────┬──────┘
       │                   │                    │                    │
       v                   v                    v                    v
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│   config    │     │  selectors   │     │    device     │     │ llm_client │
│ (YAML R/W,  │     │ (stable_dump │     │ (USB connect,│     │ (OpenAI API│
│  defaults)  │     │  fallback)   │     │  WeChat chk) │     │  compat)   │
└─────────────┘     └──────────────┘     └──────────────┘     └────────────┘
                           │
                           v
                    ┌──────────────┐
                    │   models     │     persistence (JSON save/load)
                    │ (Pydantic v2 │     exceptions (error hierarchy)
                    │  data types) │
                    └──────────────┘
```

### Core Flow

1. **Calibrate** (`wechat-summary calibrate`) — Dump WeChat UI on 3 screens, auto-detect resource IDs via anchor text, save to `wechat_selectors.yaml`
2. **Extract** (`wechat-summary extract`) — Stay on one chat, scroll up to collect messages since a date, save as JSON
3. **Extract All** (`wechat-summary extract-all`) — Start from message list, iterate all qualifying chats (with filtering), save per-chat JSON files
4. **Summarize** (`wechat-summary summarize`) — Feed extracted JSON to a local LLM, output Markdown + JSON summary

### Key Design Decisions

- **uiautomator2** over scrcpy+OCR: directly reads UI text from XML hierarchy, no OCR needed
- **Anchor-based calibration**: user provides known text (e.g., "公众号", "谢谢") to reverse-engineer resource IDs from XML tree
- **Config-driven selectors**: all WeChat resource IDs stored in editable YAML, survives WeChat version updates
- **Content-hash dedup**: 5-message overlap window between scroll pages prevents duplicates
- **Hierarchical summarization**: long chats (>3000 tokens) are chunked, summarized in parts, then meta-summarized

## Important Notes

> **Android only** — This tool uses Android UI Automation (uiautomator2) and does NOT support iOS.

> **Accessibility required** — You must enable the **TalkBack / Screen Reader** (朗读/无障碍) service on your Android phone before use. This is required for uiautomator2 to read the UI hierarchy. Go to: **Settings → Accessibility → TalkBack** (or your device's equivalent accessibility service).

## Prerequisites

- Python 3.10+
- **Android** phone with USB debugging enabled
- **Accessibility service (TalkBack/朗读) enabled** on the phone
- WeChat installed on the phone
- ADB drivers installed on PC
- (Optional) Local LLM server for summarization (Ollama, LM Studio, vLLM, etc.)

## Installation

### From source (development)

```bash
git clone <repo-url>
cd wechat_summary
pip install -e ".[dev]"
```

### Dependencies

Core: `uiautomator2`, `click`, `pydantic>=2.0`, `openai`, `tiktoken`, `pyyaml>=6.0`

Dev: `pytest`, `pytest-cov`, `pytest-mock`, `ruff`

## Quick Start

### 1. Calibrate (run once per device / WeChat version)

Connect phone via USB, open WeChat:

```bash
wechat-summary calibrate
```

Follow the 3-step guided process:
1. Stay on message list (with "公众号" visible) → press Enter
2. Enter a personal chat, send "谢谢" → press Enter
3. Enter a group chat, send "谢谢" → press Enter

Config saved to `./wechat_selectors.yaml`. Edit freely if needed.

### 2. Extract a single chat

Open a chat on your phone, then:

```bash
wechat-summary extract --since 2026-03-10 --chat-name "张三"
```

### 3. Extract all chats

Stay on the WeChat message list:

```bash
wechat-summary extract-all --since 2026-03-10
```

With filtering:

```bash
# Only specific chats
wechat-summary extract-all --since 2026-03-10 --include "张三,项目群"

# Exclude patterns
wechat-summary extract-all --since 2026-03-10 --exclude "广告,团购"

# Limit count
wechat-summary extract-all --since 2026-03-10 --max-chats 10
```

### 4. Summarize

```bash
wechat-summary summarize --input output/2026-03-10_2026-03-18/张三.json
```

## CLI Reference

### `wechat-summary calibrate`

Auto-detect WeChat resource IDs and save to config file.

| Option | Default | Description |
|--------|---------|-------------|
| `--device` | auto-detect | Device serial number |
| `--config` | `./wechat_selectors.yaml` | Output config file path |

### `wechat-summary extract`

Extract messages from a single chat (user stays in the chat).

| Option | Default | Description |
|--------|---------|-------------|
| `--since` | (required) | Extract messages since date (YYYY-MM-DD) |
| `--chat-name` | auto-detect | Chat name for the session |
| `--device` | auto-detect | Device serial number |
| `--output-dir` | `./output` | Output directory |
| `--summarize` | off | Also summarize after extraction |
| `--base-url` | `http://localhost:11434/v1` | LLM API base URL |
| `--model` | `qwen2.5` | LLM model name |
| `--api-key` | `ollama` | LLM API key |
| `--config` | auto-load | Selector config YAML file |

### `wechat-summary extract-all`

Extract messages from all chats on the message list.

| Option | Default | Description |
|--------|---------|-------------|
| `--since` | (required) | Extract messages since date (YYYY-MM-DD) |
| `--device` | auto-detect | Device serial number |
| `--output-dir` | `./output` | Output directory |
| `--max-chats` | unlimited | Maximum number of chats to process |
| `--include` | all | Only process these chats (comma-separated, partial match) |
| `--exclude` | none | Skip these chats (comma-separated, partial match) |
| `--exclude-file` | `./exclude.txt` | File with exclude patterns, one per line |
| `--summarize` | off | Also summarize each chat |
| `--base-url` | `http://localhost:11434/v1` | LLM API base URL |
| `--model` | `qwen2.5` | LLM model name |
| `--api-key` | `ollama` | LLM API key |
| `--config` | auto-load | Selector config YAML file |

### `wechat-summary summarize`

Summarize a previously extracted chat session.

| Option | Default | Description |
|--------|---------|-------------|
| `--input` | (required) | Path to JSON chat session file |
| `--output-dir` | `./output` | Output directory |
| `--base-url` | `http://localhost:11434/v1` | LLM API base URL |
| `--model` | `qwen2.5` | LLM model name |
| `--api-key` | `ollama` | LLM API key |
| `--system-prompt` | built-in | Custom system prompt file (plain text) |
| `--user-template` | built-in | Custom user template file (with `{chat_name}` and `{messages}` placeholders) |

### `wechat-summary gui`

Launch the graphical user interface. All features available via GUI with the same settings as CLI.

```bash
wechat-summary gui
```

## Configuration

### Selector Config (`wechat_selectors.yaml`)

Auto-generated by `calibrate`. Contains all WeChat resource IDs:

```yaml
message_list:
  container: "com.tencent.mm:id/j8g"
  chat_item: "com.tencent.mm:id/cj1"
  chat_name: "com.tencent.mm:id/kbq"
  # ...

chat_view:
  message_container: "com.tencent.mm:id/bp0"
  message_text: "com.tencent.mm:id/bkl"
  # ...

navigation:
  back_button: "com.tencent.mm:id/actionbar_up_indicator"
  wechat_tab: "com.tencent.mm:id/icon_tv"
```

Config loading priority:
1. `--config path.yaml` (explicit)
2. `./wechat_selectors.yaml` (auto-load from current directory)
3. Built-in defaults (with warning to run calibrate)

### Exclude List (`exclude.txt`)

One pattern per line, partial match. Lines starting with `#` are comments:

```
# Skip shopping groups
团购
购物

# Skip bots
服务通知
微信支付
```

Auto-loaded from `./exclude.txt` if present. Use `--exclude-file ""` to disable.

### LLM Configuration

Supports any OpenAI Chat Completions API compatible server:

```bash
# Ollama (default, no config needed)
wechat-summary summarize --input chat.json

# LM Studio
wechat-summary summarize --input chat.json --base-url http://localhost:1234/v1

# Remote API with key
wechat-summary summarize --input chat.json \
  --base-url https://api.example.com/v1 \
  --api-key sk-xxxxx \
  --model gpt-4o
```

Environment variables: `WECHAT_LLM_BASE_URL`, `WECHAT_LLM_MODEL`, `WECHAT_LLM_API_KEY`

Also supports OpenAI Responses API — auto-detects and falls back if server rejects Chat Completions.

### Custom Prompts

Customize the summarization prompts by providing text files:

```bash
wechat-summary summarize --input chat.json \
  --system-prompt prompts/system_prompt.txt \
  --user-template prompts/user_template.txt
```

**System prompt** (`prompts/system_prompt.txt`) — defines the LLM's role:
```
你是一个聊天记录分析助手。请阅读以下微信聊天记录，并生成一段简洁的中文总结。
总结应涵盖主要讨论内容、关键决定和重要信息。
```

**User template** (`prompts/user_template.txt`) — must contain `{chat_name}` and `{messages}` placeholders:
```
聊天名称：{chat_name}
以下是聊天记录：
{messages}

请输出一段中文总结。
```

Example custom prompt for extracting action items:
```
聊天名称：{chat_name}
以下是聊天记录：
{messages}

请提取所有待办事项和行动项，按负责人分组列出。
```

In the GUI, these can be set via the "系统提示词" and "用户模板" fields in the LLM 设置 section.

If not specified, built-in default Chinese prompts are used.

## Output Structure

### Single chat (`extract`)

```
output/
  张三_20260318_143022.json
```

### Batch (`extract-all`)

```
output/
  2026-03-10_2026-03-18/     # since_today folder
    张三.json
    项目讨论群.json
    技术交流群.json
```

### Summary

```
output/
  张三_20260318_143022_summary.md
  张三_20260318_143022_summary.json
```

## Built-in Blacklist

These are always skipped in `extract-all`:

- 公众号
- 服务号
- 服务通知
- 微信支付
- 文件传输助手
- 微信团队
- 腾讯新闻

## Development

### Run tests

```bash
pytest tests/ -v
```

### Run with coverage

```bash
pytest tests/ --cov=src/wechat_summary --cov-report=term
```

### Lint

```bash
ruff check src/
```

### Project structure

```
src/wechat_summary/
  __init__.py          # version
  __main__.py          # entry point
  calibrator.py        # anchor-based ID auto-detection
  cli.py               # Click CLI (calibrate, extract, extract-all, summarize)
  config.py            # SelectorConfig dataclass + YAML persistence
  device.py            # DeviceManager (USB connection, WeChat check)
  exceptions.py        # exception hierarchy
  extractor.py         # MessageExtractor (XML parsing, scroll, dedup)
  llm_client.py        # LLMClient (OpenAI-compatible)
  models.py            # Pydantic v2 data models
  navigator.py         # ChatListNavigator (list parsing, navigation, filtering)
  persistence.py       # ChatSessionStore (JSON save/load)
  selectors.py         # stable_dump, find_element with fallback
  summarizer.py        # ChatSummarizer (chunking, Chinese prompts)

tests/
  conftest.py          # shared fixtures
  fixtures/            # XML test fixtures
  test_calibrator.py
  test_cli.py
  test_config.py
  test_device.py
  test_e2e.py
  test_extract_all.py
  test_extractor.py
  test_navigator.py
  ...
```

## Troubleshooting

### LLM connection test

```bash
python test_llm_connection.py [base_url] [api_key] [model]
```

### Device not found

1. Enable USB debugging on phone
2. Run `adb devices` to verify connection
3. Accept USB debugging prompt on phone

### WeChat IDs changed after update

Run `wechat-summary calibrate` again to re-detect IDs.

### Extraction keeps scrolling infinitely

Usually caused by unrecognized timestamp format. Check the `⚠️ 时间未识别` log output and file an issue with the format.

## License

MIT
