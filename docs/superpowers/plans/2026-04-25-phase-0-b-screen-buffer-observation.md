# Phase 0-B: ScreenBuffer Observation (ASCII dump to log) — Implementation Plan

> **AMENDED 2026-04-25 per ADR 0002** (`docs/adr/0002-phase-0-b-render-callback-pivot.md`).
> The original design (synchronous read from `HandleEvent` via `TextConsole.GetScrapBuffer1`) was empirically falsified mid-implementation: `ConsoleChar.Copy` does NOT propagate `BackupChar`, so every buffer reachable from `HandleEvent` lost the tile-mode ASCII fallback. Pivoted to `XRLCore.RegisterAfterRenderCallback` + `Interlocked.Exchange` handshake, which `docs/architecture-v5.md:408-411` already sanctioned. Empirical record at `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md`. Affected sections below: **Architecture**, **Why we use `RegisterAfterRenderCallback`**, **Timing correctness**, **Pivot branch (executed)**, **Reference**, **File Structure**, **Task 2**, **Task 3**, **Task 9 PR body**.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one 80×25 ASCII snapshot of CoQ's current screen to `Player.log` at every player decision point (one per `BeginTakeActionEvent`), so Phase 0-C+ has a concrete observation primitive that the Python Brain will eventually consume over WebSocket.

**Architecture (amended per ADR 0002):**
- Subscribe `XRLCore.RegisterAfterRenderCallback(Action<XRLCore, ScreenBuffer>)` once per process from `IPlayerSystem.RegisterPlayer`, guarded by a static `_afterRenderRegistered` flag (`decompiled/XRL.Core/XRLCore.cs:624-626`).
- `LLMOfQudSystem.HandleEvent(BeginTakeActionEvent)` increments the per-instance turn counter and stores the new turn into a static slot via `Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount)`. It does NOT read or log the screen.
- The render callback fires post-`Zone.Render` and pre-`DrawBuffer` (`decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426`). It atomically captures-and-clears the slot via `Interlocked.Exchange`. When non-zero, it walks the source `ScreenBuffer` cell-by-cell reading `ConsoleChar.Char` then falling back to `BackupChar` then to space (`decompiled/XRL.World/Zone.cs:5411-5418` writes `BackupChar` for tile-mode cells; `decompiled/ConsoleLib.Console/ConsoleChar.cs:65,116,385-400` for the field, the `Char` property, and the `Copy` that drops `BackupChar`).
- Log via `MetricsManager.LogInfo(msg)` with `[LLMOfQud][screen] BEGIN turn=N w=W h=H\n<body>END turn=N` framing — a single `LogInfo` call per snapshot so Unity emits one log entry; the `INFO - ` prefix appears only on the BEGIN line.

**Why we use `RegisterAfterRenderCallback` (revised):**
- `Zone.Render` writes the ASCII glyph into `_Char`, then for tile cells copies it to `BackupChar` and zeros `_Char` (`decompiled/XRL.World/Zone.cs:5411-5418`). To recover the tile-mode glyph the snapshot must read `BackupChar`.
- `ConsoleChar.Copy` (`decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400`) does NOT include `BackupChar`. Therefore `TextConsole.GetScrapBuffer1(true)` (which calls `ScrapBuffer.Copy(CurrentBuffer)`) and `TextConsole.DrawBuffer(...)` (which calls `CurrentBuffer.Copy(Buffer)`) both strip `BackupChar` from any buffer reachable from a `HandleEvent` synchronous path. The original plan's `GetScrapBuffer1` design cannot deliver tile-mode ASCII.
- Only the **source `ScreenBuffer` passed to `Zone.Render`** retains `BackupChar`, and only between that call and the subsequent `DrawBuffer` copy. `RegisterAfterRenderCallback` hands us that buffer.
- `docs/architecture-v5.md:408-411` already sanctions this API as one of two ScreenBuffer-access mechanisms. The original plan was stricter than the spec; ADR 0002 brings them back in line.
- The hot-reload duplicate-registration hazard remains acknowledged but is gated by a static `_afterRenderRegistered` flag for the verified single-process model. Mid-session reload (Phase 0-A Task 7, deferred) is documented as a known unverified case.

