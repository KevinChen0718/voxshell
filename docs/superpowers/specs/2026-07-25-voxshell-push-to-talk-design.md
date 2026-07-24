# voxshell Push-to-Talk v1 設計

## 決策

Push-to-Talk v1 讓使用者按住全域快捷鍵說出下一步，放開後在 Mac 本機轉成文字，直接送回剛才由 voxshell 回報的 Codex session。

核心循環：

```text
Codex 做事
    ↓
voxshell 朗讀結果並記住 session
    ↓
使用者按住快捷鍵說下一步
    ↓
本機轉錄，放開即送出
    ↓
原 Codex session 繼續做事
```

按住快捷鍵是本次送出的明確授權。v1 不增加文字預覽或第二次確認。

## 為什麼採這個方案

- 比手打快，也不需要另外操作通用聽寫工具。
- 不常駐錄音；只有按住快捷鍵時才存取麥克風。
- Codex 通知可讓 voxshell 保存來源 session，避免只把文字放進剪貼簿後讓使用者自行找視窗。
- 與 voxshell 現有的語音回報組成完整但仍可控的來回循環。

沒有採用的方案：

- 通用語音輸入：會與 Typeless、OnVoice、macOS 聽寫競爭，且沒有解決送回哪個 Agent 的問題。
- 回報後自動開啟麥克風：較接近免手操作，但有隱私、環境誤觸與誤送風險。
- 代理完整 Terminal / PTY：可能破壞 Codex TUI、快捷鍵、權限提示與 session 行為，超出 v1 範圍。

## v1 使用流程

1. Codex 完成一輪工作。
2. 現有 `notify` adapter 讀取 JSON payload、朗讀精簡結果，並以原子寫入保存：
   - Codex session / thread id
   - working directory
   - 通知時間
   - 適合顯示的專案名稱
3. 使用者按住預設快捷鍵 `⌥ Space`。
4. Push-to-Talk companion 在 key-down 時鎖定當下目標 session，播放開始提示音並開始錄音。
5. 使用者說出下一步。
6. 使用者放開快捷鍵；companion 停止錄音並播放結束提示音。
7. faster-whisper 在本機轉錄音訊。
8. 非空白文字透過 Codex resume adapter 送回 key-down 時鎖定的 session。
9. Codex 完成下一輪後，既有 voxshell 通知再次朗讀結果。

`Esc` 只在快捷鍵仍按住、錄音尚未送出時取消本次操作。

## 目標 session 規則

- 以最近一次成功朗讀的 Codex 通知作為候選目標。
- 候選通知預設 15 分鐘後失效；逾時就不允許直接送出。
- key-down 時複製候選 session 資料，後續通知不得改變本次目標。
- companion 必須在錄音狀態中顯示專案名稱，降低送錯專案的風險。
- 沒有有效 session id 或 working directory 時，不啟動錄音，播放錯誤提示音。
- v1 不提供多 session 選擇器；要回覆其他 session，先讓該 session 成為最近一次 voxshell 通知。

## 元件與資料流

```text
Codex notify payload
        ↓
existing speech pipeline ──→ macOS say
        ↓
atomic active-session state
        ↓
Push-to-Talk companion
  ├─ global hotkey
  ├─ ffmpeg microphone recording
  ├─ faster-whisper transcription
  └─ Codex resume adapter
        ↓
codex exec resume <session-id> -
        ↑
 transcript 透過 stdin 傳入
```

### Session state

Session state 放在 voxshell 自己的使用者狀態目錄，不寫進專案 repo。資料只保留路由所需欄位，不保存完整 assistant 回覆。

狀態寫入必須使用 temporary file + replace，避免通知與快捷鍵同時讀寫出現半份 JSON。

目前 Codex `notify` adapter 取得的欄位名稱是 `thread-id`；v1 會在 adapter 邊界把它正規化成內部 `session_id`。這個值能否直接作為 `codex exec resume` 的 `SESSION_ID`，由下方最小技術實驗判定，不從欄位名稱推定。

### Push-to-Talk companion

全域 key-down / key-up 需要一個選用的長駐 companion。原本只做朗讀的 hook 模式仍不需要 daemon；README 與安裝流程必須清楚區分兩種模式。

Companion 需要：

- Microphone 權限，用於按住期間錄音。
- Accessibility 權限，用於監聽全域快捷鍵。

