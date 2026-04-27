# ADR 0011: Phase 1 PR-1 scope — boundary-first slice with auth and telemetry plumbing

Status: Accepted (2026-04-27)

Amend marker: Amend v5.9

## Context

Architecture v5.9 is frozen by ADR 0001; the spec is not edited for
Phase 1 sequencing changes. The frozen Phase 1 task list presents 1-A
through 1-G as one phase: WebSocket bridge, tool-call message format,
Codex auth, SQLite telemetry, ToolRouter, error/retry infrastructure,
and terminal-action idempotency (`docs/architecture-v5.md:2836-2864`).

Phase 0-G then locked a narrower implementation boundary that Phase 1
inherits: `BuildDecisionInput -> Decide -> Execute`, with
`IDecisionPolicy.Decide(DecisionInput) -> Decision` as the replaceable
policy point (`docs/memo/phase-0-g-exit-2026-04-27.md:155-230`,
`mod/LLMOfQud/IDecisionPolicy.cs:58-64`). Phase 1 does not need to
rewrite `BuildDecisionInput` or `Execute` to prove the first
out-of-process policy.

Implementing every v5.9 Phase 1 item as one PR is too large for the
repo's current cadence. Phase 0-G alone needed three ADRs and more than
five review rounds before its boundary contract stabilized. The
user-driven 2026-04-27 readiness scoping conversation therefore sealed
five decisions in
`docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` §Sealed
Decisions.

ADR 0007 is the recent cautionary precedent: an empirical probe
falsified load-bearing assumptions about `PreventAction`, energy drain,
and render fallback, so the design had to be corrected by a mid-
implementation ADR before acceptance could be trusted. Phase 1 PR-1 has
the same class of load-bearing claims around async `Decide`, game-thread
blocking, disconnect pause, and reconnect wake. Those claims must be
probed before ADR 0012 / ADR 0013 lock the durable mechanics.

## Decision

Adopt the sealed 2026-04-27 PR cascade:

1. **Q1 PR-1 scope: MVP boundary proof (Option A).** PR-1 implements
   1-A WebSocket bridge, `WebSocketPolicy : IDecisionPolicy`, 1-C
   Codex auth scaffolding, 1-D SQLite telemetry scaffolding,
   disconnect=pause posture, and reconnect-wake plumbing. It defers
   1-B, 1-E, full 1-F, and 1-G.
2. **Q2 supervisor_request placement: Phase 1 follow-up sub-PR.**
   PR-2 introduces `supervisor_request` /
   `supervisor_response` alongside the v5.9 tool envelope; PR-1 does
   not send supervisor messages.
3. **Q3 disconnect fallback: pause, no `HeuristicPolicy`
   continuation.** On disconnect, `WebSocketPolicy` dispatches no
   `Decision`; CoQ native idle absorbs the pause at `PlayerTurn`
   (`decompiled/XRL.Core/ActionManager.cs:1797-1799`). Probe 8
   determines the reconnect-wake mechanism.
4. **Q4 1-C Codex auth and 1-D SQLite telemetry: included in PR-1.**
   PR-1 creates `device_flow`, `token_store`, `broker`, SQLite schema,
   and writer scaffolding even though no real LLM call is made.
5. **Q5 FindPath System-layer safety-net: deferred to Phase 2a or
   later.** Phase 1 does not introduce CoQ pathfinder integration.
   LLM screen reasoning remains responsible for exploration quality per
   ADR 0010.

The resulting Phase 1 structure is:

```text
PR-1 (boundary + plumbing):
  - 1-A WebSocket bridge (BrainClient.cs <-> app.py)
  - WebSocketPolicy : IDecisionPolicy
  - 1-C Codex auth (device_flow, token_store, broker)
  - 1-D SQLite telemetry tables
  - Disconnect = pause posture (no HeuristicPolicy fallback)
  - Reconnect-wake mechanism (Probe 8 result drives the choice)
  - Latency target: <100ms round-trip with no-LLM canned Python policy
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

Phase 2a opens here; LLM is connected via Codex auth from PR-1.
```

ADR 0012 (async `IDecisionPolicy.Decide` threading contract) and
ADR 0013 (disconnect=pause plus reconnect wake) will land later:
either in this readiness sequence if Task 1 probe results arrive
cleanly, or as mid-flight ADRs in PR-1.1 using the ADR 0007 pattern.

## Alternatives Considered

1. **Option B: 1-A + 1-B + 1-F in one PR.** This better aligns with
   the v5.9 communication-protocol section, but it leaves Codex auth,
   SQLite telemetry, and 1-G unresolved while still forcing the review
   to cover both thread mechanics and the tool envelope. It also
   defers the telemetry that would help diagnose reconnect and timeout
   failures.
