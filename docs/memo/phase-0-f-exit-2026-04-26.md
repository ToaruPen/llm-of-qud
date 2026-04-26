# Phase 0-F Exit — 2026-04-26

## Outcome
- First runtime-active phase. The MOD now issues movement and melee-attack commands autonomously each `CommandTakeActionEvent` dispatch — no keyboard input required for the engine to advance turns.
- Combined Step A + Step B acceptance run on Joppa Mutant Marauder, 505 `[cmd]` lines total. Cross-channel parity gate `[screen] BEGIN == [screen] END == [state] == [caps] == [build] == [cmd] = 505`. ERROR=0 across all six observation lines.
- **ADR 0007 mid-implementation correction**: a 488-turn pre-patch run on commit `be2e6b2` empirically falsified the design spec's load-bearing claim that `ActionManager`'s player render fallback (`decompiled/XRL.Core/ActionManager.cs:1806-1808`) flushes `[screen]/[state]/[caps]/[build]` per turn. Root cause: success-path `finally { E.PreventAction = true; }` made `CommandTakeActionEvent.Check` return false at `decompiled/XRL.Core/ActionManager.cs:829-832`, the iteration `continue`d, and the render fallback was never reached on the same iteration. ADR 0007 scopes `PreventAction = true` to the abnormal-energy catch path only; success path leaves `PreventAction` at default `false`. Post-patch run on commit `2d3c282` restored the per-turn 6-line cadence.
- Latest `[cmd]` line passes `json.loads`, contains all 17 top-level `command_issuance.v1` keys, is non-sentinel, and the `target_hp_after < target_hp_before` invariant holds across the 11 damaging-hit records.
- Every-line JSON validity: 505/505 `[cmd]` lines parse cleanly, 0 sentinels emitted during the run.
- Step A criterion 2: longest consecutive-east-Move success run = **79 records** (≥10 required). 232 pure-Step-A records (turns 1..232 of session 1) all pass per-record invariants.
- Step B criterion 3: 15 `AttackDirection` records, **11 damaging hits** (≥1 required). Targets observed in-run: snapjaw scavenger (id 728, HP 3 → 0), two-headed boar (HP 37 → 35), salthopper.

## Acceptance counts

| Frame | Count |
|---|---|
| `[cmd]` | 505 |
| `[screen] BEGIN` | 505 |
| `[screen] END` | 505 |
| `[state]` | 505 |
| `[caps]` | 505 |
| `[build]` | 505 |
| ERROR (any frame) | 0 |
| `AttackDirection` records | 15 |
| Damaging hits (target_hp_after < before) | 11 |
| Longest consecutive east-Move success run | 79 |

Per-segment split:
- Step A pure segment (turns 1..232 of session 1): 232 records, all `action: "Move", dir: "E"`, target_* null.
- Step B segment (rest of run including a within-session `_beginTurnCount` reset): 273 records, 15 of which are `AttackDirection`.

Both segments meet their respective spec thresholds (Step A ≥10 consecutive successes + ≥40 turns; Step B ≥3 attacks + ≥1 damaging hit + ≥40 turns).

