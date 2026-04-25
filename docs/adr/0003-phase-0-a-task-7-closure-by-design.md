# ADR 0003: Phase 0-A Task 7 closure by operational scope

Status: Accepted (2026-04-25)

## Context

Phase 0-A's plan
(`docs/superpowers/plans/2026-04-23-phase-0-a-mod-skeleton.md`) Task 7
required a delta-measurement acceptance for the **mid-session Mods-menu mod
toggle (OFF → ON)** path: re-register events without duplicate dispatch and
without missed events. The plan's acceptance criterion is a `delta == 2`
result against a baseline of 20 player turns at throttle=10
(`:586-670`).

The exit memo (`docs/memo/phase-0-a-exit-2026-04-23.md:117-143`) records
the criterion as **NOT MET**: the delta measurement against the toggle
path has never been performed. What HAS been verified, across Phase 0-A
Sessions B/C and Phase 0-B's 95-turn run, is the **fresh-process relaunch**
path — single load marker per launch, exact 10-action throttle spacing,
ERROR=0 over 95 turns. Fresh-process relaunch and mid-session toggle are
distinct execution paths; the former does not subsume the latter.

The architectural hazard the original plan worried about
(`XRLCore.RegisterOnBeginPlayerTurnCallback` having no duplicate guard at
`decompiled/XRL.Core/XRLCore.cs:576-579`) does not apply to our
implementation — we use `IPlayerSystem` whose `ApplyRegistrar` /
`ApplyUnregistrar` form a symmetric per-instance lifecycle
(`decompiled/XRL/IPlayerSystem.cs:9-33`). Phase 0-B added a static
`_afterRenderRegistered` guard for `RegisterAfterRenderCallback`
(`mod/LLMOfQud/LLMOfQudSystem.cs`), which closes the duplicate-registration
window inside one process even if the static field were preserved across an
in-process Roslyn assembly swap.

The **operational runtime model** is the deciding factor. The streaming
harness (architecture-v5.9, Phase 2+) launches CoQ once with a fixed mod
set and never toggles mods mid-session; the toggle path is non-applicable
to production operation. The user has confirmed this premise as the
governing assumption.

## Decision

Close Phase 0-A Task 7 as a **design-decision closure**, not an empirical
PASS. The acceptance criterion (`delta == 2` from in-game toggle
measurement) remains formally **not measured**. We are dropping it from the
open-acceptance list because:

1. The runtime contract for the streaming harness fixes mods at launch
   (`docs/architecture-v5.md` Phase 2+ operational model).
2. The structural mitigations are in place: `IPlayerSystem` symmetric
   lifecycle, static `_afterRenderRegistered` guard, `IsUnregister`-aware
   `RegisterPlayer` body.
3. Accumulated single-process evidence (Phase 0-A Sessions B/C, Phase 0-B
   95-turn run) is consistent with no duplicate dispatch under the
   fresh-launch contract.

Re-open conditions (any one re-opens Task 7 as a hard prerequisite for the
phase that introduces them):

- A phase introduces dev-loop iteration that mutates mod source within a
  running CoQ process and expects state continuity.
- A phase introduces runtime A/B switching of mod logic.
- The streaming runtime contract changes to allow mid-session mod
  toggling.
- A phase relies on the static `_loadMarkerLogged`, `_beginTurnCount`, or
  `_afterRenderRegistered` fields surviving an in-process assembly swap
  with specific semantics (continue-vs-reset).

## Alternatives Considered

- **Run the in-game delta measurement (option A from the closure
  discussion)** — rejected for now. The 15-20-minute measurement would
  produce empirical PASS/FAIL data, but the result is only consumed by
  phases that the runtime contract excludes. Time spent on it does not buy
  any guarantee beyond what the operational scope already gives.
  Re-considered if any re-open condition fires.
- **Leave Task 7 deferred indefinitely** — rejected. "Deferred without a
  closure rationale" creates ambiguity for future agents about whether the
  gap blocks downstream work. An explicit closure with re-open triggers
  removes the ambiguity while preserving the option to re-measure.
- **Amend the Phase 0-A plan to drop Task 7** — rejected. Phase 0-A plan
  is frozen per `docs/CLAUDE.md`. The plan retains Task 7 as written; this
  ADR records the closure of the acceptance gap that the plan opened.

## Consequences

### Positive

- Open-hazard list shrinks. Project memory and exit memo no longer carry
  Task 7 as an unresolved gap, removing a recurring "is this still
  blocking?" question for downstream phases.
- The re-open trigger list is explicit. Future agents can mechanically
  check whether their phase needs Task 7 closed before proceeding (per
  re-open conditions above).
- Phase 0-C and beyond can plan freely under the fresh-launch contract.

### Negative / Carry-forward

- The four concrete behavioral questions enumerated in the exit memo
  (`:122-134`) — `ApplyUnregistrar` execution, retained event subscription,
  `_loadMarkerLogged` survival, `_beginTurnCount` continuation — remain
  formally unanswered. Any work that needs answers must run the delta
  measurement first.
- The closure's correctness depends on the streaming runtime keeping its
  fixed-launch contract. If a future phase introduces mid-session toggling
  without re-opening Task 7, the architectural mitigations may not be
  sufficient and behavior is undefined.
- This is a deviation from the pattern of "plan acceptance = empirical
  PASS or explicit waiver". The ADR is the waiver.

## Related Artifacts

- `docs/superpowers/plans/2026-04-23-phase-0-a-mod-skeleton.md:586-670`
  — Phase 0-A Task 7 specification (frozen, retained as-written)
- `docs/memo/phase-0-a-exit-2026-04-23.md:64-70, 93-143` — Task 7
  resolution section (will be updated to reflect CLOSED status)
- `docs/architecture-v5.md` Phase 2+ operational model — fixed-launch
  contract that this closure relies on
- `mod/LLMOfQud/LLMOfQudSystem.cs` — `IPlayerSystem` implementation,
  `_afterRenderRegistered` static guard
- `decompiled/XRL/IPlayerSystem.cs:9-33` — symmetric `ApplyRegistrar` /
  `ApplyUnregistrar` lifecycle
- `decompiled/XRL.Core/XRLCore.cs:576-579, 624-626` — the callback
  registration APIs (one without duplicate guard, the other with our
  static-flag mitigation)

## Supersedes

None. This ADR closes an acceptance gap opened by the Phase 0-A plan; it
does not supersede any prior ADR.
