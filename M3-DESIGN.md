# voxshell M3 開發設計說明

> 這是 read-aloud M3 的歷史設計紀錄。當時刻意不做 Push-to-Talk；後來新增的選用 Codex companion 以獨立設計與風險邊界實作，請以 [`docs/superpowers/specs/2026-07-25-voxshell-push-to-talk-design.md`](docs/superpowers/specs/2026-07-25-voxshell-push-to-talk-design.md) 為準。主要朗讀模式仍不需要麥克風或常駐 daemon。

voxshell M2 是一個獨立的本機語音閒聊迴圈：`ffmpeg` 錄音、`faster-whisper` 轉文字、每輪啟動全新的 AI CLI、再用 macOS `say` 念出回覆。M3 的產品定位改成「給 CLI AI 裝上聲音」：不再另外開一個沒有專案脈絡的聊天迴圈，而是讓使用者正在工作的 Claude Code / Codex CLI / Gemini CLI session 在回覆結束後自動出聲。M2 管線保留為 demo mode，主產品價值改成「嘴巴」：透過各 CLI 的 lifecycle hook / notify 機制讀取剛完成的 assistant 回覆，清洗成適合朗讀的短稿，背景播放。

## 1. 嘴巴架構

### 方案比較

方案 A：Claude Code `Stop` hook 讀 `transcript_path`，從 JSONL 反向找最後一則 assistant 訊息。這符合原始構想，但風險較高。Claude Code 官方文件明確說 `Stop` hook 的 `transcript_path` 在 Stop 當下不保證已包含最後訊息，對「剛回完就念」這個需求不是最穩主路徑。

方案 B：Claude Code `Stop` hook 直接讀 stdin JSON 的 `last_assistant_message`，只有在欄位不存在或空白時才 fallback 到 `transcript_path`。這是 v1 推薦方案。Claude Code 官方文件說 `Stop` 會在主 agent 回覆完成時觸發，且 `last_assistant_message` 就是最終回覆文字；讀稿、通知這類 hook 應優先用這個欄位。

方案 C：改用 `MessageDisplay` 邊串流邊念。這會更接近即時語音，但 v1 不推薦，因為要處理 partial text、改稿、工具輸出和中斷，容易念錯或重複念。

### 推薦

v1 使用方案 B：Claude Code `Stop` command hook -> 讀 stdin JSON -> 取 `last_assistant_message` -> 清洗 -> 產生短稿 -> 背景呼叫 `say`。`transcript_path` 僅作 fallback，不當作主資料來源。

### 理由與穩健原則

hook 腳本要 fail open：任何 JSON parse 失敗、欄位缺失、transcript 讀不到、清洗後沒有可念文字，都安靜 `exit 0`，不可阻擋 Claude Code。stdout 預設不要輸出，stderr 只在 debug 模式才寫到 voxshell log，避免 Claude Code 把 hook 輸出當成控制訊號或錯誤。

transcript fallback 要保守：不要假設 JSONL schema 固定。做法是從檔尾反向掃描最近 N 行，逐行 JSON parse，找可能代表 assistant 的 record；內容可能是純字串、`message.content`、或 content array 裡的 text block。找不到就放棄，不報錯。

清洗要偏向「少念」：移除 fenced code block、diff block、表格、長清單、Markdown 標記、URL、過長路徑、檔案行號雜訊；保留自然語句。清洗後若 code-like 比例太高，直接不念。

防卡主程式：Claude Code 支援 command hook 的 `async: true` 和 `timeout`。v1 應把 read-aloud hook 設成 async；腳本本身也要快速返回，把真正的 `say` 交給背景 speaker process。timeout 建議設 5 到 10 秒給 hook 啟動邏輯，不把整段朗讀時間算進阻塞路徑。若使用者 Claude Code 版本太舊、不支援 async，安裝器應提示版本不符或改用腳本自我 daemonize，但這個 fallback 標為次要路徑。

連續回覆搶話：v1 推薦「新回覆打斷舊回覆」。理由是 coding agent 的最新回覆通常取代前一段狀態，排隊朗讀會讓使用者聽到過期資訊。實作原則是只 kill voxshell 自己啟動的上一個 `say` PID，不使用全域 `killall say`。用 PID file 記錄上一個 speaker process；新回覆來時先確認 PID 還活著，再終止它，然後啟動新朗讀。

## 2. 跨 AI 支援

### Claude Code

