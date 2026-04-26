# ADR 0006: Phase 0-F command-issuance API pivot from CommandEvent.Send to direct Move/AttackDirection

Status: Accepted (2026-04-26); Consequence #3 cadence framing partially superseded by ADR 0007 (2026-04-26)

## Context

`docs/architecture-v5.md:2803` (v5.9 freeze) framed Phase 0-F as
"Movement/attack command issuance via `CommandEvent.Send()`". Direct
inspection of the decompiled CoQ source shows `CommandEvent.Send` does
not perform movement or attack:

- `CommandEvent.Send` only fires the registered-event chain plus a
  pooled `CommandEvent` for the actor (`decompiled/XRL.World/CommandEvent.cs:44-128`).
- `CmdMoveE` is dispatched in `XRLCore.PlayerTurn()`'s switch by
  directly calling `The.Player.Move("E")`
  (`decompiled/XRL.Core/XRLCore.cs:1107-1109`).
- `CmdAttackE` is dispatched the same way:
  `The.Player.AttackDirection("E")`
  (`decompiled/XRL.Core/XRLCore.cs:1270-1271`).
- No registered handler for the string `"CmdMoveE"` exists in the
  decompiled source. `CommandEvent.Send(player, "CmdMoveE")` outside
  of `XRLCore.PlayerTurn()`'s switch is a silent no-op that does NOT
  drain energy.

A second design question — which IPlayerSystem event hook to use —
was resolved in favor of `CommandTakeActionEvent` over the
`BeginTakeActionEvent` hook used by Phases 0-A through 0-E for
observation. `BeginTakeActionEvent` runs BEFORE the inner action loop
in `ActionManager` (`decompiled/XRL.Core/ActionManager.cs:786-800`); a
handler that drains energy there causes the entire inner action loop
(`BeforeTakeActionEvent`, `CommandTakeActionEvent`, hostile interrupt,
AutoAct, brain goals, `EndActionEvent`) to be skipped because the loop
gate at `decompiled/XRL.Core/ActionManager.cs:800` requires `Energy.Value >= 1000`.
`CommandTakeActionEvent` fires inside the inner loop
(`decompiled/XRL.Core/ActionManager.cs:829-832`), preserving
`EndActionEvent` emission and the player render fallback at
`decompiled/XRL.Core/ActionManager.cs:1806-1808`.

The codex 2026-04-26 design consultation rounds (recorded in
`docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md`)
weighed three rounds of refinement against the `:2803` literal text
and approved the API + hook + threading combination locked in the
spec.

## Decision

Phase 0-F implements movement and attack command issuance via:

1. **API**: direct calls to `GameObject.Move(string Direction, bool DoConfirmations = true, ...)` and `GameObject.AttackDirection(string dir)`. NOT `CommandEvent.Send`.
2. **Hook**: `IPlayerSystem.HandleEvent(CommandTakeActionEvent E)`. NOT `BeginTakeActionEvent`.
3. **Mirror**: `AutoAct.ClearAutoMoveStop()` is called explicitly before each `Move("E")` to mirror the `decompiled/XRL.Core/XRLCore.cs:1108` wrapper. The attack path does not need this call.
4. **Threading**: the new `[cmd]` LogInfo line is emitted on the game thread directly via `MetricsManager.LogInfo` inside `HandleEvent(CommandTakeActionEvent)`. NOT through `PendingSnapshot` and NOT from `AfterRenderCallback`. The four existing observation channels remain on their render-thread emission path.
5. **Last-ditch drain non-equivalence**: when the catch-path fallback `player.PassTurn()` itself throws, the handler falls back to `player.Energy.BaseValue = 0`. This is intentionally non-equivalent to `PassTurn`: it bypasses `UseEnergyEvent` emission. Any system that depends on `UseEnergyEvent` from a player turn-end MUST NOT depend on the catch-path Layer-3 drain emitting it.

## Alternatives Considered

