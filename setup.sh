#!/bin/bash
set -e

cd "$(dirname "${0}")"

say_line() {
  local en="${1}"
  local zh="${2}"
  printf '%s / %s\n' "${en}" "${zh}"
}

os_name="$(uname)"
if [ "${os_name}" != "Darwin" ]; then
  say_line "This setup script is for macOS." "這個 setup.sh 目前只支援 macOS。"
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  say_line "Homebrew is not installed." "找不到 Homebrew。"
  say_line "Install it with the official command below." "請用下面的官方指令安裝。"
  printf '%s\n' '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  say_line "Installing ffmpeg with Homebrew." "正在用 Homebrew 安裝 ffmpeg。"
  brew install ffmpeg
else
  say_line "ffmpeg is already installed." "ffmpeg 已安裝。"
fi

if ! command -v python3 >/dev/null 2>&1; then
  say_line "python3 was not found." "找不到 python3。"
  say_line "Install Python 3, then run ./setup.sh again." "請先安裝 Python 3，再重新執行 ./setup.sh。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  say_line "Creating Python virtual environment." "正在建立 Python 虛擬環境。"
  python3 -m venv .venv
else
  say_line "Using existing Python virtual environment." "沿用現有 Python 虛擬環境。"
fi

.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

found_cli=""
for cli in claude codex gemini; do
  if command -v "${cli}" >/dev/null 2>&1; then
    if [ -z "${found_cli}" ]; then
      found_cli="${cli}"
    else
      found_cli="${found_cli}, ${cli}"
    fi
  fi
done

if [ -n "${found_cli}" ]; then
  say_line "AI CLI found: ${found_cli}" "找到 AI CLI：${found_cli}"
else
  say_line "No AI CLI found yet." "目前還沒有找到 AI CLI。"
  say_line "Install claude, codex, or gemini before running voxshell." "啟動 voxshell 前，請先安裝 claude、codex 或 gemini 其中一個。"
fi

say_line "Setup complete." "安裝完成。"
say_line "Start Codex push-to-talk with: ./run-ptt.sh" "用 ./run-ptt.sh 啟動 Codex Push-to-Talk。"
say_line "Start the legacy conversation demo with: ./run.sh" "用 ./run.sh 啟動舊版語音對話示範。"
