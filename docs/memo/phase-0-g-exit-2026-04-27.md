# Phase 0-G Exit — 2026-04-27

## Outcome

- **Phase 0-G judgment-boundary実証 complete.** The
  `BuildDecisionInput → IDecisionPolicy.Decide → Execute` boundary
  established by ADR 0009 is wired in
  `mod/LLMOfQud/LLMOfQudSystem.cs:HandleEvent(CommandTakeActionEvent)`,
  with a minimal `HeuristicPolicy` (`mod/LLMOfQud/HeuristicPolicy.cs`)
  as the validation vehicle. The interface
  (`mod/LLMOfQud/IDecisionPolicy.cs`) and DTOs satisfy
  ADR 0009 §Decision #4: `Decide` reads only `DecisionInput` and is
  replaceable by an out-of-process call without changing
  `BuildDecisionInput` or `Execute`.
- **5-run Warden Joppa acceptance: 4 PASS / 1 FAIL.** The single
  failure is **Run 2** (1777 cmd lines), which ran on the
  pre-`b726814` build whose `_blockedDirs.Clear()` on a successful
  `Move` discarded wall knowledge — a feedback-memory bug that
  drove `pass_turn_fallback_rate` to 0.490. Fixed by switching to
  `Dictionary<cellKey, HashSet<string>>` per-cell blocked-direction
  memory (`mod/LLMOfQud/LLMOfQudSystem.cs:42-46, 259+`,
  commit `b726814`); Runs 3-5 ran on the post-fix build and all
  passed. The architecture-v5.md `:2812` "≥50 turns survival in
  3/5 runs" gate is satisfied (4 of 5).
- **ADR 0009 §Decision #5.4 sharpened by ADR 0010 (this phase).**
  Run 5 (3691 cmd lines) exhibited 96.4% time in 2-cell N⇄S
  oscillation inside a U-shape (コの字) wall pocket but
  satisfied the ADR 0009 §5.4 thresholds at
  `pass_turn_fallback_rate = 0.010`,
  `successful_terminal_action_rate = 0.990`. Rather than tighten
  the gate with anti-cycle metrics or patch `HeuristicPolicy` with
  anti-backtrack logic, ADR 0010 declares heuristic exploration
  quality a non-goal and reinterprets ADR 0009 §5.4 as
  boundary-integrity sanity checks (not exploration competence).
  Phase 1 LLM owns exploration quality
  (`docs/architecture-v5.md:2836-2855`).
- **Cross-channel parity (4 PASS runs, ADR 0010 sharpened):**
  cmd = decision = 4946 lines combined; state/caps/build/screen all
  within ±2 lines per run (chargen-boundary slicing artifact +
  Run 5 shutdown ThreadAbortException — see Open Observations).
  Zero structured-channel ERR (state/caps/build/decision/cmd/screen)
  except 1 `[state] ERROR turn=3693 ThreadAbortException` at Run 5
  shutdown (engine quit, not a runtime emit failure).
- **PROBE 3' three responsiveness probes (Task 6) PASS** (operator
  in-game, 2026-04-27): 3a adjacent hostile elicits non-explore
  intent; 3b low-HP adjacent hostile elicits non-attack intent
  (escape via `OppositeDir` Move); 3c blocked-direction memory
  causes the 2nd `Decide` to choose a different `dir` with
  `reason_code=blocked_dir`. ADR 0009 §Decision #5.3 satisfied.
- **20/20 sampled-turn programmatic audit on Run 5** (Task 8). Each
  sampled turn passes 7 cross-channel checks: presence in all 5
  JSON channels + screen, hp consistency
  (`state.player.hp == decision.input_summary.hp`), intent ⊂
  `{attack, escape, explore}`, action ⊂ `{Move, AttackDirection}`,
  decision/cmd action match, state shape, and per-channel schema
  label (`runtime_caps.v1`, `current_build.v1`,
  `command_issuance.v1`, `decision.v1`). ADR 0009 §Decision #5.5
  inherited gate (≥19/20 ⇔ "99% accuracy spirit") satisfied.

## Acceptance counts

Per-run channel counts (raw line totals, including chargen-boundary
slicing artifacts):