**Timing correctness (amended):**
- `BeginTakeActionEvent` fires before player input (`decompiled/XRL.Core/ActionManager.cs:788` via `BeginTakeActionEvent.Check(Actor)`).
- The render callback fires after every `Zone.Render` call, which under normal play happens at least once between two consecutive `BeginTakeActionEvent` fires (the game must redraw to show the previous turn's result). The `Interlocked.Exchange` slot serializes them: the snapshot lands on the next render after the request is set.
- Multiple `BeginTakeActionEvent` fires between two renders collapse to the latest turn — acceptable for Phase 0-B observation cadence (one per LLM decision point, not strictly per game tick).
- This is treated as **empirically verified by Task 5 / Task 6**: 95-turn run, BEGIN=END=95, ERROR=0, three-cell spot-check PASS (see exit memo).

**Pivot branch (executed 2026-04-25):**
The original plan defined a Pivot branch only for "1-turn timing lag". The actual blocker was different — tile-mode rendering blanked snapshots because `BackupChar` was lost in every buffer copy. The pivot:
1. Recorded in `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` (raw evidence: turn 1, 5, 13 verbatim; BEGIN/END counts; build_log compile result; the `Zone.cs:5414` and `ConsoleChar.cs:385-400` citations).
2. Two Codex review iterations rejected (a) the `_Char → BackupChar` fallback alone (scrap buffer drops BackupChar) and (b) the `lock (BufferCS) { read CurrentBuffer }` direct-read (CurrentBuffer also drops BackupChar via `DrawBuffer`'s `CurrentBuffer.Copy(Buffer)`).
3. Final pivot to `XRLCore.RegisterAfterRenderCallback` per ADR 0002, validated empirically with `@`, walls, floors, NPCs, water, foliage all readable in `Player.log`.
4. Phase 0-A Task 7 (mid-session reload) remains deferred but is now a known-unverified case for this implementation, recorded in the exit memo.

**Scope boundaries:**
- In scope: local file I/O to `Player.log` via `MetricsManager.LogInfo`. One snapshot per player `BeginTakeActionEvent`. Manual in-game acceptance.
- Out of scope: WebSocket transport (Phase 1), Python Brain consumption, HP/position/zone/entity extraction (Phase 0-C), tile/color/foreground data (only the char layer matters for ASCII-map parity), throttling strategies (every-turn is fine; file size measured below).
- The log-volume envelope: 80×25=2000 chars + 25 newlines + two markers ≈ 2.05 KB per snapshot. 20 turns of manual acceptance ≈ 41 KB. 1000 turns ≈ 2 MB. Acceptable without throttling.

**Tech Stack:**
- Same as Phase 0-A. CoQ Roslyn compile, `mod/LLMOfQud/*.cs`, `Logger.buildLog` / `MetricsManager.LogInfo`, in-game verification against `build_log.txt` + `Player.log`. No new dependencies.
- Environment paths confirmed in `docs/memo/phase-0-a-exit-2026-04-23.md` (Freehold Games / CavesOfQud, **not** Kitfox Games / Caves of Qud):
  - `$MODS_DIR = $HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods`
  - `$COQ_SAVE_DIR = $HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG = $HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach (Phase 0-B continuation of Phase 0-A policy):**
- Manual in-game verification is still the acceptance surface. No external unit tests introduced yet; the snapshot helper is too game-API-coupled (`TextConsole`, `ScreenBuffer`, `ConsoleChar`) for a clean pure-logic extraction.
- Optional, non-blocking: a throwaway reference-compile probe against bundled `Assembly-CSharp.dll` in Task 2.5 proves our `TextConsole`/`ScreenBuffer`/`ConsoleChar` call sites compile before we depend on them. Skip unless the user asks.
- Game-as-harness automated smoke is still deferred to Phase 2a (`agents/references/testing-strategy.md`; memory `feedback_test_strategy.md` — harness-first philosophy, but 0-B has too little surface to justify the harness yet).

**Reference:**
- `docs/architecture-v5.md` (v5.9) — line 2799 (Phase 0-B scope), `:408-411` (ScreenBuffer access guidance, sanctioning `RegisterAfterRenderCallback`), §5 MOD Integration Strategy.
- `docs/adr/0002-phase-0-b-render-callback-pivot.md` — the design pivot ADR.
- `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` — empirical record of the BackupChar discovery and two Codex pivots.
- `docs/memo/phase-0-a-exit-2026-04-23.md` — env paths, Task 7 resolution, feed-forward.
- CoQ API (all citations must be re-verified before editing — rule: root AGENTS.md §Imperatives item 1):
  - `decompiled/XRL.Core/XRLCore.cs:624-626` — `RegisterAfterRenderCallback` (subscription API)
  - `decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426` — callback invocation sites (post-`Zone.Render`, pre-`DrawBuffer`)
  - `decompiled/XRL.World/Zone.cs:5411-5418` — `Zone.Render` writes `BackupChar` for tile-mode cells, zeros `_Char`
  - `decompiled/ConsoleLib.Console/ConsoleChar.cs:65` — `public char BackupChar`
  - `decompiled/ConsoleLib.Console/ConsoleChar.cs:67,116` — `_Char` field / `Char` property
  - `decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400` — `Copy` (drops `BackupChar`)
  - `decompiled/ConsoleLib.Console/ScreenBuffer.cs:21,79-100,291-308` — `Buffer[x,y]`, `Width`, `Height`, and `Copy` (per-cell `ConsoleChar.Copy`)
  - `decompiled/ConsoleLib.Console/TextConsole.cs:29,31,57-67,142-163` — `BufferCS`, `CurrentBuffer`, `GetScrapBuffer1`, `DrawBuffer` (the `CurrentBuffer.Copy(Buffer)` site that drops `BackupChar`)
  - `decompiled/XRL.Core/ActionManager.cs:788` — `BeginTakeActionEvent.Check(Actor)` dispatch
  - `decompiled/MetricsManager.cs:407-409` — `LogInfo` → Unity Player.log

---

## Prerequisites (one-time per session)

Before starting Task 1, confirm:

1. Phase 0-A is landed on `main` (commit `039df51 feat(mod): add Phase 0-A MOD skeleton with IPlayerSystem registration` or a successor). Verify `mod/LLMOfQud/LLMOfQudSystem.cs` contains the `RegisterPlayer` + `HandleEvent(BeginTakeActionEvent)` skeleton.
2. The symlink `$MODS_DIR/LLMOfQud` still resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling or missing, re-create per Phase 0-A Task 1 before proceeding.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. A clean CoQ save slot is available for the acceptance run (Task 5). Use the same Warden build as Phase 0-A if possible, or any playable character — 0-B does not constrain the build.

---

## File Structure (amended)

All C# source changes are within **one existing file** — `mod/LLMOfQud/LLMOfQudSystem.cs`. No new .cs files, no new namespaces, no new types.

**Files touched in this plan:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs` — add `using System.Text;`, `using System.Threading;`, `using ConsoleLib.Console;`, `using XRL.Core;`; add static fields `_afterRenderRegistered` and `_pendingSnapshotTurn`; add private helpers `SnapshotAscii(ScreenBuffer)` and `AfterRenderCallback(XRLCore, ScreenBuffer)`; extend `RegisterPlayer` to subscribe the callback once; extend `HandleEvent(BeginTakeActionEvent)` with the `Interlocked.Exchange` request line.
- Create: `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` — empirical record (created as part of the pivot, not the original plan).
- Create: `docs/adr/0002-phase-0-b-render-callback-pivot.md` + decision record under `docs/adr/decisions/`.
- Create: `docs/memo/phase-0-b-exit-<YYYY-MM-DD>.md` — exit memo, matching the shape of `docs/memo/phase-0-a-exit-2026-04-23.md`.

No new files under `mod/LLMOfQud/`, no manifest changes, no new symlinks. The Roslyn compile set grows by zero files — just the existing `LLMOfQudSystem.cs` gains ~80 lines.

---

## Task 1: Add the `SnapshotAscii` helper (pure, dependency-light)

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** Separates the "read and format the buffer" concern from the "log it at the right time" concern. Keeps `HandleEvent` short. The helper takes a `ScreenBuffer` so it is testable in principle (even though we're not writing an external unit test in 0-B).

- [ ] **Step 1: Open the existing file and add the `using` directive**

Current top of `mod/LLMOfQud/LLMOfQudSystem.cs`:

```csharp
using System;
using XRL;
using XRL.World;
```

Add `ConsoleLib.Console` (for `TextConsole`, `ScreenBuffer`, `ConsoleChar`) and `System.Text` (for `StringBuilder`):

```csharp
using System;
using System.Text;
using ConsoleLib.Console;
using XRL;
using XRL.World;
```

Citation for the added namespace: `decompiled/ConsoleLib.Console/TextConsole.cs:13` declares `namespace ConsoleLib.Console;`.

- [ ] **Step 2: Add the `SnapshotAscii` private static helper inside `class LLMOfQudSystem`**

Add this method as a sibling of `HandleEvent`:

```csharp
// Render a ScreenBuffer as an ASCII grid.
// decompiled/ConsoleLib.Console/ScreenBuffer.cs:21 (Buffer[,]), :79-100 (Width/Height)
// decompiled/ConsoleLib.Console/ConsoleChar.cs:67,116 (_Char / Char)
private static string SnapshotAscii(ScreenBuffer buf)
{
    if (buf == null)
    {
        return "<null-buffer>";
    }
    int w = buf.Width;
    int h = buf.Height;
    if (w <= 0 || h <= 0 || buf.Buffer == null)
    {
        return "<empty-buffer w=" + w + " h=" + h + ">";
    }
    StringBuilder sb = new StringBuilder(w * h + h);
    for (int y = 0; y < h; y++)
    {
        for (int x = 0; x < w; x++)
        {
            char c = buf.Buffer[x, y].Char;
            sb.Append(c == '\0' ? ' ' : c);
        }
        sb.Append('\n');
    }
    return sb.ToString();
}
```

Notes on the implementation:
- `buf.Buffer[x, y]` matches the field declaration at `decompiled/ConsoleLib.Console/ScreenBuffer.cs:21` (`public ConsoleChar[,] Buffer;`). The indexing order is `[x, y]` (column, row), confirmed by `decompiled/ConsoleLib.Console/ScreenBuffer.cs:140-145` (`if (x >= _Width) { ...; if (y >= _Height)`) and by the outer loop in `ScreenBuffer.cs:176-180` (`for (int i = 0; i < Height; i++) { for (int j = 0; j < Width; j++) { ...` — that loop uses the reverse order but still resolves `Buffer[j, i]` in the body: verify at the line you cite before landing).
- `ConsoleChar.Char` is a property wrapping `_Char` (`decompiled/ConsoleLib.Console/ConsoleChar.cs:116`). Reading the property is safe and matches how the game itself reads printable text.
- `'\0'` cells exist where a tile/graphical glyph is drawn — `ConsoleChar.Tile` setter explicitly zeros `Char` (`decompiled/ConsoleLib.Console/ConsoleChar.cs:109`). Substituting `' '` keeps the ASCII grid rectangular.
- Preallocated `StringBuilder` capacity `= w*h + h` avoids reallocation for the expected 80×25 layout (2025 chars).

- [ ] **Step 3: Save the file. Verify compile via CoQ build_log (Task 4 covers in-game; here just confirm syntax via editor)**

Command:

```bash
# Syntactic sanity: pattern-match the method exists and the braces balance
grep -c "private static string SnapshotAscii" mod/LLMOfQud/LLMOfQudSystem.cs
```

Expected: `1`

- [ ] **Step 4: Commit (only when user explicitly requests). Suggested message:**

```
feat(mod): add SnapshotAscii helper for Phase 0-B screen observation

Reads ScreenBuffer.Buffer[x,y].Char over Width x Height, substitutes
NUL for space, joins rows with \n. No caller yet — Task 2 wires it in.

Cites decompiled/ConsoleLib.Console/ScreenBuffer.cs:21,79-100 and
decompiled/ConsoleLib.Console/ConsoleChar.cs:116.
```

---

## Task 2: Add the `AfterRenderCallback` and BackupChar fallback (amended per ADR 0002)

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists (revised):** Isolates the **render-thread snapshot capture** step from the **game-thread request-and-counter** step. The callback receives the source `ScreenBuffer` from `XRLCore` — the only buffer in CoQ's pipeline that retains `BackupChar`, which `Zone.Render` uses to preserve the ASCII glyph for tile-mode cells (`decompiled/XRL.World/Zone.cs:5411-5418`). The original plan's `LogScreenSnapshot` + `GetScrapBuffer1` was rejected because both `ScrapBuffer.Copy` and `CurrentBuffer.Copy` route through `ConsoleChar.Copy` which strips `BackupChar` (`decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400`).

- [ ] **Step 1: Update `SnapshotAscii` to use the `Char → BackupChar → ' '` fallback chain**

Replace the inner cell read (Task 1 left it reading only `Char`):

```csharp
for (int x = 0; x < w; x++)
{
    ConsoleChar cell = buf.Buffer[x, y];
    char c = cell.Char;
    if (c == '\0') c = cell.BackupChar;
    sb.Append(c == '\0' ? ' ' : c);
}
```

The first `if` recovers tile-mode cells where `Zone.Render` zeroed `_Char` after copying it to `BackupChar`. The second `if` handles cells that genuinely never received any glyph.

- [ ] **Step 2: Add `using System.Threading;` and `using XRL.Core;` to the file's `using` block**

These bring `Interlocked` and `XRLCore` into scope.

- [ ] **Step 3: Add the static fields and the `AfterRenderCallback` helper**

Add inside `class LLMOfQudSystem`, as siblings of `_loadMarkerLogged` and `SnapshotAscii`:

```csharp
private static bool _afterRenderRegistered;

// Snapshot request handshake between HandleEvent (game thread) and
// AfterRenderCallback (render thread). Non-zero = "next render should
// snapshot this turn number". Interlocked.Exchange on both sides gives
// the full memory barrier; a plain int field is sufficient.
private static int _pendingSnapshotTurn;
```

```csharp
// Fires on the render thread after Zone.Render but before DrawBuffer.
// No-op unless HandleEvent requested a snapshot. Interlocked.Exchange
// atomically captures-and-clears the requested turn so concurrent
// BeginTakeActionEvent fires cannot double-log the same snapshot.
// decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)
private static void AfterRenderCallback(XRLCore core, ScreenBuffer buf)
{
    int turn = Interlocked.Exchange(ref _pendingSnapshotTurn, 0);
    if (turn == 0)
    {
        return;
    }
    try
    {
        int w = buf != null ? buf.Width : 0;
        int h = buf != null ? buf.Height : 0;
        string body = SnapshotAscii(buf);
        MetricsManager.LogInfo(
            "[LLMOfQud][screen] BEGIN turn=" + turn + " w=" + w + " h=" + h + "\n" +
            body +
            "[LLMOfQud][screen] END turn=" + turn);
    }
    catch (Exception ex)
    {
        // Never let observation kill the mod. Each exception is logged
        // verbatim (type + message) so transient and recurring failures
        // both surface in Player.log without crashing the game. Phase 0-B
        // accepted ERROR=0 over 95 turns; if log spam ever shows up here,
        // dedupe at that point rather than pre-engineering a HashSet now.
        MetricsManager.LogInfo(
            "[LLMOfQud][screen] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
    }
}
```

Notes:
- The callback fires every render frame. The `turn == 0` early return makes the no-op path effectively free.
- `Interlocked.Exchange` on both reader and writer side gives a full memory barrier without `volatile`. The single-writer-single-clearer pattern guarantees atomicity.
- Multiple `BeginTakeActionEvent` fires between two renders collapse to the latest turn — the older request is silently dropped. This is intentional: the LLM only needs the most recent decision-point snapshot.
- `try/catch` is the **only** place we add broad exception handling in this plan. The rationale: a throw on the render thread could poison the game's frame loop. Dropping a snapshot silently is fine; breaking rendering is not. This is a documented exception to AGENTS.md "no defensive validation".

- [ ] **Step 4: Confirm the surfaces**

```bash
grep -c "private static void AfterRenderCallback" mod/LLMOfQud/LLMOfQudSystem.cs
grep -c "_pendingSnapshotTurn"                    mod/LLMOfQud/LLMOfQudSystem.cs
grep -n "if (c == '\\\\0') c = cell.BackupChar"   mod/LLMOfQud/LLMOfQudSystem.cs
```

Expected: `1` for the first method, ≥ 3 for `_pendingSnapshotTurn` (declaration + Interlocked write + Interlocked read), one line match for the BackupChar fallback.

- [ ] **Step 5: Commit (if user requests). Suggested message:**

```
feat(mod): add AfterRenderCallback + BackupChar fallback for Phase 0-B

Subscribes once to XRLCore.RegisterAfterRenderCallback to capture the
source ScreenBuffer from Zone.Render before DrawBuffer's per-cell Copy
strips BackupChar. The callback consumes a turn slot set via
Interlocked.Exchange from HandleEvent (Task 3). Reads each cell with
Char -> BackupChar -> ' ' to recover tile-mode ASCII. Try/catch prevents
the render thread from being killed by snapshot failures.

Cites decompiled/XRL.Core/XRLCore.cs:624-626,2347-2351,
decompiled/XRL.World/Zone.cs:5411-5418, and
decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400.

See ADR 0002 for design rationale.
```

---

## Task 3: Wire the snapshot request and the callback subscription (amended per ADR 0002)

**Files:**
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`

**Why this task exists:** Two minimal edits land the new design in the game's event flow:
- `RegisterPlayer` subscribes the render callback once per process.
- `HandleEvent(BeginTakeActionEvent)` requests a snapshot for the next render via `Interlocked.Exchange`. It does NOT log the screen synchronously.

- [ ] **Step 1: Extend `RegisterPlayer` to subscribe the callback once**

Place the subscription inside the existing `if (!Registrar.IsUnregister && ...)` neighborhood. Use a separate `_afterRenderRegistered` static guard so the subscription survives any per-instance churn:

```csharp
public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar)
{
    if (!Registrar.IsUnregister && !_loadMarkerLogged)
    {
        _loadMarkerLogged = true;
        Logger.buildLog.Info(
            "[LLMOfQud] loaded v" + VERSION +
            " at " + DateTime.UtcNow.ToString("o"));
    }
    if (!Registrar.IsUnregister && !_afterRenderRegistered)
    {
        // XRLCore fires this after Zone.Render populates the source buffer
        // (including BackupChar for tile-mode cells) and BEFORE DrawBuffer
        // copies that source into CurrentBuffer through ConsoleChar.Copy,
        // which drops BackupChar. Source buffer is the only buffer from
        // which tile-mode ASCII glyphs are recoverable without mutating
        // game state.
        // decompiled/XRL.Core/XRLCore.cs:624-626 (RegisterAfterRenderCallback)
        // decompiled/XRL.Core/XRLCore.cs:2347-2351, 2380-2383, 2423-2426 (invocation sites)
        XRLCore.RegisterAfterRenderCallback(AfterRenderCallback);
        // Set the guard flag only after a successful Add so a hypothetical
        // throw inside RegisterAfterRenderCallback does not permanently
        // block future re-registration attempts.
        _afterRenderRegistered = true;
    }
    Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
    base.RegisterPlayer(Player, Registrar);
}
```

`_afterRenderRegistered` is static, so the callback list grows by exactly one entry per process. This gates (but does not solve) the duplicate-registration hazard the original plan flagged — Phase 0-A Task 7 closure remains the proper fix for mid-session reload.

- [ ] **Step 2: Replace `HandleEvent(BeginTakeActionEvent)` body with the request-flag form**

```csharp
public override bool HandleEvent(BeginTakeActionEvent E)
{
    _beginTurnCount++;
    // Ask the next render to snapshot. We cannot snapshot from here:
    // by the time HandleEvent runs, the only buffer we can reach
    // (TextConsole.CurrentBuffer) has already gone through
    // ScreenBuffer.Copy / ConsoleChar.Copy, which drops BackupChar.
    // decompiled/ConsoleLib.Console/TextConsole.cs:31 (CurrentBuffer)
    // decompiled/ConsoleLib.Console/TextConsole.cs:142-163 (DrawBuffer -> CurrentBuffer.Copy(Buffer))
    // decompiled/ConsoleLib.Console/ScreenBuffer.cs:291-308 (Copy dispatches per-cell ConsoleChar.Copy)
    // decompiled/ConsoleLib.Console/ConsoleChar.cs:385-400 (Copy omits BackupChar)
    Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount);
    if (_beginTurnCount % 10 == 0)
    {
        MetricsManager.LogInfo(
            "[LLMOfQud] begin_take_action count=" + _beginTurnCount);
    }
    return base.HandleEvent(E);
}
```

The `Interlocked.Exchange` write must come **after** the counter increment so the requested turn matches the counter the per-10-turns log will print. Order rule (unchanged from the original plan): `_beginTurnCount++` strictly first.

Do not change the existing per-10-turns counter line; Task 5 / Task 6 rely on its continuity with Phase 0-A's Session C evidence.

- [ ] **Step 3: Confirm the insertion points and ordering**

```bash
grep -n "RegisterAfterRenderCallback\|_afterRenderRegistered\|Interlocked.Exchange.*_pendingSnapshotTurn\|_beginTurnCount++\|begin_take_action count" mod/LLMOfQud/LLMOfQudSystem.cs
```

Expected (line numbers approximate):

```
RegisterAfterRenderCallback(AfterRenderCallback);  // inside RegisterPlayer
_afterRenderRegistered = true;                     // set AFTER successful registration (lockout-safe)
_beginTurnCount++;                                 // inside HandleEvent
Interlocked.Exchange(ref _pendingSnapshotTurn, _beginTurnCount);  // after the counter
```

The Interlocked write must appear after `_beginTurnCount++` and before the `if (_beginTurnCount % 10 == 0)` block.

- [ ] **Step 4: Commit (if user requests). Suggested message:**

```
feat(mod): wire AfterRenderCallback + Interlocked snapshot request (Phase 0-B)

RegisterPlayer subscribes XRLCore.RegisterAfterRenderCallback exactly
once per process via _afterRenderRegistered. HandleEvent requests the
next snapshot via Interlocked.Exchange instead of synchronous logging.
The callback (Task 2) consumes the slot atomically and writes one
LogInfo per snapshot. Preserves the every-10-turns counter log for
continuity with Phase 0-A acceptance.

See ADR 0002 for design rationale.
```

---

## Task 4: In-process Roslyn compile check via CoQ

**Files:** None. This task runs the game.

**Why this task exists:** CoQ compiles `.cs` files in-memory at launch (`decompiled/XRL/ModInfo.cs:757-823`). `build_log.txt` is authoritative for compile success. Before the acceptance run, prove the mod still compiles with the new helpers.

- [ ] **Step 1: Launch CoQ fresh** (fully quit and relaunch; do not toggle the mod from the Mods menu — the Phase 0-A Task 7 gap is still open).

- [ ] **Step 2: Without embarking yet, quit the game**

This is enough to exercise the Roslyn compile path (`ModManager.BuildMods()` runs during splash).

- [ ] **Step 3: Inspect `build_log.txt`**

```bash
tail -n 80 "$COQ_SAVE_DIR/build_log.txt" | grep -E "=== LLM OF QUD ===|Compiling \d+ files?\.\.\.|Success :\)|COMPILER ERRORS|\[LLMOfQud\]"
```

Expected output pattern (timestamps will differ):

```
[YYYY-MM-DDTHH:MM:SS] === LLM OF QUD ===
[YYYY-MM-DDTHH:MM:SS] Compiling 2 files...
[YYYY-MM-DDTHH:MM:SS] Success :)
[YYYY-MM-DDTHH:MM:SS] Defined symbol: MOD_LLMOFQUD
```

Critical: **no `COMPILER ERRORS` block** naming `LLMOfQudSystem.cs`. If one appears, capture the full block verbatim, stop, and fix the cited line before re-running.

- [ ] **Step 4: Record the CoQ build and timestamp for the exit memo**

```bash
grep -m 1 "BUILD_" "$COQ_SAVE_DIR/build_log.txt" | tail -1
```

Expected: something like `Defined symbol: BUILD_2_0_210` (or newer). Stash the value in your session notes for Task 6.

---

## Task 5: Acceptance run — one decision, spot-check one snapshot against the in-game display

**Files:** None. This task plays the game.

**Why this task exists:** The timing assumption (`CurrentBuffer` reflects what the player sees when `BeginTakeActionEvent` fires) is empirical. This task falsifies it or confirms it with a single decision point. A single spot-check is sufficient to prove the signal; the 20-turn volume check in Task 6 proves durability.

- [ ] **Step 1: Launch CoQ fresh, embark any character (reuse Phase 0-A's Warden if convenient). Do not move yet.**

- [ ] **Step 2: Before issuing any input, open the Player.log in a second terminal:**

```bash
tail -F "$PLAYER_LOG" | grep -E "INFO - \[LLMOfQud\]"
```

You should immediately see one snapshot being written when you first gain control (the first `BeginTakeActionEvent` on the player). Structure:

```
INFO - [LLMOfQud][screen] BEGIN turn=1 w=80 h=25
<80 chars>
<80 chars>
... (25 rows total) ...
<80 chars>
[LLMOfQud][screen] END turn=1
```

- [ ] **Step 3: Without moving, visually compare the ASCII grid in Player.log to the on-screen rendering**

Spot-check rule: for at least **three distinct cells** you can identify on screen (e.g., the player glyph `@`, a visible wall segment, an adjacent floor tile), verify the character at the corresponding `[x, y]` in the logged ASCII matches.

- Identify the player's on-screen position (CoQ's starting screen usually has `@` centered around row 12, col 40 — but do not assume; read it from the log).
- Identify one wall character (`#` or similar) adjacent.
- Identify one floor character (`.` or similar) adjacent.

