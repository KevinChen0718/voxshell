# Install voxshell with an AI assistant

This document is written for an AI assistant helping a person install voxshell. English comes first; a complete Traditional Chinese version follows.

voxshell is a macOS voice loop for coding agents. After Codex or Claude Code finishes a turn, voxshell removes code and terminal noise, then speaks a short result with the built-in `say` command. Codex users can optionally hold a global shortcut, speak the next instruction, and release to send it back to the latest spoken task.

---

## English instructions for the assisting AI

### Your goal

Help the user prove the speech pipeline works, review the exact configuration change, and install only the adapter they choose. Install the optional Push-to-Talk companion only when the user asks for voice follow-up. Do not install the separate legacy conversation demo unless the user explicitly asks for it.

### Safety rules

- Explain each command in plain language before running it.
- Never use `sudo`; the main read-aloud mode does not need it.
- Do not move or delete unrelated files.
- Always run the relevant installer with `--dry-run` first and show the user the diff.
- Do not overwrite an existing Codex notifier. The installer intentionally stops on that conflict.
- Do not edit JSON or TOML with regex or blind string replacement.
- Keep the cloned folder in place after installation because the hook stores an absolute path.
- If a command fails, read the actual error and address its cause instead of retrying blindly.

### 1. Confirm the platform

Run:

```bash
uname -s
python3 --version
```

Continue only if the first command prints `Darwin` and Python is 3.9 or newer. voxshell currently depends on macOS `say`.

### 2. Choose and clone the project location

Ask the user where they want the repository to live. After they choose, clone it and enter the folder:

```bash
git clone https://github.com/KevinChen0718/voxshell.git
cd voxshell
```

Do not assume a location or clone over an existing folder.

### 3. Prove the pipeline before installing

Preview the exact short script without speaking:

```bash
python3 hooks/voxshell-speak.py --preview \
  "Installation preview is working. The speech pipeline is ready. This third sentence will be omitted."
```

Expected output:

```text
Installation preview is working. The speech pipeline is ready.
```

Then speak the same sample:

```bash
python3 hooks/voxshell-speak.py --demo \
  "Installation preview is working. The speech pipeline is ready. This third sentence will be omitted."
```

The user should hear the first two sentences. If there is no sound, check macOS output volume and run `say "voxshell audio test"`. Do not start editing agent settings until direct `say` works.

### 4. Ask which coding agent to connect

Ask one question: “Should I connect voxshell to Codex CLI, Claude Code, or both?”

Verify the selected command exists:

```bash
command -v codex
command -v claude
```

Only the selected command needs to be present.

### 5A. Connect Codex CLI

Show the proposed change:

```bash
python3 hooks/install_codex_notify.py --dry-run
```

Explain that the installer adds one top-level `notify` argv array to `~/.codex/config.toml`. If another notifier already exists, the command exits with status 1 and does not write. Stop and follow its fan-out-wrapper guidance; never replace the existing notifier without the user's explicit decision.

After the user approves the displayed diff:

```bash
python3 hooks/install_codex_notify.py
```

The installer creates a timestamped backup before changing an existing file.

### 5B. Connect Claude Code

Show the proposed merge:

```bash
python3 hooks/install_claude_hook.py --dry-run
```

Explain that the installer parses `~/.claude/settings.json`, preserves unknown fields and other hooks, and appends one asynchronous `Stop` hook. Invalid JSON causes a safe stop without writing.

After the user approves the displayed diff:

```bash
python3 hooks/install_claude_hook.py
```

The installer creates a timestamped backup before changing an existing file.

### 6. End-to-end check

Start a fresh session of the connected coding agent and ask it:

```text
Reply with exactly three short sentences saying the voxshell test is complete.
```

The user should hear only the first two sentences after the turn completes. If not:

1. Confirm the agent was restarted after installation.
2. Run the matching installer again with `--dry-run`; an installed configuration should show no change.
3. Inspect `~/.voxshell/mute`; if it exists, explain that it intentionally mutes all hooks.
4. Retry once with `VOXSHELL_DEBUG=1` and inspect `~/.voxshell/voxshell.log`.
5. Do not expose the user's transcript or configuration contents in public logs.

