# Phase 1 Progress — 2026-04-29

## Current Status

Phase 1 PR-1.1 is merged.

- PR: [#20 Phase 1 PR-1 disconnect acceptance hardening](https://github.com/ToaruPen/llm-of-qud/pull/20)
- Branch merged: `feat/phase-1-pr-1-impl` -> `main`
- Merge time: 2026-04-29T02:28:27Z
- Merge commit on `main`: `43c86a5`

PR-1.1 proves the Phase 0-G `IDecisionPolicy` boundary can cross the
C# MOD <-> Python process boundary without changing `decision_input.v1`
or `decision.v1`.

## Completed in PR-1.1

- `mod/LLMOfQud/BrainClient.cs`: dedicated WebSocket transport thread,
  connect/disconnect lifecycle, request correlation, timeout handling,
  and reconnect callback plumbing.
- `mod/LLMOfQud/WebSocketPolicy.cs`: `IDecisionPolicy` implementation
  that sends `decision_input.v1` to the Python probe server and parses
  `decision.v1` responses.
- `mod/LLMOfQud/LLMOfQudSystem.cs`: runtime policy rehydration,
  disconnect pause behavior, and reconnect wake using
  `ActionManager.SkipPlayerTurn` plus `Keyboard.KeyEvent.Set()`.
- `brain/app.py`: localhost WebSocket probe server with phase controls,
  canned no-LLM decisions, latency/disconnect probes, and acceptance
  phase behavior.
- `brain/auth/*`: Codex auth scaffolding with token persistence and
  Phase 2a placeholder errors.
- `brain/db/*`: SQLite telemetry schema and async writer scaffolding.
- Tests covering Python probe behavior, auth scaffolding, telemetry
  writer behavior, and static C# contract checks.

## Acceptance Evidence

Acceptance progress is recorded in
`docs/memo/phase-1-pr-1-acceptance-progress-2026-04-29.md`.

Four accepted runtime runs were collected. Each accepted run showed:

- Channel parity across `[decision]`, `[cmd]`, `[state]`, `[caps]`,
  `[build]`, and `[screen]`.
- Exactly one disconnect pause and one reconnect wake.
- No `ERR_`, `ERROR`, `MODERROR`, or `Traceback` markers in accepted
  artifacts.
- Round-trip p95 at `1ms`, well under the `<100ms` no-LLM target from
  `docs/architecture-v5.md:2862-2864`.

The original plan's five-run target was not fully executed as written.
PR #20 accepted the four-run evidence because the fourth run revealed no
new failure modes and the PR review converged with all checks passing.

## Verification After Merge

Commands run on `main` after PR #20 merged:

```bash
uv run pytest tests/
pre-commit run --all-files
```

Results:

- `uv run pytest tests/`: 39 passed.
- `pre-commit run --all-files`: all hooks passed.

## Remaining Phase 1 Work

PR-2 is next. It owns the v5.9 envelope and operational message layer:

- `tool_call` / `tool_result` request-response envelope.
- `ToolRouter.cs`.
- Full error/retry infrastructure.
- `supervisor_request` / `supervisor_response`.
- Precedent research for the tool-call envelope and prompt-cache
  strategy, as required by ADR 0011's PR-2 forward-looking note.

PR-3 remains the terminal-action idempotency slice:

- `action_nonce`
- `state_version`
- `session_epoch`
- cached duplicate result behavior

Phase 2a should not begin until PR-2 and PR-3 land.
