# Phase 1 PR-1 Implementation Plan — WebSocket Bridge (Boundary Slice)

> **For agentic workers:** REQUIRED SUB-SKILL: Execute via Codex delegate per task, with Claude as orchestrator. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the Phase 1 PR-1 boundary slice before any Phase 2 work:
1-A WebSocket bridge, `WebSocketPolicy : IDecisionPolicy`, 1-C Codex auth
scaffolding, 1-D SQLite telemetry scaffolding, disconnect=pause, and
reconnect-wake plumbing. The scope is sealed by Q1-Q5 in
`docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` and recorded by
ADR 0011. PR-1 proves that the Phase 0-G decision boundary can cross a
process boundary without changing `decision_input.v1` or `decision.v1`.
The exit gate remains: full round-trip latency `<100ms` with a no-LLM
canned Python policy (`docs/architecture-v5.md:2862-2864`).

**Architecture:** Phase 0-G's
`BuildDecisionInput -> Decide -> Execute` triple stays in
`LLMOfQudSystem.cs`; PR-1 swaps `_policy = new HeuristicPolicy()` to
`_policy = new WebSocketPolicy(...)`. `WebSocketPolicy.Decide` blocks
for O(timeout) on a `Task` completed by `BrainClient`, while
`BrainClient` owns socket connect, send, receive, and reconnect detection
on a dedicated non-game thread. The disconnect path is sealed as pause,
not runtime `HeuristicPolicy` fallback, but the exact pause/wake mechanism
is probe-driven by Task 1 and ADR 0013.

**Tech Stack:** C# in the existing Roslyn-compiled CoQ MOD; Python 3.13
with uv, `websockets` 16.0, `aiosqlite`, and `structlog` per
`docs/architecture-v5.md:1834-1836` and `brain/AGENTS.md`.

**Sealed scope notice (ADR 0011):**

| Sealed decision | Choice | PR-1 implementation task |
|---|---|---|
| Q1 PR-1 scope | Option A boundary proof | Tasks 2-5 create `BrainClient`, `WebSocketPolicy`, and `brain/app.py` without 1-B tool envelope |
| Q2 supervisor_request placement | PR-2 | Task 4 pauses locally; no `supervisor_request` messages in PR-1 |
| Q3 disconnect fallback | Pause, no runtime `HeuristicPolicy` continuation | Tasks 1 and 4 lock pause and reconnect-wake after probes |
| Q4 1-C / 1-D | Include in PR-1 | Tasks 6 and 7 add auth and SQLite scaffolding |
| Q5 FindPath safety-net | Defer to Phase 2a or later | No CoQ pathfinder integration in PR-1 |

---

## Definitions

- **Single gate before pushing**:
  `pre-commit run --all-files && uv run pytest tests/`.
- **PR convergence**: PR-1.0 is this readiness PR: plan, ADR 0011,
  decision-log entry, decision record, and the sealed-decisions memo.
  It merges first. Implementation PR-1.1 opens only after Task 1 probe
  results either lock ADR 0012 / ADR 0013 or force mid-flight ADRs using
  the ADR 0007 precedent.
- **Phase 1 PR cascade**: PR-1.0 -> PR-1.1 -> PR-2 -> PR-3 -> Phase 2a.
- **Probe-before-lock rule**: ADR 0007 exists because an empirical probe
  falsified a load-bearing implementation claim after design lock
  (`docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md`).
  PR-1 treats Probes 1, 2, 3, 6, and 8 from
  `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` §5 as Task 1
  gates. No C# or Python implementation proceeds until those probes pass
  or the design pivots through ADR 0012 / ADR 0013.

## Files affected

**Create C#:**

- `mod/LLMOfQud/BrainClient.cs` — WebSocket client, dedicated thread,
  async send/receive, connect/disconnect lifecycle.
- `mod/LLMOfQud/WebSocketPolicy.cs` — `IDecisionPolicy`
  implementation; blocking-await O(timeout) on `BrainClient` roundtrip.

**Modify C#:**

- `mod/LLMOfQud/LLMOfQudSystem.cs` — instantiate `WebSocketPolicy`
  with `HeuristicPolicy` as compile-time fallback only; no runtime
  fallback on disconnect per Q3=pause; wire pause posture and
  reconnect-wake.

**Create Python:**

- `brain/app.py` — WebSocket server on localhost:4040 per
  `docs/architecture-v5.md:1842`.
- `brain/auth/device_flow.py`, `brain/auth/token_store.py`,
  `brain/auth/broker.py` — 1-C scaffolding that imports cleanly and has
  unit-test smoke coverage; real Codex API calls defer to Phase 2a per
  `docs/architecture-v5.md:1847-1850`.