### Optional settings

Only create `~/.voxshell/config.json` after asking the user about voice or rate:

```json
{
  "voice": "Samantha",
  "rate": 190,
  "max_sentences": 2,
  "max_chars": 320
}
```

Use `say -v '?'` to list voices. Do not enable `summary_cmd` by default; it calls an external command for every completed turn and may consume quota.

### Optional Codex Push-to-Talk

Only offer this after the Codex notifier works end to end. Explain before installation that it adds a long-running local companion, listens only for the configured shortcut and `Esc`, and needs macOS Microphone and Accessibility permission.

Install its dependencies:

```bash
./setup.sh
```

Explain that the first start may download the selected faster-whisper model once; transcription itself runs locally after that model is present.

Start it:

```bash
./run-ptt.sh
```

The expected interaction is: hold `⌥ Space`, confirm the terminal displays the intended project, speak, and release to send immediately. `Esc` cancels while recording. If the shortcut conflicts with another app, choose a different one, for example:

```bash
./run-ptt.sh --hotkey control+shift+v
```

Never bypass macOS permission prompts. If Codex resume fails, keep the printed transcript available to the user and do not retry automatically.

### Uninstall

Remove only the voxshell entry with the matching installer:

```bash
python3 hooks/install_codex_notify.py --uninstall
python3 hooks/install_claude_hook.py --uninstall
```

Run only the command for the adapter the user wants removed. These commands preserve other settings.

### Optional microphone conversation demo

This is not required for the main product. Only if the user explicitly wants the older mic → local Whisper → AI CLI → speech loop, explain that it installs `ffmpeg` and Python packages, then run:

```bash
./setup.sh
./run.sh
```

The first microphone use may trigger a macOS permission prompt. Never attempt to bypass the prompt.

---

## 給協助安裝的 AI：繁體中文完整指引

### 你的目標

先讓使用者親耳確認朗讀管線能動，再讓他看清楚設定會改什麼，最後只安裝他選擇的 Codex CLI／Claude Code 接頭。只有使用者想用語音接著下指令時，才安裝選用的 Push-to-Talk companion；除非使用者另外要求，也不要啟動舊版麥克風對話 demo。

### 安全規則

- 跑指令前先用白話說明它會做什麼。
- 不使用 `sudo`；主要朗讀模式不需要它。
- 不移動或刪除其他檔案。
- 安裝前一定先跑 `--dry-run`，把差異給使用者看。
- Codex 若已有其他 notifier，不能覆蓋；安裝器會刻意停止。
- 不用 regex 或盲目字串替換修改 JSON／TOML。
- 安裝後不要移動 clone 下來的資料夾，因為 hook 記的是絕對路徑。
- 指令失敗時讀真正錯誤、處理原因，不要盲目重跑。

### 1. 確認平台

```bash
uname -s
python3 --version
```

第一行必須是 `Darwin`，Python 必須是 3.9 以上。voxshell 目前依賴 macOS 內建的 `say`。

### 2. 選擇位置並 clone

先問使用者想把專案放哪裡，再執行：

```bash
git clone https://github.com/KevinChen0718/voxshell.git
cd voxshell
```

不要自行猜位置，也不要蓋到既有資料夾。

### 3. 安裝前先證明朗讀管線能動

先只看清洗後會念的文字：

```bash
python3 hooks/voxshell-speak.py --preview \
  "安裝預覽成功。朗讀管線已經準備好。第三句應該被省略。"
```

預期輸出：

```text
安裝預覽成功。 朗讀管線已經準備好。
```

再真正朗讀：

```bash
python3 hooks/voxshell-speak.py --demo \
  "安裝預覽成功。朗讀管線已經準備好。第三句應該被省略。"
```

使用者應該聽到前兩句。沒聲音時，先檢查 Mac 音量並執行 `say "voxshell 聲音測試"`；在直接 `say` 能動以前，不要開始改 agent 設定。

