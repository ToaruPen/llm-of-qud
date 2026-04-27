# Phase 1 Readiness Brainstorm — WebSocket Bridge

Date: 2026-04-27

Status: Draft brainstorm memo, not an implementation plan

## Purpose

Phase 1 is the first point where the Phase 0-G judgment boundary becomes
out-of-process. The frozen v5.9 Phase 1 goal is "C# MOD ↔ WebSocket ↔ Python
Brain pipeline" with tasks 1-A through 1-G and a no-LLM round-trip exit gate
(`docs/architecture-v5.md:2836-2864`). Phase 0-G also established a narrower
handoff surface: replace `HeuristicPolicy` behind
`IDecisionPolicy.Decide(DecisionInput) → Decision`, without changing
`BuildDecisionInput` or `Execute` (`docs/adr/0009-phase-0-g-rescope-judgment-boundary.md:88-107`,
`docs/memo/phase-0-g-exit-2026-04-27.md:155-230`).

This memo scopes the design decisions that should be settled before any Phase 1
implementation begins. It intentionally proposes options and trade-offs rather
than one recommendation.

## Source Baseline

- Architecture v5.9 is frozen. No spec edits without a new ADR
  (`docs/adr/0001-architecture-v5-9-freeze.md:11-27`).
- Current Python Brain is empty except `brain/AGENTS.md`; Phase 1 is the first
  real population of `brain/`.
- Current MOD uses `IPlayerSystem`, registers both `BeginTakeActionEvent` and
  `CommandTakeActionEvent`, and executes the Phase 0-G
  `BuildDecisionInput → Decide → Execute` flow in `HandleEvent(CommandTakeActionEvent)`
  (`mod/LLMOfQud/LLMOfQudSystem.cs:73-100`,
  `mod/LLMOfQud/LLMOfQudSystem.cs:358-612`).
- `BeginTakeActionEvent.Check` dispatches to `Object.HandleEvent(...)`, not a
  game-system-only path (`decompiled/XRL.World/BeginTakeActionEvent.cs:37-52`).
  `IPlayerSystem.RegisterPlayer` is the player-body registration hook
  (`decompiled/XRL/IPlayerSystem.cs:35-39`).
- `CommandTakeActionEvent.Check` resets `PreventAction`, dispatches the object
  event, and returns false if `PreventAction` is set
  (`decompiled/XRL.World/CommandTakeActionEvent.cs:28-40`).
- `CommandTakeActionEvent` is inside the `ActionManager` inner action loop, after
  the energy gate and before the player keyboard branch
  (`decompiled/XRL.Core/ActionManager.cs:800-838`).
- If the autonomous action drains player energy below 1000, the engine skips
  `PlayerTurn()` and reaches the player render fallback
  (`decompiled/XRL.Core/ActionManager.cs:838`,
  `decompiled/XRL.Core/ActionManager.cs:1797-1808`).

## Inherited Locks (Do NOT Touch)

- `decision_input.v1` field set is locked:
  `Player.{Hp,MaxHp,Pos}`, `Adjacent.{HostileDir,HostileId,BlockedDirs}`,
  `Recent.{LastActionTurn,LastAction,LastDir,LastResult}`, `Turn`
  (`docs/memo/phase-0-g-exit-2026-04-27.md:167-173`,
  `mod/LLMOfQud/IDecisionPolicy.cs:12-41`). Adding fields is
  `decision_input.v2` + ADR territory.
- `decision.v1` is locked: top-level keys `{turn, schema, input_summary, intent,
  action, dir, reason_code, error}`; intent enum `{attack, escape, explore}`;
  action enum `{Move, AttackDirection}`
  (`docs/memo/phase-0-g-exit-2026-04-27.md:175-180`,
  `mod/LLMOfQud/SnapshotState.cs:938-947`).
- `IDecisionPolicy.Decide` is input-only and must not read CoQ APIs directly
  (`mod/LLMOfQud/IDecisionPolicy.cs:58-64`,
  `docs/memo/phase-0-g-exit-2026-04-27.md:157-165`).
- `command_issuance.v1` remains locked. Field additions or order changes require
  v2 + ADR (`docs/memo/phase-0-f-exit-2026-04-26.md:71`,
  `mod/LLMOfQud/SnapshotState.cs:841-917`).
