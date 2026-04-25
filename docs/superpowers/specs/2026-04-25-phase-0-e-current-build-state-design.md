# Phase 0-E: Current Build State Observation — Design Spec

**Goal:** Emit one structured `[LLMOfQud][build] {...}` JSON line per player decision point, alongside the existing `[screen]` (0-B), `[state]` (0-C), and `[caps]` (0-D) frames. The new line carries the **current** build identity (genotype + subtype) and current attribute / level / hunger / thirst values — the fields Phase 2 `check_status` (`docs/architecture-v5.md:443-468`) consumes that are NOT already in `[state]` or `[caps]`. The Brain (Phase 1+) consumes this as the fourth per-turn observation primitive.

**Pivot from spec line `:2802`:** v5.9 spec at `docs/architecture-v5.md:2802` originally framed this phase as "BirthBuildProfile capture (genotype, calling, attributes)". This design pivots to **current build state** because the actual downstream consumer (`check_status` at `:443-468`) returns CURRENT attributes/level/hunger/thirst, not birth-time values. The "Birth" framing was leftover from earlier design iterations where retrospective build identity was the primary use; that retrospective use case (DeathLogger / cross-run learning per `:1683-1687`) is deferred to a later phase. The pivot requires a new ADR (numbered 0005, drafted as Task 0 of the implementation plan).

**Architecture (Phase 0-D mirror):**

- **Game thread (`HandleEvent(BeginTakeActionEvent)`)**: build the build JSON from `The.Player.GetGenotype()` / `GetSubtype()` / `GetStat(...)` / `GetPart<Stomach>()`. Same `try/catch` posture as 0-D's caps JSON: any exception becomes a sentinel `{"turn":N,"schema":"current_build.v1","error":{...}}` valid-JSON line.
- **`PendingSnapshot` extension, NOT a parallel slot.** Per `docs/memo/phase-0-c-exit-2026-04-25.md:117` (carried into 0-D): any new field threads through `PendingSnapshot`, never as a parallel `Interlocked.Exchange` slot. `PendingSnapshot` gains one new field: `string BuildJson`. The atomic publish becomes `(Turn, StateJson, DisplayMode, CapsJson, BuildJson)` as one ref-typed object swap.
- **Render thread (`AfterRenderCallback`)**: emit a fourth `MetricsManager.LogInfo` call: `[LLMOfQud][build] {...}` in its own `try` scope. **Honest fault isolation statement (corrected from earlier draft):** the existing `AfterRenderCallback` (`mod/LLMOfQud/LLMOfQudSystem.cs:220-253`) wraps the `[screen]` body walk and the `[state]` emit in a single `try`, with `[caps]` in a second `try` (`:260-268`). Phase 0-E adds a third `try` for `[build]`. Therefore: **`[caps]` and `[build]` are independently fault-isolated; `[screen]` and `[state]` share a single try and a failure in either path emits only the `[screen] ERROR` sentinel and skips the other.** Splitting `[screen]` and `[state]` into independent tries is out of 0-E scope (would re-open 0-C contracts). v1 acceptance counts assume that pre-existing coupling.
- **Per-turn output: 5 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]`.

**Cadence: every-turn full dump (provisional, same posture as 0-D).**

The Brain receives `[build]` every player decision point. Event-driven emission was evaluated and rejected (codex consultation 2026-04-25): CoQ events do not enumerably cover all paths that mutate the captured fields. Bypass paths:
- `Stomach.HungerLevel` / `Water` are direct field writes with no `HungerLevelChangedEvent` / `ThirstLevelChangedEvent` (`decompiled/XRL.World.Parts/Stomach.cs:30, 20, 608-643`).
- `Statistic._Value` / `_Bonus` / `_Penalty` / `Shifts` are backing fields exposed publicly (`decompiled/XRL.World/Statistic.cs:146, 154, 156, 158`); writes through these directly bypass `StatChangeEvent`.
- `Leveler.LevelUp()` mutates `Level.BaseValue` then several other stats sequentially, so a per-event emit would catch half-way state (`decompiled/XRL.World.Parts/Leveler.cs:261-298`).
- Genotype/subtype mutations have no canonical events at all — `GetGenotype` / `GetSubtype` are property/tag reads (`GameObject.cs:10019, 10024`); `SetStringProperty` / `RemoveStringProperty` update the dictionary without dispatching events (`:4193, 4208`).
- **Save/load deserialization restores stats directly.** `Statistic.Load` reads `_Value` / `_Bonus` / `_Penalty` / `Shifts` from the writer back into the fields and does NOT call `NotifyChange` (`decompiled/XRL.World/Statistic.cs:595-615`).
- Mod / Harmony patches can write to `Statistic._Value` etc. directly. Defensive only; v1 hazard, not a 0-E gate.

Effect-driven stat shifts DO go through events: `Confused` and similar effects use `StatShifter.SetStatShift()` → `Statistic.AddShift()` → `Bonus`/`Penalty`/`BaseValue` setters which call `NotifyChange()` (`decompiled/XRL.World/StatShifter.cs:122-166`, `decompiled/XRL.World/Statistic.cs:697-727`, `decompiled/XRL.World.Effects/Confused.cs:112-118`, `Statistic.cs:231, 272, 294, 646`). So effect application is NOT a bypass — but the other paths above still exist.

To make event-driven robust would require force-emit on `BeginTakeActionEvent` (first), `AfterGameLoadedEvent`, `AfterPlayerBodyChangeEvent`, WebSocket reconnect, and N-turn safety beacons — heavier than per-turn full dump for a ~200-byte payload.

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
  "hunger": "sated",
  "thirst": "quenched"
}
```

