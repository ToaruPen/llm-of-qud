# Phase 0-G: Heuristic Bot — Design Spec

**Goal:** Layer a smallest-possible decision policy on top of Phase 0-F's `CommandTakeActionEvent` direct-action path so the player advances each turn by the locally-best of three branches: `flee` if hurt and a hostile is adjacent, `attack` if a hostile is adjacent, `explore` otherwise. Emit one structured `[LLMOfQud][decision] {...}` JSON line per `CommandTakeActionEvent` dispatch — a sixth per-turn observation primitive alongside `[screen]` (0-B), `[state]` (0-C), `[caps]` (0-D), `[build]` (0-E), and `[cmd]` (0-F). The MOD remains the only actor; no LLM yet.

**Spec line `docs/architecture-v5.md:2804` is implemented as written.** No pivot. The interrupt-detection-latency exit criterion (`docs/architecture-v5.md:2817`) requires interpretation: this spec adopts ADR 0008's reading that "interrupt fires within same turn" is satisfied by the heuristic branching to `attack` (or `flee`) on the very `CommandTakeActionEvent` where a hostile becomes adjacent. AutoAct's engine-level `decompiled/XRL.Core/ActionManager.cs:834-837` interrupt path remains owned by Phase 0b (`docs/architecture-v5.md:2825-2834`); 0-G does not engage `AutoAct.Setting`. ADR 0008 records this interpretation.

**Architecture:**

- **Game thread (`HandleEvent(CommandTakeActionEvent E)`)**: extends the Phase 0-F handler in `mod/LLMOfQud/LLMOfQudSystem.cs:181-378`. The new shape is two ordered phases inside the same handler invocation:
  1. **Decide**: read player HP/max-HP, run the existing 8-direction hostile scan from Phase 0-F (`decompiled/XRL.World/Cell.cs:7322-7324, 8511-8558` + `decompiled/XRL.World/GameObject.cs:10887-10894`), classify `hurt`, pick one of three branches, choose the executing direction. Emit `[decision]` synchronously.
  2. **Execute**: dispatch `Move(dir, DoConfirmations:false)` or `AttackDirection(dir)` per the branch; on `result==false && !energySpent`, fall through to `PassTurn()` (Layer 2). Emit `[cmd]` synchronously, identical shape to Phase 0-F's `command_issuance.v1`.
