# Phase 0-F: Movement / Attack Command Issuance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Issue movement and melee-attack commands autonomously from the MOD via direct `GameObject.Move("E", DoConfirmations:false)` and `GameObject.AttackDirection(dir)` calls hooked from `HandleEvent(CommandTakeActionEvent)`. Emit one structured `[LLMOfQud][cmd] {...}` JSON line per dispatch — a fifth per-turn observation primitive — game-thread direct emit, decoupled from the existing render-thread `AfterRenderCallback`. Phase 0-F is the first phase where the MOD acts on the game; all prior phases observed only.

**Architecture (per design spec `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md`):**

- **Game thread** (`HandleEvent(CommandTakeActionEvent E)`): run Step B hostile detection; if hostile adjacent → `AttackDirection(dir)`, else `Move("E", DoConfirmations:false)`; on `result==false` and no energy drain → `PassTurn()`; emit `[cmd]` line synchronously via `MetricsManager.LogInfo`; `E.PreventAction = true` in `finally`; `return true`.
- **3-layer drain (defense in depth):** Layer 1 = action API spends energy on success. Layer 2 = `PassTurn()` on action-returned-false-without-drain. Layer 3 = `Energy.BaseValue = 0` last-ditch only when `PassTurn()` itself throws.
- **Game-thread direct emit for `[cmd]`, NOT through `PendingSnapshot`.** `PendingSnapshot` keeps its single observation slot (`StateJson, DisplayMode, CapsJson, BuildJson`) — no extension for `[cmd]`. `[cmd]` is decoupled from render cadence.
- **Per-turn output: 6 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]` + 1 `[cmd]`. **Parser correlation contract: correlate by the `turn` field, never adjacency or count parity.**
- **Hook is `CommandTakeActionEvent`, NOT `BeginTakeActionEvent`.** A `BeginTakeActionEvent` handler that drains energy would skip the entire inner action loop in `decompiled/XRL.Core/ActionManager.cs:786-800`. `CommandTakeActionEvent` fires inside the loop (`decompiled/XRL.Core/ActionManager.cs:829-832`), keeping `EndActionEvent`, hostile interrupt, and ActionManager's player render fallback (`decompiled/XRL.Core/ActionManager.cs:1806-1808`) intact.
- **API is direct `Move`/`AttackDirection`, NOT `CommandEvent.Send`.** `XRLCore.PlayerTurn()` switch handles `CmdMoveE`/`CmdAttackE` strings by directly calling `The.Player.Move("E")` (`decompiled/XRL.Core/XRLCore.cs:1107-1109`) and `The.Player.AttackDirection("E")` (`:1270-1271`); `CommandEvent.Send("CmdMoveE")` has no registered handler and would silent-no-op without draining energy. ADR 0006 records this pivot.

**Schema lock: `command_issuance.v1`** — full record fields (no missing, no extra): `{turn, schema, hook, action, dir, result, fallback, energy_before, energy_after, pos_before, pos_after, target_id, target_name, target_pos_before, target_hp_before, target_hp_after, error}`. Sentinel reduced shape: `{turn, schema, error}`. Field semantics, error posture, normalization rules, and out-of-scope deferrals are locked in the design spec; this plan implements that contract verbatim and references back to the spec rather than restating it.

**Tech Stack:** Same as Phase 0-A through 0-E. CoQ Roslyn-compiles `mod/LLMOfQud/*.cs` at game launch (`decompiled/XRL/ModInfo.cs:478, 757-823`). Manual in-game verification against `Player.log` is the acceptance gate (Phase 0-C ADR 0004 in force — no C# unit test framework).

- New `using` directives needed in `mod/LLMOfQud/LLMOfQudSystem.cs`: add `using XRL.World.Capabilities;` for `AutoAct.ClearAutoMoveStop()` (verify symbol path against `decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`). No new `using` directives in `SnapshotState.cs`.
- Environment paths (verified 2026-04-26 from `phase-0-e-exit-2026-04-26.md:30-37`):
  - `$MODS_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods`
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach (mirrors 0-D / 0-E, ADR 0004 still in force):**

- Manual in-game verification on two character runs:
  - **Step A run** (movement only): fresh Mutated Human Marauder, Joppa central clear east lane, ≥40 turns total of `CommandTakeActionEvent` dispatch with ≥10 successful east `Move` records.
  - **Step B run** (combat): same character, debug-spawned adjacent hostile via `wish testhero:<blueprint>`, ≥40 turns total with ≥3 `AttackDirection` records and ≥1 with `target_hp_after < target_hp_before`.
- Acceptance counts: `[screen] BEGIN == [screen] END == [state] == [caps] == [build] == [cmd] >= 40` for both runs (cross-channel regression gate).
- `ERR_SCREEN == 0` is the hard gate; `ERR_STATE / ERR_CAPS / ERR_BUILD / ERR_CMD == 0` are soft gates.
- Spot-check semantic invariants: 17-key full-record set, `hook=="CommandTakeActionEvent"` always, `action ∈ {"Move","AttackDirection"}`, `dir ∈ 8-direction enum`, `energy_after < energy_before` strictly, `result==false ⇒ fallback=="pass_turn"`, `pos_*` shape `{x,y,zone}`.
- **No C# unit tests** — deferred to Phase 2a per ADR 0004.

**Reference:**

- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` (spec — locked at the commit Task 0 lands).
- `docs/architecture-v5.md` (v5.9, frozen): `:2803` (Phase 0-F line being reinterpreted by ADR 0006), `:2804` (Phase 0-G boundary line), `:1787-1790` (game-queue routing rule).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0006.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — precedent for spec-line pivoting ADR; 0006 mirrors its template.
- `docs/memo/phase-0-e-exit-2026-04-26.md` — Phase 0-E outcomes; rule 5 (JSON null discipline + 5th-occurrence helper extraction trigger) drives Task 2 of this plan.
- `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` — precedent plan structure modeled here.
- CoQ APIs (verified 2026-04-26):
  - **Event**: `CommandTakeActionEvent` (`decompiled/XRL.World/CommandTakeActionEvent.cs:1-42`), `Check` returns `Object.HandleEvent(...) && !PreventAction` (`decompiled/XRL.World/CommandTakeActionEvent.cs:37-38`).
  - **ActionManager flow**: per-segment `Energy += Speed` add (`decompiled/XRL.Core/ActionManager.cs:785`), inner action loop (`decompiled/XRL.Core/ActionManager.cs:800-830`), `BeforeTakeActionEvent.Check` (`decompiled/XRL.Core/ActionManager.cs:819-826`), `CommandTakeActionEvent.Check` (`decompiled/XRL.Core/ActionManager.cs:829-832`), hostile interrupt (`decompiled/XRL.Core/ActionManager.cs:834-837`), Brain goals (`decompiled/XRL.Core/ActionManager.cs:1763-1767`), `PlayerTurn()` call (`decompiled/XRL.Core/ActionManager.cs:1797-1799`), player render fallback (`decompiled/XRL.Core/ActionManager.cs:1806-1808`), `EndActionEvent.Send` (`decompiled/XRL.Core/ActionManager.cs:1828`).
  - **PlayerTurn switch**: `CmdMoveE` → `Move("E")` (`decompiled/XRL.Core/XRLCore.cs:1107-1109`), `CmdAttackE` → `AttackDirection("E")` (`decompiled/XRL.Core/XRLCore.cs:1270-1271`).
  - **Movement API**: `Move` overloads (`decompiled/XRL.World/GameObject.cs:15274`, `decompiled/XRL.World/GameObject.cs:15719-15722`), tutorial intercept (`decompiled/XRL.World/GameObject.cs:15336-15338`), zone-cross (`decompiled/XRL.World/GameObject.cs:15384`, `decompiled/XRL.World/GameObject.cs:15404-15409`), success energy spend (`decompiled/XRL.World/GameObject.cs:15397-15400`), fail path (`decompiled/XRL.World/GameObject.cs:15378-15382`), confirmation gate (`decompiled/XRL.World/GameObject.cs:15630-15699`).
  - **Attack API**: `AttackDirection` (`decompiled/XRL.World/GameObject.cs:17882-17902`), `Combat.AttackDirection` (`decompiled/XRL.World.Parts/Combat.cs:844-860`), `Combat.AttackCell` (`decompiled/XRL.World.Parts/Combat.cs:877-889`), melee energy spend (`decompiled/XRL.World.Parts/Combat.cs:794-799`).
  - **Hostile detection**: `Cell.GetCellFromDirection` (`decompiled/XRL.World/Cell.cs:7322-7324`), `Cell.GetCombatTarget` (`decompiled/XRL.World/Cell.cs:8511-8558`), `GameObject.IsHostileTowards` (`decompiled/XRL.World/GameObject.cs:10887-10894`).
  - **Turn-end fallback**: `PassTurn` (`decompiled/XRL.World/GameObject.cs:17543-17545`), `UseEnergy` + `UseEnergyEvent` emit (`decompiled/XRL.World/GameObject.cs:2925-2930`).
  - **Energy / statistics**: `GameObject.Energy` field (`decompiled/XRL.World/GameObject.cs:145`), `Statistic.Value` (`decompiled/XRL.World/Statistic.cs:238-252`), `Statistic.BaseValue` setter (`decompiled/XRL.World/Statistic.cs:218-232`), `StatChange_*` listeners (`decompiled/XRL.World/Statistic.cs:646-673`), `hitpoints` / `baseHitpoints` (`decompiled/XRL.World/GameObject.cs:1177-1198`).
  - **Position / zone**: `GameObject.CurrentZone == CurrentCell?.ParentZone` (`decompiled/XRL.World/GameObject.cs:473`), `Zone.ZoneID` (`decompiled/XRL.World/Zone.cs:389`).
  - **Target identity**: `GameObject.ID` (`decompiled/XRL.World/GameObject.cs:340-350`, `decompiled/XRL.World/GameObject.cs:389-399`), `ShortDisplayNameStripped` (`decompiled/XRL.World/GameObject.cs:763-766`).
  - **AutoAct mirror**: `AutoAct.ClearAutoMoveStop` (`decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`).
  - **Event dispatch contract**: `EventRegistry` chain abort on false (`decompiled/XRL.Collections/EventRegistry.cs:260-272`), `GameObject` parts/effects chain abort on false (`decompiled/XRL.World/GameObject.cs:14024-14030, 14053-14059`).
  - **MetricsManager.LogInfo**: `decompiled/MetricsManager.cs:407-409`.

---

## Prerequisites (one-time per session)

Before starting any task, confirm:

1. Phase 0-E is landed on `main` (commit `3c7eec7 feat(mod): Phase 0-E current_build.v1 [build] observation` or a successor). Verify `mod/LLMOfQud/SnapshotState.cs` has the `BuildBuildJson` + `AppendBuildIdentity / AppendBuildAttributes / AppendBuildResources / NormalizeStomachStatus` helpers and `mod/LLMOfQud/LLMOfQudSystem.cs` has the 4-LogInfo `AfterRenderCallback`.
2. The symlink `$MODS_DIR/LLMOfQud` resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling, re-create per Phase 0-A Task 1.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. **Disable any coexisting user mod for the acceptance runs.** Phase 0-E's 160-turn run was performed with `LLMOfQud` only (other mods `Skipping, state: Disabled`). Re-verify the in-game Mods list reflects single-mod load before starting Tasks 6 and 7.
5. Two clean save slots are NOT required (Phase 0-F's two acceptance runs are sequential on the same character — Step A in a clear lane, Step B after `wish testhero:<blueprint>`).

---

## File Structure

ADR + plan + spec land in a docs-only PR (Task 0). Implementation tasks (Tasks 2–5) modify the two existing C# files. Tasks 1, 6, 7 are manual in-game work with no code edits. Task 8 finalizes the exit memo.

**Docs-only PR (PR-F1, on branch `feat/phase-0-f-design`):**

- Add: `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` — design spec (already on the branch when this plan starts; verify in Task 0 Step 1).
- Add: `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` — this plan.
- Create: `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — ADR documenting the API pivot (`CommandEvent.Send` → direct `Move/AttackDirection`), the hook choice (`CommandTakeActionEvent` not `BeginTakeActionEvent`), the AutoAct mirror, the threading decoupling, and the Layer-3 `BaseValue=0` non-equivalence.
- Append to: `docs/adr/decision-log.md` — index entry for ADR 0006.

**Implementation PR (PR-F2, on branch `feat/phase-0-f-impl` cut from `main` after PR-F1 merges):**

- Modify: `mod/LLMOfQud/SnapshotState.cs`
  - Extract: `AppendJsonStringOrNull(StringBuilder sb, string s)` — emits `null` literal when `s == null`, else delegates to `AppendJsonString`.
  - Extract: `AppendJsonIntOrNull(StringBuilder sb, int? n)` — emits `null` literal when null, else digits.
  - Migrate the existing 4 nullable-string call sites in `SnapshotState.cs` (`genotype_id`, `subtype_id`, `hunger`, `thirst`) to use `AppendJsonStringOrNull`.
  - Add: `BuildCmdJson(...)` static — emits the full 17-key `command_issuance.v1` record.
  - Add: `BuildCmdSentinelJson(int turn, Exception ex)` static — emits the reduced `{turn, schema, error}` record.
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Add `using XRL.World.Capabilities;` for `AutoAct`.
  - Extend `RegisterPlayer`: add `Registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);` next to the existing `BeginTakeActionEvent` registration.
  - Add: `public override bool HandleEvent(CommandTakeActionEvent E)` — Step A (Task 4) and Step B (Task 5) implementation, 3-layer drain (Tasks 4 + 5).

External (created during execution):

- `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-e-exit-2026-04-26.md`'s shape.

No manifest edits. No symlink changes. No new dependencies. The Roslyn compile set stays at 3 files (`LLMOfQudSystem.cs`, `SnapshotState.cs`, `LLMOfQudBootstrap.cs` — unchanged for this phase).

---

## Task 0: ADR 0006 + plan landing (docs-only PR-F1, Phase 0-C / 0-E precedent)

**Why this task exists:** The design spec's "ADR 0006 timing" section (option 1) records the decision: a separate prerequisite docs-only PR lands ADR 0006 + this plan BEFORE the implementation PR opens. ADR re-opens the v5.9 freeze for the `:2803` Phase 0-F line and changes the API surface from `CommandEvent.Send` to direct `Move/AttackDirection`; reviewing it independently of the C# diff is the safer ordering.

**Files:**

- Create: `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md`
- Modify: `docs/adr/decision-log.md` (append index entry)
- Add: `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` (this plan, when staged for the docs PR)

**Branch:** `feat/phase-0-f-design` (the spec is already committed here; ADR + this plan are added to the same branch and the branch is opened as PR-F1).

- [ ] **Step 1: Verify the branch state.**

```bash
git branch --show-current
git log --oneline feat/phase-0-f-design -10
```

Expected: current branch is `feat/phase-0-f-design`; `git log` shows the spec commit on top of `3c7eec7` (Phase 0-E merge to main) or its successor. If the branch does not exist, create it from `main`: `git switch -c feat/phase-0-f-design main`.

- [ ] **Step 2: Read the existing ADR template and ADR 0005 for shape.**

```bash
cat docs/adr/0000-adr-template.md
cat docs/adr/0005-phase-0-e-current-build-state-pivot.md
```

ADR 0006 mirrors ADR 0005's shape per the canonical template (`docs/adr/0000-adr-template.md`): front-matter (Status, Date), Context, Decision, Alternatives Considered (numbered), Consequences (numbered), Related Artifacts, Supersedes. There is NO standalone `## References` section — references fold into `## Related Artifacts`. Length ~120–180 lines.

- [ ] **Step 3: Write `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md`.**

```markdown
# ADR 0006: Phase 0-F command-issuance API pivot from CommandEvent.Send to direct Move/AttackDirection

Status: Accepted (<YYYY-MM-DD>)

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
gate at `decompiled/XRL.Core/ActionManager.cs:800` requires
`Energy.Value >= 1000`. `CommandTakeActionEvent` fires inside the
inner loop (`decompiled/XRL.Core/ActionManager.cs:829-832`),
preserving `EndActionEvent` emission and the player render fallback
at `decompiled/XRL.Core/ActionManager.cs:1806-1808`.

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
- Exit memo: `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md` (created at
  the implementation plan's Task 8).

## Supersedes

None. ADR 0006 narrows the interpretation of `docs/architecture-v5.md:2803` under the freeze rule (ADR 0001) without superseding any prior ADR.
```

Replace `<YYYY-MM-DD>` with the actual date the ADR is finalized (use `date -u +%Y-%m-%d`).

- [ ] **Step 4: Append the index entry to `docs/adr/decision-log.md`.**

Read the existing file first:

```bash
cat docs/adr/decision-log.md
```

Append a new entry mirroring the existing format. Per the latest entries, the format is `- <ISO timestamp> | adr_required=true | <short title> | [details](decisions/<file>.md)`. Run the helper to create the machine-readable record AND emit the index line:

```bash
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Phase 0-F command-issuance API pivot from CommandEvent.Send to direct Move/AttackDirection" \
  --rationale "CommandEvent.Send has no registered handler for CmdMoveE/CmdAttackE; engine itself dispatches via direct GameObject.Move/AttackDirection in XRLCore.PlayerTurn(). Hook is CommandTakeActionEvent (not BeginTakeActionEvent) to keep the inner action loop's bookkeeping intact." \
  --adr docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
```

The script appends to `decision-log.md` and writes a per-decision file under `decisions/`. Verify by re-reading `decision-log.md`.

- [ ] **Step 5: Run the static checks gate.**

```bash
pre-commit run --all-files
```

Expected: all hooks PASS. The `check_adr_decision.py` hook runs against the staged paths; if it complains, re-check that the `create_adr_decision.py` invocation in Step 4 succeeded.

- [ ] **Step 6: Commit ADR 0006.**

```bash
git add docs/adr/0006-phase-0-f-command-issuance-api-pivot.md \
        docs/adr/decision-log.md \
        docs/adr/decisions/
git commit -m "$(cat <<'EOF'
docs(adr): ADR 0006 — Phase 0-F command-issuance API pivot

Re-opens the docs/architecture-v5.md:2803 Phase 0-F line semantics
under the freeze rule of ADR 0001. The pivot is driven by:
- CommandEvent.Send has no registered handler for CmdMoveE/CmdAttackE;
  engine itself uses direct GameObject.Move("E") and
  GameObject.AttackDirection("E") calls in XRLCore.PlayerTurn().
- Hook is CommandTakeActionEvent (not BeginTakeActionEvent) so
  ActionManager's inner action loop bookkeeping (EndActionEvent,
  hostile interrupt, AutoAct, render fallback) stays intact.
- AutoAct.ClearAutoMoveStop() is mirrored explicitly to match the
  decompiled/XRL.Core/XRLCore.cs:1108 keypress wrapper.
- [cmd] LogInfo emits on the game thread directly, decoupled from
  AfterRenderCallback render cadence.
- Last-ditch Energy.BaseValue=0 in the catch path is intentionally
  NOT equivalent to PassTurn — it bypasses UseEnergyEvent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Add this plan to the docs PR.**

The spec is already on the branch. Add this plan and verify it stages cleanly:

```bash
git add docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md
git status
```

Then commit:

```bash
git commit -m "$(cat <<'EOF'
docs(plan): Phase 0-F command-issuance implementation plan

Lands the implementation plan for Phase 0-F alongside ADR 0006 and the
design spec (already committed at the branch tip's previous commit).
Tasks 0-8: ADR + plan + empirical probe + AppendJsonStringOrNull
helper extraction + command JSON builders + HandleEvent registration
+ Step A logic + Step B logic + acceptance runs + exit memo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push and open PR-F1.**

```bash
git push -u origin feat/phase-0-f-design
gh pr create --base main --head feat/phase-0-f-design \
  --title "docs: Phase 0-F readiness — ADR 0006, plan, design spec" \
  --body "$(cat <<'EOF'
## Summary

- ADR 0006 records the Phase 0-F API pivot: \`CommandEvent.Send()\` (literal in spec :2803) → direct \`GameObject.Move/AttackDirection\` calls. Hook is \`CommandTakeActionEvent\` (not \`BeginTakeActionEvent\`).
- Design spec at \`docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md\` (3 rounds of Codex review, APPROVED).
- Implementation plan at \`docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md\` (this PR is PR-F1; PR-F2 will carry the implementation against \`main\` after this lands).

## Test plan

- [ ] \`pre-commit run --all-files\` clean
- [ ] CI green
- [ ] CodeRabbit comments addressed before merge
- [ ] Docs-only PR — no runtime acceptance required (PR-F2 carries that)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

After PR-F1 merges to `main`, branch out PR-F2 from `main` for Tasks 2–7.

---

## Task 1: Empirical probe — pin the Step B hostile blueprint

**Why this task exists:** Acceptance criterion 3 requires a deterministic adjacent hostile via `wish testhero:<blueprint>`. The design spec calls for a probe BEFORE locking the implementation: confirm the chosen blueprint stays hostile post-spawn and is detectable by `Cell.GetCombatTarget(player, ..., Filter: o => o.IsHostileTowards(player))`. This task pins the blueprint into a constant the implementation will reference.

**Files:** none (manual game session). The chosen blueprint goes into Task 7's acceptance procedure as a hard constant — record it in the operator's notes.

**Branch:** any. Probe is in-game work; no commits.

- [ ] **Step 1: Boot CoQ with `LLMOfQud` only enabled.**

In the in-game Mods list, disable any other user mod. Confirm a single-mod load order (`1: LLMOfQud`).

- [ ] **Step 2: Start a fresh Mutated Human Marauder, advance past chargen.**

Use the same chargen path as Phase 0-E's Mutant Marauder run (160-turn precedent). Skip / dismiss the tutorial popup if it appears.

- [ ] **Step 3: Open the wish console and pick a candidate blueprint.**

Wish console keystroke: `Ctrl+W` in debug builds; the standard release build uses `wish:` from a debug menu. Try each candidate in order and accept the first that satisfies all four sub-checks below:

Candidates (in priority order):

1. `Glowfish` — small wildlife, baseline hostile in the Joppa watervine area.
2. `Salt-spider` — slightly tougher, baseline hostile in the salt areas.
3. `Mutant Hero` — generic mutant testhero spawn.
4. `goatfolk_hunter` — humanoid hostile.

Issue:

```
wish testhero:Glowfish
```

This invokes `Wishing.cs:255-260` semantics: the spawned object is placed in the cell east of the player and "activated" (typically meaning aggro toward the player).

- [ ] **Step 4: Verify hostility post-spawn (4 sub-checks).**

For the candidate to PASS:

1. **Spawn succeeds**: a creature appears one cell east of the player. If the wish silently fails (e.g., blueprint name typo), try the next candidate.
2. **Hostile flag set**: open the look-at panel (`l`, then aim east) — the creature shows `(hostile)` or red highlight. If neutral / friendly, the blueprint stays out of consideration even if Step 5 would catch it.
3. **No immediate disengagement**: wait one turn (press `5` / pass turn). The creature MUST remain in the cell east of the player or attempt to attack. If it wanders away or becomes non-hostile, try the next candidate.
4. **`GetCombatTarget` resolves it**: enable the CoQ debug overlay if available; alternatively, this sub-check is deferred until Task 7 acceptance run reads the actual `[cmd]` log lines and confirms `target_id` is non-null. If sub-checks 1–3 pass, accept the blueprint provisionally and verify sub-check 4 during Task 7. If Task 7 reveals `target_id == null` despite an apparent adjacent hostile, return to this task with the next candidate.

- [ ] **Step 5: Record the chosen blueprint in `phase-0-f-blueprint.txt` (operator-local note).**

```bash
echo "Phase 0-F Step B blueprint: <chosen_blueprint>" > /tmp/phase-0-f-blueprint.txt
echo "Probed at: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /tmp/phase-0-f-blueprint.txt
echo "Joppa zone used: <zone_id from in-game Wish>" >> /tmp/phase-0-f-blueprint.txt
```

This file is operator-local and not committed. The blueprint name goes into Task 7 Step 1 verbatim.

---

## Task 2: Extract `AppendJsonStringOrNull` / `AppendJsonIntOrNull` helpers + migrate 4 existing call sites

**Why this task exists:** Phase 0-E exit memo rule 5 (`docs/memo/phase-0-e-exit-2026-04-26.md:60`) commits to extracting an `AppendJsonStringOrNull(sb, value)` helper "when a 5th occurrence lands". Phase 0-F adds 5 nullable string-or-object fields (`target_id`, `target_name`, `target_pos_before`, `target_hp_before`, `target_hp_after`) — the threshold is met. This task does the extraction + migrates the existing 4 nullable-string call sites in `SnapshotState.cs` (`genotype_id`, `subtype_id`, `hunger`, `thirst`) BEFORE Task 3 adds the new builders, so Task 3 can use the helper from the start.

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` (extract helpers, migrate 4 sites)

**Branch:** `feat/phase-0-f-impl` (cut from `main` after PR-F1 merges).

- [ ] **Step 1: Cut the implementation branch from `main`.**

```bash
git switch main
git pull
git switch -c feat/phase-0-f-impl
```

Verify:

```bash
git log --oneline main -3
```

The latest commit on `main` should include ADR 0006 + plan + spec from PR-F1. If it doesn't, PR-F1 has not landed yet — wait.

- [ ] **Step 2: Read the current `AppendJsonString` and identify the 4 call sites.**

```bash
grep -n "AppendJsonString" mod/LLMOfQud/SnapshotState.cs
```

Expected: `AppendJsonString` definition (around `:30-47` per the spec citation) plus call sites for `genotype_id`, `subtype_id`, `hunger`, `thirst` in the build-section helpers, plus the existing `[caps]` / `[state]` call sites that are NOT being migrated. Identify exactly 4 call sites where the current code is the workaround pattern:

```csharp
if (x == null) sb.Append("null"); else AppendJsonString(sb, x);
```

These are the 4 sites flagged in `phase-0-e-exit-2026-04-26.md:60`.

- [ ] **Step 3: Add `AppendJsonStringOrNull` and `AppendJsonIntOrNull` helpers after the existing `AppendJsonString`.**

```csharp
        // Emits JSON `null` when value is null; otherwise delegates to AppendJsonString.
        // Phase 0-E exit memo rule 5: extract this helper at the 5th nullable-string
        // call site. Phase 0-F adds target_id/name/pos_before/hp_before/hp_after — 5
        // new sites — pushing past the threshold. The 4 pre-existing call sites
        // (genotype_id, subtype_id, hunger, thirst) are migrated to this helper in
        // the same Phase 0-F change.
        public static void AppendJsonStringOrNull(StringBuilder sb, string s)
        {
            if (s == null)
            {
                sb.Append("null");
                return;
            }
            AppendJsonString(sb, s);
        }

        // Emits JSON `null` for null int?; otherwise the integer value as digits.
        // Used by Phase 0-F target_hp_before / target_hp_after / target_pos_before.x
        // / .y where the absence of a target is represented as JSON null rather than
        // a magic sentinel like -1.
        public static void AppendJsonIntOrNull(StringBuilder sb, int? n)
        {
            if (!n.HasValue)
            {
                sb.Append("null");
                return;
            }
            sb.Append(n.Value);
        }
```

Both methods are `public static` to match `AppendJsonString`'s visibility and to be callable from both the new `BuildCmdJson` and the existing `BuildBuildJson`.

- [ ] **Step 4: Migrate the 4 existing call sites.**

For each of the 4 sites identified in Step 2, replace:

```csharp
if (x == null) sb.Append("null"); else AppendJsonString(sb, x);
```

with:

```csharp
AppendJsonStringOrNull(sb, x);
```

Concretely, the targets are inside `AppendBuildIdentity` (genotype_id, subtype_id) and `AppendBuildResources` (hunger, thirst). Use `grep -n "Append(\"null\")" mod/LLMOfQud/SnapshotState.cs` to locate them precisely.

- [ ] **Step 5: Compile + load probe.**

Drop the symlink in place (already there from Phase 0-A) and launch CoQ. Tail `build_log.txt`:

```bash
tail -f "$COQ_SAVE_DIR/build_log.txt" &
```

Quit CoQ after the load probe line emits. Expected `build_log.txt` contains:

```
Compiling 3 files... Success :)
[LLMOfQud] loaded v0.0.1 at <ISO timestamp>
```

No `COMPILER ERRORS` for `LLMOfQud`. No `MODWARN`.

If the compile fails, the most likely cause is a typo in the new helper signature or a wrong helper visibility. Fix and re-launch CoQ.

- [ ] **Step 6: Quick runtime sanity check — Phase 0-E parity is preserved.**

Open a Phase 0-E save (Mutant Marauder), advance one turn, quit. Run:

```bash
grep "INFO - \[LLMOfQud\]\[build\]" "$PLAYER_LOG" | tail -1 | cut -d' ' -f5- | python3 -c "import sys, json; print(json.loads(sys.stdin.read().strip()))"
```

Expected: the latest `[build]` line still parses as JSON and shows the existing 9-key shape. If `genotype_id` / `subtype_id` / `hunger` / `thirst` are now broken (e.g., emitting `"null"` literal-quoted instead of unquoted JSON null), the migration in Step 4 was wrong — fix and re-test.

- [ ] **Step 7: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "$(cat <<'EOF'
refactor(mod): extract AppendJsonStringOrNull / AppendJsonIntOrNull helpers

Phase 0-E exit memo rule 5 (docs/memo/phase-0-e-exit-2026-04-26.md:60)
committed to extracting these helpers when the 5th nullable-string
call site landed. Phase 0-F adds target_id/name/pos_before/
hp_before/hp_after — 5 new nullable sites — meeting the threshold.
This commit extracts the helpers and migrates the 4 pre-existing
call sites (genotype_id, subtype_id, hunger, thirst) to use them.

Phase 0-E [build] runtime output is unchanged; the migration is a
pure refactor (verified by JSON-parse spot-check of the latest [build]
line on a Phase 0-E save).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add `BuildCmdJson` and `BuildCmdSentinelJson` builders in `SnapshotState`

**Why this task exists:** The full-record and sentinel JSON shapes for `[cmd]` are locked in the spec. Centralizing the builders in `SnapshotState.cs` (alongside `BuildStateJson` / `BuildCapsJson` / `BuildBuildJson`) keeps the single-source-of-truth pattern Phase 0-D / 0-E established. The handler in Task 4 consumes these builders rather than inlining `StringBuilder` walks.

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs`

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Choose between positional parameters and a parameter struct.**

The full-record builder takes 17 fields (Phase 0-F design spec schema lock). A positional method signature is brittle (long parameter list, easy to mis-order). A parameter struct (`CmdRecord`) is clearer and matches the Phase 0-D `[caps]` precedent of grouping a coherent payload. Use a parameter struct.

- [ ] **Step 2: Add the `CmdRecord` struct + the two builders to `SnapshotState.cs`.**

Insert after the existing `BuildBuildJson` method:

```csharp
        // Phase 0-F command_issuance.v1 record fields. Plain struct — no behavior.
        // The handler populates it inside HandleEvent(CommandTakeActionEvent),
        // BuildCmdJson serializes it. Field order in this struct is a hint to
        // emission order but BuildCmdJson dictates the canonical JSON field order
        // (the spec schema lock). Do not reorder fields here without also
        // updating BuildCmdJson — and never both without an ADR (the schema is
        // locked at v1).
        internal struct CmdRecord
        {
            public int Turn;
            public string Action;            // "Move" | "AttackDirection"
            public string Dir;               // "N" | "NE" | ... | "NW"  (never null in v1)
            public bool Result;
            public string Fallback;          // null | "pass_turn"
            public int EnergyBefore;
            public int EnergyAfter;
            public int PosBeforeX;
            public int PosBeforeY;
            public string PosBeforeZone;
            public int PosAfterX;
            public int PosAfterY;
            public string PosAfterZone;
            public string TargetId;          // null when no hostile attacked
            public string TargetName;        // null when no hostile attacked
            public bool HasTargetPosBefore;  // discriminator for {x,y,zone} | null
            public int TargetPosBeforeX;
            public int TargetPosBeforeY;
            public string TargetPosBeforeZone;
            public int? TargetHpBefore;
            public int? TargetHpAfter;
        }

        // Builds the value of [LLMOfQud][cmd] line for the success / expected-fallback
        // path. Caller prepends the "[LLMOfQud][cmd] " prefix at the LogInfo call site.
        // Field order is the schema lock at command_issuance.v1; reordering requires
        // an ADR.
        public static string BuildCmdJson(CmdRecord r)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append('{');
            sb.Append("\"turn\":").Append(r.Turn);
            sb.Append(",\"schema\":\"command_issuance.v1\"");
            sb.Append(",\"hook\":\"CommandTakeActionEvent\"");
            sb.Append(",\"action\":");
            AppendJsonString(sb, r.Action);
            sb.Append(",\"dir\":");
            AppendJsonString(sb, r.Dir);
            sb.Append(",\"result\":").Append(r.Result ? "true" : "false");
            sb.Append(",\"fallback\":");
            AppendJsonStringOrNull(sb, r.Fallback);
            sb.Append(",\"energy_before\":").Append(r.EnergyBefore);
            sb.Append(",\"energy_after\":").Append(r.EnergyAfter);
            sb.Append(",\"pos_before\":");
            AppendPosObject(sb, r.PosBeforeX, r.PosBeforeY, r.PosBeforeZone);
            sb.Append(",\"pos_after\":");
            AppendPosObject(sb, r.PosAfterX, r.PosAfterY, r.PosAfterZone);
            sb.Append(",\"target_id\":");
            AppendJsonStringOrNull(sb, r.TargetId);
            sb.Append(",\"target_name\":");
            AppendJsonStringOrNull(sb, r.TargetName);
            sb.Append(",\"target_pos_before\":");
            if (r.HasTargetPosBefore)
            {
                AppendPosObject(sb, r.TargetPosBeforeX, r.TargetPosBeforeY, r.TargetPosBeforeZone);
            }
            else
            {
                sb.Append("null");
            }
            sb.Append(",\"target_hp_before\":");
            AppendJsonIntOrNull(sb, r.TargetHpBefore);
            sb.Append(",\"target_hp_after\":");
            AppendJsonIntOrNull(sb, r.TargetHpAfter);
            sb.Append(",\"error\":null");
            sb.Append('}');
            return sb.ToString();
        }

        // Reduced sentinel shape consistent with Phase 0-D [caps] / 0-E [build]
        // sentinels: {turn, schema, error:{type, message}}. Used when HandleEvent
        // (CommandTakeActionEvent) catches an exception. AppendJsonString is used
        // for type/message so RFC-8259 control-character escapes (U+0000-U+001F,
        // U+2028, U+2029) are correct even when ex.Message has tab / newline / etc.
        public static string BuildCmdSentinelJson(int turn, Exception ex)
        {
            StringBuilder sb = new StringBuilder(256);
            sb.Append('{');
            sb.Append("\"turn\":").Append(turn);
            sb.Append(",\"schema\":\"command_issuance.v1\"");
            sb.Append(",\"error\":{\"type\":");
            AppendJsonString(sb, ex.GetType().Name);
            sb.Append(",\"message\":");
            AppendJsonString(sb, ex.Message ?? "");
            sb.Append("}}");
            return sb.ToString();
        }

        // Inline helper: emit a {"x":N,"y":N,"zone":"..."} object. Mirrors the shape
        // [state] uses (SnapshotState.cs:206-211 — pos-of-player). zone is the
        // GameObject.CurrentCell.ParentZone.ZoneID string. Emits zone via
        // AppendJsonStringOrNull so a player whose CurrentCell.ParentZone is somehow
        // null (defensive — should never happen for a positioned object) emits
        // "zone":null instead of crashing the line build.
        private static void AppendPosObject(StringBuilder sb, int x, int y, string zone)
        {
            sb.Append("{\"x\":").Append(x);
            sb.Append(",\"y\":").Append(y);
            sb.Append(",\"zone\":");
            AppendJsonStringOrNull(sb, zone);
            sb.Append('}');
        }
```

**Add `using System;` to the top of `SnapshotState.cs`.** Current file has `using System.Collections.Generic; using System.Globalization; using System.Text;` etc. but NOT `using System;`. `BuildCmdSentinelJson` uses `Exception`, which lives in `System` — without the using, `Exception` does not resolve. Insert at the top of the using block:

```csharp
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using XRL;
... // rest unchanged
```

`StringBuilder` is already imported via `using System.Text;`.

- [ ] **Step 3: Compile + load probe (no runtime behavior change yet).**

Launch CoQ, observe `build_log.txt`:

```
Compiling 3 files... Success :)
[LLMOfQud] loaded v0.0.1 at <timestamp>
```

No `COMPILER ERRORS` for `LLMOfQud`. The new builders are not yet called by any caller, so there is no runtime behavior change — but they must compile.

- [ ] **Step 4: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "$(cat <<'EOF'
feat(mod): add BuildCmdJson / BuildCmdSentinelJson for command_issuance.v1

Phase 0-F. Adds the two static builders SnapshotState exposes for
[LLMOfQud][cmd]. Schema locked at command_issuance.v1 per
docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md
and ADR 0006:
- Full record: 17 keys, including pos_before/pos_after as {x,y,zone}.
- Sentinel: reduced {turn, schema, error:{type, message}}.

Internal CmdRecord struct groups the 17 fields the handler will
populate in Task 4 (HandleEvent registration + Step A) and Task 5
(Step B detection); using a struct over a 17-positional method
signature is a brittleness reduction.

No HandleEvent caller yet — added in Task 4. Compile-only landing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Register `CommandTakeActionEvent` + implement Step A

**Why this task exists:** This is the first task that runtime-actually-acts. After this task lands, the player moves east one cell per turn autonomously. Step B detection is added in Task 5 — keeping Step A independently landable lets us catch any keyboard-fallback / energy-drain regression on the simpler movement-only case before adding combat.

**Files:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Add the `using XRL.World.Capabilities;` directive.**

At the top of `mod/LLMOfQud/LLMOfQudSystem.cs`, add the new using next to the existing ones:

```csharp
using System;
using System.Text;
using System.Threading;
using ConsoleLib.Console;
using XRL;
using XRL.Core;
using XRL.UI;
using XRL.World;
using XRL.World.Capabilities;   // NEW: AutoAct.ClearAutoMoveStop
```

- [ ] **Step 2: Register the new event in `RegisterPlayer`.**

Find the existing line:

```csharp
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
```

Add the new registration on the next line:

```csharp
            Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
            Registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID);
```

Both registrations must run in `RegisterPlayer` (not in `Bootstrap` or static ctor) so the IPlayerSystem dispatch table picks them up correctly. Verified pattern: `decompiled/XRL/WanderSystem.cs:57-60` — the engine itself registers events this way.

- [ ] **Step 3: Add `HandleEvent(CommandTakeActionEvent E)` — Step A only (movement east + 3-layer drain).**

Insert the new method after the existing `HandleEvent(BeginTakeActionEvent)` and BEFORE `SnapshotAscii`. The Step B detection branch is added in Task 5; Task 4 lands with a hardcoded "always Move E" body so Step A is testable in isolation.

```csharp
        // Phase 0-F: act on the player's command point.
        // Hook chosen per ADR 0006: CommandTakeActionEvent fires inside the inner
        // action loop in ActionManager (decompiled/XRL.Core/ActionManager.cs:829),
        // AFTER BeginTakeActionEvent has already enqueued the per-turn observation
        // snapshot. Acting here keeps EndActionEvent, hostile interrupt, AutoAct,
        // and the player render fallback (ActionManager.cs:1806-1808) intact.
        // BeginTakeActionEvent would skip all of those because draining energy
        // there fails the inner loop's gate at :800.
        // [cmd] is emitted on the game thread directly (NOT through PendingSnapshot)
        // — see ADR 0006 Consequence #3 and the design spec's Architecture section.
        public override bool HandleEvent(CommandTakeActionEvent E)
        {
            int turn = _beginTurnCount;
            GameObject player = The.Player;

            // Defensive: HandleEvent should not fire when player is null (the
            // event is dispatched against the player object), but a body-swap
            // window or shutdown race could leave us with no player. Emit a
            // sentinel and let the loop fall through.
            if (player == null)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] {\"turn\":" + turn +
                    ",\"schema\":\"command_issuance.v1\",\"error\":{\"type\":\"NullPlayer\",\"message\":\"The.Player is null\"}}");
                E.PreventAction = true;
                return true;
            }

            int energyBefore = 0;
            try
            {
                energyBefore = player.Energy?.Value ?? 0;
                Cell cellBefore = player.CurrentCell;
                int posBeforeX = cellBefore?.X ?? -1;
                int posBeforeY = cellBefore?.Y ?? -1;
                string posBeforeZone = cellBefore?.ParentZone?.ZoneID;

                // Step A: hardcoded Move East. Step B detection is added in Task 5.
                AutoAct.ClearAutoMoveStop();   // mirror XRLCore.cs:1108 wrapper
                bool result = player.Move("E", DoConfirmations: false);

                bool energySpent = (player.Energy != null && player.Energy.Value < energyBefore);

                string fallback = null;
                if (!result && !energySpent)
                {
                    // Layer 2: action returned false without spending energy.
                    // PassTurn() => UseEnergy(1000, "Pass", Passive:true) so the
                    // turn advances and the engine doesn't fall through to
                    // PlayerTurn() waiting on keyboard input.
                    player.PassTurn();
                    energySpent = true;
                    fallback = "pass_turn";
                }
                else if (!result)
                {
                    // API drained energy on its own fail path (e.g., flag=true
                    // dashing case at GameObject.cs:15309 -> :15378-15382). Log as
                    // pass_turn for accounting; the autonomy invariant
                    // energy_after < energy_before still holds.
                    fallback = "pass_turn";
                }

                int energyAfter = player.Energy?.Value ?? 0;
                Cell cellAfter = player.CurrentCell;

                SnapshotState.CmdRecord rec = new SnapshotState.CmdRecord
                {
                    Turn = turn,
                    Action = "Move",
                    Dir = "E",
                    Result = result,
                    Fallback = fallback,
                    EnergyBefore = energyBefore,
                    EnergyAfter = energyAfter,
                    PosBeforeX = posBeforeX,
                    PosBeforeY = posBeforeY,
                    PosBeforeZone = posBeforeZone,
                    PosAfterX = cellAfter?.X ?? -1,
                    PosAfterY = cellAfter?.Y ?? -1,
                    PosAfterZone = cellAfter?.ParentZone?.ZoneID,
                    TargetId = null,
                    TargetName = null,
                    HasTargetPosBefore = false,
                    TargetHpBefore = null,
                    TargetHpAfter = null,
                };

                MetricsManager.LogInfo("[LLMOfQud][cmd] " + SnapshotState.BuildCmdJson(rec));
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] " + SnapshotState.BuildCmdSentinelJson(turn, ex));
                // Layer 3 ladder: if energy hasn't drained yet, try PassTurn first;
                // if that also throws, set BaseValue=0 as a last-ditch emergency
                // drain. ADR 0006 Consequence #5: BaseValue=0 is intentionally NOT
                // equivalent to PassTurn — it bypasses UseEnergyEvent
                // (decompiled/XRL.World/GameObject.cs:2925-2930). Direct BaseValue=0
                // only runs the Statistic setter and NotifyChange
                // (decompiled/XRL.World/Statistic.cs:218-232) and may fire
                // StatChange_* listeners (:646-673), but no UseEnergyEvent. Use
                // ONLY when PassTurn() itself throws.
                // The threshold is the loop-gate condition (ActionManager.cs:800,
                // :838): the engine reaches PlayerTurn() at :1797-1799 only when
                // Energy.Value >= 1000. Compare against literal 1000 — NOT
                // energyBefore — because (a) the exception may have fired BEFORE
                // energyBefore was captured (initial value 0 → guard would skip
                // drain incorrectly), (b) the autonomy invariant is "engine does
                // not wait on keyboard input", which only depends on whether
                // energy stays >= 1000 after our handler returns.
                if (player?.Energy != null && player.Energy.Value >= 1000)
                {
                    try { player.PassTurn(); } catch { /* swallow */ }
                    if (player.Energy.Value >= 1000)
                    {
                        player.Energy.BaseValue = 0;
                    }
                }
            }
            finally
            {
                // PreventAction = true makes CommandTakeActionEvent.Check return
                // false, which causes ActionManager.cs:829-832's inner-loop continue
                // to skip the rest of the action path for this segment. Combined
                // with energy drain (Layers 1/2/3 above), this is what guarantees
                // the engine never falls through to The.Core.PlayerTurn() at
                // :1797-1799 waiting on keyboard input.
                E.PreventAction = true;
            }

            // Return true. Returning false would abort event dispatch — other
            // handlers registered on CommandTakeActionEvent would not fire. The
            // EventRegistry chain stops on false (decompiled/XRL.Collections/
            // EventRegistry.cs:260-272); the GameObject parts/effects chain stops
            // on false (decompiled/XRL.World/GameObject.cs:14024-14030, 14053-14059).
            // PreventAction=true is the proper "skip this action" signal.
            return true;
        }
