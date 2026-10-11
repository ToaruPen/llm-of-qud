# Claude Code autonomous interactive pilot — lifecycle

Transport: `claude-cli`, foreground print. Exact requested model: `claude-opus-5-5`; effort: `xhigh`. This attempt was explicitly authorized by the user. No fallback or automatic retry.

Original task: perform useful autonomous play through up to 200 advancing game turns, at most 100 completed decisions, through the authorized MCP. Task prompt: [claude-m1-prompt-macros-pilot-20260927.txt](claude-m1-prompt-macros-pilot-20260927.txt); replacement system prompt: [claude-m1-system-macros-pilot-20260927.txt](claude-m1-system-macros-pilot-20260927.txt). Both mode 0600.

```json
{
  "status": "completed",
  "pid": 26864,
  "startedUtc": "2026-09-27T04:37:34Z",
  "elapsedSeconds": 92.3,
  "deadlineSeconds": 900,
  "exitCode": 0,
  "models": [
    "claude-opus-5-5"
  ],
  "effortRequested": "xhigh",
  "events": {
    "system": 55,
    "stream_event": 410,
    "assistant": 36,
    "rate_limit_event": 1,
    "user": 18,
    "result": 1
  },
  "tools": {
    "mcp__qud__get_state": 2,
    "mcp__qud__act": 16
  },
  "subtype": "success",
  "is_error": false,
  "turns": 19,
  "permissionDenialCount": 0,
  "survivingInvocationPids": [],
  "stderrPresent": false,
  "rawOutputRetained": false
}
```

Raw transcript was not requested and was not retained. Only allowlisted lifecycle metadata is saved here. Secret-like values are redacted before displaying candidate result text. A supervisor-reviewed synthesis will be appended separately. CLI completion alone does not prove gameplay; the supervisor must verify the ledger and game logs. The game session uses restricted mode, no built-in tools, no user/project/local settings, disabled hooks/skills/memory, and only the explicitly authorized local qud MCP. Safe mode disables MCP and cannot serve this game-playing contract. No global setting was changed.

## Codexによる照合

49行の台帳を検証し、16判断（explore 9、goto 1、move 6）、turn 25→225、HP 18/18、Red Rock 地下1層 (41,16) を確認した。seq 17で待機。PlayerTurn / EndPlayerTurn / UIタスク / 未知タスクは全て0。リカバリー・モーダル・実行拒否は0。台帳先頭ハッシュは `c05d67ee5ebd7f55b7d4969e477b341dbc8cff407061b452e4d96ecfbed64a81`。凍結した台帳と照合結果は `.runtime/macros-live-20260927/claude-pilot/`。測定終了後に handoff し、ゲームとハーネスを正常終了した。

実プレイはClaude Codeのinteractive走行で92.3秒。無人1時間やSDK直接走行は未検証。空腹への対応に必要な所持品操作は未実装だった。修正と検証はCodexが担当し、ClaudeはゲームMCP操作だけを行った。
