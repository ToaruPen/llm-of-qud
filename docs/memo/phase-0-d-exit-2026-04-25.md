# Phase 0-D Exit — 2026-04-25

## Outcome
- True Mutant 112-turn run on Joppa: BEGIN == END == [state] == [caps] == 112. ERROR=0 across screen/state/caps.
- Latest [caps] line passes `json.loads` and has all 6 top-level v1 keys.
- Every-line JSON validity: 112/112 lines parse cleanly, 0 sentinels.
- First-turn vs last-turn shape parity OK.
- Semantic invariants (Warden-strict path) OK across all 112 non-sentinel turns: mutations / abilities / equipment all non-empty every turn, no duplicate `part_id` across slots, no `{{<color>|...}}` markup leakage in `ordinal_name`, `ui_display_level` is integer-typed.
- Cooldown spot-check: NOT EXERCISED — no ability had `cooldown_segments_raw > 0` across the 112 turns. Per acceptance criterion #9, documented and accepted.
- Initial 139-turn True Kin smoke run preceded this Warden-strict run. The True Kin pass surfaced the only issue caught this phase: a `MODWARN CS0618` for `BaseMutation.DisplayName.get` being `[Obsolete]` in CoQ 2.0.210 (commit `9d369ea`); switched to `m.GetDisplayName(WithAnnotations: false)` and re-verified clean compile + clean MODWARN scan on the second run.

## Acceptance counts

| Frame | Count |
|---|---|
| [screen] BEGIN | 112 |
| [screen] END | 112 |
| [state] | 112 |
| [caps] | 112 |
| ERROR (any frame) | 0 |

