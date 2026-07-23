# voxshell Agent Audio Watch 定位設計

## 決策

voxshell 定位為 Coding Agent 的語音值班員，而不是語音輸入工具、寵物介面或一般文字轉語音程式。

目前版本的核心承諾：

> Stop watching the terminal. Hear the result when your coding agent finishes.

繁體中文：

> 不用盯著 Terminal；Coding Agent 完成時，直接聽到結果。

下一階段加入事件分類後，產品主張才升級為：

> Stop watching your coding agents. Hear only what needs your attention.

## 使用者與問題

主要使用者是在 macOS 上使用 Codex CLI 或 Claude Code，而且會切去其他視窗、離開座位，或同時執行多個工作的人。

畫面上的文字狀態只能在使用者正在觀看時提供幫助。voxshell 讓使用者不看畫面，也能在 Agent 完成或未來需要介入時收到短而有用的語音通知。

## 產品邊界

### 現在可以承諾

- 在 Codex CLI 或 Claude Code 完成一輪工作後取得最後回覆。
- 移除程式碼、表格、網址、長路徑與其他不適合朗讀的內容。
- 在本機保留最多兩句有用結果，使用 macOS `say` 朗讀。
- 預設不錄音、不呼叫額外 API，朗讀失敗也不阻塞 Coding Agent。

### 下一階段

- 區分完成、卡住與等待批准三種事件。
- 在語音中說出 Agent 與專案名稱。
- 只在真正需要注意時打斷使用者，避免朗讀每一段進度。

### 明確不做

- 不自行開發語音辨識模型或通用聽寫工具。
- 不複製 Codex 寵物或製作常駐角色介面。
- 不把雙向語音對話寫成現成功能。
- 未來若需要語音回覆，優先整合 macOS 聽寫或其他本機語音輸入工具。

## 產品架構

```text
Codex notify / Claude Code Stop hook
                  ↓
          event + final reply
                  ↓
     local clean + shorten + classify
                  ↓
       attention policy + interruption
                  ↓
              macOS say
```

目前版本使用完成事件、文字清理與朗讀。事件分類及注意力規則屬於下一階段，不在這次 README 定位修改中假裝已完成。

## README 資訊順序

1. 首句說明使用者不用持續盯著 Terminal。
2. 一句話解釋 voxshell 會在 Agent 完成時朗讀精簡結果。
3. 用簡圖呈現事件、清理與本機朗讀流程。
4. 列出現在真的支援的功能與限制。
5. 在問題段落說明視覺通知只在觀看畫面時有效。
6. 在 Roadmap 中列出卡住、等待批准與多 Agent 識別。
7. 繁體中文快速說明使用相同承諾，不使用較寬泛的「完整語音模式」描述。

## 失敗處理

- 無法解析事件時保持安靜，不猜測事件類型。
- 內容仍像程式碼時不朗讀。
- 語音後端失敗時不影響 Agent。
- 新通知只中斷 voxshell 自己啟動的上一段語音。

## 驗證

這次 README 修改完成後應符合：

- 新訪客能在 10 秒內說出 voxshell 解決的問題。
- 首屏不讓人誤以為產品支援完整雙向語音對話。
- 現成功能與 Roadmap 有清楚區隔。
- 英文與繁中定位一致。
- 安裝指令、平台支援與現有測試說明不被改壞。

未來事件分類完成時，應以完成、卡住、等待批准、未知事件及連續新通知建立測試案例。

## 比賽展示故事

同時執行多個 Coding Agent：一個正常完成、一個測試失敗、一個等待批准。voxshell 不朗讀所有輸出，只以短語音指出真正需要使用者注意的工作。

這是下一階段的展示目標；目前 README 只會把它標示為 Roadmap，不會宣稱已完成。
