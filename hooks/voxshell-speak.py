#!/usr/bin/env python3
"""Claude Code Stop hook: speak a short, cleaned assistant reply."""

import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path


MAX_STDIN_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_LINES = 80
DEFAULT_MAX_SENTENCES = 2
CJK_MAX_CHARS = 240
EN_MAX_CHARS = 500
TOOL_NAME = "voxshell-speak.py"
MANUAL_MODES = ("--demo", "--preview")


def voxshell_home() -> Path:
    return Path(os.environ.get("VOXSHELL_HOME", "~/.voxshell")).expanduser()


def debug_enabled(home: Path) -> bool:
    return os.environ.get("VOXSHELL_DEBUG") == "1" or (home / "debug").exists()


def log_debug(home: Path, message: str) -> None:
    if not debug_enabled(home):
        return
    try:
        home.mkdir(parents=True, exist_ok=True)
        with (home / "voxshell.log").open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except Exception:
        pass


def read_payload(home: Path):
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        log_debug(home, "stdin too large; skip")
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        log_debug(home, "stdin json parse failed; skip")
        return None
    if not isinstance(payload, dict):
        log_debug(home, "stdin json is not an object; skip")
        return None
    return payload


def read_codex_payload(home: Path):
    if len(sys.argv) < 3:
        log_debug(home, "codex notify argv missing payload; skip")
        return None
    raw = sys.argv[-1]
    try:
        payload = json.loads(raw)
    except Exception:
        log_debug(home, "codex notify json parse failed; skip")
        return None
    if not isinstance(payload, dict):
        log_debug(home, "codex notify json is not an object; skip")
        return None
    if payload.get("type") != "agent-turn-complete":
        log_debug(home, "codex notify type ignored; skip")
        return None
    text = extract_text_from_content(payload.get("last-assistant-message"))
    if not text:
        log_debug(home, "codex notify has no assistant text; skip")
        return None
    return payload


def extract_text_from_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return ""


def extract_text_from_record(record) -> str:
    if isinstance(record, str):
        return record.strip()
    if not isinstance(record, dict):
        return ""

    direct = extract_text_from_content(record.get("last_assistant_message"))
    if direct:
        return direct

    message = record.get("message")
    if isinstance(message, dict):
        content = extract_text_from_content(message.get("content"))
        if content:
            return content

    content = extract_text_from_content(record.get("content"))
    if content:
        return content

    text = record.get("text")
    if isinstance(text, str):
        return text.strip()
    return ""


def tail_lines(path: Path, max_lines: int, max_bytes: int):
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            chunks = []
            seen = 0
            remaining = min(position, max_bytes)
            while position > 0 and seen <= max_lines and remaining > 0:
                size = min(8192, position, remaining)
                position -= size
                remaining -= size
                handle.seek(position)
                chunk = handle.read(size)
                chunks.append(chunk)
                seen += chunk.count(b"\n")
            data = b"".join(reversed(chunks))
    except Exception:
        return []
    return data.decode("utf-8", errors="replace").splitlines()[-max_lines:]


def fallback_transcript(payload: dict, home: Path) -> str:
    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript.strip():
        log_debug(home, "no transcript_path fallback")
        return ""
    path = Path(transcript).expanduser()
    if not path.exists() or not path.is_file():
        log_debug(home, "transcript_path missing; skip fallback")
        return ""

    for line in reversed(tail_lines(path, MAX_TRANSCRIPT_LINES, MAX_TRANSCRIPT_BYTES)):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except Exception:
            continue
        text = extract_text_from_record(record)
        if text:
            log_debug(home, "transcript fallback found text")
            return text
    log_debug(home, "transcript fallback found no text")
    return ""


def extract_assistant_text(payload: dict, home: Path, codex_notify: bool) -> str:
    if codex_notify:
        return extract_text_from_content(payload.get("last-assistant-message"))

    text = extract_text_from_content(payload.get("last_assistant_message"))
    if not text:
        text = fallback_transcript(payload, home)
    return text