- `PreventAction = true` is only Layer 4 abnormal-energy defense, not normal
  autonomy. Success path must leave it false so `CommandTakeActionEvent.Check`
  returns true and the render fallback remains reachable
  (`docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md:71-92`,
  `mod/LLMOfQud/LLMOfQudSystem.cs:583-608`).
- Render fallback at `decompiled/XRL.Core/ActionManager.cs:1806-1808` is
  load-bearing for the per-turn `[screen]/[state]/[caps]/[build]` flush
  (`docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md:148-162`).
- Adjacent hostile scan priority is `N → NE → E → SE → S → SW → W → NW`
  (`docs/memo/phase-0-f-exit-2026-04-26.md:66`,
  `mod/LLMOfQud/LLMOfQudSystem.cs:310-323`).
- JSON null-discipline helpers are inherited. Use `AppendJsonStringOrNull` and
  `AppendJsonIntOrNull`; do not inline ad hoc null emission
  (`mod/LLMOfQud/SnapshotState.cs:84-110`).
- Anti-degeneracy thresholds remain boundary-integrity sanity checks, not
  exploration-quality gates: `pass_turn_fallback_rate ≤ 20%`,
  `successful_terminal_action_rate ≥ 70%`, and at least two intents across the
  five-run trace (`docs/memo/phase-0-g-exit-2026-04-27.md:202-211`,
  `docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md:89-114`).
- "Harness, not bot" remains the scope frame. `HeuristicPolicy` exploration
  quality is a non-goal; Phase 1 may rely on LLM reasoning or introduce a
  System-layer safety-net only under a new ADR
  (`docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md:81-136`).

## 1. Minimum PR-1 Scope Decision

### Option A: 1-A + `WebSocketPolicy : IDecisionPolicy` Only

Tasks included:

- Implement the C# WebSocket client and Python WebSocket server enough to carry
  `DecisionInput` to Python and return `Decision`.
- Add `WebSocketPolicy : IDecisionPolicy` behind the existing
  `BuildDecisionInput → Decide → Execute` flow.
- Keep `decision_input.v1` and `decision.v1` unchanged.
- Defer the v5.9 `tool_call` / `tool_result` envelope, reconnect, timeout,
  telemetry DB, Codex auth, ToolRouter, and terminal-action idempotency.

What it proves:

- The Phase 0-G boundary is genuinely replaceable by an out-of-process policy.
- Serialization of the locked DTOs is sufficient for a remote decision.
- The existing direct `Move` / `AttackDirection` execution path still works after
  the decision source changes. Current execution uses `GameObject.Move(...)` and
  `GameObject.AttackDirection(...)`
  (`decompiled/XRL.World/GameObject.cs:15719-15723`,
  `decompiled/XRL.World/GameObject.cs:17882-17903`).

What it leaves untested:

- v5.9 Phase 1 exit criterion "Python → tool call → C# → result → Python"
  (`docs/architecture-v5.md:2862-2864`).
- Unified `tool_call` / `tool_result` envelope semantics
  (`docs/architecture-v5.md:2399-2424`).
- `session_epoch`, `message_id`, stale epoch rejection, `action_nonce`, and
  `state_version` guards (`docs/architecture-v5.md:2624-2675`).
- Disconnect behavior, timeout behavior, and streaming-visible recovery.
- Any Python-side module boundaries beyond `app.py`.

Friction with v5.9:

- High if PR-1 is expected to be a spec-conformant Phase 1 slice. v5.9 describes
  tool calls, not a direct `decision_input.v1 → decision.v1` WebSocket RPC.
- Low if PR-1 is explicitly framed as a boundary spike before Phase 1 proper.
- If accepted as Phase 1 scope, likely ADR-required: "Phase 1 PR-1 may prove
  the `IDecisionPolicy` bridge before implementing the v5.9 tool envelope."

### Option B: 1-A + 1-B + 1-F

Tasks included:

- Implement WebSocket bridge.
- Implement the unified `tool_call` / `tool_result` envelope shape from v5.9.
- Add timeout, reconnect/error handling, and disconnected fallback posture.
- Keep Codex auth and SQLite telemetry out.
- Keep terminal-action idempotency either absent or explicitly partial.

What it proves:

- The actual v5.9 wire shape can round-trip between Python and C#.
- Basic tool-call latency can be measured against the Phase 1 `<100ms` no-LLM
  exit target (`docs/architecture-v5.md:2862-2864`).