2. **Option C: larger Phase 1 readiness bridge.** This would include
   boundary proof plus explicit timeout / reconnect semantics and some
   envelope safety fields. It was useful as a framing option, but the
   sealed Q4 decision explicitly pulls 1-C and 1-D into PR-1 while Q2
   and Q3 keep supervisor and runtime fallback out.
3. **No pivot: implement v5.9 Phase 1 strictly as one PR.** Rejected
   because it combines 1-A through 1-G into a review surface larger
   than recent Phase 0 practice can support. It would also lock async
   and pause mechanics before the required empirical probes complete.

See `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` §1 for the
full trade-off treatment.

## Consequences

Easier:

- Phase 0-G boundary integrity survives PR-1. `WebSocketPolicy`
  replaces only `IDecisionPolicy`; `BuildDecisionInput` and `Execute`
  stay load-bearing.
- Review surface stays manageable by phase: boundary and plumbing in
  PR-1, envelope and ops in PR-2, idempotency in PR-3.
- Codex auth and SQLite plumbing land before Phase 2a needs them for
  real provider debugging.
- Pause posture aligns with CoQ-native idle: if player energy remains
  high after no autonomous action, `ActionManager` reaches
  `PlayerTurn()` (`decompiled/XRL.Core/ActionManager.cs:838,1797-1799`).

Harder:

- 1-G idempotency lands later, so PR-1 must avoid pretending to be the
  full Phase 1 completion gate.
- No real Codex API call is exercised in PR-1; auth fragility may
  surface only in Phase 2a.
- SQLite schema may churn between PR-1 and PR-2 when the v5.9 envelope
  becomes authoritative.

Re-open triggers:

- If Task 1 probes falsify blocking-await viability, ADR 0012 may
  supersede the implementation mechanics assumed by this scope.
- If Task 1 probes falsify pause or reconnect-wake viability, ADR 0013
  may supersede the disconnect posture or move pause mechanics to a
  different engine path.
- If PR-1 latency cannot meet `<100ms` with no LLM
  (`docs/architecture-v5.md:2862-2864`), PR-1 scope must be revisited
  before PR-2 opens.

## Forward-looking note for PR-2 (harness-core surfaces)

PR-2 introduces 1-B (tool call envelope), 1-E (`ToolRouter.cs`), and
the surfaces that Phase 2a+ prompt caching and provider continuation
will sit on. These are harness-core abstractions: once locked, they
propagate into every subsequent provider client, every overlay event,
and every telemetry row. The decision recorded here — for the PR-2
readiness phase, NOT for PR-1 — is that those surfaces require
explicit precedent research before any Plan or spec lock:

- The tool-call envelope shape MUST be surveyed against real precedent
  before locking: Anthropic Messages API `tool_use` blocks, OpenAI
  Responses API tool calling, the v5.9 envelope reference at
  `docs/architecture-v5.md:2364-2424`, and the current Codex Provider
  behavior. A naive copy of any single source will leak
  provider-specific assumptions into the harness.
- Prompt-caching strategy MUST be researched against provider-specific
  cache semantics: `previous_response_id` continuation, cache
  breakpoints, cache TTLs, and the `instructions` re-send rule
  (`docs/architecture-v5.md:2898-2901`). It must also be researched
  against the harness's own re-emission discipline: when the system
  prompt changes, when the build block changes, when notes change,
  and how those events interact with cache invalidation.
- The PR-2 readiness deliverable is expected to include a
  precedent-survey memo analogous to
  `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md`, produced
  BEFORE the PR-2 Plan or any subsequent ADR locks the envelope or
  caching shape. Codex delegate (advisor mode) is the right tool for
  the survey; the orchestrator-side reviewer is responsible for
  reconciling the survey against the v5.9 spec before lock.

This note is intentionally placed in ADR 0011 (and not deferred to a
PR-2 readiness ADR) so the rule is visible the moment PR-2 work begins
and cannot be silently skipped.

## Supersedes

None. This ADR is additive and partial-amends v5.9 Phase 1 sequencing;
it does not supersede prior ADRs.

## Related Artifacts

- `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` — sealed
  2026-04-27 PR-1 scope decisions and required probes.
- `docs/adr/0001-architecture-v5-9-freeze.md` — freezes v5.9 and
  prevents direct edits to `docs/architecture-v5.md`.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md`
  — probe-before-lock precedent for falsified implementation claims.
- `docs/adr/0009-phase-0-g-rescope-judgment-boundary.md` — locks the
  Phase 0-G judgment boundary that PR-1 crosses.
- `docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md`
  — keeps exploration quality and FindPath safety-net out of Phase 1
  PR-1.
- `docs/architecture-v5.md:2836-2864` — frozen Phase 1 task list and
  exit criterion.
- `docs/architecture-v5.md:1778-1804` — WebSocket thread routing and
  queue deadlock warning.
- `mod/LLMOfQud/IDecisionPolicy.cs:58-64` — input-only policy boundary.