def remove_long_paths(text: str) -> str:
    kept = []
    for token in text.split():
        bare = token.strip("()[]{}<>,.;:!?'\"")
        if "/" in bare and len(bare) > 20:
            continue
        kept.append(token)
    return " ".join(kept)


def code_like_ratio(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 1.0
    code_chars = set("{}[]();=<>$\\|`~@")
    hits = sum(1 for char in compact if char in code_chars)
    return hits / len(compact)


def clean_text(text: str, home: Path) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", " ", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("|", "+", "-")):
            continue
        lines.append(stripped)
    text = "\n".join(lines)

    text = remove_long_paths(text)
    text = re.sub(r"^[#>\s]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        log_debug(home, "cleaned text empty; skip")
        return ""
    if code_like_ratio(text) > 0.28:
        log_debug(home, "cleaned text too code-like; skip")
        return ""
    return text


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def load_config(home: Path) -> dict:
    defaults = {
        "voice": None,
        "rate": None,
        "max_sentences": DEFAULT_MAX_SENTENCES,
        "max_chars": None,
        "summary_cmd": None,
        "summary_timeout": 8,
    }
    path = home / "config.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        return defaults
    if not isinstance(config, dict):
        return defaults

    voice = config.get("voice")
    rate = config.get("rate")
    max_sentences = config.get("max_sentences")
    max_chars = config.get("max_chars")
    summary_cmd = config.get("summary_cmd")
    summary_timeout = config.get("summary_timeout")
    if isinstance(voice, str) and voice.strip():
        defaults["voice"] = voice.strip()
    if isinstance(rate, int) and rate > 0:
        defaults["rate"] = rate
    if isinstance(max_sentences, int) and max_sentences > 0:
        defaults["max_sentences"] = min(max_sentences, 5)
    if isinstance(max_chars, int) and max_chars > 0:
        defaults["max_chars"] = max_chars
    if isinstance(summary_cmd, str) and summary_cmd.strip():
        defaults["summary_cmd"] = summary_cmd.strip()
    if isinstance(summary_timeout, (int, float)) and summary_timeout > 0:
        defaults["summary_timeout"] = min(float(summary_timeout), 30.0)
    return defaults


def split_sentences(text: str):
    chunks = re.findall(r".+?[。！？.!?]+[\"'”’）)]*|.+$", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def truncate_near_boundary(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text.strip()
    window = text[:limit].rstrip()
    floor = max(0, int(limit * 0.6))
    cut = -1
    for mark in "。！？.!?，,；;：:":
        cut = max(cut, window.rfind(mark, floor))
    if cut >= floor:
        return window[: cut + 1].strip()
    return window.strip()


def make_script(text: str, config: dict) -> str:
    sentences = split_sentences(text)
    selected = " ".join(sentences[: config["max_sentences"]]).strip()
    if not selected:
        selected = text.strip()
    limit = config["max_chars"] or (CJK_MAX_CHARS if contains_cjk(selected) else EN_MAX_CHARS)
    return truncate_near_boundary(selected, limit)


def hard_limit_script(text: str, config: dict) -> str:
    selected = text.strip()
    if not selected:
        return ""
    limit = config["max_chars"] or (CJK_MAX_CHARS if contains_cjk(selected) else EN_MAX_CHARS)
    return truncate_near_boundary(selected, limit)


def prepare_script(text: str, config: dict, home: Path, allow_summary: bool = True) -> str:
    cleaned = clean_text(text, home)
    if not cleaned:
        return ""
    if allow_summary:
        summarized = summarize_script(cleaned, config, home)
        if summarized:
            return summarized
    return make_script(cleaned, config)


def summarize_script(text: str, config: dict, home: Path) -> str:
    command_text = config.get("summary_cmd")
    if not command_text:
        return ""
    try:
        command = shlex.split(command_text)
    except ValueError:
        log_debug(home, "summary_cmd parse failed; fallback")
        return ""
    if not command:
        return ""
    try:
        result = subprocess.run(
            command,
            input=text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=config.get("summary_timeout", 8),
            check=False,
        )
    except Exception:
        log_debug(home, "summary_cmd failed or timed out; fallback")
        return ""
    if result.returncode != 0:
        log_debug(home, "summary_cmd returned non-zero; fallback")
        return ""
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            return hard_limit_script(stripped, config)
    log_debug(home, "summary_cmd output empty; fallback")
    return ""


def read_pid_file(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("created_by") != TOOL_NAME:
        return None
    pid = data.get("pid")
    if isinstance(pid, int) and pid > 0:
        return pid
    return None


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def stop_previous_speaker(home: Path) -> None:
    pid = read_pid_file(home / "speak.pid")
    if not pid or not process_is_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        log_debug(home, "terminated previous voxshell speaker")
    except Exception:
        pass


def start_say(script: str, config: dict, home: Path) -> None:
    say_cmd = shlex.split(os.environ.get("VOXSHELL_SAY_CMD", "say"))
    if not say_cmd:
        return
    command = say_cmd[:]
    if config.get("voice"):
        command.extend(["-v", config["voice"]])
    if config.get("rate"):
        command.extend(["-r", str(config["rate"])])
    command.append(script)

    stop_previous_speaker(home)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    (home / "speak.pid").write_text(
        json.dumps({"pid": process.pid, "created_by": TOOL_NAME, "command": command[0]}),
        encoding="utf-8",
    )
    log_debug(home, "started say process")


def manual_mode(args, home: Path):
    if not args or args[0] not in MANUAL_MODES:
        return None

    mode = args[0]
    text = " ".join(args[1:]).strip()
    if not text:
        print(
            "Usage: python3 hooks/voxshell-speak.py --preview \"text\"\n"
            "       python3 hooks/voxshell-speak.py --demo \"text\"",
            file=sys.stderr,
        )
        return 2

    home.mkdir(parents=True, exist_ok=True)
    config = load_config(home)
    # Manual modes must be deterministic and free: never invoke summary_cmd.
    script = prepare_script(text, config, home, allow_summary=False)
    if not script:
        print("Nothing speakable remained after cleaning / 清理後沒有可朗讀內容", file=sys.stderr)
        return 1

    if mode == "--preview":
        print(script)
        return 0

    env_muted = os.environ.get("VOXSHELL_MUTE", "").strip().lower() in ("1", "true", "yes", "on")
    if env_muted or (home / "mute").exists():
        print("voxshell is muted; use --preview to inspect the text / voxshell 已靜音，可用 --preview 查看文字", file=sys.stderr)
        return 1

    start_say(script, config, home)
    print(f"Speaking / 正在朗讀: {script}")
    return 0


def main() -> int:
    home = voxshell_home()
    args = sys.argv[1:]
    if args and args[0] in MANUAL_MODES:
        try:
            return manual_mode(args, home)
        except Exception as exc:
            print(f"Demo failed / 示範失敗: {exc}", file=sys.stderr)
            return 1

    try:
        # Env mute comes first so headless/automation callers can opt out
        # before we even touch stdin or the filesystem.
        if os.environ.get("VOXSHELL_MUTE", "").strip().lower() in ("1", "true", "yes", "on"):
            return 0

        home.mkdir(parents=True, exist_ok=True)

        if (home / "mute").exists():
            log_debug(home, "mute marker exists; skip")
            return 0

        codex_notify = "--codex-notify" in sys.argv[1:]
        payload = read_codex_payload(home) if codex_notify else read_payload(home)
        if payload is None:
            return 0

        text = extract_assistant_text(payload, home, codex_notify)
        if not text:
            log_debug(home, "no assistant text; skip")
            return 0

        config = load_config(home)
        script = prepare_script(text, config, home)
        if not script:
            log_debug(home, "short script empty; skip")
            return 0

        start_say(script, config, home)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