- Error handling is exercised before Phase 2 LLM latency and provider failures
  make diagnosis harder.

What it leaves untested:

- Codex auth and provider client paths.
- SQLite persistence and structured telemetry.
- Full terminal-action idempotency if 1-G is not included.
- Whether `WebSocketPolicy : IDecisionPolicy` and the v5.9 tool-loop model are
  the same abstraction or two parallel abstractions. v5.9 says Python sends
  terminal actions as tool calls (`docs/architecture-v5.md:2475-2506`);
  Phase 0-G says Python can replace only `Decide` and let C# execute.

Friction with v5.9:

- Moderate. This option aligns better with v5.9 than Option A, but if it omits
  1-G it does not satisfy the Phase 1 "promoted from 2b" idempotency work
  required before Phase 2a Gate 1 (`docs/architecture-v5.md:2847-2861`).
- It may still need an ADR if PR-1 deliberately ships without 1-G while calling
  itself a Phase 1 implementation slice.

### Option C: Boundary-First Bridge Plus Explicit Failure Semantics

Tasks included:

- Implement 1-A with `WebSocketPolicy : IDecisionPolicy`.
- Carry `decision_input.v1` and `decision.v1` over WebSocket as the PR-1
  application payload.
- Add only the envelope fields needed for operational safety:
  `message_id`, `session_epoch`, timeout classification, and fallback reason.
- Include 1-F-style timeout/disconnect fallback to `HeuristicPolicy`.
- Defer full 1-B tool envelope, 1-C auth, 1-D SQLite, 1-E ToolRouter, and 1-G
  terminal-action idempotency to follow-up Phase 1 sub-PRs.
- Name the PR as "Phase 1 readiness bridge" rather than "Phase 1 complete."

What it proves:

- The real inherited boundary survives process crossing.
- Timeout/disconnect posture is empirically tested before the implementation
  depends on provider latency.
- It creates a small surface for the required async/threading probes.

What it leaves untested:

- Full v5.9 tool envelope and ToolRouter.
- Python-driven terminal action tool calls.
- Codex auth, SQLite, and full idempotency.
- Whether Phase 2 will use `WebSocketPolicy` directly or pivot to Python
  `tool_call` terminal actions.

Friction with v5.9:

- Moderate to high, but explicit. It acknowledges that Phase 0-G created a
  narrower boundary than the v5.9 Phase 1 tool envelope.
- Almost certainly ADR-required if adopted: it amends the Phase 1 implementation
  sequence without editing the frozen spec.

## 2. Engine-Speed Autonomy Throttle Placement

Phase 0-F observed that autonomous dispatch can traverse four zones in seconds
of wall time (`docs/memo/phase-0-f-exit-2026-04-26.md:73-78`). Phase 0-G
inherits this hazard (`docs/memo/phase-0-g-exit-2026-04-27.md:293-301`).

Engine constraints:

- `ActionManager` loops while actor energy is `>= 1000`
  (`decompiled/XRL.Core/ActionManager.cs:800-838`).
- If the player still has enough energy after `CommandTakeActionEvent`, the
  engine enters the player branch and may call `PlayerTurn()`
  (`decompiled/XRL.Core/ActionManager.cs:838`,
  `decompiled/XRL.Core/ActionManager.cs:1797-1799`).
- If energy is below 1000, the player render fallback runs
  (`decompiled/XRL.Core/ActionManager.cs:1806-1808`).
- `RenderBase()` pumps `gameQueue` when called on the core thread, then renders
  and draws buffers (`decompiled/XRL.Core/XRLCore.cs:2517-2582`).
- After-render callbacks fire from render buffer generation
  (`decompiled/XRL.Core/XRLCore.cs:2347-2351`,
  `decompiled/XRL.Core/XRLCore.cs:2422-2426`).

Options:

- Python-side artificial sleep / pacing:
  - Keeps C# simple.
  - Naturally matches the remote-policy boundary.
  - Does not protect against a local fallback `HeuristicPolicy` running at
    engine speed after disconnect.
  - Needs a policy: sleep before responding, after responding, or only after
    accepted terminal actions.
