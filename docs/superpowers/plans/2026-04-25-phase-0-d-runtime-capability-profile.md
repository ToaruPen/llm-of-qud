# Phase 0-D: RuntimeCapabilityProfile Observation (mutations, abilities, cooldowns, effects, equipment) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one structured `[LLMOfQud][caps] {...}` JSON line per player decision point, alongside the existing `[screen]` (0-B) and `[state]` (0-C) frames. The new line carries a `RuntimeCapabilityProfile`: passive + active mutations with levels, activated abilities with cooldown rollup + raw segments + `is_usable`, status effects with raw `Duration` + `duration_kind`, equipment slots with `BodyPart` identity. The Python Brain (Phase 1+) consumes this as the third per-turn observation primitive without re-deriving capability state from `[screen]` glyphs or `[state]` HP.

**Architecture:**
- **Same threading split as Phase 0-C** (`docs/architecture-v5.md:1787-1790`, `docs/memo/phase-0-c-exit-2026-04-25.md:116-117`):
  - Game thread (`HandleEvent(BeginTakeActionEvent)`): build the caps JSON from `The.Player.GetPart<Mutations>()` / `GetPart<ActivatedAbilities>()` / `Effects` / `GetPart<Body>()`. Same `try/catch` posture as 0-C's state JSON: any exception becomes a sentinel `{"turn":N,"schema":"runtime_caps.v1","error":{...}}` valid-JSON line.
  - Render thread (`AfterRenderCallback`): consume the existing `PendingSnapshot` slot, emit a third `MetricsManager.LogInfo` call: `[LLMOfQud][caps] {"turn":N,"schema":"runtime_caps.v1",...}`. The line is **independent** of `[state]` — if `[state]` builds successfully but `[caps]` fails, only `[caps]` becomes the error sentinel; `[state]` is unaffected.
- **Slot extension, not parallel slot.** Per the Phase 0-C exit memo's standing rule (`docs/memo/phase-0-c-exit-2026-04-25.md:117`), any new field threads through `PendingSnapshot`, never as a parallel `Interlocked.Exchange` slot. `PendingSnapshot` gains one new field: `string CapsJson`. `(Turn, StateJson, DisplayMode, CapsJson)` continues to be published atomically as one ref-typed object swap.
- **Separate `[caps]` line, not `[state]` extension.** Per Codex 2026-04-25 advisory + the Phase 0-C exit memo's "Open design questions" Q1 framing: `[state]` is already ~5 KB at turn=110 with growth-from-entities risk; `[caps]` carves an independent growth boundary. The line emits at `cadence(per-turn)`, mirrors the existing two-line per-turn pattern, and gives Phase 1+ the option to filter / compress / queue capability lines independently (see "Provisional cadence" below).
- **Schema versioning in payload.** Every `[caps]` line begins `{"turn":N,"schema":"runtime_caps.v1",...}`. Phase 1+ WebSocket / Codex API consumers anchor on `schema` for forward-compatible field additions. Bumping the version requires an ADR.

**Provisional cadence (every-turn full dump):**
- 0-D emits a full caps profile every player decision point. No diffing, no trigger-driven delta path, no cadence split between volatile (cooldowns / effects) and stable (mutation / equipment list) fields. Rationale: Phase 0 is observation-first; the Brain is intentionally stateless across turns; trigger-driven coverage in CoQ is non-trivial because mutation `Level` flows through `SyncMutationLevelsEvent` (`decompiled/XRL.World.Parts/Mutations.cs:115-119`), equip is split across `EquippedEvent` (item) and `EquipperEquippedEvent` (equipper), and cooldowns tick segment-wise inside `ActionManager`. Full dump on the game thread sidesteps all coverage gaps.
- **Provisional clause (recorded for posterity):** "Adopt full per-turn dump for Phase 0-D. Migrate to a better cadence (hybrid volatile-vs-stable / on-demand pull / payload compression / WebSocket-side filtering) if measured constraints — Player.log size, Brain prompt cache hit rate, WebSocket bandwidth, or Phase 0-H `snapshot_hash` design — justify it." See "Open hazards / future revisit" at the end of this plan for the explicit re-open trigger list.

**Why no diffing in 0-D:**
- Mod-side delta would require persisting last-turn caps in the mod, comparing field-by-field, and restoring after a save/load → too much state for an observation-first phase.
- Brain-side diff is fine in principle, but 0-D's runtime contract is "Brain receives full observation per decision point, statelessly". Diffing belongs to the Phase 0-H `TurnSnapshot DTO + snapshot_hash` design (`docs/architecture-v5.md:2801-2805`).

**Scope boundaries:**
- **In scope (per Q1 brainstorm = scope B, confirmed 2026-04-25):**
  - `mutations`: `MutationList` (passive + active). For each: `class`, `display_name`, `base_level`, `level`, `ui_display_level` (`m.GetUIDisplayLevel()`, the actual UI-displayed value — `decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:209-212` defaults to `Level` but subclasses override it), `can_level` (`m.CanLevel()` method call), `type`, `is_active` (i.e. `Level > 0`). Both passive (currently 0-level) and active emitted; `ActiveMutationList` is a derived view (`Mutations.cs:100`) and not emitted separately.
  - `abilities`: `AbilityByGuid.Values`. For each: `guid`, `command`, `display_name`, `class`, `enabled`, `toggleable`, `toggle_state`, `active_toggle`, `always_allow_toggle_off`, `visible` (`ActivatedAbilityEntry.Visible`, `decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:195`), `cooldown_segments_raw` (`e.CommandCooldown?.Segments` — true storage), `cooldown_segments_effective` (`e.Cooldown` getter — toggle-aware, returns 0 when `AlwaysAllowToggleOff && ToggleState && Toggleable`), `cooldown_rounds` (`ceil(cooldown_segments_effective / 10)`), `is_usable`.
  - `effects`: iterate `player.Effects` (`Rack<Effect>`, `IEnumerable<Effect>` per `decompiled/XRL.Collections/Rack.cs:10`). For each: `class`, `display_name`, `display_name_stripped`, `duration_raw`, `duration_kind`. `duration_kind` = `"finite"` if `0 < Duration < 9999`, `"indefinite"` if `Duration == 9999` (`Effect.DURATION_INDEFINITE`, `decompiled/XRL.World/Effect.cs:92`), `"unknown"` otherwise (e.g. negative or post-expiration).
  - `equipment`: `body.GetEquippedParts()` (`decompiled/XRL.World.Parts/Body.cs:883-897`). For each part with `Equipped != null`: `part_id` (BodyPart.ID **only when `p.HasID()` returns true** — `BodyPart.cs:438-440`; the `ID` getter lazy-allocates by incrementing `The.Game.BodyPartIDSequence` when `_ID == 0` per `BodyPart.cs:365-381`, which would mutate game state during observation. Emit `null` when no ID is yet assigned), `part_name` (BodyPart.Name), `part_type` (BodyPart.Type), `ordinal_name` (`GetOrdinalName().Strip()` — `BodyPart.cs:5706-5727` wraps the result in `{{<color>|...}}` markup that must be stripped for plain-text consumption), `equipped: {name, blueprint}`.
  - Schema versioning + error sentinel.
- **Out of scope for 0-D (deferred):**
  - Inventory full dump (carried items not equipped). Phase 0-? — the equipment block reports what is equipped and on which slot, but does NOT enumerate `player.Inventory.Objects`.
  - HP / position / attributes (already in `[state]`).
  - Hunger / thirst / movement points / encumbrance (Phase 0-D scope was explicitly capped at scope B in the brainstorm).
  - `MutationModifierTracker` enumeration (`Mutations.cs:88`) — modifier lineage is internal; Brain consumes the resolved `Level` only.
  - Trigger-driven delta emission, hybrid cadence, payload compression — all deferred per the provisional clause.
  - C# unit tests for `AppendCaps*` helpers (deferred to Phase 2a per ADR 0004's substituted manual JSON-validity gate).

**Open hazards inherited from prior phases (do not address here):**
- Mid-session mod reload — closed by ADR 0003 as a design-decision; streaming runtime fixes mods at launch. `_pendingSnapshot` reset to `null` on a fresh process is unchanged from 0-C.
- Render-thread exception spam dedup — 0-B + 0-C accumulated 0 errors over 95 + 110 turns. The new `[caps]` emission is one additional `MetricsManager.LogInfo` call per turn with the same `try/catch` shell; the dedup posture is unchanged ("fix when it shows up").
- Multi-mod coexistence under Phase 0-C framing — untested. 0-D acceptance run uses single-mod load (LLMOfQud only) like 0-C.

**Tech Stack:**
- Same as Phase 0-A / 0-B / 0-C. CoQ Roslyn-compiles `mod/LLMOfQud/*.cs` at game launch (`decompiled/XRL/ModInfo.cs:478, 757-823`). Manual in-game verification against `Player.log` is the acceptance gate.
- New `using` directives needed in `mod/LLMOfQud/SnapshotState.cs`:
  - `using XRL.World.Anatomy;` for `BodyPart`.
  - `using XRL.World.Parts.Mutation;` for `BaseMutation`.
  - `XRL.World.Parts` is already imported (used for `Mutations`, `Body`, `ActivatedAbilities`, `Render`).
- Environment paths (verified, unchanged from 0-C):
  - `$MODS_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods`
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach:**
- Manual in-game verification (Phase 0-A / 0-B / 0-C precedent). Game-as-harness automated smoke is deferred to Phase 2a per `agents/references/testing-strategy.md`.
- C# unit tests for `AppendCaps*` helpers are deferred to Phase 2a per **ADR 0004**. Substitute: a manual JSON-validity check on the **latest single** `[LLMOfQud][caps]` line, parsed by `python3 -c "import sys, json; json.loads(sys.stdin.read())"`. This mirrors the Phase 0-C `[state]` gate. Per ADR 0004 re-open trigger 4, a single attributable JSON-invalidity occurrence at any phase forces the C# test infrastructure to be added.
- Acceptance counts: `[screen] BEGIN == [screen] END == [state] == [caps]` (modulo turns where the game thread JSON-build threw and emitted a sentinel — those still count). ERROR=0 at the screen path; isolated `[caps]` errors do not fail the gate by themselves but are inspected.
- Spot-check shape: Warden initial turn must have non-empty `mutations`, `equipment` arrays and a non-null `abilities` array. `effects` may legitimately be empty on the very first turn.
- Spot-check semantic: cooldown change. After ability use, the same ability's `cooldown_segments_raw` must drop monotonically across consecutive turns (a turn where `cooldown_segments_raw > 0` exists confirms the codepath wires through). Tested empirically only if a Warden ability is used during the run; otherwise documented as "not exercised this run" in the exit memo.

