#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

TMPDIR="$(mktemp -d)"
trap 'find "$TMPDIR" -depth -delete' EXIT

export VOXSHELL_HOME="$TMPDIR/voxshell-home"
export SAY_LOG="$TMPDIR/say.log"
export SAY_TEXT="$TMPDIR/say-text.log"
mkdir -p "$VOXSHELL_HOME"

STUB="$TMPDIR/say-stub.sh"
cat > "$STUB" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SAY_LOG"
last="${!#}"
printf '%s\n' "$last" >> "$SAY_TEXT"
STUB
chmod +x "$STUB"
export VOXSHELL_SAY_CMD="$STUB"

SPEAK="$ROOT/hooks/voxshell-speak.py"
INSTALLER="$ROOT/hooks/install_claude_hook.py"
CODEX_INSTALLER="$ROOT/hooks/install_codex_notify.py"

reset_say() {
  : > "$SAY_LOG"
  : > "$SAY_TEXT"
  [[ ! -e "$VOXSHELL_HOME/mute" ]] || unlink "$VOXSHELL_HOME/mute"
  [[ ! -e "$VOXSHELL_HOME/speak.pid" ]] || unlink "$VOXSHELL_HOME/speak.pid"
}

wait_for_lines() {
  local file="$1"
  local expected="$2"
  local i
  for i in {1..50}; do
    if [[ -f "$file" ]] && [[ "$(wc -l < "$file" | tr -d ' ')" -ge "$expected" ]]; then
      return 0
    fi
    sleep 0.05
  done
  return 1
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf 'FAIL %s\nexpected: %s\nactual:   %s\n' "$label" "$expected" "$actual" >&2
    exit 1
  fi
  printf 'ok - %s\n' "$label"
}

assert_no_say() {
  local label="$1"
  sleep 0.15
  if [[ -s "$SAY_TEXT" ]]; then
    printf 'FAIL %s\nunexpected say text: %s\n' "$label" "$(cat "$SAY_TEXT")" >&2
    exit 1
  fi
  printf 'ok - %s\n' "$label"
}

run_speak() {
  "$PYTHON" "$SPEAK"
}

run_codex_notify() {
  "$PYTHON" "$SPEAK" --codex-notify "$1"
}

run_preview() {
  "$PYTHON" "$SPEAK" --preview "$1"
}

run_demo() {
  "$PYTHON" "$SPEAK" --demo "$1"
}

reset_say
printf '%s' '{"last_assistant_message":"第一句。第二句！第三句？"}' | run_speak
wait_for_lines "$SAY_TEXT" 1
assert_eq "第一句。 第二句！" "$(tail -n 1 "$SAY_TEXT")" "normal Chinese speaks first two sentences"

reset_say
cat <<'JSON' | run_speak
{"last_assistant_message":"我改好了。\n```python\nfor i in range(10):\n    print(i)\n```\n測試通過。第三句。"}
JSON
wait_for_lines "$SAY_TEXT" 1
assert_eq "我改好了。 測試通過。" "$(tail -n 1 "$SAY_TEXT")" "code block removed, natural text remains"

reset_say
cat <<'JSON' | run_speak
{"last_assistant_message":"```python\ndef f(x):\n    return x + 1\n```"}
JSON
assert_no_say "mostly code does not speak"

reset_say
touch "$VOXSHELL_HOME/mute"
printf '%s' '{"last_assistant_message":"這段不應該被念。"}' | run_speak
assert_no_say "mute marker suppresses speech"

reset_say
bad_output="$(printf '{bad json' | "$PYTHON" "$SPEAK" 2>&1)"
assert_eq "" "$bad_output" "bad JSON exits silently"

reset_say
TRANSCRIPT="$TMPDIR/transcript.jsonl"
cat > "$TRANSCRIPT" <<'JSONL'
{"type":"user","message":{"content":"不要念這句。"}}
{"message":{"role":"assistant","content":[{"type":"text","text":"備援第一句。備援第二句。備援第三句。"}]}}
JSONL
printf '{"transcript_path":"%s"}' "$TRANSCRIPT" | run_speak
wait_for_lines "$SAY_TEXT" 1
assert_eq "備援第一句。 備援第二句。" "$(tail -n 1 "$SAY_TEXT")" "transcript fallback speaks assistant text"

reset_say
run_codex_notify '{"type":"agent-turn-complete","last-assistant-message":"Codex 第一句。Codex 第二句。Codex 第三句。"}'
wait_for_lines "$SAY_TEXT" 1
assert_eq "Codex 第一句。 Codex 第二句。" "$(tail -n 1 "$SAY_TEXT")" "codex notify speaks first two sentences"

