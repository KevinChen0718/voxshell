# voxshell

**Voice mode for CLI coding agents.** Let Codex or Claude Code finish the work in your terminal, then hear the useful part of the answer without switching back to read it.

voxshell connects to an agent's turn-complete event, removes code blocks, tables, URLs, and path noise, keeps a short natural-language result, and speaks it with macOS `say`.

```text
Codex notify / Claude Code Stop hook
                  ↓
          last assistant reply
                  ↓
        clean + shorten locally
                  ↓
              macOS say
```

- No daemon and no account of its own
- No audio recording in the main read-aloud mode
- No API call by default
- Safe installers that preview, back up, merge, and uninstall
- Codex CLI and Claude Code adapters
- macOS only for now

[繁體中文快速說明](#繁體中文快速說明)

## The problem

Coding agents often spend minutes running tools while you move to another window or task. When they finish, the answer waits silently in the terminal. Generic text-to-speech reads too much: Markdown, code, paths, diffs, and test logs.

voxshell gives the active coding session a small, selective voice. A newer answer interrupts only the previous voxshell speaker, so stale updates do not queue up.

## Try it in 30 seconds

The preview and demo paths use the same cleaning and shortening code as the real hooks. They do not install anything or call an AI model.

```bash
git clone https://github.com/KevinChen0718/voxshell.git
cd voxshell

python3 hooks/voxshell-speak.py --preview \
  "The refactor is complete. All 27 tests pass. The full diff is in the terminal."

python3 hooks/voxshell-speak.py --demo \
  "The refactor is complete. All 27 tests pass. The full diff is in the terminal."
```

`--preview` prints the exact built-in short script without speaking. `--demo` speaks it with macOS `say`. Both modes deliberately skip the optional `summary_cmd`, making the test deterministic and free.

Run the complete automated test suite:

```bash
PYTHONDONTWRITEBYTECODE=1 bash tests/test_speak.sh
```

## Install for Codex CLI

Requirements: macOS, Python 3.9+, and Codex CLI.

First inspect the proposed `~/.codex/config.toml` change:

```bash
python3 hooks/install_codex_notify.py --dry-run
```

If the diff is correct, install it:

```bash
python3 hooks/install_codex_notify.py
```

Codex appends an `agent-turn-complete` JSON payload to the configured `notify` command. voxshell reads `last-assistant-message`, then uses the shared local speech pipeline.

The installer stops without writing if another top-level `notify` command already exists. Codex accepts one command argv array, not a list of independent notifiers; use a small fan-out wrapper if you need both. The installed command contains this checkout's absolute path, so keep the folder in place after installation.

Uninstall only the voxshell entry:

```bash
python3 hooks/install_codex_notify.py --uninstall
```

## Install for Claude Code

Requirements: macOS, Python 3.9+, and Claude Code with `Stop` hooks.

Preview the merge into `~/.claude/settings.json`:

```bash
python3 hooks/install_claude_hook.py --dry-run
```

Install after reviewing the diff:

```bash
python3 hooks/install_claude_hook.py
```

The hook reads `last_assistant_message` from stdin. If that field is absent, it conservatively scans the tail of `transcript_path` as a fallback. Parsing or speech failures are fail-open: they never block the coding agent.

Uninstall only the voxshell hook:

```bash
python3 hooks/install_claude_hook.py --uninstall
```

## Configuration

Create `~/.voxshell/config.json` only if you want to override defaults:

```json
{
  "voice": "Samantha",
  "rate": 190,
  "max_sentences": 2,
  "max_chars": 320
}
```

List installed macOS voices with:

```bash
say -v '?'
```

### Optional AI-generated spoken summary

By default, voxshell makes no model call and reads the first two useful sentences after cleaning. Advanced users can set `summary_cmd` to any command that accepts the cleaned reply on stdin and returns one spoken line on stdout:

```json
{
  "summary_cmd": "/absolute/path/to/voxshell/hooks/summarize-with-codex.sh",
  "summary_timeout": 8
}
```

The included example invokes `codex exec` on every completed turn. That consumes quota and adds latency, so it is disabled by default. Failure or timeout silently falls back to the built-in two-sentence result.

## Mute and debug

Mute one launched agent session:

```bash
VOXSHELL_MUTE=1 codex
```

Mute all voxshell hooks with a marker file, then restore speech later:

```bash
mkdir -p ~/.voxshell
touch ~/.voxshell/mute
mv ~/.voxshell/mute ~/.voxshell/mute.off
```

Enable a local decision log when troubleshooting:

```bash
VOXSHELL_DEBUG=1 python3 hooks/voxshell-speak.py --demo "Debug test completed."
```

The log is written to `~/.voxshell/voxshell.log`.

## What gets spoken

The built-in pipeline:

1. Accepts a Claude stdin payload, Codex notify argv payload, or explicit demo text.
2. Rejects malformed and oversized input.
3. Removes fenced code, inline code, URLs, long paths, tables, and list noise.
4. Skips content that still looks mostly like code.
5. Keeps the first two natural-language sentences with a hard character limit.
6. Stops only the previous speaker recorded in voxshell's own PID file.
7. Starts macOS `say` in the background.

## Privacy and safety

- Main hook mode does not record microphone audio.
- Cleaning, shortening, configuration, and speech happen locally.
- No network request is made unless you explicitly configure `summary_cmd` or the coding agent itself uses a network service.
- Installers parse configuration, preserve unknown fields, create timestamped backups, avoid duplicate entries, and write atomically.
- The Codex installer refuses to overwrite an existing third-party notifier.
- The Claude and Codex adapters fail open so a speech problem cannot stop the agent.
- Recordings created by the optional legacy conversation demo are temporary and locally transcribed; only its transcript is passed to the selected AI CLI.

## Supported platforms

| Platform | Status | Integration |
|---|---|---|
| macOS + Codex CLI | Supported | top-level `notify` command |
| macOS + Claude Code | Supported | `Stop` hook |
| macOS manual demo | Supported | `--demo` and `--preview` |
| Windows / Linux | Not yet | needs a cross-platform TTS backend |
| Gemini CLI | Not yet | no stable turn-complete adapter selected |

## Optional microphone conversation demo

The older mic → local Whisper → AI CLI → speech loop remains available as an experimental demo. It is separate from the main read-aloud product and has heavier dependencies.

```bash
./setup.sh
./run.sh --brain "codex exec"
```

Run `./run.sh --help` or read [INSTALL-FOR-AI.md](INSTALL-FOR-AI.md) for guided setup.

## How Codex helped build voxshell

Codex was used as an engineering collaborator, not as a one-shot code generator:

- It compared lifecycle options and found that Claude's `last_assistant_message` is safer than relying on a transcript that may not be fully flushed.
- It implemented a shared pipeline for Claude stdin payloads and Codex notify argv payloads instead of duplicating behavior.
- It built conservative JSON and TOML installers around backups, idempotency, atomic writes, and conflict refusal.
- It generated adversarial tests for malformed input, code-heavy replies, mute precedence, transcript fallback, installer conflicts, summary timeout, and manual judge demos.
- Human product decisions kept the scope mouth-first, limited speech to a short result, avoided global `killall`, and made all model-based summarization optional.

The design record is in [M3-DESIGN.md](M3-DESIGN.md). A reusable hackathon description, evidence checklist, and sub-three-minute recording script are in [docs/submission-kit.md](docs/submission-kit.md).

## Project structure

```text
hooks/voxshell-speak.py          shared cleaning and speech pipeline
hooks/install_codex_notify.py    safe Codex config installer
hooks/install_claude_hook.py     safe Claude settings installer
hooks/summarize-with-codex.sh    optional summary command example
tests/test_speak.sh              end-to-end tests with isolated temp config
talk.py                          optional legacy microphone demo
docs/submission-kit.md           reusable competition submission package
```

## Roadmap

- Cross-platform TTS backends
- A supported Gemini CLI adapter
- Optional push-to-talk into the active coding session
- Smarter local summary-section detection without a model call

## License

MIT

---

## 繁體中文快速說明

voxshell 會在 Codex 或 Claude Code 完成一輪工作後，自動取出最後回覆，拿掉程式碼、表格、網址與長路徑，只用 macOS `say` 念出前兩句有用的自然語言。主模式不錄音、預設不呼叫額外模型，也不會因為朗讀失敗卡住你的 coding agent。

先不用安裝，直接測試清洗結果：

```bash
python3 hooks/voxshell-speak.py --preview \
  "修改完成。27 個測試全部通過。完整差異仍留在終端機。"

python3 hooks/voxshell-speak.py --demo \
  "修改完成。27 個測試全部通過。完整差異仍留在終端機。"
```

安裝到 Codex CLI：

```bash
python3 hooks/install_codex_notify.py --dry-run
python3 hooks/install_codex_notify.py
```

安裝到 Claude Code：

```bash
python3 hooks/install_claude_hook.py --dry-run
python3 hooks/install_claude_hook.py
```

安裝器都會先讓你看差異、保留既有設定並建立備份。完整設定、安全說明與解除安裝方式請看上方英文主文件；給 AI 代為引導安裝則使用 [INSTALL-FOR-AI.md](INSTALL-FOR-AI.md)。