- C#-side render-tick synchronization in `BeginTakeActionEvent`:
  - Ensures even fallback/local policy is human-observable.
  - Risks reintroducing a wait in the game-thread path that Phase 0-F avoided.
  - Needs careful proof that it does not disturb the BTA/CTA energy sequence.
    BTA runs before the inner action loop gate
    (`decompiled/XRL.Core/ActionManager.cs:786-800`); CTA is inside the loop
    (`decompiled/XRL.Core/ActionManager.cs:829-832`).
- Natural rate-limiting via LLM decision latency:
  - Likely true once real Codex calls are in the loop.
  - Not true for no-LLM PR-1, echo policies, local test policies, or fallback
    `HeuristicPolicy`.
  - Makes stream pacing depend on provider behavior rather than a harness
    contract.
- Hybrid:
  - Python sets the normal minimum cadence.
  - C# has a hard maximum command rate only when the policy is local/fallback or
    when Python responds too fast.
  - More complex, but separates "viewer pacing" from "provider latency."

The load-bearing choice is whether Phase 1 wants a deterministic harness pacing
contract before LLM integration, or whether it accepts provider latency as the
first real throttle.

## 3. Threading Contract for Async `Decide`

Current `IDecisionPolicy.Decide` is synchronous
(`mod/LLMOfQud/IDecisionPolicy.cs:61-64`). Turning it into a WebSocket roundtrip
touches CoQ's thread queues:

- `GameManager` owns separate `uiQueue` and `gameQueue`
  (`decompiled/GameManager.cs:142-144`).
- `ThreadTaskQueue.awaitTask` queues work to another thread and blocks with
  `WaitOne()` unless already on that queue's thread
  (`decompiled/QupKit/ThreadTaskQueue.cs:135-155`).
- `ThreadTaskQueue.executeAsync` returns a `Task` without blocking the caller
  (`decompiled/QupKit/ThreadTaskQueue.cs:77-100`).
- `uiQueue.executeTasks()` is pumped from `GameManager`
  (`decompiled/GameManager.cs:2837-2842`).
- Popups use `uiQueue.awaitTask(...)` and then wait on a completion task
  (`decompiled/XRL.UI/Popup.cs:823-909`).
- v5.9 explicitly warns not to call `awaitTask()` from a thread that the target
  queue needs in order to drain (`docs/architecture-v5.md:1778-1804`).

Threading options:

- Blocking await with timeout + fallback:
  - Shape: CTA calls `WebSocketPolicy.Decide`, blocks up to TIMEOUT_MS, then
    falls back to `HeuristicPolicy`.
  - Deadlock risk: if Python asks C# for a tool during that same decision and
    the request needs `gameQueue` or `uiQueue`, the game thread may be blocked
    waiting for Python while Python waits for a queue that cannot drain.
  - Schema impact: can stay at `decision_input.v1` / `decision.v1` if timeout
    metadata is envelope-only or log-only.
  - Probe required before lock: whether O(100ms) blocking preserves render
    fallback and AutoAct/keyboard behavior.
- Pre-fetched decision:
  - Shape: BTA builds/sends the next `DecisionInput`, CTA consumes a completed
    decision or falls back.
  - Deadlock risk: lower for network latency, but BTA timing must be proven
    equivalent enough for the DTO. BTA fires before the inner loop; CTA fires
    inside it (`decompiled/XRL.Core/ActionManager.cs:786-832`).
  - Schema impact: no DTO bump if the input fields remain identical. May need
    envelope `request_id` / `state_version` to reject stale prefetches.
- ThreadTaskQueue routing:
  - Shape: WebSocket thread receives tool requests and routes C# reads/actions
    through `gameQueue.executeAsync` or `uiQueue.executeAsync`, matching the v5.9
    queue table (`docs/architecture-v5.md:1787-1794`).
  - Deadlock risk: low if no caller blocks the queue it needs; high if
    `awaitTask()` is used from the wrong side.
  - Schema impact: stays at v1 for `DecisionInput`, but tool results need the
    v5.9 envelope if this is more than a decision RPC.
- Continuation pattern:
  - Shape: CTA starts a WebSocket request, returns immediately, and a later
    continuation executes the decision through a queue.
  - Deadlock risk: lower, but behavioral risk is highest. Executing
    `Move`/`AttackDirection` outside the CTA loop may not preserve the same
    energy, `EndActionEvent`, hostile-interrupt, and render-fallback semantics.
  - Schema impact: likely ADR-worthy even if the DTO is unchanged, because it
    changes the execution timing contract. If extra state is needed to prove
    the continuation is still current, that becomes a schema/envelope decision.

