# Phase 0-B Exit Memo (2026-04-25)

## Status

Phase 0-B (`docs/architecture-v5.md:2799` — "ScreenBuffer observation, ASCII map dump to log") **PASS**. Implementation deviated from the original plan via ADR 0002 (`docs/adr/0002-phase-0-b-render-callback-pivot.md`) due to an empirical blocker discovered mid-implementation. The frozen architecture-v5 spec (`:408-411`) was not changed; only the Phase 0-B plan was amended to align with it.

## Environment (empirically verified 2026-04-25)

| Variable | Value |
|---|---|
| OS | macOS Darwin 25.4.0 (Apple Silicon) |
| `$MODS_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods` |
| `$COQ_SAVE_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud` |
| `$PLAYER_LOG` | `$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log` |
| Mod symlink | `$MODS_DIR/LLMOfQud → ~/Dev/llm-of-qud/mod/LLMOfQud` (inherited from Phase 0-A) |
| Mod display | LLM of Qud (manifest unchanged, `VERSION = "0.0.1"`) |
| Verified CoQ launch | 2026-04-25 08:38:58 local (build_log timestamp) |

## Phase 0-B acceptance

### Compile (build_log.txt)

```
[2026-04-25T08:38:58] === LLM OF QUD ===
[2026-04-25T08:38:58] Compiling 2 files...
[2026-04-25T08:38:59] Success :)
[2026-04-25T08:39:05] [LLMOfQud] loaded v0.0.1 at 2026-04-24T23:39:05.5115060Z
```