- `brain/db/schema.py`, `brain/db/writer.py` — 1-D scaffolding per
  `docs/architecture-v5.md:1862-1864`.
- `brain/pyproject.toml` if no Python project file exists yet; otherwise
  extend the existing Python package configuration.

**Out of scope:**

- `brain/tool_loop.py`
- `brain/tool_schemas.py`
- `brain/prompt_builder.py`
- `brain/notes_manager.py`
- `brain/clients/codex_client.py`
- `brain/session/*`
- `brain/safety/*`
- `brain/overlay/*`

Those files are Phase 2a, PR-2, or PR-3 scope. Do not create them in
PR-1.

---

## Task 0: Land PR-1.0 readiness docs

**Files modified:**

- Create: `docs/superpowers/plans/2026-04-27-phase-1-pr-1-websocket-bridge.md`
- Create: `docs/adr/0011-phase-1-pr-1-scope.md`
- Modify: `docs/adr/decision-log.md`
- Create: `docs/adr/decisions/2026-04-27-*phase-1-pr-1-readiness*.md`
- Existing source memo, already landed before PR-1.0:
  `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md`

**Pass criteria:**

- Branch is cut from `main`, recommended name:
  `docs/phase-1-pr-1-readiness`.
- ADR 0011 states `Amend v5.9` because it sequences
  `docs/architecture-v5.md:2840-2861` across PR-1, PR-2, and PR-3
  without editing the frozen spec.
- The decision record exists and points at ADR 0011.
- No implementation files are created in PR-1.0.

**Verification commands:**

```bash
pre-commit run --all-files
uv run pytest tests/
git status --short
```

- [ ] Generate the decision record with:

```bash
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Add Phase 1 PR-1 readiness (Plan + ADR 0011)" \
  --rationale "Sealed 2026-04-27 scope decisions split frozen v5.9 Phase 1 into PR-1/PR-2/PR-3 so the WebSocket boundary, auth scaffolding, telemetry scaffolding, and pause posture can be reviewed before implementation." \
  --adr docs/adr/0011-phase-1-pr-1-scope.md
```

## Task 1: Empirical probes before implementation

**Files modified:**

- Create: `docs/memo/phase-1-pr-1-probes-YYYY-MM-DD.md`
- Create if probes pass cleanly: `docs/adr/0012-*.md`
- Create if probes pass cleanly: `docs/adr/0013-*.md`
- Create mid-flight replacement ADRs if any probe falsifies a
  load-bearing claim.

**Pass criteria:**

- Probes 1, 2, 3, 6, and 8 are run against minimal instrumentation
  before production C# / Python implementation begins.
- Each probe records setup, raw observable, expected result, actual
  result, and falsification action.
- No ADR 0012 / ADR 0013 claim is locked without a matching probe
  result. If a probe fails, write the ADR in the ADR 0007 pattern:
  cite the falsified claim, cite engine lines, then state the corrected
  rule.

**Verification commands:**

```bash
rg -n "Probe 1|Probe 2|Probe 3|Probe 6|Probe 8" docs/memo/phase-1-pr-1-probes-*.md
pre-commit run --all-files
```

- [ ] **Probe 1: blocking WebSocket wait on CTA.**
  Setup: 100 turns with Python sleeping 0ms, 50ms, 100ms, and 250ms
  before returning a fixed `Decision`.
  Pass: one `[decision]` and one `[cmd]` per CTA; `[screen]`,
  `[state]`, `[caps]`, and `[build]` remain correlated by turn; no
  keyboard prompt.
  If falsified: ADR 0012 must reject blocking `Decide` as the durable
  model and choose prefetch, queue routing, or continuation with new
  probes.

- [ ] **Probe 2: timeout fallback preserves energy drain.**
  Setup: Python sleeps beyond timeout for 50 turns.
  Pass: fallback-labeled `[decision]` and `[cmd]` lines show accepted
  energy drain or accepted negative energy; `PreventAction` remains
  scoped to the ADR 0007 abnormal-energy catch path.
  If falsified: ADR 0012 must alter timeout mechanics before
  implementation continues.

- [ ] **Probe 3: disconnect mid-`Decide`.**
  Setup: Python accepts a request, closes the socket before response,
  and repeats over 20 turns.
  Pass: exactly one `[decision]` and one `[cmd]` per turn, no duplicate
  terminal action, no stale decision applied after reconnect, and
  blocked-dir memory updates only after failed Move with
  `fallback == "pass_turn"` as in
  `mod/LLMOfQud/LLMOfQudSystem.cs:259-299`.
  If falsified: ADR 0013 must specify stale response rejection or a
  different disconnect sequence.

