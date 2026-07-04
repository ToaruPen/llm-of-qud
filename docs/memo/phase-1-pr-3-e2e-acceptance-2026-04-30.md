# Phase 1 PR-3 E2E Acceptance Memo

Date: 2026-04-30
Branch: `codex/phase-1-pr-3-idempotency`
Verdict: PASS for terminal tool-call happy path

## Scope

This run validates that the Phase 1 PR-3 branch Roslyn-compiles in Caves of
Qud, loads the `LLMOfQud` mod, and completes an in-game WebSocket round trip
through the Python Brain `tool_call_probe:execute` phase.

It does not inject adversarial duplicate or stale terminal tool calls in-game.
Those paths remain covered by Python tests and C# static contract tests.

## Commands / Checks

- Started the Python Brain probe server:

  ```bash
  uv run python -m brain.app --phase tool_call_probe:execute --port 4040
  ```

- Confirmed Caves of Qud mod compile/load from:

  ```text
  ~/Library/Application Support/Freehold Games/CavesOfQud/build_log.txt
  ```

- Confirmed runtime round-trip counts from:

  ```text
  ~/Library/Logs/Freehold Games/CavesOfQud/Player.log
  ```

## Build Evidence

The build log for the accepted run contains:

```text
[2026-04-30T23:15:50] === LLM OF QUD ===
[2026-04-30T23:15:50] Compiling 8 files...
[2026-04-30T23:15:51] Success :)
[2026-04-30T23:15:56] [LLMOfQud] loaded v0.0.1 at 2026-04-30T14:15:56.8061380Z
```

## E2E Evidence

| Signal | Count |
|---|---:|
| C# `[LLMOfQud][decision_request] queued` | 330 |
| C# `[LLMOfQud][decision_response] received` | 330 |
| C# `[LLMOfQud][decision]` | 330 |
| C# `[LLMOfQud][disconnect_pause]` | 0 |
| Python server `phase=tool_call_probe:execute` decision requests | 330 |
| Python server `decision_response` | 330 |
| LLMOfQud-specific runtime error markers | 0 |

The first attempted game launch in this session ran without a Brain server
listening on `localhost:4040`, producing 52 `disconnect_pause` lines and no
decision responses. That run is excluded from the accepted evidence window.

The accepted run started after the Brain server was listening on
`localhost:4040`; it completed 330 matched request/response/decision cycles.

## Notes

- The Python server logged a `ConnectionClosedError` after turn 330 when the
  game process exited without a close frame. This is shutdown noise and did not
  occur until after the accepted evidence window.
- The runtime log contains 9 `[cmd]` lines with `result:false` and
  `fallback:"pass_turn"`. These are command-issuance fallbacks for blocked or
  failed in-game movement, not WebSocket transport failures and not terminal
  tool-call idempotency failures.

## Limitations

This happy-path E2E run exercises terminal tool-call dispatch through
`tool_call_probe:execute`, including live Roslyn compilation and in-game
WebSocket request/response flow. It does not prove the adversarial idempotency
branches in-game:

- duplicate `message_id`
- duplicate `action_nonce`
- stale `state_version`
- stale `session_epoch`
- mismatched `snapshot_hash`

Those branches are covered by automated tests in this branch. A future in-game
probe phase can deliberately inject those malformed or duplicate tool calls if
runtime evidence for each rejection branch is required.