```

Catch-path drain threshold is the literal `>= 1000`, not `>= energyBefore`. Rationale: the exception may fire BEFORE `energyBefore = player.Energy?.Value ?? 0` runs, leaving `energyBefore = 0` (the local's initial value). With `>= energyBefore` the guard would say "we have enough" and SKIP the drain — leaving energy at its actual >= 1000 level and the loop falling through to PlayerTurn() waiting on keyboard input. The literal `>= 1000` matches the loop-gate condition at `decompiled/XRL.Core/ActionManager.cs:800, 838` (which gates whether `PlayerTurn()` is called at `:1797-1799`).

- [ ] **Step 4: Compile + load probe.**

Launch CoQ, watch `build_log.txt`. Expected:

```
Compiling 3 files... Success :)
[LLMOfQud] loaded v0.0.1 at <timestamp>
```

No `COMPILER ERRORS`. If `AutoAct.ClearAutoMoveStop` does not resolve, double-check the `using XRL.World.Capabilities;` directive in Step 1 and verify against `decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`.

- [ ] **Step 5: Quick runtime probe — one east move on a Phase 0-E save.**

Open a Phase 0-E save (Mutant Marauder) in Joppa central. Press `5` once (pass — wait, that's keyboard input — actually do not press anything, the autonomous handler should fire on the next `CommandTakeActionEvent`). Actually, the player is currently positioned in a known cell; observe whether the player advances east one cell over the next turn.

Tail `Player.log`:

```bash
tail -f "$PLAYER_LOG" | grep "INFO - \[LLMOfQud\]\[cmd\]" &
```

Expected: a single `[cmd]` line per dispatch with `action:"Move", dir:"E", result:true, energy_before:1000, energy_after:0, pos_after.x = pos_before.x + 1`.

If the player does NOT advance OR keyboard input is required to make the next dispatch fire, the `PreventAction` / `return true` / 3-layer drain are not working as designed. Diagnose by adding temporary `MetricsManager.LogInfo` debug lines BEFORE / AFTER each step in `HandleEvent` to identify the failure point.

- [ ] **Step 6: Commit.**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "$(cat <<'EOF'
feat(mod): Phase 0-F Step A — autonomous Move("E") via CommandTakeActionEvent

Phase 0-F first runtime-active commit. Registers
CommandTakeActionEvent in RegisterPlayer; HandleEvent(
CommandTakeActionEvent) hardcodes Move("E", DoConfirmations:false)
each turn and emits one [LLMOfQud][cmd] LogInfo line per dispatch.

Architecture per ADR 0006:
- Hook = CommandTakeActionEvent (inside ActionManager's inner action
  loop, NOT BeginTakeActionEvent which fires before the loop).
- API = direct GameObject.Move (NOT CommandEvent.Send).
- AutoAct.ClearAutoMoveStop() called explicitly to mirror the
  decompiled/XRL.Core/XRLCore.cs:1108 keypress wrapper.
- 3-layer drain: API success drains via UseEnergy; PassTurn() on
  result==false; Energy.BaseValue=0 as last-ditch only when PassTurn
  itself throws (intentionally NOT equivalent — no UseEnergyEvent).
- E.PreventAction=true in finally; return true (NOT false; would
  abort event dispatch chain).
- [cmd] emitted from game thread directly via MetricsManager.LogInfo,
  decoupled from AfterRenderCallback render cadence.

Step B (adjacent-hostile detection -> AttackDirection) lands in the
next commit. Step A alone is testable in isolation: player walks east
one cell per turn; if a hostile is adjacent east, Move resolves it as
combat (per Move's combat-object path at decompiled/XRL.World/GameObject.cs:15344-15346)
which we accept as a known v1 limitation until Task 5 makes the
hostile detection + Attack* explicit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add Step B — adjacent-hostile detection + `AttackDirection`

**Why this task exists:** Step A's hardcoded `Move("E")` does not honestly satisfy the spec line `:2803`'s "and attack" half. Codex flagged this in the brainstorming round: a `Move` against an adjacent hostile resolves through Move's combat-object path which is subtly different from the canonical `AttackDirection` flow. Task 5 makes the attack path explicit and provides the correct `target_id` / `target_hp_before` / `target_hp_after` capture the schema requires.

**Files:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs` (replace the hardcoded Step A body with the Step A + Step B body)

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Replace the body of `HandleEvent(CommandTakeActionEvent)` to add Step B detection BEFORE the Step A move.**