- [ ] **Probe 6: render fallback under slow decisions.**
  Setup: 60 turns with 200ms artificial decision latency.
  Pass: each completed decision has exactly one action and one
  observation set; observations do not bunch after many turns.
  If falsified: ADR 0012 must reject or narrow game-thread blocking.

- [ ] **Probe 8: reconnect wake mechanism.**
  Setup: hold WebSocket disconnected for 30+ seconds, observe CoQ
  entering native keyboard wait at `PlayerTurn`
  (`decompiled/XRL.Core/ActionManager.cs:838,1797-1799`), reconnect,
  then test wake options.
  Pass: chosen wake resumes within one render frame, applies no stale
  action, and leaves energy unchanged from the pre-pause state.
  Sub-options to test:
  (i) block-BTA polling loop; (ii) drain energy via `PassTurn`;
  (iii) `PreventAction = true` with no energy drain; (iv)
  `Keyboard.PushKey` wake injection.
  If falsified: ADR 0013 must choose a different pause absorber or
  reconnect wake mechanism before Task 4 proceeds.

## Task 2: `BrainClient.cs` skeleton

**Files modified:**

- Create: `mod/LLMOfQud/BrainClient.cs`

**Pass criteria:**

- Runs socket connect/disconnect/send/receive on a dedicated non-game
  thread.
- Never calls `ThreadTaskQueue.awaitTask()` from a thread that the
  target queue needs to drain; `awaitTask()` blocks with `WaitOne()`
  (`decompiled/QupKit/ThreadTaskQueue.cs:135-155`). Use
  `executeAsync()` (`decompiled/QupKit/ThreadTaskQueue.cs:77-100`) or
  queue-specific fire-and-forget only if future PR-2 tool routing needs
  a CoQ read.
- Preserves v5.9 queue separation: `gameQueue` and `uiQueue` are
  distinct (`decompiled/GameManager.cs:142-144`), and v5.9 warns
  against default-dispatching all WebSocket work to `gameQueue`
  (`docs/architecture-v5.md:1778-1804`).

**Verification commands:**

```bash
rg -n "awaitTask|Thread|Task|WebSocket|gameQueue|uiQueue" mod/LLMOfQud/BrainClient.cs
pre-commit run --all-files
```

- [ ] Implement connect lifecycle, disconnect detection, request
  correlation, and receive-loop completion of pending decisions.

## Task 3: `WebSocketPolicy.cs : IDecisionPolicy`

**Files modified:**

- Create: `mod/LLMOfQud/WebSocketPolicy.cs`

**Pass criteria:**

- `Decide(DecisionInput input)` blocks for `<= TIMEOUT_MS` on the
  `BrainClient` roundtrip.
- Socket close raises `DisconnectedException`.
- Successful response returns `Decision`.
- `decision_input.v1` / `decision.v1` wire format remains unchanged.
  `IDecisionPolicy.Decide` is locked as input-only at
  `mod/LLMOfQud/IDecisionPolicy.cs:58-64`.

**Verification commands:**

```bash
rg -n "class WebSocketPolicy|IDecisionPolicy|TIMEOUT_MS|DisconnectedException|Decide" mod/LLMOfQud/WebSocketPolicy.cs
pre-commit run --all-files
```

- [ ] Add only the minimal exception types and serialization needed
  for PR-1. Do not add v5.9 `tool_call` / `tool_result` envelopes here.

## Task 4: `LLMOfQudSystem.cs` wiring

**Files modified:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Pass criteria:**

- `_policy` is `WebSocketPolicy` in normal PR-1 operation.
- `HeuristicPolicy` exists only as compile-time fallback or test
  construction aid; runtime disconnect does not continue autonomous
  actions through it.
- `DisconnectedException` enters the Task 1 Probe 8 pause posture.
- Reconnect-wake hook is implemented by the ADR 0013 mechanism.
- ADR 0007 scope remains unchanged: `PreventAction` is not used on
  the success path, and the render fallback at
  `decompiled/XRL.Core/ActionManager.cs:1806-1808` remains load-bearing.

**Verification commands:**

```bash
rg -n "WebSocketPolicy|HeuristicPolicy|DisconnectedException|PreventAction|RenderBase" mod/LLMOfQud/LLMOfQudSystem.cs
pre-commit run --all-files
```

- [ ] Wire the policy swap and pause branch without changing
  `BuildDecisionInput` or `Execute`.

## Task 5: Python `brain/app.py`

**Files modified:**

- Create: `brain/app.py`

**Pass criteria:**

- Serves WebSocket on localhost:4040 per `docs/architecture-v5.md:1842`.
- Dispatches JSON `decision_input.v1` requests to a no-LLM canned policy.
- Default canned policy returns east `Move` for the first positive probe.
- Negative-test probes can configure sleep, timeout, disconnect-before-
  response, and fixed decision responses.