| Run | cmd | state | caps | build | decision | screen BEGIN | last_hp | Result |
|----:|----:|------:|-----:|------:|---------:|-------------:|--------:|--------|
| 1 | 253 | 253 | 253 | 253 | 253 | 253 | 2 | PASS |
| 2 | 1777 | 1777 | 1777 | 1777 | 1777 | 1777 | 2 | FAIL (pre-`b726814`) |
| 3 | 380 | 380 | 380 | 380 | 380 | 380 | 3 | PASS |
| 4 | 622 | 621 | 621 | 621 | 622 | 622 | 1 | PASS (1-line slice artifact) |
| 5 | 3691 | 3693 | 3692 | 3692 | 3691 | 3691 | 18 | PASS (1 ERR_STATE on shutdown, U-pocket) |

Combined PASS-run aggregates (Runs 1, 3, 4, 5):

| Frame | Count |
|---|---|
| `[cmd]` | 4946 |
| `[decision]` | 4946 |
| `[state]` (JSON valid) | 4946 |
| `[caps]` (JSON valid) | 4946 |
| `[build]` (JSON valid) | 4946 |
| `[screen] BEGIN` | 4946 |
| `[state] ERROR sentinel` | 1 (Run 5 shutdown ThreadAbortException) |
| Other channel ERRs | 0 |
| Distinct `intent` values observed | 3: `explore` (4902), `attack` (27), `escape` (17) |
| Distinct `action` values observed | 2: `Move`, `AttackDirection` |

Anti-degeneracy gate (per-PASS-run, ADR 0009 §5.4 thresholds with
ADR 0010 sharpening):

| Run | pass_turn_fallback_rate | successful_terminal_action_rate | Threshold |
|---:|--:|--:|--|
| 1 | 0.000 | 1.000 | ≤ 0.20 / ≥ 0.70 |
| 3 | 0.003 | 0.997 | PASS |
| 4 | 0.000 | 1.000 | PASS |
| 5 | 0.010 | 0.990 | PASS (interpreted per ADR 0010) |

The ≥2-distinct-intents-across-5-runs constraint is satisfied with
margin (3 distinct intents observed).

## Verified environment

- CoQ build: `BUILD_2_0_210`, Unity Version `6000.0.41f1` (same as
  Phase 0-D / 0-E / 0-F — no game update across phases).
- Single-mod load order: `1: LLMOfQud`. Other user mods skipped per
  `build_log.txt`.
