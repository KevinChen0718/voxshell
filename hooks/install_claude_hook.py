#!/usr/bin/env python3
"""Safely install or remove the voxshell Claude Code Stop hook."""

import argparse
import difflib
import json
import os
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path


HOOK_MARKER = "voxshell-speak.py"


def speak_command() -> str:
    script = Path(__file__).resolve().with_name(HOOK_MARKER)
    return f"python3 {shlex.quote(str(script))}"


def hook_entry() -> dict:
    return {
        "type": "command",
        "command": speak_command(),
        "async": True,
        "timeout": 10,
    }


def load_settings(path: Path):
    if not path.exists():
        return {}, ""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse failed / JSON 解析失敗: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("settings root must be an object / settings 根層必須是物件")
    return data, raw


def dump_settings(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def stop_groups(data: dict):
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be an object / hooks 必須是物件")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise ValueError("hooks.Stop must be an array / hooks.Stop 必須是陣列")
    return stop


def command_is_voxshell(item) -> bool:
    return isinstance(item, dict) and HOOK_MARKER in str(item.get("command", ""))


def is_installed(stop: list) -> bool:
    for group in stop:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        if any(command_is_voxshell(item) for item in hooks):
            return True
    return False


def install(data: dict) -> bool:
    stop = stop_groups(data)
    if is_installed(stop):
        return False
    stop.append({"hooks": [hook_entry()]})
    return True


def uninstall(data: dict) -> bool:
    stop = stop_groups(data)
    changed = False
    for group in stop:
        if not isinstance(group, dict):
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            continue
        kept = [item for item in hooks if not command_is_voxshell(item)]
        if len(kept) != len(hooks):
            group["hooks"] = kept
            changed = True
    return changed


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
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"{path} (current)",
        tofile=f"{path} (new)",
    )
    output = "".join(diff)
    if output:
        print(output, end="")
    else:
        print("No changes / 無變更")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Install voxshell Claude Code Stop hook")
    parser.add_argument("--settings", default="~/.claude/settings.json", help="Claude settings.json path")
    parser.add_argument("--uninstall", action="store_true", help="Remove voxshell hook")
    parser.add_argument("--dry-run", action="store_true", help="Print diff without writing")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv or sys.argv[1:])
    settings = Path(args.settings).expanduser()
    try:
        data, before = load_settings(settings)
        changed = uninstall(data) if args.uninstall else install(data)
        after = dump_settings(data)

        if args.dry_run:
            print_diff(settings, before, after)
            return 0

        if not changed:
            action = "not installed" if args.uninstall else "already installed"
            print(f"voxshell hook {action} / voxshell hook {action}")
            return 0

        if settings.exists():
            backup_path = backup(settings)
            print(f"Backup created / 已備份: {backup_path}")
        atomic_write(settings, after)
        action = "removed" if args.uninstall else "installed"
        print(f"voxshell hook {action} / voxshell hook 已{'移除' if args.uninstall else '安裝'}")
    except ValueError as exc:
        print(f"Stop, no write / 停止，未寫入: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed / 失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
