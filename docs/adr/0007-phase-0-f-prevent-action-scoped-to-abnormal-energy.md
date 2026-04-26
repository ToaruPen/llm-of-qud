# ADR 0007: Phase 0-F PreventAction usage scoped to abnormal-energy catch path; render-fallback restored

Status: Accepted (2026-04-26)

## Context

ADR 0006 set the Phase 0-F design pivot to direct `Move`/`AttackDirection`
calls inside `HandleEvent(CommandTakeActionEvent)` and committed two
load-bearing claims that, on empirical verification, are mutually
incompatible:

- **Claim A (design spec line 9):** "ActionManager's player render
  fallback runs after energy is spent on the `CommandTakeActionEvent`
  path, so existing `[screen]/[state]/[caps]/[build]` still flush"
  (`docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md:9`).
- **Claim B (design spec line 12 + Task 4 / Task 5 implementation):**
  "Setting `E.PreventAction = true` ... causes the surrounding
  `if (!CommandTakeActionEvent.Check(Actor)) continue;` ... to
  short-circuit the loop iteration"
  (`docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md:12`,
  `mod/LLMOfQud/LLMOfQudSystem.cs:349-352`).

The two claims cannot both hold in the same `ActionManager` inner-loop
iteration. Reading the dispatch site verbatim:

- `decompiled/XRL.Core/ActionManager.cs:829-832` —
  `if (!CommandTakeActionEvent.Check(Actor)) continue;`
- `decompiled/XRL.World/CommandTakeActionEvent.cs:37-39` —
  `Check` returns `Object.HandleEvent(...) && !PreventAction`.
- `decompiled/XRL.Core/ActionManager.cs:838` —
  `if (Actor?.Energy != null && Actor.Energy.Value >= 1000 && Actor.IsPlayer())`
  guards the keyboard-input-bearing branch (`PlayerTurn()` at
  `decompiled/XRL.Core/ActionManager.cs:1797-1799`).
- `decompiled/XRL.Core/ActionManager.cs:1806-1808` —
  `else if (Actor.IsPlayer()) { The.Core.RenderBase(); }`
  is the player render fallback, reached only when the `:838` energy
  guard is false (i.e., player but `Energy.Value < 1000`).

`PreventAction = true` flips `Check` to false at `:829-832`, the
iteration `continue`s, and neither `:838`'s player branch nor
`:1806-1808`'s render fallback is reached on that iteration. Energy
draining alone (Layers 1/2/3 of the implementation plan) is sufficient
to keep `:838` false and to prevent `PlayerTurn()` from gating on
keyboard input; `PreventAction = true` is therefore redundant on the
success path and is the direct cause of the empirical observation
described below.

**Empirical observation (488-turn autonomous run on
`feat/phase-0-f-impl` at commit `be2e6b2`, recorded in
`/tmp/phase-0-f-acceptance/raw-player-15-05-08.log`):**

| Channel | Run-window count | Source |
|---|---|---|
| `[cmd]` (game-thread direct emit) | 488 | per-turn |
| `begin_take_action count=` (sampling, every 10 turns) | 48 | confirms `BeginTakeActionEvent` fires per turn |
| `[state]/[caps]/[build]` ERROR sentinels | 0 | builders succeed; `PendingSnapshot` is updated per turn |
| `[screen] BEGIN` | 1 | death screen only |
| `[screen] END` | 0 | render did not complete the after-render walk before the run ended |
| `[state]` | 1 | death screen only |
| `[caps]` | 1 | death screen only |
| `[build]` | 1 | death screen only |

The render-thread channels emit at ~0 cadence during the autonomous
run. ADR 0006 Consequence #3 anticipated a cadence shift (parser
correlation by `turn`, not adjacency); the empirical cadence is not
shifted but effectively zero, falsifying both the cadence assumption
and design spec line 9. The single death-screen flush is consistent
with `RenderBase()` being reached only when game-over rendering forces
it on a path independent of the per-turn loop.

## Decision