All three must match. If any does **not** match, treat as potential timing lag (see "Pivot branch" in the header).

- [ ] **Step 4: If all three match, take exactly one action (press `.` to rest one turn) and verify a second snapshot appears with `turn=2`**

Expected: one new `BEGIN turn=2 ... END turn=2` block, and its contents differ from `turn=1` only in ways consistent with one game tick (message-log line at the top scrolls, ambient creatures may have moved).

- [ ] **Step 5: Decide acceptance**

**PASS condition:**
- Exactly one snapshot per player `BeginTakeActionEvent` (two so far: `turn=1` and `turn=2`).
- 25 rows of 80 chars each in each snapshot, with the `BEGIN`/`END` markers intact.
- The three-cell spot-check matches the on-screen rendering at the moment the snapshot fired.

**FAIL conditions and responses:**
- *Double-logged `turn=1`* → duplicate `HandleEvent` dispatch. Task 7 hazard has materialized even without mid-session toggle; stop and investigate `ApplyRegistrar`/`ApplyUnregistrar` symmetry.
- *Spot-check mismatch of the player's own glyph* by exactly one tile against the prior direction of movement → 1-turn timing lag. Take the **Pivot branch** (header). Do **not** continue.
- *Exception line* `[LLMOfQud][screen] ERROR turn=1 ...` → fix the cited exception class in `SnapshotAscii`/`LogScreenSnapshot` before continuing.

