#!/usr/bin/env python3
"""Hold a global shortcut, speak, and resume the latest spoken Codex task."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


ROOT = Path(__file__).resolve().parent
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from voxshell_state import (  # noqa: E402
    DEFAULT_TTL_SECONDS,
    load_active_session,
    state_is_fresh,
    validate_state,
)


DEFAULT_HOTKEY = "option+space"
MIN_AUDIO_BYTES = 2000
VIRTUAL_AUDIO_HINTS = (
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
BUILTIN_AUDIO_HINTS = (
    "macbook",
    "built-in",
    "內建",
    "imac",
    "mac mini",
    "mac studio",
)


def voxshell_home() -> Path:
    return Path(os.environ.get("VOXSHELL_HOME", "~/.voxshell")).expanduser()


def say_line(en: str, zh: str) -> None:
    print(f"{en} / {zh}", flush=True)


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: frozenset[str]
    trigger: str

    @classmethod
    def parse(cls, value: str) -> "HotkeySpec":
        aliases = {
            "alt": "option",
            "opt": "option",
            "option": "option",
            "control": "control",
            "ctrl": "control",
            "command": "command",
            "cmd": "command",
            "shift": "shift",
        }
        parts = [part.strip().lower() for part in value.split("+") if part.strip()]
        if len(parts) < 2:
            raise ValueError("hotkey needs at least one modifier and one key")

        trigger = parts[-1]
        if trigger == " ":
            trigger = "space"
        if trigger != "space" and not re.fullmatch(r"[a-z0-9]", trigger):
            raise ValueError("trigger must be space or one letter/number")

        modifiers = []
        for part in parts[:-1]:
            normalized = aliases.get(part)
            if normalized is None:
                raise ValueError(f"unsupported modifier: {part}")
            modifiers.append(normalized)
        if not modifiers or len(set(modifiers)) != len(modifiers):
            raise ValueError("hotkey modifiers must be unique")
        return cls(frozenset(modifiers), trigger)

    @property
    def display(self) -> str:
        symbols = {
            "control": "⌃",
            "option": "⌥",
            "shift": "⇧",
            "command": "⌘",
        }
        ordered = ("control", "option", "shift", "command")
        prefix = "".join(symbols[name] for name in ordered if name in self.modifiers)
        key = "Space" if self.trigger == "space" else self.trigger.upper()
        return f"{prefix} {key}"


@dataclass
class Recording:
    process: subprocess.Popen
    path: Path


@dataclass
class Capture:
    target: dict
    recording: Recording


@dataclass(frozen=True)
class ResumeResult:
    ok: bool
    error: str = ""


class RecordingError(RuntimeError):
    pass


class SoundPlayer:
    SOUNDS = {
        "start": "/System/Library/Sounds/Tink.aiff",
        "stop": "/System/Library/Sounds/Pop.aiff",
        "success": "/System/Library/Sounds/Glass.aiff",
        "cancel": "/System/Library/Sounds/Funk.aiff",
        "error": "/System/Library/Sounds/Basso.aiff",
    }

    def play(self, kind: str) -> None:
        path = self.SOUNDS.get(kind)
        if not path or shutil.which("afplay") is None or not Path(path).exists():
            return
        try:
            subprocess.run(
                ["afplay", path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def find_audio_device() -> str:
    """Choose a physical-looking macOS avfoundation audio input."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "0"

    devices = []
    in_audio = False
    for line in result.stderr.splitlines():
        lowered = line.lower()
        if "audio devices" in lowered:
            in_audio = True
            continue
        if "video devices" in lowered:
            in_audio = False
            continue
        if not in_audio:
            continue
        match = re.search(r"\]\s*\[(\d+)\]\s*(.+)$", line)
        if match:
            devices.append((match.group(1), match.group(2).strip()))

    if not devices:
        return "0"
    physical = [
        item
        for item in devices
        if not any(hint in item[1].lower() for hint in VIRTUAL_AUDIO_HINTS)
    ]
    pool = physical or devices
    for index, name in pool:
        if any(hint in name.lower() for hint in BUILTIN_AUDIO_HINTS):
            return index
    return pool[0][0]