Replace the entire `HandleEvent(CommandTakeActionEvent)` method body (the version from Task 4) with:

```csharp
        public override bool HandleEvent(CommandTakeActionEvent E)
        {
            int turn = _beginTurnCount;
            GameObject player = The.Player;

            if (player == null)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] {\"turn\":" + turn +
                    ",\"schema\":\"command_issuance.v1\",\"error\":{\"type\":\"NullPlayer\",\"message\":\"The.Player is null\"}}");
                E.PreventAction = true;
                return true;
            }

            int energyBefore = 0;
            try
            {
                energyBefore = player.Energy?.Value ?? 0;
                Cell cellBefore = player.CurrentCell;
                int posBeforeX = cellBefore?.X ?? -1;
                int posBeforeY = cellBefore?.Y ?? -1;
                string posBeforeZone = cellBefore?.ParentZone?.ZoneID;

                // Step B: adjacent hostile detection.
                // Direction priority: N -> NE -> E -> SE -> S -> SW -> W -> NW.
                // First non-null Cell.GetCombatTarget hit wins.
                // The filter o => o != player && o.IsHostileTowards(player) mirrors
                // what Combat.AttackCell uses internally (Combat.cs:877-889).
                string targetDir = null;
                GameObject targetObj = null;
                if (cellBefore != null)
                {
                    string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
                    for (int i = 0; i < priority.Length; i++)
                    {
                        Cell adj = cellBefore.GetCellFromDirection(priority[i], BuiltOnly: false);
                        if (adj == null) continue;
                        // Verified signature at decompiled/XRL.World/Cell.cs:8511:
                        //   GetCombatTarget(GameObject Attacker = null,
                        //     bool IgnoreFlight = false, bool IgnoreAttackable = false,
                        //     bool IgnorePhase = false, int Phase = 0,
                        //     GameObject Projectile = null, GameObject Launcher = null,
                        //     GameObject CheckPhaseAgainst = null,
                        //     GameObject Skip = null, List<GameObject> SkipList = null,
                        //     bool AllowInanimate = true, bool InanimateSolidOnly = false,
                        //     Predicate<GameObject> Filter = null)
                        // GameObject.cs:10887-10894 IsHostileTowards.
                        GameObject t = adj.GetCombatTarget(
                            Attacker: player,
                            IgnoreFlight: false,
                            IgnoreAttackable: false,
                            IgnorePhase: false,
                            Phase: 5,
                            AllowInanimate: false,
                            Filter: o => o != player && o.IsHostileTowards(player));
                        if (t != null)
                        {
                            targetDir = priority[i];
                            targetObj = t;
                            break;
                        }
                    }
                }

                bool result;
                string action;
                string dir;
                string targetId = null;
                string targetName = null;
                bool hasTargetPosBefore = false;
                int targetPosBeforeX = -1;
                int targetPosBeforeY = -1;
                string targetPosBeforeZone = null;
                int? targetHpBefore = null;

                if (targetObj != null)
                {
                    targetId = targetObj.ID;
                    targetName = targetObj.ShortDisplayNameStripped;
                    Cell tCell = targetObj.CurrentCell;
                    if (tCell != null)
                    {
                        hasTargetPosBefore = true;
                        targetPosBeforeX = tCell.X;
                        targetPosBeforeY = tCell.Y;
                        targetPosBeforeZone = tCell.ParentZone?.ZoneID;
                    }
                    // hitpoints = Statistic.Value (live HP), per spec field semantics.
                    // GameObject.cs:1177-1198: hitpoints / baseHitpoints.
                    targetHpBefore = targetObj.hitpoints;
                    result = player.AttackDirection(targetDir);
                    action = "AttackDirection";
                    dir = targetDir;
                }
                else
                {
                    // Step A fallback: Move East.
                    AutoAct.ClearAutoMoveStop();   // mirror XRLCore.cs:1108
                    result = player.Move("E", DoConfirmations: false);
                    action = "Move";
                    dir = "E";
                }

                bool energySpent = (player.Energy != null && player.Energy.Value < energyBefore);

                string fallback = null;
                if (!result && !energySpent)
                {
                    player.PassTurn();
                    energySpent = true;
                    fallback = "pass_turn";
                }
                else if (!result)
                {
                    fallback = "pass_turn";
                }

                int? targetHpAfter = (targetObj != null) ? (int?)targetObj.hitpoints : null;
                int energyAfter = player.Energy?.Value ?? 0;
                Cell cellAfter = player.CurrentCell;

                SnapshotState.CmdRecord rec = new SnapshotState.CmdRecord
                {
                    Turn = turn,
                    Action = action,
                    Dir = dir,
                    Result = result,
                    Fallback = fallback,
                    EnergyBefore = energyBefore,
                    EnergyAfter = energyAfter,
                    PosBeforeX = posBeforeX,
                    PosBeforeY = posBeforeY,
                    PosBeforeZone = posBeforeZone,
                    PosAfterX = cellAfter?.X ?? -1,
                    PosAfterY = cellAfter?.Y ?? -1,
                    PosAfterZone = cellAfter?.ParentZone?.ZoneID,
                    TargetId = targetId,
                    TargetName = targetName,
                    HasTargetPosBefore = hasTargetPosBefore,
                    TargetPosBeforeX = targetPosBeforeX,
                    TargetPosBeforeY = targetPosBeforeY,
                    TargetPosBeforeZone = targetPosBeforeZone,
                    TargetHpBefore = targetHpBefore,
                    TargetHpAfter = targetHpAfter,
                };

                MetricsManager.LogInfo("[LLMOfQud][cmd] " + SnapshotState.BuildCmdJson(rec));
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][cmd] " + SnapshotState.BuildCmdSentinelJson(turn, ex));
                // Catch-path drain threshold = literal 1000, NOT energyBefore.
                // See Task 4 commentary: the exception may fire before energyBefore
                // is captured, in which case the local default of 0 would make a
                // ">= energyBefore" guard incorrectly skip drain. The autonomy
                // invariant is "engine does not wait on keyboard input"; that
                // depends only on Energy.Value < 1000 after our handler returns
                // (ActionManager.cs:800, :838, :1797-1799).
                if (player?.Energy != null && player.Energy.Value >= 1000)
                {
                    try { player.PassTurn(); } catch { /* swallow */ }
                    if (player.Energy.Value >= 1000)
                    {
                        player.Energy.BaseValue = 0;
                    }
                }
            }
            finally
            {
                E.PreventAction = true;
            }

            return true;
        }
```