### 4. 問要接哪個 coding agent

只問一題：「要把 voxshell 接到 Codex CLI、Claude Code，還是兩個都接？」

檢查所選工具是否存在：

```bash
command -v codex
command -v claude
```

只需要使用者選的工具存在。

### 5A. 接上 Codex CLI

先顯示預計修改：

```bash
python3 hooks/install_codex_notify.py --dry-run
```

跟使用者說：安裝器會在 `~/.codex/config.toml` 加上一組頂層 `notify` 指令。若已經有其他 notifier，程式會回傳狀態 1 並且完全不寫入；這時照畫面上的 fan-out wrapper 指引處理，沒有得到明確同意前不能取代原設定。

使用者確認差異後才安裝：

```bash
python3 hooks/install_codex_notify.py
```

修改既有設定前，安裝器會自動建立時間戳備份。

### 5B. 接上 Claude Code

先顯示合併差異：

```bash
python3 hooks/install_claude_hook.py --dry-run
```

跟使用者說：安裝器會解析 `~/.claude/settings.json`、保留不認識的欄位與其他 hooks，只追加一個非同步 `Stop` hook。JSON 壞掉時會安全停止、不寫入。

使用者確認後才安裝：

```bash
python3 hooks/install_claude_hook.py
```

修改既有設定前，安裝器會自動建立時間戳備份。

### 6. 真實端到端測試

重新開一個已接上的 coding agent session，請它：

```text
請只用三個短句回覆，內容說 voxshell 測試已完成。
```

一輪結束後，使用者應只聽到前兩句。若沒有：

1. 確認安裝後有重新啟動 agent。
2. 對同一安裝器再跑一次 `--dry-run`；已安裝時應沒有新差異。
3. 檢查 `~/.voxshell/mute` 是否存在；存在代表使用者刻意全域靜音。
4. 只重試一次並加上 `VOXSHELL_DEBUG=1`，查看 `~/.voxshell/voxshell.log`。
5. 不把使用者逐字稿或設定內容貼到公開 log。

### 選配設定

只有使用者想改聲音或語速時，才建立 `~/.voxshell/config.json`：

```json
{
  "voice": "Meijia",
  "rate": 190,
  "max_sentences": 2,
  "max_chars": 240
}
```

用 `say -v '?'` 查看聲音。不要預設啟用 `summary_cmd`；它會在每輪結束後呼叫外部指令，可能消耗額度。

### 選用的 Codex Push-to-Talk

只在 Codex notifier 的端到端測試成功後提供。事前說清楚：它會啟動一個留在本機的常駐 companion，只辨識指定快捷鍵與 `Esc`，並需要 macOS 麥克風與「輔助使用」權限。

安裝套件：

```bash
./setup.sh
```

先說明第一次啟動可能會下載一次所選的 faster-whisper 模型；模型到位後，轉錄會在本機完成。

啟動：

```bash
./run-ptt.sh
```

請使用者按住 `⌥ Space`，確認終端機顯示正確專案名稱，說出指令後放開即送出；錄音時按 `Esc` 取消。若快捷鍵與其他 App 衝突，可改用例如：

```bash
./run-ptt.sh --hotkey control+shift+v
```

不可繞過 macOS 權限提示。若 Codex resume 失敗，保留畫面上印出的逐字稿給使用者，不可自動重試。

### 解除安裝

用相同安裝器只移除 voxshell 自己的項目：

```bash
python3 hooks/install_codex_notify.py --uninstall
python3 hooks/install_claude_hook.py --uninstall
```

只執行使用者要移除的那一種；其他設定都會保留。

### 選配的麥克風對話 demo

這不是主產品的必要項目。只有使用者明確想玩舊版「麥克風 → 本機 Whisper → AI CLI → 朗讀」時，先說明它會安裝 `ffmpeg` 與 Python 套件，再執行：

```bash
./setup.sh
./run.sh
```

第一次使用麥克風時，macOS 可能跳出權限視窗；不可嘗試繞過。