- Does not create `tool_loop.py`, `tool_schemas.py`, or Codex client code.

**Verification commands:**

```bash
uv run ruff check brain/
uv run ruff format --check brain/
uv run mypy --strict brain/
uv run basedpyright
uv run pytest tests/
```

- [ ] Implement the PR-1 server and probe controls with typed Python
  interfaces.

## Task 6: Python `brain/auth/*` scaffolding

**Files modified:**

- Create: `brain/auth/device_flow.py`
- Create: `brain/auth/token_store.py`
- Create: `brain/auth/broker.py`
- Create smoke tests under `tests/` as needed.

**Pass criteria:**

- Modules import cleanly and expose stable placeholder contracts for
  Phase 2a.
- No real Codex API call is made in PR-1.
- Secrets are never committed; token-store tests use temp paths.

**Verification commands:**

```bash
uv run ruff check brain/
uv run mypy --strict brain/
uv run pytest tests/
```

- [ ] Add minimal typed scaffolding that Phase 2a can replace without
  changing import paths.

## Task 7: Python `brain/db/*` scaffolding

**Files modified:**

- Create: `brain/db/schema.py`
- Create: `brain/db/writer.py`
- Create smoke tests under `tests/` as needed.

**Pass criteria:**

- SQLite schema can record PR-1 telemetry events:
  `connection_lifecycle`, `decision_request`, `decision_response`,
  `disconnect_pause`, and `reconnect_wake`.
- Writes are async and isolated from CoQ queues; v5.9 assigns telemetry
  SQLite writes to the WebSocket thread/background work
  (`docs/architecture-v5.md:1794`).
- Schema churn risk is accepted until PR-2 locks the envelope.

**Verification commands:**

```bash
uv run ruff check brain/
uv run mypy --strict brain/
uv run pytest tests/
```

- [ ] Add schema creation and an async writer with deterministic smoke
  tests.

## Task 8: Acceptance run

**Files modified:**

- Create run artifacts under the operator-local acceptance directory.
- Update no source file unless acceptance exposes a bug.

**Pass criteria:**

- 5-run gate follows Phase 0 precedent.
- Round-trip latency is `<100ms` for no-LLM policy; record median and
  p95.
- Each run includes at least one disconnect=pause -> reconnect cycle.
- Channel parity is maintained:
  `[cmd]=[decision]=[state]=[caps]=[build]=[screen]`.
- No `ERR_*` sentinels.
- Phase 1 exit criterion is satisfied as far as PR-1 scope allows:
  C# -> WebSocket -> Python -> C# -> result-bearing decision -> Python
  telemetry, with v5.9 tool envelope explicitly deferred to PR-2
  (`docs/architecture-v5.md:2862-2864`).

**Verification commands:**

```bash
pre-commit run --all-files
uv run pytest tests/
```

- [ ] Run and summarize five no-LLM acceptance runs.

## Task 9: Exit memo

**Files modified:**

- Create: `docs/memo/phase-1-pr-1-exit-YYYY-MM-DD.md`

**Pass criteria:**

- Memo follows the Phase 0-G exit-memo style.
- Includes probe outcomes, ADR 0012 / 0013 status, acceptance metrics,
  known deferrals, and PR-2 handoff.
- Calls out any schema or envelope facts that remain intentionally
  deferred.

**Verification commands:**

```bash
pre-commit run --all-files
uv run pytest tests/
```

- [ ] Write the exit memo after Task 8 acceptance completes.

---

## Acceptance

PR-1.1 exits when the no-LLM canned Python policy completes five
acceptance runs with median and p95 round-trip latency below 100ms,
disconnect=pause -> reconnect demonstrated at least once per run,
channel parity maintained across `[cmd]`, `[decision]`, `[state]`,
`[caps]`, `[build]`, and `[screen]`, and no `ERR_*` sentinels. The
v5.9 exit text remains the target citation
(`docs/architecture-v5.md:2862-2864`), while ADR 0011 records that
the full `tool_call` / `tool_result` envelope portion lands in PR-2.

## Risks

- **Unity main-thread freeze:** Probe 8 option (i), a block-BTA polling
  loop, may reproduce a Run 5-style freeze if it blocks longer than the
  queue/render path can tolerate.
- **Auth scaffolding fragility:** PR-1 includes 1-C without real Codex
  calls, so Phase 2a may reveal contract gaps despite import and smoke
  tests.
- **SQLite schema churn:** PR-1 telemetry tables precede the PR-2
  envelope lock, so `decision_request` / `decision_response` columns may
  churn when `tool_call` / `tool_result` becomes authoritative.