reset_say
run_codex_notify "{\"type\":\"agent-turn-complete\",\"thread-id\":\"thread-123\",\"cwd\":\"$TMPDIR\",\"last-assistant-message\":\"已完成並保存路由。\"}"
wait_for_lines "$SAY_TEXT" 1
"$PYTHON" - "$VOXSHELL_HOME/active-codex-session.json" "$TMPDIR" <<'PY'
import json
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
assert state["version"] == 1
assert state["session_id"] == "thread-123"
assert state["cwd"] == sys.argv[2]
assert state["project_name"] == Path(sys.argv[2]).name
assert isinstance(state["notified_at"], float)
assert "last-assistant-message" not in state
assert stat.S_IMODE(path.stat().st_mode) == 0o600
PY
printf 'ok - spoken Codex notify stores only private routing state\n'

reset_say
preview_output="$(run_preview $'完成修正。\n```python\nprint("skip")\n```\n測試通過。第三句。')"
assert_eq "完成修正。 測試通過。" "$preview_output" "preview prints cleaned first two sentences"
assert_no_say "preview never launches say"

reset_say
demo_output="$(run_demo 'Demo 第一句。Demo 第二句。Demo 第三句。')"
wait_for_lines "$SAY_TEXT" 1
assert_eq "Demo 第一句。 Demo 第二句。" "$(tail -n 1 "$SAY_TEXT")" "demo speaks through the production pipeline"
assert_eq "Speaking / 正在朗讀: Demo 第一句。 Demo 第二句。" "$demo_output" "demo reports the spoken script"

reset_say
set +e
empty_preview_output="$("$PYTHON" "$SPEAK" --preview 2>&1)"
empty_preview_status=$?
set -e
assert_eq "2" "$empty_preview_status" "preview without text exits 2"
if [[ "$empty_preview_output" != Usage:* ]]; then
  echo "FAIL preview without text should print usage" >&2
  exit 1
fi
printf 'ok - preview without text prints usage\n'

reset_say
run_codex_notify '{"type":"other-event","last-assistant-message":"這段不應該被念。"}'
assert_no_say "codex notify ignores non turn-complete type"

reset_say
bad_codex_output="$("$PYTHON" "$SPEAK" --codex-notify '{bad json' 2>&1)"
assert_eq "" "$bad_codex_output" "codex notify bad JSON exits silently"

reset_say
VOXSHELL_MUTE=1 run_codex_notify '{"type":"agent-turn-complete","last-assistant-message":"這段也不應該被念。"}'
assert_no_say "env mute suppresses codex notify before payload handling"

SUMMARY_OK="$TMPDIR/summary-ok.sh"
cat > "$SUMMARY_OK" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
printf '%s\n' '摘要成功。'
STUB
chmod +x "$SUMMARY_OK"

reset_say
printf '{"summary_cmd":"%s","summary_timeout":2}\n' "$SUMMARY_OK" > "$VOXSHELL_HOME/config.json"
printf '%s' '{"last_assistant_message":"原文第一句。原文第二句。原文第三句。"}' | run_speak
wait_for_lines "$SAY_TEXT" 1
assert_eq "摘要成功。" "$(tail -n 1 "$SAY_TEXT")" "summary_cmd successful output replaces first-two-sentence script"

reset_say
preview_with_summary="$(run_preview '預覽第一句。預覽第二句。預覽第三句。')"
assert_eq "預覽第一句。 預覽第二句。" "$preview_with_summary" "preview skips optional summary command"
assert_no_say "preview with summary config remains silent"

SUMMARY_SLOW="$TMPDIR/summary-slow.sh"
cat > "$SUMMARY_SLOW" <<'STUB'
#!/usr/bin/env bash
sleep 1
printf '%s\n' '太慢了。'
STUB
chmod +x "$SUMMARY_SLOW"

reset_say
printf '{"summary_cmd":"%s","summary_timeout":0.1}\n' "$SUMMARY_SLOW" > "$VOXSHELL_HOME/config.json"
printf '%s' '{"last_assistant_message":"逾時第一句。逾時第二句。逾時第三句。"}' | run_speak
wait_for_lines "$SAY_TEXT" 1
assert_eq "逾時第一句。 逾時第二句。" "$(tail -n 1 "$SAY_TEXT")" "summary_cmd timeout falls back silently"
[[ ! -e "$VOXSHELL_HOME/config.json" ]] || unlink "$VOXSHELL_HOME/config.json"

SETTINGS_DIR="$TMPDIR/claude"
SETTINGS="$SETTINGS_DIR/settings.json"
mkdir -p "$SETTINGS_DIR"
cat > "$SETTINGS" <<'JSON'
{
  "theme": "dark",
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo existing",
            "timeout": 1
          }
        ]
      }
    ]
  },
  "custom": {
    "keep": true
  }
}
JSON

