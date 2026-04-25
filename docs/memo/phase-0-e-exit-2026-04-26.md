# Phase 0-E Exit — 2026-04-26

## Outcome
- Combined-process acceptance run on Joppa: True Kin Priest of All Moons (40 turns) → Mutant Marauder (120 turns), 160 `[build]` lines total. BEGIN == END == [state] == [caps] == [build] == 160. ERROR=0 across all four observation lines.
- Latest `[build]` line (Mutant turn 120) passes `json.loads` and contains all 9 top-level `current_build.v1` keys.
- Every-line JSON validity: 160/160 lines parse cleanly, 0 sentinels.
- First-turn (True Kin turn 1) vs last-turn (Mutant turn 120) shape parity OK — top-level keys and `attributes` keys identical across the genotype switch.
- Semantic invariants gate (spec criterion 8) PASS across all 160 non-sentinel turns:
  - `attributes` always has the 6 lowercase keys with integer values.
  - `genotype_kind` always in `{mutant, true_kin}`; zero `unknown`.
  - `level` always positive integer.
  - `genotype_id` / `subtype_id` always non-null on both genotype runs.
  - `hunger` / `thirst` always non-null (both bodies have a `Stomach` part) and within the closed non-amphibious enum sets.
- Spec criterion 9 (two-build smoke) cleared — both `genotype_kind` enum branches and a True-Kin-side `subtype_id` empirically exercised.
- No code changes from `_beginTurnCount` lifecycle observation: the implementation is correct on the live runtime.

## Acceptance counts

| Frame | Count |
|---|---|
| [screen] BEGIN | 160 |
| [screen] END | 160 |
| [state] | 160 |
| [caps] | 160 |
| [build] | 160 |
| ERROR (any frame) | 0 |

Per-genotype split: True Kin Priest of All Moons = 40 turns; Mutant Marauder = 120 turns. Both meet their respective spec thresholds (Mutant primary ≥ 100; True Kin secondary ≥ 10).

