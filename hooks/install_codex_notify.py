#!/usr/bin/env python3
"""Safely install or remove the voxshell Codex CLI notify command."""

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path


HOOK_MARKER = "voxshell-speak.py"


def notify_argv():
    script = Path(__file__).resolve().with_name(HOOK_MARKER)
    return ["python3", str(script), "--codex-notify"]


def notify_line() -> str:
    values = ", ".join(json.dumps(part) for part in notify_argv())
    return f"notify = [{values}]\n"


def is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and not stripped.startswith("#")


def find_top_level_notify_statement(text: str):
    lines = text.splitlines(keepends=True)
    in_table = False
    for index, line in enumerate(lines):
        if is_table_header(line):
            in_table = True
        if in_table:
            continue
        if line.lstrip().startswith("#"):
            continue
        if not re.match(r"^\s*notify\s*=", line):
            continue

        end = index + 1
        statement = line
        bracket_depth = line.count("[") - line.count("]")
        while bracket_depth > 0 and end < len(lines):
            statement += lines[end]
            bracket_depth += lines[end].count("[") - lines[end].count("]")
            end += 1
        return index, end, statement
    return None


def apply_install(before: str):
    found = find_top_level_notify_statement(before)
    if found:
        _, _, statement = found
        if HOOK_MARKER in statement:
            return before, "already"
        return before, "conflict"
    return notify_line() + before, "installed"


def apply_uninstall(before: str):
    found = find_top_level_notify_statement(before)
    if not found:
        return before, "not_installed"
    start, end, statement = found
    if HOOK_MARKER not in statement:
        return before, "not_installed"
    lines = before.splitlines(keepends=True)
    after = "".join(lines[:start] + lines[end:])
    return after, "removed"


def backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = path.with_name(f"{path.name}.bak.{stamp}")
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def print_diff(path: Path, before: str, after: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"{path} (current)",
        tofile=f"{path} (new)",
    )
    output = "".join(diff)
    if output:
        print(output, end="")
    else:
        print("No changes / 無變更")


def print_conflict(path: Path) -> None:
    command = " ".join(notify_argv())
    print(
        "Stop, no write: an existing top-level Codex notify command was found.\n"
        "停止，未寫入：已找到既有的 Codex 頂層 notify 指令。\n\n"
        "Codex notify is one argv array for a single command; Codex appends the JSON payload as the final argv.\n"
        "Codex notify 是單一指令的 argv 陣列；Codex 會把 JSON payload 自動附在最後一個 argv。\n\n"
        "Manual integration / 手動整合：\n"
        f"1. Edit / 編輯: {path}\n"
        "2. Keep your existing notify command, or replace it with a small wrapper script.\n"
        "   保留現有 notify 指令，或改成一個小型 wrapper script。\n"
        "3. In that wrapper, call both your existing notifier and voxshell with the payload argv.\n"
        "   在 wrapper 內同時呼叫原本 notifier 與 voxshell，並傳入 payload argv。\n"
        f"   voxshell command / voxshell 指令: {command} \"$payload\"\n",
        file=sys.stderr,
    )


def read_config(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Install voxshell Codex CLI notify command")
    parser.add_argument("--config", default="~/.codex/config.toml", help="Codex config.toml path")
    parser.add_argument("--uninstall", action="store_true", help="Remove voxshell notify command")
    parser.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = Path(args.config).expanduser()
    try:
        before = read_config(config)
        after, status = apply_uninstall(before) if args.uninstall else apply_install(before)

        if status == "conflict":
            print_conflict(config)
            return 1

        if args.dry_run:
            print_diff(config, before, after)
            return 0

        if before == after:
            if status == "already":
                print("voxshell Codex notify already installed / voxshell Codex notify 已安裝")
            else:
                print("voxshell Codex notify not installed / voxshell Codex notify 尚未安裝")
            return 0

        if config.exists():
            backup_path = backup(config)
            print(f"Backup created / 已備份: {backup_path}")
        atomic_write(config, after)

        if status == "removed":
            print("voxshell Codex notify removed / voxshell Codex notify 已移除")
        else:
            print("voxshell Codex notify installed / voxshell Codex notify 已安裝")
            print("Format: notify is argv; Codex appends payload as last argv / 格式：notify 是 argv，Codex 會把 payload 附在最後")
    except Exception as exc:
        print(f"Failed / 失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