它不得存取鍵盤輸入內容，只辨識設定的快捷鍵與錄音期間的 `Esc`。

### Codex resume adapter

官方 Codex CLI 參考記載：

- `codex exec resume [SESSION_ID] [PROMPT]` 可以依 session id 接續並帶入 follow-up prompt。
- `notify` 是接收 Codex JSON payload 的外部命令。
- Codex hooks 的共同欄位包含 `session_id` 與 `cwd`。

Hooks 的 `session_id` 不等於已證明 `notify` 的 `thread-id` 可直接 resume。官方文件也沒有保證：原本互動式 TUI 仍開啟時，另一個 `codex exec resume` process 能安全接續同一 session。因此正式開發前先做最小實驗，不能把這兩點當成已確認行為。

本機 CLI 的 `--help` 另確認 `[PROMPT]` 可使用 `-` 從 stdin 讀取。v1 必須使用 stdin，避免語音 transcript 出現在 process argv；也不得加入任何跳過 Codex approval 或 sandbox 的旗標。

## 最小技術實驗

先驗證路由，不先做全域快捷鍵 UI：

1. 啟動一個測試 Codex session，完成一輪無副作用工作。
2. 從真實通知 payload 保存 session id 與 cwd。
3. 保持原 TUI 開啟，從另一個 process 執行 `codex exec resume`，傳入只要求回覆固定文字的 prompt。
4. 確認：
   - follow-up 出現在同一 session；
   - 原 TUI 沒有損壞或鎖死；
   - 第二輪完成仍觸發 voxshell 通知；
   - 沒有產生意外 fork 或重複 session。

若任一項失敗，停止 v1 實作並重新評估官方 app-server / remote-control 路線；不改用鍵盤模擬或未文件化的 Terminal 注入。

## 失敗處理

- 快捷鍵衝突：啟動時停止並要求使用者設定其他組合。
- 麥克風或 Accessibility 權限缺失：說明缺少哪個權限，不重試迴圈。
- 錄音太短或空白：不送出。
- 轉錄失敗：不送出，刪除暫存音檔。
- Codex resume 回傳非零：保留 transcript 於 companion 畫面供複製，播放失敗提示音，不自動重試。
- 錄音期間收到新通知：本次仍送到 key-down 時鎖定的 session。
- companion 或 speech hook 失敗：不得阻塞 Codex 本身。

## 隱私與資料生命週期

- 麥克風只在按住快捷鍵時啟用。
- 音訊只存於 temporary file，轉錄完成或失敗後都刪除。
- faster-whisper 在本機執行。
- transcript 只傳給使用者原本選用的 Codex CLI；voxshell 不另外上傳。
- 除 routing state 外，不新增長期語音或逐字稿紀錄。

## 測試

自動測試：

- Codex payload 能正確保存 session id、cwd 與專案名稱。
- Session state 原子寫入、缺欄位拒絕與損壞 JSON 容錯。
- key-down 鎖定目標，後續通知不會換掉本次目標。
- key-up 只在有效、未逾時 session 與非空 transcript 同時成立時建立 resume command。
- `Esc` 取消、空白錄音、轉錄失敗與 resume 失敗都不送出。
- 音檔在成功與失敗路徑都會刪除。
- command 使用固定 argv 陣列並從 stdin 傳入 transcript，不以 shell string 或 process argv 拼接 transcript。

手動驗收：

- 真實 Codex TUI 的同 session 接續實驗通過。
- `⌥ Space` 在其他 App 前景時仍可錄音。
- 權限提示、開始／結束／錯誤提示音可辨識。
- 說中文、英文及中英混合指令都能送回正確專案。
- 原本 Claude Code 與 Codex 的朗讀功能及測試保持正常。

## v1 明確不做

- Claude Code 語音回覆。
- 多 session 選擇器。
- 文字預覽、第二次確認或語音「送出」口令。
- 自動修正文句的 LLM。
- 常駐免手監聽或 wake word。
- Windows / Linux。

## 成功標準

使用者在其他 App 工作時，可以按住 `⌥ Space` 說出下一步；放開後，指令送回剛才由 voxshell 回報的 Codex session，並在該 session 完成後再次聽到結果。整個流程不需要打字、切換視窗或手動選擇 session。

## 官方資料

- [Codex developer commands](https://developers.openai.com/codex/developer-commands)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Codex hooks](https://developers.openai.com/codex/hooks)