## 4. Disconnect / Fail-Open Posture

### Fallback to `HeuristicPolicy`

Pros:

- Preserves the Phase 0-G boundary and keeps the game advancing.
- Avoids a stream dead zone if Python dies.
- Gives a deterministic local recovery path.

Cons:

- Local heuristic can run at engine speed unless throttled.
- Exploration quality is explicitly a non-goal; fallback may visibly oscillate
  in known patterns (`docs/memo/phase-0-g-exit-2026-04-27.md:254-267`,
  `docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md:81-136`).
- If fallback actions are not clearly labeled, telemetry may blur LLM agency vs.
  harness agency.

### Pause via `supervisor_request`

Pros:

- Aligns with v5.9's human-in-the-loop non-tool message concept:
  `supervisor_request` / `supervisor_response` are standalone messages, not
  tool envelopes (`docs/architecture-v5.md:2421-2424`).
- Safer for survival than blind local exploration in dangerous state.

Cons:

- If the WebSocket is disconnected, C# cannot rely on Python receiving the
  request until reconnect.
- A pause conflicts with the streaming rule that detection must happen well
  before 30 seconds of silence (`docs/architecture-v5.md:1897-1901`).
- Requires UI/overlay semantics that may not exist in PR-1.

### Explore, Do Not Act

Pros:

- Conservative with respect to player survival if implemented as no terminal
  action, or as pass/wait only.
- Makes disconnect obvious.

Cons:

- A CTA handler still has to preserve the energy-drain/autonomy invariant.
  Current fallback uses `PassTurn()` only as engine bookkeeping after failed
  terminal action (`mod/LLMOfQud/LLMOfQudSystem.cs:489-505`).
- Repeated pass/wait may kill the character if hostile or environmental damage
  is present.
- It risks being the worst streaming behavior: no visible agency and no useful
  recovery.

## 5. Empirical Claim Probes Before Spec / Plan Lock

Probe 1: Blocking WebSocket wait on CTA.

- Claim: the game thread can safely wait O(100ms) for a remote `Decision`
  without breaking render cadence or action-loop semantics.
- Minimal probe: 100 turns with Python sleeping 0ms, 50ms, 100ms, 250ms before
  returning a fixed decision.
- Observable: `[decision]`, `[cmd]`, `[screen]`, `[state]`, `[caps]`, `[build]`
  counts by turn; no missing render fallback; no keyboard prompt.
- Expected: one `[decision]` and one `[cmd]` per CTA; observation channels remain
  correlated by turn.
- Failure signature: `[cmd]` advances while render channels stall, game freezes,
  or `PlayerTurn()` waits for input.

Probe 2: Timeout fallback preserves energy drain.

- Claim: timed-out `WebSocketPolicy.Decide` can fall back to `HeuristicPolicy`
  without corrupting energy or setting `PreventAction` on success.
- Minimal probe: Python sleeps beyond timeout for 50 turns.
- Observable: fallback-labeled `[decision]`, `[cmd]` with `energy_after < 1000`
  or accepted negative energy; render fallback still flushes.
- Expected: no `PreventAction` except abnormal-energy catch path.
- Failure signature: render cadence collapses, repeated stale decisions, or
  engine waits for keyboard.

Probe 3: Disconnect mid-`Decide`.

- Claim: socket close while CTA is waiting does not double-execute, skip drain,
  or corrupt recent/blocked-dir memory.
- Minimal probe: Python accepts a request, closes connection before response,
  repeated over 20 turns.
- Observable: exactly one `[decision]` and one `[cmd]` per turn, fallback reason
  marks disconnect, blocked-dir memory still updates only after failed Move with
  `fallback == "pass_turn"` (`mod/LLMOfQud/LLMOfQudSystem.cs:259-299`).
- Expected: no duplicate terminal actions.
- Failure signature: same turn has two `[cmd]` lines, no `[cmd]`, or stale
  decision applied after reconnect.

Probe 4: Continuation execution, if considered.

- Claim: `Move` / `AttackDirection` from a continuation or queued task preserves
  the same semantics as execution inside CTA.
- Minimal probe: compare 20 direct CTA actions against 20 queued-continuation
  actions in the same location.
- Observable: `EndActionEvent` side effects if instrumented, energy drain,
  render fallback, `[cmd]` timing.