## Verified environment
- CoQ build: `2.0.210.24` (Unity `6000.0.41f1`), grepped from Player.log header
- Single-mod load order: `1: LLMOfQud` (QudJP / Dynamic Background Color / Equippable Handcart all `Skipping, state: Disabled` per `build_log.txt`)
- macOS path layout (Freehold Games):
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`
  - Roslyn assembly written to `$COQ_SAVE_DIR/ModAssemblies/LLMOfQud.dll` (transient — Roslyn-rebuilt every launch)
- Mod compile: `Compiling 3 files... Success :)` with `Defined symbol: MOD_LLMOFQUD`. No `MODWARN` for `LLMOfQud` after the obsolete-API fix.

## Sample shape (latest [caps] line, turn 112)
- `mutations` (8): `Night Vision`, `Regeneration`, `Wings`, `Kindle`, `Syphon Vim`, `Telepathy`, `Teleport Other`, `Quantum Jitters`. All `base_level=1 level=1 ui_display_level=1 is_active=true`. `can_level` correctly partitions: `true` for `Regeneration` / `Wings` / `Syphon Vim` / `Teleport Other`; `false` for `Night Vision` / `Kindle` / `Telepathy` / `Quantum Jitters` (passive / binary mutations).
- `abilities` (10): `Sprint`, `Make Camp`, `Lay Mine`, `Set Bomb`, `Recharge`, `Fly`, `Kindle`, `Syphon Vim`, `Telepathy`, `Teleport Other`. All `is_usable=true` (fresh save, no cooldowns). `Sprint` and `Fly` are toggleable (`toggleable=true`, `toggle_state=false` since untoggled). All `visible=false` on this build — note in "Open observations" below.
- `effects` (0): empty array. Acceptable on a clean run; helper exercise deferred to a future phase that picks up a transient effect.
- `equipment` (5): body (Cloth Robe), right hand (Dagger), left hand (Wrench), feet (Leather Moccasins), thrown weapon (ColdGrenade1). All `part_id=null` (`HasID()=false`). Per the Phase 0-D plan "Open hazards", consumers fall back to `(part_name, ordinal_name)` for slot identity.

## Phase 0-D-specific implementation rules (carry forward to 0-E+)
1. Caps JSON build runs on the game thread inside `HandleEvent(BeginTakeActionEvent)`. Render thread emits prepared strings only.
2. `PendingSnapshot.CapsJson` is the single threading slot for caps payload. Future caps fields (Phase 0-E `BirthBuildProfile`?) thread through this object, never as a parallel slot.
3. Per-turn cadence is full dump. Provisional clause: migrate to a better cadence if measured constraints justify it (see "Provisional cadence" below).
4. Schema is `runtime_caps.v1`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
5. `[caps]` failure is independent of `[screen]` and `[state]` — sentinel JSON (always parseable) replaces the data on a build error.
6. Effects observation point is post-`BeforeBeginTakeActionEvent` decrement (game-thread `BeginTakeActionEvent`). Effects with `Duration <= 0` are pre-`CleanEffects` ghosts and emit with `duration_kind: "unknown"`.
7. **Obsolete-API hygiene rule (new this phase):** any new CoQ-API call site MUST be checked against `decompiled/<path>.cs` for `[Obsolete]` attributes on the getter / setter / method. The CS0618 caught here was a non-fatal compile warning; future obsolete usages on hotter paths (e.g. `set DisplayName` triggering a `SyncMutationLevelsEvent`) could break runtime invariants silently.

## Provisional cadence — future revisit triggers
The every-turn full dump approach is provisional. Re-open the cadence design when ANY of the following becomes empirically true:
1. Phase 1 WebSocket boundary lands and per-turn payload becomes a measurable bandwidth or token-cost item.
2. `Player.log` size becomes a deployment-blocker on long streaming sessions, OR a single Unity log line approaches an output truncation limit (Unity historically truncates long single-line `Debug.Log` calls — re-verify under the Unity 6000.0.41f1 build CoQ 2.0.210 ships).
3. Provider-neutral request / token / cache-cost metrics show the redundant stable-list portion harms cost or cache reuse.
4. Phase 0-H `snapshot_hash` design needs separated stable / volatile components for a meaningful hash.
5. A future phase introduces inventory full dump and per-turn payload doubles.
6. Game-thread frame-time or GC pressure regression attributable to `BuildCapsJson` allocations (full `StringBuilder` + boxed numerics every turn). Profile under sustained Joppa play if subjective frame stutter appears around player-turn boundary.
7. Save / load round-trip semantics become load-bearing: `BodyPart.ID` is serialized state. If a phase ever re-uses `part_id` across save / load, validate that the value space we emit survives a save → quit → reload cycle.
8. The Brain becomes a programmatic `[caps]` consumer (parses every line, not only the latest). At that point latest-line manual JSON validity is no longer sufficient; gate must move to "every line parses cleanly" as a CI step.

At any of those triggers, re-evaluate the candidates noted in the Phase 0-D plan: hybrid cadence, on-demand pull, payload compression, WebSocket-side filtering, Brain-side diff.

## Open observations (recorded but not blocking)
- **`visible=false` for all 10 abilities on the True Mutant build.** `ActivatedAbilityEntry.Visible` (`decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:195`) is the UI-surface flag and was `false` on every ability across all 112 turns. The in-game ability menu still surfaces these abilities, so either (a) the menu reads a different visibility predicate, or (b) `Visible` is a per-turn / per-context dynamic flag we're catching at the wrong cycle point. Brain consumers should treat `visible` as advisory rather than authoritative for "is this ability shown to the player". Re-open in Phase 1 if the Brain needs to mirror the in-game menu exactly.
- **`part_id` was `null` for every equipped slot across both runs (139 + 112 = 251 turns total).** `HasID()` returned false for every body part — no slot was "asked for" by anything during normal play. The plan flagged this as expected; recording it as empirically confirmed. Slot identity uniqueness was verified via `(part_name, ordinal_name)` — no collisions across either run.
- **Cooldown decrement code path uncovered.** `cooldown_segments_raw > 0` was never observed across both runs. This means the `e.CommandCooldown != null` branch and the toggle-aware `e.Cooldown` getter special-case (`AlwaysAllowToggleOff && ToggleState && Toggleable`) are unexercised in the acceptance run. Phase 1+ Brain test runs that exercise abilities should be the first place this path is empirically validated.

## Feed-forward for Phase 0-E
Phase 0-E (`BirthBuildProfile`: genotype, calling, attributes) per `docs/architecture-v5.md:2802`. Decompiled starting points the next plan will likely need (verify before re-citing):
- `decompiled/XRL.World/GameObject.cs` — `GetGenotype()`, `GetSubtype()`, `GetGameStat`/`GetStat` for attributes
- `decompiled/XRL.World.Parts/Statistics.cs` — `Statistics["Strength"].Value/.BaseValue` etc
- `decompiled/XRL.UI/CharacterCreate.cs` (or equivalent) — birth-time vs runtime delta

Open design questions for Phase 0-E (not for this exit memo):
- Whether `BirthBuildProfile` is captured ONCE per character (write at birth, read until death) or recomputed every turn from current state. Since Phase 0-E is about birth attributes, write-once is natural — but the runtime currently has no observation point for "the moment of birth" and we may need an alternative anchor (first BeginTakeActionEvent? specific event?).
- Whether `BirthBuildProfile` lives in `[caps]` (re-open the v1 schema lock) or a new `[birth]` line.

## Open hazards (still tracked from earlier phases)
- Render-thread exception spam dedup: zero ERROR lines over 95 + 110 + 251 turns. Continue to defer.
- Multi-mod coexistence: untested across all four phases. Revisit when a phase needs multi-mod observation. Phase 0-D acceptance run had QudJP, Dynamic Background Color, and Equippable Handcart present but `Skipping, state: Disabled` — the `1: LLMOfQud` load order was clean.

## Files modified / created in Phase 0-D

| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Added `CapsJson` field to `PendingSnapshot`; added `BuildCapsJson` + `AppendMutations` + `AppendAbilities` + `AppendEffects` + `AppendEquipment` static helpers. ~250 lines. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Extended `HandleEvent` to build caps JSON in a separate `try/catch` and populate `PendingSnapshot.CapsJson`. Extended `AfterRenderCallback` to emit a third LogInfo line `[LLMOfQud][caps]`. |
| `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md` | Created at the start of Phase 0-D. |
| `docs/memo/phase-0-d-exit-2026-04-25.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:1787-1790` (game-queue routing rule), `:2801` (Phase 0-D scope), `:443-468` (Phase 2 `check_status` consumer that will read `[caps]`).
- `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md`
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate (every-line variant adopted here per plan Step 6b).
- `mod/LLMOfQud/SnapshotState.cs` — caps JSON build helpers.
- `mod/LLMOfQud/LLMOfQudSystem.cs` — game-thread / render-thread split (3 lines/turn).
- CoQ APIs (verify before re-citing): see Phase 0-D plan "Reference" section.