class FfmpegRecorder:
    def __init__(self, device: str):
        self.device = device

    def start(self) -> Recording:
        handle = tempfile.NamedTemporaryFile(
            prefix="voxshell-ptt-",
            suffix=".wav",
            delete=False,
        )
        path = Path(handle.name)
        handle.close()
        try:
            process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "avfoundation",
                    "-i",
                    f":{self.device}",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            _delete_audio(path)
            raise RecordingError(str(exc)) from exc

        # Permission or device failures return almost immediately.
        time.sleep(0.12)
        if process.poll() is not None:
            error = process.stderr.read().strip() if process.stderr else ""
            _delete_audio(path)
            raise RecordingError(error or "ffmpeg stopped before recording")
        return Recording(process=process, path=path)

    def stop(self, recording: Recording) -> None:
        process = recording.process
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired as exc:
                    raise RecordingError("ffmpeg did not stop") from exc
        if process.returncode not in (0, 255):
            error = process.stderr.read().strip() if process.stderr else ""
            raise RecordingError(error or f"ffmpeg exited {process.returncode}")


class LocalWhisperTranscriber:
    def __init__(self, model_name: str, language: Optional[str]):
        from faster_whisper import WhisperModel

        say_line("Loading local speech model.", "正在載入本機語音模型。")
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.language = language

    def transcribe(self, path: Path) -> str:
        if not path.exists() or path.stat().st_size < MIN_AUDIO_BYTES:
            return ""
        segments, _ = self.model.transcribe(str(path), language=self.language)
        return "".join(segment.text for segment in segments).strip()


