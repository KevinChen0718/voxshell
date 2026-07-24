#!/usr/bin/env python3
"""Small, private routing state shared by the Codex hook and push-to-talk."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional


STATE_FILENAME = "active-codex-session.json"
STATE_VERSION = 1
DEFAULT_TTL_SECONDS = 15 * 60
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def _nonempty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def state_from_codex_payload(
    payload: dict,
    *,
    notified_at: Optional[float] = None,
) -> Optional[dict]:
    """Normalize a Codex notify payload into the minimal routing state."""
    if not isinstance(payload, dict) or payload.get("type") != "agent-turn-complete":
        return None

    session_id = _nonempty_string(payload.get("thread-id"))
    cwd = _nonempty_string(payload.get("cwd"))
    if (
        not session_id
        or not SESSION_ID_PATTERN.fullmatch(session_id)
        or not cwd
        or "\x00" in cwd
        or not Path(cwd).is_absolute()
    ):
        return None

    timestamp = time.time() if notified_at is None else notified_at
    if not isinstance(timestamp, (int, float)) or timestamp < 0:
        return None

    project_name = Path(cwd.rstrip(os.sep)).name or cwd
    return {
        "version": STATE_VERSION,
        "session_id": session_id,
        "cwd": cwd,
        "project_name": project_name,
        "notified_at": float(timestamp),
    }


def validate_state(data: Any) -> Optional[dict]:
    """Return a normalized copy of valid state, otherwise None."""
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None

    session_id = _nonempty_string(data.get("session_id"))
    cwd = _nonempty_string(data.get("cwd"))
    project_name = _nonempty_string(data.get("project_name"))
    notified_at = data.get("notified_at")
    if (
        not session_id
        or not SESSION_ID_PATTERN.fullmatch(session_id)
        or not cwd
        or "\x00" in cwd
        or not Path(cwd).is_absolute()
        or not project_name
        or not isinstance(notified_at, (int, float))
        or notified_at < 0
    ):
        return None

    return {
        "version": STATE_VERSION,
        "session_id": session_id,
        "cwd": cwd,
        "project_name": project_name,
        "notified_at": float(notified_at),
    }


def state_is_fresh(
    state: dict,
    *,
    now: Optional[float] = None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> bool:
    if ttl_seconds <= 0:
        return False
    normalized = validate_state(state)
    if normalized is None:
        return False
    current = time.time() if now is None else now
    age = current - normalized["notified_at"]
    return 0 <= age <= ttl_seconds


def atomic_write_state(home: Path, state: dict) -> Path:
    """Write state with mode 0600 using temp-file + replace."""
    normalized = validate_state(state)
    if normalized is None:
        raise ValueError("invalid voxshell session state")

    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / STATE_FILENAME
    fd, temporary = tempfile.mkstemp(
        prefix=f".{STATE_FILENAME}.",
        suffix=".tmp",
        dir=str(home),
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def remember_codex_session(
    home: Path,
    payload: dict,
    *,
    notified_at: Optional[float] = None,
) -> bool:
    state = state_from_codex_payload(payload, notified_at=notified_at)
    if state is None:
        return False
    atomic_write_state(home, state)
    return True


def load_active_session(
    home: Path,
    *,
    now: Optional[float] = None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    is_directory: Callable[[str], bool] = os.path.isdir,
) -> Optional[dict]:
    """Load a fresh routing target and reject stale or missing directories."""
    path = home / STATE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    state = validate_state(data)
    if state is None or not state_is_fresh(state, now=now, ttl_seconds=ttl_seconds):
        return None
    try:
        directory_exists = is_directory(state["cwd"])
    except (OSError, ValueError):
        return None
    if not directory_exists:
        return None
    return state