The lambda `Filter: o => o != player && o.IsHostileTowards(player)` is a `Predicate<GameObject>` — matches the signature at `decompiled/XRL.World/Cell.cs:8511-8557`. The `cellBefore != null` guard around the priority loop is defensive: a player without a `CurrentCell` (briefly during zone transitions) falls through to Step A.

- [ ] **Step 2: Compile + load probe.**

Launch CoQ:

```
Compiling 3 files... Success :)
[LLMOfQud] loaded v0.0.1 at <timestamp>
```

No `COMPILER ERRORS`. If `Predicate<GameObject>` doesn't resolve, ensure the `using System;` directive is in scope (it is — already at the top of the file from Task 4). If `targetObj.hitpoints` doesn't compile, double-check the property name (it is lowercase `hitpoints` per `decompiled/XRL.World/GameObject.cs:1177-1198`).

- [ ] **Step 3: Quick runtime probe — east-walk run on a Phase 0-E save.**

Open the Phase 0-E Marauder save in Joppa central. Watch the player walk east. The behavior should be identical to Task 4 (no adjacent hostiles in central market lane). Tail:

```bash
tail -f "$PLAYER_LOG" | grep "INFO - \[LLMOfQud\]\[cmd\]" &
```

Expect: every `[cmd]` line still shows `action:"Move", dir:"E"`, `target_id:null`, etc. The Step B branch is defined but never enters because no adjacent hostile.