## Verified environment
- CoQ build: `BUILD_2_0_210`, Unity Version `6000.0.41f1`, Unity Reported Version `2.0.4` (same as Phase 0-D — no game update between phases).
- Single-mod load order: `1: LLMOfQud` (other user mods all `Skipping, state: Disabled` per `build_log.txt`).
- macOS path layout (publisher rebrand from Kitfox Games → Freehold Games confirmed during this phase, AGENTS.md fixed in `d6606f5`):
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log` (NOT under `$COQ_SAVE_DIR`)
  - Roslyn assembly written to `$COQ_SAVE_DIR/ModAssemblies/LLMOfQud.dll` (transient).
- Mod compile: `Compiling 3 files... Success :)` with `Defined symbol: MOD_LLMOFQUD`. No `MODWARN` / `COMPILER ERRORS` for `LLMOfQud`.

## Sample shapes

**True Kin first turn:**
```json
{"turn":1,"schema":"current_build.v1","genotype_kind":"true_kin","genotype_id":"True Kin","subtype_id":"Priest of All Moons","level":1,"attributes":{"strength":18,"agility":18,"toughness":20,"intelligence":18,"willpower":22,"ego":16},"hunger":"sated","thirst":"quenched"}
```

**True Kin last turn (40):** same field set, attributes clamped after live modifiers — `agility 18 → 14`, `intelligence 18 → 14` (debuffs applied), proves `Statistic.Value` is read post-modifier per spec line 61.

**Mutant last turn (120):**
```json
{"turn":120,"schema":"current_build.v1","genotype_kind":"mutant","genotype_id":"Mutated Human","subtype_id":"Marauder","level":1,"attributes":{"strength":20,"agility":15,"toughness":13,"intelligence":19,"willpower":19,"ego":18},"hunger":"sated","thirst":"quenched"}
```

Both genotype branches resolve `genotype_kind`, `genotype_id`, and `subtype_id` to non-null, distinct values; the JSON shape is identical across the genotype boundary.

## Phase 0-E-specific implementation rules (carry forward to next phases)
1. `[build]` JSON is built on the game thread inside `HandleEvent(BeginTakeActionEvent)`; render thread emits the prepared string only. Same routing as 0-D `[caps]`.
2. `PendingSnapshot.BuildJson` is the single threading slot for build payload. Future build fields thread through this object, never as a parallel `Interlocked.Exchange` slot.
3. Schema is `current_build.v1`. Field additions or order changes require a v2 bump + ADR. The locked field order is `{turn, schema, genotype_kind, genotype_id, subtype_id, level, attributes, hunger, thirst}`.
4. `[build]` failure is independent of `[screen]`/`[state]`/`[caps]` — sentinel JSON `{turn, schema, error:{type, message}}` (always parseable, control-character-safe via `AppendJsonString`) replaces the data on a build error.
5. **Explicit JSON null discipline (new this phase):** `SnapshotState.AppendJsonString(sb, null)` emits `""` (empty quoted string), NOT JSON `null`. For nullable fields where the schema requires JSON `null`, the call site MUST use `if (x == null) sb.Append("null"); else AppendJsonString(sb, x);`. This appears 4 times in the current code (`genotype_id`, `subtype_id`, `hunger`, `thirst`). When a 5th occurrence lands, extract a helper `AppendJsonStringOrNull(sb, value)`.
6. **CapsCase ↔ lowercase mapping is fixed at compile time** for attribute keys (parallel `_AttrCoqNames` / `_AttrJsonKeys` arrays). Do NOT call `ToLowerInvariant()` per turn — it's a guaranteed allocation that the compile-time mapping eliminates.
7. **CoQ display markup strip rule:** `Stomach.FoodStatus()` / `WaterStatus()` return `{{<C>|<text>}}` markup with optional trailing `!` on famished / wilted / dehydrated / desiccated. The `NormalizeStomachStatus` helper strips in this order: leading `{{<C>|` → trailing `}}` → trailing `!` → `ToLowerInvariant()`. Reverse-ordering the `}}` and `!` strips is a silent bug — `Famished!}}` would lose the `!` strip because `s[Length-1] == '}'` after the `!` check; only stripping `}}` first exposes the `!`.
8. **Genotype-kind derivation MUST guard `player == null` first** before calling `IsTrueKin()` / `IsMutant()`. Both methods dereference `this`, so the order matters — `null → "unknown"` is the first branch.
9. **Obsolete-API hygiene rule (carried from 0-D):** any new CoQ-API call site checked against `decompiled/<path>.cs` for `[Obsolete]` attributes. Phase 0-E added 4 new GameObject calls (`GetGenotype`, `GetSubtype`, `IsTrueKin`, `IsMutant`), 1 Statistic call (`Value`), 1 GameObject part-getter (`GetPart<Stomach>`), and 2 Stomach calls (`FoodStatus`, `WaterStatus`). None were `[Obsolete]`-tagged in `BUILD_2_0_210`.

## Provisional cadence — future revisit triggers (inherited from 0-D + extended)
The every-turn full dump approach is provisional. Phase 0-D enumerated 8 re-open conditions for `[caps]`; the same conditions apply to `[build]`, plus one Phase 0-E-specific addition:

9. **Stable-vs-volatile field separation.** `genotype_kind` / `genotype_id` / `subtype_id` are stable across a character's life (they only change on chargen / death → new game). `level` / `attributes` / `hunger` / `thirst` are volatile (modifier-driven, per-turn). If Phase 1 Brain wants to compute a build-state diff for token-cost reasons, the natural split is identity (stable) vs runtime (volatile), and the schema may grow a `birth_*` slice that captures the stable values once. This is the "deferred Phase 0-? retrospective birth-profile capture" gated on Layer 3 Cross-Run Knowledge per ADR 0005 + spec `:1696-1710`.

## Open observations (recorded but not blocking)
- **Live attribute clamping confirmed.** True Kin `agility` and `intelligence` both moved 18 → 14 between turn 1 and turn 40 (combat modifier / effect-driven debuff). `Statistic.Value` is correctly returning the clamped + modifier-applied effective value, not the base value. Brain consumers should NOT recompute base values from `attributes` — they're already runtime values.
- **Hunger / thirst bucket coverage was minimal.** All 160 turns showed `hunger="sated"` and `thirst="quenched"`. The acceptance gate (closed enum membership) passed because the values are valid enum members, but the alternate buckets (`hungry` / `wilted` / `famished` for hunger; `thirsty` / `parched` / `dehydrated` for thirst) were not exercised. Re-open the markup-strip path validation when a future run produces a non-Sated / non-Quenched bucket. Until then, the strip logic is verified against CoQ source (`decompiled/XRL.World.Parts/Stomach.cs:87-143`) but not against runtime output for those buckets.
- **`_beginTurnCount` resets on new-game / chargen, even within the same CoQ process.** The True Kin run died at turn 40, the user clicked through the death popup back to chargen, created a new Mutant character, and the next `[build]` line emitted `turn=1` — not `turn=41`. This means the `LLMOfQudSystem` instance (or at least its `_beginTurnCount` field) is rebuilt on `RegisterPlayer()` for the new character. Phase 0-A's "is `_beginTurnCount` lifecycle in-process or per-character?" question is answered empirically: per-character. This is also why `RequireSystem<LLMOfQudSystem>()` is the right registration pattern — it produces a fresh instance per new-game session.
- **Amphibious thirst family untested.** Both runs were non-amphibious bodies. The `desiccated/dry/moist/wet/soaked` thirst bucket family (`Stomach.cs:106-126`) is documented in `NormalizeStomachStatus`'s comment but not empirically exercised. v1 acceptance gate explicitly does not assert membership in the amphibious set (spec hazard "Hunger/thirst bucket stability") — re-open if a future phase covers an amphibious build.

## Feed-forward for Phase 0-? (deferred death recording / Cross-Run Knowledge)
Per ADR 0005 the literal "BirthBuildProfile" / DeathLogger use case (`docs/architecture-v5.md:1696-1710`) is deferred. The Phase 0-E observation above on `_beginTurnCount` reset adds a concrete data point for that deferred phase:

- **New-game / chargen is a natural reset trigger** — the `LLMOfQudSystem` instance is rebuilt, so any "previous run" capture must persist OUTSIDE the system's instance state (e.g. to a memo file under `$COQ_SAVE_DIR`).
- **Death is observable (popup + mainmenu transition), but not yet hooked.** A future death-logger phase will need either (a) a CoQ event listener for `EnterMenuEvent` / `BeforeBeginGameEvent`, or (b) an `OnDestroy` hook on the player GameObject. Both are in `decompiled/`; verify before citing.
- **Save → load was not exercised in this acceptance run.** The "Save/load resilience" hazard (carried from 0-D as point 7 in Provisional cadence) remains untested. Phase 0-E added more nullable-state fields (`hunger`/`thirst`) which may behave differently across save round-trip than runtime-only state — re-verify when save/load is exercised, even informally.

## Open hazards (still tracked from earlier phases)
- Render-thread exception spam dedup: 0 ERROR lines over 95 + 110 + 251 + 160 = 616 cumulative turns across phases 0-B/0-C/0-D/0-E. Continue to defer.
- Multi-mod coexistence: still untested (single-mod load order in this run, same as 0-D).
- Save / load resilience for `[caps]` and `[build]`: untested in 0-D, not exercised in 0-E either. Re-open when a phase explicitly walks save → quit → reload.
- Cooldown decrement (`cooldown_segments_raw > 0`) for `[caps]`: still NOT EXERCISED across all phases.

## Files modified / created in Phase 0-E

| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Added `BuildJson` field to `PendingSnapshot`; added `AppendBuildIdentity` + `_AttrCoqNames` / `_AttrJsonKeys` + `AppendBuildAttributes` + `NormalizeStomachStatus` + `AppendBuildResources` static helpers + `BuildBuildJson` entry point. ~211 lines added across Tasks 1-4. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Extended `HandleEvent` to build build JSON in a separate `try/catch` and populate `PendingSnapshot.BuildJson`. Extended `AfterRenderCallback` to emit a fourth LogInfo line `[LLMOfQud][build]`. Header comment updated to "four LogInfo calls". |
| `AGENTS.md`, `mod/AGENTS.md` | Corrected post-rebrand macOS paths (Kitfox Games → Freehold Games; Player.log moved from `$COQ_SAVE_DIR` to `~/Library/Logs/Freehold Games/CavesOfQud/`). Hygiene fix landed alongside Phase 0-E impl. |
| `.gitignore` | Added `__pycache__/` and `*.pyc` to suppress noise from `scripts/` test runs. |
| `docs/adr/0005-phase-0-e-current-build-state-pivot.md` | Records the design pivot from BirthBuildProfile to current build state; landed in PR-E1 (docs PR). |
| `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` | Design spec, codex PASS at commit `8861358`; landed in PR-E1. |
| `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` | Implementation plan; landed in PR-E1. |
| `docs/memo/phase-0-e-exit-2026-04-26.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:1787-1790` (game-queue routing rule), `:2802` (Phase 0-E line, reinterpreted by ADR 0005), `:443-468` (Phase 1+ `check_status` consumer of `[build]`), `:1696-1710` (Layer 3 Cross-Run Knowledge — deferred phase the retrospective birth-profile use case is gated on).
- `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — pivot from BirthBuildProfile to current build state.
- `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` — `current_build.v1` schema lock, field semantics, error posture.
- `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` — implementation plan.
- `docs/memo/phase-0-d-exit-2026-04-25.md` — Phase 0-D exit memo, "Feed-forward for Phase 0-E" section that seeded this phase's design questions.
- `mod/LLMOfQud/SnapshotState.cs` — build JSON helpers (`AppendBuildIdentity`, `AppendBuildAttributes`, `NormalizeStomachStatus`, `AppendBuildResources`, `BuildBuildJson`).
- `mod/LLMOfQud/LLMOfQudSystem.cs` — game-thread / render-thread split (4 LogInfo lines/turn).
- CoQ APIs verified during Phase 0-E (re-cite from `decompiled/`):
  - `decompiled/XRL.World/GameObject.cs:642` (`Level`), `:4373-4383` (`GetStat`), `:9353` (`GetPart<T>`), `:10019` (`GetGenotype`), `:10024` (`GetSubtype`), `:10029-10031` (`IsTrueKin`), `:10034-10036` (`IsMutant`).
  - `decompiled/XRL.World/Statistic.cs:51-53` (`Attributes`), `:238-252` (`Value` clamped getter).
  - `decompiled/XRL.World.Parts/Stomach.cs:87-102` (`FoodStatus`), `:104-143` (`WaterStatus`).
- Acceptance log artifact: `/tmp/phase-0-e-acceptance/Player.log.combined-truekin-mutant` (160 lines, both genotypes).
