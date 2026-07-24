# voxshell reusable competition submission kit

This file is the source package for Devpost-style hackathons and developer-tool competitions. The product copy is ready to paste. Before each event, replace the small event-specific block below and verify every claim against the current repository.

## Replace these fields for each event

| Field | Value to add at submission time |
|---|---|
| `EVENT_NAME` | Official competition name |
| `EVENT_TRACK` | Usually Developer Tools; use the event's exact label |
| `REQUIRED_TECH` | Required model, API, SDK, or platform and exactly where voxshell used it |
| `BUILD_SESSION_ID` | Primary eligible build-session or feedback ID |
| `ELIGIBLE_COMMIT_RANGE` | Commits created within the event window |
| `VIDEO_URL` | Public demo video URL |
| `REPOSITORY_URL` | Public repository URL |

Do not submit old values from a previous event. Recheck eligibility, dates, existing-project rules, repository visibility, video constraints, required technologies, and whether AI-assisted copy must be rewritten in the entrant's own voice.

## Submission basics

**Project name**

voxshell

**Tagline**

Hear what your coding agent finished, then hold one key to tell it what to do next.

**Recommended track**

Developer Tools

**One-sentence description**

voxshell speaks the useful part of a coding-agent result, then lets a Codex user hold a global shortcut, speak the next instruction, and release to send it back to that task.

**Technologies**

Python 3.9+, macOS `say`, Codex CLI `notify` and `exec resume`, Claude Code `Stop` hooks, faster-whisper, pynput, ffmpeg, JSON, TOML, Bash

## Paste-ready long description

### Inspiration

Coding agents can work for several minutes while I move to another window or task. The problem is that their result waits silently in the terminal. Existing text-to-speech tools can read a screen, but coding-agent replies contain Markdown, code blocks, diffs, file paths, tables, and test logs that are painful to hear. Even after hearing an update, giving the next instruction normally means switching back and typing.

I wanted the agent I was already using—with its real project context—to have a small, selective voice and a deliberate voice return path. It should tell me the outcome, not narrate the terminal; I should be able to answer without opening an unrelated dictation app.

### What it does

voxshell connects to Codex CLI's completion notification or Claude Code's `Stop` hook. When a turn finishes, it extracts the last assistant message, rejects malformed or oversized input, removes code and other visual noise, and keeps a short natural-language result. macOS then speaks that result with its built-in `say` command.

The default read-aloud path is local and deterministic: no extra model call, no daemon, no separate account, and no microphone recording. A newer result interrupts only the speaker process started by voxshell, so old updates do not queue up.

Codex users can optionally run a Push-to-Talk companion. The completion adapter stores only the latest task's session id, project directory, project name, and timestamp. Within 15 minutes, the user holds `⌥ Space`; voxshell locks that target, records only while the keys are held, transcribes locally with faster-whisper, and sends the text through stdin to `codex exec resume`. Releasing is the explicit send action, and `Esc` cancels before send. The selected Whisper model may be downloaded once on first start; transcription is local after that.

Users can run `--preview` to inspect the exact cleaned text without sound or `--demo` to exercise the production speech pipeline before changing any agent configuration. Safe installers support dry-run diffs, backups, idempotent reruns, atomic writes, conflict refusal, and targeted uninstall.

### How I built it

The read-aloud core is one Python standard-library pipeline shared by three inputs: a Claude JSON payload on stdin, a Codex completion payload as the final command argument, and explicit demo text. Normalizing these inputs before cleaning prevents adapter behavior from drifting.

The cleaner removes fenced and inline code, URLs, long paths, Markdown decoration, tables, and list-heavy noise. It skips replies that still look mostly like code, selects the first two useful sentences, and applies a language-aware character limit. Speech runs in the background so the coding agent is never blocked.

The Claude installer parses and merges JSON while preserving unknown fields and other hooks. The Codex installer uses a conservative line edit because Python 3.9 has no standard TOML writer; if it finds another notifier, it stops instead of guessing how to combine commands.

The Push-to-Talk path is deliberately separate. A private `0600` JSON file is written with temp-file plus replace, the target is copied at key-down so a later notification cannot redirect the recording, and every success or failure path deletes the temporary WAV. Resume uses a fixed argv array and stdin, never a shell-built command or approval-bypass flag.

For `EVENT_NAME`, add one short paragraph here explaining how `REQUIRED_TECH` was used in the eligible `ELIGIBLE_COMMIT_RANGE`. Describe a concrete design, implementation, or verification contribution and do not imply that a build-time model is a runtime dependency.

### Challenges

The hardest part was making spoken output useful rather than merely audible. Coding replies are designed for eyes, so aggressive removal is safer than trying to narrate every detail. Another challenge was integrating with configuration files people already trust. A convenient installer is not acceptable if it can erase unrelated settings or notifications.

The two agent integrations also deliver completion data differently. Sharing one downstream pipeline while keeping small, explicit adapters reduced both code and test surface.

The most important technical uncertainty was whether a real Codex `notify` thread id could safely resume while the original interactive client remained open. I tested that route before building the UI. External turns kept one session id, preserved the persisted history, triggered subsequent notifications, and did not lock the original TUI. The experiment also exposed a limitation worth documenting: an already-open TUI does not immediately refresh its in-memory transcript after an external turn.

### Accomplishments

- A working Codex CLI and Claude Code read-aloud layer with no daemon.
- A hold-to-talk Codex follow-up loop that routes back to the latest spoken task.
- Local speech recognition with no always-on microphone or separate transcript service.
- Local, model-free cleaning and text-to-speech by default.
- Judge-friendly preview and demo paths that require no configuration changes.
- Fail-open hooks that cannot block the coding agent on parse or speech failure.
- Conservative installers with dry-run, backup, idempotency, atomic writes, and uninstall.
- Automated coverage for malformed input, code-heavy replies, mute precedence, fallback parsing, notifier conflicts, session expiry, target locking, cancellation, stdin-only resume, audio cleanup, and end-to-end demo behavior.