方案：使用 `~/.claude/settings.json` 的 `hooks.Stop` command hook。Claude Code 官方文件確認：command hook 透過 stdin 收 JSON；`Stop` 在主 agent 回覆完成時觸發；`Stop` input 包含 `last_assistant_message`、`transcript_path`、`cwd`、`permission_mode` 等欄位；command hook 支援 `async` 與 `timeout`。

推薦：M3 Phase 1 只承諾 Claude Code。它的 hook 文件最完整，而且 `last_assistant_message` 直接命中 voxshell 嘴巴需求。

限制：hook 以使用者本機權限執行，安裝器必須明確告知；舊版 Claude Code 的 async / 欄位支援可能不同；企業 managed policy 可能禁止使用者 hooks。

### Codex CLI

方案 A：使用 `~/.codex/config.toml` 的 top-level `notify = [...]`。查到 Codex `ConfigToml` 有 `notify: Option<Vec<String>>`；本機安裝版 `codex-cli 0.144.1` 的 binary 與 OpenAI Codex 原始碼都有 `legacy_notify`，會把一個 JSON payload 作為最後一個 argv 傳給外部命令，payload type 是 `agent-turn-complete`，包含 `thread-id`、`turn-id`、`cwd`、`input-messages`、`last-assistant-message`。這很適合 read-aloud：外部命令讀 argv 最後一個 JSON，取 `last-assistant-message` 後朗讀。

概念接法：

```toml
notify = ["/absolute/path/to/voxshell-codex-say"]
```

`voxshell-codex-say` 的輸入不是 stdin，而是最後一個 argv JSON。它應該安靜失敗、背景播放、只處理 `type = "agent-turn-complete"` 且有 `last-assistant-message` 的 payload。

方案 B：使用 Codex lifecycle hooks。OpenAI Codex 原始碼顯示 `config.toml` 有 `[hooks]` 設定，支援 `Stop`、`PreToolUse`、`PostToolUse`、`SessionStart` 等事件；`Stop` command input 包含 `last_assistant_message` 與 `transcript_path`。概念接法如下：

```toml
[hooks]
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "/absolute/path/to/voxshell-codex-say-hook"
timeout = 5
```

限制：Codex 原始碼顯示 command hooks 目前會略過 `async = true`，也就是 async hooks 尚未支援；hook 可能需要 trust review；公開文件對這套 hooks 的穩定性與一般使用者安裝流程仍不如 Claude Code 清楚。

推薦：Codex v1.5 先走 `notify`，不是 lifecycle `Stop` hook。理由是 `notify` 天然是「回合完成通知」，payload 已有 `last-assistant-message`，且 legacy implementation 是 spawn 外部命令、不等它結束，比 hook 更接近嘴巴需求。未確認：`notify` 在公開 docs 是否仍是推薦入口，以及未來是否會被 lifecycle hooks 取代；名稱 `legacy_notify` 顯示它可能是相容層，正式支援前要用當前 Codex 版本實測。

### Gemini CLI

目前只在 Gemini CLI 官方設定文件查到 `settings.json`、MCP、custom tool discovery / tool call command、telemetry、sandbox 等設定，沒有查到等價的「每回合結束時觸發外部程式」hook / notify。未確認，需查證：Gemini CLI 是否有 undocumented lifecycle hook、extension event、或 telemetry subscriber 可用於 read-aloud。

推薦：M3 不把 Gemini CLI 放進 v1 承諾；README 可以列為 planned / unconfirmed support。若後續找不到正式 hook，Gemini 支援只能退而求其次走 wrapper / pty transcript 監聽，這會比 Claude / Codex 脆弱，不適合第一版公開主打。

## 3. 念稿策略

### 方案比較

方案 A：整篇念。最完整，但 coding agent 回覆常包含 diff、測試輸出、路徑、清單，使用者體驗很差，v1 不採用。

方案 B：只念最後一段。簡單，但很多 agent 最後一段常是「測試沒跑」或下一步，不一定代表主結論。

方案 C：偵測摘要段。若看到 `Summary`、`做了什麼`、`變更`、`Tests`、`驗證` 等 heading，就抽取摘要與驗證句。效果可能最好，但規則會逐漸複雜，且中英文格式差異大。

方案 D：清洗後只念前 N 句並設硬上限。最簡單、可預測，符合「先讓產品能用」。

### 推薦