- Expected: parity with current CTA behavior.
- Failure signature: action happens outside the turn loop, energy remains
  `>= 1000`, render fallback misses, or command telemetry no longer correlates.

Probe 5: Tool-call queue routing.

- Claim: a Python-originated tool request can safely read game state via
  `gameQueue.executeAsync` while the game loop continues, and UI choices can be
  routed to `uiQueue` without deadlock.
- Minimal probe: issue `inspect_surroundings` during idle, combat, and a popup;
  for popup, route only a benign read first.
- Observable: request completes, no modal freeze, queue tasks drain.
- Expected: game reads return from `gameQueue`; popup/UI paths do not call
  `awaitTask()` from a blocking context.
- Failure signature: Python waits forever, popup freezes, or game thread blocks
  with `uiQueue` pending.

Probe 6: Render fallback under slow decisions.

- Claim: if `Decide` takes longer than one render frame, `ActionManager` still
  reaches the render fallback after the action drains energy.
- Minimal probe: 60 turns at 200ms artificial decision latency.
- Observable: wall-clock cadence, per-turn render channels, no after-render
  backlog.
- Expected: each completed decision has exactly one action and one observation
  set.
- Failure signature: observations bunch after many turns or disappear until
  death/quit.

Probe 7: Session epoch / duplicate handling, if included in PR-1.

- Claim: stale responses from an old connection are ignored.
- Minimal probe: Python sends a late response after C# has advanced
  `session_epoch`.
- Observable: no stale decision applied; fallback or fresh decision wins.
- Expected: old epoch rejected or logged.
- Failure signature: old decision executes after reconnect.

Probe 8: Reconnect wake mechanism (REQUIRED — added by sealed decision Q3=pause).

- Claim: when `WebSocketPolicy.Decide` is replaced by a pause-on-disconnect
  posture, the engine will block at `PlayerTurn()` waiting for keyboard input
  (CoQ native idle behavior, `decompiled/XRL.Core/ActionManager.cs:1797-1799`
  for the player branch where input is awaited), and on WebSocket reconnect a
  wake signal must un-block the engine without corrupting energy or duplicating
  actions.
- Minimal probe: hold the WebSocket disconnected for 30+ seconds, observe the
  engine enters keyboard-wait, reconnect, observe whether (a) engine resumes
  spontaneously without intervention, (b) engine requires `Keyboard.PushKey`
  injection to resume, or (c) engine requires a different unblock mechanism.
- Observable: wall-clock time between reconnect and the next
  `BeginTakeActionEvent` fire; presence of stale `[decision]` / `[cmd]` line on
  resume; energy value at resume vs. at disconnect.
- Expected: engine resumes within one render frame after the chosen wake
  mechanism, no stale action applied, energy unchanged from pre-pause state.
- Failure signature: engine never resumes without manual key press, or resumes
  with stale decision applied, or energy corruption (e.g. energy < 1000 without
  an action having been taken).

## 6. 1-C Codex Auth and 1-D SQLite Telemetry Placement

Codex auth options:

- PR-1:
  - Pros: validates the eventual Phase 2 provider path early.
  - Cons: does not help prove the C# ↔ Python boundary; adds secrets/device-flow
    complexity before threading and failure semantics are known.
- Later Phase 1 sub-PR:
  - Pros: keeps PR-1 focused, but lands before Phase 2 LLM integration.
  - Cons: Phase 1 completion still waits on it if v5.9 task list is read
    strictly (`docs/architecture-v5.md:2840-2847`).
- Phase 2a:
  - Pros: auth appears exactly when real provider calls are needed.
  - Cons: deviates from v5.9 Phase 1 task ordering and likely needs ADR if
    formally moved.

SQLite telemetry options:

- PR-1:
  - Pros: useful for debugging reconnect and timeout probes.
  - Cons: persistence schema churn before message scope is settled.
- Later Phase 1 sub-PR:
  - Pros: after envelope/fallback choices are known, schema can record stable
    facts instead of guesses.
  - Cons: early probes rely on Player.log and Python logs only.
- Phase 2a:
  - Pros: defers all DB work until LLM behavior creates enough telemetry volume
    to justify it.
  - Cons: weakens Phase 1 observability and may make reconnect bugs harder to
    diagnose.