- **Hook is `CommandTakeActionEvent`**, unchanged from Phase 0-F. `BeginTakeActionEvent` continues to drive observation (`[state]`, `[caps]`, `[build]`); CTA continues to drive issuance (`[cmd]`) and now also `[decision]`.
- **Direct API path, not `CommandEvent.Send`**, unchanged from Phase 0-F (ADR 0006). The new `flee` branch reuses `GameObject.Move(string Direction, bool DoConfirmations = true, ...)` (`decompiled/XRL.World/GameObject.cs:15274-15290, 15719-15722`) with the same `DoConfirmations: false` and `AutoAct.ClearAutoMoveStop()` mirror as Phase 0-F's east `Move`.
- **`PreventAction` scope unchanged from ADR 0007.** Success path leaves `PreventAction = false` so the `decompiled/XRL.Core/ActionManager.cs:1806-1808` render fallback fires per turn and `[screen]/[state]/[caps]/[build]` continue to flush. `PreventAction = true` is set ONLY when post-recovery `Energy.Value >= 1000` (Layer 4).
- **Game-thread direct emit for `[decision]`, NOT through `PendingSnapshot`.** Same posture as `[cmd]` in Phase 0-F: `MetricsManager.LogInfo` (`decompiled/MetricsManager.cs:407-409`) is called synchronously inside `HandleEvent(CommandTakeActionEvent)`. `PendingSnapshot` keeps its single observation slot for the four render-thread channels.
- **Per-turn output: 7 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]` + 1 `[decision]` + 1 `[cmd]`. Order on the game thread inside `HandleEvent(CommandTakeActionEvent)` is `[decision]` BEFORE `[cmd]`. Order between the four render-thread channels and the two game-thread channels (`[decision]`, `[cmd]`) remains unconstrained — interleaving from other CoQ subsystems' `LogInfo` is permitted. **Parser correlation contract: correlate by the `turn` field, never adjacency or count parity.** This rule is the unchanged Phase 0-F contract extended to a sixth channel.

**Decision logic (single handler, game-thread):**

`HandleEvent(CommandTakeActionEvent E)` executes the following pseudocode. The Phase 0-F structure (try / catch / finally with the 3-layer drain at lines `181-378` of `LLMOfQudSystem.cs`) is preserved verbatim; the new logic inserts BEFORE the existing action-dispatch branch.

```
HandleEvent(CommandTakeActionEvent E):
  int turn = _beginTurnCount
  GameObject player = The.Player
  if player == null: emit cmd-sentinel; PreventAction=true; return true

  try:
    int energy_before = player.Energy.Value
    int hp = player.hitpoints                   # Statistic.Value (live)
    int max_hp = player.baseHitpoints           # Statistic.BaseValue
    pos_before = {x: player.CurrentCell.X,
                  y: player.CurrentCell.Y,
                  zone: player.CurrentCell.ParentZone.ZoneID}

    # ---- Decide ----
    # Step 1: 8-direction hostile scan (unchanged from Phase 0-F)
    (hostileDir, hostileObj) = ScanAdjacentHostile(player.CurrentCell, player)
    bool adjacentHostile = (hostileObj != null)

    # Step 2: hurt classification — composite, codex Q2 lock
    bool hurt = (hp <= max(8, floor(max_hp * 0.60))) AND adjacentHostile

    # Step 3: branch selection
    string branch
    string chosenDir
    string fallback = null
    if hurt:
      branch = "flee"
      chosenDir = ChooseFleeDir(player.CurrentCell, hostileObj, player, out fallback)
      # fallback ∈ {null, "boxed_in_attack", "no_safe_cell_pass"}
      # null         => safe inverse or farthest-safe cell found
      # boxed_in_attack => no safe cell anywhere; chosenDir = hostileDir, branch escalates to attack
      # no_safe_cell_pass => no safe cell AND no adjacent hostile (cannot happen when hurt is true,
      #                       included for defensive sentinel completeness)
    elif adjacentHostile:
      branch = "attack"
      chosenDir = hostileDir
    else:
      branch = "explore"
      chosenDir = ChooseExploreDir(player.CurrentCell, player)
      # explore picks "E" first, scans E,SE,NE,S,N,W,SW,NW for first safe; if none, PassTurn
      if chosenDir == null:
        fallback = "no_safe_cell_pass"

    # Emit [decision] BEFORE action — captures intent independent of action outcome
    EmitDecisionLine(turn, branch, hp, max_hp, hurt,
                    hostileDir, hostileObj?.ID,
                    chosenDir, fallback, error: null)

    # ---- Execute ----
    bool result
    string action
    string dir
    target_id = target_name = null
    target_pos_before = target_hp_before = null

    if branch == "attack" OR (branch == "flee" AND fallback == "boxed_in_attack"):
      target_id = hostileObj.ID
      target_name = hostileObj.ShortDisplayNameStripped
      target_pos_before = {x,y,zone}
      target_hp_before = hostileObj.hitpoints
      result = player.AttackDirection(chosenDir)   # chosenDir = hostileDir for both branches
      action = "AttackDirection"
      dir = chosenDir
    elif branch == "flee" AND fallback == "no_safe_cell_pass":
      # Pathological: hurt yet no adjacent hostile (shouldn't happen given hurt definition)
      # Pass turn rather than make up a direction
      result = false; action = "Move"; dir = chosenDir   # chosenDir is "E" placeholder
    elif chosenDir != null:                              # explore (any chosenDir) OR flee (safe cell)
      AutoAct.ClearAutoMoveStop()
      result = player.Move(chosenDir, DoConfirmations: false)
      action = "Move"
      dir = chosenDir
    else:                                                 # explore with no safe direction → PassTurn only
      result = false; action = "Move"; dir = "E"

    bool energySpent = (player.Energy.Value < energy_before)
    string cmdFallback = null
    if !result AND !energySpent:
      player.PassTurn()
      energySpent = true
      cmdFallback = "pass_turn"
    elif !result AND energySpent:
      cmdFallback = "pass_turn"

    int? target_hp_after = (hostileObj != null) ? hostileObj.hitpoints : null
    int energy_after = player.Energy.Value
    pos_after = ...

    EmitCmdLine(turn, action, dir, result, cmdFallback,
                energy_before, energy_after,
                pos_before, pos_after,
                target_id, target_name, target_pos_before,
                target_hp_before, target_hp_after,
                error: null)

  catch Exception ex:
    EmitDecisionSentinel(turn, ex)               # emits [decision] sentinel if not already emitted
    EmitCmdSentinel(turn, ex)                    # emits [cmd] sentinel
    if player?.Energy != null AND player.Energy.Value >= 1000:
      try: player.PassTurn() catch: pass
      if player.Energy.Value >= 1000:
        player.Energy.BaseValue = 0              # Layer-3 last-ditch (ADR 0006 Consequence #5)
  finally:
    if player?.Energy != null AND player.Energy.Value >= 1000:
      E.PreventAction = true                     # Layer-4 abnormal-energy defense (ADR 0007)
  return true
