# Phase 0-F: Movement / Attack Command Issuance — Design Spec

**Goal:** Issue movement and melee-attack commands autonomously from the MOD, ending each player decision point with one synchronous CoQ-API call (`GameObject.Move` or `GameObject.AttackDirection`) without keyboard input. Emit one structured `[LLMOfQud][cmd] {...}` JSON line per `CommandTakeActionEvent` dispatch — a fifth per-turn observation primitive alongside `[screen]` (0-B), `[state]` (0-C), `[caps]` (0-D), `[build]` (0-E). Phase 0-F is the first phase where the MOD acts on the game; all prior phases observed only.

**Pivot from spec line `:2803`:** v5.9 spec at `docs/architecture-v5.md:2803` originally framed this phase as "Movement/attack command issuance via `CommandEvent.Send()`". This design pivots to **direct `GameObject.Move` / `GameObject.AttackDirection` calls** because `CommandEvent.Send("CmdMoveE")` has no registered handler in the decompiled CoQ source — `XRLCore.PlayerTurn()` handles `Cmd*` strings by switching on the string and calling the underlying API directly (`decompiled/XRL.Core/XRLCore.cs:1107-1109` for `CmdMoveE` → `The.Player.Move("E")`; `:1270-1271` for `CmdAttackE` → `The.Player.AttackDirection("E")`). Sending `CommandEvent.Send(player, "CmdMoveE")` outside that switch would fire only the registered-event chain (any object with `HasRegisteredEvent("CmdMoveE")`) plus the pooled `CommandEvent`; neither path performs the actual move, and energy would not drain. The pivot also shifts the observation hook from `BeginTakeActionEvent` (used by 0-A through 0-E for observation) to `CommandTakeActionEvent` for command issuance — see Architecture below for why. The pivot requires a new ADR (numbered 0006, drafted as Task 0 of the implementation plan).

**Architecture:**