- macOS path layout (post-rebrand, same as 0-E / 0-F):
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`
  - Roslyn assembly written to
    `$COQ_SAVE_DIR/ModAssemblies/LLMOfQud.dll` (transient).
- Mod compile: `Compiling 5 files... Success :)` with
  `Defined symbol: MOD_LLMOFQUD`. No `MODWARN` / `COMPILER ERRORS`
  for `LLMOfQud`. The 5 files are `IDecisionPolicy.cs` (new),
  `HeuristicPolicy.cs` (new), `LLMOfQudSystem.cs` (modified),
  `SnapshotState.cs` (modified), and `Options.cs` (unchanged from
  0-F).
- Acceptance run launches: 5 distinct CoQ launches between
  2026-04-27T01:30Z and 2026-04-27T07:18Z. Run 2 launched on
  pre-`b726814` build; Runs 3-5 launched on post-`b726814` build.
  Run 5 launched on the final post-`9a1ec86` build (ADR 0010
  docs-only; mod assembly identical to post-`b726814`).

## Sample shapes

**`decision.v1` — `intent="explore"` (default explore, no hostile):**
```json
{"turn":1,"schema":"decision.v1","input_summary":{"hp":20,"max_hp":20,"adjacent_hostile_dir":null,"blocked_dirs_count":0},"intent":"explore","action":"Move","dir":"E","reason_code":"default_explore","error":null}
```

**`decision.v1` — `intent="attack"` (adjacent hostile, full HP):**
```json
{"turn":197,"schema":"decision.v1","input_summary":{"hp":20,"max_hp":20,"adjacent_hostile_dir":"NE","blocked_dirs_count":0},"intent":"attack","action":"AttackDirection","dir":"NE","reason_code":"adj_hostile","error":null}
```

**`decision.v1` — `intent="escape"` (low HP + adjacent hostile, escape via OppositeDir):**
```json
{"turn":252,"schema":"decision.v1","input_summary":{"hp":3,"max_hp":20,"adjacent_hostile_dir":"NE","blocked_dirs_count":0},"intent":"escape","action":"Move","dir":"SW","reason_code":"low_hp_adj_hostile","error":null}
```

**`[state] ERROR` sentinel (Run 5 shutdown, human-readable diagnostic
form per Phase 0-D pattern at `mod/LLMOfQud/LLMOfQudSystem.cs:130-135`):**
```text
INFO - [LLMOfQud][state] ERROR turn=3693 ThreadAbortException: Thread was being aborted.
```

This line is NOT a JSON sentinel — it is the human-readable diagnostic
emitted alongside (or instead of, under thread-abort) the JSON sentinel
that `LLMOfQudSystem` queues on `PendingSnapshot`. The shutdown thread
abort prevented the JSON sentinel from flushing. Validator updated to
treat `[xxx] ERROR turn=N ...` lines as valid sentinel observations
rather than JSON-invalid noise (matches the existing screen-channel
ERROR-sentinel handling).

## Phase 0-G implementation rules (carry forward to Phase 0-G+ / Phase 1)

1. **`IDecisionPolicy` boundary is the LLM/WebSocket plug-in point.**
   `IDecisionPolicy.Decide(DecisionInput) → Decision`
   (`mod/LLMOfQud/IDecisionPolicy.cs:58`) is **input-only**: it must
   not reference `The.*`, `Cell.*`, `MetricsManager`,
   `GameObject.*`, or any CoQ API outside the supplied DTO. Phase 1's
   `WebSocketPolicy` and Phase 2+'s `LLMPolicy` swap into this
   interface verbatim. PROBE 2' (Task 4 Step 2 grep gate) enforces
   the no-CoQ-API rule statically; future policy implementations
   inherit the same gate.

2. **`DecisionInput` field set is locked at `decision_input.v1`.**
   Any new signal a future policy requires (visit-count history,
   path-cost map, item-on-cell, vision cone, etc.) MUST be added to
   `DecisionInput` by `BuildDecisionInput` and is a
   `decision_input.v2` change requiring a new ADR. Locked fields:
   `Player.{Hp,MaxHp,Pos}`, `Adjacent.{HostileDir,HostileId,BlockedDirs}`,
   `Recent.{LastActionTurn,LastAction,LastDir,LastResult}`, `Turn`.

3. **`decision.v1` wire schema is locked.** Top-level keys (in
   order): `{turn, schema, input_summary, intent, action, dir,
   reason_code, error}`. Intent enum: `{attack, escape, explore}`.
   Action enum: `{Move, AttackDirection}`. Sentinel form:
   `{turn, schema, error: {type, message}}`. Any field addition or
   enum change requires `decision.v2` + ADR.

4. **Per-cell blocked-direction memory** (`Dictionary<cellKey,
   HashSet<string>>`, `mod/LLMOfQud/LLMOfQudSystem.cs:42-46`).
   `cellKey = "{x}:{y}:{zone}"`. Updated via `UpdateBlockedDirsMemory`
   only on `Move` failures with `fallback == "pass_turn"`.
   Successful moves do NOT clear the memory (the Run 2 lesson). Past
   blocked-dir knowledge is per-cell, NOT per-policy-instance — a
   future LLM policy can still read it via `Adjacent.BlockedDirs`
   without inheriting the same data structure.

5. **3-layer drain pattern (inherited from Phase 0-F) is intact.**
   Layer 1 = `Move`/`AttackDirection` success spends energy via the
   API. Layer 2 = `pass_turn` fallback when Layer 1 returns false
   (see `mod/LLMOfQud/LLMOfQudSystem.cs` Execute helper). Layer 3 =
   `Energy.BaseValue = 0` last-ditch in the catch path. ADR 0007
   `PreventAction` scope (success path → false; abnormal-energy
   catch path → true) is preserved unchanged. The Phase 0-G refactor
   restructured `HandleEvent(CommandTakeActionEvent)` into the
   `BuildDecisionInput → Decide → Execute` triple but did NOT alter
   the energy-drain semantics or `PreventAction` placement.

6. **Anti-degeneracy gate operationalizes `:2812` as
   boundary-integrity, NOT exploration competence (ADR 0010).** The
   ADR 0009 §5.4 thresholds (`pass_turn_fallback_rate ≤ 20%`,
   `successful_terminal_action_rate ≥ 70%`, ≥2 distinct intents) are
   sanity checks against catastrophic policy degradation, NOT
   measures of exploration quality. Future Phase 0-G+ phases that
   want exploration-quality gates (cycle detection, distinct-cell
   counting, etc.) require a new ADR and a phase scope that has the
   capability to pursue them (LLM observation reasoning OR
   System-layer pathfinder safety-net introduction).

7. **PROBE 3' three-probe pattern is the responsiveness contract.**
   Any future Phase 0-G+ policy implementation (heuristic v2,
   `WebSocketPolicy`, `LLMPolicy`) MUST satisfy 3a (adjacent hostile
   elicits non-explore intent), 3b (low HP elicits non-attack
   intent), 3c (blocked-direction memory causes 2nd `Decide` to
   switch dir or action). These are minimum behavioral
   correctness checks separate from acceptance-run survival.

8. **CoQ pathfinder
   (`decompiled/XRL.World.AI.Pathfinding/FindPath.cs`) is a Phase 1+
   System-layer safety-net candidate, NOT a Phase 0-G dependency
   (ADR 0010 §Decision #5).** Used by mouse-click move and AI
   traversal in CoQ. A future System-layer integration could call
   `FindPath` when a cycle-detection signal fires (e.g., the
   policy reports `intent=explore` for the same cell N turns
   in a row), bypassing the policy to escape U-pockets. This is
   explicitly out-of-scope for Phase 0-G and would require an ADR
   if introduced in Phase 1+.

## Provisional cadence — future revisit triggers (extends 0-D / 0-E / 0-F)

- **`decision.v1` schema lock.** Re-open if a Phase 1 consumer
  (Python brain) needs additional fields. Likely candidates: visit
  history (cycle detection), entity ID at action target (correlation
  with `entities[]`), tactical hints from screen-character analysis.
- **`Adjacent.BlockedDirs` semantics.** Currently per-cell hard-block.
  An LLM policy might prefer soft-deprioritize-but-allow-retry
  (e.g., "the wall might disappear if a destructible barrier was
  reduced"). Re-open if Phase 1 LLM needs the distinction.
- **PROBE 3c stability.** PROBE 3c assumed 1-turn `BlockedDirs`
  population latency on first wall bump. If a future CoQ patch
  changes `Move` failure semantics (e.g., always returns false and
  burns energy elsewhere), the probe needs re-validation.
- **Run 5 ThreadAbortException emission posture.** The
  `[state] ERROR turn=3693 ...` line is the Phase 0-D human-readable
  diagnostic emitted before the JSON sentinel; the JSON sentinel did
  not flush because the thread was aborted mid-emission. If a
  consumer requires guaranteed JSON-only state observations, the
  emission ordering must be inverted (JSON first, diagnostic second)
  or the diagnostic dropped.

## Open observations (recorded but not blocking)

- **Run 5 U-pocket oscillation (96.4% of turns at 2 cells).** Player
  at zone `JoppaWorld.12.17.2.2.10` cells `(55,3)` ⇄ `(55,4)` for
  3,558 of 3,691 turns. `HeuristicPolicy.ExploreOrder` deterministic
  greedy (`E, SE, NE, S, N, W, SW, NW`) prefers `S` at one cell and
  `N` at the other when E/SE/NE are wall-blocked, never trying `W`
  (the escape direction). All Moves succeed (`pos_after !=
  pos_before`), so the validator metric counts each step as a
  successful terminal action. Per ADR 0010 this is acceptable;
  Phase 1 LLM owns exploration quality. The trace is preserved
  operator-locally under the Phase 0-G acceptance run-5 directory
  for future reference (path inlined in the operator-local
  artifacts section below).
- **Run 4 1-line slicing artifact.** `cmd=622` vs
  `state/caps/build=621`. The Player.log slicer cut the chargen
  boundary one [cmd] line later than the matched [state]/[caps]/
  [build] start. Not a runtime parity issue — operator slicing
  procedure can be tightened in future runs by splitting on the
  2nd `[state] turn=1` rather than `[cmd] turn=1`.
- **Run 5 chargen-boundary slicing leftovers.** `state=3693`,
  `caps=3692`, `build=3692` vs `cmd=3691`. Same artifact; same
  recommendation.
- **`escape` intent fired 17 times across the 4 PASS runs.** All 17
  fires correctly used `OppositeDir(HostileDir)` and emitted
  `reason_code=low_hp_adj_hostile`. PROBE 3b validates the
  responsiveness; the in-run firings confirm the path is exercised
  in real combat (snapjaw / two-headed boar / salthopper / wandering
  wraith encounters).
- **`attack` intent fired 27 times.** All 27 used the actual hostile
  direction; combat resolved per CoQ rules (some hits, some misses,
  some kills). 11 damaging hits across the 27 (consistent with
  Phase 0-F's 11/15 damaging-hit rate on a smaller sample).
- **PROBE 1' (BASELINE) outcomes are inherited from PR-G1.5.**
  PROBE 1 BASELINE captured Phase 0-F's 9919-turn east-march
  behavior on Warden Joppa as evidence that the original ADR 0008
  heuristic-specifics framing was misaligned. ADR 0009 (rescope) and
  ADR 0010 (non-goal declaration) inherit that finding.

## Open hazards (still tracked)

- **Engine-speed autonomy** (inherited from Phase 0-F). Policy
  decisions at engine-thread cadence remain unobservable in real
  time. Phase 1 (WebSocket bridge,
  `docs/architecture-v5.md:2836-2855`) MUST address rate-limiting,
  throttle to render cadence, or LLM decision latency naturally
  enforcing pace. Until Phase 1 lands, autonomous runs are not
  human-streamable in real time.
- **Cooldown decrement (`cooldown_segments_raw > 0`) for `[caps]`**:
  still NOT EXERCISED across Phase 0-D through 0-G. Defer to phase
  with active mutation use (no Phase 0 phase invokes mutations on
  the heuristic policy).
- **Multi-mod coexistence**: still untested (single-mod load order
  in all Phase 0 acceptance runs).
- **Save / load resilience** for `[caps]` / `[build]` / `[cmd]` /
  `[decision]`: within-session `_beginTurnCount` reset is observed
  cleanly across Phase 0-D/E/F/G; no formal save-quit-reload
  acceptance was performed in Phase 0-G. Defer.
- **Tutorial intercept** (`decompiled/XRL.World/GameObject.cs:15336-15338`):
  not exercised by Warden runs (Warden chargen skips tutorial).
  Still untested as in Phase 0-F.
- **Hostile-interrupt path** (Phase 0-F note): now reachable but
  remains no-op because `HeuristicPolicy` does not engage AutoAct.
  Re-open if a future policy uses `AutoAct.Setting`.
- **U-pocket policy oscillation** (Phase 0-G specific). Documented
  per ADR 0010 §Decision #6 as Known Limitation; deferred to Phase 1
  LLM. If Phase 1 chooses to introduce a System-layer
  `FindPath` safety-net under a new ADR, this hazard reduces.

## Known Limitations (per ADR 0010 §Decision #6)

`HeuristicPolicy` is a **boundary-validation scaffold**, not an
optimized exploration agent. The following limitations are explicit
and intentional:

1. **No cycle detection.** `HeuristicPolicy` does not detect
   2-cycle, 3-cycle, or longer-period orbits. The deterministic
   `ExploreOrder = {E, SE, NE, S, N, W, SW, NW}` can produce
   indefinite oscillation in U-shape (コの字) wall geometries
   where the preferred directions at two adjacent cells are
   reciprocal.
2. **No anti-backtrack.** `Decide` does not consult
   `Recent.LastDir` to avoid immediately reversing. (The
   `DecisionInput.Recent` field set is populated by
   `BuildDecisionInput`, but `HeuristicPolicy` ignores it. A
   future policy is free to use it without schema change.)
3. **No symmetry-break heuristic.** The deterministic ExploreOrder
   means policy behavior is fully replayable from
   `(player_pos, blocked_dirs)`, which is a desirable property for
   debugging but means deterministic geometries trap deterministic
   policies.
4. **Exploration quality is owned by Phase 1 LLM**
   (`docs/architecture-v5.md:2836-2855`). The LLM has access to
   the full `screen.log` context (visible map, entity glyphs,
   spatial layout) and can reason about U-pockets in ways the
   `DecisionInput` DTO cannot capture by design (the DTO is
   intentionally narrow to keep the boundary contract small).

These limitations were observed empirically (Run 5 of Task 7 spent
96.4% of 3,691 turns oscillating between two cells in a U-pocket)
and are documented per ADR 0010 §Decision #6 to prevent the
"build a smarter heuristic" category error from recurring in
Phase 0-G+.

## Files modified / created in Phase 0-G

| Path | Change |
|---|---|
| `mod/LLMOfQud/IDecisionPolicy.cs` | NEW — Task 2 (commit `eb1740c`). Defines `IDecisionPolicy.Decide(DecisionInput) → Decision` interface and DTOs (`DecisionInput`, `PlayerSnapshot`, `AdjacencySnapshot`, `RecentHistory`, `Decision`, `Pos`). Boundary contract comment lock at the interface declaration site. |
| `mod/LLMOfQud/HeuristicPolicy.cs` | NEW — Task 4 (commit `ed66d4a`). Minimal `IDecisionPolicy` implementation with adjacent-hostile attack, low-HP escape, deterministic ExploreOrder default. Per ADR 0010 §Decision #4, this is the final Phase 0-G policy form. |
| `mod/LLMOfQud/SnapshotState.cs` | Modified — Task 3 (commit `66d4388`). Added `BuildDecisionJson(int turn, Decision decision, DecisionInput input)` and `BuildDecisionSentinelJson(int turn, Exception ex)` after `BuildCmdSentinelJson`. Mirrors the `command_issuance.v1` builder conventions (StringBuilder, char delimiters, InvariantCulture). `input_summary` digest: `{hp, max_hp, adjacent_hostile_dir, blocked_dirs_count}`. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Modified — Task 5 (commits `6f7a24a`, `419b710`, `fb1d4da`). Extracted `ScanAdjacentHostile` helper; added `IDecisionPolicy _policy` field, `BuildDecisionInput`, `LookupBlockedDirsForCell`, `CellKey`, `UpdateBlockedDirsMemory`; refactored `HandleEvent(CommandTakeActionEvent)` into `BuildDecisionInput → Decide → Execute`. Subsequent fixes: `1a9770f` (gate `target_*` capture by `decision.Action == "AttackDirection"` to preserve Phase 0-F docstring contract); `b726814` (per-cell blocked-direction memory `Dictionary<cellKey, HashSet<string>>` to fix Run 2 clear-on-success oscillation). |
| `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` | Created in PR-G1, partial-superseded by ADR 0009 (PR-G1.5). Decision #1, #2, #4 principle, #5, #6 retained. |
| `docs/adr/0009-phase-0-g-rescope-judgment-boundary.md` | Created in PR-G1.5. Establishes the judgment boundary, 5 acceptance criteria, anti-degeneracy gate, and `decision_input.v1` / `decision.v1` schema locks. |
| `docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md` | NEW (this PR-G2). Sharpens ADR 0009 §Decision #5.4 interpretation, declares heuristic exploration quality non-goal, no policy/metric patches, deferred-to-Phase-1 stance on CoQ `FindPath` integration. |
| `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md` | Revised in PR-G1.5 (boundary contract spec lock). |
| `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md` | Revised in PR-G1.5 (Tasks 2-9 with PROBE 3' replacing PROBE 2-4). |
| `docs/adr/decision-log.md` + `docs/adr/decisions/2026-04-26-*.md` | Decision records for ADR 0008 (PR-G1 + 2 follow-ups), ADR 0009 (PR-G1.5 + 5 codex follow-ups), ADR 0010 (this PR-G2). |
| `docs/memo/phase-0-g-exit-2026-04-27.md` | This file. |

## References

- `docs/architecture-v5.md` (v5.9): `:2804` (Phase 0-G line),
  `:2811-2817` (Phase 0 exit criteria), `:2812` (5-run survival
  gate operationalized by ADR 0009 §5.4 + ADR 0010 sharpening),
  `:2814` + `:2816` (99% accuracy gate operationalized by
  ADR 0008 Decision #6 / inherited by ADR 0009 §5.5),
  `:2836-2855` (Phase 1 WebSocket bridge inheriting the boundary).
- `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` —
  Decision #1 (`:2817` interpretation), Decision #2 (`[decision]`
  channel concept), Decision #5 (no frozen-text deviation),
  Decision #6 (`:2814+:2816` joint reading) inherited.
- `docs/adr/0009-phase-0-g-rescope-judgment-boundary.md` — primary
  Phase 0-G ADR; boundary contract, 5 acceptance criteria,
  `decision_input.v1` / `decision.v1` schema lock.
- `docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md`
  — sharpens ADR 0009 §5.4 interpretation; declares heuristic
  exploration quality non-goal; documents Run 5 U-pocket as
  acceptable; defers `FindPath` System-layer integration to Phase
  1+.
- `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`
  — boundary contract spec.
- `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`
  — Phase 0-G implementation plan (Tasks 2-9).
- `docs/memo/phase-0-f-exit-2026-04-26.md` — Phase 0-F exit memo
  whose carry-forward observations seeded this phase.
- `mod/LLMOfQud/IDecisionPolicy.cs` — boundary contract.
- `mod/LLMOfQud/HeuristicPolicy.cs` — final Phase 0-G policy
  (no further changes per ADR 0010 §Decision #4).
- `mod/LLMOfQud/SnapshotState.cs` — `decision.v1` JSON builders
  (`BuildDecisionJson`, `BuildDecisionSentinelJson`).
- `mod/LLMOfQud/LLMOfQudSystem.cs` — refactored
  `HandleEvent(CommandTakeActionEvent)` body
  (`BuildDecisionInput → Decide → Execute`); per-cell blocked-dir
  memory; `IDecisionPolicy _policy` field.
- CoQ APIs verified during Phase 0-G (re-cite from `decompiled/`):
  - `decompiled/XRL/IEventHandler.cs:882` —
    `BeginTakeActionEvent` interface declaration (inherited from
    Phase 0-A).
  - `decompiled/XRL/CommandTakeActionEvent.cs:37-39` — `Check`
    semantics (inherited from Phase 0-F).
  - `decompiled/XRL.Core/ActionManager.cs:786-800, 829-832, 838,
    1797-1799, 1806-1808` — energy gate, CTA short-circuit,
    keyboard branch guard, render fallback (inherited from Phase
    0-F via ADR 0007).
  - `decompiled/XRL.World/GameObject.cs:15274-15290, 15397-15400,
    17882-17902` — `Move`, `AttackDirection` signatures (inherited
    from Phase 0-F).
  - `decompiled/XRL.World/Cell.cs:8511-8557` — `GetCombatTarget`
    (inherited from Phase 0-F via `ScanAdjacentHostile` helper
    refactor).
  - `decompiled/XRL.World.AI.Pathfinding/FindPath.cs` — CoQ engine
    pathfinder (mouse-click + AI traversal). Documented in ADR 0010
    §Decision #5 as Phase 1+ System-layer safety-net candidate; not
    adopted in Phase 0-G.
- Acceptance log artifacts (operator-local, not committed):
  - `/tmp/phase-0-g-acceptance/run-{1,2,3,4,5}/` — per-run channel
    splits (`cmd.log`, `state.log`, `caps.log`, `build.log`,
    `decision.log`, `screen.log`).
  - `/tmp/phase-0-g-acceptance/validate.py` — 5-run acceptance
    validator with anti-degeneracy gate, branch↔action invariant,
    and ERROR-sentinel-aware JSON validity check (updated in this
    phase to recognize the human-readable
    `[xxx] ERROR turn=N ...` diagnostic form alongside JSON
    sentinels).
  - 20-turn programmatic audit on Run 5 (Task 8): inline Python
    script, 7 cross-channel checks, 20/20 PASS.