1. **`CommandEvent.Send("CmdMoveE")` as the literal `:2803` says.** Rejected because `CommandEvent.Send` does not perform movement; the engine itself does not use it for `CmdMoveE` dispatch (the engine uses the `XRLCore.PlayerTurn()` switch's direct `Move` call). Sending `CommandEvent` outside the `PlayerTurn` switch is a silent no-op that does not drain energy and would cause the engine to fall through to `PlayerTurn()` waiting on keyboard input — breaking the autonomy claim of the entire phase.
2. **Hook `BeginTakeActionEvent` (mirror Phase 0-A through 0-E).** Rejected because `BeginTakeActionEvent` fires BEFORE the inner action loop. A `BeginTakeActionEvent` handler that drains energy causes `ActionManager` to skip `BeforeTakeActionEvent`, `CommandTakeActionEvent`, `EndActionEvent`, the hostile interrupt check, AutoAct, brain goals, and the player render fallback. `CommandTakeActionEvent` fires inside the loop and keeps all of those paths intact.
3. **Harmony-patch `XRLCore.PlayerTurn()` to inject our action.** Rejected because (a) Harmony patching is reserved for paths that have no event hook (per `docs/architecture-v5.md` Phase 0-A guidance), (b) `CommandTakeActionEvent` is precisely the event hook this would otherwise need, (c) Harmony patches add cross-mod compatibility risk and increase the surface area of "things that can break on a CoQ update".
4. **Stage `[cmd]` through `PendingSnapshot` and emit from `AfterRenderCallback`.** Rejected because (a) the action and its `[cmd]` log line happen on the game thread; coupling the log emission to the next render is unnecessary and introduces a window where the game state may have already changed, (b) Phase 0-F's central change is energy-drain timing, which directly affects render cadence — keeping `[cmd]` decoupled from render is defense-in-depth against the Codex-flagged hazard "render cadence shifts because PlayerTurn() is no longer reached".

## Consequences

1. The `:2803` spec line is reinterpreted: "via `CommandEvent.Send()`" naming in the v5.9 freeze remains historically accurate but is overridden for Phase 0-F semantics by this ADR. Future phase enumeration MUST reference both `:2803` (frozen text) and ADR 0006 (override) when citing Phase 0-F scope.
2. **AutoAct mirror semantics**: direct `Move("E")` bypasses the `decompiled/XRL.Core/XRLCore.cs:1108` `AutoAct.ClearAutoMoveStop()` call unless we mirror it. Phase 0-F mirrors it. Phase 0-G+ NPC-AutoMove or follower scenarios re-evaluate whether explicitly clearing `AutomoveInterruptTurn` is still desired.
3. **Thread-decoupled `[cmd]` cadence**: parser correlation contract for the five LogInfo channels (`[screen] BEGIN/END`, `[state]`, `[caps]`, `[build]`, `[cmd]`) is "correlate by `turn` field, never adjacency or count parity". `[cmd]` runs on the game thread synchronously; the four observation channels run on the render thread via `AfterRenderCallback`. Other CoQ subsystems' `LogInfo` lines may interleave between any two of the six per-turn lines.
4. **Phase 0-G+ inherits this API path**: any future autonomous dispatch (heuristic bot, LLM-driven action) uses direct `Move/AttackDirection/PassTurn/AttackCell/...` calls. Future phases that need to issue commands via `CommandEvent.Send` for the side effects (e.g., a mutation that listens for `CommandFooEvent`) re-open this ADR.
5. **`Energy.BaseValue = 0` non-equivalence is permanent**: the catch-path Layer-3 drain skips `UseEnergyEvent` (`decompiled/XRL.World/GameObject.cs:2925-2930`). The implementation comment at the call site documents this in code; the spec section "Error posture (3-layer drain, defense in depth)" documents it in design.

## Related Artifacts

- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md`
  — design spec (3 rounds of Codex review, APPROVED); defines the
  `command_issuance.v1` schema, hostile-scan priority, 3-layer
  energy-drain posture, and acceptance criteria this ADR formalizes.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md`
  — implementation plan (lands in the same docs-only PR as this ADR).
- `docs/adr/decisions/2026-04-26-phase-0-f-command-issuance-api-pivot-from-commandevent-send-to-direct-move-attackdirection.md`
  — machine-readable decision record produced by
  `scripts/create_adr_decision.py` for the pre-commit ADR gate.
- `docs/architecture-v5.md:2803` — Phase 0-F line being reinterpreted.
- `docs/architecture-v5.md:2804` — Phase 0-G boundary preserved.
- `docs/architecture-v5.md:1787-1790` — game-queue routing rule.
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that
  required this ADR.
- `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — precedent
  ADR for spec-line pivoting.
- `docs/memo/phase-0-e-exit-2026-04-26.md` — Phase 0-E exit memo whose
  carry-forward rule 5 (JSON null discipline + 5th-occurrence helper
  extraction trigger) is acted on by the implementation plan's Task 2.
- Implementation: `mod/LLMOfQud/LLMOfQudSystem.cs`
  (`HandleEvent(CommandTakeActionEvent)`),
  `mod/LLMOfQud/SnapshotState.cs`
  (command JSON builders + helper extraction).

Future artifact (not yet produced; will be linked here once written):
the Phase 0-F exit memo, created at the implementation plan's Task 8
under `docs/memo/` with filename `phase-0-f-exit-YYYY-MM-DD.md` (the
date stamp is fixed at memo-write time via `date -u +%Y-%m-%d`).

## Supersedes

None at the time of writing. ADR 0006 narrows the interpretation of `docs/architecture-v5.md:2803` under the freeze rule (ADR 0001) without superseding any prior ADR.

## Superseded By (Partial)

`docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md` (2026-04-26) partially supersedes Consequence #3 (cadence framing) above. The `[cmd]`/observation correlation contract (correlate by `turn`, not line adjacency) is retained; the implicit assumption that observation channels emit at any cadence during autonomous dispatch is replaced by ADR 0007's explicit "ActionManager render fallback at `decompiled/XRL.Core/ActionManager.cs:1806-1808` flushes per turn once `E.PreventAction` is scoped to the abnormal-energy catch path" contract.