**Reference:**
- `docs/architecture-v5.md` (v5.9): `:1787-1790` (game-queue routing rule), `:2801` (Phase 0-D scope), `:443-468` (Phase 2 `check_status` tool surface that consumes this), `:1718` (`BuildProfileCapture.cs` placeholder for the eventual file split, NOT introduced in 0-D).
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` — render-callback emit pattern this plan extends to 3 lines/turn.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate, applied here to the new `[caps]` line.
- `docs/memo/phase-0-c-exit-2026-04-25.md:111-137` — exit memo's "Phase 0-C-specific implementation rules (still in force)" + "Feed-forward for Phase 0-D" sections this plan resolves.
- CoQ APIs (verified 2026-04-25; re-confirm before each citation per root AGENTS.md §Imperatives item 1):
  - **Mutations**: `decompiled/XRL.World.Parts/Mutations.cs:86` (`MutationList: List<BaseMutation>`), `:100` (`ActiveMutationList = MutationList.Where(m => m.Level > 0).ToList()`).
  - **BaseMutation**: `decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:117-130` (`Level` getter calls `CalcLevel()`, setter calls `SyncMutationLevelsEvent.Send`). `:209-212` (`GetUIDisplayLevel()` — virtual, default returns `Level`, overridable per subclass; CoQ's character-sheet UI consumes this at `decompiled/Qud.UI/CharacterMutationLine.cs:87`). `:732-` (`CanLevel()` — method, NOT a property). `BaseMutation` exposes `Name` (mutation entry name), `DisplayName` (display string), `BaseLevel` (raw stat), `Level` (resolved), `Type` (category), `IsDefect()`.
  - **ActivatedAbilities**: `decompiled/XRL.World.Parts/ActivatedAbilities.cs:181` (`AbilityByGuid: Dictionary<Guid, ActivatedAbilityEntry>`), `:184` (`Cooldowns: List<CommandCooldown>`). Iterate `AbilityByGuid.Values` for the ability list — Cooldowns is a parallel reverse-index used by `AddCooldown` / `RemoveCooldown` and is NOT the source of truth for "which abilities does the player have".
  - **ActivatedAbilityEntry**: `decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:259-284` (`Cooldown` getter — returns 0 for toggleable abilities with `AlwaysAllowToggleOff && ToggleState && Toggleable`, otherwise `CommandCooldown.Segments`), `:286` (`CooldownRounds = (int)Math.Ceiling((double)Cooldown / 10.0)`), `:295-308` (`IsUsable` — checks `Enabled && (Cooldown == 0 || (ToggleState && ActiveToggle))`). Public string fields: `Command`, `DisplayName`, `Class`. Public bool fields: `Enabled`, `Toggleable`, `ToggleState`, `ActiveToggle`, `AlwaysAllowToggleOff`. Public Guid: `ID`. Public `CommandCooldown` field: `CommandCooldown`.
  - **CommandCooldown**: `decompiled/XRL.World/CommandCooldown.cs:11-13` (`public string Command; public int Segments;`).
  - **Effect**: `decompiled/XRL.World/Effect.cs:92` (`DURATION_INDEFINITE = 9999`), `:106-109` (`Duration` is `[NonSerialized] public int`), `:101-104` (`DisplayName` is `[NonSerialized] public string`), `:153` (`DisplayNameStripped => DisplayName.Strip()`), `:644-648` (standard countdown decrements `Duration` in `BeforeBeginTakeActionEvent` only when `Object?.Brain != null && Duration > 0 && Duration != 9999`).
  - **GameObject Effects**: `decompiled/XRL.World/GameObject.cs:569` (`Effects => _Effects ?? (_Effects = new EffectRack())`), `decompiled/XRL.World/EffectRack.cs:5` (`EffectRack : Rack<Effect>`), `decompiled/XRL.Collections/Rack.cs:10` (`Rack<T> : IEnumerable<T>`).
  - **Body / BodyPart**: `decompiled/XRL.World.Parts/Body.cs:883-897` (`GetEquippedParts()` returns parts where `P.Equipped != null`). `decompiled/XRL.World.Anatomy/BodyPart.cs:345-347` (`Equipped => _Equipped`), `:5706-5727` (`GetOrdinalName()` returns part name with ordinal suffix when multiple same-typed parts exist).
  - **MetricsManager.LogInfo** (unchanged): `decompiled/MetricsManager.cs:407-409` — `LogInfo(msg)` → `Debug.Log("INFO - " + Message)` → `Player.log`.

---

## Prerequisites (one-time per session)

Before starting Task 1, confirm:

1. Phase 0-C is landed on `main` (commit `1afbf01 feat(mod): Phase 0-C internal-API observation` or a successor). Verify `mod/LLMOfQud/SnapshotState.cs` has the existing `BuildStateJson` + `AppendJsonString` + `AppendEntity` helpers, and `mod/LLMOfQud/LLMOfQudSystem.cs` has the `_pendingSnapshot` ref slot + the two-LogInfo-call `AfterRenderCallback`.
2. The symlink `$MODS_DIR/LLMOfQud` still resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling, re-create per Phase 0-A Task 1.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. A clean save slot for the acceptance run (Task 6). Reusing the Phase 0-C Warden keeps the spot-check character familiar, but any playable build works — 0-D does not constrain the build.
5. **Disable any coexisting user mod for the acceptance run.** Phase 0-C's 110-turn run was performed with `QudJP` disabled (single-mod load order: `1: LLMOfQud`). Re-verify the in-game Mods list reflects single-mod load before starting Task 6.

---

## File Structure

Two C# files are touched in this plan:

- Modify: `mod/LLMOfQud/SnapshotState.cs`
  - Add `using XRL.World.Anatomy;` and `using XRL.World.Parts.Mutation;`.
  - Add `string CapsJson` field to `PendingSnapshot`.
  - Add `BuildCapsJson(int turn, GameObject player)` static method.
  - Add `AppendMutations(StringBuilder, GameObject)`, `AppendAbilities(StringBuilder, GameObject)`, `AppendEffects(StringBuilder, GameObject)`, `AppendEquipment(StringBuilder, GameObject)` helpers.
  - Reuse the existing `AppendJsonString` for all string escapes.
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Extend `HandleEvent(BeginTakeActionEvent)`: build `capsJson` on the game thread in a separate `try/catch`, populate `PendingSnapshot.CapsJson`. The state JSON build path is unchanged.
  - Extend `AfterRenderCallback`: emit the third `MetricsManager.LogInfo("[LLMOfQud][caps] " + capsJson)` after the existing `[state]` emission. The new call sits in its own `try` scope so a `[caps]` emission failure does not blank `[screen]` or `[state]`.

No other source file changes. No manifest edits. No symlink changes. No new dependencies. The Roslyn compile set stays at 3 files.

External (created during execution):
- `docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-c-exit-2026-04-25.md`'s shape.

---

## Task 1: End-to-end `[caps]` line stub

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs:1-7` (using directives), append new method at end of `SnapshotState` static class
- Modify: `mod/LLMOfQud/SnapshotState.cs:10-21` (`PendingSnapshot` class)
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs:60-108` (`HandleEvent`)
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs:175-223` (`AfterRenderCallback`)

**Why this task exists:** Lock the threading + emission contract before adding any field-extraction logic. By the end of Task 1 a Warden in-game produces three lines per turn — `[screen]`, `[state]`, `[caps] {"turn":N,"schema":"runtime_caps.v1"}` — with the same correlation contract Phase 0-C established. Field extraction (mutations / abilities / effects / equipment) is added field-at-a-time in Tasks 2-5 against this stable scaffold. Spec rule per `docs/memo/phase-0-c-exit-2026-04-25.md:117`: any new field threads through `PendingSnapshot`, never as a parallel slot.

- [ ] **Step 1: Extend `PendingSnapshot` with `CapsJson`.**

In `mod/LLMOfQud/SnapshotState.cs:10-21`, replace the existing `PendingSnapshot` class with:

```csharp
internal sealed class PendingSnapshot
{
    public int Turn;
    public string StateJson;
    // Captured on the game thread alongside StateJson. AfterRenderCallback
    // MUST consume this rather than re-reading Options.UseTiles, which can
    // flip between turns and would otherwise produce inconsistent
    // mode= (in [screen]) vs display_mode= (in [state]) framing for the
    // same turn. See ADR 0002 + game-thread routing rule
    // docs/architecture-v5.md:1787-1790.
    public string DisplayMode;
    // Phase 0-D: RuntimeCapabilityProfile JSON for this turn. Built on the
    // game thread inside HandleEvent so all CoQ API reads stay on the
    // game queue (docs/architecture-v5.md:1787-1790). Render thread emits
    // verbatim. Per docs/memo/phase-0-c-exit-2026-04-25.md:117, future
    // observation fields thread through this object, never as parallel
    // Interlocked.Exchange slots.
    public string CapsJson;
}
```

- [ ] **Step 2: Add the `BuildCapsJson` stub.**

In `mod/LLMOfQud/SnapshotState.cs`, append at the end of the `SnapshotState` static class (just before its closing `}`):

```csharp
        // Entry point used by HandleEvent to build the caps line payload
        // (the value of the [LLMOfQud][caps] line; caller adds the prefix).
        // Phase 0-D Task 1: stub returning {"turn":N,"schema":"runtime_caps.v1"}.
        // Subsequent tasks fill in mutations / abilities / effects / equipment.
        // Schema bumps (v2+) require an ADR.
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(2048);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");
            sb.Append('}');
            return sb.ToString();
        }
```

The `GameObject player` parameter is unused in the stub but locked into the signature so Tasks 2-5 do not need to retouch the caller. If the C# compiler warns about unused parameter, suppress with `_ = player;` at the top of the body — but in normal Roslyn-CSharp builds `CS0219` does not fire on unused method parameters, so no suppression should be needed.

- [ ] **Step 3: Add the using directives required for Tasks 2-5.**

In `mod/LLMOfQud/SnapshotState.cs:1-7`, replace the existing using block with:

```csharp
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using XRL;
using XRL.UI;
using XRL.World;
using XRL.World.Anatomy;
using XRL.World.Parts;
using XRL.World.Parts.Mutation;
```

`System.Collections.Generic` is needed for `Dictionary<,>` enumeration in the abilities helper (Task 3). `XRL.World.Anatomy` is for `BodyPart`. `XRL.World.Parts.Mutation` is for `BaseMutation`. The other directives are unchanged from 0-C.

- [ ] **Step 4: Wire `BuildCapsJson` into `HandleEvent`.**

In `mod/LLMOfQud/LLMOfQudSystem.cs:74-99`, replace the state-JSON build + `PendingSnapshot` construct block with:

```csharp
            string stateJson;
            string displayMode;
            try
            {
                stateJson = SnapshotState.BuildStateJson(_beginTurnCount, out displayMode);
            }
            catch (Exception ex)
            {
                // Mirror the AfterRenderCallback exception posture: never let
                // observation kill the mod. Emit a sentinel JSON so the parser
                // sees a valid line; the broader [state] line will still flow
                // for the next turn.
                stateJson = "{\"turn\":" + _beginTurnCount.ToString() +
                    ",\"error\":\"" + ex.GetType().Name + "\"}";
                displayMode = Options.UseTiles ? "tile" : "ascii";
                MetricsManager.LogInfo(
                    "[LLMOfQud][state] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-D: build caps JSON on the game thread in a separate
            // try/catch. Failure here MUST NOT kill the [state] emission;
            // produce a valid-JSON sentinel so downstream parsers always
            // see a parseable [caps] line for this turn. Use the existing
            // SnapshotState.AppendJsonString helper so control characters
            // (newline / tab / U+0000-U+001F) in ex.Message are escaped
            // RFC-8259 correctly — a coarse Replace chain would emit
            // invalid JSON exactly when a parser is most likely to break.
            string capsJson;
            try
            {
                capsJson = SnapshotState.BuildCapsJson(_beginTurnCount, The.Player);
            }
            catch (Exception ex)
            {
                StringBuilder errSb = new StringBuilder(256);
                errSb.Append("{\"turn\":").Append(_beginTurnCount.ToString())
                    .Append(",\"schema\":\"runtime_caps.v1\"")
                    .Append(",\"error\":{\"type\":");
                SnapshotState.AppendJsonString(errSb, ex.GetType().Name);
                errSb.Append(",\"message\":");
                SnapshotState.AppendJsonString(errSb, ex.Message ?? "");
                errSb.Append("}}");
                capsJson = errSb.ToString();
                MetricsManager.LogInfo(
                    "[LLMOfQud][caps] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            PendingSnapshot pending = new PendingSnapshot
            {
                Turn = _beginTurnCount,
                StateJson = stateJson,
                DisplayMode = displayMode,
                CapsJson = capsJson,
            };
            Interlocked.Exchange(ref _pendingSnapshot, pending);
```

`SnapshotState.AppendJsonString` is `internal static` in the same assembly (`mod/LLMOfQud/SnapshotState.cs:30-66`), so it is callable directly from `LLMOfQudSystem`. Using the same RFC-8259 escape table as the happy path means the sentinel JSON is provably parseable for any exception message — including ones with embedded newlines, tabs, U+0000–U+001F, or U+2028/U+2029 — and Phase 0-D acceptance step 6 (`json.loads` of the latest `[caps]` line) cannot become a false negative because the catch path emitted unescaped control characters.

- [ ] **Step 5: Extend `AfterRenderCallback` to emit `[caps]`.**

In `mod/LLMOfQud/LLMOfQudSystem.cs:175-223`, replace the existing method with:

```csharp
        // Fires on the render thread after Zone.Render but before DrawBuffer.
        // No-op unless HandleEvent published a PendingSnapshot. Interlocked.Exchange
        // atomically captures-and-clears the slot so concurrent BeginTakeActionEvent
        // fires cannot double-log the same snapshot. Emits THREE LogInfo calls per
        // snapshot — one [screen] block (with display_mode + ascii_sources metadata),
        // one [state] structured line, one [caps] structured line — all sharing
        // turn=N as the parser-side correlation key. The parser must NOT assume
        // adjacency; LogInfo lines from other game subsystems can interleave.
        // decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
        // decompiled/XRL.UI/Options.cs:574-576 (Options.UseTiles)
        private static void AfterRenderCallback(XRLCore core, ScreenBuffer buf)
        {
            PendingSnapshot pending = Interlocked.Exchange<PendingSnapshot>(ref _pendingSnapshot, null);
            if (pending == null)
            {
                return;
            }
            int turn = pending.Turn;
            string stateJson = pending.StateJson;
            string capsJson = pending.CapsJson;
            string displayMode = pending.DisplayMode;
            try
            {
                int w = buf != null ? buf.Width : 0;
                int h = buf != null ? buf.Height : 0;
                int charCount, backupCount, blankCount;
                string body = SnapshotAscii(buf, out charCount, out backupCount, out blankCount);

                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] BEGIN turn=" + turn +
                    " w=" + w + " h=" + h +
                    " mode=" + displayMode +
                    " src=char:" + charCount + ",backup:" + backupCount + ",blank:" + blankCount +
                    "\n" + body +
                    "[LLMOfQud][screen] END turn=" + turn);

                MetricsManager.LogInfo("[LLMOfQud][state] " + stateJson);
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][screen] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }

            // Phase 0-D: emit [caps] in its own try scope. A [caps] failure
            // here MUST NOT blank [screen]/[state] for this turn (those have
            // already emitted above). The capsJson value was prepared on the
            // game thread; if its build threw, capsJson is already an error
            // sentinel and this block just emits it verbatim.
            try
            {
                MetricsManager.LogInfo("[LLMOfQud][caps] " + capsJson);
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][caps] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }
        }
```

The split into two `try` blocks is intentional: the existing one wraps the `SnapshotAscii` walk + `[screen]` + `[state]` emission as a unit (any exception there means the source buffer was bad and there is nothing useful to log for the turn except the `[screen] ERROR` sentinel); the new `[caps]` block has its own try because the only operation is the prepared-string LogInfo call and the failure mode is essentially "Unity log pipe is broken", which we still log a sentinel for symmetry.

- [ ] **Step 6: Compile probe.**

Restart Caves of Qud (full quit + relaunch — mod assembly is cached for the process). Then:

```bash
grep -E "^\[[^]]+\] (=== LLM OF QUD ===|Compiling [0-9]+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$COQ_SAVE_DIR/build_log.txt" | tail -10
```

Expected: a `Compiling 3 files...` (or `Compiling 1 file...` if CoQ batches differently — the regex tolerates either) followed by `Success :)`. **No `COMPILER ERRORS`.** Note: BSD `grep -E` on macOS does NOT recognise `\d`; the pattern uses `[0-9]+` for portability. If the compile fails, the next run won't load the mod; fix and re-launch before proceeding to Step 7.

- [ ] **Step 7: Smoke run — verify all three lines emit per turn.**

Load any save, take 5 player-turn actions (move 5 steps), then quit. Then:

```bash
LOG="$PLAYER_LOG"
echo "screen BEGIN: $(grep -c 'INFO - \[LLMOfQud\]\[screen\] BEGIN' "$LOG")"
echo "screen END:   $(grep -c '^\[LLMOfQud\]\[screen\] END'   "$LOG")"
echo "state:        $(grep -c 'INFO - \[LLMOfQud\]\[state\]'        "$LOG")"
echo "caps:         $(grep -c 'INFO - \[LLMOfQud\]\[caps\]'         "$LOG")"
echo "ERROR:        $(grep -c '\[LLMOfQud\]\[\(screen\|state\|caps\)\] ERROR' "$LOG")"
```

Expected: all four counts equal, ERROR=0. The exact value should be 5 (or 6 if the game emits one extra render-callback after final move). Counts may differ slightly if CoQ pumps an extra frame between the last move and quit.

- [ ] **Step 8: JSON validity probe.**

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "import sys, json; d = json.loads(sys.stdin.read()); print('OK turn=' + str(d['turn']) + ' schema=' + d['schema'])"
```

Expected: `OK turn=5 schema=runtime_caps.v1` (or whatever turn count Step 7 ended at). If `python3` raises `json.JSONDecodeError`, the stub line is malformed; fix before proceeding.

- [ ] **Step 9: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "feat(mod): Phase 0-D Task 1 — [caps] line stub end-to-end

PendingSnapshot gains CapsJson field; HandleEvent builds a stub caps JSON
on the game thread; AfterRenderCallback emits a third LogInfo line per
turn. Stub payload is {\"turn\":N,\"schema\":\"runtime_caps.v1\"}.
Field extraction (mutations / abilities / effects / equipment) added in
Tasks 2-5 against this scaffold."
```

---

