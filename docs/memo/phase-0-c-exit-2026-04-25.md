# Phase 0-C Exit Memo (2026-04-25)

## Status

Phase 0-C (`docs/architecture-v5.md:2799-2816` — internal-API observation: HP, position, zone, visible entities) **PASS**. Tasks 1-6 complete. Implementation followed the approved plan (`docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md`) without mid-implementation deviation; the only governance addition was ADR 0004 (deferral of C# unit-test infrastructure for `AppendJsonString` to Phase 2a). Frozen architecture-v5 spec untouched.

## Environment (empirically verified 2026-04-25)

| Variable | Value |
|---|---|
| OS | macOS Darwin 25.4.0 (Apple Silicon) |
| `$MODS_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods` |
| `$COQ_SAVE_DIR` | `$HOME/Library/Application Support/Freehold Games/CavesOfQud` |
| `$PLAYER_LOG` | `$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log` |
| Mod symlink | `$MODS_DIR/LLMOfQud → ~/Dev/llm-of-qud/mod/LLMOfQud` (inherited, unchanged) |
| Mod display | LLM of Qud (manifest unchanged, `VERSION = "0.0.1"`) |
| Verified CoQ launch | 2026-04-25 14:37:22 local / 05:37:43 UTC (build_log + load marker) |
| Final load order | `1: LLMOfQud` (QudJP disabled in this run — single-mod observation) |
| ModAssembly path | `$COQ_SAVE_DIR/ModAssemblies/LLMOfQud.dll` (Roslyn output, MOD_LLMOFQUD symbol defined) |

## Phase 0-C acceptance (`bash /tmp/phase-0-c-acceptance.sh` — 14 PASS / 0 FAIL / 0 WARN)

### Task 4 — Roslyn compile probe (build_log.txt)

```
[2026-04-25T14:37:22] === LLM OF QUD ===
[2026-04-25T14:37:22] Compiling 3 files...
[2026-04-25T14:37:22] Success :)
[2026-04-25T14:37:22] Location: …/ModAssemblies/LLMOfQud.dll
[2026-04-25T14:37:22] Defined symbol: MOD_LLMOFQUD
[2026-04-25T14:37:22] ==== FINAL LOAD ORDER ====
[2026-04-25T14:37:22] 1: LLMOfQud
[2026-04-25T14:37:43] [LLMOfQud] loaded v0.0.1 at 2026-04-25T05:37:43.8290570Z
```

`Compiling 3 files...` confirms `SnapshotState.cs` was picked up (Phase 0-B compiled 2). `Success :)` and the absence of any `COMPILER ERRORS` block confirm clean Roslyn output. The post-Bootstrap delay between compile (14:37:22) and load marker (14:37:43, ≈21 s) is the in-game embark latency, not a compile issue.

### Task 5 / Task 6 — framing counts and JSON validity (Player.log)

| Counter | Value |
|---|---|
| `INFO - [LLMOfQud][screen] BEGIN turn=` | 110 |
| `^[LLMOfQud][screen] END turn=` (continuation, no `INFO - ` prefix) | 110 |
| `INFO - [LLMOfQud][state] {` | 110 |
| `INFO - [LLMOfQud][screen] ERROR turn=` | 0 |
| `INFO - [LLMOfQud][state] ERROR turn=` | 0 |
| `INFO - [LLMOfQud] begin_take_action count=` (every-10) | 11 (turns 10, 20, …, 110) |
| Total Player.log size | 2,056,190 bytes / 3,323 lines |

`BEGIN == END == [state] == 110`. Zero render-thread or game-thread exceptions over the full run. The Phase 0-A per-10-turns counter survives intact through the Phase 0-B + 0-C re-entries of `HandleEvent`, so 0-A correlation holds.

### ADR 0004 acceptance step — manual JSON validity on the latest [state] line

`turn=110` `[state]` line parses cleanly via `python3 -c "import sys, json; json.loads(sys.stdin.read())"`. Top-level keys and types:

```
{"turn": int, "player": dict, "pos": dict, "display_mode": str, "entities": list}
turn=110
display_mode=tile
entities count=56
player.hp=[20, 20]
pos={"x": 7, "y": 9, "zone": "JoppaWorld.11.22.0.0.10"}
```

This is the gate documented in `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` (Acceptance Step). All Phase 0-C reopen triggers in ADR 0004 evaluated negative for this run (no JSON-invalid line, no Phase 1 WebSocket boundary yet, no `AppendJsonString` regression).

### First-snapshot evidence (turn=1)

```
INFO - [LLMOfQud][screen] BEGIN turn=1 w=80 h=25 mode=tile src=char:2,backup:1998,blank:0
…ASCII grid…
[LLMOfQud][screen] END turn=1
INFO - [LLMOfQud][state] {"turn":1,"player":{…,"hp":[20,20]},"pos":{"x":79,"y":10,"zone":"JoppaWorld.11.22.0.1.10"},"display_mode":"tile","entities":[{"id":"e1","name":"watervine","glyph":"ô","pos":{…},"rel":{"dx":-69,"dy":-10},"distance":69,"adjacent":false,"hostile_to_player":false,"hp":[25,25]}, …]}
```

- `mode=tile` matches `display_mode=tile` in the structured frame (cross-frame consistency).
- `src=char:2,backup:1998,blank:0` confirms the BackupChar fallback recovers ≥99 % of cells in tile mode (the 2 raw `char` cells are HUD chrome, not map cells), echoing the Phase 0-B finding.
- `entities[0]` is a `watervine` plant at `distance=69` — the visible-and-creature-like gate is permissive on the embark zone. The schema reports `name` / `glyph` / `pos` / `rel` (player-relative) / `distance` / `adjacent` / `hostile_to_player` / `hp` exactly as planned.

### Last-snapshot evidence (turn=110)

```
INFO - [LLMOfQud][screen] BEGIN turn=110 w=80 h=25 mode=tile src=char:0,backup:2000,blank:0
```

`char:0,backup:2000` for the final turn — the camera has scrolled into a region with no HUD letters in the captured rectangle, exercising the all-BackupChar branch of `SnapshotAscii`. Combined with turn=1's `char:2,backup:1998`, both branches of the Char/BackupChar fallback got real coverage during the run.

## Snapshot volume (110-turn run)

| Metric | Value |
|---|---|
| Total turns observed | 110 |
| BEGIN markers | 110 |
| END markers | 110 |
| `[state]` lines | 110 |
| ERROR markers | 0 |
| Total Player.log bytes | 2,056,190 |
| Bytes / snapshot (incl. ASCII grid + state JSON) | ≈ 18.7 KB |
| Bytes / `[state]` line (turn=110, 56 entities) | ≈ 5.0 KB |

The per-snapshot bytes increased from Phase 0-B's ≈ 2.05 KB to ≈ 18.7 KB. The delta is dominated by the new `[state]` JSON line (≈ 5 KB at 56 entities; turn=1 with 130 entities was larger) plus the wider `[screen] BEGIN` header. Linear projection: 1,000 turns ≈ 19 MB. Phase 1 WebSocket transport will replace `Player.log` as the primary sink, so this is a soft ceiling, not a deployment constraint.

## Execution deviations from plan

None at code level. Tasks 1-6 executed as written in `docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md`. Governance additions made during planning, not deviations:

1. **ADR 0003** (`docs/adr/0003-phase-0-a-task-7-closure-by-design.md`) closed the lingering Phase 0-A Task 7 (mid-session Mods-menu reload) by operational scope, since the streaming runtime fixes mods at launch. Four re-open triggers documented.
2. **ADR 0004** (`docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md`) deferred C# unit-test infrastructure for `AppendJsonString` to Phase 2a. The acceptance gate was substituted with the manual single-line `json.loads` check above. Six re-open triggers documented; the most likely is Phase 1 WebSocket boundary (`docs/architecture-v5.md:2399-2419`) or a single attributable JSON-invalidity surfacing in a future run.
3. **Push gate friction** caused by multi-ADR rollups in a single push. Worked around with a rollup decision record (`docs/adr/decisions/2026-04-25-phase-0-c-readiness-rollup.md`) per the existing `2026-04-24-repo-bootstrap-push-consolidation.md` precedent. Upstream fix tracked separately (issue against `ToaruPen/ToaruPen_Template`).

## Notes for downstream consumers

1. **Two-LogInfo framing**: every snapshot emits exactly two top-level `MetricsManager.LogInfo` calls — one `[screen]` block (multi-line: `BEGIN` + grid + `END`) and one `[state]` line. Parsers MUST NOT assume adjacency: other CoQ subsystems can interleave `INFO - …` lines between them. Correlate by `turn=N`.
2. **`INFO - ` prefix only on the first line** of a multi-line `LogInfo`. The `[screen] END turn=N` line is a continuation of the BEGIN call's emission and therefore appears as a bare `[LLMOfQud][screen] END turn=N` (no `INFO - `). The acceptance script anchors on `^[LLMOfQud][screen] END` for this reason. Do not add an `INFO - ` requirement to END parsers.
3. **Single-mod run**: this acceptance was performed with QudJP disabled (final load order `1: LLMOfQud`). Phase 0-B's QudJP coexistence claim is from a separate session; we have not re-verified the multi-mod path under Phase 0-C framing. If a future phase depends on multi-mod observation, re-verify there.
4. **Game-thread vs render-thread split** is intact: state JSON build runs in `HandleEvent(BeginTakeActionEvent)` per spec `:1787-1790`. The render thread only consumes a `PendingSnapshot` snapshot via `Interlocked.Exchange<PendingSnapshot>`. Tearing risk is therefore confined to the JSON-build path itself, which only reads game-state on the game thread.
5. **`PendingSnapshot` ref slot** intentionally collapses the (turn, JSON) pair into one atomic publish. Any future field added to the snapshot must be threaded through this object, not added as a parallel static slot.
6. **Visibility filter**: entity gate is `IsVisible() && (Brain != null || HasPart("Combat") || baseHitpoints > 0)`. This is permissive on Joppa (e.g. watervine passes via `baseHitpoints > 0`). If Phase 0-D restricts to "agents you can interact with this turn", tighten the gate there, not here.

## Feed-forward for Phase 0-D

Phase 0-D (per `docs/architecture-v5.md` Phase Plan) extends observation to `RuntimeCapabilityProfile`: mutations, abilities, cooldowns, status effects, equipment. Decompiled citations the next plan will likely need (verify before re-citing):

| Concern | Suggested starting point |
|---|---|
| Active mutations | `decompiled/XRL.World/MutationsCollection.cs` (collection on Player) |
| Abilities + cooldowns | `decompiled/XRL.World/ActivatedAbilityEntry.cs` + `ActivatedAbilities` part |
| Status effects | `decompiled/XRL.World.Effects/*` (`Effect` base + collection) |
| Equipment slots | `decompiled/XRL.World.Parts/Body.cs` + `BodyPart` slots; `Equipped` field per slot |
| Inventory | `decompiled/XRL.World.Parts/Inventory.cs` |
| Player capability summary | Sidebar / character sheet UI in `decompiled/XRL.UI/` (treat as reference, not API) |

Open design questions for Phase 0-D planning (not for this exit memo):

- Whether `RuntimeCapabilityProfile` extends the existing `[state]` line or moves to a third `[caps]` line. Risk: `[state]` payload growth (turn=1 already > 7 KB at 130 entities). If the profile is large/static, separate it.
- Whether to emit the profile every turn (large, redundant most turns) or only when a `MutationsRecalculatedEvent` / equivalent trigger fires.
- Whether the Brain should diff on the harness side (cheap, language-model-friendly) or the mod side (cheaper bandwidth, more code).

## Open hazards (still tracked from earlier phases)

- **Render-thread exception spam dedup**: zero ERROR lines over 95 turns (Phase 0-B) + 110 turns (Phase 0-C). Continue to defer dedup until/unless errors actually appear.
- **Multi-mod coexistence under Phase 0-C framing**: untested as noted above. Not a Phase 0-C blocker; revisit when Phase 0-D or a multi-mod stream session needs it.

## Files modified / created in Phase 0-C

| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Created (~210 lines). `PendingSnapshot` class + `SnapshotState` static helpers (`AppendJsonString` with RFC 8259 escape table incl. U+2028/U+2029, `AppendAsciiSourcesJson`, `AppendEntity`, `BuildStateJson`). |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Modified. Added `using XRL.UI;`; replaced `_pendingSnapshotTurn` int with `_pendingSnapshot` ref slot; `HandleEvent` now builds state JSON on the game thread (with try/catch sentinel); `SnapshotAscii` now returns `out int charCount, backupCount, blankCount`; `AfterRenderCallback` emits two LogInfo calls (`[screen]` BEGIN augmented with `mode=` + `src=…`, plus `[state] {…}`). |
| `docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md` | Created at the start of Phase 0-C. Reviewed across Codex Q1-Q5 + 2 plan-review passes before implementation. |
| `docs/adr/0003-phase-0-a-task-7-closure-by-design.md` | Created. Closes Phase 0-A Task 7 by operational scope. |
| `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` | Created. Defers C# unit-test infra to Phase 2a; substitutes manual JSON-validity gate. |
| `docs/adr/decision-log.md` | Updated index with ADR 0003, ADR 0004, and the Phase 0-C readiness rollup. |
| `docs/adr/decisions/2026-04-25-phase-0-a-task-7-closure-by-operational-scope.md` | Created via `scripts/create_adr_decision.py`. |
| `docs/adr/decisions/2026-04-25-defer-c-unit-test-infrastructure-for-phase-0-c-appendjsonstring-to-phase-2a.md` | Created via `scripts/create_adr_decision.py`. |
| `docs/adr/decisions/2026-04-25-phase-0-c-readiness-rollup.md` | Created (manual rollup, `adr_required: false`) covering both 0003 and 0004. |
| `docs/memo/phase-0-a-exit-2026-04-23.md` | Updated. Task 7 status DEFERRED → CLOSED (ADR 0003). |
| `docs/memo/phase-0-c-exit-2026-04-25.md` | This file. |

Per AGENTS.md §Imperatives item 5, no PR has been opened for `feat/phase-0-c-implementation` yet — that's the next step (Task 8). Commits already on `origin/feat/phase-0-c-implementation`: `1007520`, `7754f56`, `056d396`, `ab2c848`, `4f2ce93`. The exit memo + this run's evidence belong on top before opening the PR.

## References

- `docs/architecture-v5.md` (v5.9) — `:1787-1790` (game-thread state-build routing), `:2399-2419` (Phase 1 WebSocket boundary, ADR 0004 reopen trigger), `:2799-2816` (Phase 0-B/0-C scope)
- `docs/superpowers/plans/2026-04-25-phase-0-c-internal-api-observation.md`
- `docs/adr/0003-phase-0-a-task-7-closure-by-design.md`
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md`
- `docs/memo/phase-0-a-exit-2026-04-23.md` (env paths, Task 7 closure)
- `docs/memo/phase-0-b-exit-2026-04-25.md` (BackupChar fallback rule, framing prefix observation)
- `mod/LLMOfQud/SnapshotState.cs` — JSON build helpers
- `mod/LLMOfQud/LLMOfQudSystem.cs` — game-thread / render-thread split
- CoQ APIs (verify before re-citing): `decompiled/XRL.Core/XRLCore.cs:624-626, 2347-2351, 2380-2383, 2423-2426`; `decompiled/XRL.World/Zone.cs:388-398, 1982-2010, 5411-5418`; `decompiled/XRL.World/Cell.cs:210, 212, 214`; `decompiled/XRL.World/GameObject.cs:766, 1177-1213, 2972-2986, 9930-, 10887-10894`; `decompiled/XRL.UI/Options.cs:574-576`; `decompiled/MetricsManager.cs:407-409`