v1 採方案 D：清洗後念前 2 句，並設定長度上限。建議中文上限約 180 到 240 字，英文約 350 到 500 characters；超過就截斷在句尾或逗號附近，不補「以下省略」這類干擾語。

### 理由

CLI coding agent 的 final answer 通常先給結論，再補細節；念前 2 句最容易聽到真正狀態。這個策略不需要額外模型、不依賴固定 heading，也不會把 300 行 diff 念完。Phase 2 之後再加入「摘要段優先」：若偵測到短的 Summary / Tests 區塊，就優先念摘要與驗證狀態；否則回退前 2 句。

## 4. 開關與安裝體驗

### 方案比較

mute/unmute 可用環境變數、marker file、或設定檔。環境變數適合單次 session，但 hook process 未必繼承使用者當下想改的 shell env。設定檔可擴充，但 v1 需要 parser 與 schema。marker file 最簡單：存在就靜音，不存在就朗讀。

Claude Code hook 安裝可手動請使用者貼 JSON，也可一鍵修改 `~/.claude/settings.json`。手貼最安全但體驗差；一鍵修改體驗好，但最大風險是砸壞既有 settings。

### 推薦

v1 mute/unmute 使用 marker file：`~/.voxshell/mute` 存在代表靜音。未來若有 `~/.voxshell/config.json`，也保留 marker file 作為最高優先級的 emergency mute。hook 腳本每次啟動先檢查 marker，存在就 `exit 0`。

安裝器修改 `~/.claude/settings.json` 時必須使用 JSON parser，不用 regex 字串拼接。流程：

1. 若檔案不存在，建立最小 JSON object。
2. 若檔案存在，先 parse；parse 失敗就停止，不寫入。
3. 寫入前建立 timestamp backup。
4. 保留所有未知欄位，只在 `hooks.Stop` 底下追加 voxshell command hook。
5. 用穩定識別方式避免重複追加，例如 command 絕對路徑相同就視為已安裝。
6. 用 temp file + atomic rename 寫回。

解除安裝只移除 voxshell 自己加的 hook entry，不清空使用者其他 hooks；若 array 變空可以保守保留空結構，避免過度整理造成 diff 風險。解除安裝也可刪除 `~/.voxshell/mute`、PID file、log file，但不刪使用者設定備份。

### 理由

這是公開 GitHub 產品最容易被使用者信任或不信任的地方。寧可多一個 backup 和 dry-run，也不要為了安裝方便覆寫使用者既有 Claude Code 設定。

## 5. 耳朵範圍

### 方案比較

方案 A：v1 依賴 macOS 內建 Dictation / Voice Control，voxshell 只做嘴巴。使用者把游標放在 Claude Code / Codex / Gemini CLI 輸入框，用系統聽寫把語音變文字送進正在工作的 session。

方案 B：voxshell 自帶 push-to-talk：錄音 -> whisper -> 把文字貼進目前 CLI 輸入框。這會牽涉剪貼簿、Accessibility 權限、焦點管理、終端機相容性、Enter 送出時機、以及避免誤貼到錯誤視窗。

方案 C：voxshell 包一層 pty，自己代理整個 CLI session。這能控制耳朵和嘴巴，但會重新發明 terminal multiplexer，還可能破壞各 CLI 的 TUI、快捷鍵、權限 prompt 和 session resume。

### 推薦

v1 採方案 A：README 老實說「M3 第一版是 mouth-first；耳朵請先用 macOS Dictation 或你習慣的輸入法語音輸入」。M2 的 `talk.py` 保留為 demo mode，展示完整 speech-to-text-to-speech loop，但不再宣稱那是主產品模式。

### 理由

產品差異化是把「正在工作的 AI session」念出來，不是再做一個聽寫工具。自帶 push-to-talk 會把 M3 拉回 Typeless / dictation 類產品的競爭，而且權限與焦點錯貼風險很高。先把嘴巴做好，耳朵後續再做 optional companion。

## Phase 拆分