Field semantics:

- `turn`: integer, the same `_beginTurnCount` correlation key used by `[screen]` / `[state]` / `[caps]`. Required for raw log line correlation (parser does NOT assume adjacency — LogInfo lines from other game subsystems can interleave between the four).
- `schema`: literal string `"current_build.v1"`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
- `genotype_kind`: enum `"mutant" | "true_kin" | "unknown"`. Derived from `GameObject.IsTrueKin()` / `IsMutant()` (`decompiled/XRL.World/GameObject.cs:10029-10031, 10034-10036`). The `"unknown"` value covers the both-false case (which should not normally happen in CoQ but is exposed honestly rather than silently coerced — body-swap to a non-creature object could in principle reach it). Two-boolean form (`is_mutant + is_true_kin`) was rejected because it lets the LLM see impossible states (`true/true`, `false/false`).
- `genotype_id`: raw string from `player.GetGenotype()` (e.g., `"Mutated Human"`, `"True Kin"`). Emitted as JSON `null` if `GetGenotype()` returns C# null. **Implementation note:** the existing `SnapshotState.AppendJsonString` helper emits `""` (empty string) for null input (`mod/LLMOfQud/SnapshotState.cs:30-47`), NOT JSON `null`; the `BuildBuildJson` path therefore must explicitly emit `sb.Append("null")` for the null case rather than calling `AppendJsonString(sb, null)`. Source: `decompiled/XRL.World/GameObject.cs:10019`.
- `subtype_id`: raw string from `player.GetSubtype()` (e.g., `"Warden"`, `"Praetorian"`, `"Esper"`). Emitted as JSON `null` per the same explicit-null rule above when `GetSubtype()` returns null. Source: `decompiled/XRL.World/GameObject.cs:10024`. The `display_name` was dropped because in CoQ practice subtype id and display name are the same string; if a subtype is found where they diverge, schema bumps to v2 and adds `subtype_display_name` then.
- `level`: integer, `player.Level` (which returns the `Level` stat's `Value`, `decompiled/XRL.World/GameObject.cs:642`). Current effective level, includes any temporary modifiers if any exist. For Phase 0-E v1, `level` is treated as monotonic non-decreasing (level-up only); if a CoQ path is found that decreases level, it is logged but does not fail the gate.
- `attributes`: object with exactly 6 keys (lowercase: `strength`, `agility`, `toughness`, `intelligence`, `willpower`, `ego`), each value an integer. **Implementation note: CoQ's internal canonical attribute names are CapsCase** (`"Strength"`, `"Agility"`, …, per `Statistic.Attributes` at `decompiled/XRL.World/Statistic.cs:51-53`), and `GameObject.Statistics` is a `Dictionary<string, Statistic>` with exact-match `TryGetValue` (`decompiled/XRL.World/GameObject.cs:153, 4373-4383`). The implementation must read with the CapsCase key (`player.GetStat("Strength")`) and emit the JSON key in lowercase. The integer value is `Statistic.Value` — the **clamped, modifier-applied effective** value that combat math uses (`decompiled/XRL.World/Statistic.cs:238-252`). `_Value + _Bonus - _Penalty` semantics; consumers do NOT need to recompute. `base_value` and `modifier_total` were dropped because (1) Phase 0-D `[caps]` precedent of dual raw/effective applies to ability cooldowns where toggle special-cases create real semantic divergence; attributes have no analogous divergence relevant to Brain decisions, (2) `modifier_total` as `Value - BaseValue` is misleading because `Value` is clamped before subtraction.
- `hunger`: **string-or-null**. **Normalized** (markup-stripped, trailing `!` stripped, lowercased) form of CoQ's display bucket. Source: `Stomach.FoodStatus()` returns markup-wrapped strings — `{{g|Sated}}`, `{{W|Hungry}}`, `{{R|Wilted!}}` (only when player has `PhotosyntheticSkin` mutation), `{{R|Famished!}}` (`decompiled/XRL.World.Parts/Stomach.cs:87-102`). We normalize to `"sated" | "hungry" | "wilted" | "famished"`. **Emitted as JSON `null` when `player.GetPart<Stomach>()` is null** (robot body, body-swap to non-creature object) — see "Stomach-less body / amphibious body" hazard for v1 policy. The bucket-transition logic lives in `UpdateHunger()` (`Stomach.cs:608-643`). Note: `check_status` spec sample at `:462` shows `"satiated"`, but the actual CoQ display string is `"Sated"`; we use the lowercased CoQ form (`"sated"`) and the implementation plan must update `check_status` to match. Integer was dropped because it adds noise the LLM does not use.
- `thirst`: **string-or-null**. **Normalized** (markup-stripped, trailing `!` stripped, lowercased) form of CoQ's `Stomach.WaterStatus()` (`decompiled/XRL.World.Parts/Stomach.cs:104-143`). For non-amphibious bodies, the buckets are `"dehydrated"` (Water `<= 0`), `"parched"`, `"thirsty"`, `"quenched"`, `"tumescent"` (`Water > WATER_QUENCHED`, source `:142`). Thresholds come from `RuleSettings` (`decompiled/XRL.Rules/RuleSettings.cs:13-23`). Amphibious bodies use a different bucket family (`"desiccated" | "dry" | "moist" | "wet" | "soaked"` per `Stomach.cs:104-124`); see "Open hazards" for the v1 policy. **Emitted as JSON `null` when `Stomach` is absent**, same rule as `hunger`. The implementation reads `Stomach.WaterStatus()`, strips markup tokens (e.g., `{{R|...}}`), strips a trailing `!` if present, lowercases.

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
- Render thread `[build]` emit is in its own try scope. A `[build]` failure does NOT blank `[screen]` / `[state]` / `[caps]` (which have already emitted by then) — `[build]` is independently fault-isolated from both the existing `[screen]+[state]` group (one shared try) and the `[caps]` try (separate). See Architecture section for the honest fault-isolation statement; the `[screen]+[state]` shared-try posture is an inherited Phase 0-C/0-D constraint, not a new 0-E choice.
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
2. **Counts — primary run.** Over a single primary Joppa run with a Mutant build: `[screen] BEGIN == [screen] END == [state] == [caps] == [build] >= 100`. (Same `>=100` baseline as 0-D.)
3. **Counts — secondary smoke run.** Over a separate True Kin smoke run: `[screen] BEGIN == [screen] END == [state] == [caps] == [build] >= 10` (10–20 turns is sufficient — this run exists for genotype/subtype data variety, not for codepath divergence; see criterion 9).
4. **Hard error gate.** `ERR_SCREEN == 0` on both runs. Soft gates: `ERR_STATE == 0`, `ERR_CAPS == 0`, `ERR_BUILD == 0`. Non-zero counts are investigated and recorded in the exit memo; they do not mechanically fail (sentinel JSON is intentional defense in depth) but they are an ADR 0004 re-open trigger candidate.
5. **Latest-line JSON validity.** Latest `[build]` line on each run passes `json.loads` AND is non-sentinel (top-level keys do not include `error`) AND `schema == "current_build.v1"` AND required keys present (`turn, schema, genotype_kind, genotype_id, subtype_id, level, attributes, hunger, thirst`). If the very last `[build]` line of a run is a sentinel, the gate fails — graceful degradation is fine across the run, but the LAST observation must succeed (it is what the Brain would consume on a hot-resume).
6. **Every-line JSON validity + schema/key-set check.** All `[build]` lines on both runs parse cleanly. For each non-sentinel line: `schema == "current_build.v1"` AND the top-level key set is exactly `{turn, schema, genotype_kind, genotype_id, subtype_id, level, attributes, hunger, thirst}` (no missing, no extra). Sentinel-error lines (`{turn, schema, error}`) are tolerated but reported.
7. **Shape parity.** Evaluated only across non-sentinel lines: the first non-sentinel `[build]` line vs the last non-sentinel `[build]` line on the primary run have identical top-level keys. (Sentinel lines have a different key set — `{turn, schema, error}` — and are excluded from this comparison; criterion 6 already gates the per-line key set for non-sentinel lines.)
8. **Phase 0-E specific semantic invariants.** Across non-sentinel turns of both runs (Mutant + True Kin builds — both have `Stomach`, so `hunger != null && thirst != null` is required for every non-sentinel turn of acceptance; if any non-sentinel turn emits `hunger == null` or `thirst == null` on these builds, that's a hard failure indicating a `Stomach` lookup bug):
   - `attributes` has **exactly** the 6 lowercase keys `{strength, agility, toughness, intelligence, willpower, ego}` (set equality, order not asserted, no extra keys).
   - Each attribute value is a JSON integer.
   - `genotype_kind` is one of `"mutant" | "true_kin" | "unknown"`. **Count of `"unknown"` across both runs MUST be 0.** Any `"unknown"` is a hard failure for v1 (the body-swap / non-creature path that could legitimately produce it is out of scope; see open hazards).
   - `level` is a positive integer (`>= 1`).
   - `hunger != null` AND `hunger` is one of `{sated, hungry, wilted, famished}`. The bucket strings are derived from `Stomach.FoodStatus()` markup-stripped + trailing-`!`-stripped + lowercased (`decompiled/XRL.World.Parts/Stomach.cs:87-102`). `wilted` only occurs when the player has the `PhotosyntheticSkin` mutation; an acceptance run on a non-PhotosyntheticSkin Mutant will not exercise it. A new bucket observed empirically is a hard failure (would require schema documentation update).
   - `thirst != null` AND `thirst` is one of `{tumescent, quenched, thirsty, parched, dehydrated}` for non-amphibious bodies. The full bucket set is derived from `Stomach.WaterStatus()` (`decompiled/XRL.World.Parts/Stomach.cs:104-143`) + `RuleSettings` thresholds (`decompiled/XRL.Rules/RuleSettings.cs:13-23`), markup-stripped + lowercased; a new bucket observed empirically is a hard failure (amphibious-body bucket family is documented in open hazards but is out of scope for the gate).
9. **Two-build smoke (0-E specific) — for data variety, not codepath divergence.** The primary run uses a Mutant build (existing Phase 0-D acceptance reusable, e.g., the True Mutant 8-mutation Warden). The secondary smoke run uses a True Kin build (e.g., Praetorian or any True Kin starting calling). Justification: `BuildBuildJson` does NOT branch on genotype — it calls `IsTrueKin()` / `IsMutant()` and reads the same six attribute keys / `Stomach` / `Level` for either case. The second run exists to (a) verify `genotype_kind` resolves to `"true_kin"` (covering the enum branch a single Mutant run never hits), and (b) verify the True-Kin-side `subtype_id` data (Praetorian etc.) parses as a non-null string. Both runs MUST satisfy: `genotype_id` non-null, `subtype_id` non-null, `genotype_kind` matches the build (`"mutant"` for primary, `"true_kin"` for secondary).
10. **Single-mod load order.** Acceptance runs performed with only `LLMOfQud` enabled (Phase 0-D parity).
11. **Spec-correction ADR landed.** ADR 0005 is committed before the implementation lands. See "ADR 0005 timing" below for the merge order trade-off.
12. **Exit memo committed.** `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` exists on the branch.

**Open hazards / future revisit:**

- **Hunger/thirst bucket stability.** Bucket strings are derived from `Stomach.FoodStatus()` / `Stomach.WaterStatus()` (`decompiled/XRL.World.Parts/Stomach.cs:87-143`) and `RuleSettings` thresholds (`decompiled/XRL.Rules/RuleSettings.cs:13-23`). For Phase 0-E v1, the documented bucket sets in criterion 8 are treated as a closed enum (a new bucket observed empirically is a hard failure → schema documentation update + acceptance re-run, not a silent extension). Amphibious-body buckets (`desiccated/dry/moist/wet/soaked` per `Stomach.cs:104-124`) are excluded from the v1 gate; if a Phase 1+ build path hits one, the Brain sees it but the gate does not assert.
- **Stomach-less body / amphibious body.** `BuildBuildJson` reads `player.GetPart<Stomach>()`. v1 policy: if `Stomach` is null (robot body, body-swap into a non-creature object via `AfterPlayerBodyChangeEvent`), `hunger` and `thirst` are emitted as JSON `null`. The schema `current_build.v1` therefore allows `hunger: string | null` and `thirst: string | null`. Acceptance criterion 8 is conditioned on `hunger != null && thirst != null` for non-sentinel turns of the two acceptance runs (both Mutant and True Kin builds have `Stomach`); a Stomach-less body run is out of v1 acceptance scope but the schema is forward-compatible.
- **Subtype display divergence.** v1 emits `subtype_id` only. If a future build path produces `subtype_id != display_name` (e.g., localized display vs canonical id), the v1 line silently emits the canonical id only. v2 + ADR if Brain prompts need the displayed string.
- **Level monotonicity.** Treated as monotonic non-decreasing in v1. If a path is found that decreases level (death + revive? mod hooks?), exit memo records the empirical case; semantic invariants are NOT updated to require monotonicity (no false-positive failure).
- **`Value` clamp invisibility.** `Statistic.Value` already applies CoQ's hard clamps (cybernetic limits, mutation bonuses). Brain consumers do not see the unclamped raw `_Value` on purpose — combat math uses `Value`. If a Phase 1+ Brain finds it needs the unclamped raw, schema v2 + ADR.
- **Multi-mod coexistence.** Untested across all five phases. Same posture as 0-B/0-C/0-D.
- **Save/load resilience.** `Stomach`/`Statistic`/`GameObject` survive save round-trip per existing serialization (the `Statistic.Load` deserialization path at `decompiled/XRL.World/Statistic.cs:595-615` is one of the bypass-event paths that motivated per-turn full dump). Genotype/subtype property strings survive. **Save/load specific re-open trigger:** if any non-sentinel `[build]` line emitted on the first turn after `AfterGameLoadedEvent` (`decompiled/XRL.World/AfterGameLoadedEvent.cs:27`) shows attribute / level / hunger / thirst values inconsistent with the pre-save state — i.e., the dump appears to read stale or zero-initialized fields after deserialization — that is an acceptance failure and triggers re-evaluating cadence / capture point. Exit memo of the acceptance run must explicitly state whether at least one save → load round-trip occurred during the primary run; if zero load events occurred, the exit memo records this as a coverage gap rather than passing the trigger.
- **`check_status` adapter responsibility (Phase 1+, not 0-E scope, but architecturally relevant).** `check_status` (`docs/architecture-v5.md:443-468`) returns `{hp, level, attributes, active_effects, cooldowns, hunger, thirst, equipment_summary}`. After Phase 0-E lands, the per-turn line set is sufficient to synthesize that contract, but with field-name mapping the Phase 1+ Python adapter must perform: (a) `equipment_summary` is a free-form summary string the adapter synthesizes from `[caps].equipment[]`; the v1 mod does NOT emit `equipment_summary`. (b) `active_effects[].name` ← `[caps].effects[].display_name_stripped`; `active_effects[].turns_remaining` ← `[caps].effects[].duration_raw` (or whichever 0-D field the exit memo settled on — adapter must verify against the 0-D exit memo before consumption). (c) `cooldowns[]` ← `[caps].abilities[]` filtered to those with non-zero cooldown. (d) `hp` ← `[state].player.hp` (already in v1 0-C). The 0-E `[build]` line directly supplies `level`, `attributes`, `hunger`, `thirst` with no transformation other than the `check_status`-side string-bucket name harmonization (e.g., if the consumer prefers `"satiated"` over our normalized `"sated"`, the harmonization happens in the adapter, not in the mod).

**ADR 0005 timing — separate prerequisite docs PR (precedent: Phase 0-C):**

The ADR re-opens the `:2802` Phase 0-E line semantics (BirthBuildProfile → current build state) and changes the consumer-facing surface. Two viable orderings:

1. **Separate prerequisite docs-only PR** (Phase 0-C precedent — the Phase 0-C readiness docs-only PR `ab96d30` (#7) landed `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` plus the Phase 0-C plan body BEFORE the Phase 0-C implementation PR `1afbf01` (#9); the same PR also bundled the unrelated `docs/adr/0003-phase-0-a-task-7-closure-by-design.md` for Phase 0-A closure, which is a separate concern, not the Phase 0-C ADR): the ADR PR lands first; the implementation PR opens against `main` after the ADR is on `main`. Pro: clean review history (the design pivot is reviewed independently of the C# diff). Pro: if the ADR is rejected / requires major revision, no code thrown away. Con: two PRs, two CI runs, one more merge step.
2. **Single PR with ADR commit first**: the implementation branch opens with commit 1 = ADR 0005, commits 2..N = code + spec + plan + memo. Pro: atomic ship. Con: ADR review happens alongside C# review; reviewers cannot reason about the design pivot separately from the implementation.

**Decision (recorded in ADR 0005 itself, not relitigated by implementation):** option (1), separate prerequisite docs-only PR. Phase 0-C precedent applies because Phase 0-E is also a spec-pivoting phase; merge order: ADR PR → spec/plan PR (this design + the implementation plan can co-land in one docs-only PR if convenient) → implementation PR. Phase 0-D, by contrast, was within-locked-schema and required no ADR — the comparison does not apply here.

If the user explicitly opts for option (2) at execution time (e.g., to ship in one merge for the streaming-build deadline), the implementation plan accommodates by reordering Task 0 (ADR commit) to be the first commit on the implementation branch and dropping the prerequisite-PR step. The plan documents both paths.

**References:**

- `docs/architecture-v5.md` (v5.9, frozen): `:443-468` (`check_status` consumer contract — drove the pivot), `:1718` (`BuildProfileCapture.cs` — the spec component that holds both BirthBuildProfile + RuntimeCapabilityProfile per v5.9), `:1734` (`AssessmentHandler` dispatching to `BuildProfile`), `:1787-1790` (game-queue routing rule), `:2802` (Phase 0-E line being reinterpreted by ADR 0005).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0005.
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` — render-callback emit pattern this design extends to 4 lines/turn.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/memo/phase-0-c-exit-2026-04-25.md:111-137` — "Phase 0-C-specific implementation rules (still in force)" carried forward.
- `docs/memo/phase-0-d-exit-2026-04-25.md` — Phase 0-D outcomes; `:42-58` provisional cadence trigger list inherited; "Feed-forward for Phase 0-E" section is the source for the open questions resolved in this design.
- `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md` — precedent plan structure to model the 0-E plan on.
- CoQ APIs (verified 2026-04-25):
  - **Player identity**: `GameObject.GetGenotype()` (`decompiled/XRL.World/GameObject.cs:10019`), `GetSubtype()` (`:10024`), `IsTrueKin()` (`:10029-10031`), `IsMutant()` (`:10034-10036`), `genotypeEntry` (`:312-323`), `subtypeEntry` (`:325-336`).
  - **Statistics**: `Statistic.Value` getter (`decompiled/XRL.World/Statistic.cs:238-252`), `BaseValue` (`:218-233`), `_Value` / `_Bonus` / `_Penalty` / `Shifts` backing fields (`:146, 154, 156, 158`), canonical attribute list `Statistic.Attributes` (`:51-53`), `NotifyChange` call sites (`:231, 272, 294`) and method body (`:646`), `Statistic.Load` (`:595-615`).
  - **Level**: `GameObject.Level` (`decompiled/XRL.World/GameObject.cs:642`), `Leveler` (`decompiled/XRL.World.Parts/Leveler.cs:30-105, 261-298`).
  - **Hunger / thirst**: `Stomach.HungerLevel` field (`decompiled/XRL.World.Parts/Stomach.cs:30`), `Stomach.FoodStatus()` (`:87-102`), `UpdateHunger()` (`:608-643`), `Stomach.Water` field (`:20`), `Stomach.WaterStatus()` (`:104-143`), water-update flow (`:237-284`), `RuleSettings` thresholds (`decompiled/XRL.Rules/RuleSettings.cs:13-23`).
  - **Stat write paths bypassing events** (relevant to event-driven rejection): `_Value`/`_Bonus`/`_Penalty`/`Shifts` (`Statistic.cs:146, 154, 156, 158`); `Statistic.Load` save/load deserialization (`:595-615`); `SetStringProperty` / `RemoveStringProperty` for genotype/subtype (`GameObject.cs:4193, 4208`).
  - **Save/load + body-swap re-anchors** (also relevant to event-driven rejection): `AfterGameLoadedEvent` (`decompiled/XRL.World/AfterGameLoadedEvent.cs:27`), `AfterPlayerBodyChangeEvent` (`decompiled/XRL.World/GamePlayer.cs:80, 105`).
  - **MetricsManager.LogInfo**: `decompiled/MetricsManager.cs:407-409` (unchanged, same `Player.log` sink as 0-B/0-C/0-D).