- **Game thread (`HandleEvent(CommandTakeActionEvent E)`)**: dispatch the action and emit the `[cmd]` line synchronously. The new `IPlayerSystem` event registration is added to `RegisterPlayer()`: `Registrar.Register(SingletonEvent<CommandTakeActionEvent>.ID)`. `CommandTakeActionEvent` fires inside the inner action loop (`decompiled/XRL.Core/ActionManager.cs:829`), AFTER `BeginTakeActionEvent` already enqueued the per-turn observation snapshot. Choosing `CommandTakeActionEvent` over `BeginTakeActionEvent` for issuance is deliberate: a `BeginTakeActionEvent` handler that dispatches an action would cause `ActionManager` to skip the entire inner action loop (`BeforeTakeActionEvent`, `CommandTakeActionEvent`, hostile-interrupt, AutoAct, brain goals, `EndActionEvent`) because that loop is gated by an `Energy.Value >= 1000` check that we would have just drained (`decompiled/XRL.Core/ActionManager.cs:786-800, 1797-1828`). `CommandTakeActionEvent` fires inside the loop — `flag2` is true, `EndActionEvent` still fires, and ActionManager's player render fallback runs after energy is spent (`decompiled/XRL.Core/ActionManager.cs:1806-1808`). The existing `[screen]/[state]/[caps]/[build]` pipeline stays unchanged.
- **Direct API path, not `CommandEvent.Send`.** Movement is `player.Move("E", DoConfirmations: false)` (`decompiled/XRL.World/GameObject.cs:15719-15722` overload, full signature at `:15274-15290`). Attack is `player.AttackDirection(dir)` (`:17882-17902`). Both spend energy synchronously on success: `Move` calls `UseEnergy(num3, "Movement", ...)` at `:15397-15400` (where `num3` defaults to 1000 for non-forced player movement, `:15289`); melee attack calls `UseEnergy` inside `Combat.MeleeAttackWithWeapon` at `decompiled/XRL.World.Parts/Combat.cs:794-798` after `AttackCell` resolution (`:877-889`). `Forced: true` is rejected because it sets the energy cost to 0, breaking turn semantics; `DoConfirmations: false` bypasses the player liquid/stairs/danger confirmation popups gated by `DoConfirmations && IsPlayer()` at `decompiled/XRL.World/GameObject.cs:15630-15699`.
- **`AutoAct` mirror.** The CoQ `case "CmdMoveE"` in `XRLCore.PlayerTurn()` is two statements: `AutoAct.ClearAutoMoveStop(); The.Player.Move("E");` (`decompiled/XRL.Core/XRLCore.cs:1107-1109`). `ClearAutoMoveStop()` only sets `GameObject.AutomoveInterruptTurn = int.MinValue` (`decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`) — idempotent, no-op when no AutoAct is active. The Phase 0-F handler explicitly calls `AutoAct.ClearAutoMoveStop()` before each `Move` to mirror the `CmdMoveE` wrapper semantics. The attack path does not need this call (`case "CmdAttackE"` at `XRLCore.cs:1270-1271` does not invoke `ClearAutoMoveStop()`).
- **`PreventAction` not energy-skip.** `CommandTakeActionEvent.Check` returns `Object.HandleEvent(...) && !PreventAction` (`decompiled/XRL.World/CommandTakeActionEvent.cs:37-39`). Setting `E.PreventAction = true` causes the surrounding `if (!CommandTakeActionEvent.Check(Actor)) continue;` at `ActionManager.cs:829-832` to short-circuit the loop iteration. The handler returns `true` from `HandleEvent` — returning `false` would abort event dispatch in CoQ's `EventRegistry` chain (`decompiled/XRL.Collections/EventRegistry.cs:260-272`) and the parts/effects chain (`decompiled/XRL.World/GameObject.cs:14024-14030, 14053-14059`), unintentionally suppressing other registered handlers on the same event. (The StickyTongue precedent at `decompiled/XRL.World.Parts.Mutation/StickyTongue.cs:53-72` returns `false` from `BeginTakeActionEvent`, where ActionManager explicitly zeroes energy on a false `Check` (`ActionManager.cs:786-791`); the symmetric treatment does NOT exist for `CommandTakeActionEvent` (`:829-832` only `continue`s, energy is not cleared).
- **Game-thread direct emit for `[cmd]`, NOT through `PendingSnapshot`.** `[cmd]` is emitted via `MetricsManager.LogInfo` synchronously inside `HandleEvent(CommandTakeActionEvent)`. `PendingSnapshot` keeps its single observation slot (`StateJson, DisplayMode, CapsJson, BuildJson`) and is NOT extended for `[cmd]`. Rationale: (a) `PendingSnapshot` is consumed by `AfterRenderCallback` on the render thread; staging `[cmd]` through it would couple command cadence to render cadence — a hazard because direct `Move`/`AttackDirection` may shift the render cadence (`PlayerTurn()` is normally what triggers the render in `ActionManager`'s player branch, and Phase 0-F changes the path that energy drain takes). The `ActionManager` player render fallback at `:1806-1808` runs after energy is spent on the `CommandTakeActionEvent` path, so existing `[screen]/[state]/[caps]/[build]` still flush; the new `[cmd]` line is decoupled from that flush by design. (b) `MetricsManager.LogInfo` is just `UnityEngine.Debug.Log("INFO - " + Message)` with no special CoQ event dispatch (`decompiled/MetricsManager.cs:407-409`), safe to call from the game thread.
- **Per-turn output: 6 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]` + 1 `[cmd]`. The first 5 emit on the render thread via `AfterRenderCallback`; `[cmd]` emits on the game thread inside `HandleEvent(CommandTakeActionEvent)`. **Parser correlation contract: `[cmd]` and the four observation channels MUST be correlated by the `turn` field, never by line adjacency or count parity.** Other CoQ subsystems' `LogInfo` lines may interleave between any two of the six. This rule extends the existing comment at `mod/LLMOfQud/LLMOfQudSystem.cs:224-231` to cover `[cmd]`.

**Step A / Step B logic (single phase, both inside one handler):**

`HandleEvent(CommandTakeActionEvent E)` runs Step B detection first, falls back to Step A move-east when no hostile is adjacent. Pseudocode:

```
HandleEvent(CommandTakeActionEvent E):
  bool energySpent = false
  GameObject player = The.Player
  int turn = _beginTurnCount
  try:
    int energy_before = player.Energy.Value
    pos_before = {x: player.CurrentCell.X,
                  y: player.CurrentCell.Y,
                  zone: player.CurrentCell.ParentZone.ZoneID}

    # Step B: adjacent hostile detection (priority N -> NE -> E -> SE -> S -> SW -> W -> NW)
    string targetDir = null
    GameObject targetObj = null
    foreach dir in ["N","NE","E","SE","S","SW","W","NW"]:
      Cell adj = player.CurrentCell.GetCellFromDirection(dir, BuiltOnly:false)
      if adj == null: continue
      GameObject t = adj.GetCombatTarget(
        player,
        IgnoreFlight: false, IgnoreAttackable: false, IgnorePhase: false,
        Phase: 5, AllowInanimate: false,
        Filter: o => o != player && o.IsHostileTowards(player))
      if t != null:
        targetDir = dir; targetObj = t; break

    bool result
    string action; string dir
    target_id = target_name = null
    target_pos_before = target_hp_before = null

    if targetObj != null:
      target_id = targetObj.ID
      target_name = targetObj.ShortDisplayNameStripped
      target_pos_before = {x: targetObj.CurrentCell.X,
                           y: targetObj.CurrentCell.Y,
                           zone: targetObj.CurrentCell.ParentZone.ZoneID}
      target_hp_before = targetObj.hitpoints   # Statistic.Value (live)
      result = player.AttackDirection(targetDir)
      action = "AttackDirection"; dir = targetDir
    else:
      AutoAct.ClearAutoMoveStop()              # mirror CmdMoveE wrapper
      result = player.Move("E", DoConfirmations:false)
      action = "Move"; dir = "E"

    energySpent = (player.Energy.Value < energy_before)

    string fallback = null
    if !result and !energySpent:
      player.PassTurn()                        # UseEnergy(1000,"Pass",Passive:true)
      energySpent = true
      fallback = "pass_turn"
    elif !result and energySpent:
      fallback = "pass_turn"                   # log accounting; API spent energy on its own fail path

    int energy_after = player.Energy.Value
    pos_after = {x: player.CurrentCell.X,
                 y: player.CurrentCell.Y,
                 zone: player.CurrentCell.ParentZone.ZoneID}
    int? target_hp_after = (targetObj != null) ? targetObj.hitpoints : null

    EmitCmdFullRecord(turn, action, dir, result, fallback,
                      energy_before, energy_after,
                      pos_before, pos_after,
                      target_id, target_name, target_pos_before,
                      target_hp_before, target_hp_after,
                      error: null)
  catch Exception ex:
    EmitCmdSentinel(turn, ex)                  # reduced {turn, schema, error}
    # Avoid double-spend: only drain if action API hadn't already drained.
    # Energy.Value capture inside catch is a fresh read; energy_before may be
    # unavailable if the exception fired before its capture.
    if player?.Energy != null and player.Energy.Value >= 1000:
      try: player.PassTurn() catch: pass       # Pass may itself throw; swallow
      if player.Energy.Value >= 1000:
        player.Energy.BaseValue = 0            # last-ditch ONLY (see error posture)
  finally:
    E.PreventAction = true
  return true