Two `.cs` files compiled clean. The load marker (Phase 0-A's `Logger.buildLog.Info`) confirms `IPlayerSystem.RegisterPlayer` fired exactly once.

### Snapshot framing (Player.log)

| Counter | Value |
|---|---|
| `[LLMOfQud][screen] BEGIN turn=` | 95 |
| `[LLMOfQud][screen] END turn=` | 95 |
| `[LLMOfQud][screen] ERROR turn=` | 0 |
| `INFO - [LLMOfQud] begin_take_action count=` | 9 (turns 10, 20, …, 90) |
| Total Player.log size | 242,147 bytes / 2,808 lines |

BEGIN/END equal and matching the played turn count. Zero render-thread exceptions over the full session. The per-10-turns counter line from Phase 0-A is intact, so 0-A acceptance correlation holds.

### Three-cell spot-check (turn=30, verbatim)

`Player.log` lines 978–1004 (excerpt of representative rows):

```
INFO - [LLMOfQud][screen] BEGIN turn=30 w=80 h=25
...
úúúúúú`,,.'úú..,ú``,.,'.'`.,,`××××,'úúúúú.'.×Ø××,.ú.,×                          
``'`.úúúúúúú..,'ú'.',,..'.,.'..``,'`úúúú``,',..'`,ú.'× ×    ú.×                 
.,`..`.'ú```,..,ú'.'.'.'.'..''×  ×,ùúúúúú`.,,,,...ú.`'úùúúúúú,×           ..,,.,
.'',,'ùúúù=`.,.`úú``,..'..'`,×   ×`úúúúú`...`,úúúúúúúúú',..'úú×      ..',.      
           ±'@..`úúúú.`.''``,×   +.úúúúúúúúúúúú.ôô'..ôôôôô.'.'úúú,,'Ø           
           ±±''.,.,.úú.,`,'.,××  ×,úúúúúú`..ô,ôôôôôôôôôôôôôô.''.úú.ùúããØ        
            ±...'.`úúúúú,``'××××`.úúúú`,.ôôôôôôôôôôô. ~ôô'`..,'.úúú		þØ       
            ±`.ôôô'.`..'úú.'.,`'.`'úúúú,'ôôôôô ~ ôô÷~~~ôôô,.,,`'.'=úååØ        
...
[LLMOfQud][screen] END turn=30
```

Spot-check:

- **Player `@`**: line 996 column 12 (Joppa map, snapped to a wall edge). Visible.
- **Wall (`±`)**: lines 996–1000 column 11 (vertical wall segment). Visible.
- **Floor / vegetation (`ú`, `ô`)**: throughout. Visible.

Bonus glyphs recovered (CP437): `Ø`, `þ`, `ã`, `å` (NPCs), `=` (door), `+` (closed door), `~` (water), `ô` (forest tile), `±` (statue/monument). All present even though CoQ was running in **tile graphics mode** (verified by direct in-game viewing during the run). This confirms the `Char → BackupChar → ' '` fallback is recovering the ASCII glyph that `Zone.Render` stashed in `BackupChar` before zeroing `_Char` for tile rendering (`decompiled/XRL.World/Zone.cs:5411-5418`).

## Timing-assumption verdict

The original plan expected the spot-check to falsify a "1-turn timing lag" pivot trigger. The actual blocker was a **rendering-mode** issue (tile mode + `BackupChar` not propagated through `ScreenBuffer.Copy`), not timing. The pivot recorded in `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` resolved it via `XRLCore.RegisterAfterRenderCallback`. After the pivot, the original timing assumption holds: the snapshot reflects the state the player saw at the moment of `BeginTakeActionEvent`. PASS, no 1-turn lag observed.

## Snapshot volume (95-turn run)

| Metric | Value |
|---|---|
| Total turns observed | 95 |
| BEGIN markers | 95 |
| END markers | 95 |
| ERROR markers | 0 |
| Bytes/snapshot | ≈ 2,050 (80×25 + newlines + framing) |
| Mod log volume | ≈ 95 × 2.05 KB = ≈ 195 KB |
| Player.log total | 242 KB (95 turn snapshots + per-10 counters + Unity engine logs) |

Linear scaling: 1,000 turns ≈ 2 MB. No throttling needed for Phase 0-B. Phase 0-C+ (WebSocket transport) can choose its own framing — capture point is decoupled.

## Execution deviations from plan

1. **Pivot from `GetScrapBuffer1` to `RegisterAfterRenderCallback`** (ADR 0002). Caused by the empirical discovery that `ConsoleChar.Copy` does not propagate `BackupChar`, blanking tile-mode cells. Two Codex review iterations falsified the intermediate "lock + read CurrentBuffer" attempt (`CurrentBuffer` is itself a copy via `DrawBuffer`'s `CurrentBuffer.Copy(Buffer)`). The final design takes the source buffer at the post-`Zone.Render`, pre-`DrawBuffer` callback site.
2. **Task 1 unchanged** (SnapshotAscii pure helper). **Task 2 amended** to add the BackupChar fallback and replace `LogScreenSnapshot(GetScrapBuffer1)` with `AfterRenderCallback`. **Task 3 amended** to add the `RegisterAfterRenderCallback` subscription and replace synchronous logging with an `Interlocked.Exchange` request.
3. **New file added by the pivot**: `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` (empirical record). **New ADR**: `docs/adr/0002-phase-0-b-render-callback-pivot.md` + decision record under `docs/adr/decisions/`.
4. **Task 5 / Task 6 collapsed into one continuous 95-turn session**. Original plan's 1-turn spot-check (Task 5) and 20-turn durability (Task 6) were merged because the user's verification run naturally covered both gates. PASS recorded in this memo.
5. **`MetricsManager.LogInfo` framing observation**: a single `LogInfo` call emits one Unity log entry. The `INFO - ` prefix appears only on the first line; subsequent lines (body + END marker) are emitted as continuation text without the prefix. `grep "INFO - \[LLMOfQud\]\[screen\] BEGIN"` finds 95; `grep "\[LLMOfQud\]\[screen\] END"` finds 95. Plain raw greps work; an `INFO - `–prefixed grep for END would return zero. This is documented here so Phase 0-C log parsers don't get tripped up.

## Task 7 status

Deferred from Phase 0-A. Phase 0-B inherits this deferral.

The `_afterRenderRegistered` static flag prevents duplicate callback registration **within a single process**. Mid-session mod toggle / reload behavior is unverified for both:

1. The original Phase 0-A `IPlayerSystem` lifecycle (the gap recorded in `docs/memo/phase-0-a-exit-2026-04-23.md`).
2. The new `XRLCore.RegisterAfterRenderCallback` subscription (`AfterRenderCallbacks` is `List<Action<...>>` populated by `.Add` with no `Contains()` guard, `decompiled/XRL.Core/XRLCore.cs:624-626`).

Closing Task 7 properly will require a separate plan that addresses both gaps. The current implementation is correct for the **fresh-launch model** documented and tested here.

## Feed-forward for Phase 0-C

Phase 0-C (per `docs/architecture-v5.md`) extends observation to internal-API extraction (HP, position, zone, entities). Decompiled citations the next plan will need:

| Concern | Citation |
|---|---|
| Player HP / status | `decompiled/XRL.World/GameObject.cs` (Statistics, hitpoints helper); the helper used by Sidebar lives near `decompiled/XRL.UI/Sidebar.cs` |
| Player position | `The.Player.CurrentCell` → `Cell.X / Y / ParentZone` (`decompiled/XRL.World/Cell.cs`) |
| Active zone | `The.Game.ZoneManager.ActiveZone` (`decompiled/XRL/ZoneManager.cs`); zone ID via `Zone.ZoneID` |
| Visible entities | `Zone.GetObjects()` returns ALL objects regardless of visibility (`decompiled/XRL.World/Zone.cs:1982`); MUST filter by `The.Player.CanSee(obj)` or `obj.IsVisible()` per spec `:404-406` |
| Capture point | Reuse this phase's `AfterRenderCallback` — it's invoked after `Zone.Render`, when visibility / lighting / explored maps are coherent for the current frame. The Phase 0-C extraction can sit alongside the current snapshot logic and pull from `core` / `The.Player` directly during the same callback. |
| Transport | Phase 1 will introduce WebSocket. Phase 0-C should still write to `Player.log` so the harness-first acceptance loop continues to work without the Brain. |

Open design questions for Phase 0-C planning (not for this exit memo):

- Whether `BeginTakeActionEvent` (game thread) requesting and `AfterRenderCallback` (render thread) emitting still composes when the snapshot grows from "string" to "structured frame with HP / entities / map". A queue may replace the single-int `Interlocked.Exchange` slot.
- Whether the grouping (one `LogInfo` call per snapshot) survives or needs structured multi-call framing for Brain parsers.
- Whether to expose tile mode awareness (`BackupChar`-fallback usage) in the structured frame as a metadata field.

## Files modified / created in Phase 0-B

| Path | Change |
|---|---|
| `mod/LLMOfQud/LLMOfQudSystem.cs` | +80 lines (using `System.Text` / `System.Threading` / `ConsoleLib.Console` / `XRL.Core`; static fields `_afterRenderRegistered` and `_pendingSnapshotTurn`; helpers `SnapshotAscii` and `AfterRenderCallback`; extended `RegisterPlayer` and `HandleEvent`). |
| `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md` | Created at the start of Phase 0-B; **amended in place per ADR 0002** to align with the post-pivot design. |
| `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md` | Created during the pivot. Empirical record + design rationale for the new approach. |
| `docs/adr/0002-phase-0-b-render-callback-pivot.md` | Created. Status Accepted (2026-04-25). |
| `docs/adr/decisions/2026-04-24-phase-0-b-observation-pivot-to-afterrendercallback.md` | Created via `scripts/create_adr_decision.py`. |
| `docs/adr/decision-log.md` | Updated index with the new entry (script-driven). |
| `docs/memo/phase-0-b-exit-2026-04-25.md` | This file. |

No commits made during Phase 0-B. Per AGENTS.md §Imperatives item 5, commit + PR will only happen on explicit user request.

## References

- `docs/architecture-v5.md` (v5.9) — `:2799` (Phase 0-B scope), `:408-411` (ScreenBuffer access)
- `docs/adr/0002-phase-0-b-render-callback-pivot.md`
- `docs/superpowers/plans/2026-04-25-phase-0-b-screen-buffer-observation.md` (amended)
- `docs/memo/phase-0-b-tile-mode-finding-2026-04-25.md`
- `docs/memo/phase-0-a-exit-2026-04-23.md` — Phase 0-A exit, env paths, Task 7 deferral
- `mod/LLMOfQud/LLMOfQudSystem.cs` — implementation
- CoQ APIs (verify before re-citing): `decompiled/XRL.Core/XRLCore.cs:624-626, 2347-2351, 2380-2383, 2423-2426`; `decompiled/XRL.World/Zone.cs:5388-5439`; `decompiled/ConsoleLib.Console/ConsoleChar.cs:65,67,116,278-299,385-400`; `decompiled/ConsoleLib.Console/ScreenBuffer.cs:21,79-100,291-308`; `decompiled/ConsoleLib.Console/TextConsole.cs:29,31,57-67,142-163`; `decompiled/MetricsManager.cs:407-409`