---

## Task 6: 20-turn durability run + manual volume check

**Files:** None. Plays the game.

**Why this task exists:** Catches regressions invisible to the single-turn spot-check: drift in log volume, missed turns, intermittent errors, accidental interactions with the existing `begin_take_action count=N` every-10-turns line.

- [ ] **Step 1: Continuing the Task 5 session, play 20 consecutive turns of any activity (rest, walk, whatever)**

Avoid opening menus that might block the player's `BeginTakeActionEvent` (e.g., inventory, wish). The goal is 20 clean player actions.

- [ ] **Step 2: Count snapshots in Player.log**

```bash
grep -c "INFO - \[LLMOfQud\]\[screen\] BEGIN" "$PLAYER_LOG"
grep -c "INFO - \[LLMOfQud\]\[screen\] END"   "$PLAYER_LOG"
```

Expected: both counts equal, and equal to the number of player turns elapsed since game launch (`turn=1` through `turn=N`). If BEGIN ≠ END, an exception interrupted the snapshot mid-write — inspect for `[LLMOfQud][screen] ERROR` lines.

- [ ] **Step 3: Verify the per-10-turns counter line is still present and co-located correctly**

```bash
grep "INFO - \[LLMOfQud\] begin_take_action count=" "$PLAYER_LOG" | tail -3
```