def resume_codex(
    target: dict,
    transcript: str,
    *,
    codex_command: str = "codex",
    runner: Callable = subprocess.run,
) -> ResumeResult:
    """Resume Codex with fixed argv and pass the transcript only on stdin."""
    text = transcript.strip()
    if not text:
        return ResumeResult(False, "empty transcript")
    normalized = validate_state(target)
    if normalized is None:
        return ResumeResult(False, "invalid Codex target")

    command = [
        codex_command,
        "exec",
        "resume",
        normalized["session_id"],
        "-",
    ]
    try:
        result = runner(
            command,
            input=text,
            text=True,
            cwd=normalized["cwd"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return ResumeResult(False, str(exc))
    if result.returncode != 0:
        error = (result.stderr or "").strip()
        return ResumeResult(False, error or f"Codex exited {result.returncode}")
    return ResumeResult(True)


def _delete_audio(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


class PushToTalkController:
    """Thread-safe recording lifecycle independent from the keyboard backend."""

    def __init__(
        self,
        *,
        home: Path,
        ttl_seconds: float,
        recorder,
        transcriber,
        sender: Callable[[dict, str], ResumeResult],
        sound: SoundPlayer,
        clock: Callable[[], float] = time.time,
        worker_factory: Optional[Callable[[Callable[[], None]], object]] = None,
    ):
        self.home = home
        self.ttl_seconds = ttl_seconds
        self.recorder = recorder
        self.transcriber = transcriber
        self.sender = sender
        self.sound = sound
        self.clock = clock
        self.worker_factory = worker_factory or self._thread_worker
        self.lock = threading.Lock()
        self.capture: Optional[Capture] = None
        self.busy = False
        self.last_failed_transcript = ""
        self.worker = None

    @staticmethod
    def _thread_worker(callback: Callable[[], None]):
        worker = threading.Thread(target=callback, name="voxshell-ptt-send")
        worker.start()
        return worker

    def begin(self) -> bool:
        with self.lock:
            if self.capture is not None or self.busy:
                return False

        target = load_active_session(
            self.home,
            now=self.clock(),
            ttl_seconds=self.ttl_seconds,
        )
        if target is None:
            self.sound.play("error")
            say_line(
                "No recent Codex task. Let Codex finish a spoken turn first.",
                "沒有最近的 Codex 任務；請先讓 Codex 完成並朗讀一輪。",
            )
            return False

        self.sound.play("start")
        try:
            recording = self.recorder.start()
        except Exception as exc:
            self.sound.play("error")
            say_line(
                "Could not start the microphone.",
                "無法啟動麥克風。",
            )
            print(str(exc), file=sys.stderr, flush=True)
            return False

        with self.lock:
            if self.capture is not None or self.busy:
                try:
                    self.recorder.stop(recording)
                finally:
                    _delete_audio(recording.path)
                return False
            # Copy at key-down. Later notify updates cannot retarget this capture.
            self.capture = Capture(target=dict(target), recording=recording)
        print(
            f"Recording for {target['project_name']}… / "
            f"正在錄給 {target['project_name']}…",
            flush=True,
        )
        return True

    def end(self) -> bool:
        with self.lock:
            capture = self.capture
            if capture is None:
                return False
            self.capture = None
            self.busy = True

        try:
            self.recorder.stop(capture.recording)
        except Exception as exc:
            _delete_audio(capture.recording.path)
            with self.lock:
                self.busy = False
            self.sound.play("error")
            say_line("Recording failed; nothing was sent.", "錄音失敗，沒有送出。")
            print(str(exc), file=sys.stderr, flush=True)
            return False

        self.sound.play("stop")
        self.worker = self.worker_factory(lambda: self._finish(capture))
        return True

    def cancel(self) -> bool:
        with self.lock:
            capture = self.capture
            if capture is None:
                return False
            self.capture = None
        try:
            self.recorder.stop(capture.recording)
        except Exception:
            pass
        _delete_audio(capture.recording.path)
        self.sound.play("cancel")
        say_line("Recording cancelled.", "已取消錄音。")
        return True

    def _finish(self, capture: Capture) -> None:
        try:
            try:
                transcript = self.transcriber.transcribe(capture.recording.path).strip()
            except Exception as exc:
                self.sound.play("error")
                say_line("Transcription failed; nothing was sent.", "轉錄失敗，沒有送出。")
                print(str(exc), file=sys.stderr, flush=True)
                return

            if not transcript:
                self.sound.play("error")
                say_line("I did not hear a command; nothing was sent.", "沒有聽到指令，未送出。")
                return

            if not state_is_fresh(
                capture.target,
                now=self.clock(),
                ttl_seconds=self.ttl_seconds,
            ):
                self.last_failed_transcript = transcript
                self.sound.play("error")
                say_line("The Codex task expired; nothing was sent.", "Codex 任務已逾時，沒有送出。")
                print(f"Transcript / 逐字稿：{transcript}", flush=True)
                return

            try:
                result = self.sender(capture.target, transcript)
            except Exception as exc:
                result = ResumeResult(False, str(exc))
            if not result.ok:
                self.last_failed_transcript = transcript
                self.sound.play("error")
                say_line("Codex resume failed; nothing was retried.", "Codex 續接失敗，沒有自動重試。")
                print(f"Transcript / 逐字稿：{transcript}", flush=True)
                if result.error:
                    print(result.error, file=sys.stderr, flush=True)
                return

            self.last_failed_transcript = ""
            self.sound.play("success")
            print(
                f"Sent to {capture.target['project_name']}. / "
                f"已送到 {capture.target['project_name']}。",
                flush=True,
            )
        finally:
            _delete_audio(capture.recording.path)
            with self.lock:
                self.busy = False

    def wait(self) -> None:
        worker = self.worker
        if hasattr(worker, "join"):
            worker.join()


class GlobalKeyboardAdapter:
    """Translate only the configured shortcut and Esc into controller events."""

    MODIFIER_NAMES = {
        "alt": "option",
        "alt_l": "option",
        "alt_r": "option",
        "alt_gr": "option",
        "ctrl": "control",
        "ctrl_l": "control",
        "ctrl_r": "control",
        "cmd": "command",
        "cmd_l": "command",
        "cmd_r": "command",
        "shift": "shift",
        "shift_l": "shift",
        "shift_r": "shift",
    }

    def __init__(self, spec: HotkeySpec, controller: PushToTalkController):
        self.spec = spec
        self.controller = controller
        self.modifiers_down: set[str] = set()
        self.trigger_down = False
        self.activated = False

    def _key_name(self, key) -> Optional[str]:
        name = getattr(key, "name", None)
        if isinstance(name, str):
            if name in self.MODIFIER_NAMES:
                return self.MODIFIER_NAMES[name]
            if name in ("space", "esc"):
                return name
        char = getattr(key, "char", None)
        if isinstance(char, str) and len(char) == 1:
            return char.lower()
        return None

    def on_press(self, key):
        name = self._key_name(key)
        if name in self.spec.modifiers:
            self.modifiers_down.add(name)
            return
        if name == "esc":
            if self.controller.cancel():
                self.activated = False
            return
        if (
            name == self.spec.trigger
            and not self.trigger_down
            and self.spec.modifiers.issubset(self.modifiers_down)
        ):
            self.trigger_down = True
            self.activated = self.controller.begin()

    def on_release(self, key):
        name = self._key_name(key)
        should_end = False
        if name == self.spec.trigger and self.trigger_down:
            self.trigger_down = False
            should_end = self.activated
            self.activated = False
        if name in self.spec.modifiers:
            self.modifiers_down.discard(name)
            if self.activated and not self.spec.modifiers.issubset(self.modifiers_down):
                should_end = True
                self.activated = False
        if should_end:
            self.controller.end()


def accessibility_status() -> Optional[bool]:
    """Return macOS Accessibility trust, or None when it cannot be queried."""
    try:
        import ApplicationServices

        return bool(ApplicationServices.AXIsProcessTrusted())
    except (ImportError, AttributeError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Global push-to-talk for the latest spoken Codex task."
    )
    parser.add_argument(
        "--hotkey",
        default=DEFAULT_HOTKEY,
        help="Shortcut such as option+space or control+shift+v.",
    )
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--lang", default="auto")
    parser.add_argument("--device", default=None, help="ffmpeg avfoundation audio index")
    parser.add_argument(
        "--session-ttl",
        type=float,
        default=DEFAULT_TTL_SECONDS,
        help="Seconds before the latest spoken Codex task expires.",
    )
    return parser


def startup_check() -> bool:
    if sys.platform != "darwin":
        say_line("Push-to-talk currently requires macOS.", "Push-to-Talk 目前只支援 macOS。")
        return False
    for command in ("ffmpeg", "codex"):
        if shutil.which(command) is None:
            say_line(f"{command} was not found in PATH.", f"PATH 裡找不到 {command}。")
            return False
    try:
        import pynput  # noqa: F401
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        say_line("Push-to-talk dependencies are missing.", "缺少 Push-to-Talk 套件。")
        print(str(exc), file=sys.stderr)
        say_line("Run ./setup.sh first.", "請先執行 ./setup.sh。")
        return False

    trusted = accessibility_status()
    if trusted is False:
        say_line(
            "Accessibility permission is off for this terminal app.",
            "這個終端機 App 尚未取得「輔助使用」權限。",
        )
        say_line(
            "Enable it in System Settings -> Privacy & Security -> Accessibility.",
            "請到「系統設定 → 隱私權與安全性 → 輔助使用」開啟。",
        )
        return False
    return True


def main(argv=None) -> int:
    os.environ.pop("PYTHONPATH", None)
    args = build_parser().parse_args(argv)
    try:
        spec = HotkeySpec.parse(args.hotkey)
    except ValueError as exc:
        print(f"Invalid hotkey / 快捷鍵無效：{exc}", file=sys.stderr)
        return 2
    if args.session_ttl <= 0:
        print("Session TTL must be positive / Session TTL 必須大於 0", file=sys.stderr)
        return 2
    if not startup_check():
        return 1

    from pynput import keyboard

    language = None if args.lang == "auto" else args.lang
    device = args.device or find_audio_device()
    transcriber = LocalWhisperTranscriber(args.whisper_model, language)
    controller = PushToTalkController(
        home=voxshell_home(),
        ttl_seconds=args.session_ttl,
        recorder=FfmpegRecorder(device),
        transcriber=transcriber,
        sender=resume_codex,
        sound=SoundPlayer(),
    )
    adapter = GlobalKeyboardAdapter(spec, controller)

    print("=" * 64)
    say_line("voxshell push-to-talk is ready.", "voxshell Push-to-Talk 已準備好。")
    print(f"Hold to talk / 按住說話：{spec.display}")
    say_line("Release to send. Press Esc while recording to cancel.", "放開即送出；錄音時按 Esc 取消。")
    print(f"Microphone device / 麥克風裝置：{device}")
    print("=" * 64, flush=True)

    try:
        with keyboard.Listener(
            on_press=adapter.on_press,
            on_release=adapter.on_release,
        ) as listener:
            listener.join()
    except KeyboardInterrupt:
        controller.cancel()
        controller.wait()
        say_line("Push-to-talk stopped.", "Push-to-Talk 已停止。")
    except Exception as exc:
        print(f"Keyboard listener failed / 快捷鍵監聽失敗：{exc}", file=sys.stderr)
        say_line(
            "Check Accessibility permission or choose another --hotkey.",
            "請檢查「輔助使用」權限，或改用其他 --hotkey。",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
