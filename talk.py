#!/usr/bin/env python3
"""
voxshell: a local voice conversation shell for macOS.

Pipeline: ffmpeg records audio, faster-whisper transcribes it, an AI CLI thinks,
and macOS say speaks the reply.
"""

import argparse
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

VIRTUAL_HINTS = (
    "teams",
    "microsoft",
    "aggregate",
    "virtual",
    "blackhole",
    "soundflower",
    "zoomaudio",
    "loopback",
    "multi-output",
)
BUILTIN_HINTS = ("macbook", "built-in", "內建", "imac", "mac mini", "mac studio")
EXIT_WORDS_ZH = ("掰掰", "再見", "結束", "拜拜")
EXIT_WORDS_EN = {"bye", "goodbye", "exit", "quit"}
DEFAULT_PERSONA = (
    "You are a calm, neutral voice assistant. Reply in the same language the "
    "user used. Keep answers short, natural, conversational, and easy to hear "
    "when spoken aloud. Do not use bullet points, numbering, markdown, code "
    "blocks, or long lists."
)

HERE = os.path.dirname(os.path.abspath(__file__))


def say_line(en: str, zh: str) -> None:
    """Print a short bilingual message."""
    print(f"{en} / {zh}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Local voice chat shell for macOS. / macOS 本機語音對話外殼。"
        )
    )
    parser.add_argument(
        "--voice",
        default=None,
        help="macOS say voice name. Default: system voice. / say 聲音名。預設：系統聲音。",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        help=(
            "faster-whisper model name, such as tiny/base/small/medium/large-v3. "
            "Default: base. / faster-whisper 模型名，例如 tiny/base/small/medium/large-v3。預設：base。"
        ),
    )
    parser.add_argument(
        "--lang",
        default="auto",
        help=(
            "Speech language code. Use auto for detection. Default: auto. / "
            "辨識語言代碼；auto 代表自動偵測。預設：auto。"
        ),
    )
    parser.add_argument(
        "--rate",
        default=None,
        type=int,
        help="Speech rate in words per minute. Default: system rate. / 語速，每分鐘字數。預設：系統語速。",
    )
    parser.add_argument(
        "--brain",
        default="claude -p",
        help=(
            "AI CLI command template. The prompt is appended as the final argument. "
            "Default: claude -p. / AI CLI 指令樣板；prompt 會接在最後一個參數。預設：claude -p。"
        ),
    )
    parser.add_argument(
        "--persona",
        default=DEFAULT_PERSONA,
        help=(
            "System persona text. Prefix with @ to read from a file. / "
            "系統人格描述；用 @ 開頭可讀取檔案。"
        ),
    )
    return parser


def split_brain_command(brain: str) -> Optional[List[str]]:
    """Split the AI CLI command template."""
    try:
        command = shlex.split(brain)
    except ValueError:
        return None
    return command or None


def load_persona(persona_arg: str) -> Optional[str]:
    """Load persona text, optionally from a file."""
    if not persona_arg.startswith("@"):
        return persona_arg

    path = os.path.expanduser(persona_arg[1:])
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        say_line(
            "Could not read the persona file.",
            "讀不到 persona 檔案。",
        )
        print(f"Path / 路徑：{path}")
        return None


def check_startup(brain_command: List[str]):
    """Run dependency checks before importing faster-whisper."""
    if shutil.which("ffmpeg") is None:
        say_line(
            "ffmpeg is not installed or not in PATH.",
            "找不到 ffmpeg，或 ffmpeg 不在 PATH 裡。",
        )
        say_line(
            "Install it with: brew install ffmpeg",
            "請執行：brew install ffmpeg",
        )
        sys.exit(1)

    if shutil.which(brain_command[0]) is None:
        say_line(
            "The AI CLI command was not found in PATH.",
            "找不到 AI CLI 指令，或它不在 PATH 裡。",
        )
        print(f"Command / 指令：{brain_command[0]}")
        say_line(
            "Install one CLI such as claude, codex, or gemini, then try again.",
            "請先安裝 claude、codex 或 gemini 其中一個 CLI，再重試。",
        )
        sys.exit(1)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        say_line(
            "faster-whisper is not installed in this environment.",
            "這個環境還沒有安裝 faster-whisper。",
        )
        say_line(
            "Run ./setup.sh first.",
            "請先執行 ./setup.sh。",
        )
        sys.exit(1)

    return WhisperModel