Expected: `count=10` and `count=20` present. The 0-A cadence is intact.

- [ ] **Step 4: Pick turn 10 and turn 20 and spot-check each**

For `turn=10` and `turn=20`, do the same three-cell spot-check as Task 5 against the state the player saw *at the moment of that decision*. You don't need to remember the exact screen — pick any three cells from the logged snapshot and confirm they're plausible for that zone (walls are `#`, floors are `.`, the player is `@` somewhere near the middle rows, etc.). Implausible runs of `\0` / non-printable chars, zero-width snapshots, or sudden transitions to all-spaces are failures.

- [ ] **Step 5: Measure log bulk**

```bash
wc -l "$PLAYER_LOG"
du -h  "$PLAYER_LOG"
```

For a 20-turn run: expect `BEGIN+25 rows+END` = 27 lines per snapshot × 20 = ~540 lines from the mod, plus whatever CoQ itself writes. Size ≈ 41 KB from the mod. If the file is dramatically larger (say > 5 MB), something is amplifying writes — investigate before moving on.

- [ ] **Step 6: Quit the game cleanly (main menu → Quit, not force-kill)**

This lets CoQ flush any buffered log. Then re-run the counts from Step 2 against the final file to confirm nothing was lost.

---

## Task 7: Mid-session reload check — **NOT PERFORMED IN PHASE 0-B**