### What I learned

Lifecycle data is better than screen scraping. Structured completion and session fields are both more reliable and easier to secure than watching terminal output. I also learned that accessibility features need editorial judgment: the valuable unit is not “all available text,” but the smallest spoken update that lets someone decide what the agent should do next.

### What's next

The next steps are cross-platform speech backends, a stable Gemini CLI adapter, a small native menu-bar UI, first-party live-client injection if Codex exposes it, and better local detection of summary and verification sections without requiring a model call.

## Testing instructions for judges

**Platform:** macOS with Python 3.9 or newer. The zero-install test does not require Codex or Claude Code.

```bash
git clone REPOSITORY_URL
cd voxshell

python3 hooks/voxshell-speak.py --preview \
  "The refactor is complete. All tests pass. The full diff remains in the terminal."

python3 hooks/voxshell-speak.py --demo \
  "The refactor is complete. All tests pass. The full diff remains in the terminal."

PYTHONDONTWRITEBYTECODE=1 bash tests/test_speak.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests/test_ptt.py
```

Expected preview:

```text
The refactor is complete. All tests pass.
```

The demo speaks the same two sentences. The test suites use isolated temporary configuration and fakes for speech, recording, transcription, and Codex resume; they do not edit the judge's real Codex or Claude settings.

For full integration, follow the dry-run-first instructions in the repository README. The installers contain absolute paths, so do not move the cloned folder after installation. Push-to-Talk additionally needs `./setup.sh`, a working Codex notification, and user-granted Microphone and Accessibility permissions.

## Evidence package for an existing project

If an event allows existing projects only when they are meaningfully extended during the competition, fill this table before submitting:

| Evidence | What to provide |
|---|---|
| Before state | Last commit or dated archive before the event window |
| Eligible extension | User-visible capability added during the event |
| Commit range | `ELIGIBLE_COMMIT_RANGE` with timestamps inside the window |
| Build session | `BUILD_SESSION_ID` and its model/tool metadata |
| Human decisions | Specific scope, safety, and product decisions made by the entrant |
| Verification | Test output and a video showing the eligible extension |

Keep prior work and event work separate. Never imply that pre-event functionality was created during the event.

## One-take demo video script (about 2 minutes 40 seconds)

Record at 1080p with terminal text enlarged. Do not use copyrighted music. If the event requires a particular platform or model, show its name and eligible contribution on screen while reading the event-specific sentence below.

| Time | Screen | Voiceover |
|---|---|---|
| 0:00–0:15 | Title: `voxshell — hear the result, speak the next step` | “Coding agents can work while I move to another task, but their result waits silently in the terminal. voxshell lets me hear the useful result and answer without switching back to type.” |
| 0:15–0:35 | README architecture diagram | “It receives the final reply from Codex or Claude Code, removes code blocks, paths, tables, and other visual noise, then speaks only a short useful result with macOS text-to-speech.” |
| 0:35–0:55 | Run `--preview` with a three-sentence sample containing a code block | “Preview uses the real cleaning pipeline without installing anything. The code disappears, and only the first two useful sentences remain.” |
| 0:55–1:15 | Run `--demo`; let the spoken result be audible | “Demo sends that same result through the production speech path. It makes no model call and records no audio.” |
| 1:15–1:35 | Trigger a real Codex turn, move focus to another App, and hear the result | “The real workflow starts when Codex finishes. voxshell speaks the outcome and remembers only the routing data for this task.” |
| 1:35–1:58 | Keep the other App focused; hold `⌥ Space`, speak a short follow-up, and release | “I hold one shortcut, confirm the project name, and speak the next step. Releasing sends the local transcript directly back to the same Codex task.” |
| 1:58–2:12 | Let the resumed Codex task finish and hear the second spoken result | “The task continues with its existing context, then the same completion hook closes the loop by speaking again.” |
| 2:12–2:27 | Show privacy state file and an `Esc` cancellation | “The microphone is open only while I hold the shortcut. Audio is temporary, the routing state contains no reply text, and Escape cancels before send.” |
| 2:27–2:42 | Run both test suites and show their passing summaries | “Tests cover the speech cleaner, safe installers, session expiry, locked routing, cancellation, stdin-only resume, failures, and audio cleanup.” |
| 2:42–2:55 | Event-specific slide and end card | “For `EVENT_NAME`, I used `REQUIRED_TECH` for the eligible extension documented here. voxshell lets me hear the result and speak the next step.” |

If an event has a stricter limit, remove the installer section before speeding up the narration. Clarity is better than fast speech.

## Asset checklist

- Public repository with a relevant license
- README tested from a fresh clone
- Public demo video within the event's duration limit
- Repository URL: `REPOSITORY_URL`
- Video URL: `VIDEO_URL`
- Primary eligible session ID: `BUILD_SESSION_ID`
- Event-specific required-tech paragraph completed
- Commit timestamps checked against the official event timezone
- At least one screenshot showing preview and one showing real agent completion
- No secrets, private transcripts, personal paths, third-party trademarks, or unlicensed music in public assets
- Submission text rewritten where the event requires the entrant's own unaided wording
- Legal terms and final submit action reviewed by the entrant

## Final claim audit

Immediately before submission, search the repository and submission text for:

```text
EVENT_NAME
EVENT_TRACK
REQUIRED_TECH
BUILD_SESSION_ID
ELIGIBLE_COMMIT_RANGE
VIDEO_URL
REPOSITORY_URL
```

The final public submission must contain none of these placeholders. Also rerun the full tests and verify the public repository from a logged-out browser.