```

**Note on emission ordering:** `EmitDecisionLine` is the FIRST `LogInfo` call in the handler. If an exception fires AFTER the decision line was emitted, the `catch` block emits a `[cmd]` sentinel only (the decision was already published). If the exception fires BEFORE the decision line, the `catch` block emits both a `[decision]` sentinel and a `[cmd]` sentinel. A boolean flag `decisionEmitted` tracks this (initialized `false`, set `true` immediately after `EmitDecisionLine` returns).

**Hostile scan (`ScanAdjacentHostile`) — unchanged from Phase 0-F.** Direction priority `N → NE → E → SE → S → SW → W → NW`, first non-null `Cell.GetCombatTarget` hit wins. Filter `o => o != player && o.IsHostileTowards(player)`. Sources: `decompiled/XRL.World/Cell.cs:7322-7324` (`GetCellFromDirection`), `decompiled/XRL.World/Cell.cs:8511-8558` (`GetCombatTarget`), `decompiled/XRL.World/GameObject.cs:10887-10894` (`IsHostileTowards`).

**Safe-cell predicate (`IsSafeCell`).** A cell is "safe to step into" iff:

1. The cell is non-null. (`Cell.GetCellFromDirection(dir, BuiltOnly: false)` returned non-null.)
2. `cell.IsEmptyOfSolidFor(player, IncludeCombatObjects: true)` returns `true` — no solid object, no door (or unlocked door), no NPC body in the cell. (`decompiled/XRL.World/Cell.cs:5290-5305`.)
3. `cell.GetCombatTarget(Attacker: player, IgnorePhase: false, Phase: 5, AllowInanimate: false, Filter: o => o != player && o.IsHostileTowards(player))` returns `null` — no adjacent hostile in the cell.
4. `cell.GetDangerousOpenLiquidVolume()` returns `null` — no dangerous open liquid (lava, sludge, etc.). (`decompiled/XRL.World/Cell.cs:8597-8607`.)

The four conditions are evaluated in this short-circuit order. Note: `IsEmptyOfSolidFor` (`decompiled/XRL.World/Cell.cs:5296`) explicitly EXCLUDES `StairsDown`/`StairsUp` from solid-object rejection, so a cell containing only stairs returns `true` from rule 2. Phase 0-G's `IsSafeCell` therefore treats stair cells as safe — the bot WILL step onto stairs if they appear east-bias-first (or appear during a flee scan). On Joppa surface this is rare but possible (zone-edge stair tiles). Phase 0-G accepts this: a single involuntary zone change costs at most one turn of progress and does not violate any acceptance criterion (the 5-run gate counts `[cmd]` lines, not zone-stable turns). If a future phase needs stair-avoidance, add a fifth `IsSafeCell` clause then. Rule 4 may also misclassify some pseudo-liquid game elements; same acceptance posture. Rules 1–4 are the empirical-probe-validated cut.

**Flee direction (`ChooseFleeDir`).** Two-stage scan:

1. **Inverse direction first.** `inverseOf(hostileDir)` — table: N↔S, E↔W, NE↔SW, NW↔SE. If `IsSafeCell(GetCellFromDirection(inverseDir))` returns true, return `inverseDir` with `fallback=null`.
2. **Farthest-safe scan.** Iterate over the eight directions in Phase 0-F's priority order. For each, compute the destination cell and its Chebyshev distance to the hostile's cell (`max(|dx|, |dy|)`). Among directions where `IsSafeCell` is true, pick the one with maximum Chebyshev distance; tie-break by the same N→NE→E→SE→S→SW→W→NW priority. If at least one safe cell exists, return its direction with `fallback=null`.
3. **Boxed-in escalation.** No safe cell in any of the eight directions. Set `fallback="boxed_in_attack"`, return `hostileDir` (the executing branch becomes Attack, NOT Move).

Rationale: stepping toward a hostile-blocked cell is no worse than standing still while hurt; attacking it at least dispatches damage potential. Phase 0-G accepts this cut over the alternative ("PassTurn while hurt and surrounded") because the hurt branch is reached precisely when adjacent_hostile is true — the hostile is by definition adjacent and addressable by `AttackDirection`.

**Explore direction (`ChooseExploreDir`).** East-bias scan with deterministic fallback:

1. If `IsSafeCell(GetCellFromDirection("E"))` is true, return `"E"`.
2. Else iterate `SE → NE → S → N → W → SW → NW` in fixed order; return the first direction whose destination is safe.
3. If no direction is safe, return `null`. The handler treats `null` as "no Move issued; emit `[cmd]` with `fallback="pass_turn"` and call `PassTurn()` directly".

The east-bias priority preserves Phase 0-F's empirical 79-record east-walk acceptance result (`docs/memo/phase-0-f-exit-2026-04-26.md:9, 80`); the diagonal/perpendicular tier (`SE, NE, S, N, W, SW, NW`) keeps progress in roughly the same direction when east is blocked. Random-walk is rejected because it cannot meet the 50-turn Joppa survival gate without the operator-observable east-progression Phase 0-F validated.

**Schema lock: `decision.v1`.**

Full record (decision computed, no exception):

```json
{
  "turn": 42,
  "schema": "decision.v1",
  "branch": "flee",
  "hp": 14,
  "max_hp": 28,
  "hurt": true,
  "adjacent_hostile_dir": "E",
  "adjacent_hostile_id": "857",
  "chosen_dir": "W",
  "fallback": null,
  "error": null
}
```

Sentinel record (exception path) — reduced shape consistent with `[caps]` / `[build]` / `[cmd]` posture:

```json
{
  "turn": 42,
  "schema": "decision.v1",
  "error": {"type": "<ExceptionTypeName>", "message": "..."}
}
```

**Field semantics:**

- `turn`: integer, the same `_beginTurnCount` correlation key used by all five other channels. Required for log-line correlation.
- `schema`: literal string `"decision.v1"`. Field additions or order changes require v2 + ADR.
- `branch`: enum `"flee" | "attack" | "explore"`. The branch the heuristic selected. `attack` is selected ONLY when `adjacent_hostile_id != null && hurt == false`. `flee` is selected ONLY when `hurt == true` (which implies `adjacent_hostile_id != null`). `explore` is selected when no adjacent hostile.
- `hp`: integer, `player.hitpoints` (live `Statistic.Value`). Same accessor as `[state]`. (`decompiled/XRL.World/GameObject.cs:1177-1198`, `decompiled/XRL.World/Statistic.cs:238-252`.)
- `max_hp`: integer, `player.baseHitpoints` (`Statistic.BaseValue`).
- `hurt`: boolean, the result of `hp <= max(8, floor(max_hp * 0.60)) && adjacent_hostile_dir != null`. The threshold parameters (`8` floor and `0.60` ratio) are the codex-recommended starting point; **PROBE 2 (HP threshold sweet spot) MAY adjust these before the spec locks for implementation**. The composite (`AND adjacent_hostile`) prevents fleeing-from-nothing on damage from environment / starvation / status effects.
- `adjacent_hostile_dir`: string-or-null, the direction of the hostile-scan winner (`"N"|"NE"|...|"NW"`). Null when no hostile adjacent.
- `adjacent_hostile_id`: string-or-null, `hostileObj.ID` when set; matches the `target_id` field in the same-turn `[cmd]` line for `attack`/`flee` branches.
- `chosen_dir`: string-or-null, the direction the resulting action will use. For `attack` and `flee` (boxed-in escalation), equals the corresponding `[cmd].dir`. For `flee` (safe step), equals the inverse-or-farthest-safe direction. For `explore`, the chosen east-bias direction or `null` if all eight directions blocked. **Parser invariant**: when `branch == "attack"`, `chosen_dir == adjacent_hostile_dir`.
- `fallback`: string-or-null. Tracks decision-time escalation distinct from `[cmd].fallback` (which tracks action-time PassTurn).
  - `null`: branch executed without escalation.
  - `"boxed_in_attack"`: `flee` branch could not find a safe cell; `chosen_dir` was overridden to `adjacent_hostile_dir`; the resulting action is `AttackDirection`.
  - `"no_safe_cell_pass"`: `explore` branch could not find ANY safe cell; the resulting action is `PassTurn`.
  - `"no_safe_cell_pass"` from `flee` is tolerated as a defensive value but should NOT occur (`flee` requires `adjacent_hostile`, so `boxed_in_attack` always has a target available).
- `error`: object-or-null. Same RFC-8259-escaped shape as Phase 0-F's `[cmd].error`.

**JSON null discipline.** `decision.v1` has 4 nullable fields (`adjacent_hostile_dir`, `adjacent_hostile_id`, `chosen_dir`, `fallback`). The Phase 0-F-extracted helpers `AppendJsonStringOrNull` (`mod/LLMOfQud/SnapshotState.cs`, Phase 0-F Task 2) cover all four. No new helper extraction needed.

**`InvariantCulture` discipline.** All integer fields (`turn`, `hp`, `max_hp`) emit via `.ToString(CultureInfo.InvariantCulture)` per Phase 0-F rule (`docs/memo/phase-0-f-exit-2026-04-26.md:71`). `hurt` boolean serializes as JSON `true`/`false` literals (no culture sensitivity).

**Out of scope for `decision.v1` (deferred):**

- **Multi-step planning / pathfinding.** A* exists at `decompiled/XRL.World.AI.Pathfinding/FindPath.cs:84-135` but is over-scope for a 50-turn Joppa heuristic. Phase 0-G stays single-step. Multi-step `AutoExplore`-style chains deferred to Phase 0b (`docs/architecture-v5.md:2825-2834`) and later.
- **Resource management.** Ignored. Hunger, thirst, water, food, and ability cooldowns are observed via `[state]`/`[build]`/`[caps]` but not consumed by the heuristic. Phase 2a (`docs/architecture-v5.md:2866-2933`) adds resource-aware decision-making.
- **Ability activation.** Phase 0-G dispatches only `Move` and `AttackDirection`. Active mutations / equipment abilities deferred to Phase 0b.
- **Conversation / popups / modals.** Phase 0-G does not handle conversations, ability-targeting prompts, level-up dialogs, or any popup. The `:838` energy guard plus Layer-4 `PreventAction` shields against these by suppressing keyboard-input branches; if a popup nonetheless surfaces, the run-failure mode is "deadlock" (no `[cmd]` for >5 game turns), which is one of the 5-run gate's failure conditions.
- **Item management.** No pickup, drop, equip, unequip, throw, fire, eat. The acceptance run on Warden depends on starting equipment + visible-cell hostiles only.
- **`PassTurn` as an explicit branch.** The branch enum is `"flee" | "attack" | "explore"`. `PassTurn` is a *fallback*, never a *decision*; if Phase 0-G+ ever wants to record "the heuristic chose to wait", that bumps the schema to `decision.v2`.
- **External command source.** Phase 1 is the WebSocket-bridge phase. Phase 0-G's command source remains the in-process heuristic.
- **C# unit tests.** Deferred to Phase 2a per ADR 0004.

**Error posture (inherits Phase 0-F 3-layer drain + ADR 0007 PreventAction scope):**

- **Outer try/catch/finally** is the same shape as Phase 0-F's handler at `mod/LLMOfQud/LLMOfQudSystem.cs:181-378`.
- **Decision-time exception** (e.g., `ScanAdjacentHostile` throws because of a partially-constructed Zone). Catch emits `[decision]` sentinel + `[cmd]` sentinel; energy-drain ladder runs as in Phase 0-F. The two sentinels guarantee the parser sees a well-formed `[decision]` and `[cmd]` per turn even on this path.
- **Decision-emitted then execution-time exception** (e.g., `Move` throws because of a tutorial intercept failure). Catch emits `[cmd]` sentinel only — `[decision]` was already published. The `decisionEmitted` boolean flag determines this branch.
- **Layer 1 (normal success)**: `Move`/`AttackDirection` drain energy on success (Phase 0-F semantics).
- **Layer 2 (`result==false && !energySpent`)**: `PassTurn()` is called inside the `try` block. Same as Phase 0-F.
- **Layer 3 (`PassTurn` itself throws)**: catch falls back to `player.Energy.BaseValue = 0`. Documented non-equivalence with `PassTurn` (skips `UseEnergyEvent`) per ADR 0006 Consequence #5.
- **Layer 4 (`PreventAction = true` only when post-recovery energy still ≥ 1000)** per ADR 0007 — unchanged.
- **`[decision]` failure does not affect `[cmd]`.** And vice versa — both emit independently from the game thread, both fall back to sentinels under exception. The four observation channels run on the render thread via `AfterRenderCallback` from `PendingSnapshot` and are unaffected by either game-thread emission failure.

**Files modified / created:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Replace the body of `HandleEvent(CommandTakeActionEvent E)` at `:181-378` with the decision-then-execute pseudocode above. The existing 3-layer drain + ADR 0007 `finally` block is preserved verbatim; the new code adds a Decision phase before the existing Execute phase.
  - Add the `ChooseFleeDir`, `ChooseExploreDir`, `IsSafeCell` private static helpers as new methods on `LLMOfQudSystem` (or `SnapshotState`, see below).
- Modify: `mod/LLMOfQud/SnapshotState.cs`
  - Add `internal struct DecisionRecord` (mirrors `CmdRecord` shape) and `BuildDecisionJson(DecisionRecord r)` / `BuildDecisionSentinelJson(int turn, Exception ex)` static methods. The struct carries the per-turn variable fields; `schema` and `error` are emitted as constants by the builders. Together, struct + builder produce the v1 schema's 11 emitted JSON keys.
  - The safe-cell + flee-dir + explore-dir helpers live in `SnapshotState` (consistent with Phase 0-F's pattern of pure-data helpers in `SnapshotState`), OR remain in `LLMOfQudSystem` as private statics (consistent with Phase 0-F's pattern of game-state-reading code in `LLMOfQudSystem`). The plan picks the latter: scanning the player's surroundings reads `The.Player`/`Cell` and is more naturally co-located with the `HandleEvent` consumer. `BuildDecisionJson` / `BuildDecisionSentinelJson` are pure-data and live in `SnapshotState`.
- Create: `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` — narrow ADR documenting the interrupt-semantics interpretation, the heuristic-specific lock (branch order, hurt threshold), and the new `[decision]` channel decision (preferred over schema bumping `command_issuance.v1`).
- Create: `docs/memo/phase-0-g-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-f-exit-2026-04-26.md`'s shape.

No manifest edits. No symlink changes. No new dependencies. The Roslyn compile set stays at 3 files.

**Acceptance criteria (rollup against `docs/architecture-v5.md:2811-2817`):**

A Phase 0-G acceptance run is PASS iff all of the following hold:

1. **Compile clean.** `build_log.txt` shows `Compiling 3 file(s)... Success :)` for `LLMOfQud`. No `COMPILER ERRORS`. No `MODWARN CS0618` (obsolete-API hygiene from Phase 0-D / 0-E).
2. **5-run survival gate (`:2812`).** Five fresh-chargen Warden runs (Mutated Human + Warden subtype + Roleplay mode + standard preset mutations) executed sequentially in a single CoQ launch OR five fresh launches if stability requires isolation. **At least 3 of the 5 runs survive ≥50 `[cmd]` records** with the player alive at turn 50 (the `[state]` line for turn 50 has `player.hp > 0`). A failing run is one that ends in any of: death before turn 50, game crash, deadlock (no new `[cmd]` for >5 seconds of wall time while the game process is alive), parity loss on a surviving run (turn-N has `[cmd]` but missing one or more of `[decision]/[state]/[caps]/[build]`).
3. **No-crash gate (`:2815`).** All 5 runs complete without a CoQ process crash. Death-before-50 is allowed (counted toward the 2-failure tolerance); CoQ process crash is NOT.
4. **Observation accuracy gate (`:2816`).** A separate "observation audit" pass (which may be one of the 5 runs OR a sixth dedicated run) samples 20 random turns from the run's `[state]` records and compares to actual game state captured via screen recording. **At least 19 of 20 sampled turns match** on all of: `player.hp` (live HP integer), `player.pos` (`x`, `y`, `zone` triple), `entities[]` set (set equality on `id` keys, modulo entities that were on screen but out of `[state]` filter — see below). 19/20 = 95%; the architecture-v5.md text at `:2816` is 99%; we operationalize 95% as the per-sample-pass criterion at N=20 (the smallest representable rate at N=20 is 95% = 19/20, so 99% is mathematically unreachable at this sample size). Per ADR 0008 Decision #6, if a tighter audit is required, escalate to **N=100 sampled turns** (allowing at most 1 mismatch = 99% per-sample-pass), which preserves the spirit of `:2816` exactly.
5. **Interrupt latency gate (`:2817`).** Per ADR 0008, this exit criterion is satisfied by the heuristic same-turn branch interruption. Acceptance procedure: spawn an adjacent hostile via `wish testhero:<blueprint>` at a turn N where the player was previously not in combat; verify the `[decision]` line for turn N has `branch == "attack"` (or `"flee"` if `hurt == true`), NOT `"explore"`. AutoAct-level interrupt (`decompiled/XRL.Core/ActionManager.cs:834-837`) is NOT required to fire — Phase 0b owns that.
6. **Hard error gate.** `ERR_SCREEN == 0` across all 5 runs. Soft gates: `ERR_STATE / ERR_CAPS / ERR_BUILD / ERR_DECISION / ERR_CMD == 0`. Non-zero counts trigger an exit-memo entry and are an ADR re-open candidate.
7. **Latest-line JSON validity.** The latest `[decision]` and `[cmd]` lines on each surviving run pass `json.loads`, are non-sentinel, and have `schema == "decision.v1"` / `schema == "command_issuance.v1"` respectively.
8. **Every-line JSON validity + schema/key-set.** All `[decision]` lines on all 5 runs parse cleanly. For each non-sentinel line: `schema == "decision.v1"` AND key set is exactly `{turn, schema, branch, hp, max_hp, hurt, adjacent_hostile_dir, adjacent_hostile_id, chosen_dir, fallback, error}`. Sentinel-error lines (`{turn, schema, error}`) are tolerated but reported.
9. **Phase 0-G semantic invariants.** Across non-sentinel turns of all surviving runs:
   - `branch ∈ {"flee", "attack", "explore"}`. Any other value is a hard failure for v1.
   - `branch == "attack"` IMPLIES `adjacent_hostile_dir != null && hurt == false`.
   - `branch == "flee"` IMPLIES `hurt == true && adjacent_hostile_dir != null`.
   - `branch == "explore"` IMPLIES `adjacent_hostile_dir == null`.
   - `branch == "attack"` IMPLIES `chosen_dir == adjacent_hostile_dir`.
   - `hurt == true` IMPLIES `hp <= max(8, floor(max_hp * 0.60)) && adjacent_hostile_dir != null`.
   - `fallback ∈ {null, "boxed_in_attack", "no_safe_cell_pass"}`.
   - `fallback == "boxed_in_attack"` IMPLIES `branch == "flee"` AND the same-turn `[cmd].action == "AttackDirection"`.
   - `fallback == "no_safe_cell_pass"` IMPLIES the same-turn `[cmd].fallback == "pass_turn"`.
10. **Cross-channel correlation.** For each turn N appearing in any `[cmd]` line: there exists a `[decision]` line with the same `turn`, AND for each branch label `branch` the action types are consistent: `"attack"` ↔ `[cmd].action == "AttackDirection"`, `"flee"` ↔ `[cmd].action ∈ {"Move", "AttackDirection"}`, `"explore"` ↔ `[cmd].action == "Move"`.
11. **Phase 0-F invariants preserved.** Every Phase 0-F acceptance gate (cross-channel parity for the 5 prior channels, JSON validity, energy-drain semantics) holds on all 5 runs. `[cmd]`'s schema stays at `command_issuance.v1`.
12. **Spec-correction ADR landed.** ADR 0008 is committed before the implementation lands. See "ADR 0008 timing" below.
13. **Exit memo committed.** `docs/memo/phase-0-g-exit-<YYYY-MM-DD>.md` exists on the branch.

**Empirical probes required BEFORE locking acceptance criteria (sequenced):**

The probes resolve the load-bearing empirical claims this design makes (codex Q9; project rule per `feedback_empirical_claim_probe_before_lock.md`). Probes are run on a sacrificial CoQ session AFTER the readiness PR (PR-G1) merges but BEFORE the implementation PR (PR-G2) opens. PROBE 1 is baseline-only (informational, never gating). PROBE 2-4 are pass/fail; if any falsifies a spec-locked parameter, the spec is amended via a follow-up docs-only **PR-G1.5 spec-amendment** PR (branch `docs/phase-0-g-spec-amendment-probe<N>` cut from `main`) which must merge before PR-G2 opens. Pushing to PR-G1's readiness branch is NOT an option — that branch is squash-merged and deleted by the time probes run. PROBE 5 runs against the full implementation as part of Task 5 acceptance. See plan Task 1 for the operational workflow.

1. **PROBE 1 — Joppa east-bias 50-turn survival (BASELINE ONLY).** Run the unmodified `main` HEAD MOD (Phase 0-F: east-Move + adjacent-attack, no decision logic). Launch a fresh Warden, observe up to 50 `[cmd]` turns. **Informational only — NOT a pass/fail gate for PR-G2.** Records whether the existing handler survives 50 turns alone (which sets the heuristic's improvement floor) and identifies the killing entity if not. The only PROBE 1 outcome that pauses the phase is "fundamentally impossible without resource management" → escalate to user. (Joppa start is `JoppaWorld.11.22.1.1.10@37,22` per `Base/EmbarkModules.xml:275-277`; Joppa.rpm has open ground east of x=39.)
2. **PROBE 2 — Hurt threshold sweet spot.** Launch a fresh Warden, take damage to bring HP through bands `90% → 70% → 60% → 50% → 40% → 30%` of `baseHitpoints`. At each band, check whether the proposed `hp <= max(8, floor(max_hp * 0.60))` formula correctly classifies the player as `hurt` AND whether the hurt-bot's `flee` branch reaches a safe cell within 3 turns. PASS if 60% triggers flee at survivable HP for at least 5 different damage scenarios. If 60% is too eager (flee triggered when attack would have been safer) or too slow (flee triggered after lethal damage was inevitable), spec-amend the threshold ratio. The `8` HP floor exists for low-baseHP characters; on Warden with baseHP ~28, the floor is dominated by the ratio (`floor(28 * 0.60) == 16`).
3. **PROBE 3 — Flee safe-cell predicate.** With the player in a Joppa cell, spawn an adjacent hostile at a known direction. Verify the `IsSafeCell` predicate correctly identifies the inverse-direction cell as safe (or unsafe) in 8 controlled scenarios (one per direction). PASS if all 8 scenarios match operator expectation. The probe also exercises the boxed-in branch by parking the player in a 2-wall building corner (3 of 8 directions blocked by wall) and then spawning hostiles into the remaining 5 cells, leaving zero safe directions — this is the exact runtime condition that triggers `flee → boxed_in_attack`. (The earlier "7 of 8 cells" framing leaves one safe cell and cannot exercise the boxed-in branch; see plan PROBE 3 sub-test 3c.)
4. **PROBE 4 — Same-turn interrupt.** Launch a fresh Warden in `explore` mode (no adjacent hostiles). On turn N, spawn an adjacent hostile via `wish testhero:Snapjaw scavenger` (the Phase 0-F-validated blueprint). Verify the `[decision]` line for turn N has `branch == "attack"` (player at full HP, so not flee). PASS if the same-turn branch correctly observes the new hostile and chooses `attack`, NOT `explore`.
5. **PROBE 5 — Channel correlation under branch mix.** Run a 50-turn session with a mix of explore turns, attack turns, and (if possible) flee turns. PASS if every `[cmd]` line has a matching `[decision]` line by `turn` field AND the `branch ↔ action` invariant in criterion 10 holds for every line.

Probe 1 runs the unmodified `main` HEAD MOD; probes 2-4 use the actual MOD with temporary diagnostic stubs; probe 5 runs against the full implementation. Probe 2 needs HP-controlled damage delivery (`wish damage` / `wish heal`); probe 3 needs spawn control over 8 directions; probe 4 needs `wish testhero:Snapjaw scavenger`. **PROBE 1 records baseline data (informational only). PROBES 2–4 MUST PASS before the implementation PR (PR-G2) opens.** Probe 5 is run as part of the implementation phase's acceptance and is captured here for completeness.

**Open hazards / future revisit:**

- **`fallback == "no_safe_cell_pass"` from `flee` is logically unreachable** but is part of the schema for defensive completeness. If observed in a run, it indicates a `ChooseFleeDir` bug (the function should always return a non-null `chosenDir` when `hurt && adjacent_hostile_dir != null`). Re-open trigger.
- **Tutorial intercept on first turn** (Phase 0-F open hazard `mod/LLMOfQud/LLMOfQudSystem.cs:245-247`). If the first `Move("E")` triggers the tutorial intercept (`decompiled/XRL.World/GameObject.cs:15336-15338`), the heuristic's explore branch returns `result==false` and the cmd-fallback `"pass_turn"` fires. The `[decision]` line for that turn still records `branch == "explore"`. Acceptance counts that turn as part of the 50-turn budget; if more than ~3 turns are tutorial-eaten, the run-failure mode is "ran out of turn budget for survival proof". Operator instruction: skip the tutorial before the 50-turn run begins.
- **Hostile-interrupt path in ActionManager remains no-op** (Phase 0-F open observation). Phase 0-G does not engage `AutoAct.Setting`, so `decompiled/XRL.Core/ActionManager.cs:834-837`'s `CheckHostileInterrupt` returns early at `IsInterruptable() == false`. The 0-G heuristic's same-turn branch IS the interrupt mechanism, per ADR 0008. If a future phase engages AutoAct, the engine-level interrupt becomes load-bearing and must be re-tested.
- **Engine-speed autonomy (Phase 0-F-introduced).** Phase 0-G inherits this hazard. Phase 1 (WebSocket bridge) owns the fix. Phase 0-G runs at engine speed; the 5-run acceptance completes in seconds of wall time.
- **Cooldown decrement (`[caps].cooldown_segments_raw > 0`)** still NOT EXERCISED through Phase 0-F. Phase 0-G runs Warden, which has standard preset mutations; if any mutation has a cooldown that decrements per turn (unlikely without ability activation, but possible passively), this phase may be the first to exercise the field. Re-open trigger if `[caps].cooldown_segments_raw` ever reads non-zero on a 0-G acceptance run.
- **Multi-mod coexistence** still untested.
- **Save/load resilience** still untested.

**ADR 0008 timing — separate prerequisite docs PR (Phase 0-E / 0-F precedent):**

ADR 0008 is narrow scope (interrupt-semantics interpretation + heuristic specifics + new `[decision]` channel decision). It does not reinterpret frozen architecture-v5.md text the way ADR 0006/0007 did, but it does formally add a sixth observation channel and a new schema, both of which are visible to Phase 1. Two viable orderings (same shape as Phase 0-F):

1. **Separate prerequisite docs-only PR** (Phase 0-C / 0-E / 0-F precedent): docs PR-G1 lands ADR 0008 + this spec + the implementation plan; impl PR-G2 opens against `main` after PR-G1 merges.
2. **Single PR with ADR commit first**: impl branch opens with commit 1 = ADR 0008, commits 2..N = code + spec + plan + memo.

**Decision (recorded in ADR 0008):** option (1), separate prerequisite docs-only PR. Phase 0-C / 0-E / 0-F all used option (1).

**References:**

- `docs/architecture-v5.md` (v5.9, frozen): `:2804` (Phase 0-G line being implemented), `:2811-2817` (Phase 0 exit criteria including 0-G's gates), `:2825-2834` (Phase 0b ownership of AutoAct interrupt), `:2836-2855` (Phase 1 WebSocket bridge consumer of `[decision]` and `[cmd]`), `:1787-1790` (game-queue routing rule).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0008.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — direct `Move`/`AttackDirection` API path inherited; `command_issuance.v1` schema-lock rule cited; new `[decision]` channel chosen over schema bump.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md` — `PreventAction` scope inherited verbatim; render fallback dependency unchanged.
- `docs/memo/phase-0-f-exit-2026-04-26.md` — Phase 0-F outcomes; §"Feed-forward for Phase 0-G / Phase 1" drives this design's branch-extension pattern; §"Open hazards" enumerates the carry-forward set this spec acknowledges.
- `docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md` — Phase 0-F spec; this spec mirrors its shape.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` — Phase 0-F plan; the 0-G plan models its task structure.
- CoQ APIs (verified 2026-04-26):
  - **Decision-time read**: `GameObject.hitpoints` / `baseHitpoints` (`decompiled/XRL.World/GameObject.cs:1177-1198`), `Statistic.Value` / `BaseValue` (`decompiled/XRL.World/Statistic.cs:218-252`).
  - **Hostile scan** (unchanged from Phase 0-F): `Cell.GetCellFromDirection` (`decompiled/XRL.World/Cell.cs:7322-7324`), `Cell.GetCombatTarget` (`decompiled/XRL.World/Cell.cs:8511-8558`), `GameObject.IsHostileTowards` (`decompiled/XRL.World/GameObject.cs:10887-10894`).
  - **Safe-cell predicate**: `Cell.IsEmptyOfSolidFor` (`decompiled/XRL.World/Cell.cs:5290-5305`), `Cell.GetDangerousOpenLiquidVolume` (`decompiled/XRL.World/Cell.cs:8597-8607`), `GameObject.PhaseAndFlightMatches` (transitively used by `IsEmptyOfSolidFor`).
  - **Action API** (unchanged): `GameObject.Move` (`decompiled/XRL.World/GameObject.cs:15274-15290, 15719-15722`), `GameObject.AttackDirection` (`decompiled/XRL.World/GameObject.cs:17882-17902`), `AutoAct.ClearAutoMoveStop` (`decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`), `GameObject.PassTurn` (`decompiled/XRL.World/GameObject.cs:17543-17545`).
  - **CTA hook** (unchanged): `CommandTakeActionEvent` (`decompiled/XRL.World/CommandTakeActionEvent.cs:1-42`), `Check` returns `Object.HandleEvent(...) && !PreventAction` (`decompiled/XRL.World/CommandTakeActionEvent.cs:37-39`).
  - **ActionManager flow** (unchanged): inner action loop `decompiled/XRL.Core/ActionManager.cs:786-832`, `:838` energy guard, `:1797-1799` `PlayerTurn` call, `:1806-1808` render fallback, `:1828` `EndActionEvent.Send`.
  - **AutoAct interrupt (NOT engaged by 0-G)**: `decompiled/XRL.World.Capabilities/AutoAct.cs:95-102` `IsInterruptable()`, `decompiled/XRL.Core/ActionManager.cs:834-837` `CheckHostileInterrupt`. Cited because ADR 0008's interpretation of `:2817` rests on the fact that this path is reachable but no-op when AutoAct is inactive.
  - **A* pathfinding (NOT used by 0-G)**: `decompiled/XRL.World.AI.Pathfinding/FindPath.cs:84-135`. Cited as the explicit out-of-scope alternative.
  - **Cooldown decrement (NOT EXERCISED, hazard)**: `decompiled/XRL.Core/ActionManager.cs:1836-1839` `TickAbilityCooldowns`, `decompiled/XRL.World.Parts/ActivatedAbilities.cs:398-418` (path through which Warden's passive mutations might exercise the cooldown counter).
  - **Joppa starting zone**: `Base/EmbarkModules.xml:275-277` (`Joppa @ JoppaWorld.11.22.1.1.10@37,22`); `Base/Joppa.rpm:3634-3643` (the starting zone's east-lane cell layout, evidence for explore-east survival).
  - **Subtype data**: `Base/Subtypes.xml:288-299` (Warden subtype: Strength +2, LongBlades + Shield + Shield_Slam + Rifles + Pistol skills, Wardens reputation +300).
  - **MetricsManager.LogInfo** (unchanged sink): `decompiled/MetricsManager.cs:407-409`.
