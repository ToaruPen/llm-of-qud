# Phase 1 PR-2.1 E2E Acceptance Memo

Date: 2026-04-29
Branch: `codex/phase-1-pr-2-protocol-core`
Verdict: PASS

## Artifacts

Artifact directory: `/tmp/llm-of-qud-pr-2-1-e2e-20260429-134028`

- Full Player log: `Player.full.log`
- Build log: `build.full.log`
- Server log: `server.log`
- Count summary: `e2e-counts.txt`
- Error scan: `error-grep.txt`
- LLMOfQud Player log tail extract: `Player.llmofqud.tail.txt`

## Commands / Checks

- Confirmed build success from `build.full.log`: `Compiling 8 files...`, `Success :)`, `Location: .../LLMOfQud.dll`, final load order `1: LLMOfQud`, and `[LLMOfQud] loaded v0.0.1`.
- Confirmed E2E count summary from `e2e-counts.txt`.
- Recounted runtime markers in `Player.full.log` and `server.log`.
- Filtered error markers for LLMOfQud-specific failures, excluding expected `error:null` fields and known unrelated startup/shutdown noise.

## E2E Evidence

| Signal | Count |
|---|---:|
| C# `[LLMOfQud][decision_request] queued` | 520 |
| C# `[LLMOfQud][decision_response] received` | 520 |
| C# `[LLMOfQud][decision]` | 520 |
| C# `[LLMOfQud][cmd]` | 520 |
| C# command `result=true` | 520 |
| C# command `result=false` | 0 |
| Build success | 1 |
| Python server `phase=tool_call_probe:not_a_real_tool` | 520 |
| Python server `decision_response` | 520 |
| LLMOfQud-specific error markers, excluding `error:null` | 0 |

The run completed 520 matched request/response/decision/command cycles. The Python server emitted 520 probe-phase requests and 520 decision responses. C# command execution succeeded for all 520 commands and reported no failed command results.

Subagent reviewer verdict: PASS.

## Ignored Shutdown / Startup Noise

The following log noise is excluded from the verdict:

- Startup Galaxy/Steam initialization errors near the beginning of `Player.full.log`. These are unrelated to LLMOfQud.
- Shutdown and termination errors after evidence capture, including `ThreadAbortException`, Mono shutdown/runtime messages, and the server-side `ConnectionClosedError`. The operator force-quit/stopped the run after the 520-turn evidence window was captured.

The server recorded turn 520 before the later connection-close warning, so shutdown noise does not affect the accepted E2E evidence.

## Limitations

There are no dedicated C# runtime markers for `tool_call` / `tool_result`. The tool-call proof for this run relies on the Python `tool_call_probe:not_a_real_tool` phase, where the probe server only logs `decision_response` after observing the matching `tool_result`.
