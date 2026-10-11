# Claude Code autonomous interactive pilot — lifecycle

Transport: `claude-cli`, foreground print. Exact requested model: `claude-opus-5-5`; effort: `xhigh`. This attempt was explicitly authorized by the user. No fallback or automatic retry.

Original task: perform 25 actual Claude-chosen game decisions through the authorized MCP. Task prompt: [claude-m1-prompt-interactive-pilot-20260927.txt](claude-m1-prompt-interactive-pilot-20260927.txt); replacement system prompt: [claude-m1-system-interactive-pilot-20260927.txt](claude-m1-system-interactive-pilot-20260927.txt). Both mode 0600.

```json
{
  "status": "completed",
  "pid": 65992,
  "startedUtc": "2026-09-27T01:48:41Z",
  "elapsedSeconds": 83.3,
  "deadlineSeconds": 600,
  "exitCode": 0,
  "models": [
    "claude-opus-5-5"
  ],
  "effortRequested": "xhigh",
  "events": {
    "system": 52,
    "stream_event": 566,
    "assistant": 45,
    "rate_limit_event": 1,
    "user": 27,
    "result": 1
  },
  "tools": {
    "mcp__qud__get_state": 2,
    "mcp__qud__act": 25
  },
  "subtype": "success",
  "is_error": false,
  "turns": 28,
  "permissionDenialCount": 0,
  "survivingInvocationPids": [],
  "stderrPresent": false,
  "rawOutputRetained": false
}
```

Raw transcript was not requested and was not retained. Only allowlisted lifecycle metadata is saved here. Secret-like values are redacted before displaying candidate result text. A supervisor-reviewed synthesis will be appended separately. CLI completion alone does not prove gameplay; the supervisor must verify the ledger and game logs. The game session uses restricted mode, no built-in tools, no user/project/local settings, disabled hooks/skills/memory, and only the explicitly authorized local qud MCP. Safe mode disables MCP and cannot serve this game-playing contract. No global setting was changed.

Supervisor evidence: .runtime/r6-live-20260927/run8/claude-pilot-ledger.jsonl is the frozen 25-decision ledger. harness.verify --require-completed 25 --m1 passed; 77 rows, seq 1 to 26, 25 completed decisions (23 move, 2 explore), world turns 9 to 28, HP 18/18 throughout. Both explore calls stopped without progress (ENGINE_STOP); all 23 moves executed. This is 83.3 seconds of actual Claude Code interactive development play, not the M2 one-hour SDK protocol criterion. Recovery was performed by the operator before Claude began.
The ledger also records one accepted notice_accept system response for the exploration notice at seq 3. The player saw no respond-required modal, but a modal did occur and was handled by the system rule. All four telemetry counters were 0.