def find_audio_device() -> str:
    """Choose a real microphone avfoundation index and avoid virtual devices."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
        ).stderr
    except Exception:
        return "0"

    devices = []
    in_audio = False
    for line in out.splitlines():
        low = line.lower()
        if "audio devices" in low:
            in_audio = True
            continue
        if "video devices" in low:
            in_audio = False
            continue
        if in_audio:
            match = re.search(r"\]\s*\[(\d+)\]\s*(.+)$", line)
            if match:
                devices.append((match.group(1), match.group(2).strip()))

    if not devices:
        return "0"
    real = [device for device in devices if not any(h in device[1].lower() for h in VIRTUAL_HINTS)]
    pool = real or devices
    for index, name in pool:
        if any(h in name.lower() for h in BUILTIN_HINTS):
            return index
    return pool[0][0]


def record(wav_path: str, device: str) -> None:
    """Record audio with ffmpeg until the user presses Enter again."""
    input("\nPress Enter to start speaking. / 按 Enter 開始講話。")
    say_line(
        "Recording. Press Enter again when you are done.",
        "錄音中。講完後再按一次 Enter 停止。",
    )
    try:
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "avfoundation",
                "-i",
                f":{device}",
                "-ar",
                "16000",
                "-ac",
                "1",
                wav_path,
            ],
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        say_line(
            "Could not start ffmpeg recording.",
            "無法啟動 ffmpeg 錄音。",
        )
        return

    input()
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait()


def listen(model, wav_path: str, language: Optional[str]) -> str:
    """Transcribe the recording and return an empty string on recoverable errors."""
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) < 2000:
        return ""
    try:
        segments, _ = model.transcribe(wav_path, language=language)
        return "".join(segment.text for segment in segments).strip()
    except Exception:
        say_line(
            "I could not understand this recording.",
            "這段錄音聽不出來。",
        )
        return ""


def format_history(history: List[Dict[str, str]]) -> str:
    """Format the stateless conversation prompt."""
    lines = []
    for message in history:
        speaker = "User" if message["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {message['content']}")
    return "\n".join(lines)


def think(history: List[Dict[str, str]], brain_command: List[str], persona: str) -> str:
    """Send the full conversation to the configured AI CLI."""
    convo = format_history(history)
    prompt = (
        f"{persona}\n\n"
        "Current conversation:\n"
        f"{convo}\n\n"
        "Reply naturally to the user's latest message:"
    )
    try:
        result = subprocess.run(
            brain_command + [prompt],
            capture_output=True,
            text=True,
            cwd=HERE,
        )
    except OSError:
        say_line(
            "Could not start the AI CLI.",
            "無法啟動 AI CLI。",
        )
        return "I could not start the AI command. / 我無法啟動 AI 指令。"

    if result.returncode != 0:
        say_line(
            "The AI CLI returned an error.",
            "AI CLI 回傳錯誤。",
        )
        say_line(
            "Check that the CLI is installed and logged in.",
            "請確認 CLI 已安裝，而且已完成登入。",
        )
        return "I could not get a reply from the AI command. / 我無法從 AI 指令取得回覆。"

    reply = result.stdout.strip()
    if not reply:
        say_line(
            "The AI CLI returned an empty reply.",
            "AI CLI 回傳空白內容。",
        )
        return "I could not get a reply from the AI command. / 我無法從 AI 指令取得回覆。"
    return reply


def speak(text: str, voice: Optional[str], rate: Optional[int]) -> None:
    """Speak text with macOS say."""
    command = ["say"]
    if voice:
        command.extend(["-v", voice])
    if rate is not None:
        command.extend(["-r", str(rate)])
    command.append(text)
    try:
        subprocess.run(command)
    except OSError:
        say_line(
            "Could not start macOS say.",
            "無法啟動 macOS say。",
        )


def should_exit(text: str) -> bool:
    """Return True when the transcript contains an exit phrase."""
    if any(word in text for word in EXIT_WORDS_ZH):
        return True
    english_words = set(re.findall(r"[A-Za-z]+", text.lower()))
    return bool(english_words & EXIT_WORDS_EN)


def print_microphone_help() -> None:
    """Print macOS microphone permission guidance."""
    say_line(
        "The first recording was empty or too small.",
        "第一段錄音是空的，或檔案太小。",
    )
    say_line(
        "Check System Settings -> Privacy & Security -> Microphone, then enable your Terminal app.",
        "請檢查 System Settings → Privacy & Security → Microphone，並打開你的終端機 App 權限。",
    )


def main() -> None:
    os.environ.pop("PYTHONPATH", None)
    parser = build_parser()
    args = parser.parse_args()

    brain_command = split_brain_command(args.brain)
    if brain_command is None:
        say_line(
            "The --brain command could not be parsed.",
            "--brain 指令無法解析。",
        )
        say_line(
            "Example: --brain 'claude -p'",
            "範例：--brain 'claude -p'",
        )
        sys.exit(1)

    persona = load_persona(args.persona)
    if persona is None:
        sys.exit(1)

    WhisperModel = check_startup(brain_command)
    say_line(
        "Loading faster-whisper.",
        "正在載入 faster-whisper。",
    )
    model = WhisperModel(args.whisper_model, device="cpu", compute_type="int8")
    language = None if args.lang == "auto" else args.lang
    device = find_audio_device()

    print("=" * 56)
    say_line("voxshell is ready.", "voxshell 已準備好。")
    print(f"Microphone device index / 麥克風裝置 index：{device}")
    say_line(
        "Press Enter to record. Say bye, goodbye, exit, or quit to stop.",
        "按 Enter 開始錄音。說掰掰、再見、結束、拜拜、bye、goodbye、exit 或 quit 可結束。",
    )
    print("=" * 56)

    history = []
    first_recording = True
    try:
        while True:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                wav = handle.name

            record(wav, device)
            if first_recording:
                first_recording = False
                if not os.path.exists(wav) or os.path.getsize(wav) < 2000:
                    print_microphone_help()

            user_text = listen(model, wav, language)
            try:
                os.unlink(wav)
            except OSError:
                pass

            if not user_text:
                say_line(
                    "I did not hear anything. Please try again.",
                    "我沒有聽到內容，請再試一次。",
                )
                continue

            print(f"\nYou said / 你說：{user_text}")

            if should_exit(user_text):
                goodbye = "Okay, see you next time."
                speak(goodbye, args.voice, args.rate)
                say_line("Goodbye.", "再見。")
                break

            history.append({"role": "user", "content": user_text})
            reply = think(history, brain_command, persona)
            history.append({"role": "assistant", "content": reply})
            print(f"Assistant / 助理：{reply}")
            speak(reply, args.voice, args.rate)
    except KeyboardInterrupt:
        print()
        say_line("Stopped.", "已結束。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say_line(
            "Unexpected error. Please check your setup and try again.",
            "發生未預期錯誤。請檢查安裝後再重試。",
        )
        sys.exit(1)