## Verified environment
- CoQ build: `BUILD_2_0_210`, Unity Version `6000.0.41f1`, Unity Reported Version `2.0.4` (same as Phase 0-D / 0-E — no game update between phases).
- Single-mod load order: `1: LLMOfQud`. Other user mods skipped per `build_log.txt`.
- macOS path layout (post-rebrand, same as 0-E):
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`
  - Roslyn assembly written to `$COQ_SAVE_DIR/ModAssemblies/LLMOfQud.dll` (transient).
- Mod compile: `Compiling 3 files... Success :)` with `Defined symbol: MOD_LLMOFQUD`. No `MODWARN` / `COMPILER ERRORS` for `LLMOfQud`.
- Acceptance run launch timestamp: `2026-04-26T15:41:09Z` (single CoQ launch, post-ADR-0007 patch on commit `2d3c282`).

## Sample shapes

**Step A first turn (Move East, no hostile):**
```json
{"turn":1,"schema":"command_issuance.v1","hook":"CommandTakeActionEvent","action":"Move","dir":"E","result":true,"fallback":null,"energy_before":1036,"energy_after":-21,"pos_before":{"x":0,"y":17,"zone":"JoppaWorld.14.22.2.1.10"},"pos_after":{"x":1,"y":17,"zone":"JoppaWorld.14.22.2.1.10"},"target_id":null,"target_name":null,"target_pos_before":null,"target_hp_before":null,"target_hp_after":null,"error":null}
```

**Step B first turn (Snapjaw scavenger detected NE, AttackDirection, killing blow):**
```json
{"turn":234,"schema":"command_issuance.v1","hook":"CommandTakeActionEvent","action":"AttackDirection","dir":"NE","result":true,"fallback":null,"energy_before":1042,"energy_after":73,"pos_before":{"x":26,"y":17,"zone":"JoppaWorld.14.22.2.1.10"},"pos_after":{"x":26,"y":17,"zone":"JoppaWorld.14.22.2.1.10"},"target_id":"728","target_name":"snapjaw scavenger","target_pos_before":{"x":27,"y":16,"zone":"JoppaWorld.14.22.2.1.10"},"target_hp_before":3,"target_hp_after":0,"error":null}
```

`target_hp_after < target_hp_before` confirms `hitpoints` is the live `Statistic.Value` (post-modifier, post-damage), not `baseHitpoints`. Across the 15 attack records, HP delta varies between 0 (miss / armor block) and 3 (lethal blow); HP=0 at `target_hp_after` indicates the kill turn.

**Negative `energy_after` is expected.** `Move`/`AttackDirection` can spend more than 1000 energy per dispatch depending on weapon/movement delay (Combat.MeleeAttackWithWeapon at `decompiled/XRL.World.Parts/Combat.cs:794-798` calls `UseEnergy(num3 * 100)` with `num3 = WeaponDelay`; weapon delay 11 → spends 1100). The autonomy invariant is `Energy.Value < 1000` after our handler returns, NOT `Energy.Value >= 0`. Negative values are a non-issue for the `:838` energy guard — they simply mean the next BTA / CTA cycle gives the player time to recover via NPC turns + Speed regen.

## Phase 0-F-specific implementation rules (carry forward to next phases)
1. **`CommandTakeActionEvent` is the issuance hook**, NOT `BeginTakeActionEvent`. BTA fires before the inner action loop and a BTA energy-drain skips the entire loop (hostile-interrupt, AutoAct, brain goals, EndActionEvent). CTA fires inside the loop and keeps all those paths intact. Phase 0-A through 0-E observation continues to use BTA; future Phase 0-G+ command-issuance variants (heuristic bot, LLM-driven action) inherit the CTA hook.
2. **Direct `GameObject.Move` / `GameObject.AttackDirection`, NOT `CommandEvent.Send`.** ADR 0006 documents why. `CommandEvent.Send("CmdMoveE")` outside `XRLCore.PlayerTurn()`'s switch is a silent no-op that does NOT drain energy. Any Phase 0-G+ command type that needs the same direct path uses the underlying `GameObject` API, not the event chain.
3. **`AutoAct.ClearAutoMoveStop()` mirrors the `CmdMoveE` keypress wrapper** (`decompiled/XRL.Core/XRLCore.cs:1107-1109`). Call before `Move("E")` only — the attack path does not need it. `AttackDirection` does not have an equivalent wrapper.
4. **`PreventAction = true` is Layer-4 abnormal-energy defense, NOT the autonomy mechanism (ADR 0007).** The autonomy invariant ("engine does not wait on keyboard input after our handler returns") depends entirely on `Energy.Value < 1000` from Layers 1/2/3 (`Move`/`AttackDirection` success → `PassTurn` fallback → `Energy.BaseValue = 0` last-ditch). The `:838` energy guard at `decompiled/XRL.Core/ActionManager.cs:838` already prevents the keyboard-input branch when `Energy.Value < 1000`; the iteration falls through to the render fallback at `:1806-1808` and observation channels flush. `PreventAction = true` is set ONLY when post-recovery energy is still `>= 1000` (Layers 1/2/3 all failed).
5. **Render fallback `:1806-1808` is now load-bearing for the per-turn `[screen]/[state]/[caps]/[build]` flush.** Future CoQ patches that change this fallback (e.g. the `else if (Actor.IsPlayer())` branch removed or its body altered) re-open Phase 0-F. This is documented in ADR 0007 Consequence #2.
6. **Game-thread direct emit for `[cmd]`, NOT `PendingSnapshot`.** `[cmd]` emits via `MetricsManager.LogInfo` synchronously inside `HandleEvent(CommandTakeActionEvent)`. `PendingSnapshot` is reserved for the four observation channels (state/caps/build + screen-block-from-screen-buffer). Future per-action telemetry types (e.g. `[npc]`, `[zone]`) follow the same game-thread direct-emit pattern if they are correlated with command issuance.
7. **8-direction priority scan: N → NE → E → SE → S → SW → W → NW.** Fixed in code; NOT derived from CoQ's internal direction enum (which is not a stable contract). First non-null `Cell.GetCombatTarget` hit wins; same-distance ties (all 8 cells are at distance 1) resolve by this priority order. Diagonal-first bias is intentional and documented in design spec.
8. **`Cell.GetCombatTarget` filter mirrors `Combat.AttackCell` (`decompiled/XRL.World.Parts/Combat.cs:877-889`)**: same `GetCombatTarget` call shape with `Phase: 5` (= `IgnorePhase: true` per `decompiled/XRL.World/Cell.cs:8513-8516`), `AllowInanimate: false`, and `Filter: o => o != player && o.IsHostileTowards(player)`. Identical semantics for "is there an adjacent hostile? if so, which".
9. **`hitpoints` (lowercase, live `Statistic.Value`) for `target_hp_*`, NOT `baseHitpoints`.** `decompiled/XRL.World/GameObject.cs:1177-1198`. The schema field captures live HP at the moment of measurement; this gives consumers a meaningful damage delta between `target_hp_before` and `target_hp_after`.
10. **JSON helper inheritance from Phase 0-E.** The 5th-occurrence trigger from Phase 0-E rule 5 fired in this phase: `genotype_id`, `subtype_id`, `hunger`, `thirst` (4 from 0-E) plus the new nullable string fields in `command_issuance.v1` produced 4+ more. Helpers `AppendJsonStringOrNull` and `AppendJsonIntOrNull` were extracted in Task 2 of the plan; future phases use these directly instead of inlining the `if (x == null) Append("null"); else AppendJsonString(sb, x);` pattern.
11. **`InvariantCulture` discipline for integer-to-JSON.** All integer emissions in `BuildCmdJson` / `BuildCmdSentinelJson` / `AppendPosObject` use `.ToString(CultureInfo.InvariantCulture)` (commit `edd8370`). Future builders must match this pattern — culture-dependent integer formatting (e.g., `"1.234"` for `1234` under `de-DE`) would corrupt the JSON.
12. **Schema is `command_issuance.v1`.** Field additions or order changes require a v2 bump + ADR. Locked top-level key order is `{turn, schema, hook, action, dir, result, fallback, energy_before, energy_after, pos_before, pos_after, target_id, target_name, target_pos_before, target_hp_before, target_hp_after, error}`. Sentinel shape is `{turn, schema, error: {type, message}}`.

## Provisional cadence — future revisit triggers (inherited from 0-D / 0-E + extended)
The every-turn full dump approach is provisional. Phase 0-D enumerated 8 re-open conditions for `[caps]`; 0-E added the stable-vs-volatile field separation trigger. Phase 0-F adds:

- **Render-fallback dependency on `PreventAction` scope (ADR 0007).** Per-turn observation cadence is now load-bearing on the success path leaving `PreventAction = false` so the `:1806-1808` fallback fires. Any future change to the catch-path Layer-4 logic — extending the `if (player?.Energy != null && player.Energy.Value >= 1000) { E.PreventAction = true; }` guard, or moving `PreventAction = true` somewhere else — must preserve the success-path invariant. Re-open trigger: a future phase needs to set `PreventAction = true` on the success path for some other reason (e.g., to suppress a registered handler), in which case the observation pipeline must move off `PendingSnapshot`/`AfterRenderCallback` to the game thread.
- **Engine-speed autonomy is the new normal.** With Phase 0-F active, the player walks east at full game-thread speed (no render frame budget, no input wait). Operator observation: the run feels "尋常ではない程速く". The 505-record run completed in seconds of wall time, traversing 4 zones. This is intentional for the autonomy phase but is the open hazard Phase 1 (WebSocket bridge) MUST address: rate-limiting, throttle to render cadence, or LLM-driven decision latency naturally enforcing pace. Until then, autonomous runs are not human-observable in real time.

## Open observations (recorded but not blocking)
- **Auto-zone traversal works.** The autonomous handler traversed 4 zones (`JoppaWorld.14.22.2.1.10 → .12.22.1.1.10 → .11.22.2.1.10 → .12.22.0.1.10`) without operator intervention. Zone-edge `Move("E")` returns true at the eastmost cell, the engine swaps zones, and the next `[cmd]` line emits the new `pos_after.zone` value. No special handling needed in the MOD.
- **Within-session `_beginTurnCount` reset confirmed.** The 505-record run included one reset at index 301 (turn 301 → turn 1). Same lifecycle as observed in Phase 0-E (`_beginTurnCount` is per-system-instance, rebuilt on `RegisterPlayer` for a new chargen / save-load round-trip). Both halves of the run pass acceptance independently — the validator does not depend on monotonic turn numbers across the whole artifact.
- **`Energy.Value` going negative is benign.** `decompiled/XRL.World/Statistic.cs:238-253` clamps `Value` to `[Min, Max]`. `Move`/`AttackDirection` can spend > 1000 (weapon delay > 1.0×); this drives `Value` below 0. The `:838` energy guard checks `Value >= 1000`, so any negative value satisfies the autonomy invariant.
- **Triple-evaluation defense-in-depth.** The catch-block ladder evaluates `player?.Energy != null && player.Energy.Value >= 1000` to attempt drain, then the `finally` re-evaluates the same guard to scope `PreventAction`. Code-quality reviewer noted (and verified at `decompiled/XRL.World/Statistic.cs:238-253`) that `Statistic.Value` is a pure computed getter — no exception risk on re-read. The `Bonus` accumulation edge case (where `BaseValue = 0` doesn't drop `Value < 1000` because of active modifier bonuses) is the reason for the `finally` re-evaluation; one render cadence is intentionally sacrificed in that pathological case to preserve autonomy.
- **`target_hp_after == target_hp_before` for some attack turns is normal.** `result: true` only means `AttackDirection` returned true (the action completed). Whether the attack hit and dealt damage depends on combat resolution (to-hit roll, armor, AV/DV, weapon damage). Of 15 `AttackDirection` records, 11 dealt damage (`target_hp_after < target_hp_before`); the other 4 are misses or armor blocks (`target_hp_after == target_hp_before`). Both subsets are valid `[cmd]` records.
- **No hostile-interrupt fired on the success path.** Per ADR 0007's correction to the design spec (line 247 / hostile-interrupt hazard), `PreventAction = false` on the success path now lets the `:834-837` interrupt block evaluate. AutoAct was inactive throughout (we don't engage `AutoAct.Setting`), so `IsInterruptable()` returned false on every dispatch and the interrupt did not fire. Empirically confirmed; the path is now reachable but the no-op condition holds.

## Feed-forward for Phase 0-G / Phase 1
- **Phase 0-G** (per `docs/architecture-v5.md:2804`) takes the next step on autonomous behavior. Carry forward:
  - The CTA hook + direct API path established here — extend with new action verbs (`CmdRest`, `CmdEat`, `CmdInventory`, etc.) by adding branches inside the same handler, or by routing through a shared helper that selects the API call.
  - The 8-direction priority scan generalizes to any "find adjacent X" detection (allies, items, doors, etc.). The filter predicate is the only thing that changes.
  - `AutoAct.ClearAutoMoveStop()` should be re-evaluated when Phase 0-G+ introduces multi-step movement chains (auto-walk to a tile, follow an NPC). The current "clear before every Move" pattern matches the keypress wrapper, but a multi-step chain may want to preserve `AutomoveInterruptTurn` between steps.
- **Phase 1** (WebSocket bridge, `docs/architecture-v5.md:2836-2855`) consumes the `[cmd]` schema as the canonical "what just happened" event the Brain saw. Carry forward:
  - **Rate limiting is mandatory.** The current implementation runs at engine-thread speed; a Brain that takes seconds to decide each command will naturally throttle the cadence. But a hardcoded heuristic Brain would not, and could continue producing the unobservable-speed runs seen in this phase.
  - **`turn` field correlation.** Phase 1 parser correlates `[cmd]` with `[state]`/`[caps]`/`[build]`/`[screen]` by `turn=N`, NOT line adjacency. Other CoQ subsystems' `LogInfo` lines may interleave; the parser must be tolerant.
  - **Sentinel handling.** Sentinel `[cmd]` lines (`{turn, schema, error: {type, message}}`) are observed-zero in this run but are part of v1. Brain must handle them (e.g., as "engine couldn't issue a command this turn — read the next observation pair to recover").

## Open hazards (still tracked from earlier phases)
- Render-thread exception spam dedup: 0 ERROR lines over 95 + 110 + 251 + 160 + 505 = 1121 cumulative turns across phases 0-B/0-C/0-D/0-E/0-F. Continue to defer.
- Multi-mod coexistence: still untested (single-mod load order in this run, same as 0-D / 0-E).
- Save / load resilience for `[caps]` / `[build]` / `[cmd]`: the within-session `_beginTurnCount` reset observed here suggests save-load triggers `RegisterPlayer` re-fire (which the existing implementation handles cleanly), but no formal save-quit-reload acceptance was performed. Defer.
- Cooldown decrement (`cooldown_segments_raw > 0`) for `[caps]`: still NOT EXERCISED across all phases.
- **New, Phase-0-F-specific:** Hostile-interrupt path is now reachable but no-op (AutoAct inactive). If a future phase engages AutoAct from inside `HandleEvent(CommandTakeActionEvent)` — a "follow this path" action — the interrupt becomes load-bearing and must be tested against the current `:834-837` semantics.

## Files modified / created in Phase 0-F

| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Added `AppendJsonStringOrNull` / `AppendJsonIntOrNull` helpers (Task 2, commit `9db578a`); added `internal struct CmdRecord`, `BuildCmdJson(CmdRecord r)`, `BuildCmdSentinelJson(int turn, Exception ex)`, `private static AppendPosObject(...)` (Task 3, commit `0a33b82`); added `InvariantCulture` to all integer emissions (fix `edd8370`). |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Registered `CommandTakeActionEvent` in `RegisterPlayer` and added the `HandleEvent(CommandTakeActionEvent E)` body — Step A move-east in Task 4 (commit `f461bf0`); Step B adjacent-hostile detection + `AttackDirection` in Task 5 (commit `be2e6b2`); ADR 0007 patch scoping `PreventAction = true` to abnormal-energy catch path in Task 5b (commit `2d3c282`). |
| `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` | New ADR landed in PR-F1 (commit `715caf5`). Status updated post-acceptance to "Consequence #3 cadence framing partially superseded by ADR 0007 (2026-04-26)". |
| `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md` | New ADR landed mid-implementation (commit `f098839`). Scopes `PreventAction = true` to abnormal-energy catch path; restores render-fallback reachability for per-turn observation cadence. |
| `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` | Design spec for `command_issuance.v1`. Architecture lines 9 / 12 / 13, pseudocode `finally`, Error posture, and Hostile-interrupt-hazard sections corrected by ADR 0007 (commit `f098839`). |
| `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` | Implementation plan with Tasks 0–8 plus Task 5b inserted in `f098839`. |
| `docs/adr/decision-log.md` + `docs/adr/decisions/2026-04-26-phase-0-f-*.md` | Decision records for ADR 0006 (3 entries: original + PR-13 review fixes + spec citation canonicalization) and ADR 0007. |
| `docs/memo/phase-0-f-exit-2026-04-26.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:2803` (Phase 0-F line, reinterpreted by ADR 0006), `:2804` (Phase 0-G boundary), `:1787-1790` (game-queue routing rule), `:2836-2855` (Phase 1 WebSocket bridge consumer).
- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — pivot from `CommandEvent.Send` to direct `Move`/`AttackDirection`, hook choice rationale.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md` — `PreventAction` scope correction, render fallback restoration.
- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` — `command_issuance.v1` schema lock, field semantics, error posture, acceptance criteria.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` — implementation plan (Tasks 0..8 + 5b).
- `docs/memo/phase-0-e-exit-2026-04-26.md` — Phase 0-E exit memo whose carry-forward observations seeded this phase.
- `mod/LLMOfQud/LLMOfQudSystem.cs:181-378` — current `HandleEvent(CommandTakeActionEvent)` body (commit `2d3c282`).
- `mod/LLMOfQud/SnapshotState.cs` — `command_issuance.v1` JSON builders (`BuildCmdJson`, `BuildCmdSentinelJson`, `AppendPosObject`) and JSON helpers (`AppendJsonStringOrNull`, `AppendJsonIntOrNull`).
- CoQ APIs verified during Phase 0-F (re-cite from `decompiled/`):
  - `decompiled/XRL.Core/ActionManager.cs:786-800` (BTA energy gate), `:829-832` (CTA `Check` short-circuit), `:838` (player + Energy>=1000 keyboard branch guard), `:1797-1799` (`PlayerTurn()` call), `:1806-1808` (player render fallback).
  - `decompiled/XRL.World/CommandTakeActionEvent.cs:37-39` (`Check` returns `Object.HandleEvent(...) && !PreventAction`).
  - `decompiled/XRL.Core/XRLCore.cs:1107-1109` (`CmdMoveE` keypress wrapper), `:1270-1271` (`CmdAttackE` keypress wrapper), `:624-626` (`AfterRenderCallbacks` registration), `:2354-2426` (`RenderBaseToBuffer` + AfterRenderCallbacks fan-out), `:2517-2582` (`RenderBase` → `RenderBaseToBuffer` → `_Console.DrawBuffer`).
  - `decompiled/XRL.World/GameObject.cs:1177-1198` (`hitpoints` / `baseHitpoints`), `:10887-10894` (`IsHostileTowards`), `:15274-15290` (`Move` signature), `:15397-15400` (`Move` → `UseEnergy("Movement")`), `:15336-15338` (tutorial intercept), `:17882-17902` (`AttackDirection` signature).
  - `decompiled/XRL.World/Cell.cs:8511-8557` (`GetCombatTarget` signature, `Phase: 5` ⇔ `IgnorePhase: true`), `GetCellFromDirection` (verified by reviewer in-file).
  - `decompiled/XRL.World.Capabilities/AutoAct.cs:386-389` (`ClearAutoMoveStop` body), `:834-837` (hostile interrupt site referenced in ActionManager).
  - `decompiled/XRL.World.Parts/Combat.cs:794-798` (`MeleeAttackWithWeapon` energy spend), `:877-889` (`AttackCell` `GetCombatTarget` shape — Phase 0-F filter mirrors this).
  - `decompiled/XRL.World/Statistic.cs:238-253` (`Value` clamped getter).
  - `decompiled/MetricsManager.cs:407-409` (`LogInfo` body).
  - `decompiled/Logger.cs` + `decompiled/SimpleFileLogger.cs` (`Logger.buildLog.Info` → `build_log.txt` for the `[LLMOfQud] loaded` marker — Phase 0-F operator-confirmed in build log, NOT `Player.log`).
- Acceptance log artifacts (operator-local, not committed):
  - `/tmp/phase-0-f-acceptance/raw-player-step-a-and-b-2026-04-26.log` (full Player.log of the post-ADR-0007 run, 16017 lines)
  - `/tmp/phase-0-f-acceptance/cmd-records-only.log` (505 filtered `[cmd]` lines)
  - `/tmp/phase-0-f-acceptance/summary.txt` (acceptance summary)
  - `/tmp/phase-0-f-acceptance/raw-player-15-05-08.log` (pre-ADR-0007 488-turn evidence run referenced in ADR 0007's empirical observation table)