```

**Direction priority** is fixed at `N → NE → E → SE → S → SW → W → NW`, deterministic and decompiled-source-agnostic (CoQ's internal direction ordering is not a stable contract). The first cell with a hostile target wins; same-distance ties (all eight cells are at distance 1 by definition) resolve by this priority. Walking diagonal-first is intentional: it biases attacks toward orthogonal-aligned attackers when both an orthogonal and a diagonal hostile are present in the same turn — which matches CoQ's typical "attacker stepped from the side" pattern more often than "attacker stepped from straight ahead".

`Cell.GetCombatTarget` filter signature (verified): `Cell GetCombatTarget(GameObject Looker, bool IgnoreFlight = false, bool IgnoreAttackable = false, bool IgnorePhase = false, int Phase = 5, GameObject ForcedObject = null, GameObject Defender = null, GameObject Visible = null, GameObject Ignore = null, Predicate<GameObject> Filter = null, bool AllowInanimate = false)` per `decompiled/XRL.World/Cell.cs:8511-8557`. The filter `o => o != player && o.IsHostileTowards(player)` uses `GameObject.IsHostileTowards(GameObject)` (`decompiled/XRL.World/GameObject.cs:10887-10894`).

**Schema lock: `command_issuance.v1`.**

Full record (action attempted, no exception):

```json
{
  "turn": 42,
  "schema": "command_issuance.v1",
  "hook": "CommandTakeActionEvent",
  "action": "Move",
  "dir": "E",
  "result": true,
  "fallback": null,
  "energy_before": 1000,
  "energy_after": 0,
  "pos_before": {"x": 12, "y": 7, "zone": "JoppaWorld.53.3.0.0.10"},
  "pos_after":  {"x": 13, "y": 7, "zone": "JoppaWorld.53.3.0.0.10"},
  "target_id": null,
  "target_name": null,
  "target_pos_before": null,
  "target_hp_before": null,
  "target_hp_after": null,
  "error": null
}
```

Sentinel record (exception path) — reduced shape consistent with `[caps]` / `[build]` posture from Phase 0-D / 0-E:

```json
{
  "turn": 42,
  "schema": "command_issuance.v1",
  "error": {"type": "<ExceptionTypeName>", "message": "..."}
}
```

**Field semantics:**

- `turn`: integer, the same `_beginTurnCount` correlation key used by the four observation channels. Required for log-line correlation across the five-channel parser. `[cmd]` semantically represents "the command issued for observation turn N"; observation lines for turn N reflect state BEFORE the action, `[cmd]` for turn N reflects the action itself (and its energy/position deltas).
- `schema`: literal string `"command_issuance.v1"`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
- `hook`: literal string `"CommandTakeActionEvent"` in v1. Recorded explicitly so future phases (e.g., a second hook variant) can be distinguished without a schema bump.
- `action`: enum `"Move" | "AttackDirection"`. Future actions (use, throw, fire, abilities) bump to v2. The two v1 values are the only direct-API surfaces the architecture supports for autonomous dispatch in Phase 0-F.
- `dir`: enum `"N" | "NE" | "E" | "SE" | "S" | "SW" | "W" | "NW"` for both `Move` and `AttackDirection`. The literal `"E"` is the only value Step A emits; Step B emits whichever direction the priority scan resolved. **Never null in v1** — the handler always picks a direction (Step A defaults to `"E"`); a future `PassTurn`-only or stationary-action variant would set `dir: null`, requiring a v2 schema bump.
- `result`: boolean. The direct return value of `Move(...)` or `AttackDirection(...)`. `true` = action succeeded as understood by the API. `false` = action failed in the API's terms (wall hit without `Forced`, immobile, paralyzed, no target in cell, etc.). For `Move` the `flag` variable in the function (`decompiled/XRL.World/GameObject.cs:15282, 15309`) controls whether the fail path at `IL_0dcc` (`:15378-15382`) drains energy; in the Phase 0-F default case (`Forced=false`, no `Dashing`), `flag` stays `false` and a fail-path return does NOT drain energy → fallback fires.
- `fallback`: string-or-null. `null` when no fallback was needed (action succeeded OR the API drained energy on its own fail path). `"pass_turn"` when the handler called `PassTurn()` to ensure turn advancement, OR for log accounting when the API drained energy on its own fail path (we cannot distinguish "API drained on fail" from "API drained on success" without a per-API-flag inspection that the API does not expose; logging `"pass_turn"` whenever `result=false` is honest about the autonomy-preservation intent). Future fallback values (e.g., `"force_skip"`, `"interrupt"`) bump to v2.
- `energy_before`, `energy_after`: integer, `player.Energy.Value` captured at handler entry and at the moment of `[cmd]` emission. The delta proves the action consumed energy. **`energy_after < energy_before` is the canonical autonomy gate**, NOT `energy_after < 1000` — `ActionManager` adds `Actor.Speed` to `Energy.BaseValue` once per segment before the action loop (`decompiled/XRL.Core/ActionManager.cs:785`), so `energy_before` can exceed 1000 for high-Speed actors and the literal-1000 threshold would misjudge. Within a single `HandleEvent` invocation no `Actor.Speed` add can sneak in: `CommandTakeActionEvent.Check` runs synchronously inside the action loop iteration (`ActionManager.cs:829`), the `Speed` add (`:785`) happens before the loop entered.
- `pos_before`, `pos_after`: object `{"x": int, "y": int, "zone": string}`. `x` / `y` are zone-local cell coordinates from `player.CurrentCell.X` / `.Y`. `zone` is `player.CurrentCell.ParentZone.ZoneID` — the canonical zone identifier (e.g., `"JoppaWorld.53.3.0.0.10"`). Existing `[state]` already emits `pos.x/y/zone` with the same accessor (`mod/LLMOfQud/SnapshotState.cs:177, 206-211`). The Phase 0-F shape mirrors `[state]` exactly. Including `zone` (rather than just `{x,y}`) protects against the `Move` zone-cross path: when direction crosses a zone boundary, `Move` calls `ProcessEnteringZone(...)` and the player's active zone changes (`decompiled/XRL.World/GameObject.cs:15384, 15404-15409`); `pos_after.zone != pos_before.zone` is the parser-side zone-transition signal. `GameObject.CurrentZone` is just `CurrentCell?.ParentZone` (`decompiled/XRL.World/GameObject.cs:473`); `Zone.ZoneID` is stable within a save (`decompiled/XRL.World/Zone.cs:389`, `ZoneManager.cs:273, 932`).
- `target_id`: string-or-null. `targetObj.ID` (`decompiled/XRL.World/GameObject.cs:340-350, 389-399`). Stable across the same actor's lifetime; survives save/load. Emitted as JSON `null` when no hostile was attacked (Step A move-east branch, or Step B but no adjacent hostile found).
- `target_name`: string-or-null. `targetObj.ShortDisplayNameStripped` (`decompiled/XRL.World/GameObject.cs:763-766`) — markup-stripped human-readable name. JSON `null` on the same condition as `target_id`.
- `target_pos_before`: object-or-null. `{x, y, zone}` of the target cell at the moment Step B detection captured it. JSON `null` when no target.
- `target_hp_before`, `target_hp_after`: integer-or-null. `targetObj.hitpoints` — current effective HP via `Statistic.Value` (`decompiled/XRL.World/GameObject.cs:1177-1198`, `Statistic.cs:238-252`). NOT `baseHitpoints` (which is the cap via `Statistic.BaseValue` at `:218-233`). The delta `target_hp_after < target_hp_before` is the Step B acceptance signal that the attack landed a damage event. JSON `null` on no-target.
- `error`: object-or-null. JSON `null` on full record. On sentinel record, the full line is reduced to `{turn, schema, error}` with `error: {"type": "<ExceptionType>", "message": "..."}`. Both `type` and `message` use the existing `SnapshotState.AppendJsonString` helper for RFC-8259 escape (control characters, U+2028, U+2029 — same defense-in-depth as 0-D/0-E sentinels).

**JSON null discipline (Phase 0-E rule 5 forced helper extraction).** `mod/LLMOfQud/SnapshotState.cs:30-47` `AppendJsonString` emits `""` (empty quoted string) for null input, NOT JSON `null`. v1 `[cmd]` has 5 nullable string-or-object fields (`target_id`, `target_name`, `target_pos_before`, `target_hp_before`, `target_hp_after`) — the Phase 0-E rule "extract a helper at the 5th occurrence" is met. The implementation MUST extract:
- `AppendJsonStringOrNull(StringBuilder sb, string s)` — emits `null` when `s == null`, else `AppendJsonString(sb, s)`.
- `AppendJsonIntOrNull(StringBuilder sb, int? n)` — emits `null` when `n == null`, else `n.Value` as digits.
- `AppendJsonObjectOrNull` is unnecessary (the position objects are inlined; the null-vs-object branch lives at the call site for clarity).

The existing 4 nullable string call sites in `SnapshotState.cs` (Phase 0-E `genotype_id`, `subtype_id`, `hunger`, `thirst`) MUST be migrated to the new helper as part of Phase 0-F's hygiene step. This is the documented carry-forward from `docs/memo/phase-0-e-exit-2026-04-26.md:60`: "When a 5th occurrence lands, extract a helper `AppendJsonStringOrNull(sb, value)`."

**Out of scope for `command_issuance.v1` (deferred):**

- **Heuristic logic beyond single if/else.** Phase 0-G (`docs/architecture-v5.md:2804`) is the heuristic-bot phase ("flee if hurt, attack if adjacent, explore otherwise"). Phase 0-F deliberately stops at one if/else (adjacent hostile? → attack : move-east), no internal state, no path memory, no flee, no resource awareness. Drawing the 0-F/0-G boundary at "single stateless if/else" is a defensible cut documented in ADR 0006.
- **Other action surfaces.** `Use`, `Throw`, `Fire`, `Activate ability`, `Talk`, `Pickup`, `Drop`, `Open inventory`, etc. All deferred to Phase 0b ("Can We Act on Abilities?") and later. v1 `[cmd]` schema's `action` enum is `"Move" | "AttackDirection"` — adding actions requires v2 + ADR.
- **External command source.** Phase 1 is the WebSocket-bridge phase (`:2836-2855`); Phase 0-F's command source is the hardcoded if/else. Reading commands from a file/socket is explicitly deferred.
- **Auto-walk / multi-turn move chains.** `AutoMove`, `AutoExplore`, multi-step pathfinding — deferred to 0-G+. The handler runs once per `CommandTakeActionEvent`; one event = one action.
- **`PassTurn` as a directly-emittable action.** v1's `dir` is never null. A future `PassTurn`-as-action variant (e.g., resting, waiting on a tile) bumps to v2.
- **Energy delta for non-self actors.** `[cmd]` reports the player's `energy_before/after` only. Target energy is not captured (it's not part of the action's player-side accounting and adding it bloats the schema for a Phase 1+ use case that has not materialized).
- **Multiple-target attack accounting.** Cleave / area-of-effect attacks via `AttackDirection` may damage more than the targeted object; v1 captures only the explicitly-targeted `target_id`. Other damaged objects appear in `[state]` next turn (HP delta) and in CoQ message log; v1 does not enumerate them.
- **C# unit tests for command-issuance helpers.** Deferred to Phase 2a per ADR 0004 (Phase 0-C C# test infra deferral). Manual JSON-validity gate inherited.

**Error posture (3-layer drain, defense in depth):**

- **Outer try/catch** wraps the whole `HandleEvent` body. On exception, the `catch` emits the sentinel `[cmd]` line and falls into the energy-drain ladder. `finally` block sets `E.PreventAction = true` regardless of success/failure path — protects against the keyboard-input fallback even when the action dispatch itself faulted.
- **Layer 1 (normal success):** `Move` / `AttackDirection` drain energy synchronously on success. `energySpent = (player.Energy.Value < energy_before)` after the call. No fallback fires.
- **Layer 2 (action returned false, no energy drain):** `PassTurn()` is called inside the `try` block. `PassTurn` is `UseEnergy(1000, "Pass", null, null, Passive: true)` (`decompiled/XRL.World/GameObject.cs:17543-17545`) — emits `UseEnergyEvent` (`:2925-2930`), runs energy-cost adjustment, fires listeners. `fallback = "pass_turn"` recorded in the `[cmd]` line.
- **Layer 3 (exception thrown anywhere in the handler):** `catch` emits sentinel JSON. If `Energy.Value >= 1000` (i.e., neither the API nor the layer-2 PassTurn drained), try `PassTurn()` once inside an inner try/catch (swallow if it also throws). If energy is STILL `>= 1000`, `player.Energy.BaseValue = 0` as a **last-ditch emergency drain**.
- **Important non-equivalence.** `Energy.BaseValue = 0` is NOT a clean substitute for `PassTurn()`. `PassTurn` → `UseEnergy` → emits `UseEnergyEvent` (`decompiled/XRL.World/GameObject.cs:2925-2930`). Direct `BaseValue = 0` only runs the `Statistic` setter and `NotifyChange` (`decompiled/XRL.World/Statistic.cs:218-232`); it MAY fire `StatChange_*` / `StatChangeEvent` listeners (`Statistic.cs:646-673`), but it does NOT emit `UseEnergyEvent`. Any future system that depends on `UseEnergyEvent` from the player's turn-end MUST NOT depend on the catch-path Layer-3 drain emitting it. Layer 3 is reachable only when `PassTurn` itself throws (a pathological state like `Statistic` being null, save/load mid-turn, or a concurrent mutation), and is intentionally lossy on event emission to guarantee turn advancement at all costs. ADR 0006 Consequence #5 documents this. The implementation comment at the `BaseValue = 0` call site reproduces the non-equivalence note.
- **Per-field error not supported.** Whole-line sentinel only — same posture as 0-D `[caps]` and 0-E `[build]`. If `targetObj.hitpoints` reads throw (e.g., target despawned mid-handler), the whole `[cmd]` line for that turn is the sentinel. This keeps parser logic simple.
- **`[cmd]` failure does not affect the four observation channels.** The four observation channels run on the render thread via `AfterRenderCallback` from `PendingSnapshot`, which was published before `CommandTakeActionEvent` fires. A `[cmd]` exception cannot retroactively alter `[screen]/[state]/[caps]/[build]` for the same turn. (The reverse — observation-channel failure affecting `[cmd]` — is also impossible because they run on different threads and read different state.)

**Files modified / created:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs` — extend `RegisterPlayer()` to register `SingletonEvent<CommandTakeActionEvent>.ID`. Add new `HandleEvent(CommandTakeActionEvent E)` method implementing Step A / Step B logic + 3-layer drain + sentinel + game-thread direct emit.
- Modify: `mod/LLMOfQud/SnapshotState.cs` — add command-issuance JSON builders: a full-record builder that emits the locked `command_issuance.v1` shape, and a sentinel builder for the reduced `{turn, schema, error}` shape. The exact C# parameter list / struct vs. positional arguments is an implementation-plan choice; the locked surface is the JSON output, not the function signature. Extract `AppendJsonStringOrNull(StringBuilder sb, string s)` and `AppendJsonIntOrNull(StringBuilder sb, int? n)` helpers. Migrate the existing 4 nullable-string call sites in `SnapshotState.cs` (`genotype_id`, `subtype_id`, `hunger`, `thirst`) to the new helper.
- Create: `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — ADR documenting the API pivot from `CommandEvent.Send()` to direct `Move/AttackDirection`, hook choice (`CommandTakeActionEvent` not `BeginTakeActionEvent`), `AutoAct.ClearAutoMoveStop` mirror, threading decoupling, and the Layer-3 `BaseValue=0` non-equivalence consequence.
- Create: `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-e-exit-2026-04-26.md` shape.

No other source file changes. No manifest edits. The Roslyn compile set stays at 3 files (`LLMOfQudSystem.cs`, `SnapshotState.cs`, `LLMOfQudBootstrap.cs`).

**Acceptance criteria (rollup):**

A Phase 0-F acceptance run is PASS iff all of the following hold:

1. **Compile clean.** `build_log.txt` shows `Compiling 3 file(s)... Success :)` for `LLMOfQud`. No `COMPILER ERRORS` for the mod. No `MODWARN CS0618` (codebase-level obsolete-API hygiene from Phase 0-D / 0-E).
2. **Step A counts (movement-only run).** Fresh Mutated Human Marauder, spawned in or moved to a Joppa zone with a clear east lane (e.g., the central market street). Run length: ≥40 turns of `CommandTakeActionEvent` dispatch. Within that run:
   - **≥10 consecutive `[cmd]` records** with `action == "Move"`, `dir == "E"`, `result == true`, `pos_after.x == pos_before.x + 1`, `pos_after.y == pos_before.y`, `pos_after.zone == pos_before.zone`, `energy_before >= 1000`, `energy_after < energy_before`, and `fallback == null`.
   - At most **1 trailing `result: false, fallback: "pass_turn"`** record permitted at the run's terminal wall (the eleventh `[cmd]` line if the lane is exactly 10 cells long; the last line of the 40+-turn run otherwise).
   - **Cross-channel regression gate**: total `[screen] BEGIN == [screen] END == [state] == [caps] == [build] == [cmd] >= 40` over the run. (Equality across the five render-thread channels reaffirms 0-E parity; `[cmd]` count parity with the four is required for Step A specifically because Step A fires one command per `CommandTakeActionEvent` and `CommandTakeActionEvent` fires once per `BeginTakeActionEvent` segment in the normal path.)
3. **Step B counts (combat run).** Same character. Spawn an adjacent hostile via debug `wish testhero:<blueprint>` — empirical probe BEFORE locking the spec already verified the blueprint stays hostile post-spawn (see "Empirical probe required" below). Run length: ≥40 turns of `CommandTakeActionEvent` dispatch including the combat segment. Within that run:
   - **≥3 consecutive `[cmd]` records** with `action == "AttackDirection"` once the hostile is adjacent.
   - **≥1 of those 3** has `result == true`, `target_id != null`, `target_name != null`, `target_hp_after < target_hp_before` (using `hitpoints` — Statistic.Value live), `dir` matches the priority-scan winner (`N → NE → E → SE → S → SW → W → NW`).
   - Cross-channel regression gate: total `[screen] BEGIN == [screen] END == [state] == [caps] == [build] == [cmd] >= 40`. As Step A.
4. **Hard error gate.** `ERR_SCREEN == 0` on both runs. Soft gates: `ERR_STATE == 0`, `ERR_CAPS == 0`, `ERR_BUILD == 0`, `ERR_CMD == 0`. Non-zero counts are investigated and recorded in the exit memo; sentinel JSON is intentional defense in depth, but any non-zero count triggers an exit-memo entry and is an ADR re-open candidate.
5. **Latest-line JSON validity.** Latest `[cmd]` line on each run passes `json.loads` AND is non-sentinel (top-level keys do not include `error`) AND `schema == "command_issuance.v1"` AND required keys present (the full key set listed in "Field semantics"). If the very last `[cmd]` line of a run is a sentinel, the gate fails — graceful degradation across the run is fine, but the LAST observation must succeed (it is what the Brain would consume on a hot-resume).
6. **Every-line JSON validity + schema/key-set check.** All `[cmd]` lines on both runs parse cleanly. For each non-sentinel line: `schema == "command_issuance.v1"` AND the top-level key set is exactly `{turn, schema, hook, action, dir, result, fallback, energy_before, energy_after, pos_before, pos_after, target_id, target_name, target_pos_before, target_hp_before, target_hp_after, error}` (no missing, no extra). Sentinel-error lines (`{turn, schema, error}`) are tolerated but reported.
7. **Shape parity.** Evaluated only across non-sentinel lines: the first non-sentinel `[cmd]` line vs the last non-sentinel `[cmd]` line on each run have identical top-level keys. (Sentinel lines are excluded; criterion 6 already gates per-line.)
8. **Phase 0-F specific semantic invariants.** Across non-sentinel turns of both runs:
   - `hook == "CommandTakeActionEvent"` on every line.
   - `action ∈ {"Move", "AttackDirection"}`. Any other value is a hard failure for v1.
   - `dir ∈ {"N","NE","E","SE","S","SW","W","NW"}` (never null in v1).
   - `result ∈ {true, false}`.
   - `fallback ∈ {null, "pass_turn"}`.
   - `energy_after < energy_before` (canonical autonomy gate). Strict less-than: `energy_after == energy_before` is a hard failure (means no API drained energy and no fallback fired).
   - `result == false` IMPLIES `fallback == "pass_turn"`.
   - `pos_before` and `pos_after` are objects with exactly the 3 keys `{x, y, zone}`; `x`, `y` are integers; `zone` is a non-empty string.
   - Step A run only: `target_*` fields are all `null` on every non-sentinel line.
   - Step B run combat segment: at least one line has `target_id != null`, `target_name != null`, `target_pos_before != null`, `target_hp_before != null`, `target_hp_after != null`.
9. **No keyboard input observed.** Acceptance runs performed without operator pressing any key during the dispatch window (i.e., no `[KEY:...]` in the CoQ debug log between the first and last `[cmd]` of the run, if such logging is enabled; manual confirmation from the runner if not). The Phase 0-F autonomy claim is empirical, not theoretical: if `PlayerTurn()` were reached and waited on input, only manual intervention (or `PreventAction = true` working) would unblock it.
10. **Single-mod load order.** Acceptance runs performed with only `LLMOfQud` enabled (Phase 0-D / 0-E parity).
11. **Spec-correction ADR landed.** ADR 0006 is committed before the implementation lands. See "ADR 0006 timing" below for the merge order trade-off.
12. **Exit memo committed.** `docs/memo/phase-0-f-exit-<YYYY-MM-DD>.md` exists on the branch.

**Empirical probe required BEFORE locking acceptance criterion 3:**

Pick a candidate hostile blueprint (e.g., `Glowfish`, `Salt-spider`, `Pyrokinetic Mutant`) and execute the following sequence in a sacrificial CoQ session:

1. `wish testhero:<blueprint>` to spawn an adjacent hostile east of the player.
2. Verify in the message log / `[caps].entities` that the spawned creature shows hostile allegiance to the player.
3. Wait one turn without the player acting; confirm the creature does NOT immediately disengage / become peaceful / leave the cell.
4. Confirm the creature is in a state where `Cell.GetCombatTarget(player, ..., Filter: o => o.IsHostileTowards(player))` returns it (this is implicit if step 2 + step 3 hold, but verify by checking the CoQ debug overlay or manual `look-around` after the wish).

The chosen blueprint goes into the implementation plan as a hard constant. If no blueprint passes the probe, the acceptance criterion 3 falls back to "Step B run uses a NPC encounter wherever it occurs naturally"; this is allowed but increases run-to-run variance.

**Open hazards / future revisit:**

- **Tutorial intercept on first turn.** `Move` returns false without spending energy when `IsPlayer() && !TutorialManager.BeforePlayerEnterCell(cell)` (`decompiled/XRL.World/GameObject.cs:15336-15338`). Phase 0-F acceptance assumes the tutorial has been completed or skipped. If a fresh-character run hits the tutorial intercept, Step A's first move triggers the layer-2 `PassTurn` fallback for one turn while the tutorial-flag flips; this is allowed by criterion 8's `result == false IMPLIES fallback == "pass_turn"` rule but the exit memo MUST record the turn count.
- **Save/load resilience for `[cmd]`.** `CommandTakeActionEvent` registration survives save/load via the standard `IPlayerSystem` lifecycle (`RegisterPlayer` re-fires on load). The `_beginTurnCount` reset on new-game / chargen documented in `docs/memo/phase-0-e-exit-2026-04-26.md:74` also applies to the `[cmd]` `turn` field. v1 acceptance does NOT exercise save/load mid-run; if it does, the exit memo records the round-trip behavior. Re-open trigger if `[cmd]` for the first turn after `AfterGameLoadedEvent` shows `energy_before` / `pos_before` inconsistent with the post-load `[state]`.
- **Hostile interrupt during fallback `PassTurn`.** `ActionManager.cs:834-837` runs `AutoAct.CheckHostileInterrupt()` when the actor is the player and AutoAct is interruptible. Our handler sets `PreventAction = true`, which makes `CommandTakeActionEvent.Check` return false BEFORE the hostile-interrupt block at `:834-837`; the interrupt does not fire on the `[cmd]` path. If a future variant calls `PassTurn` from outside `HandleEvent(CommandTakeActionEvent)` — e.g., from `BeginTakeActionEvent` for a "rest" command — the interrupt path becomes relevant.
- **Brain Goals.** `ActionManager.cs:1763-1767` fires `Actor.Brain.FireEvent("CommandTakeAction")` for the player when goals are queued. v1 player has no Brain.Goals; if a future setup pre-queues goals (NPC body-swap?), our `[cmd]` could conflict with the goal-driven dispatch. v1 is gated to runs without queued goals; Step A / Step B acceptance both start from a fresh-spawn / freshly-wished state, no goals queued.
- **Multi-mod coexistence.** Untested across all six phases. Same posture as 0-B / 0-C / 0-D / 0-E.
- **`AutoAct.ClearAutoMoveStop` semantic divergence.** Phase 0-F calls `ClearAutoMoveStop()` to mirror the `CmdMoveE` wrapper. If a future phase / mod relies on `AutomoveInterruptTurn` retaining its prior value across player turns to suppress AutoAct, our explicit clear breaks that contract. Phase 0-G+ NPC-AutoMove scenarios revisit this.
- **`Move` with combat-object on the destination cell.** `Move` may resolve a combat path through the target cell instead of stepping (`decompiled/XRL.World/GameObject.cs:15344-15346, 15540-15563`). Step A's `Move("E")` against an east hostile would attack-via-Move rather than step. Step B detection runs FIRST, so the hostile is intercepted by the `AttackDirection` branch before Step A could see it. If the priority order ever changes, this hazard re-opens.
- **Direct API divergence from CoQ keypress wrapper.** Keypresses go through `ControlManager` → `CmdMoveE` switch → `XRLCore.PlayerTurn()` → `AutoAct.ClearAutoMoveStop(); Move("E")`. Our handler bypasses `ControlManager` and `XRLCore.PlayerTurn()`. Side effects of those layers (e.g., `Sidebar.SidebarTick++` at `:666`, `Keyboard.ClearMouseEvents` at `:706`, `MessageQueue` separator at `ActionManager.cs:792-795`) are skipped on `[cmd]`-driven turns. Acceptance criterion 9 does not require parity with keypress-driven sidebar/message-queue side effects — those are out of scope for autonomy. Phase 1+ (WebSocket bridge) will need to surface these via overlay JSON if the streaming layer needs them.

**ADR 0006 timing — separate prerequisite docs PR (precedent: Phase 0-C / 0-E):**

The ADR re-opens spec line `:2803`'s API surface. Two viable orderings:

1. **Separate prerequisite docs-only PR** (Phase 0-C / 0-E precedent): the ADR PR lands first; the implementation PR opens against `main` after the ADR is on `main`. Pro: clean review history. Pro: if the ADR is rejected, no code thrown away. Con: two PRs, two CI runs, one more merge step.
2. **Single PR with ADR commit first**: the implementation branch opens with commit 1 = ADR 0006, commits 2..N = code + spec + plan + memo. Pro: atomic ship. Con: ADR review happens alongside C# review.

**Decision (recorded in ADR 0006 itself):** option (1), separate prerequisite docs-only PR. Phase 0-C / 0-E precedent applies — both prior spec-pivoting phases used option (1). Merge order: ADR PR → spec/plan PR (this design + the implementation plan can co-land in one docs-only PR if convenient) → implementation PR.

If the user explicitly opts for option (2) at execution time, the implementation plan accommodates by reordering Task 0 (ADR commit) to be the first commit on the implementation branch and dropping the prerequisite-PR step. The plan documents both paths.

**References:**

- `docs/architecture-v5.md` (v5.9, frozen): `:2803` (Phase 0-F line being reinterpreted by ADR 0006), `:2804` (Phase 0-G heuristic-bot phase that 0-F intentionally does not enter), `:1787-1790` (game-queue routing rule).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0006.
- `docs/adr/0002-phase-0-b-render-callback-pivot.md` — render-callback emit pattern for the four observation channels (unchanged in 0-F).
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — precedent ADR for spec-line pivoting; ADR 0006 mirrors its template.
- `docs/memo/phase-0-e-exit-2026-04-26.md` — Phase 0-E outcomes and carry-forward rules; rule 5 (JSON null discipline + 5th-occurrence helper extraction) drives Phase 0-F's `AppendJsonStringOrNull` migration.
- `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` — precedent spec structure to model 0-F on.
- CoQ APIs (verified 2026-04-26):
  - **Event hook**: `CommandTakeActionEvent` (`decompiled/XRL.World/CommandTakeActionEvent.cs:1-42`), `Check` returns `Object.HandleEvent(...) && !PreventAction` (`:37-38`).
  - **ActionManager flow**: per-segment Speed add (`decompiled/XRL.Core/ActionManager.cs:785`), inner action loop (`:800-830`), `BeforeTakeActionEvent.Check` (`:819-826`), `CommandTakeActionEvent.Check` (`:829-832`), hostile interrupt (`:834-837`), Brain goals (`:1763-1767`), `PlayerTurn()` call (`:1797-1799`), player render fallback (`:1806-1808`), `EndActionEvent.Send` (`:1828`).
  - **`PlayerTurn()` switch** (the engine's keypress handler this design supersedes for autonomous dispatch): `CmdMoveE` → `Move("E")` (`decompiled/XRL.Core/XRLCore.cs:1107-1109`), `CmdAttackE` → `AttackDirection("E")` (`:1270-1271`).
  - **Movement API**: `Move` two-overload set (`decompiled/XRL.World/GameObject.cs:15274, 15719-15722`), energy-cost defaulting (`:15282, 15289, 15309`), tutorial intercept (`:15336-15338`), wall-hit/immobile/paralyzed paths (`:15351-15375`), zone-cross handling (`:15384, 15404-15409`), success energy spend (`:15397-15400`), confirmation popups (`:15630-15699`), failure path (`:15378-15382`).
  - **Attack API**: `AttackDirection` (`decompiled/XRL.World/GameObject.cs:17882-17902`), `Combat.AttackDirection` (`decompiled/XRL.World.Parts/Combat.cs:844-860`), `Combat.AttackCell` (`:877-889`), melee energy spend (`:794-799`).
  - **Hostile detection**: `Cell.GetCellFromDirection` (`decompiled/XRL.World/Cell.cs:7322-7324`), `Cell.GetCombatTarget` (`:8511-8557`), `GameObject.IsHostileTowards` (`decompiled/XRL.World/GameObject.cs:10887-10894`).
  - **Turn-end fallback**: `PassTurn` (`decompiled/XRL.World/GameObject.cs:17543-17545`), `UseEnergy` + `UseEnergyEvent` emit (`:2925-2930`).
  - **Energy / statistics**: `GameObject.Energy` field (`decompiled/XRL.World/GameObject.cs:145`), `Statistic.Value` (`decompiled/XRL.World/Statistic.cs:238-252`), `Statistic.BaseValue` setter + `NotifyChange` (`:218-232`), `StatChange_*` listeners (`:646-673`), `hitpoints` / `baseHitpoints` semantics (`GameObject.cs:1177-1198`).
  - **Position / zone**: `GameObject.CurrentZone == CurrentCell?.ParentZone` (`decompiled/XRL.World/GameObject.cs:473`), `Zone.ZoneID` (`decompiled/XRL.World/Zone.cs:389`), `ZoneManager` cache (`decompiled/XRL.World/ZoneManager.cs:273, 932`).
  - **Target identity**: `GameObject.ID` (`decompiled/XRL.World/GameObject.cs:340-350, 389-399`), `ShortDisplayNameStripped` (`:763-766`).
  - **AutoAct mirror**: `AutoAct.ClearAutoMoveStop` (`decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`).
  - **Event dispatch contract**: `EventRegistry` chain abort on false (`decompiled/XRL.Collections/EventRegistry.cs:260-272`), `GameObject` parts/effects chain abort on false (`decompiled/XRL.World/GameObject.cs:14024-14030, 14053-14059`).
  - **MetricsManager.LogInfo**: `decompiled/MetricsManager.cs:407-409` (unchanged, same `Player.log` sink as 0-B/0-C/0-D/0-E).
