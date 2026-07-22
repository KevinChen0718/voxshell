#!/usr/bin/env bash
# Optional example for summary_cmd. Each call spends OpenAI quota and adds a few seconds of latency.
# 選配範例：每次呼叫都會消耗 OpenAI 額度，並增加數秒延遲。
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  exit 1
fi

input="$(head -c 4000)"
if [[ -z "${input//[[:space:]]/}" ]]; then
  exit 1
fi

prompt=$'用跟輸入相同的語言，把以下 AI 回覆濃縮成一句適合念出來的口語摘要，只輸出那一句。\n\n'
codex exec --sandbox read-only "${prompt}${input}"