"$PYTHON" "$INSTALLER" --settings "$SETTINGS" >"$TMPDIR/install-1.out"
backup_count="$(find "$SETTINGS_DIR" -name 'settings.json.bak.*' | wc -l | tr -d ' ')"
[[ "$backup_count" -ge 1 ]] || { echo "FAIL installer backup missing" >&2; exit 1; }
"$PYTHON" "$INSTALLER" --settings "$SETTINGS" >"$TMPDIR/install-2.out"
"$PYTHON" - "$SETTINGS" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
assert data["theme"] == "dark"
assert data["custom"]["keep"] is True
stop = data["hooks"]["Stop"]
commands = [
    hook["command"]
    for group in stop
    for hook in group.get("hooks", [])
    if isinstance(hook, dict)
]
assert "echo existing" in commands
assert sum("voxshell-speak.py" in command for command in commands) == 1
entry = next(hook for group in stop for hook in group.get("hooks", []) if "voxshell-speak.py" in hook.get("command", ""))
assert entry["type"] == "command"
assert entry["async"] is True
assert entry["timeout"] == 10
PY
"$PYTHON" "$INSTALLER" --settings "$SETTINGS" --uninstall >"$TMPDIR/uninstall.out"
"$PYTHON" - "$SETTINGS" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
assert data["theme"] == "dark"
assert data["custom"]["keep"] is True
commands = [
    hook["command"]
    for group in data["hooks"]["Stop"]
    for hook in group.get("hooks", [])
    if isinstance(hook, dict)
]
assert "echo existing" in commands
assert not any("voxshell-speak.py" in command for command in commands)
PY
printf 'ok - installer install, idempotent rerun, uninstall preserve JSON\n'

CODEX_DIR="$TMPDIR/codex"
CODEX_CONFIG="$CODEX_DIR/config.toml"
mkdir -p "$CODEX_DIR"
cat > "$CODEX_CONFIG" <<'TOML'
model = "gpt-5"

[profiles.default]
approval_policy = "never"
TOML
"$PYTHON" "$CODEX_INSTALLER" --config "$CODEX_CONFIG" >"$TMPDIR/codex-install-1.out"
"$PYTHON" - "$CODEX_CONFIG" "$ROOT/hooks/voxshell-speak.py" <<'PY'
import sys
from pathlib import Path

config = Path(sys.argv[1])
script = str(Path(sys.argv[2]).resolve())
text = config.read_text()
expected = f'notify = ["python3", "{script}", "--codex-notify"]\n'
assert text.startswith(expected), text
assert 'model = "gpt-5"' in text
assert '[profiles.default]' in text
PY
before_idempotent="$(cat "$CODEX_CONFIG")"
"$PYTHON" "$CODEX_INSTALLER" --config "$CODEX_CONFIG" >"$TMPDIR/codex-install-2.out"
assert_eq "$before_idempotent" "$(cat "$CODEX_CONFIG")" "codex installer idempotent when already installed"
"$PYTHON" "$CODEX_INSTALLER" --config "$CODEX_CONFIG" --uninstall >"$TMPDIR/codex-uninstall.out"
"$PYTHON" - "$CODEX_CONFIG" <<'PY'
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
assert "voxshell-speak.py" not in text
assert text.startswith('model = "gpt-5"\n')
assert '[profiles.default]' in text
PY
printf 'ok - codex installer install, idempotent rerun, uninstall preserve TOML\n'

OTHER_NOTIFY="$CODEX_DIR/other-notify.toml"
cat > "$OTHER_NOTIFY" <<'TOML'
notify = ["terminal-notifier", "-message", "done"]
model = "gpt-5"
TOML
before_other="$(cat "$OTHER_NOTIFY")"
set +e
"$PYTHON" "$CODEX_INSTALLER" --config "$OTHER_NOTIFY" >"$TMPDIR/codex-conflict.out" 2>"$TMPDIR/codex-conflict.err"
conflict_status=$?
set -e
assert_eq "1" "$conflict_status" "codex installer exits 1 for existing other notify"
assert_eq "$before_other" "$(cat "$OTHER_NOTIFY")" "codex installer leaves existing other notify unchanged"

DRY_RUN_CONFIG="$CODEX_DIR/dry-run.toml"
cat > "$DRY_RUN_CONFIG" <<'TOML'
[profiles.default]
model = "gpt-5"
TOML
before_dry_run="$(cat "$DRY_RUN_CONFIG")"
"$PYTHON" "$CODEX_INSTALLER" --config "$DRY_RUN_CONFIG" --dry-run >"$TMPDIR/codex-dry-run.out"
assert_eq "$before_dry_run" "$(cat "$DRY_RUN_CONFIG")" "codex installer dry-run leaves file unchanged"
if ! grep -q '^+notify = ' "$TMPDIR/codex-dry-run.out"; then
  echo "FAIL codex installer dry-run diff missing notify line" >&2
  exit 1
fi
printf 'ok - codex installer conflict and dry-run behavior\n'

printf 'all tests passed\n'
