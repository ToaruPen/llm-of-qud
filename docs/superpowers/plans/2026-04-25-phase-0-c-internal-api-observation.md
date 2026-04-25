# Phase 0-C: Internal API Observation (HP, position, zone, entities) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one structured JSON state line per player decision point, alongside the existing 80×25 ASCII screen block from Phase 0-B, so Phase 0-C+ has a structured observation primitive (HP / position / zone / visible entities with hostility) that the Python Brain (Phase 1+) can parse line-by-line over WebSocket without re-deriving it from ASCII.

**Architecture:**
- Game thread (`HandleEvent(BeginTakeActionEvent)`): increment turn counter, build the state JSON from `The.Player` / `The.ZoneManager.ActiveZone` / `Zone.GetObjects()` (game-thread state read, per `docs/architecture-v5.md:1787-1790`'s game-queue routing rule), wrap into a single `PendingSnapshot` instance, atomically publish via `Interlocked.Exchange`.
- Render thread (`AfterRenderCallback`, post-`Zone.Render` / pre-`DrawBuffer` per ADR 0002): atomically capture-and-clear the `PendingSnapshot`, walk the source `ScreenBuffer` for the ASCII body and the `ascii_sources` count map, then emit two `MetricsManager.LogInfo` calls — one for `[LLMOfQud][screen] ... turn=N ...` (the existing 0-B block, augmented with `display_mode`), one for `[LLMOfQud][state] {...}` (the new structured line). Both share `turn=N` as the correlation key; the parser must NOT assume adjacency.
- Slot replacement: 0-B's single `_pendingSnapshotTurn` int is replaced by a `_pendingSnapshot` ref slot of class `PendingSnapshot` (`Turn`, `StateJson`). Reference-typed `Interlocked.Exchange<T>` keeps both fields paired across threads with a single atomic operation.

**Why two LogInfo calls (not one combined JSON):** `MetricsManager.LogInfo` is `Debug.Log("INFO - " + Message)` (`decompiled/MetricsManager.cs:407-409`); each call emits exactly one Unity log entry. Embedding the 25-row ASCII inside the JSON would force every newline to escape (`\n` * 25) and destroy human readability of `Player.log` for manual acceptance. Keeping ASCII as a multi-line block (Phase 0-B framing, unchanged) and adding ONE additional JSON line preserves the manual-grep loop while giving the Brain a clean line-per-record JSON parse target. Codex advisor 2026-04-25 confirmed this trade-off.

**Why JSON state on game thread (not render thread):** `Zone.GetObjects()` returns `List<GameObject>` referencing live game objects (`decompiled/XRL.World/Zone.cs:1982`). Reading them on the render thread mid-`Zone.Render` lifecycle risks tearing because the game thread can mutate object state between `Zone.Render(buf)` and the post-render callback. Spec `docs/architecture-v5.md:1787-1790` explicitly routes player/zone reads through the game queue. The render callback is restricted to ScreenBuffer-only reads.

**Why atomic class-instance slot (not two int+ref slots):** A pair of separate `Interlocked.Exchange` writes is not an atomic group; the render thread could observe a half-published pair under contention. Single-instance `Interlocked.Exchange<PendingSnapshot>(ref _pendingSnapshot, ...)` swaps the pointer atomically, so the render thread either sees the complete (Turn, StateJson) pair or sees `null`.

**Scope boundaries:**
- In scope: HP (cur/max from `Statistics["Hitpoints"]`), position (X/Y/zone-id), entity list with hostility filter, `display_mode`, `ascii_sources` count map, manual JSON validity check.
- Out of scope (deferred to later phases per spec):
  - 0-D `RuntimeCapabilityProfile`: mutations, abilities, cooldowns, status effects, equipment.
  - 0-E `BirthBuildProfile`: genotype, calling, attributes.
  - 0-F: command issuance.
  - 0-G: heuristic bot logic. (0-C provides the inputs 0-G consumes; it does not implement decision logic.)
  - WebSocket transport (Phase 1).
  - Hunger / thirst / movement points (these are 0-D capability fields, not basic observation).
  - Fog-of-war serialization (Phase 0-C uses `obj.IsVisible()` filtering, not explored-map reconstruction).

**Open hazards inherited from prior phases (do not address here):**
- Mid-session mod reload (Phase 0-A Task 7) — closed by ADR 0003 as design-decision; streaming runtime fixes mods at launch. The new `_pendingSnapshot` ref slot resets to `null` on a fresh process; this matches 0-B's `_afterRenderRegistered` static-flag behavior.
- Render-thread exception spam dedup — 0-B left as "fix when it shows up" (zero errors over 95 turns). 0-C's render-side path is strictly smaller than 0-B's (no buffer mutation, no extra cell walk past the `ascii_sources` counter), so the same posture is retained.

**Tech Stack:**
- Same as Phase 0-A and 0-B. CoQ Roslyn-compiles `mod/LLMOfQud/*.cs` at game launch (`decompiled/XRL/ModInfo.cs:478, 757-823`); manual in-game verification against `build_log.txt` + `Player.log` is the acceptance gate. No new dependencies.
- Environment paths (verified in `docs/memo/phase-0-a-exit-2026-04-23.md` and `docs/memo/phase-0-b-exit-2026-04-25.md`):
  - `$MODS_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods`
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach:**
- Manual in-game verification (Phase 0-A and 0-B precedent). Game-as-harness automated smoke is deferred to Phase 2a per `agents/references/testing-strategy.md`.
- C# unit tests for `AppendJsonString` are deferred to Phase 2a per **ADR 0004**. Substitute: a manual JSON-validity check on the **latest single** `[LLMOfQud][state]` line, parsed by `python3 -c "import sys, json; json.loads(sys.stdin.read())"`. Per ADR 0004 re-open trigger 4, a single attributable JSON-invalidity occurrence at any phase forces the C# test infrastructure to be added.
- No external xUnit project introduced. Per `mod/AGENTS.md:5-21` no `.csproj` may live inside `mod/LLMOfQud/`.

**Reference:**
- `docs/architecture-v5.md` (v5.9): `:2800` (Phase 0-C scope), `:1787-1790` (game-queue routing rule), `:404-406` (visibility filter), `:408-411` (ScreenBuffer access), `:1186-1198` (`adjacent_hostile_count` requirement that Phase 0-G consumes), `:2426-2453` (canonical game_state field names that 0-C aliases to).
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` — the render-callback request/emit pattern this plan extends.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — `AppendJsonString` C# unit-test deferral (latest-single-line manual JSON-validity check is the substitute acceptance step).
- `docs/memo/phase-0-b-exit-2026-04-25.md:108-126` — Feed-forward for Phase 0-C, including the open design questions resolved in this plan via Codex review.
- CoQ APIs (verified, but re-confirm before each citation per root AGENTS.md §Imperatives item 1):
  - `decompiled/XRL/The.cs:23` — `public static GameObject Player => Game?.Player?.Body;`
  - `decompiled/XRL/The.cs:31` — `public static ZoneManager ZoneManager => Game?.ZoneManager;`
  - `decompiled/XRL.World/ZoneManager.cs:58` — `public Zone ActiveZone;`
  - `decompiled/XRL.World/Zone.cs:161` (field `_ZoneID`), `:388-398` (property `ZoneID` with parse-side-effect setter), `:1982-2010` (`GetObjects()` returns ALL objects, no visibility filter)
  - `decompiled/XRL.World/Cell.cs:210` (`X`), `:212` (`Y`), `:214` (`ParentZone`)
  - `decompiled/XRL.World/GameObject.cs:133` — `public Render Render;` (field, not property)
  - `decompiled/XRL.World/GameObject.cs:677-686, 6402-6421` — `DisplayName` / `GetDisplayNameEvent` machinery
  - `decompiled/XRL.World/GameObject.cs:755-766` — `ShortDisplayName` / `ShortDisplayNameSingle` / `ShortDisplayNameStripped`
  - `decompiled/XRL.World/GameObject.cs:1177-1187` — `baseHitpoints` (max HP)
  - `decompiled/XRL.World/GameObject.cs:1189-1213` — `hitpoints` (current HP)
  - `decompiled/XRL.World/GameObject.cs:2972-2986` — `DistanceTo(GameObject)` (path-distance, returns 9999999 on world-map / null cell)
  - `decompiled/XRL.World/GameObject.cs:8885` — `HasPart(string)`
  - `decompiled/XRL.World/GameObject.cs:9353` — `GetPart<T>()`
  - `decompiled/XRL.World/GameObject.cs:9930-` — `IsVisible()` (checks IsPlayer, "Non" tag, Physics, Render.Visible, FungalVision, IsHidden, …)
  - `decompiled/XRL.World/GameObject.cs:10887-10894` — `IsHostileTowards(GameObject)` delegates to `Brain?.IsHostileTowards`
  - `decompiled/XRL.World.Parts/Brain.cs:1864` — `public bool IsHostileTowards(GameObject Object)` (the actual hostility logic)
  - `decompiled/XRL.World.Parts/Render.cs:42` — `public string RenderString = "?";` (the glyph)
  - `decompiled/XRL.UI/Options.cs:574-576` — `public static bool UseTiles => Globals.RenderMode == RenderModeType.Tiles;`
  - `decompiled/MetricsManager.cs:407-409` — `LogInfo(msg)` → `Debug.Log("INFO - " + Message)`

---

## Prerequisites (one-time per session)

Before starting Task 1, confirm:

1. Phase 0-B is landed on `main` (commit `e9edf36 feat(mod): Phase 0-B ScreenBuffer ASCII observation via AfterRenderCallback` or a successor). Verify `mod/LLMOfQud/LLMOfQudSystem.cs` contains the `_afterRenderRegistered` static flag, the `_pendingSnapshotTurn` int slot, and the existing `AfterRenderCallback` body with the `Char → BackupChar → ' '` fallback.
2. The symlink `$MODS_DIR/LLMOfQud` still resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling, re-create per Phase 0-A Task 1.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. A clean save slot for the acceptance run (Task 5). Any playable character; 0-C does not constrain the build, but reusing the Phase 0-A/0-B Warden keeps the spot-check zone (Joppa) familiar.

---

## File Structure

Two C# files are touched in this plan:

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Add `using XRL.UI;` for `Options.UseTiles`. Add `using XRL.World.Parts;` only if `LLMOfQudSystem.cs` references `Render` directly; if all `Render` reads stay inside `SnapshotState`, `XRL.World.Parts` belongs only in `SnapshotState`. `ConsoleLib.Console` is already there from 0-B.
  - Replace `_pendingSnapshotTurn` (int) with `_pendingSnapshot` (`PendingSnapshot` ref).
  - Extend `HandleEvent(BeginTakeActionEvent)` to build the state JSON and atomically publish a new `PendingSnapshot`.
  - Extend `AfterRenderCallback` to consume the slot, capture `ascii_sources`, and emit two LogInfo calls (one for `[screen]` with `display_mode`, one for `[state]`).
- Create: `mod/LLMOfQud/SnapshotState.cs`
  - Internal sealed class `PendingSnapshot { public int Turn; public string StateJson; }`.
  - Static helpers `BuildStateJson(int turn, GameObject player)`, `AppendEntity(StringBuilder, GameObject player, GameObject obj)`, `AppendJsonString(StringBuilder, string)`, `BuildAsciiSourcesJson(int charCount, int backupCount, int blankCount)`.

No other source file changes. No manifest edits, no symlink changes, no new dependencies. The Roslyn compile set grows from 2 files to 3.

External (created during execution):
- `docs/memo/phase-0-c-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-b-exit-2026-04-25.md`'s shape.

---

## Task 1: Create `SnapshotState.cs` with helpers (no caller yet)

**Files:**
- Create: `mod/LLMOfQud/SnapshotState.cs`

**Why this task exists:** Isolates the pure-string assembly (JSON building, escape table, entity formatting) from the orchestration layer in `LLMOfQudSystem`. ADR 0004 explicitly designates `AppendJsonString` as the pure-functional seam; placing it in its own file keeps the seam recognizable when Phase 2a/2b lands the C# test harness and cherry-picks the test in.

- [ ] **Step 1: Create the file with the namespace, the `using` block, and the `PendingSnapshot` class.**

```csharp
using System;
using System.Globalization;
using System.Text;
using XRL;
using XRL.World;
using XRL.World.Parts;
using XRL.UI;

namespace LLMOfQud;

internal sealed class PendingSnapshot
{
    public int Turn;
    public string StateJson;
}

internal static class SnapshotState
{
    // Helpers added in Steps 2-5
}
```

Notes:
- Namespace `LLMOfQud` matches the existing `LLMOfQudSystem` (`mod/LLMOfQud/LLMOfQudSystem.cs:1`). CoQ's Roslyn compile is per-mod-Assembly; CLR namespaces inside the mod are free per project convention.
- `using XRL.World.Parts;` brings `Render` (`decompiled/XRL.World.Parts/Render.cs:10` — `namespace XRL.World.Parts`).
- `using XRL.UI;` brings `Options.UseTiles`.
- `internal` access on the helpers; Phase 0-C has no out-of-mod consumers.

- [ ] **Step 2: Add `AppendJsonString` (the pure escape helper).**

ADR 0004 requires this be defensive across the full JSON escape table including U+0000..U+001F and U+2028/U+2029.

```csharp
// JSON string escape per RFC 8259 §7. Wrapping quotes are appended.
// Handles: \", \\, \b, \f, \n, \r, \t, U+0000..U+001F as \u00XX,
// U+2028 / U+2029 as   /   (some downstream JSON parsers
// treat the raw bytes as line terminators which would break a single-
// line LogInfo emission).
internal static void AppendJsonString(StringBuilder sb, string value)
{
    sb.Append('"');
    if (value == null)
    {
        sb.Append('"');
        return;
    }
    int len = value.Length;
    for (int i = 0; i < len; i++)
    {
        char c = value[i];
        switch (c)
        {
            case '\\': sb.Append("\\\\"); break;
            case '"':  sb.Append("\\\""); break;
            case '\b': sb.Append("\\b"); break;
            case '\f': sb.Append("\\f"); break;
            case '\n': sb.Append("\\n"); break;
            case '\r': sb.Append("\\r"); break;
            case '\t': sb.Append("\\t"); break;
            case '\u2028': sb.Append("\\u2028"); break;
            case '\u2029': sb.Append("\\u2029"); break;
            default:
                if (c < 0x20)
                {
                    sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                }
                else
                {
                    sb.Append(c);
                }
                break;
        }
    }
    sb.Append('"');
}
```

Notes:
- `null` produces `""` rather than throwing. Phase 0-C never knowingly passes null, but a nil display name from a partly-initialized object is a real CoQ failure mode and we prefer a parseable empty string over a thrown exception inside `AppendJsonString`.
- Surrogate pairs (`U+D800..U+DFFF`) are passed through as-is. JSON allows lone surrogates in strings; `json.loads` accepts them. CoQ display strings are unlikely to contain them, but breaking valid surrogate pairs would corrupt the glyph, so we do not split.
- `CultureInfo.InvariantCulture` keeps `ToString("x4")` deterministic across locales.

- [ ] **Step 3: Add `BuildAsciiSourcesJson` (small JSON object for the ascii-source counter).**

```csharp
internal static void AppendAsciiSourcesJson(
    StringBuilder sb, int charCount, int backupCount, int blankCount)
{
    sb.Append("{\"char\":").Append(charCount.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"backup_char\":").Append(backupCount.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"blank\":").Append(blankCount.ToString(CultureInfo.InvariantCulture));
    sb.Append('}');
}
```

This intentionally takes raw counts (not a struct) so the caller can wire it into either the `[screen]` line metadata or a future structured framing without `SnapshotState` knowing about either.

- [ ] **Step 4: Add `AppendEntity` (one entity-record JSON object).**

```csharp
// Single entity record. Caller is responsible for separating multiple
// records with commas. Schema:
//   {
//     "id": "e1",                  // snapshot-local; regenerated per turn
//     "name": "snapjaw",            // ShortDisplayNameStripped
//     "glyph": "s",                 // Render.RenderString first char, or "?"
//     "pos": {"x": 41, "y": 13},   // absolute Cell coordinates
//     "rel": {"dx": 1, "dy": 1},   // relative to player
//     "distance": 2,                // path distance via DistanceTo
//     "adjacent": false,            // distance <= 1 && !same cell
//     "hostile_to_player": true,    // GameObject.IsHostileTowards(player)
//     "hp": [12, 18]                // [current, max]; null if no Statistics
//   }
internal static void AppendEntity(
    StringBuilder sb, int idOrdinal, GameObject player, GameObject obj)
{
    Cell pCell = player?.CurrentCell;
    Cell oCell = obj?.CurrentCell;
    int px = pCell != null ? pCell.X : 0;
    int py = pCell != null ? pCell.Y : 0;
    int ox = oCell != null ? oCell.X : 0;
    int oy = oCell != null ? oCell.Y : 0;
    int distance = (player != null && obj != null) ? player.DistanceTo(obj) : 9999999;
    bool adjacent = (distance == 1);
    bool hostile = (player != null && obj != null) ? obj.IsHostileTowards(player) : false;
    int hp = obj?.hitpoints ?? 0;
    int hpMax = obj?.baseHitpoints ?? 0;
    bool hasHp = (obj != null) && (hpMax > 0);

    string name = obj?.ShortDisplayNameStripped ?? "<unknown>";
    Render render = obj?.Render;
    string glyphSource = render != null ? render.RenderString : null;
    char glyphChar = (!string.IsNullOrEmpty(glyphSource)) ? glyphSource[0] : '?';

    sb.Append("{\"id\":\"e").Append(idOrdinal.ToString(CultureInfo.InvariantCulture)).Append('"');
    sb.Append(",\"name\":");
    AppendJsonString(sb, name);
    sb.Append(",\"glyph\":");
    AppendJsonString(sb, glyphChar.ToString());
    sb.Append(",\"pos\":{\"x\":").Append(ox.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"y\":").Append(oy.ToString(CultureInfo.InvariantCulture)).Append('}');
    sb.Append(",\"rel\":{\"dx\":").Append((ox - px).ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"dy\":").Append((oy - py).ToString(CultureInfo.InvariantCulture)).Append('}');
    sb.Append(",\"distance\":").Append(distance.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"adjacent\":").Append(adjacent ? "true" : "false");
    sb.Append(",\"hostile_to_player\":").Append(hostile ? "true" : "false");
    if (hasHp)
    {
        sb.Append(",\"hp\":[").Append(hp.ToString(CultureInfo.InvariantCulture));
        sb.Append(',').Append(hpMax.ToString(CultureInfo.InvariantCulture)).Append(']');
    }
    else
    {
        sb.Append(",\"hp\":null");
    }
    sb.Append('}');
}
```

Notes:
- `id` is snapshot-local (`e1`, `e2`, …). The mod does NOT persist entity IDs across turns; cross-turn correlation is out of scope for 0-C and Phase 1+ will own it via `snapshot_hash` machinery (`docs/architecture-v5.md` §4 Layer 2).
- `ShortDisplayNameStripped` (`decompiled/XRL.World/GameObject.cs:766`) removes color markup. Raw `DisplayName` may contain `&K`-style color codes that would inflate the JSON and confuse Brain parsers.
- `glyph` is the first char of `Render.RenderString` (`decompiled/XRL.World.Parts/Render.cs:42` defaults to `"?"`). Multi-char render strings (e.g., escape sequences) are truncated to one char on purpose; the structured glyph field is for indexing, not display.
- `DistanceTo(GameObject)` returns 9999999 on world-map / null cells (`GameObject.cs:2972-2986`). The 9999999 sentinel is preserved; consumers that filter by distance must handle it.
- `hp` is `[current, max]` per spec `:1186-1198` style; `null` if `baseHitpoints == 0` (the entity has no Statistics["Hitpoints"] and `hitpoints` would just return 0 misleadingly).
- `hostile_to_player` uses `GameObject.IsHostileTowards(player)` (`GameObject.cs:10887-10894`), which delegates to `Brain?.IsHostileTowards` and returns `false` when `Brain == null` — terrain and items will report `false` here, not throw.

- [ ] **Step 5: Add `BuildStateJson` (the top-level state serializer).**

```csharp
// Entry point used by HandleEvent. Returns the full state-line payload
// (the value of the [LLMOfQud][state] line; caller adds the prefix).
// Schema:
//   {
//     "turn": N,
//     "player": {"id": "p", "name": "@", "hp": [cur, max]},
//     "pos": {"x": X, "y": Y, "zone": "<ZoneID or null>"},
//     "display_mode": "tile" | "ascii",
//     "entities": [ ...AppendEntity records... ]
//   }
internal static string BuildStateJson(int turn)
{
    GameObject player = The.Player;
    Cell pCell = player?.CurrentCell;
    Zone zone = pCell?.ParentZone ?? The.ZoneManager?.ActiveZone;
    string zoneId = zone?.ZoneID;
    int px = pCell != null ? pCell.X : 0;
    int py = pCell != null ? pCell.Y : 0;
    int hp = player?.hitpoints ?? 0;
    int hpMax = player?.baseHitpoints ?? 0;
    string displayMode = Options.UseTiles ? "tile" : "ascii";

    StringBuilder sb = new StringBuilder(2048);
    sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));

    // Player block.
    sb.Append(",\"player\":{\"id\":\"p\",\"name\":");
    AppendJsonString(sb, player?.ShortDisplayNameStripped ?? "<no-player>");
    if (player != null && hpMax > 0)
    {
        sb.Append(",\"hp\":[").Append(hp.ToString(CultureInfo.InvariantCulture));
        sb.Append(',').Append(hpMax.ToString(CultureInfo.InvariantCulture)).Append(']');
    }
    else
    {
        sb.Append(",\"hp\":null");
    }
    sb.Append('}');

    // Position block.
    sb.Append(",\"pos\":{\"x\":").Append(px.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"y\":").Append(py.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"zone\":");
    if (zoneId != null) AppendJsonString(sb, zoneId); else sb.Append("null");
    sb.Append('}');

    // Display mode.
    sb.Append(",\"display_mode\":");
    AppendJsonString(sb, displayMode);

    // Entities (visible, non-player, with Brain-or-Combat).
    sb.Append(",\"entities\":[");
    if (zone != null && player != null)
    {
        int ordinal = 0;
        foreach (GameObject obj in zone.GetObjects())
        {
            if (obj == null) continue;
            if (obj == player) continue;
            if (obj.CurrentCell == null) continue;
            if (!obj.IsVisible()) continue;
            // Entity gate: must be a creature-like object. Brain present
            // OR HasPart("Combat") OR has positive baseHitpoints. This
            // excludes terrain, items, and decorative objects without
            // committing to a fixed taxonomy.
            bool isCreatureLike = (obj.Brain != null) || obj.HasPart("Combat") || obj.baseHitpoints > 0;
            if (!isCreatureLike) continue;

            ordinal++;
            if (ordinal > 1) sb.Append(',');
            AppendEntity(sb, ordinal, player, obj);
        }
    }
    sb.Append(']');

    sb.Append('}');
    return sb.ToString();
}
```

Notes:
- `player == null` happens at world-map screens and during certain modal transitions. We still emit a state line with `"player":{"name":"<no-player>","hp":null}` — manual acceptance can decide whether to skip those frames or treat them as informational.
- `zone == null` is a similar edge; we emit `"zone":null`.
- The entity gate (`Brain != null || HasPart("Combat") || baseHitpoints > 0`) is a soft heuristic. Codex's review (Q3 round 1) recommended `Brain != null || HasPart("Combat")`; we add `baseHitpoints > 0` because some pre-spawn or unfinished mob objects briefly lack a Brain part. This will admit some non-creatures with Hitpoints (e.g., destructible doors), which is acceptable for 0-C scope (they have HP and a glyph; the LLM can decide to ignore them).
- `zone.GetObjects()` allocates a new `List<GameObject>` per call (`Zone.cs:1982-2010`). One allocation per snapshot is cheap relative to the per-turn JSON build.

- [ ] **Step 6: Verify the file syntactically (no caller yet).**

```bash
grep -c "internal static string BuildStateJson" mod/LLMOfQud/SnapshotState.cs
grep -c "internal static void AppendJsonString" mod/LLMOfQud/SnapshotState.cs
grep -c "internal static void AppendEntity"     mod/LLMOfQud/SnapshotState.cs
grep -c "internal sealed class PendingSnapshot" mod/LLMOfQud/SnapshotState.cs
```

Expected: each returns `1`.

Compile-check happens in Task 4 (CoQ launch). No commit yet (per `agents/references/commit-policy.md` "Never commit unless explicitly requested by the user").

---

## Task 2: Replace 0-B's int slot with the `PendingSnapshot` ref slot

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** The current Phase 0-B `_pendingSnapshotTurn` int slot only carries `turn`. Phase 0-C must also carry `stateJson` (built on the game thread) across to the render thread. Two separate `Interlocked.Exchange` calls (one int, one ref) are not atomic as a pair; the render thread could observe a half-published state. Using a single class-instance ref slot via `Interlocked.Exchange<T>` gives one atomic publish point.

- [ ] **Step 1: Open `mod/LLMOfQud/LLMOfQudSystem.cs` and remove the `_pendingSnapshotTurn` field.**

The current declaration in Phase 0-B looks like:

```csharp
private static int _pendingSnapshotTurn;
```

Delete this line. (If the codebase has drifted, locate it via `grep -n "_pendingSnapshotTurn" mod/LLMOfQud/LLMOfQudSystem.cs`.)

- [ ] **Step 2: Add the new `_pendingSnapshot` ref slot.**

In the same field-declaration neighborhood, add:

```csharp
// Snapshot request handshake between HandleEvent (game thread) and
// AfterRenderCallback (render thread). null = no pending request.
// Game thread: Interlocked.Exchange a fully built PendingSnapshot.
// Render thread: Interlocked.Exchange to null, captures the prior value.
// Single class-instance keeps Turn and StateJson paired atomically;
// a pair of int+string slots would not be atomic across the two writes.
private static PendingSnapshot _pendingSnapshot;
```

- [ ] **Step 3: Update `HandleEvent(BeginTakeActionEvent)` to publish a `PendingSnapshot` via the ref slot.**

Locate the existing body (post Phase 0-B):

```csharp
public override bool HandleEvent(BeginTakeActionEvent E)
{
    _beginTurnCount++;
    Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount);
    if (_beginTurnCount % 10 == 0)
    {
        MetricsManager.LogInfo(
            "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
    }
    return base.HandleEvent(E);
}
```

Replace with:

```csharp
public override bool HandleEvent(BeginTakeActionEvent E)
{
    _beginTurnCount++;

    // Build the structured state JSON on the game thread. This MUST run
    // on the game thread (not the render callback) because it reads
    // The.Player / Zone.GetObjects() / GameObject statistics — see
    // docs/architecture-v5.md:1787-1790 for the canonical routing rule.
    // Reading these on the render thread risks tearing.
    string stateJson;
    try
    {
        stateJson = SnapshotState.BuildStateJson(_beginTurnCount);
    }
    catch (Exception ex)
    {
        // Mirror the AfterRenderCallback exception posture: never let
        // observation kill the mod. Emit a sentinel JSON so the parser
        // sees a valid line; the broader [state] line will still flow
        // for the next turn.
        stateJson = "{\"turn\":" + _beginTurnCount.ToString() +
            ",\"error\":\"" + ex.GetType().Name + "\"}";
        MetricsManager.LogInfo(
            "[LLMOfQud][state] ERROR turn=" + _beginTurnCount +
            " " + ex.GetType().Name + ": " + ex.Message);
    }

    PendingSnapshot pending = new PendingSnapshot
    {
        Turn = _beginTurnCount,
        StateJson = stateJson,
    };
    Interlocked.Exchange(ref _pendingSnapshot, pending);

    if (_beginTurnCount % 10 == 0)
    {
        MetricsManager.LogInfo(
            "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
    }
    return base.HandleEvent(E);
}
```

Notes:
- `_beginTurnCount++` MUST stay first; the per-10-turns log line ties to the same value.
- `try/catch` around `BuildStateJson` is a deliberate exception to the project's "no defensive validation" rule (see Phase 0-B Task 2 Step 3 comment for the same rationale on the render thread). The state read goes through CoQ subsystems (`Statistics`, `Brain`, `Render`) that can throw under pathological game states; a throw inside `HandleEvent` would propagate into CoQ's event dispatch and break gameplay. We sacrifice one snapshot, log the failure, and continue.
- The sentinel JSON includes `error` and `turn` so the manual JSON-validity check still parses successfully on a failed turn — the latest-line check from ADR 0004 keys on parse-validity, not absence of error fields.

- [ ] **Step 4: Verify the field replacement and HandleEvent surface.**

```bash
grep -c "_pendingSnapshotTurn" mod/LLMOfQud/LLMOfQudSystem.cs
grep -c "_pendingSnapshot\b"    mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "Interlocked.Exchange.*_pendingSnapshot," mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "SnapshotState.BuildStateJson"            mod/LLMOfQud/LLMOfQudSystem.cs
```

Expected:
- `_pendingSnapshotTurn`: `0` (field removed; no remaining references).
- `_pendingSnapshot`: `≥ 3` (declaration + Exchange in HandleEvent + Exchange in AfterRenderCallback after Task 3).
- `Interlocked.Exchange.*_pendingSnapshot,`: `1` for the HandleEvent call so far.
- `SnapshotState.BuildStateJson`: `1`.

---

## Task 3: Extend `AfterRenderCallback` to consume the slot and emit `[state]` + `display_mode` + `ascii_sources`

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** The render-thread emission point gains three responsibilities while keeping its existing 0-B contract. The ASCII walk that 0-B already performs is augmented to count `_Char` / `BackupChar` / blank cells (cheap; same loop). The slot-consume changes from int read to ref `Interlocked.Exchange<PendingSnapshot>`. The new `[state]` line uses the JSON the game thread already prepared.

- [ ] **Step 1: Update the `SnapshotAscii` helper in `LLMOfQudSystem.cs` to also return source counts.**

Phase 0-B's `SnapshotAscii` returns `string`. Replace its body to return both the body and the counts. Choose the smallest signature change: return a small named tuple or an out-param triple. Use out-params for clarity and to avoid System.ValueTuple churn:

Locate the existing helper:

```csharp
private static string SnapshotAscii(ScreenBuffer buf)
{
    // existing 0-B body
}
```

Replace with:

```csharp
private static string SnapshotAscii(
    ScreenBuffer buf, out int charCount, out int backupCount, out int blankCount)
{
    charCount = 0;
    backupCount = 0;
    blankCount = 0;
    if (buf == null)
    {
        return "<null-buffer>\n";
    }
    int w = buf.Width;
    int h = buf.Height;
    if (w <= 0 || h <= 0 || buf.Buffer == null)
    {
        return "<empty-buffer w=" + w + " h=" + h + ">\n";
    }
    StringBuilder sb = new StringBuilder(w * h + h);
    for (int y = 0; y < h; y++)
    {
        for (int x = 0; x < w; x++)
        {
            ConsoleChar cell = buf.Buffer[x, y];
            char c = cell.Char;
            if (c == '\0')
            {
                char backup = cell.BackupChar;
                if (backup == '\0')
                {
                    blankCount++;
                    sb.Append(' ');
                }
                else
                {
                    backupCount++;
                    sb.Append(backup);
                }
            }
            else
            {
                charCount++;
                sb.Append(c);
            }
        }
        sb.Append('\n');
    }
    return sb.ToString();
}
```

Notes:
- This is the same per-cell logic as 0-B with three counters added in the same loop. The arithmetic cost is negligible.
- The empty-buffer / null-buffer fallbacks emit `\n` so the framing in Step 2 still produces 1 line. The counts stay zero in those cases; manual acceptance can flag the anomaly via `display_mode`-vs-counts mismatch.

- [ ] **Step 2: Replace the `AfterRenderCallback` body.**

The current Phase 0-B body reads `_pendingSnapshotTurn` via int Exchange, walks `SnapshotAscii`, and emits one `[screen]` LogInfo. Replace with:

```csharp
private static void AfterRenderCallback(XRLCore core, ScreenBuffer buf)
{
    PendingSnapshot pending = Interlocked.Exchange<PendingSnapshot>(ref _pendingSnapshot, null);
    if (pending == null)
    {
        return;
    }
    int turn = pending.Turn;
    string stateJson = pending.StateJson;
    try
    {
        int w = buf != null ? buf.Width : 0;
        int h = buf != null ? buf.Height : 0;
        int charCount, backupCount, blankCount;
        string body = SnapshotAscii(buf, out charCount, out backupCount, out blankCount);
        string displayMode = Options.UseTiles ? "tile" : "ascii";

        // Frame 1: [screen] block, augmented with display_mode and counts
        // on the BEGIN line. END line is unchanged from 0-B for parser
        // continuity.
        MetricsManager.LogInfo(
            "[LLMOfQud][screen] BEGIN turn=" + turn +
            " w=" + w + " h=" + h +
            " mode=" + displayMode +
            " src=char:" + charCount + ",backup:" + backupCount + ",blank:" + blankCount +
            "\n" + body +
            "[LLMOfQud][screen] END turn=" + turn);

        // Frame 2: [state] structured line. Parser keys on turn=N to
        // correlate with the [screen] block; adjacency is NOT assumed
        // (see ADR 0004 acceptance step and docs/memo/phase-0-b-exit-
        // 2026-04-25.md).
        MetricsManager.LogInfo("[LLMOfQud][state] " + stateJson);
    }
    catch (Exception ex)
    {
        MetricsManager.LogInfo(
            "[LLMOfQud][screen] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
    }
}
```

Notes:
- `Interlocked.Exchange<PendingSnapshot>(ref _pendingSnapshot, null)` is the atomic capture-and-clear. The render thread either reads a fully built `PendingSnapshot` or `null` — never a torn instance.
- `Options.UseTiles` is read again here (it was also read on the game thread for the JSON `display_mode` field). The two reads are not guaranteed equal if the player toggles display mode between `HandleEvent` and the next render; manual acceptance should treat that as a low-priority edge. We do NOT carry `display_mode` from `HandleEvent` to the render thread to avoid mixing concerns.
- `[screen] END` line stays exactly as 0-B (`[LLMOfQud][screen] END turn=N`) so existing 0-B grep tooling keeps working.
- The `try/catch` wraps the WHOLE emission. If anything throws (including the new `Options.UseTiles` read or the ASCII walk), we log a single ERROR line and drop the snapshot. The state JSON was already built on the game thread; if its emission fails here, the parser sees no `[state]` line for that turn — manual acceptance step 5 will catch any extended drought.

- [ ] **Step 3: Verify the surfaces.**

```bash
grep -c "Interlocked.Exchange<PendingSnapshot>" mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "BEGIN turn=\" + turn"                  mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "\\[LLMOfQud\\]\\[state\\] \" + stateJson" mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "out int charCount, out int backupCount, out int blankCount" mod/LLMOfQud/LLMOfQudSystem.cs
```

Expected: `1` for each. The `[screen]` BEGIN line has `mode=` and `src=` substrings; `[state]` line is appended; `SnapshotAscii` carries the new out-params.

No commit yet.

---

## Task 4: In-process Roslyn compile check via CoQ

**Files:** None. Runs the game.

**Why this task exists:** CoQ Roslyn-compiles all `.cs` in `mod/LLMOfQud/` at launch (`decompiled/XRL/ModInfo.cs:478, 757-823`). With `SnapshotState.cs` newly added, the compile set grows from 2 files to 3. `build_log.txt` is the authoritative compile gate.

- [ ] **Step 1: Launch CoQ fresh** (fully quit and relaunch; do not toggle from the Mods menu — Phase 0-A Task 7 was closed by ADR 0003 only for streaming-runtime use, mid-session reload remains unverified).

- [ ] **Step 2: Without embarking yet, quit the game.**

This exercises `ModManager.BuildMods()` during splash.

- [ ] **Step 3: Inspect `build_log.txt`.**

```bash
tail -n 80 "$COQ_SAVE_DIR/build_log.txt" | grep -E "=== LLM OF QUD ===|Compiling \d+ files?\.\.\.|Success :\)|COMPILER ERRORS|\[LLMOfQud\]"
```

Expected (timestamps will differ):

```
[YYYY-MM-DDTHH:MM:SS] === LLM OF QUD ===
[YYYY-MM-DDTHH:MM:SS] Compiling 3 files...
[YYYY-MM-DDTHH:MM:SS] Success :)
[YYYY-MM-DDTHH:MM:SS] [LLMOfQud] loaded v0.0.1 at YYYY-MM-DDTHH:MM:SS.fffffffZ
```

Note: `Compiling 3 files...` (was `2 files...` in 0-B). If you see `Compiling 2 files...` after Task 1, the new `SnapshotState.cs` is not under the symlinked `mod/LLMOfQud/` path — re-run the symlink check from Prerequisites.

If `COMPILER ERRORS` appears for `SnapshotState.cs` or `LLMOfQudSystem.cs`, capture the full block, stop, and fix the cited line.

- [ ] **Step 4: Record the CoQ build for the exit memo.**

```bash
grep -m 1 "BUILD_" "$COQ_SAVE_DIR/build_log.txt" | tail -1
```

Stash the value (e.g., `Defined symbol: BUILD_2_0_210` or newer).

---

## Task 5: Acceptance run — visible-NPC spot-check + JSON-validity check

**Files:** None. Plays the game.

**Why this task exists:** Three claims need empirical verification on a single run before durability testing in Task 6:
1. Each player decision point produces exactly one `[screen]` block AND one `[state]` line correlated by `turn=N`.
2. The `entities` array of `[state]` includes a known-visible NPC, with the NPC's glyph matching the corresponding cell in the ASCII block.
3. The `[state]` line is parseable JSON.

Claim (3) is the manual substitute for the C# unit test deferred by ADR 0004.

- [ ] **Step 1: Launch CoQ fresh, embark any character (the Phase 0-A/0-B Warden is the path of least friction).** Do not move yet.

- [ ] **Step 2: Open `Player.log` in a second terminal.**

```bash
tail -F "$PLAYER_LOG" | grep -E "INFO - \[LLMOfQud\]"
```

You should see, on first gaining control:
- One `[LLMOfQud][screen] BEGIN turn=1 ... mode=... src=...` line followed by 25 ASCII rows, then `[LLMOfQud][screen] END turn=1`.
- One `[LLMOfQud][state] {"turn":1,...}` line.

- [ ] **Step 3: Visual spot-check — find a visible NPC and verify its `[state]` entry matches its on-screen glyph.**

Joppa's starting screen typically has Mehmet (the watervine farmer) and at least one chicken nearby; pick whichever NPC is closest to `@`.

a. Read the `pos` of `@` from the `[state]` line: `"player":{...},"pos":{"x":X,"y":Y,"zone":"..."}`.
b. Find the NPC's `entities` entry: `"entities":[{"id":"e1","name":"<some-name>","glyph":"<G>","pos":{"x":NX,"y":NY},...}]`.
c. In the `[screen]` block, line `NY+2` (1-indexed because the `[screen]` BEGIN line is line 1 and screen row `y=0` is line 2), column `NX+1`, MUST contain the character `<G>`.
d. Verify `hostile_to_player`: chickens and Mehmet should be `false`. Snapjaws (if any are visible) should be `true`.

If the glyph mismatch is exactly off-by-one in a consistent direction, that is a coordinate-axis bug in `AppendEntity` — re-check `Cell.X` (column, 0-indexed) vs `Cell.Y` (row, 0-indexed). Phase 0-B's ASCII grid is 80×25 with `Buffer[x, y]` indexing.

- [ ] **Step 4: Manual JSON validity check (ADR 0004 acceptance step).**

```bash
grep "INFO - \[LLMOfQud\]\[state\] " "$PLAYER_LOG" | tail -n 1 | sed 's/^.*\[LLMOfQud\]\[state\] //' | python3 -c "import sys, json; print(json.loads(sys.stdin.read()))"
```

The pipeline:
1. `grep` selects all `[state]` lines.
2. `tail -n 1` keeps the LATEST one (per ADR 0004 — multi-line bulk piping is forbidden).
3. `sed` strips everything up to and including the `[LLMOfQud][state] ` prefix, leaving only the JSON object.
4. `python3 -c "..."` calls `json.loads`. Success prints the parsed dict; failure raises `json.decoder.JSONDecodeError` with the offending position.

PASS: the dict prints. FAIL: any decode error. Per ADR 0004 re-open trigger 4, a single attributable failure (not a `grep`/`sed` extraction error) is sufficient to invalidate the deferral and force C# unit-test infrastructure introduction before continuing.

- [ ] **Step 5: Take exactly one action (press `.` to rest one turn) and verify a second snapshot (turn=2) appears for both `[screen]` and `[state]`.**

Re-run the JSON validity check from Step 4 — `tail -n 1` now picks turn=2.

- [ ] **Step 6: Decide acceptance.**

PASS condition (Task 5):
- One `[screen]` block per `BeginTakeActionEvent` (turn=1 + turn=2).
- One `[state]` line per `BeginTakeActionEvent`, with `turn` matching.
- Spot-check NPC's glyph cell matches between `[screen]` body and `entities[i].glyph`.
- Both `[state]` lines parse as JSON via Step 4 / 5 commands.

FAIL responses:
- Two `[state]` lines for one turn → duplicate publication. Inspect `Interlocked.Exchange` paths in `HandleEvent`.
- `[state]` line missing for a turn that has `[screen]` → `BuildStateJson` threw. Look for `[LLMOfQud][state] ERROR turn=N` and fix the cited cause.
- `[state]` line missing AND `[screen]` BEGIN/END mismatch → `AfterRenderCallback` threw between the two LogInfo calls. Look for `[LLMOfQud][screen] ERROR turn=N`.
- Glyph mismatch off-by-one consistently → `AppendEntity` coordinate axis bug.
- JSON decode error → STOP. Capture the offending line and the JSONDecodeError verbatim. ADR 0004 trigger 4 fires; do not patch around the failure to advance the plan.

---

## Task 6: 20-turn durability run + log-volume check

**Files:** None. Plays the game.

**Why this task exists:** Catches drift invisible to the single-turn spot-check: missed turns, intermittent JSON-build exceptions, log-volume regressions from the new `[state]` line.

- [ ] **Step 1: Continuing from Task 5, play 20 consecutive turns of any activity (rest, walk, no menus that block `BeginTakeActionEvent`).**

- [ ] **Step 2: Count `[screen]` and `[state]` markers.**

```bash
grep -c "INFO - \[LLMOfQud\]\[screen\] BEGIN" "$PLAYER_LOG"
grep -c "INFO - \[LLMOfQud\]\[screen\] END"   "$PLAYER_LOG"
grep -c "INFO - \[LLMOfQud\]\[state\] "       "$PLAYER_LOG"
```

Expected: all three counts equal, equal to the number of player turns elapsed since launch (Task 5's turn=1 + turn=2 + this task's 20 = 22). If any count diverges, an exception interrupted the corresponding emit; check for `[screen] ERROR` and `[state] ERROR` lines.

- [ ] **Step 3: Verify the per-10-turns counter line is unchanged.**

```bash
grep "INFO - \[LLMOfQud\] begin_take_action count=" "$PLAYER_LOG" | tail -3
```

Expected: `count=10`, `count=20` present (turn 22 may not have triggered count=30 yet). The 0-A cadence is intact.

- [ ] **Step 4: Spot-check turn=10 and turn=20.**

For each, run the Task 5 Step 4 JSON-validity command but with the explicit turn pinned:

```bash
for T in 10 20; do
  echo "--- turn=$T ---"
  grep "INFO - \[LLMOfQud\]\[state\] {\"turn\":$T," "$PLAYER_LOG" | tail -n 1 \
    | sed 's/^.*\[LLMOfQud\]\[state\] //' \
    | python3 -c "import sys, json; print(json.loads(sys.stdin.read()))"
done
```

Expected: both print parsed dicts. If `tail -n 1` returns empty for either turn, that turn's `[state]` line was lost — re-check the slot lifecycle.

- [ ] **Step 5: Verify entity-list non-trivial at least once.**

```bash
grep "INFO - \[LLMOfQud\]\[state\] " "$PLAYER_LOG" \
  | python3 -c "
import sys, json
seen_nonempty = False
for line in sys.stdin:
    payload = line.split('[LLMOfQud][state] ', 1)[1]
    obj = json.loads(payload)
    if obj['entities']:
        print('turn', obj['turn'], 'has', len(obj['entities']), 'entities')
        seen_nonempty = True
        break
sys.exit(0 if seen_nonempty else 1)
"
```

Expected exit code 0 (at least one snapshot has entities). Joppa's surface always has chickens / Mehmet within sight; an empty list across all 22 turns indicates the visibility filter or entity gate is incorrect.

- [ ] **Step 6: Measure log bulk.**

```bash
wc -l "$PLAYER_LOG"
du -h  "$PLAYER_LOG"
```

For 22 turns: 0-B emitted ~27 lines per snapshot (`[screen]` BEGIN + 25 rows + END); 0-C adds 1 `[state]` line per snapshot. Expected: ~28 × 22 = ~616 lines from the mod, ~45 KB. If the file is dramatically larger (>5 MB), a write-amplification bug is hiding — investigate.

- [ ] **Step 7: Quit the game cleanly (main menu → Quit, NOT force-kill).**

Re-run Step 2's counts on the final file to confirm nothing was lost on shutdown.

---

## Task 7: Write the Phase 0-C exit memo

**Files:**
- Create: `docs/memo/phase-0-c-exit-<YYYY-MM-DD>.md`

**Why this task exists:** Matches the Phase 0-A / 0-B convention. Phase 0-D re-entry needs a single empirical-truth document for 0-C.

- [ ] **Step 1: Create the file with this shape (mirror `docs/memo/phase-0-b-exit-2026-04-25.md`).**

Required sections in order:

1. **Heading + status** (PASS or specific deviation).
2. **Environment (empirically verified)** — CoQ build, OS, env paths. Re-confirm at write time; do not copy stale values.
3. **Phase 0-C acceptance** — checklist with embedded log excerpts:
   - Compile (`build_log.txt`): `Compiling 3 files...` / `Success :)` / load marker.
   - Snapshot framing (`Player.log`): counts of `[screen] BEGIN`, `[screen] END`, `[state]`, `[screen] ERROR`, `[state] ERROR`. All five required.
   - Spot-check NPC: turn, NPC name, glyph, `[screen]` cell coordinate, `[state]` entry verbatim.
   - JSON-validity: latest `[state]` line at acceptance close, parsed dict printed.
   - Entity-list non-empty: turn and entity count.
4. **`AppendJsonString` rare-character review** (per ADR 0004 carry-forward). One paragraph: did any acceptance-run NPC name expose an escape edge? If yes, what; if no, state explicitly.
5. **Snapshot volume** — total `[screen]` BEGINs, total `[state]`s, bytes on disk, ratio against 0-B baseline.
6. **Execution deviations from plan** — any merged tasks, skipped steps, extended runs.
7. **Open hazards inherited / re-opened** — `_pendingSnapshot` static-field-on-reload posture, render-thread exception spam dedup posture, ADR 0004 deferral re-open conditions checked-and-not-fired.
8. **Feed-forward for Phase 0-D** — pointers (decompiled citations) for `RuntimeCapabilityProfile` (mutations / abilities / cooldowns / status effects / equipment).
9. **Files modified / created in Phase 0-C** — exact list.

- [ ] **Step 2: Fill each section from the raw evidence captured in Tasks 4–6.**

Verbatim log excerpts where the plan says "embed evidence". Per root AGENTS.md §Imperatives item 1: do not paraphrase.

- [ ] **Step 3: Do not commit until the user requests.** Per `agents/references/commit-policy.md`.

---

## Task 8: Open the PR (only on user request)

**Files:** None repo-side.

**Why this task exists:** Branch protection is active on `main` (`required-checks-gate`, `strict: true`, `required_conversation_resolution: true`, CodeRabbit `request_changes_workflow: true`). Direct push to `main` is blocked. PR goes through CodeRabbit + CI.

- [ ] **Step 1: Verify you are on a `feat/phase-0-c-*` branch, not `main`.**

```bash
git branch --show-current
```

- [ ] **Step 2: Push the branch.**

```bash
git push -u origin "$(git branch --show-current)"
```

- [ ] **Step 3: Open the PR via `gh`.**

```bash
gh pr create --title "feat(mod): Phase 0-C internal API observation (HP, position, zone, entities)" --body "$(cat <<'EOF'
## Summary
- Adds a structured `[LLMOfQud][state]` JSON line per player decision point alongside the Phase 0-B ASCII screen block.
- Game thread (`HandleEvent`) builds the state JSON via `SnapshotState.BuildStateJson`; render thread (`AfterRenderCallback`) emits `[screen]` (with new `display_mode` + `ascii_sources` metadata) and `[state]` LogInfo calls. Slots replaced by an atomic `PendingSnapshot` ref slot to keep `(turn, stateJson)` paired.
- Entity payload: `id (snapshot-local), name (ShortDisplayNameStripped), glyph (Render.RenderString[0]), pos, rel, distance, adjacent, hostile_to_player, hp`. Entity gate `Brain != null || HasPart("Combat") || baseHitpoints > 0`, visibility via `obj.IsVisible()`.
- Manual JSON-validity check on the latest single `[state]` line per ADR 0004.