Scope `E.PreventAction = true` to the abnormal-energy catch path only,
restoring the `:1806-1808` render fallback as the per-turn flush
trigger:

1. **Success path (no exception, energy drained to `< 1000`).** Do
   NOT set `E.PreventAction = true`. Allow `Check` to return true.
   The `:838` energy guard sees `Energy.Value < 1000` and skips the
   player keyboard-input branch; control reaches the
   `else if (Actor.IsPlayer()) { The.Core.RenderBase(); }` fallback
   at `:1806-1808` on the same iteration. `RenderBase` invokes
   `RenderBaseToBuffer` which fires the `AfterRenderCallbacks` chain
   (`decompiled/XRL.Core/XRLCore.cs:2354-2426`); `[screen]/[state]/
   [caps]/[build]` flush per turn as Phases 0-A through 0-E expect.
2. **Catch path (exception during dispatch, post-recovery
   `Energy.Value >= 1000`).** After Layer-3 ladder
   (`PassTurn` → `BaseValue = 0`) attempts, if `Energy.Value` is
   still `>= 1000`, set `E.PreventAction = true` as Layer-4
   defense-in-depth so the iteration short-circuits at `:829-832`.
   The render fallback is sacrificed for that one turn to preserve
   the autonomy invariant; subsequent turns recover.
3. **No other handler-control flag changes.** The handler still
   returns `true` (per ADR 0006 Decision rationale, returning false
   would suppress other registered handlers via
   `decompiled/XRL.Collections/EventRegistry.cs:260-272` and the
   parts/effects chain at
   `decompiled/XRL.World/GameObject.cs:14024-14030, 14053-14059`).

Acceptance criterion 2 (Step A) and criterion 3 (Step B) cross-channel
parity gates `[screen] BEGIN == [screen] END == [state] == [caps] ==
[build] == [cmd] >= 40` are retained as written; the Decision restores
the empirical conditions under which they hold.

## Alternatives Considered

1. **Relax acceptance criteria 2/3 (parity gate)**. Rejected. Phase 1's
   Brain consumes per-turn `[state]/[caps]/[build]/[screen]` records
   for tool-loop input. Shipping autonomy without observability
   undermines the phase's value. ADR 0006 Consequence #3 already
   weakened the inter-line adjacency contract; further weakening the
   per-turn cadence contract would defer the observability problem
   to Phase 1 with no clear path back.
2. **Explicit `The.Core.RenderBase()` from the game thread**. Viable
   but unnecessary. The ActionManager fallback path at
   `:1806-1808` already exists and is reached automatically once
   `PreventAction = true` is removed from the success path.
   Calling `RenderBase` from inside `HandleEvent` adds a re-entry
   surface (`RenderBase` → `AfterRenderCallbacks` chain → other
   handlers) that the ActionManager-driven path avoids by issuing
   `RenderBase` after the inner-loop iteration completes.
3. **Game-thread emit for `[state]/[caps]/[build]` from inside
   `HandleEvent(BeginTakeActionEvent)`** (bypass `PendingSnapshot` /
   `AfterRenderCallback`). Rejected for `[screen]`: `ScreenBuffer.Buffer`
   is a public mutable 2D array (`decompiled/ConsoleLib.Console/
   ScreenBuffer.cs:21`, indexer at `:103-115`) that the render thread
   writes under `TextConsole.BufferCS` lock (`decompiled/GameManager.cs:
   3049-3054, 3089-3091`). Reading without that lock from the game
   thread is a race. Bypassing `PendingSnapshot` for the three text
   channels while keeping `[screen]` on the render path also fragments
   the observation pipeline that Phase 0-A through 0-E established.
4. **Rate-limit autonomous dispatch to wait for render**. Rejected.
   The "engine never waits on keyboard input" invariant is the core
   Phase 0-F deliverable; throttling the game thread to wait for the
   render thread reintroduces the wait condition under a different
   name and contradicts the Phase 1+ WebSocket-bridge design that
   assumes per-turn synchronous dispatch.

