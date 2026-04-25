# Phase 0-E: Current Build State Observation — Design Spec

**Goal:** Emit one structured `[LLMOfQud][build] {...}` JSON line per player decision point, alongside the existing `[screen]` (0-B), `[state]` (0-C), and `[caps]` (0-D) frames. The new line carries the **current** build identity (genotype + subtype) and current attribute / level / hunger / thirst values — the fields Phase 2 `check_status` (`docs/architecture-v5.md:443-468`) consumes that are NOT already in `[state]` or `[caps]`. The Brain (Phase 1+) consumes this as the fourth per-turn observation primitive.

**Pivot from spec line `:2802`:** v5.9 spec at `docs/architecture-v5.md:2802` originally framed this phase as "BirthBuildProfile capture (genotype, calling, attributes)". This design pivots to **current build state** because the actual downstream consumer (`check_status` at `:443-468`) returns CURRENT attributes/level/hunger/thirst, not birth-time values. The "Birth" framing was leftover from earlier design iterations where retrospective build identity was the primary use; that retrospective use case (DeathLogger / cross-run learning per `:1683-1687`) is deferred to a later phase. The pivot requires a new ADR (numbered 0005, drafted as Task 0 of the implementation plan).

**Architecture (Phase 0-D mirror):**

- **Game thread (`HandleEvent(BeginTakeActionEvent)`)**: build the build JSON from `The.Player.GetGenotype()` / `GetSubtype()` / `GetStat(...)` / `GetPart<Stomach>()`. Same `try/catch` posture as 0-D's caps JSON: any exception becomes a sentinel `{"turn":N,"schema":"current_build.v1","error":{...}}` valid-JSON line.
- **`PendingSnapshot` extension, NOT a parallel slot.** Per `docs/memo/phase-0-c-exit-2026-04-25.md:117` (carried into 0-D): any new field threads through `PendingSnapshot`, never as a parallel `Interlocked.Exchange` slot. `PendingSnapshot` gains one new field: `string BuildJson`. The atomic publish becomes `(Turn, StateJson, DisplayMode, CapsJson, BuildJson)` as one ref-typed object swap.
- **Render thread (`AfterRenderCallback`)**: emit a fourth `MetricsManager.LogInfo` call: `[LLMOfQud][build] {...}`. The line is **independent** of `[caps]` / `[state]` / `[screen]` — if any one of the four fails, only that one becomes the error sentinel; the other three are unaffected.
- **Per-turn output: 5 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]`.

**Cadence: every-turn full dump (provisional, same posture as 0-D).**

The Brain receives `[build]` every player decision point. Event-driven emission was evaluated and rejected (codex consultation 2026-04-25): CoQ events do not enumerably cover all paths that mutate the captured fields — `Stomach.HungerLevel` / `Water` are direct field writes with no `HungerLevelChangedEvent` / `ThirstLevelChangedEvent` (`decompiled/XRL.World.Parts/Stomach.cs:30, 20, 608-643`); `Statistic._Value`/`_Bonus`/`_Penalty`/`Shifts` are public-ish backing fields that bypass `StatChangeEvent` when written directly (`decompiled/XRL.World/Statistic.cs:146, 154, 158`); `Leveler.LevelUp()` mutates `Level.BaseValue` then several other stats sequentially, so a per-event emit would catch half-way state (`decompiled/XRL.World.Parts/Leveler.cs:261-298`); genotype/subtype mutations have no canonical events at all (`GameObject.cs:10019, 10024, 4193, 4208`). To make event-driven robust would require force-emit on `BeginTakeActionEvent` (first), `AfterGameLoadedEvent`, `AfterPlayerBodyChangeEvent`, WebSocket reconnect, and N-turn safety beacons — heavier than per-turn full dump for a ~200-byte payload.

Phase 0-D's "Provisional cadence" clause is inherited verbatim: re-open if measured constraints (Player.log size, prompt cache hit rate, WebSocket bandwidth, snapshot_hash design, etc.) justify it. The `[build]` payload is small (~200 bytes) compared to `[caps]` (~5 KB observed), so cadence pressure is unlikely to come from this line first.

**Schema lock: `current_build.v1`.**

```json
{
  "turn": 47,
  "schema": "current_build.v1",
  "genotype_kind": "mutant",
  "genotype_id": "Mutated Human",
  "subtype_id": "Warden",
  "level": 3,
  "attributes": {
    "strength": 18,
    "agility": 16,
    "toughness": 14,
    "intelligence": 12,
    "willpower": 14,
    "ego": 12
  },
  "hunger": "satiated",
  "thirst": "quenched"
}
```

Field semantics:

- `turn`: integer, the same `_beginTurnCount` correlation key used by `[screen]` / `[state]` / `[caps]`. Required for raw log line correlation (parser does NOT assume adjacency — LogInfo lines from other game subsystems can interleave between the four).
- `schema`: literal string `"current_build.v1"`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
- `genotype_kind`: enum `"mutant" | "true_kin" | "unknown"`. Derived from `GameObject.IsMutant()` / `IsTrueKin()` (`decompiled/XRL.World/GameObject.cs:10031, 10036`). The `"unknown"` value covers the both-false case (which should not normally happen in CoQ but is exposed honestly rather than silently coerced). Two-boolean form (`is_mutant + is_true_kin`) was rejected because it lets the LLM see impossible states (`true/true`, `false/false`).
- `genotype_id`: raw string from `player.GetGenotype()` (e.g., `"Mutated Human"`, `"True Kin"`). `null` if `GetGenotype()` returns null. `decompiled/XRL.World/GameObject.cs:10019`.
- `subtype_id`: raw string from `player.GetSubtype()` (e.g., `"Warden"`, `"Praetorian"`, `"Esper"`). `null` if `GetSubtype()` returns null. `decompiled/XRL.World/GameObject.cs:10024`. The `display_name` was dropped because in CoQ practice subtype id and display name are the same string; if a subtype is found where they diverge, schema bumps to v2 and adds `subtype_display_name` then.
- `level`: integer, `player.Level` (which returns the `Level` stat's `Value`, `decompiled/XRL.World/GameObject.cs:642`). Current effective level, includes any temporary modifiers if any exist. For Phase 0-E v1, `level` is treated as monotonic non-decreasing (level-up only); if a CoQ path is found that decreases level, it is logged but does not fail the gate.
- `attributes`: object with exactly 6 keys (lowercase: `strength`, `agility`, `toughness`, `intelligence`, `willpower`, `ego`), each value an integer. The integer is `Statistic.Value` — the **clamped, modifier-applied effective** value that combat math uses (`decompiled/XRL.World/Statistic.cs:238-252`). `_Value + _Bonus - _Penalty` semantics; consumers do NOT need to recompute. `base_value` and `modifier_total` were dropped because (1) Phase 0-D `[caps]` precedent of dual raw/effective applies to ability cooldowns where toggle special-cases create real semantic divergence; attributes have no analogous divergence relevant to Brain decisions, (2) `modifier_total` as `Value - BaseValue` is misleading because `Value` is clamped before subtraction.
- `hunger`: string. CoQ's bucket name from `Stomach.HungerLevel` mapping (`decompiled/XRL.World.Parts/Stomach.cs:87-102, 608-643`): `"satiated"` (level 0), `"hungry"` (level 1), `"famished"` (level 2). Matches `check_status` spec contract at `:462`. Integer was dropped because it adds noise the LLM does not use.
- `thirst`: string. CoQ's bucket name derived from `Stomach.Water` against `RuleSettings` thresholds (`decompiled/XRL.World.Parts/Stomach.cs:104-143`, thresholds `decompiled/XRL.Rules/RuleSettings.cs:13-23`). Buckets approximately: `"quenched"`, `"thirsty"`, `"parched"`, `"dehydrated"`. Exact bucket boundaries are read from `RuleSettings` at runtime, not hardcoded. Matches `check_status` contract at `:462`.

**Out of scope for `current_build.v1` (deferred):**

- `XP` / `xp_to_next_level`: tracked by `Leveler` but Brain has no level-up action surface yet (Phase 0-G+). Defer.
- `attribute_points`: unspent attribute points awaiting investment. Same Brain-action gate; defer.
- `pronouns` / `name`: identity fields not relevant for combat / exploration decisions. If Phase 1+ Brain prompt needs first-person referent, add as v2.
- `genotype_description` / `subtype_description`: spec at `:444-468` does not include description text. Codex pushed back: `GenotypeEntry.GetChargenInfo()` is a chargen-time UI generation surface (markup-laden), not a Brain consumption surface. Out of scope.
- Starting equipment delta (what was given at birth and now lost / consumed). Equipment is already in `[caps]`; "starting" means a separate snapshot. Out of scope.
- Per-attribute `base_value` / modifier provenance: out for v1, possible v2 if Brain needs to reason about temporary debuffs vs permanent build.
- Derived booleans like `is_satiated_and_hydrated`: LLM reads from string buckets directly. No.
- C# unit tests for `AppendBuild` helpers: deferred to Phase 2a per ADR 0004 (substituted manual JSON-validity gate).

**Error posture (Phase 0-D parity):**

- `BuildBuildJson` runs in its own `try/catch` on the game thread. Failure produces `{"turn":N,"schema":"current_build.v1","error":{"type":"...","message":"..."}}` — a valid-JSON sentinel using the existing `SnapshotState.AppendJsonString` helper (RFC-8259 escape, including U+0000-U+001F / U+2028 / U+2029 — same defense-in-depth as 0-D's caps sentinel).
- Render thread `[build]` emit is in its own try scope. A `[build]` failure does NOT blank `[screen]` / `[state]` / `[caps]` (which have already emitted by then) — the four lines are independently fault-isolated.
- Per-field error is NOT supported. Whole-line sentinel only. If a single field read throws, the whole `[build]` line for that turn becomes the error sentinel. This matches Phase 0-D and keeps parser logic simple.
- `subtypeEntry` resolution failures (e.g., entry missing from Factory after a save/load) are graceful: `subtype_id` falls back to whatever `GetSubtype()` returned (raw string property), and `display_name` was already dropped from v1 so there is no entry-derived field that can fail mid-line. (If display names are added in v2, the v2 schema must define a sentinel for entry-resolution failure.)

**Files modified / created:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `BuildJson` field to `PendingSnapshot`; add `BuildBuildJson(int turn, GameObject player)` static method; add `AppendBuildIdentity(StringBuilder, GameObject)` and `AppendBuildAttributes(StringBuilder, GameObject)` and `AppendBuildResources(StringBuilder, GameObject)` helpers (split for clarity / per-section error isolation if needed). Reuse the existing `AppendJsonString` for all string escapes.
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs` — extend `HandleEvent(BeginTakeActionEvent)`: build `buildJson` on the game thread in a separate `try/catch`, populate `PendingSnapshot.BuildJson`. Extend `AfterRenderCallback`: emit the fourth `MetricsManager.LogInfo("[LLMOfQud][build] " + buildJson)` after the existing `[caps]` emission. The new call sits in its own `try` scope.
- Create: `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — ADR documenting the spec pivot from "BirthBuildProfile" to current build state. Cite spec `:2802` (original phase line) and `:443-468` (consumer contract that drove the pivot). The ADR re-opens Phase 0-E semantics; Phase 0-? for retrospective birth profile (DeathLogger / cross-run learning per `:1683-1687`) remains a future open phase.
- Create: `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-d-exit-2026-04-25.md` shape.

No other source file changes. No manifest edits. The Roslyn compile set stays at 3 files (`LLMOfQudSystem.cs`, `SnapshotState.cs`, plus any future split — unchanged for this phase).

**Acceptance criteria (rollup):**

A Phase 0-E acceptance run is PASS iff all of the following hold:

1. **Compile clean.** `build_log.txt` shows `Compiling 3 file(s)... Success :)` for `LLMOfQud`. No `COMPILER ERRORS` for the mod. No `MODWARN CS0618` (codebase-level obsolete-API hygiene from Phase 0-D).
2. **Counts.** `[screen] BEGIN == [screen] END == [state] == [caps] == [build] >= 100` over a single Joppa run. (Same `>=100` baseline as 0-D.)
3. **Hard error gate.** `ERR_SCREEN == 0`. Soft gates: `ERR_STATE == 0`, `ERR_CAPS == 0`, `ERR_BUILD == 0`. Non-zero counts are investigated and recorded in the exit memo; they do not mechanically fail (sentinel JSON is intentional defense in depth) but they are an ADR 0004 re-open trigger candidate.
4. **Latest-line JSON validity.** Latest `[build]` line passes `json.loads`; `schema == "current_build.v1"`; required keys present (`turn, schema, genotype_kind, genotype_id, subtype_id, level, attributes, hunger, thirst`).
5. **Every-line JSON validity.** All `[build]` lines parse cleanly. Sentinel-error lines are tolerated but reported.
6. **Shape parity.** First-turn vs last-turn `[build]` line have identical top-level keys.
7. **Phase 0-E specific semantic invariants.** Across non-sentinel turns:
   - `attributes` has exactly the 6 lowercase keys (set equality, order not asserted).
   - Each attribute value is a JSON integer.
   - `genotype_kind` is one of `"mutant" | "true_kin" | "unknown"`.
   - `level` is a positive integer.
   - `hunger` is one of the documented bucket strings (`satiated`, `hungry`, `famished` — extend if a new value is observed empirically).
   - `thirst` is one of the documented bucket strings (initial set: `quenched`, `thirsty`, `parched`, `dehydrated`; extend on empirical observation).
8. **Two-build smoke (0-E specific).** Acceptance covers TWO character runs: (a) a Mutant build (existing Phase 0-D acceptance reusable, e.g., the True Mutant 8-mutation Warden), and (b) a True Kin build (e.g., Praetorian or any True Kin starting calling). Both runs emit `[build]` cleanly; `genotype_kind` is `"mutant"` and `"true_kin"` respectively; `subtype_id` matches the in-game subtype display.
9. **Single-mod load order.** Acceptance runs performed with only `LLMOfQud` enabled (Phase 0-D parity).
10. **Spec-correction ADR landed.** ADR 0005 is committed alongside the implementation. The plan's Task 0 lands the ADR before any code-edit task.
11. **Exit memo committed.** `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` exists on the branch.

**Open hazards / future revisit:**

- **Hunger/thirst bucket stability.** Codex pointed at `decompiled/XRL.World.Parts/Stomach.cs:104-143` and `decompiled/XRL.Rules/RuleSettings.cs:13-23` as the source of bucket boundaries. If CoQ updates change bucket names or thresholds, the Phase 0-E v1 schema does not re-version; the schema documents the bucket strings as **observed at runtime**, not as a fixed enum.
- **Subtype display divergence.** v1 emits `subtype_id` only. If a future build path produces `subtype_id != display_name` (e.g., localized display vs canonical id), the v1 line silently emits the canonical id only. v2 + ADR if Brain prompts need the displayed string.
- **Level monotonicity.** Treated as monotonic non-decreasing in v1. If a path is found that decreases level (death + revive? mod hooks?), exit memo records the empirical case; semantic invariants are NOT updated to require monotonicity (no false-positive failure).
- **`Value` clamp invisibility.** `Statistic.Value` already applies CoQ's hard clamps (cybernetic limits, mutation bonuses). Brain consumers do not see the unclamped raw `_Value` on purpose — combat math uses `Value`. If a Phase 1+ Brain finds it needs the unclamped raw, schema v2 + ADR.
- **Multi-mod coexistence.** Untested across all five phases. Same posture as 0-B/0-C/0-D.
- **Save/load resilience.** `Stomach`/`Statistic`/`GameObject` survive save round-trip per existing serialization. Genotype/subtype property strings survive. Empirically validated as part of Task 6 acceptance run.

**References:**

- `docs/architecture-v5.md` (v5.9, frozen): `:443-468` (`check_status` consumer contract — drove the pivot), `:1718` (`BuildProfileCapture.cs` — the spec component that holds both BirthBuildProfile + RuntimeCapabilityProfile per v5.9), `:1734` (`AssessmentHandler` dispatching to `BuildProfile`), `:1787-1790` (game-queue routing rule), `:2802` (Phase 0-E line being reinterpreted by ADR 0005).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0005.
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` — render-callback emit pattern this design extends to 4 lines/turn.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/memo/phase-0-c-exit-2026-04-25.md:111-137` — "Phase 0-C-specific implementation rules (still in force)" carried forward.
- `docs/memo/phase-0-d-exit-2026-04-25.md` — Phase 0-D outcomes; `:42-58` provisional cadence trigger list inherited; "Feed-forward for Phase 0-E" section is the source for the open questions resolved in this design.
- `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md` — precedent plan structure to model the 0-E plan on.
- CoQ APIs (verified 2026-04-25):
  - **Player identity**: `GameObject.GetGenotype()` (`decompiled/XRL.World/GameObject.cs:10019`), `GetSubtype()` (`:10024`), `IsMutant()` (`:10031`), `IsTrueKin()` (`:10036`), `genotypeEntry` (`:312-323`), `subtypeEntry` (`:325-336`).
  - **Statistics**: `Statistic.Value` getter (`decompiled/XRL.World/Statistic.cs:238-252`), `BaseValue` (`:218-233`), `_Value` / `_Bonus` / `_Penalty` backing fields (`:146, 154, 158`), canonical attribute list `Statistic.Attributes` (`:51-53`), `NotifyChange` → `StatChangeEvent` (`:255, 277, 646, 670`).
  - **Level**: `GameObject.Level` (`decompiled/XRL.World/GameObject.cs:642`), `Leveler` (`decompiled/XRL.World.Parts/Leveler.cs:30-105, 261-298`).
  - **Hunger / thirst**: `Stomach.HungerLevel` field (`decompiled/XRL.World.Parts/Stomach.cs:30, 87-102, 608-643`), `Stomach.Water` field (`:20, 104-143, 237-284`), `RuleSettings` thresholds (`decompiled/XRL.Rules/RuleSettings.cs:13-23`).
  - **Stat write paths bypassing events** (relevant to event-driven rejection): `_Value`/`_Bonus`/`_Penalty`/`Shifts` (`Statistic.cs:146, 154, 158`); `SetStringProperty` / `RemoveStringProperty` for genotype/subtype (`GameObject.cs:4193, 4208`).
  - **Save/load + body-swap re-anchors** (also relevant to event-driven rejection): `AfterGameLoadedEvent` (`decompiled/XRL.World/AfterGameLoadedEvent.cs:27`), `AfterPlayerBodyChangeEvent` (`decompiled/XRL.World/GamePlayer.cs:80, 105`).
  - **MetricsManager.LogInfo**: `decompiled/MetricsManager.cs:407-409` (unchanged, same `Player.log` sink as 0-B/0-C/0-D).