- [ ] **Step 4: Quick runtime probe — `wish testhero:<blueprint>` confirms Step B fires.**

While the player is in a clear lane, open the wish console and spawn the blueprint chosen in Task 1:

```
wish testhero:<blueprint>
```

Wait one turn. The next `[cmd]` line should now show `action:"AttackDirection"`, `dir:"E"` (or whichever direction the spawn lands in), `target_id:"<some object ID>"`, `target_name:"<blueprint display name>"`, `target_hp_before:<some int>`, `target_hp_after: <smaller or equal int>`.

If the line shows `action:"Move"` instead, Step B detection didn't fire. Diagnose: either (a) the blueprint isn't actually hostile (re-run Task 1's probe), (b) `Cell.GetCombatTarget` filter rejected the spawn (try removing the filter and logging directly to confirm any object is in the cell at all), or (c) the spawn was placed somewhere other than adjacent.

- [ ] **Step 5: Commit.**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "$(cat <<'EOF'
feat(mod): Phase 0-F Step B — adjacent-hostile detection + AttackDirection

Phase 0-F second runtime-active commit. Adds Step B to the
HandleEvent(CommandTakeActionEvent) body: walks the 8 adjacent cells
in N->NE->E->SE->S->SW->W->NW priority order via
Cell.GetCellFromDirection + Cell.GetCombatTarget with the
o => o != player && o.IsHostileTowards(player) filter. First non-null
hit wins; calls The.Player.AttackDirection(dir) instead of Move.
Falls through to Step A's Move("E", DoConfirmations:false) when no
adjacent hostile.

Captures target_id (GameObject.ID), target_name
(ShortDisplayNameStripped), target_pos_before (x,y,zone object), and
target_hp_before/after (live hitpoints / Statistic.Value, NOT
baseHitpoints) for the [cmd] record.

Filter mirrors what Combat.AttackCell uses internally
(decompiled/XRL.World.Parts/Combat.cs:877-889) — same
GetCombatTarget call shape, identical semantics for "is there an
adjacent hostile? if so, which".

Direction priority is fixed; not derived from CoQ's internal direction
ordering (which is not a stable contract). Diagonal-first bias is
intentional per spec discussion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Step A acceptance run

**Why this task exists:** Per the design spec criterion 2: ≥10 successful east `Move` records, with a cross-channel ≥40-turn 5-channel-parity gate. This is the pure-movement acceptance with no Step B trigger.

**Files:** none (manual game session). The acceptance log artifact may be saved under `/tmp/phase-0-f-step-a-acceptance.log` for the exit memo to reference.

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Snapshot the current `Player.log` to baseline the run.**

```bash
cp "$PLAYER_LOG" "/tmp/phase-0-f-step-a-baseline.log"
```

This lets us isolate run-specific lines from older session content.

- [ ] **Step 2: Boot CoQ with `LLMOfQud` only enabled.**

Verify the Mods list shows single-mod load order. Skip / dismiss tutorial popups if they fire on a fresh character.

- [ ] **Step 3: Start a fresh Mutated Human Marauder.**

Same chargen as Phase 0-E's primary run (Mutant Marauder, default genotype + calling). Spawn → walk to Joppa central market clear east lane (operator-confirmed; if the spawn point is already in a clear lane, no manual movement needed).

- [ ] **Step 4: Let the autonomous handler run for ≥40 turns.**

Do NOT press any movement / action keys. The handler should walk the player east one cell per turn. Watch the in-game scroll; once ≥40 turns of `[cmd]` have logged (typically after ~30 seconds of game time at default speed), pause CoQ.

- [ ] **Step 5: Capture acceptance log artifact.**

```bash
diff "$PLAYER_LOG" "/tmp/phase-0-f-step-a-baseline.log" | grep "^<" | sed 's/^< //' > /tmp/phase-0-f-step-a-acceptance.log
```

Verify the artifact contains the run's lines:

```bash
grep -c "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-f-step-a-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[screen\] BEGIN" /tmp/phase-0-f-step-a-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[screen\] END" /tmp/phase-0-f-step-a-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[state\]" /tmp/phase-0-f-step-a-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[caps\]" /tmp/phase-0-f-step-a-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[build\]" /tmp/phase-0-f-step-a-acceptance.log
```

Expected: all six counts equal, each ≥ 40.

- [ ] **Step 6: Spot-check semantic invariants.**

Run this Python one-liner against the artifact to validate the criterion-8 invariants on every non-sentinel `[cmd]` line:

```bash
grep "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-f-step-a-acceptance.log | \
  sed 's/^.*\[LLMOfQud\]\[cmd\] //' | \
  python3 -c '
import sys, json
ok = bad = 0
EXPECTED_KEYS = {"turn","schema","hook","action","dir","result","fallback",
                 "energy_before","energy_after","pos_before","pos_after",
                 "target_id","target_name","target_pos_before",
                 "target_hp_before","target_hp_after","error"}
for ln, raw in enumerate(sys.stdin, 1):
    raw = raw.strip()
    if not raw: continue
    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"PARSE FAIL line {ln}: {e}")
        bad += 1; continue
    # Sentinel lines are tolerated (criterion 6) but counted separately.
    if "error" in d and d.get("error") and "type" in d.get("error", {}):
        print(f"SENTINEL line {ln}: {d}")
        continue
    if set(d.keys()) != EXPECTED_KEYS:
        print(f"KEYSET FAIL line {ln}: extra={set(d.keys())-EXPECTED_KEYS} missing={EXPECTED_KEYS-set(d.keys())}")
        bad += 1; continue
    if d["hook"] != "CommandTakeActionEvent": print(f"HOOK FAIL line {ln}"); bad += 1; continue
    if d["action"] != "Move" or d["dir"] != "E":
        print(f"ACTION/DIR FAIL line {ln}: {d['action']} {d['dir']}"); bad += 1; continue
    if d["target_id"] is not None or d["target_name"] is not None:
        print(f"STEP-A TARGET POPULATED line {ln}: {d}"); bad += 1; continue
    if d["energy_after"] >= d["energy_before"]:
        print(f"ENERGY FAIL line {ln}: before={d['energy_before']} after={d['energy_after']}"); bad += 1; continue
    if d["result"] is False and d["fallback"] != "pass_turn":
        print(f"FALLBACK FAIL line {ln}: {d}"); bad += 1; continue
    pa = d["pos_after"]; pb = d["pos_before"]
    if not (isinstance(pa, dict) and set(pa.keys()) == {"x","y","zone"}):
        print(f"POS_AFTER SHAPE FAIL line {ln}"); bad += 1; continue
    if not (isinstance(pb, dict) and set(pb.keys()) == {"x","y","zone"}):
        print(f"POS_BEFORE SHAPE FAIL line {ln}"); bad += 1; continue
    if d["result"] is True:
        if pa["x"] != pb["x"] + 1 or pa["y"] != pb["y"] or pa["zone"] != pb["zone"]:
            print(f"MOVE-EAST FAIL line {ln}: {pb} -> {pa}"); bad += 1; continue
    ok += 1
print(f"OK={ok} BAD={bad}")
'
```

Expected: `OK == <count of [cmd] lines minus any tolerated sentinels>`, `BAD == 0`.

- [ ] **Step 7: Verify wall-hit fallback if observed.**

If the run included a wall hit (player ran out of clear east cells), the artifact should contain at most ONE `[cmd]` line with `result:false, fallback:"pass_turn"` at the end of the run. The Python script above flags `STEP-A TARGET POPULATED` for any lines where target_* is not null, and `MOVE-EAST FAIL` for `result:true` records that didn't advance east — both are hard failures. A `result:false, fallback:"pass_turn"` line passes (the script does not flag it).

- [ ] **Step 8: Save the artifact + brief acceptance summary.**

```bash
cp /tmp/phase-0-f-step-a-acceptance.log /tmp/phase-0-f-acceptance/   # operator-local
echo "Step A acceptance: PASS — N=<count> lines, <count_e_moves> east moves, <count_walls> wall fallbacks" \
  >> /tmp/phase-0-f-acceptance/summary.txt
```

If the gate fails, the run does NOT pass. Diagnose by re-reading the failing lines, identify the root cause (often a corner case in `Move()` we didn't anticipate), fix the implementation, repeat from Step 1.

- [ ] **Step 9: Commit (no code change — Task 6 is a manual run).**

No commit. The acceptance run's outcome goes into the exit memo at Task 8.

---

## Task 7: Step B acceptance run

**Why this task exists:** Step A covers movement-only autonomy. Step B exercises the attack path with the deterministic `wish testhero:<blueprint>` setup pinned in Task 1. Per the design spec criterion 3: ≥3 consecutive `[cmd]` `AttackDirection` records, ≥1 with `result:true, target_hp_after < target_hp_before`, plus the same cross-channel ≥40-turn 5-channel-parity gate.

**Files:** none (manual game session). Acceptance log artifact under `/tmp/phase-0-f-step-b-acceptance.log`.

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Read the blueprint pinned in Task 1.**

```bash
cat /tmp/phase-0-f-blueprint.txt
```

The blueprint name is the constant for this run.

- [ ] **Step 2: Snapshot Player.log baseline.**

```bash
cp "$PLAYER_LOG" "/tmp/phase-0-f-step-b-baseline.log"
```

- [ ] **Step 3: Boot CoQ, fresh Mutant Marauder, walk to a position with at least one clear east cell behind for the wish-spawn cell.**

The wish spawns the blueprint east of the player. Pick a position where the east cell is empty AND walkable; an interior open Joppa room or street works. If the east cell is a wall, the spawn places the creature in the next available adjacent cell — which may not match Step B's priority-N expectation. Re-position if needed.

- [ ] **Step 4: Issue `wish testhero:<blueprint>` while AUTONOMOUS dispatch is active.**

The wish console requires keyboard input — open it via the operator-key (the user's bound key) and type `testhero:<blueprint>`. As soon as the wish console closes, the autonomous handler will fire on the next `CommandTakeActionEvent`. The first dispatch after the spawn should detect the hostile and emit `action:"AttackDirection"`.

- [ ] **Step 5: Let the autonomous handler attack until either ≥3 attack records emit OR the hostile dies OR the player dies.**

Do not press any keys. The handler walks the priority order; once the hostile is gone, Step B falls back to Step A and the run continues east-walking.

- [ ] **Step 6: Stop the run after ≥40 total `[cmd]` lines have logged.**

Pause CoQ. Capture the artifact:

```bash
diff "$PLAYER_LOG" "/tmp/phase-0-f-step-b-baseline.log" | grep "^<" | sed 's/^< //' > /tmp/phase-0-f-step-b-acceptance.log
```

- [ ] **Step 7: Verify cross-channel parity.**

```bash
grep -c "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-f-step-b-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[screen\] BEGIN" /tmp/phase-0-f-step-b-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[screen\] END" /tmp/phase-0-f-step-b-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[state\]" /tmp/phase-0-f-step-b-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[caps\]" /tmp/phase-0-f-step-b-acceptance.log
grep -c "INFO - \[LLMOfQud\]\[build\]" /tmp/phase-0-f-step-b-acceptance.log
```

Expected: all six equal, each ≥ 40 (BEGIN == END parity matches the gate from the design spec; if they diverge, a `[screen]` body walk threw mid-emit and the run does not pass).

- [ ] **Step 8: Verify Step B records semantic invariants.**

Run a Python script over the artifact to count attack records and verify HP delta on at least one:

```bash
grep "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-f-step-b-acceptance.log | \
  sed 's/^.*\[LLMOfQud\]\[cmd\] //' | \
  python3 -c '
import sys, json
attacks = []
for ln, raw in enumerate(sys.stdin, 1):
    raw = raw.strip()
    if not raw: continue
    try:
        d = json.loads(raw)
    except Exception:
        continue
    if d.get("action") == "AttackDirection":
        attacks.append((ln, d))
print(f"AttackDirection records: {len(attacks)}")
hits = [a for ln, a in attacks if a.get("result") is True
        and a.get("target_id") is not None
        and a.get("target_hp_before") is not None
        and a.get("target_hp_after") is not None
        and a["target_hp_after"] < a["target_hp_before"]]
print(f"Successful damaging attacks: {len(hits)}")
for a in hits[:3]:
    print(f"  target={a['target_name']} hp {a['target_hp_before']} -> {a['target_hp_after']} dir={a['dir']}")
assert len(attacks) >= 3, f"FAIL: need >=3 AttackDirection records, got {len(attacks)}"
assert len(hits) >= 1, f"FAIL: need >=1 successful damaging attack, got {len(hits)}"
print("STEP B GATE PASS")
'
```

Expected: `STEP B GATE PASS`. If the assertion fails, return to Task 1 and re-probe the blueprint OR re-position the player so the spawn lands in a Step-B-detectable cell.

- [ ] **Step 9: Run the full criterion-8 invariants over both Step A's artifact and Step B's artifact.**

Reuse the Step A Python script from Task 6 Step 6, but modify the assertion that "action == 'Move' and dir == 'E'" — for Step B, `action == "Move"` OR `action == "AttackDirection"` is allowed, and `dir` is whatever the priority scan resolved. The full `EXPECTED_KEYS` and `energy_after < energy_before` and `result==False ⇒ fallback=='pass_turn'` and pos shape gates still apply.

```bash
grep "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-f-step-b-acceptance.log | \
  sed 's/^.*\[LLMOfQud\]\[cmd\] //' | \
  python3 -c '
import sys, json
ok = bad = 0
EXPECTED_KEYS = {"turn","schema","hook","action","dir","result","fallback",
                 "energy_before","energy_after","pos_before","pos_after",
                 "target_id","target_name","target_pos_before",
                 "target_hp_before","target_hp_after","error"}
DIRS = {"N","NE","E","SE","S","SW","W","NW"}
for ln, raw in enumerate(sys.stdin, 1):
    raw = raw.strip()
    if not raw: continue
    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"PARSE FAIL line {ln}: {e}"); bad += 1; continue
    if d.get("error"): continue   # sentinel tolerated
    if set(d.keys()) != EXPECTED_KEYS:
        print(f"KEYSET FAIL line {ln}"); bad += 1; continue
    if d["hook"] != "CommandTakeActionEvent": bad += 1; continue
    if d["action"] not in ("Move","AttackDirection"): bad += 1; continue
    if d["dir"] not in DIRS: bad += 1; continue
    if d["result"] is False and d["fallback"] != "pass_turn": bad += 1; continue
    if d["energy_after"] >= d["energy_before"]: bad += 1; continue
    if not (isinstance(d["pos_before"], dict) and set(d["pos_before"].keys()) == {"x","y","zone"}): bad += 1; continue
    if not (isinstance(d["pos_after"], dict) and set(d["pos_after"].keys()) == {"x","y","zone"}): bad += 1; continue
    ok += 1
print(f"OK={ok} BAD={bad}")
'
```

Expected: `BAD == 0`.

- [ ] **Step 10: Save artifacts, commit nothing yet.**

```bash
cp /tmp/phase-0-f-step-b-acceptance.log /tmp/phase-0-f-acceptance/
echo "Step B acceptance: PASS — N=<count> lines, <attacks> attack records, <damaging> damaging hits" \
  >> /tmp/phase-0-f-acceptance/summary.txt
```

No commit. Acceptance results go into the exit memo at Task 8.

---

## Task 8: Exit memo + PR-F2 finalization

**Why this task exists:** Phase 0-A through 0-E established the pattern of an exit memo per phase under `docs/memo/phase-0-X-exit-<YYYY-MM-DD>.md`. The exit memo records the verified runtime environment, the acceptance counts, the Phase 0-F-specific implementation rules to carry forward, and feed-forward observations for Phase 0-G.

**Files:**

- Create: `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md`

**Branch:** `feat/phase-0-f-impl`.

- [ ] **Step 1: Read the Phase 0-E exit memo template.**

```bash
cat docs/memo/phase-0-e-exit-2026-04-26.md
```

The 0-F exit memo mirrors this shape: Outcome, Acceptance counts (table), Verified environment, Sample shapes (one full record + one sentinel), Phase-specific implementation rules, Provisional cadence carryforward, Open observations, Feed-forward for Phase 0-G, Open hazards still tracked, Files modified, References.

- [ ] **Step 2: Write `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md`.**

Use the Step 6 / Step 8 / Step 9 acceptance scripts' outputs to fill in the counts. A skeleton that the operator fills in live:

```markdown
# Phase 0-F Exit — <YYYY-MM-DD>

## Outcome
- Step A run on a fresh Mutated Human Marauder (Joppa central): N turns, M east-Move records, all `result:true` with `pos_after.x = pos_before.x + 1`. Wall-hit fallback observed at end if applicable.
- Step B run on the same character with `wish testhero:<blueprint>` adjacent hostile: N turns, K AttackDirection records, ≥1 with `target_hp_after < target_hp_before`.
- BEGIN == END == [state] == [caps] == [build] == [cmd] across both runs (cross-channel parity).
- ERROR=0 across all 5 channels on both runs.

## Acceptance counts

| Frame | Step A | Step B |
|---|---|---|
| [screen] BEGIN | <N_a> | <N_b> |
| [screen] END | <N_a> | <N_b> |
| [state] | <N_a> | <N_b> |
| [caps] | <N_a> | <N_b> |
| [build] | <N_a> | <N_b> |
| [cmd] | <N_a> | <N_b> |
| ERROR (any frame) | 0 | 0 |

## Verified environment
- CoQ build: <BUILD_*> (re-confirm from build_log.txt).
- Single-mod load order: `1: LLMOfQud`.
- macOS path layout per `phase-0-e-exit-2026-04-26.md` Verified environment section.
- Mod compile: `Compiling 3 files... Success :)`. No COMPILER ERRORS, no MODWARN.

## Sample shapes
**Step A successful east Move (turn N):**
```json
<paste latest non-sentinel [cmd] line with action="Move" from /tmp/phase-0-f-step-a-acceptance.log>
```
**Step B successful AttackDirection (any damaging hit):**
```json
<paste a [cmd] line with action="AttackDirection" and target_hp_after < target_hp_before>
```
**Sentinel (if any observed):**
```json
<if any sentinel observed; otherwise note "no sentinels emitted across N+M lines">
```

## Phase 0-F-specific implementation rules (carry forward)
1. Direct `Move/AttackDirection` calls, NOT `CommandEvent.Send`. ADR 0006 governs.
2. `CommandTakeActionEvent` is the issuance hook; `BeginTakeActionEvent` remains the observation hook.
3. `[cmd]` is emitted on the game thread via direct `MetricsManager.LogInfo`, NOT through `PendingSnapshot`.
4. `AutoAct.ClearAutoMoveStop()` mirrored before each `Move("E")`.
5. 3-layer drain: API success spends; `PassTurn()` on result==false; `Energy.BaseValue=0` last-ditch only.
6. `Energy.BaseValue=0` is NOT equivalent to `PassTurn()` — it bypasses `UseEnergyEvent`. Documented in code at the call site.
7. `return true` from `HandleEvent(CommandTakeActionEvent)` (NOT false; would abort event chain).
8. `E.PreventAction = true` in `finally` regardless of success/failure path.
9. Direction priority for Step B: N → NE → E → SE → S → SW → W → NW. Diagonal-first bias intentional.
10. Filter for `Cell.GetCombatTarget`: `o => o != player && o.IsHostileTowards(player)`.
11. Parser correlation: 5 LogInfo channels by `turn` field only — no adjacency / count parity assumption.

## Provisional cadence
Same posture as 0-D / 0-E. `[cmd]` is one-line-per-dispatch. Re-open if measured constraints justify.

## Open observations (recorded)
- <Tutorial intercept observed?>
- <Wall-hit fallback observed?>
- <Move-into-hostile via Move's combat-object path observed?>
- <Energy-Speed bumps above 1000 observed? (high-Speed actor).>

## Feed-forward for Phase 0-G
- Phase 0-G is the heuristic-bot phase ("flee if hurt, attack if adjacent, explore otherwise"). The "attack if adjacent" branch is essentially Step B reused; the heuristic adds `flee` (move AWAY from hostile when low HP) and `explore` (move toward unexplored cells when no hostile and not low HP).
- The fixed "Move East" Step A fallback is what Phase 0-G replaces with the heuristic.
- `[cmd]` schema may need a v2 bump if Phase 0-G adds a `reason` field for "why did the heuristic pick this action" (e.g., `reason: "flee_low_hp" | "attack_adjacent" | "explore_dijkstra"`).

## Open hazards (still tracked)
- Multi-mod coexistence (untested across all 6 phases).
- Save/load resilience for `[cmd]` — first turn after `AfterGameLoadedEvent` not exercised in v1.
- Hostile interrupt during fallback `PassTurn` — guarded by `PreventAction=true` but Phase 0-G+ may need to revisit.
- Brain.Goals interaction (player goals are typically empty; not exercised).
- AutoAct mirror semantic for Phase 0-G+ (clearing `AutomoveInterruptTurn` on every turn may interact with future auto-walk).
- High-Speed actor (energy bumped above 1000 by Speed add) — `energy_after < energy_before` invariant tested in v1 with default Speed; not exercised at high Speed.

## Files modified / created in Phase 0-F

| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Extracted `AppendJsonStringOrNull` / `AppendJsonIntOrNull` helpers; migrated 4 existing nullable-string call sites; added `CmdRecord` struct + `BuildCmdJson` + `BuildCmdSentinelJson` + `AppendPosObject` private helper. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Added `using XRL.World.Capabilities;`. Registered `CommandTakeActionEvent` in `RegisterPlayer`. New `HandleEvent(CommandTakeActionEvent E)` with Step A (Move E) + Step B (priority-scan + AttackDirection) + 3-layer drain + sentinel. |
| `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` | New ADR documenting the API + hook + threading + non-equivalence pivots. Landed in PR-F1. |
| `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` | Design spec; Codex APPROVED at the commit PR-F1 lands. |
| `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` | This plan; landed in PR-F1. |
| `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:2803` (Phase 0-F line, reinterpreted by ADR 0006), `:2804` (Phase 0-G boundary), `:1787-1790` (game-queue routing rule).
- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — API pivot.
- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` — schema lock.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` — implementation plan.
- `docs/memo/phase-0-e-exit-2026-04-26.md` — Phase 0-E exit memo whose carry-forward rule 5 was acted on by Phase 0-F Task 2.
- `mod/LLMOfQud/LLMOfQudSystem.cs` — `HandleEvent(CommandTakeActionEvent)`.
- `mod/LLMOfQud/SnapshotState.cs` — command JSON builders + helper extraction.
- CoQ APIs verified during Phase 0-F: per the design spec's References section.
- Acceptance log artifacts: `/tmp/phase-0-f-step-a-acceptance.log`, `/tmp/phase-0-f-step-b-acceptance.log` (operator-local, not committed).
```

Replace `<...>` placeholders with the actual values from the run.

- [ ] **Step 3: Run the static checks gate.**

```bash
pre-commit run --all-files
```

Expected: all hooks PASS.

- [ ] **Step 4: Commit the exit memo.**

```bash
git add docs/memo/phase-0-f-exit-*.md
git commit -m "$(cat <<'EOF'
docs(memo): Phase 0-F exit memo

Records the Step A and Step B acceptance run outcomes, the verified
environment, the carry-forward implementation rules, and the
feed-forward for Phase 0-G. Both runs cleared the cross-channel
≥40-turn 5-channel-parity gate with ERROR=0.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Push the implementation branch and open PR-F2.**

```bash
git push -u origin feat/phase-0-f-impl
gh pr create --base main --head feat/phase-0-f-impl \
  --title "feat(mod): Phase 0-F command_issuance.v1 [cmd] dispatch" \
  --body "$(cat <<'EOF'
## Summary

- First runtime-active phase for the MOD: \`HandleEvent(CommandTakeActionEvent)\` issues \`Move/AttackDirection\` autonomously per ADR 0006.
- New \`[LLMOfQud][cmd]\` LogInfo line per dispatch (5th observation channel, schema \`command_issuance.v1\`).
- Step A (Move East) and Step B (adjacent-hostile detection -> AttackDirection) acceptance runs PASS.
- Helper extraction: \`AppendJsonStringOrNull\` / \`AppendJsonIntOrNull\` (Phase 0-E exit memo rule 5 acted on).

## Test plan

- [x] \`pre-commit run --all-files\` clean
- [x] CoQ load probe: \`Compiling 3 files... Success :)\`
- [x] Step A acceptance: ≥10 east \`Move\` records, ≥40-turn 5-channel parity, ERROR=0
- [x] Step B acceptance: ≥3 \`AttackDirection\` records, ≥1 with \`target_hp_after < target_hp_before\`, ≥40-turn parity, ERROR=0
- [ ] CI green
- [ ] CodeRabbit comments addressed before merge

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Address CodeRabbit comments before merge.**

Wait for CodeRabbit's automated review on PR-F2. Per the docs-PR feedback policy in `MEMORY.md` (`feedback_docs_pr_merge_policy.md` — applies to docs-only PRs not to impl PRs), this is an implementation PR and DOES require addressing CodeRabbit comments before merge. Iterate on review comments until CR is satisfied or comments are explicitly waived.

- [ ] **Step 7: Merge PR-F2 once CI is green and CR is satisfied.**

```bash
gh pr merge feat/phase-0-f-impl --squash
```

Verify `main` now contains the new commits via `git log --oneline main -10`.

---

## End-of-plan self-review checklist (run mentally before declaring done)

- [ ] All 9 tasks (0-8) have a concrete deliverable file or run artifact.
- [ ] Every code block in Tasks 2-5 is complete (no `// TODO`, no placeholder).
- [ ] Every commit message in Tasks 0-8 is a real message, not a placeholder.
- [ ] Tasks 6 and 7's acceptance scripts validate the schema lock from the spec exactly.
- [ ] The exit memo in Task 8 is filled in with values from Tasks 6 and 7.
- [ ] PR-F1 (docs) lands first; PR-F2 (impl) opens against `main` after PR-F1 merges.
- [ ] Spec commit hash is referenced in PR-F1 body (verify before opening PR).
- [ ] No surprise file changes outside `mod/LLMOfQud/*.cs` and `docs/`.