## Task 2: `AppendMutations` — passive + active mutations with levels

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendMutations` helper, wire into `BuildCapsJson`.

**Why this task exists:** Mutations are the largest stable component of `RuntimeCapabilityProfile`. Emitting `MutationList` (not `ActiveMutationList`) keeps both passive (Level == 0, e.g. preselected but uninvested) and active mutations visible to the Brain. `BaseLevel` and `Level` are emitted separately because `Level` flows through `CalcLevel()` and includes stat / equipment / cooking modifiers (`decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:117-119`). Emitting only `Level` would hide the player's invested point allocation.

- [ ] **Step 1: Add `AppendMutations` to `SnapshotState`.**

In `mod/LLMOfQud/SnapshotState.cs`, append inside the `SnapshotState` static class (above `BuildCapsJson`, below `AppendEntity`):

```csharp
        // Schema:
        //   [
        //     {
        //       "class": "Carapace",                  // BaseMutation type-name
        //       "name": "Carapace",                    // Mutation entry Name
        //       "display_name": "Carapace",            // Stripped display string
        //       "base_level": 4,                       // Player-invested level
        //       "level": 4,                            // Resolved level (CalcLevel)
        //       "ui_display_level": 4,                 // m.GetUIDisplayLevel():
        //                                              //   the actual UI-displayed
        //                                              //   value. Default returns
        //                                              //   Level, but specific
        //                                              //   mutation subclasses
        //                                              //   override it (CoQ's
        //                                              //   own character-sheet UI
        //                                              //   consumes this method).
        //       "type": "Physical",                    // Mutation category
        //       "can_level": true,                     // Whether further leveling
        //                                              //   is possible
        //       "is_active": true                      // Level > 0 (matches
        //                                              //   ActiveMutationList filter)
        //     }
        //   ]
        // decompiled/XRL.World.Parts/Mutations.cs:86 (MutationList)
        // decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:117-130 (Level/BaseLevel)
        internal static void AppendMutations(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            Mutations mutPart = player?.GetPart<Mutations>();
            List<BaseMutation> list = mutPart?.MutationList;
            if (list != null && list.Count > 0)
            {
                int i = 0;
                foreach (BaseMutation m in list)
                {
                    if (m == null) continue;
                    if (i > 0) sb.Append(',');
                    i++;

                    string className = m.GetType().Name;
                    string name = m.Name ?? "";
                    string displayName = (m.DisplayName ?? m.Name ?? "").Strip() ?? "";
                    int baseLevel = m.BaseLevel;
                    int level = m.Level;
                    int uiDisplayLevel = m.GetUIDisplayLevel(); // base default is Level; subclasses override
                    string type = m.Type ?? "";
                    bool canLevel = m.CanLevel();
                    bool isActive = level > 0;

                    sb.Append("{\"class\":");
                    AppendJsonString(sb, className);
                    sb.Append(",\"name\":");
                    AppendJsonString(sb, name);
                    sb.Append(",\"display_name\":");
                    AppendJsonString(sb, displayName);
                    sb.Append(",\"base_level\":").Append(baseLevel.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"level\":").Append(level.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"ui_display_level\":").Append(uiDisplayLevel.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"type\":");
                    AppendJsonString(sb, type);
                    sb.Append(",\"can_level\":").Append(canLevel ? "true" : "false");
                    sb.Append(",\"is_active\":").Append(isActive ? "true" : "false");
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }
```

`m.DisplayName` is a string property on `BaseMutation` derived from `GetDisplayName(WithAnnotations: true)` (`decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:175-195`). `.Strip()` is the existing CoQ extension that removes ANSI color tags (used in `decompiled/XRL.World/GameObject.cs:766` for `ShortDisplayNameStripped`). The fallback to `m.Name` covers mutations whose display name resolves to empty before localization.

**`ui_display_level`** is the value `m.GetUIDisplayLevel()` returns (`decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:209-212`). The base implementation simply returns `Level`, but specific mutation subclasses can override it; CoQ's character-sheet UI consumes this exact method (`decompiled/Qud.UI/CharacterMutationLine.cs:87`). Emitting it directly avoids locking a placeholder into the v1 schema.

- [ ] **Step 2: Wire into `BuildCapsJson`.**

Replace the stub `BuildCapsJson` body (added in Task 1 Step 2) with:

```csharp
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(4096);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");

            sb.Append(",\"mutations\":");
            AppendMutations(sb, player);

            sb.Append('}');
            return sb.ToString();
        }
```

Tasks 3-5 will add `,\"abilities\":` / `,\"effects\":` / `,\"equipment\":` blocks before the closing `'}'`. Field order is locked: `turn`, `schema`, `mutations`, `abilities`, `effects`, `equipment`. Reordering requires an ADR.

- [ ] **Step 3: Compile + smoke probe.**

Restart Caves of Qud, load a Warden save (Warden has 4 preselected mutations: Carapace, Heightened Hearing, Quills, Mental Mirror), take 1 step, quit.

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$PLAYER_LOG" | tail -1 \
  | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "import sys, json; d = json.loads(sys.stdin.read()); print('mutations=' + str(len(d['mutations'])) + ' first=' + (d['mutations'][0]['display_name'] if d['mutations'] else '<empty>'))"
```

Expected for Warden: `mutations=4 first=<one of the 4 mutation display names>`. If `mutations=0` on Warden, `MutationList` is null at this turn (which would indicate a `GetPart<Mutations>()` failure) — debug by adding a transient `MetricsManager.LogInfo("[LLMOfQud][debug] mutpart=" + (mutPart != null))` line, then remove before commit.

- [ ] **Step 4: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-D Task 2 — AppendMutations (passive + active)

Adds MutationList enumeration to BuildCapsJson. Each entry carries
class, name, display_name, base_level, level, ui_display_level (via
m.GetUIDisplayLevel() — overridable per subclass), type, can_level
(via m.CanLevel() method, NOT a property), is_active. Emits both
passive (Level==0) and active mutations; consumers filter via
is_active or Level > 0."
```

---

## Task 3: `AppendAbilities` — activated abilities with cooldown rollup + raw + `is_usable`

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendAbilities` helper, wire into `BuildCapsJson`.

**Why this task exists:** Abilities are the most semantically dense part of caps because the same numeric "cooldown" can mean three different things in CoQ:
1. **`CommandCooldown.Segments`** — true 10-segments-per-round storage (`decompiled/XRL.World/CommandCooldown.cs:13`). This is the value `TickAbilityCooldowns()` decrements directly. Emitted as `cooldown_segments_raw`.
2. **`ActivatedAbilityEntry.Cooldown`** — getter returns `Segments` in the normal case but returns `0` when ALL of `AlwaysAllowToggleOff && ToggleState && Toggleable` hold (i.e. the toggle is currently ON for an ability whose design lets it stay on indefinitely; `decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:259-267`). Emitted as `cooldown_segments_effective` — this is the toggle-aware "should the UI show a cooldown?" interpretation.
3. **`ActivatedAbilityEntry.CooldownRounds`** — `ceil(Cooldown / 10)`, the value the in-game UI shows (`:286`).

Plus `IsUsable` rolls up Enabled + cooldown + toggle state (`:295-308`). Brain consumers need all three forms because emitting only one would either mislead the LLM (rollup hides toggle state), let `cooldown_segments_effective == 0` masquerade as "ready to use" for an active toggle (the underlying segment count for the ability's cost-after-untoggle is invisible to the consumer), or make Phase 0-H `snapshot_hash` design harder (raw without rollup forces the hasher to re-derive `is_usable`). Codex 2026-04-25 advisory pushback: emitting `cooldown_segments` as a single field would be a "schema lie" because it claims to be raw but inherits the getter's toggle special-case.

`Visible` (`ActivatedAbilityEntry.Visible`, `:195`) is emitted separately because UI-visibility is decoupled from enabled / usability — some abilities are present and usable but suppressed from the in-game ability menu (e.g. cybernetic-implanted abilities under specific conditions). Brain consumers need both axes.

- [ ] **Step 1: Add `AppendAbilities` to `SnapshotState`.**

Append inside the `SnapshotState` static class (below `AppendMutations`):

```csharp
        // Schema:
        //   [
        //     {
        //       "guid": "5e4f3...e",                  // ActivatedAbilityEntry.ID
        //       "command": "CommandFireMissileWeapon",
        //       "display_name": "Fire Missile Weapon",
        //       "class": "Carapace",                   // ActivatedAbilityEntry.Class
        //       "enabled": true,
        //       "toggleable": false,
        //       "toggle_state": false,
        //       "active_toggle": false,
        //       "always_allow_toggle_off": false,
        //       "visible": true,                       // ActivatedAbilityEntry.Visible
        //                                              //   (UI surfacing, separate
        //                                              //   from enabled / usability)
        //       "cooldown_segments_raw": 0,            // CommandCooldown.Segments
        //                                              //   (true storage; bypasses
        //                                              //   the toggle special-case
        //                                              //   in the Cooldown getter)
        //       "cooldown_segments_effective": 0,      // ActivatedAbilityEntry.Cooldown
        //                                              //   getter: returns Segments
        //                                              //   in the normal case;
        //                                              //   returns 0 ONLY when
        //                                              //   AlwaysAllowToggleOff &&
        //                                              //   ToggleState &&
        //                                              //   Toggleable (toggle is
        //                                              //   currently ON for an
        //                                              //   indefinitely-on ability)
        //       "cooldown_rounds": 0,                  // ceil(cooldown_segments_effective/10)
        //                                              //   matches the in-game UI
        //                                              //   "rounds remaining" value
        //       "is_usable": true                      // Enabled && (cooldown_effective==0 ||
        //                                              //   (toggle_state && active_toggle))
        //     }
        //   ]
        // decompiled/XRL.World.Parts/ActivatedAbilities.cs:181 (AbilityByGuid)
        // decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:195 (Visible)
        // decompiled/XRL.World.Parts/ActivatedAbilityEntry.cs:259-308 (Cooldown/CooldownRounds/IsUsable)
        // decompiled/XRL.World/CommandCooldown.cs:11-13 (Command/Segments)
        internal static void AppendAbilities(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            ActivatedAbilities aaPart = player?.GetPart<ActivatedAbilities>();
            Dictionary<System.Guid, ActivatedAbilityEntry> map = aaPart?.AbilityByGuid;
            if (map != null && map.Count > 0)
            {
                int i = 0;
                foreach (KeyValuePair<System.Guid, ActivatedAbilityEntry> kv in map)
                {
                    ActivatedAbilityEntry e = kv.Value;
                    if (e == null) continue;
                    if (i > 0) sb.Append(',');
                    i++;

                    string guid = kv.Key.ToString();
                    string command = e.Command ?? "";
                    string displayName = (e.DisplayName ?? e.Command ?? "").Strip() ?? "";
                    string className = e.Class ?? "";
                    bool enabled = e.Enabled;
                    bool toggleable = e.Toggleable;
                    bool toggleState = e.ToggleState;
                    bool activeToggle = e.ActiveToggle;
                    bool alwaysAllowToggleOff = e.AlwaysAllowToggleOff;
                    bool visible = e.Visible;
                    int cooldownRaw = (e.CommandCooldown != null) ? e.CommandCooldown.Segments : 0;
                    int cooldownEffective = e.Cooldown; // getter returns 0 for AlwaysAllowToggleOff && ToggleState && Toggleable
                    int cooldownRounds = e.CooldownRounds;
                    bool isUsable = e.IsUsable;

                    sb.Append("{\"guid\":");
                    AppendJsonString(sb, guid);
                    sb.Append(",\"command\":");
                    AppendJsonString(sb, command);
                    sb.Append(",\"display_name\":");
                    AppendJsonString(sb, displayName);
                    sb.Append(",\"class\":");
                    AppendJsonString(sb, className);
                    sb.Append(",\"enabled\":").Append(enabled ? "true" : "false");
                    sb.Append(",\"toggleable\":").Append(toggleable ? "true" : "false");
                    sb.Append(",\"toggle_state\":").Append(toggleState ? "true" : "false");
                    sb.Append(",\"active_toggle\":").Append(activeToggle ? "true" : "false");
                    sb.Append(",\"always_allow_toggle_off\":").Append(alwaysAllowToggleOff ? "true" : "false");
                    sb.Append(",\"visible\":").Append(visible ? "true" : "false");
                    sb.Append(",\"cooldown_segments_raw\":").Append(cooldownRaw.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"cooldown_segments_effective\":").Append(cooldownEffective.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"cooldown_rounds\":").Append(cooldownRounds.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"is_usable\":").Append(isUsable ? "true" : "false");
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }
```

**Why iterate `AbilityByGuid.Values` and not `Cooldowns`:** `Cooldowns` (`ActivatedAbilities.cs:184`) is a `List<CommandCooldown>` reverse-index used by `AddCooldown` / `RemoveCooldown` for fast lookup; it does NOT contain abilities currently at 0 cooldown, so iterating it would miss usable abilities. `AbilityByGuid` is the canonical source for "which abilities does this player have right now".

**Why `kv.Key.ToString()` for the GUID:** `ActivatedAbilityEntry.ID` is `Guid` (the dictionary key); the entry itself does NOT store the GUID redundantly. The default `Guid.ToString()` produces the `D` format (hyphenated 36-char), which is stable and safe for JSON.

- [ ] **Step 2: Wire into `BuildCapsJson`.**

Replace `BuildCapsJson` body (Task 2 version) with:

```csharp
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(8192);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");

            sb.Append(",\"mutations\":");
            AppendMutations(sb, player);

            sb.Append(",\"abilities\":");
            AppendAbilities(sb, player);

            sb.Append('}');
            return sb.ToString();
        }
```

- [ ] **Step 3: Compile + smoke probe (shape).**

Restart CoQ, load Warden, take 1 step, quit.

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$PLAYER_LOG" | tail -1 \
  | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
abilities = d.get('abilities', [])
print('abilities_count=' + str(len(abilities)))
usable = [a['display_name'] for a in abilities if a['is_usable']]
toggleable = [a['display_name'] for a in abilities if a['toggleable']]
visible = [a['display_name'] for a in abilities if a['visible']]
print('usable=' + ','.join(usable))
print('toggleable=' + ','.join(toggleable))
print('visible=' + ','.join(visible))
# Verify the new raw / effective fields are both present and integer-typed.
for a in abilities:
    assert isinstance(a['cooldown_segments_raw'], int)
    assert isinstance(a['cooldown_segments_effective'], int)
    assert isinstance(a['visible'], bool)
print('shape OK')
"
```

Expected for Warden: `abilities_count >= 1` (Warden carries at least one mutation-derived ability). Toggleable abilities present iff the build has any toggle mutations. The exact count varies by save state. Document the observed count in the exit memo.

- [ ] **Step 4: Cooldown decrement probe (semantic).**

The shape probe above does not exercise cooldown semantics. Run a forced-use probe:

1. Reload the same Warden save (clean per-instance turn counter).
2. Use any ability that incurs a non-zero cooldown — for Warden, Heightened Hearing's Detect Presence works (or any active ability the build has). If the Warden build has no usable cooldown ability, document this in the exit memo as "cooldown decrement not exercised this run" and skip to Step 5.
3. After using the ability, take 15+ additional steps (cooldowns count down per round; 15 rounds = 150 segments which exceeds any normal cooldown).
4. Quit and run:

```bash
ABILITY_NAME='Detect Presence'   # or whatever was used
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$PLAYER_LOG" | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
target = '$ABILITY_NAME'
seen = []
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    d = json.loads(line)
    for a in d.get('abilities', []):
        if a['display_name'] == target:
            seen.append((d['turn'], a['cooldown_segments_raw'], a['cooldown_segments_effective'], a['cooldown_rounds'], a['is_usable']))
nonzero = [s for s in seen if s[1] > 0]
if not nonzero:
    print('NOT EXERCISED — ' + target + ' never had a positive cooldown_segments_raw across ' + str(len(seen)) + ' turns')
    sys.exit(0)
# Start the monotonic check from the FIRST positive sample. Anything before
# that is the pre-activation baseline (raw == 0) and the legitimate 0->positive
# transition at activation must NOT count as a 'raw increased' failure.
first_pos_idx = next(i for i, s in enumerate(seen) if s[1] > 0)
prev = None
for turn, raw, eff, rounds, usable in seen[first_pos_idx:]:
    if prev is not None and raw > prev:
        print('FAIL turn=' + str(turn) + ' raw=' + str(raw) + ' increased from ' + str(prev))
        sys.exit(1)
    prev = raw
print('MONOTONIC DESCENT OK across ' + str(len(seen) - first_pos_idx) + ' post-activation samples; first nonzero=' + str(nonzero[0][1]) + ' final=' + str(seen[-1][1]))
"
```

Expected: `MONOTONIC DESCENT OK ...`. If `NOT EXERCISED`, document explicitly in the exit memo and accept. Anything else is a hard gate fail.

- [ ] **Step 5: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-D Task 3 — AppendAbilities

Adds AbilityByGuid enumeration to BuildCapsJson. Each entry carries
guid, command, display_name, class, enabled, toggleable, toggle_state,
active_toggle, always_allow_toggle_off, visible, cooldown_segments_raw,
cooldown_segments_effective, cooldown_rounds, is_usable. Splits raw vs
effective cooldown so toggleable abilities with AlwaysAllowToggleOff
expose both the underlying segment count (raw) and the toggle-aware
UI value (effective) per Codex 2026-04-25 advisory."
```

---

## Task 4: `AppendEffects` — status effects with raw `Duration` + `duration_kind`

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendEffects` helper, wire into `BuildCapsJson`.

**Why this task exists:** `Effect.Duration` does not have a uniform meaning across the effect taxonomy. The CoQ countdown logic decrements `Duration` only when `UseStandardDurationCountdown() == true && Object?.Brain != null && Duration > 0 && Duration != 9999` (`decompiled/XRL.World/Effect.cs:644-648`). Some effects override this and tick in `BeginTakeActionEvent` instead (`Dazed`, `Asleep`, `Healing`). Some tick at `EndTurnEvent` (`Meditating`, `PhasedWhileStuck`). Some update on thaw (`Lovesick` via `UseThawEventToUpdateDuration`). Some carry `Duration == 9999` to signal indefinite. Some carry `Duration <= 0` briefly between `Expired()` firing and the next `CleanEffects()` sweep (`decompiled/XRL.World/GameObject.cs:7717`). Emitting `Duration` raw + a coarse `duration_kind` flag avoids committing the schema to a single interpretation.

The observation point is `BeginTakeActionEvent` on the player's body (game thread). Per `decompiled/XRL.Core/ActionManager.cs:785-789` the dispatch order is `EarlyBeforeBeginTakeActionEvent` → `BeforeBeginTakeActionEvent` → `BeginTakeActionEvent`, and `GameObject.HandleEvent` dispatches parts → effects → registered handlers in turn (`decompiled/XRL.World/GameObject.cs:14015-14076`). So by the time `LLMOfQudSystem.HandleEvent(BeginTakeActionEvent)` fires:
- Effects with `UseStandardDurationCountdown()` have already decremented in `BeforeBeginTakeActionEvent` (`Effect.cs:644-648`).
- Effects that decrement at `BeginTakeActionEvent` (e.g. `Dazed.cs:125-130`, `Asleep.cs:232-259`, `Healing.cs:72-80`) will have decremented inside the same dispatch IF they are registered before our system on the player object's part-and-effect chain — this is the usual case but is dispatch-order-dependent.

Documented invariant for `[caps]`: **post pre-action / Begin handlers** for the player. NOT a universal "post-decrement turns remaining" claim — `EndTurn`-decrementing effects (e.g. `Meditating.cs:93-106`, `PhasedWhileStuck.cs:64-71`) and thaw-decrementing effects (`Lovesick.cs:55-63`) tick later in the cycle, so the snapshot is "pre-decrement" for those subclasses. Phase 0-H `snapshot_hash` design is responsible for resolving this if a global "turns remaining" canonical interpretation is ever needed.

- [ ] **Step 1: Add `AppendEffects` to `SnapshotState`.**

Append inside `SnapshotState` (below `AppendAbilities`):

```csharp
        // Schema:
        //   [
        //     {
        //       "class": "Dazed",
        //       "display_name": "Dazed",
        //       "display_name_stripped": "Dazed",      // .Strip() applied
        //       "duration_raw": 3,                      // Effect.Duration verbatim
        //       "duration_kind": "finite"               // | "indefinite" | "unknown"
        //                                               // finite:     0 < Duration < 9999
        //                                               // indefinite: Duration == 9999
        //                                               //             (DURATION_INDEFINITE)
        //                                               // unknown:    Duration <= 0
        //                                               //             (post-Expired,
        //                                               //              pre-CleanEffects)
        //                                               //             OR Duration > 9999
        //     }
        //   ]
        // observed_at: BeginTakeActionEvent on player. POST pre-action / Begin
        //   handlers (UseStandardDurationCountdown effects + Begin-decrementing
        //   effects like Dazed/Asleep/Healing have already ticked). NOT
        //   post-decrement for EndTurn-decrementing effects (Meditating,
        //   PhasedWhileStuck) or thaw-update effects (Lovesick) — see plan
        //   "Why this task exists" body for the full ordering note.
        // decompiled/XRL.World/Effect.cs:92 (DURATION_INDEFINITE = 9999)
        // decompiled/XRL.World/Effect.cs:101-109 (Duration / DisplayName fields)
        // decompiled/XRL.World/Effect.cs:153 (DisplayNameStripped)
        // decompiled/XRL.World/Effect.cs:644-648 (standard BeforeBegin decrement)
        // decompiled/XRL.World/EffectRack.cs:5 (EffectRack : Rack<Effect>)
        // decompiled/XRL.Collections/Rack.cs:10 (Rack<T> : IEnumerable<T>)
        internal static void AppendEffects(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            if (player != null)
            {
                int i = 0;
                foreach (Effect e in player.Effects)
                {
                    if (e == null) continue;
                    if (i > 0) sb.Append(',');
                    i++;

                    string className = e.GetType().Name;
                    string displayName = e.DisplayName ?? "";
                    string displayNameStripped = e.DisplayNameStripped ?? displayName;
                    int duration = e.Duration;
                    string durationKind;
                    if (duration == 9999) durationKind = "indefinite";
                    else if (duration > 0 && duration < 9999) durationKind = "finite";
                    else durationKind = "unknown";

                    sb.Append("{\"class\":");
                    AppendJsonString(sb, className);
                    sb.Append(",\"display_name\":");
                    AppendJsonString(sb, displayName);
                    sb.Append(",\"display_name_stripped\":");
                    AppendJsonString(sb, displayNameStripped);
                    sb.Append(",\"duration_raw\":").Append(duration.ToString(CultureInfo.InvariantCulture));
                    sb.Append(",\"duration_kind\":");
                    AppendJsonString(sb, durationKind);
                    sb.Append('}');
                }
            }
            sb.Append(']');
        }
```

- [ ] **Step 2: Wire into `BuildCapsJson`.**

Replace `BuildCapsJson` body with:

```csharp
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(8192);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");

            sb.Append(",\"mutations\":");
            AppendMutations(sb, player);

            sb.Append(",\"abilities\":");
            AppendAbilities(sb, player);

            sb.Append(",\"effects\":");
            AppendEffects(sb, player);

            sb.Append('}');
            return sb.ToString();
        }
```

- [ ] **Step 3: Compile + smoke probe.**

Restart CoQ, load Warden, take 1 step, quit.

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$PLAYER_LOG" | tail -1 \
  | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
effects = d.get('effects', [])
print('effects_count=' + str(len(effects)))
for e in effects:
    print('  ' + e['class'] + ' duration_raw=' + str(e['duration_raw']) + ' kind=' + e['duration_kind'])
"
```

Expected for Warden first turn: `effects_count` may be 0 (clean save) or include passives like `Mutated` / inherent state effects. If `effects_count > 0`, every entry must have a `duration_kind` of `"finite"`, `"indefinite"`, or `"unknown"` — never anything else. Spot-check: if a `Dazed` or `Asleep` effect exists, `duration_kind` should be `"finite"` and `duration_raw` should be a small positive integer.

**Important caveat:** if `effects_count == 0` for the entire smoke, this gate has not semantically exercised the helper. Either:
- (preferred) restart, drink a `tonic of bouncing` / step into `methane` / find another way to acquire a transient effect (the goal is to see at least one entry materialize and disappear), then re-run the probe;
- (fallback) accept the 0-count smoke and explicitly record "AppendEffects shape verified empty; semantic exercise deferred to Task 6 manual run" in the exit memo.

Do NOT skip both — at least one of the two paths must be on record before Task 5 starts.

- [ ] **Step 4: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-D Task 4 — AppendEffects

Adds player.Effects enumeration (Rack<Effect>) to BuildCapsJson. Each
entry carries class, display_name, display_name_stripped, duration_raw,
duration_kind. duration_kind classifies Duration into finite (0,9999),
indefinite (9999, DURATION_INDEFINITE constant), or unknown (<=0 or
>9999) so consumers don't conflate stale post-Expired effects with
active finite ones."
```

---

## Task 5: `AppendEquipment` — equipped items per `BodyPart`

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendEquipment` helper, wire into `BuildCapsJson`.

**Why this task exists:** Body parts in CoQ are not flat slots. A 2-arm humanoid has two `Hand` parts that need to be distinguished by `GetOrdinalName()` ("Right Hand" / "Left Hand", `decompiled/XRL.World.Anatomy/BodyPart.cs:5706-5727`). Same for arms, feet, etc. Emitting only `BodyPart.Name` would collapse both hands into a single slot identity.

`BodyPart.ID` is a per-part runtime identifier that *can* track which specific part holds which item across turns — but it has a non-obvious side effect: the getter at `BodyPart.cs:365-381` lazy-allocates a fresh ID by incrementing `The.Game.BodyPartIDSequence` whenever `_ID == 0`. Reading it from an observation pass would mutate game state. The plan therefore guards reads with `BodyPart.HasID()` (`:438-440`) and emits `part_id: null` when no ID has yet been allocated; Brain consumers fall back to the `(part_name, ordinal_name)` pair as the stable identity. Codex 2026-04-25 advisory pushback: this guard is mandatory — without it, the act of observing equipment would advance the game's BodyPartIDSequence counter every turn.

`GetOrdinalName()` returns the ordinal-tagged name wrapped in `{{<color>|...}}` markup (`BodyPart.cs:5709-5726`). Plain text consumers must call `.Strip()` on the result — without that, the `ordinal_name` field would carry CoQ-internal color tags that mean nothing to the Brain.

`Body.GetEquippedParts()` returns only parts where `Equipped != null` (`decompiled/XRL.World.Parts/Body.cs:883-897`), so the iteration is naturally filtered to "currently equipped" — non-equipped parts are not emitted. Cybernetics (`BodyPart._Cybernetics`) are out of scope; the equipped-cybernetic path is `BodyPart.Cybernetics`, which is a separate property and not part of the Phase 0-D scope-B definition.

- [ ] **Step 1: Add `AppendEquipment` to `SnapshotState`.**

Append inside `SnapshotState` (below `AppendEffects`):

```csharp
        // Schema:
        //   [
        //     {
        //       "part_id": 12,                           // BodyPart.ID when HasID(),
        //                                                //   else null. Reading the
        //                                                //   ID getter when _ID == 0
        //                                                //   lazily increments
        //                                                //   The.Game.BodyPartIDSequence
        //                                                //   (BodyPart.cs:365-381),
        //                                                //   which is a game-state
        //                                                //   mutation we MUST avoid
        //                                                //   from an observation pass.
        //       "part_name": "Hand",                      // BodyPart.Name
        //       "part_type": "Hand",                      // BodyPart.Type
        //       "ordinal_name": "Right Hand",             // GetOrdinalName().Strip()
        //                                                //   strips the {{<color>|...}}
        //                                                //   markup CoQ wraps the
        //                                                //   ordinal name in.
        //       "equipped": {
        //         "name": "iron long sword",              // ShortDisplayNameStripped
        //         "blueprint": "Iron Long Sword"          // GameObject.Blueprint
        //       }
        //     }
        //   ]
        // decompiled/XRL.World.Parts/Body.cs:883-897 (GetEquippedParts)
        // decompiled/XRL.World.Anatomy/BodyPart.cs:345-347 (Equipped)
        // decompiled/XRL.World.Anatomy/BodyPart.cs:365-381 (ID — lazy-allocates side-effect)
        // decompiled/XRL.World.Anatomy/BodyPart.cs:438-440 (HasID())
        // decompiled/XRL.World.Anatomy/BodyPart.cs:5706-5727 (GetOrdinalName — wraps in markup)
        internal static void AppendEquipment(StringBuilder sb, GameObject player)
        {
            sb.Append('[');
            Body bodyPart = player?.GetPart<Body>();
            if (bodyPart != null)
            {
                List<BodyPart> equipped = bodyPart.GetEquippedParts();
                if (equipped != null && equipped.Count > 0)
                {
                    int i = 0;
                    foreach (BodyPart p in equipped)
                    {
                        if (p == null) continue;
                        GameObject item = p.Equipped;
                        if (item == null) continue; // GetEquippedParts already filters; defensive
                        if (i > 0) sb.Append(',');
                        i++;

                        // p.HasID() guards against the lazy-allocate side-effect
                        // in the ID getter (BodyPart.cs:365-381) which would
                        // increment The.Game.BodyPartIDSequence during what is
                        // supposed to be a pure observation pass.
                        bool partHasId = p.HasID();
                        int partId = partHasId ? p.ID : 0;
                        string partName = p.Name ?? "";
                        string partType = p.Type ?? "";
                        // GetOrdinalName() wraps the result in {{<color>|...}}
                        // markup (BodyPart.cs:5709-5726). Strip for plain text.
                        string ordinalNameRaw = p.GetOrdinalName() ?? partName;
                        string ordinalName = ordinalNameRaw.Strip() ?? partName;
                        string itemName = item.ShortDisplayNameStripped ?? "<unknown>";
                        string blueprint = item.Blueprint ?? "";

                        if (partHasId)
                        {
                            sb.Append("{\"part_id\":").Append(partId.ToString(CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            sb.Append("{\"part_id\":null");
                        }
                        sb.Append(",\"part_name\":");
                        AppendJsonString(sb, partName);
                        sb.Append(",\"part_type\":");
                        AppendJsonString(sb, partType);
                        sb.Append(",\"ordinal_name\":");
                        AppendJsonString(sb, ordinalName);
                        sb.Append(",\"equipped\":{\"name\":");
                        AppendJsonString(sb, itemName);
                        sb.Append(",\"blueprint\":");
                        AppendJsonString(sb, blueprint);
                        sb.Append('}');
                        sb.Append('}');
                    }
                }
            }
            sb.Append(']');
        }
```

- [ ] **Step 2: Wire into `BuildCapsJson` (final shape).**

Replace `BuildCapsJson` body with the final form:

```csharp
        internal static string BuildCapsJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(8192);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"runtime_caps.v1\"");

            sb.Append(",\"mutations\":");
            AppendMutations(sb, player);

            sb.Append(",\"abilities\":");
            AppendAbilities(sb, player);

            sb.Append(",\"effects\":");
            AppendEffects(sb, player);

            sb.Append(",\"equipment\":");
            AppendEquipment(sb, player);

            sb.Append('}');
            return sb.ToString();
        }
```

This is the v1 schema lock. Future fields require a `runtime_caps.v2` bump and an ADR (per ADR 0001's frozen-spec rule extended to runtime contracts).

- [ ] **Step 3: Compile + smoke probe.**

Restart CoQ, load Warden, take 1 step, quit.

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$PLAYER_LOG" | tail -1 \
  | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json, collections
d = json.loads(sys.stdin.read())
eq = d.get('equipment', [])
print('equipment_count=' + str(len(eq)))
for s in eq:
    print('  ' + s['ordinal_name'] + ' (id=' + str(s['part_id']) + ') -> ' + s['equipped']['name'] + ' [' + s['equipped']['blueprint'] + ']')
# Slot identity uniqueness probe (catches lazy-allocate side-effect or HasID-guard miss):
ids = [s['part_id'] for s in eq if s['part_id'] is not None]
dupes = [k for k, v in collections.Counter(ids).items() if v > 1]
assert not dupes, 'duplicate part_ids: ' + str(dupes)
# ordinal_name must be plain text (catches GetOrdinalName markup leaking through):
for s in eq:
    on = s.get('ordinal_name','')
    assert '{{' not in on and '}}' not in on, 'ordinal_name has markup: ' + on
print('slot identity OK')
"
```

Expected for fresh Warden: at least one equipped slot — Warden starts with a Vibro Blade (Right Hand), Leather Cuirass (Body), Leather Boots (Feet), and a salve injector slot in inventory (NOT equipped → not emitted). `slot identity OK` confirms unique non-null part_ids and no markup leakage. Naked builds may produce `equipment_count=0`, which is valid; spot-check the chosen save shows the expected starting kit before failing the gate.

If `part_id` is consistently `null` for all slots, the `HasID()` guard is correct but indicates the body parts have not yet been observed by anything that allocates IDs — this is fine for the equipment block (parts are still uniquely identified by `(part_name, ordinal_name)`) but worth noting in the exit memo.

- [ ] **Step 4: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-D Task 5 — AppendEquipment + schema lock

Adds Body.GetEquippedParts() enumeration to BuildCapsJson. Each entry
carries part_id (HasID-guarded; null for unallocated parts to avoid
the lazy-allocate side-effect on The.Game.BodyPartIDSequence),
part_name, part_type, ordinal_name (Strip()-ed to drop {{<color>|...}}
markup), equipped: {name, blueprint}. Locks schema runtime_caps.v1 =
{turn, schema, mutations, abilities, effects, equipment}. Future field
additions require a v2 bump + ADR."
```

---

## Task 6: Manual acceptance run

**Files:** none (pure verification).

**Why this task exists:** Phase 0-A / 0-B / 0-C precedent. Manual in-game run is the substitute for the deferred C# unit-test infra (ADR 0004). This task locks empirical confidence that `[caps]` produces parseable JSON with the right shape across a long run, mirrors the Phase 0-C 110-turn gate.

- [ ] **Step 1: Single-mod load order.**

Open the in-game Mods menu. Confirm load order shows `1: LLMOfQud` only (any coexisting mods like `QudJP` are Disabled). If a coexisting mod is enabled, disable it and restart CoQ before continuing.

- [ ] **Step 2: Truncate Player.log to isolate the run.**

```bash
: > "$PLAYER_LOG"
```

Now any `[LLMOfQud]` lines in the file came from this run.

- [ ] **Step 3: Play 100+ player turns on Warden.**

Joppa is a fine zone (matches Phase 0-C's spot-check zone). Mix actions: 80% movement, 10% wait, 10% something that spends an ability if available. Avoid level-up / mutation-pick / faction-altering choices to keep the dataset diff-free across runs (those introduce mid-run schema state that masks bugs).

The exact count is `>= 100`. If a player death occurs before 100, restart from the same save and continue; deaths reset the per-run turn counter only at process restart (the in-mod `_beginTurnCount` is per-instance).

- [ ] **Step 4: Quit cleanly.**

Use the in-game Save & Quit. A force-quit may flush the last few log lines; cleanly exiting ensures all `LogInfo` calls reach disk.

- [ ] **Step 5: Counts gate.**

```bash
LOG="$PLAYER_LOG"
SBEGIN=$(grep -c 'INFO - \[LLMOfQud\]\[screen\] BEGIN' "$LOG")
SEND=$(grep -c '^\[LLMOfQud\]\[screen\] END'   "$LOG")
STATE=$(grep -c 'INFO - \[LLMOfQud\]\[state\]'        "$LOG")
CAPS=$(grep -c 'INFO - \[LLMOfQud\]\[caps\]'          "$LOG")
ERR_SCREEN=$(grep -c '\[LLMOfQud\]\[screen\] ERROR' "$LOG")
ERR_STATE=$(grep -c '\[LLMOfQud\]\[state\] ERROR' "$LOG")
ERR_CAPS=$(grep -c '\[LLMOfQud\]\[caps\] ERROR' "$LOG")
echo "BEGIN=$SBEGIN END=$SEND STATE=$STATE CAPS=$CAPS"
echo "ERR_SCREEN=$ERR_SCREEN ERR_STATE=$ERR_STATE ERR_CAPS=$ERR_CAPS"
```

Expected:
- `BEGIN == END == STATE == CAPS` and the value is `>= 100`.
- `ERR_SCREEN == 0`. This is the hard gate (matches 0-B and 0-C posture).
- `ERR_STATE == 0`. Soft gate; non-zero means investigate but does not by itself fail Phase 0-D.
- `ERR_CAPS == 0`. Soft gate; non-zero with finite count means a `BuildCapsJson` exception fired and the sentinel branch took over. Investigate; record in exit memo.

If any count drift > 1 against the others, the [caps] emission lost adjacency contract — investigate before declaring acceptance.

- [ ] **Step 6: Latest-line JSON validity gate (per ADR 0004).**

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
required = {'turn', 'schema', 'mutations', 'abilities', 'effects', 'equipment'}
missing = required - set(d.keys())
assert not missing, 'missing keys: ' + str(missing)
assert d['schema'] == 'runtime_caps.v1', 'unexpected schema: ' + d['schema']
print('OK turn=' + str(d['turn']) + ' mutations=' + str(len(d['mutations'])) + ' abilities=' + str(len(d['abilities'])) + ' effects=' + str(len(d['effects'])) + ' equipment=' + str(len(d['equipment'])))
"
```

Expected: `OK turn=N mutations=M abilities=A effects=E equipment=Q` with non-empty `mutations` and `equipment` for Warden (per Step 3 setup). `effects` may be 0; `abilities` is non-empty for Warden.

If JSON parsing fails, ADR 0004 re-open trigger 4 fires: a single attributable JSON-invalidity instance forces the C# test infrastructure to be added (Phase 2a is moved up). Stop, file an issue, do NOT mask the failure.

- [ ] **Step 6b: Every-line JSON validity gate.**

The latest-line gate (Step 6) is the ADR-0004 substituted minimum, but a transient mid-run malformed `[caps]` line would slip past it. Parse every `[caps]` line and assert each parses cleanly:

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
normal_required = {'turn', 'schema', 'mutations', 'abilities', 'effects', 'equipment'}
sentinel_required = {'turn', 'schema', 'error'}
fail = 0
total = 0
sentinels = 0
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    total += 1
    try:
        d = json.loads(line)
        assert d.get('schema') == 'runtime_caps.v1', 'unexpected schema: ' + str(d.get('schema'))
        # Sentinel branch: when BuildCapsJson threw, the catch path emits
        # {turn, schema, error}. This shape is intentional and must not
        # fail the every-line gate (it is the documented soft-error path).
        if 'error' in d:
            missing = sentinel_required - set(d.keys())
            assert not missing, 'sentinel missing keys at turn ' + str(d.get('turn','?')) + ': ' + str(missing)
            sentinels += 1
            print('SENTINEL turn=' + str(d.get('turn','?')) + ' type=' + d['error'].get('type',''))
        else:
            missing = normal_required - set(d.keys())
            assert not missing, 'normal missing keys at turn ' + str(d.get('turn','?')) + ': ' + str(missing)
    except Exception as exc:
        fail += 1
        print('FAIL line=' + line[:120] + ' err=' + str(exc))
if fail:
    sys.exit(1)
print('OK ' + str(total) + ' lines parsed clean (' + str(sentinels) + ' sentinels)')
"
```

Expected: `OK N lines parsed clean` with N == count from Step 5. Any FAIL or non-trivial SENTINEL count is an ADR 0004 re-open trigger 4 candidate.

- [ ] **Step 6c: Semantic invariants gate.**

Counts and JSON validity can both pass while a helper silently emits always-empty arrays or a slot-identity bug collides keys. Run the semantic invariant probes:

```bash
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json, collections
turns = []
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    d = json.loads(line)
    if 'error' in d: continue  # sentinel turns are out of scope for invariants
    turns.append(d)

# 1. Warden has non-empty mutations + equipment + abilities every non-sentinel turn.
empty_mut = [t['turn'] for t in turns if len(t['mutations']) == 0]
empty_eq  = [t['turn'] for t in turns if len(t['equipment']) == 0]
empty_ab  = [t['turn'] for t in turns if len(t['abilities']) == 0]
assert not empty_mut, 'mutations empty on turns: ' + str(empty_mut[:5])
assert not empty_eq,  'equipment empty on turns: ' + str(empty_eq[:5])
assert not empty_ab,  'abilities empty on turns: ' + str(empty_ab[:5])

# 2. Equipment slot keys are unique per turn (part_id collisions catch a
#    lazy-allocation off-by-one or HasID-guard miss).
for t in turns:
    keys = [s.get('part_id') for s in t['equipment'] if s.get('part_id') is not None]
    dupes = [k for k, v in collections.Counter(keys).items() if v > 1]
    assert not dupes, 'turn ' + str(t['turn']) + ' has duplicate part_ids: ' + str(dupes)

# 3. ordinal_name is plain text (no CoQ {{<color>|...}} markup leaking through).
for t in turns:
    for s in t['equipment']:
        on = s.get('ordinal_name','')
        assert '{{' not in on and '}}' not in on, 'turn ' + str(t['turn']) + ' ordinal_name has markup: ' + on

# 4. mutation ui_display_level is an int (catches future overrides
#    that return a non-numeric type by accident).
for t in turns:
    for m in t['mutations']:
        assert isinstance(m['ui_display_level'], int), 'turn ' + str(t['turn']) + ' mutation ' + m.get('class','?') + ' ui_display_level not int'

print('INVARIANTS OK across ' + str(len(turns)) + ' non-sentinel turns')
"
```

Expected: `INVARIANTS OK across N non-sentinel turns`. Any assertion failure is a hard gate fail — investigate before declaring acceptance.

- [ ] **Step 7: First-turn vs last-turn shape parity.**

```bash
FIRST=$(grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | head -1 | sed 's/^.*\[LLMOfQud\]\[caps\] //')
LAST=$(grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[caps\] //')
python3 -c "
import json
f = json.loads('''$FIRST''')
l = json.loads('''$LAST''')
assert sorted(f.keys()) == sorted(l.keys()), 'top-level keys diverged: ' + str(set(f.keys()) ^ set(l.keys()))
for arr in ('mutations', 'abilities', 'effects', 'equipment'):
    if f[arr] and l[arr]:
        assert sorted(f[arr][0].keys()) == sorted(l[arr][0].keys()), arr + ' shape diverged'
print('shape_parity OK')
"
```

Expected: `shape_parity OK`. Catches any conditional field omission (e.g. an `if (x) sb.Append(\",foo\":...)` that emits the field only when present).

- [ ] **Step 8: Cooldown monotonic-descent spot-check (best-effort).**

If during Step 3 you used an ability that incurs cooldown, grep for the ability across turns and verify `cooldown_segments_raw` decreases monotonically. This is the same probe as Task 3 Step 4 but run against the long Warden acceptance log, so it has many more samples.

```bash
ABILITY='<display_name you used>'
grep 'INFO - \[LLMOfQud\]\[caps\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[caps\] //' \
  | python3 -c "
import sys, json
target = '$ABILITY'
seen = []
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    d = json.loads(line)
    if 'error' in d: continue
    for a in d.get('abilities', []):
        if a['display_name'] == target:
            seen.append((d['turn'], a['cooldown_segments_raw'], a['cooldown_segments_effective']))
nonzero = [s for s in seen if s[1] > 0]
if not nonzero:
    print('NOT EXERCISED — ' + target + ' never had cooldown_segments_raw > 0 across ' + str(len(seen)) + ' turns')
else:
    # Start the monotonic check from the FIRST positive sample (same reason
    # as Task 3 Step 4: pre-activation raw==0 → activation raw>0 is a legit
    # transition and must not count as a 'raw increased' failure).
    first_pos_idx = next(i for i, s in enumerate(seen) if s[1] > 0)
    prev = None
    ok = True
    for turn, raw, eff in seen[first_pos_idx:]:
        if prev is not None and raw > prev:
            print('FAIL turn=' + str(turn) + ' raw=' + str(raw) + ' increased from ' + str(prev))
            ok = False
        prev = raw
    print(('MONOTONIC OK ' if ok else 'FAIL ') + 'first nonzero=' + str(nonzero[0][1]) + ' final=' + str(seen[-1][1]) + ' across ' + str(len(seen) - first_pos_idx) + ' post-activation samples')
"
```

Expected (best-effort): `MONOTONIC OK ...`. If `NOT EXERCISED`, document explicitly in the exit memo per acceptance criterion #9. Anything else is a hard gate fail.

- [ ] **Step 9: Commit (acceptance log artifact).**

The acceptance run produces no source changes. Skip this step; the exit memo (Task 7) records the run outcome.

---

## Task 7: Exit memo

**Files:**
- Create: `docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md` (today's date in `YYYY-MM-DD`).

**Why this task exists:** Phase 0-A / 0-B / 0-C precedent. The exit memo locks the empirical state for downstream phases to reference, records open hazards that survived this phase, and feeds-forward design questions to Phase 0-E.

- [ ] **Step 1: Write the exit memo.**

Create `docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md` with the following structure (mirrors `phase-0-c-exit-2026-04-25.md`):

```markdown
# Phase 0-D Exit — <YYYY-MM-DD>

## Outcome
- Warden N-turn run on Joppa: BEGIN == END == [state] == [caps] == N. ERROR=0 across screen/state/caps.
- Latest [caps] line passes `json.loads` and has all 6 top-level keys.
- First-turn vs last-turn shape parity OK.
- Cooldown spot-check: <result>.

## Acceptance counts
| Frame | Count |
|---|---|
| [screen] BEGIN | N |
| [screen] END | N |
| [state] | N |
| [caps] | N |
| ERROR (any frame) | 0 |

## Verified environment
- CoQ build: `BUILD_2_0_<...>` (re-grep `build_log.txt`)
- Single-mod load order: `1: LLMOfQud` (QudJP disabled or absent)
- macOS path layout: unchanged from Phase 0-C exit memo

## Phase 0-D-specific implementation rules (carry forward to 0-E+)
1. Caps JSON build runs on the game thread inside `HandleEvent(BeginTakeActionEvent)`. Render thread emits prepared strings only.
2. `PendingSnapshot.CapsJson` is the single threading slot for caps payload. Future caps fields (Phase 0-E `BirthBuildProfile`?) thread through this object, never as a parallel slot.
3. Per-turn cadence is full dump. Provisional clause: migrate to a better cadence if measured constraints justify it (see "Open hazards / future revisit" below).
4. Schema is `runtime_caps.v1`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
5. `[caps]` failure is independent of `[screen]` and `[state]` — sentinel JSON (always parseable) replaces the data on a build error.
6. Effects observation point is post-`BeforeBeginTakeActionEvent` decrement (game-thread `BeginTakeActionEvent`). Effects with `Duration <= 0` are pre-`CleanEffects` ghosts and emit with `duration_kind: "unknown"`.

## Provisional cadence — future revisit triggers
The every-turn full dump approach is provisional. Re-open the cadence design when ANY of the following becomes empirically true:
1. Phase 1 WebSocket boundary lands and per-turn payload becomes a measurable bandwidth or token-cost item.
2. `Player.log` size becomes a deployment-blocker on long streaming sessions, OR a single Unity log line approaches an output truncation limit (Unity historically truncates long single-line `Debug.Log` calls — re-verify under the Unity build CoQ ships).
3. **Provider-neutral request / token / cache-cost metrics** show the redundant stable-list portion harms cost or cache reuse (originally framed as Anthropic prompt cache hit rate; generalized 2026-04-25 per Codex advisory because the Brain may run against multiple providers).
4. Phase 0-H `snapshot_hash` design needs separated stable / volatile components for a meaningful hash.
5. A future phase introduces inventory full dump and per-turn payload doubles.
6. Game-thread frame-time or GC pressure regression attributable to `BuildCapsJson` allocations (full `StringBuilder` + boxed numerics every turn). Profile under sustained Joppa play if subjective frame stutter appears around player-turn boundary.
7. Save / load round-trip semantics become load-bearing: `BodyPart.ID` is serialized state (CoQ's serializer touches `_ID` directly). If a Phase ever re-uses `part_id` across save / load, validate that the value space we emit survives a save → quit → reload cycle.
8. The Brain becomes a programmatic `[caps]` consumer (parses every line, not only the latest). At that point latest-line manual JSON validity is no longer sufficient; gate must move to "every line parses cleanly" as a CI step.
At any of those triggers, re-evaluate the candidates noted in the Phase 0-D plan: hybrid cadence, on-demand pull, payload compression, WebSocket-side filtering, Brain-side diff.

## Feed-forward for Phase 0-E
Phase 0-E (`BirthBuildProfile`: genotype, calling, attributes) per `docs/architecture-v5.md:2802`. Decompiled starting points the next plan will likely need (verify before re-citing):
- `decompiled/XRL.World/GameObject.cs` — `GetGenotype()`, `GetSubtype()`, `GetGameStat`/`GetStat` for attributes
- `decompiled/XRL.World.Parts/Statistics.cs` — `Statistics["Strength"].Value/.BaseValue` etc
- `decompiled/XRL.UI/CharacterCreate.cs` (or equivalent) — birth-time vs runtime delta

Open design questions for Phase 0-E (not for this exit memo):
- Whether `BirthBuildProfile` is captured ONCE per character (write at birth, read until death) or recomputed every turn from current state. Since Phase 0-E is about birth attributes, write-once is natural — but the runtime currently has no observation point for "the moment of birth" and we may need an alternative anchor (first BeginTakeActionEvent? specific event?).
- Whether `BirthBuildProfile` lives in `[caps]` (re-open the v1 schema lock) or a new `[birth]` line.

## Open hazards (still tracked from earlier phases)
- Render-thread exception spam dedup: zero ERROR lines over 95 + 110 + N turns. Continue to defer.
- Multi-mod coexistence: untested across all three phases. Revisit when a phase needs multi-mod observation.

## Files modified / created in Phase 0-D
| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Added `CapsJson` field to `PendingSnapshot`; added `BuildCapsJson` + `AppendMutations` + `AppendAbilities` + `AppendEffects` + `AppendEquipment` static helpers. ~250 lines. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Extended `HandleEvent` to build caps JSON in a separate `try/catch` and populate `PendingSnapshot.CapsJson`. Extended `AfterRenderCallback` to emit a third LogInfo line `[LLMOfQud][caps]`. |
| `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md` | Created at the start of Phase 0-D. |
| `docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:1787-1790`, `:2801`, `:443-468` (Phase 2 `check_status` consumer).
- `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md`
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate.
- `mod/LLMOfQud/SnapshotState.cs` — caps JSON build helpers.
- `mod/LLMOfQud/LLMOfQudSystem.cs` — game-thread / render-thread split (3 lines/turn).
- CoQ APIs (verify before re-citing): see Phase 0-D plan "Reference" section.
```

- [ ] **Step 2: Commit the exit memo.**

```bash
git add docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md
git commit -m "docs(memo): Phase 0-D exit memo — RuntimeCapabilityProfile observation

N-turn manual acceptance on Warden Joppa: BEGIN == END == [state] ==
[caps] == N, ERROR=0, latest [caps] passes json.loads with all 6 v1
keys, first-turn / last-turn shape parity OK. Records the provisional
every-turn cadence + revisit triggers, feeds forward to Phase 0-E
(BirthBuildProfile)."
```

- [ ] **Step 3: Open PR.**

```bash
git push -u origin <branch>
gh pr create --title "feat(mod): Phase 0-D RuntimeCapabilityProfile observation" \
  --body "$(cat <<'EOF'
## Summary
- New `[LLMOfQud][caps] {"turn":N,"schema":"runtime_caps.v1",...}` line per player decision point, alongside 0-B `[screen]` and 0-C `[state]`.
- Captures mutations (passive + active), activated abilities (cooldown rollup + raw + is_usable), status effects (raw Duration + duration_kind), equipment slots (BodyPart identity + equipped item).
- N-turn Warden Joppa acceptance: BEGIN == END == [state] == [caps] == N, ERROR=0.

## Test plan
- [x] Manual acceptance run (Task 6).
- [x] Latest [caps] line passes `json.loads` (ADR 0004 substituted gate).
- [x] First-turn vs last-turn shape parity.
- [x] Cooldown spot-check (best-effort, document-only if no ability used).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The PR will be reviewed via `/codex review` and `/cavendish` (per session instructions). Address findings, push fixes, merge per `feedback_docs_pr_merge_policy.md` if applicable (this is NOT a docs-only PR; full convergence loop applies).

---

## Acceptance criteria (rollup)

A Phase 0-D acceptance run is PASS iff all of the following hold:

1. **Compile clean.** `build_log.txt` shows `Compiling 3 file(s)... Success :)` for `LLMOfQud`. No `COMPILER ERRORS` for the mod.
2. **Counts.** `BEGIN == END == [state] == [caps] >= 100` over a single Warden run on Joppa.
3. **Hard error gate.** `ERR_SCREEN == 0`.
4. **Soft error gates.** `ERR_STATE == 0`, `ERR_CAPS == 0`. Non-zero values are investigated and recorded in the exit memo; they do not mechanically fail the gate (the sentinel JSON path is intentional defense in depth) but they are a re-open-trigger-4 candidate per ADR 0004.
5. **Latest-line JSON validity.** Latest `[caps]` line passes `json.loads`; required keys are present; `schema == "runtime_caps.v1"`.
6. **Every-line JSON validity.** All `[caps]` lines parse cleanly. Sentinel-error lines are tolerated but reported.
7. **Shape parity.** First-turn vs last-turn `[caps]` line have identical top-level keys and (when arrays are non-empty) identical first-element keys.
8. **Semantic invariants.** Across non-sentinel turns: Warden has non-empty `mutations` / `equipment` / `abilities` every turn; equipment slot keys are unique per turn; `ordinal_name` contains no `{{...}}` markup; `ui_display_level` is integer-typed.
9. **Cooldown monotonic descent (best-effort).** Either an ability was used during the run and `cooldown_segments_raw` shows monotonic descent, OR the exit memo explicitly records "cooldown decrement not exercised this run".
10. **Single-mod load order.** Acceptance run was performed with only `LLMOfQud` enabled.
11. **Exit memo committed.** `docs/memo/phase-0-d-exit-<YYYY-MM-DD>.md` exists on the branch.

---

## Open hazards / future revisit

Provisional decisions in this plan that may need revisiting:

- **Cadence (every-turn full dump).** Re-open when WebSocket bandwidth, Player.log size, prompt cache efficiency, Phase 0-H snapshot_hash design, or inventory full-dump payload doubling becomes a measured constraint. Candidates at re-open: hybrid (volatile / stable separation), on-demand pull, payload compression, WebSocket-side filtering, Brain-side diff.
- **`ui_display_level` is `m.GetUIDisplayLevel()`.** Default returns `Level`, but specific subclasses override (`decompiled/XRL.World.Parts.Mutation/BaseMutation.cs:209-212`). Brain consumers should treat `ui_display_level` as authoritative for "what number does the in-game character sheet show", and `level` as the resolved post-modifier integer; for some mutations the two will differ.
- **Toggle-ON cooldown special case.** `ActivatedAbilityEntry.Cooldown` getter returns 0 only when `AlwaysAllowToggleOff && ToggleState && Toggleable` (the toggle is currently ON for an indefinitely-on ability). The plan exposes BOTH `cooldown_segments_raw` (true storage) and `cooldown_segments_effective` (toggle-aware UI value); Brain consumers must use `is_usable` (or check `toggle_state` + raw segments) — they MUST NOT read `cooldown_segments_effective == 0` as "ready to use" for a toggleable ability without checking the toggle state.
- **`part_id` is null when `_ID == 0`.** The CoQ `BodyPart.ID` getter lazy-allocates by incrementing `The.Game.BodyPartIDSequence` (`decompiled/XRL.World.Anatomy/BodyPart.cs:365-381`); the plan guards with `HasID()` to avoid mutating game state during observation. Result: a fresh body part that nothing has yet "asked for" emits `part_id: null`. Brain consumers that need a stable slot identity should fall back on `(part_name, ordinal_name)` for null cases.
- **Equipment cybernetics.** `BodyPart.Cybernetics` is NOT emitted. Re-open if a Phase introduces cyber-aware reasoning (Phase 0-E `BirthBuildProfile`?).
- **Inventory full dump out-of-scope.** Phase 0-D emits equipped items only. Inventory enumeration is deferred indefinitely; if a Phase needs it, it goes in a new `[inv]` line, not in `[caps]`.
- **EndTurn / thaw-decrementing effects.** Effects with `UseStandardDurationCountdown() == false` that tick at `EndTurnEvent` (e.g. `Meditating`, `PhasedWhileStuck`) or via `UseThawEventToUpdateDuration` (e.g. `Lovesick`) are observed PRE-decrement at `[caps]` time, not post-. The schema documents this via `duration_kind` and the helper comment, but if Phase 1+ Brain prompts assume "duration_raw is turns remaining" universally, this assumption breaks for that subclass — re-open the schema if it does.
- **Multi-mod coexistence.** Untested. Same posture as 0-B / 0-C.