## Consequences

1. **`PreventAction = true` is now defense-in-depth Layer 4**, not the
   primary autonomy mechanism. The autonomy invariant — "engine does
   not wait on keyboard input after our handler returns" — depends on
   `Energy.Value < 1000` from Layers 1/2/3, NOT on `PreventAction`.
   The implementation site MUST keep the catch-path Layer-4 path
   untouched: it is the last line of defense if all three drain layers
   fail.
2. **Render fallback at `:1806-1808` becomes load-bearing for the
   per-turn flush of `[screen]/[state]/[caps]/[build]`.** Any future
   change in CoQ that alters this fallback (e.g., a CoQ patch that
   removes the `else if (Actor.IsPlayer())` branch) is a re-open
   trigger for Phase 0-F, not just a regression.
3. **Per-turn line count is restored to 6** = 2 (`[screen]`
   BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]` + 1 `[cmd]`,
   with the parser correlation contract (correlate by `turn`, not
   line adjacency) inherited from ADR 0006 Consequence #3.
4. **ADR 0006 Consequence #3 is partially superseded.** The
   "thread-decoupled cadence" framing is retained as the parser
   contract, but the implicit assumption that observation channels
   would emit at any cadence at all during autonomous dispatch is
   replaced by the explicit "fallback `:1806-1808` flushes per turn"
   contract.
5. **Implementation patch is small** — a conditional around the
   existing `finally { E.PreventAction = true; }` in
   `mod/LLMOfQud/LLMOfQudSystem.cs:349-352`. Plan addendum lists the
   exact change.
6. **Acceptance runs invalidated by ADR 0007 must be redone.** The
   pre-ADR-0007 488-turn run captured at
   `/tmp/phase-0-f-acceptance/raw-player-15-05-08.log` does not
   satisfy criteria 2/3; the artifact is preserved as evidence for
   this ADR but is not the Phase 0-F PASS artifact.

## Related Artifacts

- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md`
  — original Phase 0-F ADR; this ADR partially supersedes Consequence
  #3 (cadence framing).
- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md`
  — design spec; lines 9 (Architecture, render fallback) and 12
  (Architecture, PreventAction) are corrected by this ADR's Decision.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md`
  — implementation plan; addendum Task 5b lands the
  `LLMOfQudSystem.cs` patch.
- `mod/LLMOfQud/LLMOfQudSystem.cs:181-358`
  — current `HandleEvent(CommandTakeActionEvent)` body (commit
  `be2e6b2`); the `finally` block at `:349-352` is the patch site.
- `decompiled/XRL.Core/ActionManager.cs:829-832, 838, 1797-1828`
  — dispatch / energy-guard / render-fallback citations.
- `decompiled/XRL.World/CommandTakeActionEvent.cs:37-39`
  — `Check` semantics.
- `decompiled/XRL.Core/XRLCore.cs:624-626, 2354-2426, 2517-2582`
  — `AfterRenderCallbacks` registration and `RenderBase` /
  `RenderBaseToBuffer` flow.
- `decompiled/ConsoleLib.Console/ScreenBuffer.cs:21, 103-115`
  — `Buffer[,]` mutable shared state (rejected (C) alternative).
- `decompiled/GameManager.cs:3049-3054, 3089-3091`
  — `TextConsole.BufferCS` lock (rejected (C) alternative).
- `/tmp/phase-0-f-acceptance/raw-player-15-05-08.log`
  — 488-turn empirical evidence (operator-local; not committed).

- `docs/memo/phase-0-f-exit-2026-04-26.md` — Phase 0-F exit memo
  recording the post-ADR-0007 acceptance results (505-record combined
  Step A + Step B run, full 6-channel parity, 11 damaging hits) and
  the carry-forward observations for Phase 0-G / Phase 1.

## Supersedes

Partially supersedes `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md`
Consequence #3 (cadence framing). All other Decisions, Alternatives,
and Consequences of ADR 0006 remain in force.
