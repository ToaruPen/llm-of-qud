# ADR 0012: Phase 1 PR-1 plan hotfix — probe-set revision after Codex pre-probe second-opinion

Status: Accepted (2026-04-27)

Amend marker: Amend v5.9

## Context

PR #18 merged
`docs/superpowers/plans/2026-04-27-phase-1-pr-1-websocket-bridge.md`
with Task 1 Probes 1, 2, 3, 6, and 8. AGENTS.md Imperative #2 states
that `docs/superpowers/plans/*` are immutable without a new ADR under
`docs/adr/` (`AGENTS.md:18`). CodeRabbit's path instructions likewise
require any diff to `docs/superpowers/plans/**/*.md` to have a new ADR
entry that references the plan filename (`.coderabbit.yaml`
path_instructions).

Before any in-game probe ran, the orchestrator asked Codex for a
read-only second opinion. The resulting memo at
`docs/memo/phase-1-pr-1-probe-codex-second-opinion-2026-04-27.md`
surfaced one direct contradiction between the merged Probe 3 and ADR
0011 §Q3 disconnect=pause posture, plus four additional load-bearing
claims and three risks that the Plan §Risks did not name.

The contradiction is mechanical, not stylistic. The merged Probe 3
expected exactly one `[decision]` and one `[cmd]` per turn after socket
close, which validates continued autonomous action. ADR 0011 §Q3 sealed
the opposite: socket disconnect dispatches no `Decision`; CoQ native
idle absorbs the pause at `PlayerTurn`. In the engine loop,
`CommandTakeActionEvent.Check` continues only when the handler returns
true and `PreventAction` remains false
(`decompiled/XRL.World/CommandTakeActionEvent.cs:37-39`). If the
player keeps energy `>= 1000`, the ActionManager player branch is
entered (`decompiled/XRL.Core/ActionManager.cs:838`) and, on the core
thread, calls `The.Core.PlayerTurn()`
(`decompiled/XRL.Core/ActionManager.cs:1797-1799`). A disconnect probe
that emits a `[decision]` and `[cmd]` therefore proves the wrong
posture for ADR 0011 §Q3.

The Codex consultation also pre-empted the Phase 0-F failure pattern
recorded in ADR 0007: a load-bearing design was locked before the
empirical probe invalidated it, forcing a mid-implementation ADR to
correct the mechanics. PR-1 should not repeat that pattern when the
contradiction is already visible from static reading.

## Decision

Amend only the Plan's Task 1 probe set and risk list. ADR 0011 sealed
Q1-Q5 stand untouched.

Plan changes:

1. **Pre-Probe Step: Compile-time `ClientWebSocket` availability
   sanity.**
2. **Probe 3 split into 3a + 3b.** Probe 3a keeps timeout fallback
   expectations; Probe 3b validates disconnect mid-Decide enters pause.
3. **Probe A added.** Probe A covers BTA / CTA bypass timing if Probe
   8 option (i) is ever exercised.
4. **Probe D added.** Probe D validates save/load lifecycle for the
   WebSocket bridge state.
5. **Probe 8 narrowed to (iv) primary + (ii) fallback.** Option (i) is
   not tested unless both higher-priority options fail; option (iii) is
   rejected.
6. **Probe E added.** Probe E validates wake-key innocuousness if Probe
   8 chooses option (iv).
7. **Sequencing recommendation added.** Run Compile-sanity -> 1 -> 6
   -> 2 -> 3a -> 3b -> A -> D -> 8(iv) -> E in one primary CoQ launch,
   with one recovery launch reserved for save/load split or 8(iv)
   failure.
8. **§Risks gains 3 entries.** Add C# WebSocket assembly availability,
   bridge runtime save/load serialization, and startup race between CoQ
   mod load and Python server readiness.

Because this ADR takes the next commit-order ADR number, ADR 0011's
future reservations shift:

- Future async `IDecisionPolicy.Decide` threading contract:
  ADR 0012 -> ADR 0013.
- Future disconnect=pause plus reconnect wake contract:
  ADR 0013 -> ADR 0014.

## Alternatives Considered

1. **Roll back PR #18 and re-issue with the corrections.** Rejected:
   it loses the orchestration-mode plus Codex-delegate workflow
   precedent already merged.
2. **Leave the Probe 3 contradiction in place and address it as a
   mid-flight ADR per ADR 0007.** Rejected: the contradiction is now
   visible from static reading, and re-correcting after probe-phase
   failure costs more than fixing now.
3. **Defer the additional probes A, D, and E to PR-1.1
   implementation.** Rejected: Probe D specifically validates the
   `[Serializable]` save/load lifecycle, which is load-bearing for
   PR-1.1 design. `IGameSystem` is `[Serializable]`
   (`decompiled/XRL/IGameSystem.cs:11-12`), CoQ writes systems on save
   (`decompiled/XRL/XRLGame.cs:1573-1582`), and calls `AfterLoad` after
   read (`decompiled/XRL/XRLGame.cs:1818-1821`).

## Consequences

Easier:

- The Plan is internally consistent with ADR 0011 §Q3 before any
  in-game probe runs.
- The Phase 0-F-style "discover contradiction during empirical run"
  risk is reduced for PR-1.

Harder:

- ADR 0011's forward references to "ADR 0012 / 0013" shift to
  "ADR 0013 / 0014". This PR handles that renumbering in ADR 0011 and
  the Plan.

Re-open triggers:

- If Probe 3b empirically falsifies the disconnect=pause posture
  (i.e. CoQ engine cannot enter a clean keyboard-wait idle from a
  CTA-thrown `DisconnectedException` with energy intact), ADR 0014
  (disconnect=pause / reconnect wake) may need to revisit ADR 0011 §Q3.

## Supersedes

None. This ADR is additive; ADR 0011 sealed Q1-Q5 stand untouched.

## Related Artifacts

- `docs/superpowers/plans/2026-04-27-phase-1-pr-1-websocket-bridge.md`
  — the amended Plan.
- `docs/memo/phase-1-pr-1-probe-codex-second-opinion-2026-04-27.md`
  — full Codex consultation captured verbatim.
- `docs/memo/phase-1-readiness-brainstorm-2026-04-27.md` — original
  sealed-decisions memo.
- `docs/adr/0011-phase-1-pr-1-scope.md` — sealed PR-1 scope; forward
  references renumbered by this ADR.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md`
  — probe-before-lock precedent.
- `AGENTS.md:18` — Imperative #2 mandating ADR for plan diffs.
- `.coderabbit.yaml` path_instructions — plan-filename
  cross-reference rule.