| Phase | 里程碑 | 範圍 | 不做 |
|---|---|---|---|
| Phase 1 | 產品擁有者本機先能用起來：Claude Code 回覆完會用 `say` 念出短稿 | Claude Code `Stop` hook、`last_assistant_message` 主路徑、清洗、前 2 句短稿、背景播放、PID 打斷、marker mute | 不做 Codex / Gemini；不做 push-to-talk；不改 M2 demo 行為 |
| Phase 2 | 可以安心公開給別人裝 | 安裝 / 解除安裝、`~/.claude/settings.json` 安全合併、backup、dry-run、README 產品轉向、M2 demo mode 說明 | 不碰使用者其他 hooks；不做跨平台 TTS |
| Phase 3 | Codex CLI adapter 可用 | 驗證 `notify = [...]` payload、Codex read-aloud script、文件化限制；若 `notify` 不穩，再評估 `[hooks] Stop` | 不承諾 Gemini；不依賴 undocumented behavior 當公開主路徑 |
| Phase 4 | 擴充輸入與語音體驗 | 可選 push-to-talk prototype、摘要段優先策略、voice/rate 設定、不同 TTS backend | 不把輔助使用權限設成必裝前提 |

## 風險清單

1. Hook / notify API 漂移。Claude Code、Codex CLI 都在快速變動；特別是 Codex `notify` 名稱帶 legacy，未確認未來是否保留。緩解方式：Phase 1 只承諾 Claude Code；每個 adapter 都有版本檢查、fail-open、明確文件化支援版本。

2. 念出來的內容不適合聽。coding agent 回覆常有 code、diff、路徑、測試輸出；如果清洗和截斷太弱，使用者會立刻關掉。緩解方式：v1 預設短稿、少念、可 mute，未來再做摘要段偵測。

3. 安裝器破壞使用者既有設定或造成安全疑慮。修改 `~/.claude/settings.json`、`~/.codex/config.toml` 都是高敏感操作。緩解方式：parser-based merge、backup、dry-run、只移除自己加的 entry，並在 README 說清楚 hook 會以本機使用者權限執行。

## 未確認項目

- 未確認：Codex `notify = [...]` 在公開 docs 是否仍是推薦入口，以及未來是否會被 lifecycle hooks 取代。
- 未確認：Codex lifecycle hooks 的一般使用者安裝 / trust review UX 在所有發行版本是否穩定；本文件只根據 OpenAI Codex 原始碼與本機 `codex-cli 0.144.1` 觀察提出設計。
- 未確認：Gemini CLI 是否有 undocumented lifecycle hook、extension event、或 telemetry subscriber 可在每回合結束時觸發外部程式。

## 裁定紀錄（2026-07-12 主對話逐項裁定）

- §1 嘴巴架構方案 B（stdin `last_assistant_message` 主路徑、transcript 只當 fallback）：**採納**。附帶條件：Phase 1 驗收必須在真實 Claude Code session 實測 hook 觸發，不得只靠假 payload。
- §2 跨 AI：Claude Code 接法**採納**；Codex 走 `notify` **採納**，但**時程提前**（見下）——`notify` 未確認項就地實測解決：本機就有 codex-cli 0.144.1，Phase 1.5 直接掛上去驗，不留懸案。Gemini 不承諾，**採納**。
- §3 念稿方案 D（前 2 句＋硬上限）：**採納**為預設。另記一筆比賽加分項：可選的「GPT-5.6 生成口語摘要」模式（把回覆丟給 GPT 產一句適合聽的摘要）——正中 Build Week 評審標準，列 Phase 1.5 選配。
- §4 marker file mute ＋ parser-based 安全合併安裝器：**採納**全部六步流程。
- §5 耳朵 v1 = macOS 聽寫、不自帶 push-to-talk：**採納**。
- **Phase 順序改判**：P1（Claude Code 嘴巴，擁有者本機能用）→ **P1.5 Codex notify adapter 提前**（原 P3；OpenAI Build Week 2026-07-13~07-21 收件、評 GPT-5.6 使用深度，Codex 支援是參賽門票）→ P2 安裝器＋README 轉向 → P3 參賽包裝（若地區資格確認）→ P4 擴充。
- 三筆「未確認」處置：Codex notify 穩定性 → P1.5 實測收掉；Codex lifecycle hooks UX → 不採用該路線，懸置；Gemini hook → 懸置、README 標 planned。

## 查證來源

- Claude Code Hooks reference: https://code.claude.com/docs/en/hooks
- OpenAI Codex config source: https://raw.githubusercontent.com/openai/codex/main/codex-rs/config/src/config_toml.rs
- OpenAI Codex hook config source: https://raw.githubusercontent.com/openai/codex/main/codex-rs/config/src/hook_config.rs
- OpenAI Codex legacy notify source: https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/src/legacy_notify.rs
- OpenAI Codex Stop hook source: https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/src/events/stop.rs
- Gemini CLI configuration docs: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/configuration.md