**Rationale:** Phase 0-A's Task 7 (mid-session Mods-menu toggle) is still deferred per `docs/memo/phase-0-a-exit-2026-04-23.md` "Task 7 resolution". Phase 0-B does **not** close it. This task exists in the plan only to document why we're not doing it, so a future plan can pick it up without re-deriving the context.

- [ ] **Step 1: Record in the exit memo (Task 8) that Phase 0-B inherits Phase 0-A's Task 7 deferral.**

No actions. Skip to Task 8.

---

## Task 8: Write the Phase 0-B exit memo

**Files:**
- Create: `docs/memo/phase-0-b-exit-<YYYY-MM-DD>.md` (use the real date at write time, e.g., `phase-0-b-exit-2026-04-25.md`)

**Why this task exists:** Matches the Phase 0-A convention (`docs/memo/phase-0-a-exit-2026-04-23.md`) so Phase 0-C re-entry has a single place to find empirical truth about 0-B.

- [ ] **Step 1: Create the file with this shape**

Required sections (in order):

1. **Heading + status**
2. **Environment (empirically verified)** — CoQ build, OS, `$MODS_DIR`, `$COQ_SAVE_DIR`, `$PLAYER_LOG`. Copy from `docs/memo/phase-0-a-exit-2026-04-23.md` only if values are still current; otherwise re-measure and record the new values.
3. **Phase 0-B acceptance** — checked boxes referencing `build_log.txt` / `Player.log` evidence, embedded as code blocks with 3–5 lines of real output each.
4. **Timing-assumption verdict** — one line: "Task 5 spot-check PASS / FAIL + pivot branch taken? yes/no".
5. **Snapshot volume (20-turn run)** — BEGIN count, END count, bytes, any ERROR lines.
6. **Execution deviations from plan** — if any task was merged, skipped, or extended.
7. **Task 7 status** — restate that Phase 0-B inherits Phase 0-A's deferral; list the hot-reload scenarios still unverified.
8. **Feed-forward for Phase 0-C** — decompiled citations you will need for internal-API observation (HP, position, zone, entities). Include pointers only, no new work.
9. **Files modified / created in Phase 0-B** — exact list.