Against the ADR 0009 / 0010 "minimum to prove the boundary" principle, both
1-C and 1-D are non-essential for PR-1 unless the user decides PR-1 must be
spec-conformant Phase 1 rather than a bridge-readiness slice.

## Anticipated ADR Triggers

Candidate ADRs, subject to user decision:

- ADR 0011: Phase 1 PR-1 scope (boundary + auth + telemetry, deferring tool
  envelope and idempotency to PR-2/PR-3).
  - Trigger: choosing the sealed PR-1 scope instead of implementing the full
    v5.9 Phase 1 task list in one PR.
  - Likely PR marker: `Amend v5.9`.
- ADR 0012: Async `IDecisionPolicy.Decide` threading contract.
  - Trigger: blocking wait, prefetch, queue routing, or continuation semantics
    become the durable implementation model.
- ADR 0013: Disconnect = pause posture and reconnect-wake mechanism.
  - Trigger: formalizing no-dispatch disconnect behavior, CoQ native idle as the
    pause absorber, and the Probe 8 reconnect wake mechanism.
- ADR 0014: Pacing / autonomy throttle.
  - Trigger: deferred from PR-1 to PR-2 unless PR-1 telemetry forces an earlier
    decision.

## Sealed Decisions — 2026-04-27

The following decisions were sealed by the user on 2026-04-27 during the Phase 1
readiness scoping conversation. They supersede the Open Questions section that
previously occupied this slot.

| Decision | Choice | Implication |
|----------|--------|-------------|
| Q1 PR-1 scope | MVP boundary proof (Option A) | PR-1 = 1-A + WebSocketPolicy:IDecisionPolicy + 1-C + 1-D + pause posture; defer 1-B/1-E/1-F-full/1-G to follow-up Phase 1 PRs |
| Q2 supervisor_request placement | Phase 1 follow-up sub-PR (not PR-1) | PR-2 will introduce supervisor_request and supervisor_response message handling alongside 1-B tool envelope |
| Q3 Disconnect fallback | pause (wait for recovery), no HeuristicPolicy continuation | WebSocketPolicy on disconnect dispatches no Decision; CoQ native idle (PlayerTurn keyboard wait) absorbs the pause; reconnect-wake mechanism (Probe 8) required |
| Q4 1-C Codex auth and 1-D SQLite telemetry | included in PR-1 | PR-1 must implement device_flow / token_store / broker and the SQLite tables even though no LLM call is made yet; trade-off: larger PR-1 surface, but auth and telemetry plumbing land before Phase 2a debugging benefits from them |
| Q5 FindPath System-layer safety-net | deferred to Phase 2a or later | Phase 1 will not introduce CoQ pathfinder integration; LLM screen reasoning owns exploration quality per ADR 0010 |

### Phase 1 PR Structure (Inherited from Sealed Decisions)

```text
PR-1 (boundary + plumbing):
  - 1-A WebSocket bridge (BrainClient.cs ↔ app.py)
  - WebSocketPolicy : IDecisionPolicy
  - 1-C Codex auth (device_flow, token_store, broker)
  - 1-D SQLite telemetry tables
  - Disconnect = pause posture (no HeuristicPolicy fallback)
  - Reconnect-wake mechanism (Probe 8 result drives the choice)
  - Latency target: < 100ms round-trip with no-LLM canned Python policy
  Required ADRs: 0011 (PR-1 scope), 0012 (async Decide threading), 0013 (pause + reconnect)

PR-2 (envelope + ops):
  - 1-B Tool call message format (request/response, v5.9 envelope)
  - 1-E ToolRouter.cs
  - 1-F Error handling and retry infrastructure (full)
  - supervisor_request / supervisor_response message handling
  Required ADRs: pacing/throttle decision if not already locked in PR-1

PR-3 (idempotency, Phase 2a Gate 1 prerequisite):
  - 1-G Terminal-action idempotency
    (action_nonce + state_version + session_epoch + cached duplicate result)
  Required ADRs: none (v5.9 spec carries the contract)

→ Phase 2a opens here; LLM is connected via Codex auth from PR-1.
```

PR-1 round-trip uses a no-LLM canned Python policy. Round-trip latency at this
stage is dominated by network IO, not LLM inference, so pacing/throttle
observation in PR-1 is for telemetry only (1-D); pacing contract is sealed in
PR-2 if the no-LLM behavior shows engine running at full speed during the
boundary RPC.
