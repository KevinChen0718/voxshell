#!/usr/bin/env python3
"""Deterministic tests for push-to-talk routing and failure behavior."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

from ptt import (  # noqa: E402
    GlobalKeyboardAdapter,
    HotkeySpec,
    PushToTalkController,
    ResumeResult,
    resume_codex,
)
from voxshell_state import (  # noqa: E402
    STATE_FILENAME,
    atomic_write_state,
    load_active_session,
    state_from_codex_payload,
)


def make_state(session_id: str, cwd: str, notified_at: float) -> dict:
    return {
        "version": 1,
        "session_id": session_id,
        "cwd": cwd,
        "project_name": Path(cwd).name,
        "notified_at": notified_at,
    }


class FakeSound:
    def __init__(self):
        self.events = []

    def play(self, kind: str) -> None:
        self.events.append(kind)


class FakeRecorder:
    def __init__(self, directory: Path, *, fail_stop: bool = False):
        self.directory = directory
        self.fail_stop = fail_stop
        self.started = []
        self.stopped = []

    def start(self):
        handle = tempfile.NamedTemporaryFile(dir=self.directory, delete=False)
        handle.write(b"audio")
        handle.close()
        recording = SimpleNamespace(path=Path(handle.name))
        self.started.append(recording)
        return recording

    def stop(self, recording) -> None:
        self.stopped.append(recording)
        if self.fail_stop:
            raise RuntimeError("stop failed")


class FakeTranscriber:
    def __init__(self, text: str = "請執行下一步", error: Exception | None = None):
        self.text = text
        self.error = error
        self.paths = []

    def transcribe(self, path: Path) -> str:
        self.paths.append(path)
        if self.error:
            raise self.error
        return self.text


class ImmediateWorker:
    def __init__(self, callback):
        callback()

    def join(self):
        return None


class MutableClock:
    def __init__(self, value: float):
        self.value = value

    def __call__(self) -> float:
        return self.value


class StateTests(unittest.TestCase):
    def test_payload_is_minimized_and_normalized(self):
        state = state_from_codex_payload(
            {
                "type": "agent-turn-complete",
                "thread-id": " session-123 ",
                "cwd": "/tmp/sample-project",
                "last-assistant-message": "must not be stored",
            },
            notified_at=10,
        )
        self.assertEqual(
            state,
            {
                "version": 1,
                "session_id": "session-123",
                "cwd": "/tmp/sample-project",
                "project_name": "sample-project",
                "notified_at": 10.0,
            },
        )
        self.assertNotIn("last-assistant-message", state)

    def test_payload_missing_route_is_rejected(self):
        self.assertIsNone(
            state_from_codex_payload(
                {
                    "type": "agent-turn-complete",
                    "last-assistant-message": "done",
                },
                notified_at=10,
            )
        )

    def test_payload_rejects_option_like_session_and_relative_cwd(self):
        self.assertIsNone(
            state_from_codex_payload(
                {
                    "type": "agent-turn-complete",
                    "thread-id": "--help",
                    "cwd": "/tmp",
                },
                notified_at=10,
            )
        )
        self.assertIsNone(
            state_from_codex_payload(
                {
                    "type": "agent-turn-complete",
                    "thread-id": "session-123",
                    "cwd": "relative/project",
                },
                notified_at=10,
            )
        )

    def test_atomic_state_load_permissions_expiry_and_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            cwd = Path(temporary) / "project"
            cwd.mkdir()
            path = atomic_write_state(home, make_state("s1", str(cwd), 100))

            loaded = load_active_session(home, now=200, ttl_seconds=900)
            self.assertEqual(loaded["session_id"], "s1")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(home.glob(f".{STATE_FILENAME}.*.tmp")), [])

            self.assertIsNone(load_active_session(home, now=1001, ttl_seconds=900))
            path.write_text("{bad json", encoding="utf-8")
            self.assertIsNone(load_active_session(home, now=200, ttl_seconds=900))

    def test_missing_working_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            atomic_write_state(home, make_state("s1", "/definitely/missing/voxshell", 100))
            self.assertIsNone(load_active_session(home, now=200, ttl_seconds=900))


class PushToTalkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.project_one = self.root / "project-one"
        self.project_two = self.root / "project-two"
        self.project_one.mkdir()
        self.project_two.mkdir()
        self.clock = MutableClock(100)
        self.sound = FakeSound()
        self.sent = []

    def tearDown(self):
        self.temporary.cleanup()

    def write_target(self, session_id: str, project: Path):
        atomic_write_state(
            self.home,
            make_state(session_id, str(project), self.clock.value),
        )

    def controller(self, *, transcript="請執行下一步", fail_stop=False, sender=None):
        recorder = FakeRecorder(self.root, fail_stop=fail_stop)
        transcriber = FakeTranscriber(text=transcript)

        def default_sender(target, text):
            self.sent.append((dict(target), text))
            return ResumeResult(True)

        controller = PushToTalkController(
            home=self.home,
            ttl_seconds=900,
            recorder=recorder,
            transcriber=transcriber,
            sender=sender or default_sender,
            sound=self.sound,
            clock=self.clock,
            worker_factory=ImmediateWorker,
        )
        return controller, recorder, transcriber

    def test_key_down_locks_target_despite_later_notify(self):
        self.write_target("session-one", self.project_one)
        controller, recorder, _ = self.controller()
        self.assertTrue(controller.begin())

        self.clock.value = 110
        self.write_target("session-two", self.project_two)
        self.assertTrue(controller.end())

        self.assertEqual(self.sent[0][0]["session_id"], "session-one")
        self.assertEqual(self.sent[0][1], "請執行下一步")
        self.assertFalse(recorder.started[0].path.exists())

    def test_cancel_stops_deletes_and_never_sends(self):
        self.write_target("session-one", self.project_one)
        controller, recorder, _ = self.controller()
        self.assertTrue(controller.begin())
        path = recorder.started[0].path
        self.assertTrue(controller.cancel())
        self.assertFalse(path.exists())
        self.assertEqual(self.sent, [])
        self.assertIn("cancel", self.sound.events)

    def test_empty_transcript_does_not_send_and_deletes_audio(self):
        self.write_target("session-one", self.project_one)
        controller, recorder, _ = self.controller(transcript=" \n ")
        controller.begin()
        path = recorder.started[0].path
        controller.end()
        self.assertEqual(self.sent, [])
        self.assertFalse(path.exists())

    def test_expired_locked_target_preserves_transcript_without_send(self):
        self.write_target("session-one", self.project_one)
        controller, recorder, _ = self.controller(transcript="還要做這件事")
        controller.begin()
        path = recorder.started[0].path
        self.clock.value = 1001
        controller.end()
        self.assertEqual(self.sent, [])
        self.assertEqual(controller.last_failed_transcript, "還要做這件事")
        self.assertFalse(path.exists())

    def test_resume_failure_preserves_transcript_and_deletes_audio(self):
        self.write_target("session-one", self.project_one)

        def failed_sender(target, text):
            return ResumeResult(False, "resume failed")

        controller, recorder, _ = self.controller(
            transcript="保留我",
            sender=failed_sender,
        )
        controller.begin()
        path = recorder.started[0].path
        controller.end()
        self.assertEqual(controller.last_failed_transcript, "保留我")
        self.assertFalse(path.exists())

    def test_transcription_failure_does_not_send_and_deletes_audio(self):
        self.write_target("session-one", self.project_one)
        recorder = FakeRecorder(self.root)
        transcriber = FakeTranscriber(error=RuntimeError("whisper failed"))
        controller = PushToTalkController(
            home=self.home,
            ttl_seconds=900,
            recorder=recorder,
            transcriber=transcriber,
            sender=lambda target, text: self.fail("must not send"),
            sound=self.sound,
            clock=self.clock,
            worker_factory=ImmediateWorker,
        )
        controller.begin()
        path = recorder.started[0].path
        controller.end()
        self.assertFalse(path.exists())

    def test_stop_failure_deletes_audio_and_clears_busy(self):
        self.write_target("session-one", self.project_one)
        controller, recorder, _ = self.controller(fail_stop=True)
        controller.begin()
        path = recorder.started[0].path
        self.assertFalse(controller.end())
        self.assertFalse(path.exists())
        self.assertFalse(controller.busy)

    def test_no_recent_target_does_not_start_microphone(self):
        controller, recorder, _ = self.controller()
        self.assertFalse(controller.begin())
        self.assertEqual(recorder.started, [])


class ResumeAdapterTests(unittest.TestCase):
    def test_transcript_is_stdin_not_argv(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="done", stderr="")

        target = {
            "session_id": "session-123",
            "cwd": "/tmp",
            "project_name": "tmp",
            "notified_at": 1,
            "version": 1,
        }
        transcript = "包含 空白 與 $() 的指令"
        result = resume_codex(
            target,
            transcript,
            codex_command="/usr/local/bin/codex",
            runner=runner,
        )
        self.assertTrue(result.ok)
        command, kwargs = calls[0]
        self.assertEqual(
            command,
            [
                "/usr/local/bin/codex",
                "exec",
                "resume",
                "session-123",
                "-",
            ],
        )
        self.assertNotIn(transcript, command)
        self.assertEqual(kwargs["input"], transcript)
        self.assertEqual(kwargs["cwd"], "/tmp")
        self.assertNotIn("-a", command)
        self.assertNotIn("-s", command)

    def test_nonzero_resume_returns_error(self):
        def runner(command, **kwargs):
            return SimpleNamespace(returncode=7, stdout="", stderr="denied")

        result = resume_codex(
            {
                "session_id": "s1",
                "cwd": "/tmp",
                "project_name": "tmp",
                "notified_at": 1,
                "version": 1,
            },
            "hello",
            runner=runner,
        )
        self.assertEqual(result, ResumeResult(False, "denied"))

    def test_invalid_target_never_invokes_runner(self):
        def runner(command, **kwargs):
            self.fail("runner must not be called")

        result = resume_codex(
            {
                "session_id": "--help",
                "cwd": "/tmp",
                "project_name": "tmp",
                "notified_at": 1,
                "version": 1,
            },
            "hello",
            runner=runner,
        )
        self.assertEqual(result, ResumeResult(False, "invalid Codex target"))


class KeyboardAdapterTests(unittest.TestCase):
    def test_option_space_starts_releases_and_escape_cancels(self):
        events = []

        class Controller:
            def begin(self):
                events.append("begin")
                return True

            def end(self):
                events.append("end")
                return True

            def cancel(self):
                events.append("cancel")
                return True

        adapter = GlobalKeyboardAdapter(HotkeySpec.parse("option+space"), Controller())
        adapter.on_press(SimpleNamespace(name="alt_l"))
        adapter.on_press(SimpleNamespace(name="space"))
        adapter.on_release(SimpleNamespace(name="space"))
        adapter.on_press(SimpleNamespace(name="space"))
        adapter.on_press(SimpleNamespace(name="esc"))
        adapter.on_release(SimpleNamespace(name="space"))
        self.assertEqual(events, ["begin", "end", "begin", "cancel"])

    def test_hotkey_parser_accepts_custom_combo(self):
        spec = HotkeySpec.parse("control+shift+v")
        self.assertEqual(spec.modifiers, frozenset({"control", "shift"}))
        self.assertEqual(spec.trigger, "v")
        self.assertEqual(spec.display, "⌃⇧ V")


if __name__ == "__main__":
    unittest.main()