- [ ] **Step 2: Fill each section from the raw evidence captured in Tasks 4–6**

Do not paraphrase log output. Paste verbatim, then annotate. Rule: root AGENTS.md §Imperatives item 1 ("Verify, never guess").

- [ ] **Step 3: Do not commit until the user requests. Per root AGENTS.md §Imperatives item 5.**

---

## Task 9: Open the PR (only on user request)

**Files:** None repo-side.

**Why this task exists:** Branch protection is active on `main` (`required-checks-gate`, `strict: true`, `required_conversation_resolution: true`, CodeRabbit `request_changes_workflow: true` — see `docs/ci-branch-protection.md`). Direct push to `main` is blocked. PRs go through CodeRabbit and CI.

- [ ] **Step 1: Verify you are on `feat/phase-0-b-*` (or similar) branch, not `main`**

```bash
git branch --show-current
```

Expected: a branch name starting with `feat/phase-0-b-`, not `main`.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin "$(git branch --show-current)"
```

- [ ] **Step 3: Open the PR via `gh`**

```bash
gh pr create --title "feat(mod): Phase 0-B ScreenBuffer ASCII observation" --body "$(cat <<'EOF'
## Summary
- Adds 80×25 ASCII snapshot of CoQ's screen to `Player.log` once per player `BeginTakeActionEvent`.
- Subscribes `XRLCore.RegisterAfterRenderCallback` once (guarded by static flag); the callback reads `Zone.Render`'s source `ScreenBuffer` with `Char → BackupChar → ' '` fallback to recover tile-mode ASCII glyphs.
- `HandleEvent` requests snapshots via `Interlocked.Exchange` on a shared int slot; no synchronous read on the game thread.