## Evidence
- `build_log.txt`: `Compiling 3 files... Success :)` (no `COMPILER ERRORS`).
- `Player.log`: 22-turn run with `[screen] BEGIN` = `[screen] END` = `[state]` count, ERROR=0, latest `[state]` parses via `python3 -c "import sys, json; json.loads(sys.stdin.read())"`.
- Spot-check: visible NPC's glyph matches the `[screen]` cell at the entity's `pos`.
- Exit memo at `docs/memo/phase-0-c-exit-<date>.md`.

## Design source
- Plan: `docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md`.
- ADR 0002 — Phase 0-B render-callback request/emit pattern that this PR extends.
- ADR 0004 — C# unit-test infrastructure deferred to Phase 2a; manual JSON-validity is the substitute acceptance step.

## Spec
- `docs/architecture-v5.md:2800` (Phase 0-C scope), `:1787-1790` (game-queue routing), `:404-406` (visibility), `:1186-1198` / `:2426-2453` (canonical fields).
EOF
)"
```

- [ ] **Step 4: Wait for CI (`required-checks-gate`) and CodeRabbit. Do not merge until both green.**

---

## Self-review checklist (run before declaring this plan ready)

- **Spec coverage:** `docs/architecture-v5.md:2800` (Phase 0-C: Internal API observation — HP, position, zone, entities) → covered by Tasks 1-3 (implementation) + Tasks 4-6 (acceptance).
- **Q1 routing rule:** `:1787-1790` requires player/zone reads on the game thread. Task 2 Step 3 builds state JSON inside `HandleEvent`, not inside `AfterRenderCallback`. Render thread reads `Options.UseTiles` and the ScreenBuffer only.
- **Q2 framing:** Two LogInfo calls share `turn=N`; parser is told (in `[state]` line comment + Task 5/6 acceptance commands) not to assume adjacency.
- **Q3 entity payload:** Includes `hostile_to_player`. Filter `obj.IsVisible() && (Brain != null || HasPart("Combat") || baseHitpoints > 0)` per Task 1 Step 5 + Codex round-1 recommendation.
- **Q4 display mode:** `display_mode` field in `[state]` JSON + `mode=` token in `[screen] BEGIN` line + `ascii_sources` counts in `[screen] BEGIN` + per-snapshot.
- **Q5 / ADR 0004:** No C# unit-test infra introduced. Manual JSON-validity step (Task 5 Step 4 + Task 6 Step 4) parses the latest single `[state]` line.
- **Placeholder scan:** No "TBD" / "implement later" / "similar to Task N". Every code-change step shows the exact code or grep.
- **Type consistency:** `PendingSnapshot` (Task 1) is referenced in Tasks 2-3 with the same `Turn` / `StateJson` field names; `_pendingSnapshot` field name is consistent; `SnapshotAscii` out-params match between Task 3 Step 1 (definition) and Task 3 Step 2 (call site).
- **Hazards documented:** Mid-session reload still inherits the ADR 0003 closure; render-thread exception spam dedup still in 0-B "fix when it shows up" posture; ADR 0004 deferral re-open conditions enumerated and instructed to be checked at exit-memo time.

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`.

Which approach?