## Evidence
- `build_log.txt`: Compile success, no `COMPILER ERRORS`.
- `Player.log`: 95-turn run with BEGIN=END=95, ERROR=0; three-cell spot-check (`@`, wall, floor) PASS in tile mode.
- Empirical record at `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` (BackupChar discovery + two Codex review pivots).
- Exit memo at `docs/memo/phase-0-b-exit-<date>.md`.

## Design pivot
Original plan's `GetScrapBuffer1`-from-`HandleEvent` design was empirically falsified mid-implementation: `ConsoleChar.Copy` does not propagate `BackupChar`, so every buffer reachable from `HandleEvent` lost the tile-mode fallback. ADR 0002 (`docs/adr/0002-phase-0-b-render-callback-pivot.md`) records the pivot to `RegisterAfterRenderCallback`, which `docs/architecture-v5.md:408-411` already sanctioned.

## Plan
- `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md` (amended per ADR 0002).

## Task 7 status
Phase 0-B inherits Phase 0-A's deferral. The `_afterRenderRegistered` static flag prevents duplicate registration within one process; mid-session reload remains a known unverified case.
EOF
)"
```

- [ ] **Step 4: Wait for CI (`required-checks-gate`) and CodeRabbit. Do not merge until both green.**

---

## Self-review checklist (ran before finalizing the plan)

- Spec coverage: `docs/architecture-v5.md:2799` ("0-B: ScreenBuffer observation (ASCII map dump to log)") → covered by Tasks 1–3 (implementation) + Tasks 4–6 (acceptance against the same `Player.log` gate Phase 0-A used).
- Placeholder scan: no "TBD"/"implement later"/"similar to Task N"; every code-change step shows the exact code.
- Type consistency (amended per ADR 0002): `SnapshotAscii(ScreenBuffer)` → `string` and `AfterRenderCallback(XRLCore, ScreenBuffer)` → `void` are used consistently across Tasks 1–3; `_beginTurnCount` matches the existing Phase 0-A field name (`mod/LLMOfQud/LLMOfQudSystem.cs:14`); the new static fields `_afterRenderRegistered` and `_pendingSnapshotTurn` are referenced in Tasks 2–3 with the same names.
- Hazards accounted for (amended per ADR 0002): Phase 0-A Task 7 hot-reload hazard is acknowledged, not eliminated — `_afterRenderRegistered` gates duplicate registration within one process but mid-session reload remains unverified, recorded in `docs/memo/phase-0-a-exit-2026-04-23.md` and the Phase 0-B exit memo. Timing assumption treated as empirical (95-turn run with three-cell spot-check PASS in lieu of the original Pivot-branch fallback). Exception-safety inside `AfterRenderCallback` is the one documented exception to the "no defensive validation" rule — a throw on the render thread could poison the game's frame loop — with rationale cited inline.

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute in this session with checkpoints.

Which approach?
