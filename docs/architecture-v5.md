# LLM-of-Qud v5: Implementation Plan

**Status**: v5.9 (Codex round-5 convergence — supervisor timeout state-aware, freeze for Phase 0)
**Date**: 2026-04-23
**Supersedes**: v5.8 (2026-04-23)
**Design shift**: Candidate selection → Hybrid tool-calling agent + safe candidate executor
**Reviews**: Pro review ×4 (2026-03-17–19), 5-agent independent verification, 4-axis consistency audit (2026-03-22), Codex advisor readiness review ×5 (2026-04-23). Codex round 5 advised "no further full review round needed" — this version is the implementation spec for Phase 0-A / 0-A2 start.

### v4.0 Changelog (from v3.2-lite)
- **C1**: `risk_delta` calculation defined (§3 Level 1)
- **C2**: `encounter_log` full schema defined (§4 Layer 2)
- **C3**: `note_evidence` table added for evidence counting persistence (§4 Layer 2)
- **C4**: `cancel_or_back` tool fully specified (§2 Tool Definitions)
- **H1**: `choose` SafetyGate unified to CONFIRM (was WARN/CONFIRM inconsistency)
- **H2**: Phase 2 split into 2a (core MVP) + 2b (hardening)
- **H3**: `session_start` / `session_end` wire messages defined (§8)
- **H4**: `state_version` increment criteria defined (§8)
- **H5**: AutoAct navigation timeout defined (§8)
- **H6**: Reconnect + `previous_response_id` handling specified (§8)
- **H7**: Error handling tasks added to Phase Plan (§9)
- **H8**: N-run evaluation infrastructure added to Phase 3 (§9)
- **H9**: Admission control "recent" window defined as 10 turns (§4)
- **M1–M13**: Fallback wording, plateau detection, schema gaps, response examples, etc.
- **v4.0a**: Pro review round 2 — terminal action schema unified, combat/utility boundary
  clarified, note_evidence DDL fixed, build_runs defined, AutoAct timeout aligned with KPI
- **v4.0b**: Pro review round 3 — PATH C CONFIRM fix, Navigation fallback table/code
  unified (AutoAct active → continue, else → explore), state_fallback() modal source
  clarified (turn_notify.modal), reconnect/heartbeat examples fully qualified with
  message_id/session_epoch/in_reply_to
- **v4.0c**: Pro review round 4 — state_fallback() complete rewrite (3rd failure path,
  signature fix), modal authority in turn_start, wire envelope normalized, NeutralEscape
  boundary/Safety enum/execution_status canonicalized, Phase 2a/2b/3 dependency DAGs added
- **v4.0d**: Pro review round 5 — wire examples fully normalized to tool_call/tool_result,
  terminal contract examples split by action_kind, cancel_or_back state recomputation rule,
  state_fallback() accepted checks on all paths, duplicate handling unified to cached result
- **v4.0e**: Pro review round 6 — action_nonce/state_version envelope-only, cooldown state_version
  boundary clarified, cross-epoch duplicate → stale_epoch (nonce cache same-epoch only),
  write_note ownership clarified (WS relay), Appendix D canonical wire schemas added
- **v5.0**: Code-grounded revision — Harmony→IGameSystem, UseNewPopups dual-path,
  AutoAct Setting string, has_cover float, visibility filter, modal 3-system,
  adjacency 8-neighbor, all verified against ~/Dev/coq-decompiled/ (5474 .cs files)
- **v5.1**: IGameSystem→IPlayerSystem (BeginTakeActionEvent is object-level event),
  modal detector view names corrected, interrupt_reason multi-signal synthesis,
  ConsoleTrade added, Popup.Suppress scope clarified, deadlock warning for awaitTask
- **v5.2**: new popup family expanded (ModernPopup*), OnSelect/OnActivateCommand operation,
  cancel_or_back semantic mapping per modal type, level_up detector, AutoActSession state,
  target_satisfied replaces at_destination, interrupt enum unified to hostile_perceived,
  deadlock warning corrected, doc version synchronized
- **v5.3**: Holistic review — hostile_perceived in game_state, navigate_to MVP scope
  (no digging), level-up supervisor takeover, 3-tier timeout (5/10/15s), tool_calls
  target aligned with p95, Death Taxonomy expanded, goal ledger, agency share metrics,
  trusted macros roadmap, first demo definition
- **v5.4**: Redline fixes — navigate_to Harmony Prefix for AllowDigging=false,
  Action.WAIT_FOR_SUPERVISOR wire contract + supervisor_request message,
  fallback_choice_id scope narrowed to dialogue/confirmation (null for level-up),
  Appendix D examples updated with hostile_perceived + mode=supervisor
- **v5.9**: Codex round-5 re-review (docs/memo/v5.8-codex-review-2026-04-23.md)
  closed the last outstanding Must-Fix (MF-v5.8-1): the `WAIT_FOR_SUPERVISOR`
  supervisor-timeout fallback silently reintroduced the modal-WAIT deadlock that
  v5.7 had removed, because its timeout path called `Action.WAIT` regardless of
  `game_state`. The supervisor timeout (both in the Action-enum contract and in
  Appendix D) is now state-aware: non-modal → `Action.WAIT`, cancellable modal →
  `cancel_or_back`, and `level_up` / uncancellable / `modal_fallback_failed` /
  `modal_desync` remain paused and renew `supervisor_request`. Never
  `Action.WAIT` while `game_state == "modal"`. Also reworded one stale
  "modal→default" summary to point at the `state_fallback()` modal policy.
  Codex round 5 explicitly marked this version as the freeze point for Phase
  0-A / 0-A2 implementation start. Remaining Should-Fix items (S2/S3) are now
  phase-assigned (2-K / 0-B) and do not block start.
- **v5.8**: Codex round-4 re-review (docs/memo/v5.7-codex-review-2026-04-23.md)
  closed two small-but-load-bearing internal inconsistencies:
  (MF-v5.7-1) `state_fallback()` docstring and Action-enum comments still said
  "returns Action.WAIT if all attempts fail" — the modal branch was updated in
  v5.7 but the function contract was stale and would have let an implementer
  silently revert the deadlock fix. Docstring now distinguishes non-modal
  (WAIT) from modal (WAIT_FOR_SUPERVISOR); Action enum comment forbids WAIT
  from the modal branch.
  (MF-v5.7-2) `supervisor_request` wire payload schema generalised beyond the
  level-up example: `reason` enum expanded to
  `level_up | unsupported_modal_uncancellable | modal_fallback_failed | modal_desync`;
  `modal` field allowed to be null when `reason == "modal_desync"`, with a
  `diagnostic` string required in that case.
  Additional fixes: Modal Implementation table's "Choice popup → Close/back"
  row now explicitly prefers `OnActivateCommand(backItem)` over
  `BackgroundClicked()` because the latter's `FirstOrDefault()` (PopupMessage.cs:876-879)
  can null-deref when no cancel command exists. Phase 0-A adds a reload-smoke
  acceptance clause that verifies exactly one begin-turn callback per decision
  point after a mod reload.
- **v5.7**: Codex round-3 re-review (docs/memo/v5.6-codex-review-2026-04-23.md)
  identified 2 small regressions remaining in v5.6, now fixed:
  (MF-v5.6-1) Phase 0-A2 build-log exit criteria loosened from a literal
  `Compiling N files...` match to a singular/plural regex
  `^Compiling \d+ files?\.\.\.$` — matches `ModInfo.cs:768-769` which emits
  `Compiling 1 file...` in the singular case.
  (MF-v5.6-2) `state_fallback()` modal branch: all terminal `WAIT` returns
  replaced with `WAIT_FOR_SUPERVISOR` to prevent modal deadlock retention;
  separated `modal is None` (protocol-invariant violation / desync) from
  `fallback_choice_id is None` (unsupported modal). Fallback narrative
  synchronised with the State × Fallback Matrix: unsupported modals try
  `cancel_or_back` first and escalate only on failure, not directly.
- **v5.6**: Codex re-review (docs/memo/v5.5-codex-review-2026-04-23.md) surfaced
  three regressions in v5.5 caused by unverified content. All three fixed by
  reading the actual decompiled source before editing:
  (MF-v5.5-A) AutoAct.TryToMove Harmony `Type[]` corrected to the verified
  10-argument signature at `AutoAct.cs:465`
  `(GameObject, Cell, ref GameObject, Cell, string, bool, bool, bool, bool, bool)`.
  (MF-v5.5-B) Phase 0-A2 rewritten from ".csproj + prebuilt DLL" to CoQ's real
  loader: `ModManager.BuildMods()` → `ModInfo.TryBuildAssembly()` Roslyn-compiles
  all `.cs` files in the mod directory. `manifest.json` fields restricted to
  those verified in `XRL/ModManifest.cs`. No `entry assembly` field, no
  .csproj required by the loader.
  (MF-v5.5-C) Modal fallback residual inconsistencies synced: bulleted Fallback
  Chain split by modal sub-type, fallback_choice_id semantics list re-categorised
  Merchant/quantity/string/ModernPopup* as `unsupported` (null fallback +
  cancel_or_back / supervisor_request), state_fallback() pseudocode now handles
  the null fallback_choice_id branch via cancel_or_back before escalating to
  supervisor.
- **v5.5**: Codex readiness review applied (docs/memo/v5.4-codex-review-2026-04-23.md) —
  (M1) AutoAct.TryToMove Harmony target disambiguated (Prefix, specify ref-LastDoor
  overload); (M2) IPlayerSystem.RegisterPlayer event-ID registration made explicit
  (`Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID)`); (M3) cross-thread
  routing split into gameQueue (world reads / CommandEvent.Send) vs uiQueue
  (PopupMessage OnSelect/OnActivateCommand / ModernUI modal); (M4) State × Fallback
  Matrix modal-disconnect row refined for level-up / unsupported modal; (M5)
  terminal-action idempotency (action_nonce + state_version + cached duplicate
  result) promoted to Phase 1 so Phase 2a Gate 1 has idempotent terminal actions;
  (M6) new Phase 0-A2 task for MOD packaging (manifest.json, .csproj, HarmonyLib
  reference, load verification); (S1) force_action_tools / navigation fallback
  semantic alignment; (S2) Phase 0-I split (snapshot fixture + 1 replay smoke
  remains; golden ×10 + full replay harness + crash dashboard deferred to 2b).
  `agency_share_llm` First-Demo target lowered from >60% to >50% (aligns with
  v5.3 Phase 2a criteria; AutoAct long-distance navigation makes >60% unrealistic
  for First Demo).

---

## 0. Vision & Goals

### Primary Goal

Build a robust harness that lets an LLM autonomously play Caves of Qud,
good enough for live streaming (à la "Claude Plays Pokemon").

### Secondary Goal

Produce research outputs as a natural byproduct of logged gameplay:
systems/demo paper, failure analysis paper, or light empirical comparison.

### Design Philosophy

> "LLM が高レベルに tool-call し、C# が安全な原子的実行を担当し、
> 画面には常に current goal / top options / public reason / last outcome を出す"
> — ChatGPT Pro review (2026-03-17)

**Hybrid approach**: The LLM decides *what to investigate* and *what strategy to pursue*
(tool-calling agent), but final action execution goes through the CandidateGenerator's
safe candidate list (candidate executor). This gives LLM genuine agency while
preventing suicidal moves.

### Key Streaming KPI

**stall-free minutes** — the stream must never appear frozen. Viewer tolerance is ~15 seconds
of apparent inactivity; 30 seconds is fatal. Overlay heartbeat (5s), soft timeout (10s),
and hard timeout (15s) are streaming lifelines layered before the fatal threshold.
SafetyGate (multi-layer), ModalInterceptor, CandidateGenerator fallback, and snapshot_hash
are streaming lifelines, not just research instruments.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    LLM (gpt-5.4)                    │
│   "I see two enemies. Let me assess the threat..."  │
│                                                     │
│   inspect_surroundings() → assess_threat("e1") →    │
│   request_candidates("combat") → execute("c2")     │
│   (turn ends; write_note is called on next turn)    │
│                                                     │
│   navigate_to("stairs_down") ← direct movement     │
│   choose("option_2") ← dialogue/level-up/modal     │
├─────────────────────────────────────────────────────┤
│              Python Brain (localhost:4040)           │
│   Tool schema hosting, session management,          │
│   knowledge base, Codex API client                  │
├─────────────────────────────────────────────────────┤
│              C# MOD (IGameSystem + Harmony)          │
│   LLMOfQudSystem : IPlayerSystem,                   │
│   Tool implementations, CandidateGenerator,         │
│   SafetyGate (multi-layer), ModalInterceptor,       │
│   ToolExecutor, AutoAct integration,                │
│   Snapshotter, DeltaTracker, DeathLogger            │
├─────────────────────────────────────────────────────┤
│              Caves of Qud (Unity/Mono)              │
└─────────────────────────────────────────────────────┘
```

### Turn Loop (per game turn)

**v5.0: Verified Turn Pipeline** (from ActionManager.cs:785-833, XRLCore.cs:662-665):
```
ActionManager.RunSegment()
  ├─ EarlyBeforeBeginTakeActionEvent.Check(Actor)   [CascadeLevel 15]
  ├─ BeforeBeginTakeActionEvent.Check(Actor)          [CascadeLevel 15]
  ├─ BeginTakeActionEvent.Check(Actor)                [CascadeLevel 143] ← LLMOfQudSystem hooks here
  ├─ while (Actor.Energy >= 1000):                    [L800 — may loop multiple times]
  │    ├─ BeforeTakeActionEvent.Check(Actor)
  │    ├─ CommandTakeActionEvent.Check(Actor)          [AI command dispatch]
  │    └─ if Actor.IsPlayer(): XRLCore.PlayerTurn()   [keyboard/AutoAct/MOD command]
  │         └─ CallBeginPlayerTurnCallbacks()          [L665 — our primary hook]
  │         └─ CommandEvent.Send(The.Player, cmd)      [L2240 — action execution]
  └─ EndActionEvent.Send(Actor)
  [10 segments] → EndTurnEvent → game.Turns++
```

**Important**: One `BeginTakeActionEvent` can lead to **multiple command loops** if the
actor has enough energy (e.g., speed bonus). The `while(Energy >= 1000)` loop at L800
means `turn_start` does NOT guarantee exactly one command per notification. The Python
Brain must handle this by treating each `CallBeginPlayerTurnCallbacks` invocation as
a separate decision point.

Three distinct paths depending on game state:

```
PATH A: Combat
1. C# detects player turn (BeginTakeActionEvent)
2. C# sends turn_start notification to Python Brain via WebSocket
3. Python Brain initiates LLM tool-calling loop:
   a. LLM receives: turn notification + session context + notes
   b. LLM calls inspection/assessment tools (0-3 calls)
   c. LLM calls request_candidates("combat")
   d. LLM calls execute(candidate_id, candidate_set_id, snapshot_hash) with public_reason
   e. Loop ends when execute() is called or max_calls exceeded
4. Python Brain forwards action to C# MOD
5. C# validates (SafetyGate post-validation) and executes via ToolExecutor
6. C# computes ActionOutcome (Level 1 feedback)
7. C# sends outcome back to Python Brain for next turn's context

PATH B: Navigation (non-combat)
1-3a. Same as above
3b. LLM decides to move → calls navigate_to(target, reason)
3c. C# SafetyGate pre-filter checks zone danger → WARN if dangerous zone
3d. C# delegates to AutoAct pathfinder → runs internally
3e. AutoAct interrupts on: hostile_perceived, took_damage, hazard, popup → new turn_start

PATH C: Dialogue / Level-up / Modal
1-3a. Same as above
3b. LLM sees choices via inspect_surroundings (canonical source for modal state)
3c. LLM calls choose(choice_id, reason)
3d. C# SafetyGate pre-filter checks for irreversible options → CONFIRM if detected (requires re-call with `confirmed: true`)
3e. C# applies choice → next turn
```

### Fallback Chain (unified through CandidateGenerator)

**Combat** fallback paths converge through CandidateGenerator. Non-combat fallback uses
safe defaults (continue AutoAct navigation, choose modal `fallback_choice_id` ONLY for
dialogue/confirmation modals, pause + supervisor for level-up, `cancel_or_back` first
for unsupported modals and supervisor only if cancellation fails, explore nearest
unexplored). There is no separate "heuristic fallback" that bypasses candidates for
combat actions. This prevents split-personality behavior in dangerous situations. The
full breakdown lives in the State × Fallback Matrix below — the bulleted chain and the
Matrix are the same policy expressed two ways.

```
Combat:    LLM calls execute()          → normal execution
Combat:    LLM timeout/max_calls        → force request_candidates("combat") → auto-pick highest-scored
Combat:    WebSocket disconnected       → C# CandidateGenerator → auto-pick highest-scored
Navigation: LLM timeout/max_calls      → if AutoAct active: continue (C#-driven); else: navigate_to nearest_unexplored
Navigation: WebSocket disconnected     → if AutoAct active: continue; else: C# AutoAct explore
Modal (dialogue/Yes-No/Yes-No-Cancel):
           LLM timeout/max_calls        → choose fallback_choice_id
           WebSocket disconnected       → C# selects fallback_choice_id
Modal (level-up / build-altering):
           LLM timeout/max_calls        → Action.WAIT_FOR_SUPERVISOR (no auto-select)
           WebSocket disconnected       → pause + supervisor_request (no auto-select)
Modal (unsupported: merchant/quantity/string input/ModernPopupGamepadAskNumber/
       ModernPopupTwiddleObject):
           LLM timeout/max_calls        → cancel_or_back if the modal allows it, else supervisor_request
           WebSocket disconnected       → same: cancel_or_back if allowed, else pause + supervisor_request
Idle:      LLM timeout/max_calls       → navigate_to nearest unexplored
Idle:      WebSocket disconnected      → C# AutoAct explore
```

The "highest-scored candidate" fallback uses the same CandidateGenerator + SafetyGate
pipeline as normal play. The only difference is that the LLM is bypassed in selection.

### State × Fallback Matrix (v3.2-lite)

What happens when the LLM fails in each game state:

| Game State | LLM Timeout / Max Calls | WebSocket Disconnect |
|------------|------------------------|---------------------|
| **Combat** | `request_candidates("combat")` → auto-pick highest-scored | C# calls CandidateGenerator directly → auto-pick highest-scored |
| **Navigation** | If AutoAct active: continue (C#-driven). Else: `navigate_to` nearest unexplored | If AutoAct active: continue. Else: C# AutoAct explore |
| **Modal (dialogue / Yes-No / Yes-No-Cancel)** | `choose` `fallback_choice_id` | C# selects `fallback_choice_id` |
| **Modal (level-up / build-altering)** | `Action.WAIT_FOR_SUPERVISOR` (supervisor takeover) | **Pause + `supervisor_request`; no auto-select** — no safe fallback exists for build-identity choices |
| **Modal (unsupported: merchant / quantity / string input / ModernPopupGamepadAskNumber / ModernPopupTwiddleObject)** | `cancel_or_back` if the modal allows it, else `supervisor_request` | Same: `cancel_or_back` if allowed, else pause + `supervisor_request` |
| **Idle** (no enemies, no modal) | `navigate_to` nearest unexplored area | C# triggers AutoAct explore |

All fallback actions go through SafetyGate. Combat fallback goes through CandidateGenerator.
Non-combat fallback uses safe defaults per the Matrix above — **not** a generic "select
default modal option". Dialogue/confirmation uses `fallback_choice_id`; level-up
escalates directly to supervisor; unsupported modals try `cancel_or_back` first and
escalate only if cancellation is unavailable or rejected; navigation defers to AutoAct
or explores unexplored cells.

**v5.5 (Codex Must-Fix #4) + v5.7 refinement**: level-up does NOT auto-select on
WebSocket disconnect — it escalates directly to supervisor because level-up choices
permanently alter build identity and auto-selecting "first option" corrupts the run.
Unsupported modals (trade, quantity input, string input, ModernPopupGamepadAskNumber,
ModernPopupTwiddleObject) are Phase 5+ scope; on disconnect / timeout C# first tries
the same safe `cancel_or_back` path for cancellable unsupported modals, and only
emits `supervisor_request` if cancellation is unavailable or rejected. `fallback_choice_id`
is **null for level_up and unsupported modals**.

### Bounded Autonomy: AutoAct Exploration

When navigate_to delegates to AutoAct, C# runs the pathfinder without LLM involvement.
This is explicitly a **bounded autonomy region** — the LLM chose the destination,
but C# handles the step-by-step movement. AutoAct is interrupted by guard conditions
(enemy visible, damage taken, hazard, popup), at which point control returns to the LLM.

---

## 2. Tool Definitions

### Tool Inventory (11 tools, Phase 2 MVP)

All tools use OpenAI Responses API format (`strict: true`).
Each tool has a clear, non-overlapping responsibility (Pro: "overlapping tool set is a failure cause").

| Tool | Category | Purpose | SafetyGate |
|------|----------|---------|------------|
| inspect_surroundings | Observation | Map, entities, terrain | — |
| check_status | Observation | HP, abilities, effects | — |
| check_inventory | Observation | Items | — |
| assess_threat | Analysis | Threat analysis for target | — |
| navigate_to | Action | Move to target via AutoAct | Pre-filter (zone danger) |
| choose | Action | Dialogue/level-up/modal | Pre-filter (CONFIRM on irreversible) |
| request_candidates | Action | Combat + utility candidates | — |
| execute | Action | Execute combat candidate | BLOCK/CONFIRM/WARN/PASS |
| write_note | Knowledge | Write to knowledge base | — |
| read_notes | Knowledge | Read knowledge base | — |
| cancel_or_back | Action | Cancel/back out of modal or submenu | — |

Phase 3 additions: assess_escape, assess_ability, search_archive (14 tools total)

### Situation-Based Tool Filtering (v3.2-lite)

Each turn, the tool loop restricts available tools based on game state
(Pro: "12 tools every turn is heavy; filter by situation"):

| Situation | Available Tools | Count |
|-----------|----------------|-------|
| Combat | inspect_surroundings, check_status, check_inventory, assess_threat, request_candidates, execute, write_note | 7 |
| Navigation | inspect_surroundings, check_status, check_inventory, navigate_to, request_candidates, execute, write_note, read_notes | 8 |
| Modal (dialogue/level-up) | inspect_surroundings, check_status, choose, cancel_or_back, write_note | 5 |
| Fallback (unknown) | All 11 tools | 11 |

Implemented via `allowed_tools` in the Responses API `tool_choice` parameter.

**`read_notes` availability**: `read_notes` is available in Navigation and Idle states but
intentionally excluded from Combat and Modal states. In combat, notes are already injected
via the system prompt each turn. In modal state, the LLM should focus on the presented choices.
The LLM can always write notes (`write_note` is available in all states).

**v4.0: `request_candidates` situation boundary** (resolved from v3.3):
- `combat`: attack, retreat, use_ability, **plus** heal, wait, use_item when tactically relevant.
  CandidateGenerator includes utility-tagged candidates (heal, wait) in combat when HP is low
  or defensive play is warranted. This is why the combat response example includes `tag: "util"` items.
- `utility`: heal, consume_item, wait, use_item (non-combat only, for proactive resource management)
- Movement uses `navigate_to` directly — NOT utility candidates
- Modal choices use `choose` directly — NOT utility candidates
- If the LLM is unsure whether to use `navigate_to` or `request_candidates`,
  the game_state filtering resolves it: combat state → candidates, non-combat → navigate_to

**Combat retreat path**: In combat state, retreat is handled via `request_candidates("combat")` →
`execute` (retreat candidates include direction, safety, cover). `navigate_to` is intentionally
excluded from combat tools — the LLM should not bypass the candidate safety pipeline for movement
during combat.

**v3.3: Missing tools noted for late Phase 2** (from Pro review #3):
- **`cancel_or_back`** (v3.4: upgraded to Phase 2 Gate 2 prerequisite):
  Explicit back/cancel for inventory, confirmation, and mis-navigated modals.
  `choose + safe default` alone is insufficient — confirmation modals, inventory
  submodals, and merchant screens can deadlock or trigger destructive defaults.
  Must be implemented before Phase 2 Gate 2.
- **Navigation progress**: LLM currently cannot query route progress or path
  invalidation. `inspect_surroundings` will include `navigation_status` field
  when AutoAct is active: `{"navigating": true, "destination": "stairs_down",
  "steps_remaining": 3, "path_valid": true}`.

**v5.0**: `steps_remaining` and `path_valid` are **MOD-synthesized fields**, not native
CoQ APIs (verified: no matching symbols in 5474 decompiled files). The C# MOD computes
these from the current AutoAct.Setting target and FindPath result each turn.

#### Observation Tools

**`inspect_surroundings`**
Returns: ASCII map (21×21), entity list with positions, terrain features, hazards.
Uses: `ScreenBuffer.Buffer[x,y].Char` reading (via ConsoleChar._Char, ConsoleChar.cs:67)
+ zone entity enumeration with **visibility filter** (Zone.GetObjects() returns ALL objects
including invisible/unseen — Zone.cs:1982. MOD MUST filter by player perception:
`The.Player.CanSee(obj)` or `obj.IsVisible()`).

**v5.0: ScreenBuffer access**: Use `TextConsole.CurrentBuffer` for current display,
or `XRLCore.RegisterAfterRenderCallback(Action<XRLCore, ScreenBuffer>)` (XRLCore.cs:624)
for stable post-render access. Note: AfterRenderCallbacks fire AFTER ConfusionShuffle
(XRLCore.cs:2343-2350) — the buffer reflects confused display if player is confused.
When a popup is active, CurrentBuffer contains popup content, not the map.

```json
{
  "type": "function",
  "name": "inspect_surroundings",
  "description": "Get the ASCII map around the player, nearby entities, objects, and hazards. Call this at the start of each turn to understand your environment.",
  "strict": true,
  "parameters": {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": false
  }
}
```

Returns:
```json
{
  "map": { "rows": ["###.....###", "...@....##.", ...], "axes": "x_right_y_down" },
  "entities": [
    {"id": "e1", "name": "snapjaw", "pos": [2, -1], "threat": "moderate", "behavior": "approaching"},
    {"id": "e2", "name": "snapjaw hunter", "pos": [5, 3], "threat": "high", "behavior": "ranged_hold"}
  ],
  "objects": [{"id": "o1", "name": "stairs_down", "pos": [8, 0]}],
  "hazards": [],
  "zone_id": "JoppaWorld.10.25.1.1.10"
}
```

**`check_status`**
Returns: HP, level, attributes, active effects, cooldowns, hunger/thirst, equipment summary.
Uses: The.Player.Statistics, ActivatedAbilities, Effects internally.

```json
{
  "type": "function",
  "name": "check_status",
  "description": "Get your current HP, level, abilities with cooldowns, active effects, equipment, and resources. Call when you need to plan around your current capabilities.",
  "strict": true,
  "parameters": { "type": "object", "properties": {}, "required": [], "additionalProperties": false }
}
```

Returns:
```json
{
  "hp": [18, 24],
  "level": 3,
  "attributes": {"strength": 16, "agility": 18, "toughness": 14, "intelligence": 20, "willpower": 17, "ego": 22},
  "active_effects": [{"name": "Burning", "turns_remaining": 2}],
  "cooldowns": [{"ability": "Pyrokinesis", "turns_remaining": 0}, {"ability": "Blink", "turns_remaining": 3}],
  "hunger": "satiated",
  "thirst": "quenched",
  "equipment_summary": "iron long sword (hand), leather armor (body)"
}
```

**`check_inventory`**
Returns: Carried items grouped by category (healing, food, water, equipment, misc).
Uses: player.Inventory.Objects internally.

```json
{
  "type": "function",
  "name": "check_inventory",
  "description": "Get your carried items grouped by category: healing, food, water, weapons, armor, and misc. Call when you need to check supplies or plan resource usage.",
  "strict": true,
  "parameters": { "type": "object", "properties": {}, "required": [], "additionalProperties": false }
}
```

Returns:
```json
{
  "categories": {
    "healing": [{"name": "salve injector", "count": 2, "effect": "heal 20-24 HP"}],
    "food": [{"name": "raw vinewafer", "count": 3}],
    "water": [{"name": "fresh water", "drams": 8}],
    "equipment": [{"name": "iron long sword", "equipped": true, "slot": "hand"}],
    "misc": [{"name": "copper nugget", "count": 1}]
  },
  "weight": {"current": 24, "max": 70},
  "encumbrance": "light"
}
```

#### Analysis Tools (v3.2: split from get_help)

Each analysis tool has a single, auditable responsibility.
This replaces the v3.1 `get_help` free-form query tool (Pro: "hidden policy engine" risk).

**`assess_threat`**
Compute threat analysis for a specific target entity.
Uses: ThreatScore, entity stats, build-relative matchup analysis.

```json
{
  "type": "function",
  "strict": true,
  "name": "assess_threat",
  "description": "Get threat analysis for a specific enemy. Returns threat level, expected damage, recommended approach, and whether your build has counters for this enemy type.",
  "parameters": {
    "type": "object",
    "properties": {
      "target": { "type": "string", "description": "Entity ID from inspect_surroundings, e.g. 'e1'" }
    },
    "required": ["target"],
    "additionalProperties": false
  }
}
```

Returns:
```json
{
  "target": "e1",
  "name": "snapjaw hunter",
  "threat_level": "high",
  "expected_damage_2turn": 14,
  "attack_type": "ranged",
  "range": 8,
  "your_hp": 18,
  "build_has_counter": true,
  "counter_ability": "Pyrokinesis",
  "recommendation": "find_cover_or_close_distance"
}
```

**`assess_escape`** — Deferred to Phase 3. Escape route information is included in
`request_candidates` retreat candidates (direction, safety score, cover, choke).

**`assess_ability`** — Deferred to Phase 3. Ability recommendations are included in
`request_candidates` ability candidates (name, expected damage, resource cost).

#### Action Tools

**`navigate_to`** (v3.2: new, replaces explore-type candidates)
Move to a target location via AutoAct state machine.
C# sets `AutoAct.Setting = "M" + targetId` (or `"P" + radius + ":" + coords`).
ActionManager then drives pathfinding via `FindPath` each turn until arrival or interrupt.

**v5.4: MVP scope restriction + enforcement mechanism**:
The native `ActionManager` path (case 'M', L993-1015) calls `AutoAct.TryToMove()`
with `AllowDigging: true` by default. This would cause the agent to dig through walls.

**Enforcement** (v5.5 Must-Fix #1, v5.6 signature correction): The C# MOD uses a
**Harmony Prefix patch** on the `ref GameObject LastDoor`-carrying overload of
`AutoAct.TryToMove()` that coerces the `AllowDigging` parameter to `false` during
Phase 2. Verified from `decompiled/XRL.World.Capabilities/AutoAct.cs:465`, the
target overload's real signature is:

```csharp
// AutoAct.cs:465 — this is the overload we patch
public static bool TryToMove(
    GameObject Actor, Cell FromCell, ref GameObject LastDoor,
    Cell ToCell = null, string Direction = null,
    bool AllowDigging = true, bool OpenDoors = true, bool Peaceful = true,
    bool PostMoveHostileCheck = true, bool PostMoveSidebarCheck = true)
```

The sibling 9-arg overload at `AutoAct.cs:613` delegates into this one at L616,
so patching the 10-arg (ref-LastDoor) version covers both call sites. The patch
MUST specify argument types because `TryToMove` has overloads — a bare
`[HarmonyPatch(typeof(AutoAct), nameof(AutoAct.TryToMove))]` is ambiguous. This is
one of the justified Harmony use cases (no public event hook exists for this
parameter).

```csharp
// LLMOfQudPatches.cs — Phase 2 navigate_to restriction
[HarmonyPatch(typeof(AutoAct), nameof(AutoAct.TryToMove),
    new Type[] {
        typeof(GameObject),                   // Actor
        typeof(Cell),                         // FromCell
        typeof(GameObject).MakeByRefType(),   // ref LastDoor — disambiguates overload
        typeof(Cell),                         // ToCell
        typeof(string),                       // Direction
        typeof(bool),                         // AllowDigging — we coerce this
        typeof(bool),                         // OpenDoors
        typeof(bool),                         // Peaceful
        typeof(bool),                         // PostMoveHostileCheck
        typeof(bool)                          // PostMoveSidebarCheck
    })]
static class Patch_NoDigging {
    static void Prefix(ref bool AllowDigging) {
        if (LLMOfQudSystem.NavigateToActive)
            AllowDigging = false;
    }
}
```

Confirm the exact `Type[]` against the installed game's assembly at
implementation time (decompiled source is a guide, not authoritative for the
shipped binary; overload signatures may be tweaked between CoQ versions).

Phase 2 MVP restrictions:
- `AllowDigging = false` (enforced via Harmony prefix on TryToMove)
- `AutoOpenDoors = true` (doors are safe and expected — no patch needed)
- Dangerous liquid swim: pre-filtered by SafetyGate navigate_to pre-check
  (the native WarnYesNo popup is intercepted by ModalInterceptor → auto-decline)
- Phase 3+ lifts digging restriction via config flag.

```json
{
  "type": "function",
  "strict": true,
  "name": "navigate_to",
  "description": "Move to a target location or object. The harness pathfinder handles movement. You will be interrupted if enemies appear, you take damage, or a popup occurs. Use for exploration, reaching stairs, or moving to specific locations.",
  "parameters": {
    "type": "object",
    "properties": {
      "target": { "type": "string", "description": "What to move toward: entity/object ID ('o1'), direction ('north'), or description ('stairs_down')" },
      "reason": { "type": "string", "description": "Brief explanation for stream viewers, max 80 chars" },
      "confirmed": { "type": "boolean", "description": "Set to true when re-confirming after a CONFIRM safety response. Include confirmation_id." },
      "confirmation_id": { "type": "string", "description": "confirmation_id from CONFIRM response, required when confirmed=true" }
    },
    "required": ["target", "reason"],
    "additionalProperties": false
  }
}
```

Returns:
```json
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "navigate_to",
  "execution_status": "in_progress",
  "acceptance_status": "accepted",
  "safety_decision": "pass",
  "action_summary": "Move toward stairs_down at [8, 0]",
  "destination": "stairs_down at [8, 0]",
  "estimated_steps": 5,
  "outcome": null,
  "safety_warning": null
}
```

SafetyGate pre-filter:
- **WARN** on dangerous zone: `{"accepted": true, "turn_complete": true, "action_kind": "navigate_to", "execution_status": "in_progress", "safety_decision": "warn", "safety_warning": "Entering zone tier 4 (your level: 3). Proceed with caution."}`
- Zone danger is computed as: `zone_tier > player_level / 3`

When AutoAct is interrupted, the next `turn_start` message includes `interrupt_reason`
(e.g., `"hostile_perceived"`, `"took_damage"`, `"popup"`).

**`choose`** (v3.2: new, replaces dialogue/level_up/modal candidates)
Make a direct choice in dialogue, level-up, or modal situations.

```json
{
  "type": "function",
  "strict": true,
  "name": "choose",
  "description": "Make a choice in a dialogue, level-up screen, or other modal popup. The available choices are shown in inspect_surroundings when a modal is active.",
  "parameters": {
    "type": "object",
    "properties": {
      "choice_id": { "type": "string", "description": "Choice ID from the modal options" },
      "reason": { "type": "string", "description": "Brief explanation for stream viewers, max 80 chars" },
      "confirmed": { "type": "boolean", "description": "Set to true when re-confirming after a CONFIRM safety response. Include confirmation_id." },
      "confirmation_id": { "type": "string", "description": "confirmation_id from CONFIRM response, required when confirmed=true" }
    },
    "required": ["choice_id", "reason"],
    "additionalProperties": false
  }
}
```

SafetyGate pre-filter:
- **CONFIRM** on irreversible options (if detectable by C#, e.g., permanent mutation selection).
  Returns `confirmation_id`; LLM must re-call with `confirmed: true` to proceed.

Returns (normal):
```json
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "choose",
  "execution_status": "accepted",
  "acceptance_status": "accepted",
  "safety_decision": "pass",
  "action_summary": "Selected: Ask about water ritual",
  "outcome": null,
  "safety_warning": null
}
```

Returns (CONFIRM required):
```json
{
  "accepted": false,
  "turn_complete": false,
  "action_kind": "choose",
  "acceptance_status": "confirm_required",
  "safety_decision": "confirm",
  "confirmation_id": "cfm_456",
  "reason": "Permanent mutation selection — cannot be reversed",
  "expires_at": {"tid": 142, "state_version": 284, "session_epoch": 3}
}
```

**Canonical Modal Schema** (v3.2-lite):

When a modal is active, `inspect_surroundings` includes a `modal` field:
```json
{
  "modal": {
    "type": "dialogue",
    "title": "Mehmet",
    "prompt": "Live and drink, friend.",
    "choices": [
      {"id": "ch1", "label": "Ask about water ritual", "is_default": false, "is_irreversible": false},
      {"id": "ch2", "label": "Trade", "is_default": false, "is_irreversible": false},
      {"id": "ch3", "label": "Leave", "is_default": true, "is_irreversible": false}
    ],
    "fallback_choice_id": "ch3"
  }
}
```

`fallback_choice_id` (v5.4: scope narrowed): The guaranteed-safe fallback choice.
**Invariant: exactly one must exist per dialogue and confirmation modal.**
Does NOT apply to level-up modals (no safe auto-select — supervisor takeover instead).
Used by state_fallback() for dialogue/confirmation auto-fallback when LLM times out.

**v5.4**: `fallback_choice_id` is a **MOD-synthesized field** — CoQ's engine has no
native concept of a default/fallback choice (verified: no matching symbols in decompiled
source). The C# MOD computes this by:
- **Dialogue**: select the "Leave"/"End" option or the last choice
- **Confirmation (Yes/No)**: select "No"
- **Confirmation (Yes/No/Cancel)**: select "Cancel"
- **Level-up**: `fallback_choice_id` is **null** → triggers `Action.WAIT_FOR_SUPERVISOR`
- **Merchant / quantity input / string input / ModernPopupGamepadAskNumber /
  ModernPopupTwiddleObject (v5.6: unified as "unsupported modal" for MVP)**:
  `fallback_choice_id` is **null**. Fallback uses `cancel_or_back` if the modal
  allows it, else emits `supervisor_request`. These modals become supported in
  Phase 5+ (see Appendix A).

Modal types: `"dialogue"`, `"level_up"`, `"confirmation"`, `"merchant"` (Phase 5+).
`is_default` marks the safe fallback option (used when LLM times out).
`is_irreversible` triggers SafetyGate CONFIRM on `choose` (requires re-confirmation).
`inspect_surroundings` is the **canonical source** for modal state (not `check_status`).

**v5.1: Modal Implementation** (corrected after Pro review with code verification):

| System | Detection | Choice Method | Cancel Method |
|--------|-----------|---------------|---------------|
| **Popup (legacy)** | `CurrentGameView.StartsWith("Popup:")` (e.g., `Popup:MessageBox`, `Popup:Choice`, `Popup:AskString` — Popup.cs:694,1213,1439) | `Keyboard.PushKey(key)` (Keyboard.cs:763) | `Keyboard.PushKey(Keys.Escape)` |
| **Popup (new UI)** | `CurrentGameView == "PopupMessage"` or `"DynamicPopupMessage"` or `StartsWith("ModernPopup")` (includes `ModernPopupGamepadAskNumber`, `ModernPopupTwiddleObject` — UIManager.cs:166-170). **Out of scope for Phase 2 MVP**: `ModernPopupGamepadAskNumber`, `ModernPopupTwiddleObject` | List selection: `PopupMessage.controller.menuData` + `OnSelect(QudMenuItem)` (PopupMessage.cs:591,736-753). Button bar: `bottomContextOptions` / `bottomContextController.items` + `OnActivateCommand(QudMenuItem)` (PopupMessage.cs:876-881). **`Popup.Suppress` only works for Show/ShowAsync/ShowBlock — NOT for ShowYesNo/ShowYesNoCancel** (Popup.cs:2244). For unsuppressible popups, operate via OnSelect/OnActivateCommand after display. | `OnActivateCommand(cancelItem)` where cancelItem is the QudMenuItem with cancel semantics, or `BackgroundClicked()` (PopupMessage.cs:876-881) |
| **Conversation** | `ConversationUI.CurrentChoices != null` (more reliable than view name — during new UI rendering, view stack pushes `PopupMessage` over `Conversation`) | `ConversationUI.Select(int)` (ConversationUI.cs:539) | `ConversationUI.Escape()` (cs:573, blocked if `AllowEscape == false`) |
| **Merchant (modern)** | `CurrentGameView == "ModernTrade"` (TradeScreen.cs:462) | Phase 5+ (not MVP) | TBD |
| **Merchant (legacy)** | `CurrentGameView == "ConsoleTrade"` (TradeUI.cs:465) | Phase 5+ (not MVP) | `Keyboard.PushKey(Keys.Escape)` |
| **Level-up** | `CurrentGameView == "Popup:Choice"` with level-up context (detected via choice content or game state flag) | `Keyboard.PushKey` for legacy / `OnSelect(QudMenuItem)` for new UI | **Cannot cancel** — must select an option. `cancel_or_back` returns error. |

`inspect_surroundings` modal detection uses `GameManager.Instance.CurrentGameView` as primary signal,
with `ConversationUI.CurrentChoices != null` as secondary for conversation-during-popup disambiguation.

**Conversation choices**: `ConversationUI.CurrentChoices` (static field) provides the
current choice list. Each `Choice` has `GetDisplayText()` for label. **Trade/Look/Escape**
buttons are NOT in `CurrentChoices` — they are external buttons added by `Popup.ShowConversation()`
(Popup.cs:1567-1605) and returned as special indices (-2/-3/-1).

**Edge cases**:
- `TutorialManager.ShowingPopup == true` blocks `Keyboard.PushKey()` (TutorialManager.cs:364)
- `GameManager.bCapInputBuffer == true` discards key queue > 2 entries (Keyboard.cs:774)
- Popup over ScreenBuffer: when popup is displayed, `TextConsole.CurrentBuffer` contains popup content
- **New UI conversation stack**: ConversationUI pushes "Conversation", then Render() calls
  Popup.ShowConversation() → WaitNewPopupMessage() which pushes "PopupMessage" on top.
  So during conversation rendering, `CurrentGameView == "PopupMessage"`, not "Conversation".
  Use `ConversationUI.CurrentChoices != null` to reliably detect active conversation.
- **Popup.Suppress scope**: Suppresses `Show()`, `ShowAsync()`, `ShowBlockPrompt()`, `ShowBlockSpace()`,
  `ShowSpace()`, `ShowBlock()` (Popup.cs:639-669,947-956). Does NOT suppress `ShowYesNo()` (L2244),
  `ShowYesNoCancel()` (L2357), `WaitNewPopupMessage()` (L823). For unsuppressible popups,
  the MOD lets them display and then operates via `OnSelect`/`OnActivateCommand`/`BackgroundClicked()`
  on the rendered PopupMessage. Harmony is only needed if pre-display suppression is required
  (not the default strategy).

**`request_candidates`** (v3.2: combat + utility)
Ask CandidateGenerator to produce safe, legal action candidates.
Non-combat movement uses navigate_to, dialogue/level-up uses choose.

```json
{
  "type": "function",
  "strict": true,
  "name": "request_candidates",
  "description": "Request a list of safe, legal action candidates for the current situation. Each candidate has an id, description, tag, and safety rating. You MUST call this before execute. Use 'combat' for fighting, 'utility' for non-combat actions (healing, consuming items, waiting).",
  "parameters": {
    "type": "object",
    "properties": {
      "situation": { "type": "string", "enum": ["combat", "utility"] }
    },
    "required": ["situation"],
    "additionalProperties": false
  }
}
```

Returns (reuses v2.1 CandidateGenerator output):
```json
{
  "candidate_set_id": "cs_142_01",
  "snapshot_hash": "a3f2c1",
  "candidates": [
    {"id": "c1", "verb": "attack", "tag": "off",
     "desc": "Melee attack snapjaw (e1)", "safety": "ok"},
    {"id": "c2", "verb": "retreat", "tag": "def",
     "desc": "Retreat NW to cover", "safety": "ok"},
    {"id": "c3", "verb": "use_ability", "tag": "off",
     "desc": "Pyrokinesis on e1, expected 9.5 dmg", "safety": "ok"},
    {"id": "c4", "verb": "use_item", "tag": "util",
     "desc": "Heal with salve, HP after: 22", "safety": "ok"},
    {"id": "c5", "verb": "retreat", "tag": "def",
     "desc": "Retreat W to choke point", "safety": "ok"},
    {"id": "c6", "verb": "wait", "tag": "util",
     "desc": "Wait (fallback)", "safety": "ok"}
  ],
  "situation": "combat",
  "safety_notes": "H1 active: HP below 30%, offensive candidates flagged as risky"
}
```

**Note**: Retreat candidates include escape route analysis (direction, safety score,
cover availability, choke points), replacing the need for a separate `assess_escape` tool.
Ability candidates include effectiveness and resource cost, replacing `assess_ability`.

**v3.2-lite: Candidate payload separation**:
- **`llm_view`** (sent to LLM): `id`, `verb`, `tag`, `desc`, `safety`, `candidate_set_id`, `snapshot_hash`
- **`internal`** (for fallback/overlay/telemetry): all of the above + `score`, `args`, `risk_score`, `batch_ok`, `batch_max`
- Scores are NOT shown to the LLM — prevents anchor bias (Pro: "LLM will just follow score order")
- Candidates in `llm_view` are presented in **randomized order** (prevents positional bias)
- `risk_score` (0.0 = safest, 1.0 = most dangerous) is separate from `score` (higher = better overall)
  Used by `state_fallback()` to pick the safest option when the best option is BLOCKED/STALE
- `result.to_llm_view()` in `tool_loop.py` returns only the `llm_view` fields

**`execute`** (v3.2: added candidate_set_id + snapshot_hash)
Execute a combat candidate by ID. C# validates via SafetyGate before execution.
Requires `candidate_set_id` and `snapshot_hash` to prevent stale candidate execution.

```json
{
  "type": "function",
  "strict": true,
  "name": "execute",
  "description": "Execute an action by candidate ID. Works for both combat and utility candidates from request_candidates. Provide the candidate_set_id and snapshot_hash from the request_candidates response.",
  "parameters": {
    "type": "object",
    "properties": {
      "candidate_id": { "type": "string", "description": "Candidate ID from request_candidates, e.g. 'c2'" },
      "candidate_set_id": { "type": "string", "description": "candidate_set_id from request_candidates response" },
      "snapshot_hash": { "type": "string", "description": "snapshot_hash from request_candidates response" },
      "public_reason": { "type": "string", "description": "Brief explanation for stream viewers, max 80 chars" },
      "confirmed": { "type": "boolean", "description": "Set to true when re-confirming after a CONFIRM safety response. Include confirmation_id." },
      "confirmation_id": { "type": "string", "description": "confirmation_id from CONFIRM response, required when confirmed=true" }
    },
    "required": ["candidate_id", "candidate_set_id", "snapshot_hash", "public_reason"],
    "additionalProperties": false
  }
}
```

Returns:
```json
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "execute",
  "execution_status": "accepted",
  "acceptance_status": "accepted",
  "safety_decision": "pass",
  "action_summary": "Retreat NW to cover",
  "outcome": {
    "hp_delta": 0,
    "damage_dealt": 0,
    "risk_delta": -15,
    "enemies_killed": 0,
    "state_changed": true,
    "net_value": 2.5,
    "tags": ["broke_los", "maintained_cover"]
  },
  "safety_warning": null
}
```

Safety responses:
- **BLOCKED**: `{"accepted": false, "turn_complete": false, "action_kind": "execute", "acceptance_status": "blocked", "safety_decision": "block", "reason": "AoE would hit self", "alternatives": ["c2", "c4"]}`
- **CONFIRM**: `{"accepted": false, "turn_complete": false, "action_kind": "execute", "acceptance_status": "confirm_required", "safety_decision": "confirm", "confirmation_id": "cfm_123", "reason": "Permanent mutation choice", "expires_at": {"tid": 142, "state_version": 284, "session_epoch": 3}}`
- **WARN**: `{"accepted": true, "turn_complete": true, "action_kind": "execute", "acceptance_status": "accepted", "safety_decision": "warn", "safety_warning": "HP critically low (15%), attack is risky"}`
- **PASS**: `{"accepted": true, "turn_complete": true, "action_kind": "execute", "acceptance_status": "accepted", "safety_decision": "pass", "safety_warning": null}`
- **STALE**: `{"accepted": false, "turn_complete": false, "action_kind": "execute", "acceptance_status": "stale", "reason": "Game state changed since candidates were generated. Call request_candidates again."}`

**v3.3: CONFIRM flow** (from Pro review #3): BLOCK/WARN/PASS alone was insufficient for
irreversible but non-fatal choices (mutation selection, faction dialogue, merchant transactions).
CONFIRM defers to the LLM with an explicit warning and requires re-confirmation.

**v3.4: CONFIRM contract** (from Pro review #4):

1st response (CONFIRM required):
```json
{
  "accepted": false,
  "turn_complete": false,
  "action_kind": "choose",
  "acceptance_status": "confirm_required",
  "safety_decision": "confirm",
  "confirmation_id": "cfm_123",
  "reason": "Permanent mutation choice",
  "expires_at": {"tid": 142, "state_version": 284, "session_epoch": 3}
}
```

Retry with confirmation:
```json
{
  "choice_id": "ch7",
  "reason": "Take the mutation",
  "confirmed": true,
  "confirmation_id": "cfm_123"
}
```

Rules:
- `confirmation_id` ties the challenge to the retry. C# rejects mismatched IDs.
- Confirmation expires when `tid`, `state_version`, or `session_epoch` changes.
- First CONFIRM response does NOT consume the `action_nonce`. The retry generates a new nonce.
- CONFIRM retry is allowed as **1 extra call beyond MAX_TOOL_CALLS** (separate budget).
  This prevents deadlock when CONFIRM arrives at call 7-8.
- Auto-fallback must NEVER auto-confirm. If CONFIRM times out, fallback is cancel/back.
- `confirmed` is an optional boolean field on `execute`, `navigate_to`, and `choose`
  tool schemas (default: false, omitted in normal calls).

#### Knowledge Tools

**`write_note`**
Write or update a note in the persistent knowledge base.
Inspired by Claude Plays Pokemon's `update_knowledge_base`.

```json
{
  "type": "function",
  "strict": true,
  "name": "write_note",
  "description": "Write or update a note in your knowledge base. Use structured keys. Notes persist across turns and are visible to stream viewers. Write when you learn something important about enemies, zones, tactics, or your current plan.",
  "parameters": {
    "type": "object",
    "properties": {
      "key": { "type": "string", "description": "Category key", "enum": [
        "current_objective", "current_plan", "known_dangers",
        "learned_tactics", "zone_notes", "build_notes", "mistakes_to_avoid"
      ]},
      "content": { "type": "string", "description": "Note content. Be specific and actionable." }
    },
    "required": ["key", "content"],
    "additionalProperties": false
  }
}
```

Returns (accepted):
```json
{
  "written": true,
  "key": "learned_tactics",
  "chars_used": 180,
  "chars_max": 300,
  "admission_check": "passed"
}
```

Returns (rejected by admission control):
```json
{
  "written": false,
  "key": "known_dangers",
  "reason": "No supporting evidence in recent 10 turns for this claim",
  "admission_check": "failed_confidence"
}
```

**`read_notes`**
Read the current knowledge base. Automatically injected at session start,
but can be explicitly called to refresh.

```json
{
  "type": "function",
  "strict": true,
  "name": "read_notes",
  "description": "Read your current knowledge base. Notes are also shown at the start of each session.",
  "parameters": { "type": "object", "properties": {}, "required": [], "additionalProperties": false }
}
```

Returns:
```json
{
  "notes": {
    "current_objective": "explore:stairs_down:JoppaWorld.10.25 — Find stairs to go deeper",
    "current_plan": "Clear remaining hostiles, then head east to stairs",
    "known_dangers": "snapjaw hunters have ranged attacks; avoid open terrain [✓×3]",
    "learned_tactics": "2 snapjaws adjacent → retreat to cover → SuccessfulDisengage [✓×2]",
    "zone_notes": "JoppaWorld.10.25: water available, Mehmet offers water ritual",
    "build_notes": "Pyrokinesis effective vs groups, Blink for emergency escape",
    "mistakes_to_avoid": "Run #6: NO_RETREAT vs SWARM. Use Blink when adjacent>=3 and HP<40%"
  }
}
```

#### Cancel / Back Tool

**`cancel_or_back`** (v4.0: new, Phase 2 Gate 2 prerequisite)
Cancel the current modal, close a submenu, or back out of a nested screen.
Prevents deadlock in confirmation modals, inventory submenus, and merchant screens
where `choose` + safe default alone is insufficient.

```json
{
  "type": "function",
  "strict": true,
  "name": "cancel_or_back",
  "description": "Cancel or go back from the current modal, submenu, or nested screen. Use when you want to exit without making a selection, or when you navigated into a submenu by mistake.",
  "parameters": {
    "type": "object",
    "properties": {
      "reason": { "type": "string", "description": "Brief explanation for stream viewers, max 80 chars" }
    },
    "required": ["reason"],
    "additionalProperties": false
  }
}
```

Returns:
```json
{
  "accepted": true,
  "turn_complete": false,
  "action_kind": "cancel_or_back",
  "previous_modal": "merchant",
  "current_modal": null,
  "new_game_state": "navigation",
  "note": "Exited merchant screen."
}
```

`cancel_or_back` is NOT a terminal action — it exits the current modal layer but does not
end the turn. The tool loop continues, allowing the LLM to inspect surroundings and decide
what to do next. If a nested modal exists (e.g., merchant → item detail), `cancel_or_back`
pops one level (item detail → merchant). Repeated calls pop further levels.

**v4.0d: State recomputation after cancel_or_back**:
When `cancel_or_back` closes a modal, the `tool_result` includes updated state:
```json
{
  "accepted": true,
  "turn_complete": false,
  "action_kind": "cancel_or_back",
  "previous_modal": "merchant",
  "current_modal": null,
  "new_game_state": "navigation",
  "note": "Exited merchant screen."
}
```
Python Brain MUST update `game_state` and `allowed_tools` from `new_game_state` before
the next iteration of the tool loop. This prevents tool starvation (e.g., being stuck
with modal-only tools after the modal is closed). The `run_turn()` loop re-calls
`select_allowed_tools(new_game_state)` when it receives a `cancel_or_back` result.

If no modal is active, returns `{"accepted": false, "reason": "No active modal to cancel"}`.

**v5.0: Conversation cancel edge case**: `ConversationUI.Escape()` is blocked when
`CurrentNode.AllowEscape == false` (ConversationUI.cs:575). In this case, `cancel_or_back`
returns `{"accepted": false, "reason": "Current conversation node does not allow escape"}`.
The LLM must use `choose` to select an available option instead.

**v5.2: cancel_or_back semantic mapping by modal type**:
`cancel_or_back` maps to different native operations depending on the active modal:

| Modal Type | Cancel Semantics | Native Operation |
|-----------|-----------------|------------------|
| **Yes/No popup** | Select "No" | `OnActivateCommand(noItem)` — ShowYesNo has no Cancel button (Popup.cs:2244) |
| **Yes/No/Cancel popup** | Select "Cancel" | `OnActivateCommand(cancelItem)` |
| **Choice popup** | Close/back | Prefer `OnActivateCommand(backItem)`. Use `BackgroundClicked()` only after a null-safe cancel-item lookup — `PopupMessage.BackgroundClicked()` (PopupMessage.cs:876-879) does `FirstOrDefault()` for a cancel command and can null-deref if none exists. |
| **Conversation** | Exit dialogue | `ConversationUI.Escape()` (blocked if `AllowEscape == false` → return error) |
| **Merchant (modern)** | Exit trade | TBD (Phase 5+) |
| **Merchant (legacy)** | Exit trade | `Keyboard.PushKey(Keys.Escape)` |
| **Level-up** | Supervisor takeover | `{"accepted": false, "reason": "Level-up requires human selection — supervisor notified"}`. v5.3: Level-up choices affect build identity. Auto-selecting "first option" corrupts the build strategy. On timeout, the system pauses and notifies the human supervisor instead of auto-selecting. |

The C# MOD inspects the current modal type and selects the appropriate native cancel operation.
For popups with no explicit cancel (e.g., Yes/No), "cancel" means selecting the safe/negative option.

### Action Tool Terminal Contract (v3.2-lite)

`execute`, `navigate_to`, and `choose` are all **terminal actions** — they end the tool-calling
loop for the current turn. The C# response for all three uses a common result structure:

```json
// navigate_to example:
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "navigate_to",
  "execution_status": "in_progress",
  "acceptance_status": "accepted",
  "safety_decision": "pass",
  "action_summary": "Move toward stairs_down at [8, 0]",
  "destination": "stairs_down at [8, 0]",
  "estimated_steps": 5,
  "outcome": null,
  "safety_warning": null
}

// execute example:
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "execute",
  "execution_status": "accepted",
  "acceptance_status": "accepted",
  "safety_decision": "pass",
  "action_summary": "Retreat NW to cover",
  "outcome": {"hp_delta": 0, "net_value": 2.5, "tags": ["broke_los"]},
  "safety_warning": null
}
```

Key differences by `action_kind`:
- `navigate_to`: `execution_status` is `"in_progress"` (AutoAct started), `outcome` is `null` (no immediate outcome), includes `destination` and `estimated_steps`
- `execute`: `execution_status` is `"accepted"`, `outcome` contains ActionOutcome
- `choose`: `execution_status` is `"accepted"`, `outcome` is `null`

| Field | Description |
|-------|------------|
| `accepted` | Whether the action was accepted (false = BLOCKED, STALE, or CONFIRM-pending) |
| `turn_complete` | Always true for accepted actions. LLM loop must exit. |
| `action_kind` | `"execute"`, `"navigate_to"`, or `"choose"` |
| `action_summary` | Human-readable summary for overlay |
| `outcome` | ActionOutcome (only for execute; null for navigate_to/choose) |
| `safety_warning` | SafetyGate warning message, or null |
| `execution_status` | **In terminal action result**: `"accepted"` (execute/choose succeeded) or `"in_progress"` (navigate_to command accepted, AutoAct started). **In subsequent turn_start messages** (NOT in the terminal result): `interrupt_reason` reports `"arrived"` / `"hostile_perceived"` / `"took_damage"` etc. The terminal action result only indicates command acceptance, never ongoing AutoAct progress. |
| `acceptance_status` | v3.4: `"accepted"` \| `"blocked"` \| `"confirm_required"` \| `"stale"` \| `"duplicate"` \| `"stale_epoch"`. Replaces the overloaded `accepted` boolean for richer rejection semantics. |
| `safety_decision` | v3.4: `"pass"` \| `"warn"` \| `"confirm"` \| `"block"`. Separate from `acceptance_status` — a WARN action is still accepted. |

When `accepted == false`, the loop continues (LLM can re-request candidates or try a different action).

---

## 3. Verification Design: How the Agent Judges Good vs Bad

### Three Levels of Quality Signal

Based on survey of Voyager, CLIN, Reflexion, ExpeL, Motif, and BALROG.

#### Level 1: Per-Action Signal (C# computed, 0ms, every turn)

Reuses v2.1 `ActionOutcome` from DeltaTracker.cs:

```
net_value =
  - damage_taken × 2.0        (taking damage is bad)
  + damage_dealt × 1.0        (dealing damage is good)
  + enemies_killed × 15.0     (killing enemies is very good)
  + goal_displacement × 3.0   (progress toward objective, see definition below)
  - items_consumed × 5.0      (using consumables has cost)
  - risk_delta × 1.5          (increasing risk is bad)
  + (state_changed ? 0 : -2)  (no state change = wasted turn)
```

**v4.0: `risk_delta` definition** (was undefined in v3):
```
risk_delta = post_risk - pre_risk

where risk is computed per-turn as:
  risk = (1.0 - hp_fraction) × 30.0            // low HP = high risk
       + adjacent_hostile_count × 8.0            // surrounded = high risk
       + (in_ranged_los ? ranged_enemy_count × 5.0 : 0)  // exposed to ranged fire
       - cover_value × 12.5                       // cover reduces risk (Cell.GetCover(): 0.0–1.0)
       - (escape_ability_ready ? 5.0 : 0)        // escape option reduces risk

hp_fraction = current_hp / max_hp
adjacent_hostile_count = hostiles in 8-neighbor cells (Chebyshev distance 1)
              // Cell.GetLocalAdjacentCells() returns 8 directional neighbors (NW,N,NE,E,SE,S,SW,W)
              // Cell.cs:286 DirectionList, Cell.cs:6877 GetLocalAdjacentCells()
              // Use: cell.AnyAdjacentCell(C => C.HasObjectWithPart("Brain", GO => GO.IsHostileTowards(player)))
ranged_enemy_count = hostiles with ranged attacks that have LOS to player
cover_value = The.Player.CurrentCell.GetCover()   // float 0.0–1.0 from Zone.GetCoverAt()
              // MissileMapType: Empty=0, VeryLightCover=0.05, LightCover=0.1,
              // MediumCover=0.3, HeavyCover=0.5, VeryHeavyCover=0.8, Wall=1.0
escape_ability_ready = Blink/Sprint/etc. off cooldown

Example: retreating from open ground (risk=35) to cover (risk=12) → risk_delta = -23
         risk_delta × 1.5 = -34.5 (large positive contribution to net_value)
```

Note: `damage_taken` and `risk_delta` partially overlap (low HP increases both).
This is intentional — `damage_taken` penalizes the event, `risk_delta` penalizes
the resulting state. Weight calibration (Phase 3) may adjust the coefficients.

**v3.1: goal_displacement definition** (Pro review: "undefined, will become reward noise"):
```
goal_displacement is computed from the agent's current_objective note:
- If current_objective mentions a target zone/NPC/object:
    displacement = (previous_distance - current_distance) to that target
    Normalized to [-1.0, 1.0] where 1.0 = reached target, -1.0 = moved maximally away
- If current_objective is "explore" or unset:
    displacement = number_of_new_cells_revealed / 10.0 (capped at 1.0)
- If in combat (no navigation goal):
    displacement = 0.0 (combat uses damage/kill signals instead)
```

This is included in the `execute` tool response so the LLM sees immediate feedback.

**v3.2-lite: Weight calibration is deferred**. Current weights are initial estimates.
Known issues (Pro review):
- `damage_taken` and `risk_delta` partially overlap
- `enemies_killed × 15.0` over-rewards risky kills (should be threat-weighted)
- `items_consumed × 5.0` doesn't account for scarcity (last salve ≠ spare salve)
Calibration plan: After 20+ runs of data, use EncounterOutcome as target variable
to tune weights via regression or Bayesian optimization. Phase 3 task.

**v3.1: Decomposed quality tags** (Pro review: "net_value alone is too scalar"):

In addition to net_value, the outcome includes boolean tags explaining *why*:
```
tags: [
  "maintained_cover",      // stayed in cover during combat
  "broke_los",             // broke line of sight to ranged enemy
  "burned_escape_cd",      // used an escape ability (now on cooldown)
  "consumed_last_heal",    // used last healing item
  "took_unnecessary_damage", // took damage that was avoidable
  "wasted_turn",           // no state change occurred
  "progressed_toward_goal", // moved closer to current objective
  "engaged_stronger_enemy", // attacked enemy with higher threat score
]
```

These tags are computed by DeltaTracker.cs from pre/post state comparison.

**v3.2: Candidate & Safety Logging** (for meta-agent analysis and debugging):

```sql
-- Log ALL candidates generated per turn (not just the selected one)
CREATE TABLE candidate_scores (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    candidate_set_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verb TEXT NOT NULL,
    tag TEXT NOT NULL,
    score REAL NOT NULL,
    safety TEXT NOT NULL,          -- "ok"|"warn"|"block"
    was_selected BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Log SafetyGate BLOCK/WARN decisions with reasons
CREATE TABLE safety_gate_log (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    gate_layer TEXT NOT NULL,     -- "pre_navigate"|"pre_choose"|"post_execute"
    decision TEXT NOT NULL,       -- "BLOCK"|"CONFIRM"|"WARN"|"PASS"
    reason TEXT,                  -- human-readable reason
    tool_name TEXT NOT NULL,
    tool_args TEXT,               -- JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**v4.0: Plateau Detection** (for self-improvement loop):
Plateau is defined as **N-run statistical comparison showing no measurable improvement
in `eval_score`** for 3 consecutive improvement cycles (each cycle = 5-10 runs).
Full-game fixed-seed identical replay is NOT possible in CoQ (combat RNG is a separate
channel — see §10 CoQ Seed Limitation). C# component regression tests use fixed seeds
for deterministic unit testing, but plateau detection operates at the statistical level.
3 consecutive cycles with eval_score improvement < 1 standard deviation → escalate to human.
This avoids the flee-bot trap where `survival_turns` improves but gameplay quality degrades.

**v3.2: Composite Evaluation Metric**:
```
eval_score = survival_turns × milestone_completion × (1 - flee_rate)
```
This single metric balances longevity, progress, and engagement. Optimizing `survival_turns`
alone incentivizes fleeing; `milestone_completion` alone incentivizes recklessness.
The `(1 - flee_rate)` term penalizes overly passive play.

**`flee_rate` definition**:
`flee_rate = NeutralEscape_count / total_encounter_count`
Only `NeutralEscape` (fled with significant damage) counts as fleeing.
`SuccessfulDisengage` (retreated safely — correct tactical play) does NOT count as fleeing.
This prevents penalizing good tactical retreats in the eval metric.

**v4.0: NeutralEscape threshold**: An escape is classified as `NeutralEscape` (not
`SuccessfulDisengage`) when total HP lost during the encounter exceeds 25% of max HP.
This threshold distinguishes "tactical retreat" (low cost) from "fled badly hurt" (high cost).
Calibrate after 20+ runs of data — if SuccessfulDisengage dominates, lower to 15%.

The LLM sees both the scalar net_value AND the decomposed tags, enabling
it to understand *why* an action was good or bad, not just *that* it was.

**Quality classification:**
- net_value > 2.0 → good action
- net_value in [-3.0, 2.0] → neutral
- net_value < -3.0 → bad action

#### Level 2: Per-Encounter Signal (C# computed, at encounter boundaries)

Reuses v2.1 `EncounterResult` from EncounterTracker.cs:

```
EncounterOutcome:
  Win                  → success (all hostiles eliminated)
  SuccessfulDisengage  → success (retreated safely — correct tactical play)
  NeutralEscape        → ambiguous (fled with >25% max HP lost during the encounter)
  FailedEscape         → failure (cornered or heavy damage during retreat)
  Death                → failure
```

Encounter boundary detection: 3-turn hysteresis (no hostile visible for 3 consecutive turns).

**Fed into notes**: After each encounter, the system auto-generates a summary
that the LLM can see. This uses CLIN-style causal abstraction templates:

```
Pattern: "{situation} → {action} → {outcome} BECAUSE {reason}"
Example: "2 snapjaws adjacent → retreated NW to cover → SuccessfulDisengage
          BECAUSE cover blocked ranged LOS"
```

#### Level 3: Per-Run Signal (post-death, offline)

**Death Taxonomy (3-tier, novel — no prior roguelike has this):**

```
Tier 1 — Proximate cause (C# computed):
  RANGED_ALPHA, SWARM, STATUS, HAZARD, RESOURCE, MELEE_SPIKE,
  ENVIRONMENT (v5.3: falling, lava, acid, gas, drowning, cave-in),
  SELF_DAMAGE (v5.3: friendly fire, self-immolation, AoE hitting self),
  CONTROL_LOSS (v5.3: domination, confusion-induced suicide, berserk),
  THIRST_STARVATION (v5.3: dehydration/starvation — distinct from RESOURCE which covers consumables),
  UNKNOWN (v5.3: catch-all for unclassifiable deaths)

Tier 2 — Strategic error (v3.1: code-first shortlist, LLM ranks/explains only):
  NO_RETREAT (didn't flee when should have)      — code: HP<40% + adjacent>=2 + retreat candidates existed
  NO_HEAL (didn't use available healing)          — code: HP<30% + heal item available + not used in last 5 turns
  ABILITY_UNUSED (had counter ability, didn't use it) — code: from classify_death_counter()
  BAD_POSITIONING (engaged in open with ranged enemies) — code: ranged_enemy_los + no_cover_used
  OVEREXTENSION (went too deep into dangerous zone)    — code: zone_tier > player_level/3
  RESOURCE_MISMANAGEMENT (ran out of healing/water)    — code: resource_count_at_death == 0

  Note: Each Tier 2 error has a code-based detection rule (not free-form LLM classification).
  LLM is only used to rank which error was most impactful and generate a human-readable explanation.
  This prevents "plausible but wrong" causal attribution (Pro review concern).

Tier 3 — Build-relative assessment (code-based):
  HAD_COUNTER (build had ability to handle this death cause)
  COUNTER_WAS_USED (did the agent actually use it?)
  BUILD_WEAKNESS (death cause is inherent weakness of this build)
```

Reuses v2.1's `DeathCapabilitySnapshot` + `classify_death_counter()` for Tier 3.

**Death recap note** (auto-generated, persisted to knowledge base):
```
"Run #7 death: SWARM:snapjaw:melee at turn 42 in Joppa Outskirts.
 Strategic error: NO_RETREAT — had 3 adjacent hostiles, HP was 35%.
 Build assessment: HAD_COUNTER (Blink was available, cooldown=0), COUNTER_WAS_USED=false.
 Lesson: Use Blink to escape when outnumbered 3:1 with HP below 40%."
```

This note is injected into `mistakes_to_avoid` for the next run.

---

## 4. Memory Stack: Low-Noise Knowledge Persistence

### v3.2: 2-Layer Architecture

| Layer | Storage | Size | Injected | Phase |
|-------|---------|------|----------|-------|
| **Active Memory** | 7 fixed-key notes | ~400 tokens | Every turn (system prompt) | Phase 2 (MVP) |
| **Archive Memory** | SQLite FTS5 | Unbounded | On-demand via `search_archive` | Phase 3 (deferred) |

Active Memory is the LLM's working memory — always visible, tightly constrained.
Archive Memory is long-term storage — keyword-searchable, used when the LLM needs
to recall specific encounters, enemies, or zones from earlier in the run or prior runs.

**`search_archive`** — Deferred to Phase 3. Keyword search against SQLite FTS5 index.
Upgrade path: FTS5 keyword search (Phase 3) → sqlite-vec semantic search (if needed).

**`spatial_log`** — Deferred to Phase 3. C# will auto-populate zone visit data
when the archive layer is implemented. Schema (v4.0, from revision-plan):
```sql
CREATE TABLE spatial_log (
    zone_id TEXT PRIMARY KEY,
    zone_name TEXT,
    zone_tier INTEGER,
    visit_count INTEGER DEFAULT 1,
    last_visited_turn INTEGER,
    enemies_encountered TEXT,  -- JSON array of archetype names
    items_found TEXT,          -- JSON array
    danger_rating TEXT,        -- "safe" | "moderate" | "dangerous" | "deadly"
    notes TEXT,                -- auto-generated summary
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Design Principles (from research)

1. **Structured > unstructured** — CLIN's templates outperform free-form by 23 points
2. **Observation masking > summarization** — JetBrains found masking old observations saves 52% cost with +2.6% success
3. **Importance-based retention** — ExpeL's ADD/UPVOTE/DOWNVOTE/EDIT for noise control
4. **Self-reinforcing error is the #1 risk** — false beliefs persist and worsen over time

### Goal Ledger (v5.3: viewer-legible objective tracking)

The fixed-key `current_objective` and `current_plan` notes are supplemented by a
structured **Goal Ledger** — a viewer-facing log of objective lifecycle events.
This addresses the contamination repair gap identified in holistic review.

```json
{
  "goals": [
    {
      "id": "g1",
      "kind": "explore",
      "target": "stairs_down",
      "zone": "JoppaWorld.10.25",
      "status": "active",
      "reason": "Need to go deeper to find Argyve's quest item",
      "created_tid": 42,
      "evidence_for": ["found stairs icon on map at turn 38"],
      "evidence_against": [],
      "abandoned_reason": null
    },
    {
      "id": "g0",
      "kind": "quest",
      "target": "copper_wire",
      "zone": "Joppa",
      "status": "abandoned",
      "reason": "Argyve asked for copper wire",
      "created_tid": 10,
      "evidence_for": ["Argyve dialogue confirmed"],
      "evidence_against": ["no copper wire found in 30 turns of exploration"],
      "abandoned_reason": "Deprioritized — exploring deeper first, will return"
    }
  ]
}
```

**Goal lifecycle**: `active` → `completed` | `abandoned` | `blocked`
- `blocked`: obstacle detected (e.g., too dangerous, path not found)
- `abandoned`: LLM decides to deprioritize (must provide reason)
- `evidence_against`: accumulated contradictions trigger re-evaluation

**Contamination repair**: When `evidence_against` accumulates ≥3 entries for an active goal,
the system injects a prompt: "Your current objective has contradictory evidence. Re-evaluate."
This prevents the LLM from fixating on stale or incorrect goals (a key failure mode
identified in Gemini Plays Pokemon's "context poisoning" and "delusion" patterns).

**Viewer display**: The overlay shows the current active goal + status. Abandoned goals
with reasons are shown briefly as "learning moments" for entertainment value.

**Storage**: Goal Ledger is a JSON blob in `notes_history` with key `"goal_ledger"`.
Not counted against the 7 fixed-key token budget (stored separately, injected on demand).

### Layer 1: Session Notepad (LLM-managed, per-run)

The LLM writes and reads structured notes via `write_note` / `read_notes` tools.

**Fixed key schema** (constrained to prevent note sprawl):

| Key | Purpose | Max size | Update frequency | Scope |
|-----|---------|----------|-----------------|-------|
| `current_objective` | What am I trying to do right now? | 100 chars | Every few turns | run |
| `current_plan` | Step-by-step plan for current objective | 200 chars | When plan changes | run |
| `known_dangers` | Enemies/zones/situations to avoid | 300 chars | After encounters | cross-run |
| `learned_tactics` | Tactics that worked or failed | 300 chars | After encounters | cross-run |
| `zone_notes` | Information about current/recent zones | 200 chars | On zone change | run |
| `build_notes` | Strengths/weaknesses of current build | 200 chars | Rarely | build-specific |
| `mistakes_to_avoid` | Lessons from deaths (auto + manual) | 300 chars | After death | cross-run |

**Total budget: ~1600 chars (~400 tokens)**. Injected into system prompt every turn.

**v3.2-lite: `current_objective` structured format**:
The `current_objective` note uses a structured format for machine-readable goal tracking:
```
Format: "{kind}:{target}:{zone} — {description}"
Example: "explore:stairs_down:JoppaWorld.10.25 — Find stairs to go deeper"
Example: "combat:snapjaw_hunter:JoppaWorld.10.25 — Eliminate ranged threat"
Example: "quest:Argyve:Joppa — Deliver copper wire to Argyve"
```
`goal_displacement` parses the `kind` and `target` fields to compute distance.
If the format is invalid, `goal_displacement = 0.0` (safe default).
**v4.0**: `write_note` for `current_objective` validates the structured format via regex
(`^(explore|combat|quest|flee):[^:]+:[^:]+\s—\s.+$`). Invalid formats are rejected with
feedback: `"current_objective must use format: {kind}:{target}:{zone} — {description}"`.
This prevents silent degradation of goal_displacement.

**v3.1: Scope column** separates run-local notes (cleared each run) from cross-run
notes (persisted). `build_notes` is tagged as build-specific — only loaded when
the same build_id is played again. This prevents cross-build contamination
(Pro review: "scope separation is weak").

**Noise reduction mechanisms:**

1. **Enum keys**: LLM cannot create arbitrary keys. 7 fixed categories only.
2. **Size limits**: Each key has a max character count. Overflow is truncated.
3. **CLIN-style templates**: System prompt instructs LLM to write in
   `"{situation} → {action} → {outcome}"` format for `learned_tactics`.
4. **Auto-generated death lessons**: `mistakes_to_avoid` is partially auto-filled
   from Tier 2/3 death analysis, reducing reliance on LLM self-reflection.
5. **Validation on write**: Python Brain checks for contradictions with recent
   game state (e.g., writing "snapjaws are weak" right after dying to snapjaws).
6. **Admission control** (v3.3: moved from Phase 3 to Phase 2, A-MAC-inspired):
   Before accepting a write to `learned_tactics`, `known_dangers`, or `mistakes_to_avoid`
   (keys where errors can be lethal), apply a 2-axis gate:
   - **Confidence**: Does the note have supporting evidence in the last **10 turns**?
     Python Brain queries `tool_calls` and `action_outcomes` tables for the last 10 tids.
     (e.g., writing "X is weak to fire" requires a fire attack on X in tids [current-10, current])
     The 10-turn window is approximately 2 encounters, ensuring the evidence is fresh.
   - **Novelty**: Is this information already captured by an existing entry?
     (semantic similarity > 0.85 with an existing note → merge, not duplicate)
   Notes that fail both axes are rejected with feedback to the LLM.
   Other keys (`current_objective`, `current_plan`, `zone_notes`, `build_notes`)
   are free-write — admission control only guards "cross-run survival knowledge".
   **v3.3 rationale** (Pro review #3): Deferring to Phase 3 risks contaminating
   the first several runs with false beliefs in `known_dangers` / `learned_tactics`.
   Phase 2 MVP implements at minimum the confidence axis (evidence check against
   recent game events). Novelty axis (semantic similarity) deferred to Phase 3.
7. **v3.1: Evidence counting** (from ExPeL): Each `learned_tactics` and `known_dangers`
   entry is internally tracked with `{confirm_count, contradict_count, last_updated_turn}`.
   When `contradict_count >= confirm_count`, the entry is flagged as unreliable and
   marked with `[?]` in the LLM's view. After 3+ contradictions with 0 confirmations,
   the entry is auto-removed. This prevents stale beliefs from fossilizing.
8. **v3.1: Cross-run seeding validation** (Pro review: "best-run seeding is dangerous"):
   Cross-run notes are not seeded from a single best run. Instead, only entries
   that appeared in ≥2 of the last 5 runs AND have `confirm_count > contradict_count`
   are carried forward. This prevents lucky-run overfitting.

### Layer 2: Auto-Log (C#/Python, SQLite)

Automatic structured logging. LLM does not write here. LLM can query via analysis tools or `search_archive` (Phase 3).

```sql
-- From v2.1, retained as-is
CREATE TABLE death_events (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    build_id TEXT NOT NULL,
    root_cause_key TEXT NOT NULL,       -- Tier 1: RANGED_ALPHA, SWARM, STATUS, HAZARD, RESOURCE, MELEE_SPIKE, ENVIRONMENT, SELF_DAMAGE, CONTROL_LOSS, THIRST_STARVATION, UNKNOWN
    root_cause_detail TEXT,             -- e.g., "snapjaw:melee"
    strategic_error TEXT,               -- v4.0 Tier 2: NO_RETREAT, NO_HEAL, etc.
    strategic_error_confidence REAL,    -- code-based detection confidence (0.0-1.0)
    had_counter BOOLEAN,               -- Tier 3
    counter_was_used BOOLEAN,          -- Tier 3
    build_weakness BOOLEAN,            -- Tier 3
    zone_id TEXT,
    hp_at_death INTEGER,
    turn_of_death INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE build_runs (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL UNIQUE,
    build_id TEXT NOT NULL,             -- e.g., "MutatedHuman:Pyrokinetic"
    game_mode TEXT NOT NULL,            -- "roleplay" | "classic"
    world_seed TEXT,
    harness_version TEXT NOT NULL,
    model_id TEXT NOT NULL,             -- e.g., "gpt-5.4"
    survival_turns INTEGER,
    death_cause TEXT,                   -- Tier 1 root_cause_key, null if alive
    milestone_completion REAL,          -- 0.0–1.0, computed from milestone checklist
    flee_rate REAL,                     -- NeutralEscape_count / total_encounter_count
    eval_score REAL,                    -- survival_turns × milestone_completion × (1 - flee_rate)
    encounter_count INTEGER DEFAULT 0,
    tool_calls_total INTEGER DEFAULT 0,
    fallback_count INTEGER DEFAULT 0,   -- times state_fallback() was triggered
    fallback_rate REAL,                 -- fallback_count / survival_turns
    p50_latency_ms INTEGER,            -- median turn latency
    p95_latency_ms INTEGER,            -- 95th percentile turn latency
    max_latency_ms INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE encounter_log (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    encounter_id TEXT NOT NULL,         -- unique per encounter
    start_tid INTEGER NOT NULL,
    end_tid INTEGER NOT NULL,
    outcome TEXT NOT NULL,              -- Win, SuccessfulDisengage, NeutralEscape, FailedEscape, Death
    enemy_archetypes TEXT NOT NULL,     -- JSON array: ["snapjaw", "snapjaw hunter"]
    enemy_count INTEGER NOT NULL,
    hp_lost INTEGER,                   -- total HP lost during encounter
    hp_lost_fraction REAL,             -- hp_lost / max_hp (used for NeutralEscape threshold: >0.25)
    abilities_used TEXT,               -- JSON array of ability names used
    candidates_requested INTEGER,      -- number of request_candidates calls
    flee_attempted BOOLEAN DEFAULT 0,
    zone_id TEXT,
    causal_summary TEXT,               -- CLIN-style: "{situation} → {action} → {outcome} BECAUSE {reason}"
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New for v3
CREATE TABLE tool_calls (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments TEXT,                    -- JSON
    result_summary TEXT,              -- truncated result
    latency_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE action_outcomes (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    candidate_id TEXT,
    verb TEXT NOT NULL,
    net_value REAL,
    hp_delta INTEGER,
    public_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE notes_history (
    id INTEGER PRIMARY KEY,
    rid TEXT NOT NULL,
    tid INTEGER NOT NULL,
    key TEXT NOT NULL,
    old_content TEXT,
    new_content TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- v4.0: Evidence counting persistence (was undefined in v3)
CREATE TABLE note_evidence (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,                  -- "learned_tactics" or "known_dangers"
    content_hash TEXT NOT NULL,         -- SHA-256 of normalized note content
    confirm_count INTEGER NOT NULL DEFAULT 0,
    contradict_count INTEGER NOT NULL DEFAULT 0,
    last_confirmed_rid TEXT,            -- last run that confirmed
    last_confirmed_tid INTEGER,
    last_contradicted_rid TEXT,         -- last run that contradicted
    last_contradicted_tid INTEGER,
    status TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'removed'
    removed_at TEXT,                    -- datetime when auto-removed
    first_seen_rid TEXT NOT NULL,       -- run where this note first appeared
    run_count INTEGER NOT NULL DEFAULT 1,  -- number of distinct runs that produced this note
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(key, content_hash)           -- cross-run: keyed by content, NOT by rid
);
```

**Evidence counting lifecycle** (v4.0):
- **Who increments**: Python Brain's `notes_manager.py`, triggered by game events.
- **When `confirm_count` increases**: After an encounter where the note's claim is
  consistent with the outcome (e.g., "snapjaws are dangerous in groups" + died to
  snapjaw swarm, or survived by following the tactic).
- **When `contradict_count` increases**: After an encounter where the note's claim
  contradicts the outcome (e.g., "snapjaws are weak" + died to snapjaws).
- **On `write_note` overwrite**: Old entry's counters are preserved in `note_evidence`
  table (keyed by `content_hash`). New content creates a new row with zeroed counters.
  This prevents counter reset on rewording while preserving history.
- **Auto-remove check**: Runs at encounter boundaries (not per-turn, not per-write).
  If `contradict_count >= 3 AND confirm_count == 0`, the entry is auto-removed
  from active memory and its `status` is set to `'removed'` with `removed_at` timestamp.
- **Cross-run persistence**: `note_evidence` rows persist across runs. The UNIQUE
  constraint is `(key, content_hash)` — not scoped to `rid`. When the same note
  content appears in a new run, `run_count` is incremented and `last_confirmed_rid`
  is updated. The ≥2/5 run seeding rule queries: `WHERE run_count >= 2 AND
  confirm_count > contradict_count AND status = 'active'`.

### Layer 3: Cross-Run Knowledge (Phase 3+)

**Deferred**. Initial implementation uses only Layer 1 + Layer 2.
When ready, the approach will be:

- Auto-extract from `death_events` + `encounter_log`: build-specific danger patterns
- **v3.2: Unified cross-run seeding rule**: Only entries confirmed in ≥2 of the last 5 runs
  AND with `confirm_count > contradict_count` carry forward to the next run. No single
  "best run" seeding — this prevents lucky-run overfitting.
- No vector DB initially. Simple SQL queries against structured logs.
- GLOVE-style validation: re-verify old "lessons" against new evidence periodically.

---

## 5. C# MOD Design (reused from v2.1)

### Retained Components

| Component | v2.1 Section | Changes for v3 |
|-----------|-------------|-----------------|
| Bootstrap.cs + IPlayerSystem registration | §2 | **v5.1: Changed from IGameSystem to IPlayerSystem** — `BeginTakeActionEvent` is an object event dispatched via `Object.HandleEvent()`, not a game event. `IGameSystem.HandleEvent(BeginTakeActionEvent)` is never called by the engine. `IPlayerSystem.RegisterPlayer()` registers on the player body and auto-handles body swap. `The.Game.RequireSystem<LLMOfQudSystem>()` registers the system. |
| Snapshotter.cs | §2 | Returns data for inspect tools instead of TurnRequest |
| BuildProfileCapture.cs | §1, §2 | No change (BirthBuildProfile + RuntimeCapabilityProfile) |
| CandidateGenerator.cs | §7 | **Now a tool backend**: called via `request_candidates` |
| SafetyGate.cs | §8 | **Role change**: validates `execute` tool calls, 4-tier response (v3.3: BLOCK/CONFIRM/WARN/PASS) |
| ToolExecutor.cs | §18 | No change (verb dispatch) |
| ModalInterceptor.cs | §8b | **v5.2: View-name family detection**. Detection: legacy popup (`Popup:*`), new popup (`PopupMessage`/`DynamicPopupMessage`/`StartsWith("ModernPopup")`), conversation (`ConversationUI.CurrentChoices != null`), trade (`ModernTrade`/`ConsoleTrade`), level-up (popup with level-up context). Operation: legacy → `Keyboard.PushKey()`. New popup list → `OnSelect(QudMenuItem)`. New popup button → `OnActivateCommand(QudMenuItem)`. Conversation → `ConversationUI.Select(int)`. Phase 2 out-of-scope: `ModernPopupGamepadAskNumber`, `ModernPopupTwiddleObject`. |
| DeltaTracker.cs | §11b | No change (ActionOutcome computation) |
| EncounterTracker.cs | §11b | No change (EncounterResult + EncounterOutcome) |
| DeathLogger.cs | §11 | No change (death signature + DeathCapabilitySnapshot) |
| BrainClient.cs | §2 | **Wire format changes** (tool call messages instead of TurnRequest) |

### New Components

| Component | Purpose |
|-----------|---------|
| ToolRouter.cs | Routes incoming tool call requests to appropriate handlers |
| InspectHandler.cs | Implements inspect_surroundings, check_status, check_inventory |
| AssessmentHandler.cs | Implements assess_threat (Phase 2). assess_escape and assess_ability added in Phase 3. Dispatches to ThreatScore, TileSafety, BuildProfile. |
| AutoActHandler.cs | Implements navigate_to backend: AutoAct integration, pathfinding, interrupt guard conditions |
| ChoiceHandler.cs | Implements choose backend: modal choice dispatch (dialogue, level-up, confirmation popups) |
| StreamOverlay.cs | Generates overlay data for streaming (goal, threats, reason, outcome) |

**v5.1: MOD Integration Strategy** (corrected after IPlayerSystem verification):

- **Primary**: `IPlayerSystem` (extends `IGameSystem`) — registers event handlers on the
  player body via `RegisterPlayer(GameObject Player, IEventRegistrar Registrar)`.
  This is required because `BeginTakeActionEvent.Check()` dispatches to `Object.HandleEvent()`,
  NOT to `The.Game.HandleEvent()`. `IGameSystem` alone cannot receive object-level events.
  `IPlayerSystem` auto-handles body swap via `AfterPlayerBodyChangeEvent` (IPlayerSystem.cs:42-53).
  Usage: `class LLMOfQudSystem : IPlayerSystem`, registered via `The.Game.RequireSystem<LLMOfQudSystem>()`.
  Examples in engine: `WanderSystem.cs:10,57-60`, `CodaSystem.cs:10,46-49`.

  **v5.5 (Codex Must-Fix #2): `RegisterPlayer()` MUST explicitly register the event ID.**
  Subclassing `IPlayerSystem` is necessary but not sufficient; without the explicit event
  registration the system does not receive `BeginTakeActionEvent`. The canonical shape is:

  ```csharp
  public override void RegisterPlayer(GameObject Player, IEventRegistrar Registrar) {
      Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID);
      // register other player-body events here (BeforeBeginTakeActionEvent, etc.)
  }

  public override bool HandleEvent(BeginTakeActionEvent E) {
      // player's turn is beginning — push turn_start to Python Brain here
      return base.HandleEvent(E);
  }
  ```

  Verified against: `decompiled/XRL.World/BeginTakeActionEvent.cs:37-52` (object-level
  dispatch), `decompiled/XRL/IPlayerSystem.cs:35` (RegisterPlayer signature),
  `decompiled/XRL/WanderSystem.cs:57` (example event registration).

- **Secondary**: `XRLCore.RegisterOnBeginPlayerTurnCallback(Action<XRLCore>)` (XRLCore.cs:576) —
  called from `PlayerTurn()` (L665) and from `ActionManager` during AutoAct steps (L848,
  but only when AutoAct is active). Use for lightweight per-turn notifications.
  **Caveat**: No duplicate-registration guard — must check before re-registering on mod reload.

- **Tertiary**: `Harmony` patches — only for methods without public event hooks
  (e.g., Popup.Show interception, ScreenBuffer post-render hooks).
  `ModInfo.ApplyHarmonyPatches()` auto-applies Harmony patches from mod assemblies (ModInfo.cs:847).

- **Cross-thread routing (v5.5: Codex Must-Fix #3)**: `GameManager.Instance` exposes
  two distinct ThreadTaskQueues (`gameQueue`, `uiQueue` at `GameManager.cs:142-144`).
  The WebSocket thread MUST NOT default-dispatch everything to `gameQueue`;
  new-popup interaction (`PopupMessage.OnSelect` / `OnActivateCommand` /
  `BackgroundClicked`) lives on the **UI thread** and `Popup.cs:823,908` confirms
  `uiQueue.awaitTask()` is how popups are shown while the game thread does
  `complete.Task.Wait()`. Invoking PopupMessage operations via `gameQueue` will
  deadlock or be dropped on frames where the game thread is waiting.

  | Operation | Target queue |
  |-----------|-------------|
  | `inspect_surroundings` / `check_status` / `check_inventory` / `assess_threat` (read player, zone, buffer) | `gameQueue` |
  | `navigate_to` / `execute` / `request_candidates` → `CommandEvent.Send` / AutoAct.Setting mutation | `gameQueue` |
  | `choose` / `cancel_or_back` on legacy `Popup:*` (Keyboard.PushKey) | `gameQueue` (input buffer) |
  | `choose` / `cancel_or_back` on new popup (`PopupMessage.OnSelect`, `OnActivateCommand`, `BackgroundClicked`) | **`uiQueue`** |
  | `choose` on `ConversationUI.Select` | `gameQueue` (conversation state is game-side) |
  | `write_note` / `read_notes` / telemetry SQLite writes | WebSocket thread (background; no queue) |

  **Deadlock warning**: `awaitTask()` blocks with `WaitOne()`, and the target
  thread must pump its task queue for completion (`executeTasks()` in
  `RenderBase()`, or `getch(pumpActions: true)` in Keyboard, or
  `uiQueue.executeTasks()` in GameManager — XRLCore.cs:2517, Keyboard.cs:1021,
  GameManager.cs:2842). **Do not call `awaitTask()` from a thread that the
  target queue needs in order to drain — this is the usual cause of the modal
  freeze in multi-queue designs.** Use `executeAsync()` (returns Task) for
  non-blocking patterns, or fire-and-forget `queueTask(...)` when the handler
  does not need the result synchronously.

### Safety Design (v3.2: multi-layer)

SafetyGate is **multi-layer**: pre-filter on `navigate_to` (zone danger) and `choose`
(irreversible options), plus post-validation on `execute` (BLOCK/CONFIRM/WARN/PASS).
This aligns with Pro's recommendation: "pre-filter + post-validation, not single gate."

**v3.3: CONFIRM level** (from Pro review #3): BLOCK/WARN/PASS alone was insufficient for
irreversible but non-fatal choices (mutation selection, faction dialogue, merchant transactions).
CONFIRM defers to the LLM with an explicit warning and requires the LLM to re-call the
action with `confirmed: true`. This prevents accidental irreversible choices during streaming.

| Level | Condition | Response | Example |
|-------|-----------|----------|---------|
| **BLOCK** | Certain death | Refuse execution, return alternatives | AoE hitting self, drinking acid |
| **CONFIRM** | Irreversible non-fatal | Defer to LLM with explicit warning, require re-confirmation | Permanent mutation choice, faction-altering dialogue, selling last healing item |
| **WARN** | High risk | Execute with warning in response | HP<30% attacking, entering dangerous zone |
| **PASS** | Normal | Execute silently | Standard movement, attack, ability use |

Pre-filter layers:
- **navigate_to**: WARN on dangerous zone (`zone_tier > player_level / 3`)
- **choose**: CONFIRM on irreversible dialogue options (if detectable by C#, e.g., permanent mutation selection)
- **execute**: Full BLOCK/CONFIRM/WARN/PASS post-validation (reuses v2.1 H1-H10 heuristics)

---

## 6. Python Brain Design

### Tech Stack (from v2.1, no changes)

Python 3.13, uv, basedpyright, mypy strict, ruff, Pydantic v2, httpx,
websockets 16.0, aiosqlite, structlog, pytest.

### Directory Layout (v3)

```
brain/
  app.py                    # WebSocket server (localhost:4040)
  tool_loop.py              # NEW: Tool-calling loop controller (max_calls, timeout)
  tool_schemas.py           # NEW: Tool JSON schema definitions for Codex API
  prompt_builder.py         # System prompt + notes injection
  notes_manager.py          # NEW: Knowledge base read/write with validation
  auth/
    device_flow.py          # Codex Device Code Flow (from v2.1)
    token_store.py          # ~/.codex/auth.json (from v2.1)
    broker.py               # JWT refresh (from v2.1)
  clients/
    codex_client.py         # Responses API + tool_use + SSE parse
  session/
    manager.py              # Session state, build profile, history
    compactor.py            # Background history compaction (simplified)
  safety/
    tool_validator.py       # NEW: Validate tool call arguments before forwarding
    json_parser.py          # Robust JSON extraction (from v2.1)
  overlay/
    stream_state.py         # NEW: Current overlay data for streaming
  db/
    schema.py               # SQLite table definitions
    writer.py               # Async log writer
```

**v3.3: Isolation note** (from Pro review #3): Python Brain currently hosts
tool schemas, prompt building, notes management, provider client, overlay state,
and DB writer in a single process. This is acceptable for MVP but risks
"god-process" coupling in Phase 3+. Plan to isolate notes_manager, overlay,
provider, and session into separate modules with clear interfaces by Phase 3.

### Codex API Client (v3.2-lite)

Phase 2 uses CodexProvider (gpt-5.4) directly. Multi-provider support
(Claude, Gemini) is deferred to Phase 3+ — different continuation semantics,
caching behavior, and streaming event shapes make a simple wrapper insufficient.
This is not needed for streaming MVP.

```python
# Phase 2: Direct implementation
class CodexProvider:
    async def create(self, input, tools, tool_choice, **kwargs) -> Response: ...
```

### Tool-Calling Loop (tool_loop.py) — v3.2-lite: State-Aware Terminal Actions

Uses `previous_response_id` for server-side continuation, `call_id` for tool result
matching, and `parallel_tool_calls=false` for sequential execution.
After `FORCE_ACTION_AFTER` calls, restricts `tool_choice` to terminal actions
appropriate for the current game state (not a system nudge — an API constraint).

```python
MAX_TOOL_CALLS_PER_TURN = 8
TURN_TIMEOUT_S = 10.0
FORCE_ACTION_AFTER = 6
TERMINAL_ACTIONS = {"execute", "navigate_to", "choose"}
AUTOACT_HEARTBEAT_S = 5.0       # v5.3: Viewer-facing progress pulse (overlay shows "navigating...")
AUTOACT_SOFT_TIMEOUT_S = 10.0   # v5.3: Warn — log + overlay "navigation taking longer than expected"
AUTOACT_HARD_TIMEOUT_S = 15.0   # v5.3: Act — send heartbeat ping to C#, trigger reconnect if no ack
                                # Rationale: "30 seconds of silence kills viewership" →
                                # detection must be well BEFORE the fatal line, not AT it.

def select_allowed_tools(game_state: str) -> list[dict]:
    """Select available tools based on current game state."""
    COMBAT_TOOLS = ["inspect_surroundings", "check_status", "check_inventory",
                    "assess_threat", "request_candidates", "execute", "write_note"]
    NAVIGATION_TOOLS = ["inspect_surroundings", "check_status", "check_inventory",
                        "navigate_to", "request_candidates", "execute",
                        "write_note", "read_notes"]
    MODAL_TOOLS = ["inspect_surroundings", "check_status", "choose", "cancel_or_back", "write_note"]

    tools = {
        "combat": COMBAT_TOOLS,
        "navigation": NAVIGATION_TOOLS,
        "modal": MODAL_TOOLS,
        "idle": NAVIGATION_TOOLS,  # idle uses navigation tools
    }.get(game_state, NAVIGATION_TOOLS)
    return [{"type": "function", "name": t} for t in tools]

def force_action_tools(game_state: str) -> list[dict]:
    """After FORCE_ACTION_AFTER calls, restrict to terminal actions only.

    v5.5 (Codex Should-Fix S5): navigation/idle allow request_candidates+execute
    for utility (heal/wait/consume_item) when HP is low. The State × Fallback
    Matrix default (navigate_to nearest unexplored) is the *auto-pick* applied
    only when the LLM produces no terminal action — this `forced` list is the
    allowed surface while the LLM is still choosing. Same semantics.
    """
    forced = {
        "combat": ["request_candidates", "execute"],
        "navigation": ["navigate_to", "request_candidates", "execute"],  # utility fallback for low HP
        "modal": ["choose", "cancel_or_back"],
        "idle": ["navigate_to", "request_candidates", "execute"],  # utility fallback for low HP
    }.get(game_state, ["navigate_to"])
    return [{"type": "function", "name": t} for t in forced]

async def run_turn(session: Session, turn_notify: TurnNotification) -> Action:
    """Run one game turn's tool-calling loop using Responses API continuation."""
    initial_input = session.build_context(turn_notify)
    tool_calls_this_turn = 0
    prev_response_id: str | None = None
    game_state = turn_notify.game_state  # "combat" | "navigation" | "modal" | "idle"

    while tool_calls_this_turn < MAX_TOOL_CALLS_PER_TURN:
        # Determine tool_choice based on call count and game state
        if tool_calls_this_turn >= FORCE_ACTION_AFTER:
            # Force terminal actions appropriate for current state
            forced = force_action_tools(game_state)
            tool_choice = {"type": "allowed_tools", "mode": "required", "tools": forced}
        else:
            # Normal: filter tools by game state
            allowed = select_allowed_tools(game_state)
            tool_choice = {"type": "allowed_tools", "mode": "auto", "tools": allowed}

        request_kwargs = {
            "model": select_model(session),
            "tools": TOOL_SCHEMAS,
            "tool_choice": tool_choice,
            "parallel_tool_calls": False,
            "stream": True,
            "store": False,
        }

        # IMPORTANT: instructions must be sent on EVERY call.
        # previous_response_id does NOT inherit instructions.
        request_kwargs["instructions"] = session.system_prompt

        if prev_response_id is None:
            request_kwargs["input"] = initial_input
        else:
            request_kwargs["previous_response_id"] = prev_response_id
            request_kwargs["input"] = [tool_result_item]

        try:
            response = await codex_client.create(**request_kwargs)
        except PreviousResponseNotFound:
            # store=false means OpenAI may evict the cached response at any time.
            # When previous_response_id becomes invalid, gracefully reset:
            # rebuild full context from active memory + current turn snapshot
            # and start a fresh conversation within the same turn.
            prev_response_id = None
            request_kwargs.pop("previous_response_id", None)
            request_kwargs["input"] = session.build_context(turn_notify)
            response = await codex_client.create(**request_kwargs)
            # v4.0: Include tool call history in rebuilt context so LLM
            # doesn't re-call observation tools it already called this turn.
            # session.build_context() includes a "tools_called_this_turn" field
            # listing tool names + summaries from earlier in this turn.
        prev_response_id = response.id

        for output_item in response.output:
            if output_item.type == "function_call":
                tool_calls_this_turn += 1
                call_id = output_item.call_id

                result = await dispatch_tool(output_item.name, output_item.arguments)
                overlay.update_tool_call(output_item.name, output_item.arguments)

                tool_result_item = {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result.to_llm_view()),  # LLM view only, no scores
                }

                # Check for terminal actions
                if output_item.name in TERMINAL_ACTIONS:
                    if result.accepted:
                        return result.action  # Turn complete
                    # BLOCKED/STALE — continue loop to let LLM retry
                    overlay.update_safety(result.safety_warning or result.reason)

                # v4.0d: Non-terminal state-changing actions (cancel_or_back)
                if output_item.name == "cancel_or_back" and result.accepted:
                    new_state = result.new_game_state
                    if new_state and new_state != game_state:
                        game_state = new_state
                        # Recompute allowed tools for the new state
                        # Next loop iteration will use updated tool_choice

            elif output_item.type == "message":
                # v3.3: Do NOT display raw model "thinking" to stream viewers.
                # LLM extended thinking faithfulness is not guaranteed (Anthropic).
                # Only public_reason (from terminal actions) is shown on overlay.
                overlay.update_status("thinking")  # shows spinner, not content

    # Max calls exceeded — state-aware fallback
    return await state_fallback(turn_notify, game_state, overlay)

async def state_fallback(turn_notify: TurnNotification, game_state: str, overlay) -> Action:
    """State-aware fallback when LLM exceeds max tool calls.

    Every dispatch_tool() call checks result.accepted. For non-modal states,
    exhausted fallback paths return Action.WAIT as a deterministic safe no-op
    that advances the turn without changing game state. Modal fallback failures
    return Action.WAIT_FOR_SUPERVISOR instead, because waiting while a modal
    is open can preserve a deadlock.

    Args:
        turn_notify: Current turn's notification (contains modal, auto_act_active, etc.)
        game_state: "combat" | "navigation" | "modal" | "idle"
        overlay: StreamOverlay for status updates
    """
    if game_state == "combat":
        candidates = await dispatch_tool("request_candidates", {"situation": "combat"})
        # Try best candidate first
        best = max(candidates.internal_candidates, key=lambda c: c.score)
        result = await dispatch_tool("execute", {
            "candidate_id": best.id,
            "candidate_set_id": candidates.candidate_set_id,
            "snapshot_hash": candidates.snapshot_hash,
            "public_reason": f"[AUTO] Timeout, picking best: {best.desc}"
        })
        if result.accepted:
            return result.action
        # Second try: safest candidate (lowest risk_score)
        safest = min(candidates.internal_candidates, key=lambda c: c.risk_score)
        if safest.id != best.id:
            result2 = await dispatch_tool("execute", {
                "candidate_id": safest.id,
                "candidate_set_id": candidates.candidate_set_id,
                "snapshot_hash": candidates.snapshot_hash,
                "public_reason": "[AUTO] Fallback to safest option"
            })
            if result2.accepted:
                return result2.action
        # Third try: wait (CandidateGenerator invariant: wait is always present)
        wait_candidates = [c for c in candidates.internal_candidates if c.verb == "wait"]
        if wait_candidates:
            result3 = await dispatch_tool("execute", {
                "candidate_id": wait_candidates[0].id,
                "candidate_set_id": candidates.candidate_set_id,
                "snapshot_hash": candidates.snapshot_hash,
                "public_reason": "[AUTO] All options blocked, waiting"
            })
            if result3.accepted:
                return result3.action
        # Final resort: re-request candidates with fresh snapshot (state may have changed)
        overlay.update_status("[AUTO] Re-requesting candidates")
        fresh = await dispatch_tool("request_candidates", {"situation": "combat"})
        safest_fresh = min(fresh.internal_candidates, key=lambda c: c.risk_score)
        result4 = await dispatch_tool("execute", {
            "candidate_id": safest_fresh.id,
            "candidate_set_id": fresh.candidate_set_id,
            "snapshot_hash": fresh.snapshot_hash,
            "public_reason": "[AUTO] Fresh candidates, safest option"
        })
        if result4.accepted:
            return result4.action
        # Absolute last resort: deterministic wait (no game state change)
        overlay.update_status("[AUTO] All fallbacks failed, waiting")
        return Action.WAIT
    elif game_state == "modal":
        modal = turn_notify.modal
        # v5.3: Level-up is a special case — do NOT auto-select.
        # Level-up choices affect build identity. Supervisor takeover on timeout.
        if modal and modal.type == "level_up":
            overlay.update_status("[SUPERVISOR] Level-up requires human selection")
            return Action.WAIT_FOR_SUPERVISOR
        # v5.7: modal is None in modal state is a protocol invariant violation
        # (game_state="modal" but turn_notify.modal is missing — stale/desync
        # notification). Try cancel_or_back defensively, else escalate.
        if modal is None:
            overlay.update_status("[SUPERVISOR] Modal state desync")
            cancel_result = await dispatch_tool("cancel_or_back",
                {"reason": "[AUTO] Modal state desync, trying to exit"})
            if cancel_result.accepted:
                return cancel_result.action
            return Action.WAIT_FOR_SUPERVISOR
        # v5.6: Unsupported modals (merchant/quantity/string input/ModernPopup*
        # out-of-scope variants) have fallback_choice_id == null in MVP.
        # Try cancel_or_back first; escalate to supervisor if the modal cannot
        # be cancelled (e.g., ConversationUI with AllowEscape=false).
        if modal.fallback_choice_id is None:
            cancel_result = await dispatch_tool("cancel_or_back",
                {"reason": "[AUTO] Timeout, exiting unsupported modal"})
            if cancel_result.accepted:
                return cancel_result.action
            overlay.update_status("[SUPERVISOR] Unsupported modal cannot be cancelled")
            return Action.WAIT_FOR_SUPERVISOR
        # Dialogue / confirmation: choose the modal's guaranteed-safe fallback.
        result = await dispatch_tool("choose", {
            "choice_id": modal.fallback_choice_id,
            "reason": "[AUTO] Timeout, choosing safe fallback"
        })
        if result.accepted:
            return result.action
        # fallback_choice_id should always be safe; if it fails (e.g. STALE),
        # attempt cancel_or_back before giving up.
        cancel_fallback = await dispatch_tool("cancel_or_back",
            {"reason": "[AUTO] fallback_choice_id failed, exiting modal"})
        if cancel_fallback.accepted:
            return cancel_fallback.action
        # v5.7: modal-state WAIT is deadlock-prone — escalate to supervisor
        # instead of silently holding the turn.
        overlay.update_status("[SUPERVISOR] Modal fallback failed")
        return Action.WAIT_FOR_SUPERVISOR
    elif game_state == "navigation" and turn_notify.auto_act_active:
        # AutoAct is already running — do nothing, wait for next turn_start
        # (interrupt or arrival). This is a no-op that advances the turn.
        return Action.WAIT
    else:
        # Idle or Navigation without active AutoAct — explore nearest unexplored
        result = await dispatch_tool("navigate_to", {
            "target": "nearest_unexplored", "reason": "[AUTO] Timeout, exploring"
        })
        if result.accepted:
            return result.action
        # If navigate_to fails (unlikely), just wait
        return Action.WAIT

# Action enum for fallback returns:
#   Action.WAIT — deterministic no-op for non-modal fallback only.
#     C# interprets this as CommandEvent.Send("CmdWait"). Always safe, always valid.
#     Used when all other non-modal fallback paths are exhausted.
#     MUST NOT be returned from the modal branch — modal fallback failures use
#     Action.WAIT_FOR_SUPERVISOR to avoid deadlock retention.
#
#   Action.WAIT_FOR_SUPERVISOR (v5.4) — pause game and request human intervention.
#     C# interprets this as:
#       1. The.Core.Game.ActionManager.PauseSegment = true  (pause the game loop)
#       2. overlay.update_status("[SUPERVISOR] {reason}")
#       3. Send supervisor_request message to Python Brain:
#          {"type": "supervisor_request",
#           "reason": "level_up" | "unsupported_modal_uncancellable"
#                   | "modal_fallback_failed" | "modal_desync",
#           "tid": N,
#           "message_id": "...", "session_epoch": N,
#           "modal": {<current modal state>} | null,   # null allowed iff reason == "modal_desync"
#           "diagnostic": "..."}                       # required when reason == "modal_desync"
#       4. Python Brain forwards to supervisor UI (web dashboard or Twitch chat command)
#       5. Supervisor responds with:
#          - "resume" → unpause, let LLM retry with supervisor's guidance injected
#          - "select:<choice_id>" → supervisor directly selects the choice
#          - "abort" → force safe fallback (Action.WAIT for combat, cancel for modal)
#       6. On supervisor timeout (5 minutes), apply state-aware timeout policy:
#            non-modal                                                → Action.WAIT
#            modal, cancellable                                       → cancel_or_back
#            modal, level_up / uncancellable / fallback_failed /
#              modal_desync (anything WAIT_FOR_SUPERVISOR originally
#              escalated for)                                         → remain paused
#                                                                        and renew
#                                                                        supervisor_request
#          Never return Action.WAIT while game_state == "modal". The supervisor
#          timeout path MUST NOT reintroduce the modal deadlock that v5.7 removed.
#     Used for: level-up selections, build-altering mutations, faction-critical dialogues.
#     Wire message: added to §8 protocol and Appendix D.
#
#   Minimum supervisor primitive (required in Phase 2a):
#     pause + notify + resume/abort. Full supervisor UI (dashboard, chat) in Phase 2b-O.

# CandidateGenerator invariant (v4.0d):
#   request_candidates("combat") ALWAYS includes a "wait" candidate (verb="wait").
#   This is enforced by CandidateGenerator.cs — wait is the universal safe fallback.

# v4.0: AutoAct idle timeout
# After navigate_to is accepted and AutoAct runs internally in C#, Python Brain
# waits for the next turn_start message (interrupt or arrival). If no turn_start
# arrives within AUTOACT_HARD_TIMEOUT_S (15s), Python sends a heartbeat ping.
# If still no response after 10s, assume C# is hung and trigger reconnect protocol.
# This prevents indefinite hangs during long AutoAct paths or C# freezes.
```

**v3.3: Loop breaker** (from Pro review #3, inspired by Gemini Plays Pokemon TEA delusion):
Turn-level detection of repeated failed plans. If the LLM attempts the same action fingerprint (`verb + normalized_target + game_state`)
3 times in 5 turns and all were BLOCKED or had negative net_value,
inject a system message: `"You have attempted {action} {N} times recently without success.
Consider a different approach."` This prevents fixation loops where the LLM retries
a failing strategy indefinitely.

**v3.1/v3.2-lite changes from Pro review:**
1. `parallel_tool_calls=False` explicit (prevents mixed parallel calls)
2. `previous_response_id` for server-side continuation (preserves reasoning state)
3. `call_id` matching for `function_call_output` (official Responses API flow)
4. `tool_choice` restriction after `FORCE_ACTION_AFTER` calls — state-aware (API-level force, not system nudge)
5. All terminal actions (`execute`, `navigate_to`, `choose`) checked uniformly via `TERMINAL_ACTIONS` set
6. State-aware fallback: combat → best candidate; modal → `state_fallback()` modal branch
   (`fallback_choice_id` for dialogue/confirmation, `cancel_or_back` for unsupported,
   `WAIT_FOR_SUPERVISOR` for level_up / uncancellable / fallback failure);
   navigation/idle → explore
7. Safe fallback uses `risk_score` (not `min(score)`) to pick the safest option when best is BLOCKED/STALE
8. `result.to_llm_view()` strips scores — LLM never sees internal scoring

### Model Selection

| Situation | Model | Reasoning | Latency target |
|-----------|-------|-----------|---------------|
| Normal gameplay | gpt-5.4 | tool_choice="auto", effort=none | <5s per turn |
| Safe exploration (auto-explore active) | None (C# heuristic) | No LLM needed | 0ms |
| Post-death reflection | gpt-5.4 | effort=medium, offline | <30s |
| Note compaction (background) | gpt-5.3-codex-spark | Cheap summarization | <5s |

**v4.0: Latency budget analysis** (for p95 <5s target):
```
Budget per turn (p95):
  LLM calls: 3 × 1.2s (streaming TTFT + tool_call parse) = 3.6s
  C# tool execution: 3 × 50ms                              = 0.15s
  WebSocket overhead: 3 × 15ms                              = 0.05s
  Python processing: 3 × 30ms                               = 0.09s
  Total: ~3.9s (within 5s budget)

Implication: p95 requires median tool_calls_per_turn ≤ 3.
FORCE_ACTION_AFTER = 6 allows up to 8 calls, but the p95 target
constrains the common case. If p95 exceeds 5s in practice, reduce
FORCE_ACTION_AFTER to 4 (max 6 calls) as first mitigation.
```

---

## 7. Streaming Overlay Design

### Screen Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ┌─────────────────────────┐  ┌────────────────────────────┐ │
│  │                         │  │  🎯 Objective:             │ │
│  │                         │  │  Explore Joppa outskirts   │ │
│  │     Caves of Qud        │  │                            │ │
│  │     Game Window          │  │  ⚠️ Threats:              │ │
│  │                         │  │  snapjaw hunter (ranged)   │ │
│  │                         │  │                            │ │
│  │                         │  │  🔧 Tools called:          │ │
│  │                         │  │  inspect_surroundings ✓    │ │
│  │                         │  │  assess_threat("e2") ✓     │ │
│  │                         │  │  request_candidates ✓      │ │
│  │                         │  │                            │ │
│  │                         │  │  ✅ Decision:              │ │
│  │                         │  │  Retreat NW to cover       │ │
│  │                         │  │  "Ranged enemy, need LOS   │ │
│  │                         │  │   break before engaging"   │ │
│  │                         │  │                            │ │
│  └─────────────────────────┘  │  📊 Last outcome:          │ │
│                               │  net_value: +2.5 (good)    │ │
│  ┌─────────────────────────┐  │                            │ │
│  │ HP: 18/24  Lv: 3       │  │  📝 Notes:                 │ │
│  │ Build: Pyrokinetic      │  │  "Snapjaw hunters have     │ │
│  │ Run: #7  Deaths: 6     │  │   ranged attacks. Always    │ │
│  │ Turns: 142             │  │   find cover first."       │ │
│  └─────────────────────────┘  └────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Overlay Data Source

StreamOverlay.cs generates a JSON blob every turn.

**v3.1: Overlay redesigned per Pro review** — deterministic display, not dependent
on LLM "thinking out loud". Added `mode`, `top_candidates`, `decision_latency_ms`,
`interrupt_reason`, `safety_warning`.

```json
{
  "mode": "llm",
  "objective": "Explore Joppa outskirts",
  "threats": ["snapjaw hunter (ranged, HIGH)"],
  "top_candidates": [
    {"id": "c4", "desc": "Heal with salve, HP→22", "score": 95.0, "tag": "util"},
    {"id": "c2", "desc": "Retreat NW to cover", "score": 85.0, "tag": "def"},
    {"id": "c5", "desc": "Retreat W to choke", "score": 78.0, "tag": "def"}
  ],
  "decision": {"id": "c2", "desc": "Retreat NW to cover"},
  "public_reason": "Ranged enemy, need LOS break before engaging",
  "decision_latency_ms": 2340,
  "last_outcome": {"net_value": 2.5, "label": "good", "tags": ["broke_los", "maintained_cover"]},
  "safety_warning": null,
  "interrupt_reason": null,
  "navigate_destination": null,
  "choose_context": null,
  "active_tool_call": null,
  "thinking_status": "idle",
  "notes_excerpt": "Snapjaw hunters have ranged attacks. Always find cover first.",
  "hp": [18, 24],
  "level": 3,
  "build": "MutatedHuman:Pyrokinetic",
  "run_number": 7,
  "death_count": 6,
  "turn": 142,
  "snapshot_hash": "a3f2c1"
}
```

**`mode`** values (v5.4 unified):
- `"llm"` — LLM is actively deciding (tool calls in progress)
- `"autoact"` — C# AutoAct is navigating (shows destination + steps)
- `"fallback"` — LLM timed out, C# auto-selected action
- `"supervisor"` — Human intervention requested (game paused)
**`top_candidates`**: Top 3 by score from the last `request_candidates` call.
**`interrupt_reason`**: Set when AutoAct is interrupted (e.g., `"hostile_perceived"`, `"took_damage"`).
**`navigate_destination`** (v3.2): Shows current navigate_to destination while AutoAct is active
  (e.g., `"stairs_down at [8, 0]"`). Null when not navigating.
  **v3.4: Navigation canonical source**: `navigate_destination` + `interrupt_reason` in
  overlay/turn_start are the canonical sources for navigation state. `execution_status`
  in the terminal action result only indicates command acceptance, NOT ongoing progress.
**`choose_context`** (v3.2): Shows dialogue text and available options when a modal is active
  (e.g., `{"modal": "dialogue", "npc": "Mehmet", "options": ["Ask about water ritual", "Leave"]}`).
**`active_tool_call`** (v3.2): Shows the tool currently being called for real-time "thinking" display
  (e.g., `{"tool": "assess_threat", "args": {"target": "e1"}}`). Null between tool calls.
**`thinking_status`** (v3.3): `"idle"` | `"thinking"` | `"acting"`. Shown as a spinner/indicator
  on the overlay. Raw model "thinking" text is NOT displayed — only `public_reason` from
  terminal actions is viewer-facing (Pro review #3: faithfulness of extended thinking not guaranteed).
```

**v5.3: Bounded autonomy visibility** (from holistic review):
The honest product truth is "LLM captain + C# autopilot." This should be embraced, not hidden.
The overlay explicitly shows the current decision authority:

| `mode` value | Meaning | Overlay indicator |
|---|---|---|
| `"llm"` | LLM is actively deciding | "Thinking..." with tool call list |
| `"autoact"` | C# AutoAct is navigating | "Navigating to {destination}..." with step counter |
| `"fallback"` | LLM timed out, C# auto-selected | "[AUTO] {reason}" in yellow |
| `"supervisor"` | Human intervention requested | "[SUPERVISOR] {reason}" in red |

The `autoact` mode should feel like "the AI decided where to go, and is now walking there"
— not like the AI is absent. The overlay shows the LLM's stated reason for the navigation
and updates steps_remaining to maintain viewer engagement during AutoAct sequences.

Consumed by a lightweight web page (localhost:8080) displayed as OBS browser source.

---

## 8. Communication Protocol

### WebSocket Messages (C# ↔ Python)

**C# → Python: Session Start** (v4.0: new)
```json
{"type": "session_start",
 "session_epoch": 3,
 "protocol_version": "4.0",
 "game_version": "2.0.207.x",
 "build_id": "MutatedHuman:Pyrokinetic",
 "world_seed": "ABCDEF123456",
 "game_mode": "roleplay",
 "message_id": "msg_sess_start_003"}
```

**Python → C#: Session Start Ack** (v4.0: new)
```json
{"type": "session_start_ack",
 "session_epoch": 3,
 "protocol_version": "4.0",
 "brain_version": "0.1.0",
 "message_id": "msg_sess_start_ack_003"}
```

Protocol version mismatch: if major versions differ, Python logs a warning
and refuses to start. Minor version differences are tolerated with a log warning.

**Python → C#: Session End** (v4.0: new)
```json
{"type": "session_end",
 "session_epoch": 3,
 "reason": "death",
 "message_id": "msg_sess_end_003",
 "final_stats": {"survival_turns": 142, "death_count": 7}}
```

**v4.0c: Wire envelope normalization**:
**ALL** tool calls use the same `tool_call` / `tool_result` wire envelope over WebSocket.
This includes observation tools (`inspect_surroundings`, `check_status`, `check_inventory`),
analysis tools (`assess_threat`), knowledge tools (`write_note`, `read_notes`), and
action tools (`execute`, `navigate_to`, `choose`, `cancel_or_back`).

**v4.0e: Tool dispatch ownership**: All tools are dispatched from Python Brain to C# MOD
via the unified WebSocket wire. `write_note` and `read_notes` are handled by Python Brain's
`notes_manager.py` but still travel through the wire for idempotency (`message_id` dedup)
and telemetry logging. C# acts as a transparent relay for knowledge tools, forwarding
args to Python's `notes_manager` endpoint. This ensures a single deduplication path.
```
Python -> C#: {"type": "tool_call", "call_id": "<call_id>", "tool": "<name>", "args": {...},
              "message_id": "...", "session_epoch": N}
C# -> Python: {"type": "tool_result", "call_id": "<call_id>", "tool": "<name>",
              "result": {"status": "ok", "output": {...},
                         "error_code": null, "error_message": null},
              "message_id": "...", "in_reply_to": "...", "session_epoch": N}
```
`call_id` is the required per-tool-call invocation identity for `tool_call` and
`tool_result`; `message_id` / `in_reply_to` remain transport correlation and
deduplication fields. `tid` is turn-level context and is not part of
`tool_call` / `tool_result` envelope identity.
Terminal actions additionally include `action_nonce` and `state_version` in the **envelope**
(not inside `args`), and `result.output` includes the unified terminal action contract (`accepted`,
`turn_complete`, `action_kind`, `execution_status`, `acceptance_status`, `safety_decision`).
There is NO separate `execute` / `exec_result` message type at the wire level.

`supervisor_request` and `supervisor_response` are **non-tool messages** — they do not use
the `tool_call`/`tool_result` envelope. They are standalone message types with their own
`message_id` and `session_epoch`, used only for human-in-the-loop escalation.
The `exec_result` examples in §8 show the **content of `result.output`** within the `tool_result` envelope.

**C# → Python: Turn Start** (v3.2: removed `active_plan`, kept `interrupt_reason`; v3.2-lite: added `game_state`)
```json
{"type": "turn_start", "tid": 142, "rid": "run_007",
 "snapshot_hash": "a3f2c1", "state_version": 284,
 "message_id": "msg_142_ts", "session_epoch": 3,
 "game_state": "combat",
 "hostile_visible": true,
 "visible_hostile_count": 2,
 "hostile_perceived": true,
 "modal_active": false,
 "modal": null,
 "auto_act_active": false,
 "interrupt_reason": null,
 "prev_outcome": {"hp_delta": 0, "risk_delta": -15, "net_value": 2.5,
                   "tags": ["broke_los", "maintained_cover"]}}
```

**Game state determination** (C# computes, canonical):
- `modal_active == true` → **Modal**
- `hostile_visible == true` → **Combat**
- `hostile_perceived == true && !hostile_visible` → **Combat** (v5.3: non-visual perception
  e.g., auditory/psychic/robotic — ArePerceptibleHostilesNearby() includes ExtraHostilePerceptionEvent.
  Without this, interrupt_reason=hostile_perceived + game_state=Idle causes tool filtering mismatch.)
- `auto_act_active == true` → **Navigation**
- else → **Idle**

Priority: Modal > Combat > Navigation > Idle.
`game_state` is the pre-computed result. `select_allowed_tools()` in Python uses this directly.

**v4.0c: `modal` field in turn_start** (authority for modal state):
When `modal_active == true`, `turn_start` includes a `modal` object identical to the
`inspect_surroundings` modal schema (type, title, prompt, choices, fallback_choice_id).
This is the **canonical source** for `state_fallback()` — the LLM may also see it via
`inspect_surroundings`, but the fallback path uses `turn_notify.modal` directly.
When `modal_active == false`, `modal` is `null`.

**Python -> C#: Tool Call Request**
```json
{"type": "tool_call", "call_id": "call_142_inspect_01", "tool": "inspect_surroundings", "args": {},
 "message_id": "msg_142_tc_01", "session_epoch": 3}
```

**C# -> Python: Tool Call Response**
```json
{"type": "tool_result", "call_id": "call_142_inspect_01", "tool": "inspect_surroundings",
 "result": {
   "status": "ok",
   "output": {"map": {...}, "entities": [...], ...},
   "error_code": null,
   "error_message": null
 },
 "message_id": "msg_142_tr_01", "in_reply_to": "msg_142_tc_01", "session_epoch": 3}
```

**Python -> C#: Terminal Action (execute example)** - uses standard `tool_call` envelope
```json
{"type": "tool_call", "call_id": "call_142_exec_01", "tool": "execute",
 "args": {
   "candidate_id": "c2",
   "candidate_set_id": "cs_142_01",
   "snapshot_hash": "a3f2c1",
   "public_reason": "Ranged enemy, need LOS break"
 },
 "action_nonce": "f7a1b2c3", "state_version": 284,
 "message_id": "msg_142_exec_01", "session_epoch": 3}
```

**C# -> Python: Terminal Action Result** - uses standard `tool_result` envelope
```json
{"type": "tool_result", "call_id": "call_142_exec_01", "tool": "execute",
 "result": {
   "status": "ok",
   "output": {
     "accepted": true, "turn_complete": true,
     "action_kind": "execute",
     "execution_status": "accepted",
     "acceptance_status": "accepted",
     "safety_decision": "pass",
     "action_summary": "Retreat NW to cover",
     "outcome": {"hp_delta": 0, "net_value": 2.5, "tags": ["broke_los", "maintained_cover"]},
     "safety_warning": null
   },
   "error_code": null,
   "error_message": null
 },
 "action_nonce": "f7a1b2c3",
 "message_id": "msg_142_er_01", "in_reply_to": "msg_142_exec_01", "session_epoch": 3}
```

Note: `action_nonce` and `state_version` are added to the `tool_call` envelope (not inside `args`)
for terminal actions only. Non-terminal tool calls omit these fields.

### AutoAct Integration (v3.2: navigate_to replaces PlanState/Batch)

v3.2 removes PlanState, horizon, and batch_ok from the wire protocol entirely.
Movement delegation is handled by `navigate_to`, which creates an AutoAct session
internally in C#. There is no LLM-visible PlanState.

**navigate_to → AutoAct flow:**
1. LLM calls `navigate_to(target, reason)`
2. C# SafetyGate pre-filter checks zone danger → WARN if `zone_tier > player_level / 3`
3. C# creates AutoAct session with guard conditions:
   - `hostile_perceived` → interrupt (ShouldHostilesInterrupt via ArePerceptibleHostilesNearby,
     includes visual + auditory + psychic + robotic senses. **Note**: targeted navigation
     M/P/U/! SKIPS this pre-move check — ActionManager.cs:834)
   - `took_damage` → interrupt (Physics.cs:3820, fires when HP decreases)
   - `caught_fire` → interrupt (Physics.cs:4142, "you caught fire")
   - `hazard_in_path` → interrupt (InterruptAutowalkEvent on path objects,
     dangerous liquid via GameObject.cs:15637, SlowDangerousMovement.cs:168)
   - `obstacle_in_way` → interrupt (hostile/NPC blocking path, GameObject.cs:15547)
   - `zone_boundary` → interrupt (ActionManager.cs:855-870)
   - `keyboard_input` → interrupt (ActionManager.cs:850, player pressed a key)
   - `arrived` → interrupt (ActionManager.cs:949-957, destination reached)
4. AutoAct runs pathfinder internally (no LLM involvement per step)
5. On guard trigger: AutoAct cancelled, new `turn_start` sent with `interrupt_reason`
6. On arrival: new `turn_start` sent with `interrupt_reason: "arrived"`

**Wire protocol for navigate_to interruption:**
```json
{"type": "turn_start", "tid": 147, "rid": "run_007",
 "snapshot_hash": "b4e1d2",
 "game_state": "combat",
 "hostile_visible": true,
 "visible_hostile_count": 1,
 "modal_active": false,
 "auto_act_active": false,
 "interrupt_reason": "hostile_perceived",
 "prev_outcome": {"hp_delta": 0, "net_value": 0, "tags": []}}
```

`interrupt_reason` in `turn_start` is a **MOD-synthesized enum** computed from **multiple signals**,
not just `AutomoveInterruptBecause`. The native interrupt reason string is often EMPTY
(hostile/damage/keyboard/zone_boundary/arrived all call `Interrupt()` without a reason string —
AutoAct.cs:130-135, Physics.cs:3820-3822, ActionManager.cs:850-857,949-957).

**v5.1: Multi-signal interrupt classification**:
The C# MOD synthesizes `interrupt_reason` by checking multiple state deltas at interrupt time:
```
interrupt_reason = classify_interrupt(
    autoact_was_active: bool,          // AutoAct.Setting was non-empty before, empty now
    because_text: string,              // AutomoveInterruptBecause (may be empty)
    hp_delta: int,                     // HP change since last step
    fire_gained: bool,                 // player gained Burning effect
    hostile_now_visible: bool,         // ArePerceptibleHostilesNearby() changed false→true
    position_changed: bool,            // player moved
    target_satisfied: bool,            // arrival condition met (varies by mode:
                                       //   M = at object, U/P = within radius, ! = used target)
    keyboard_pressed: bool,            // Keyboard.vkCode was set during AutoAct
    zone_changed: bool,               // current zone != previous zone
    modal_opened: bool,               // GameManager.CurrentGameView changed to modal
    path_failed: bool,                // FindPath returned null/empty
)
```
Priority: modal_opened > hostile_visible > took_damage > caught_fire > zone_boundary >
          obstacle > keyboard > arrived > path_failed > unknown

**v5.2: AutoActSession** — auxiliary state held by C# MOD during AutoAct execution:
```python
@dataclass
class AutoActSession:
    mode: str                    # "M" | "P" | "U" | "!" | "?" | "a" | "o"
    target_kind: str             # "object" | "coords" | "explore" | "attack" | "ongoing"
    target_id: str | None        # object ID or "x,y" coords
    radius: int                  # for P mode
    start_tid: int               # turn when AutoAct started
    start_pos: tuple[int, int]   # player position at start
    last_hp: int                 # HP at last step (for damage detection)
    last_burning: bool           # fire status at last step
    last_zone: str               # zone ID at last step
    last_pos: tuple[int, int]    # position at last step
    last_hostile_visible: bool   # hostile visibility at last step
    last_modal_active: bool      # modal state at last step
    keyboard_seen: bool          # keyboard input detected during AutoAct
    because_text: str            # AutomoveInterruptBecause (supplementary, often empty)
```
Updated each step by the C# MOD before checking for interrupt.
`classify_interrupt()` reads this session + current state to produce the enum.
`because_text` is a **supplementary signal** — may be empty for hostile/damage/keyboard/arrived.

Additional stop conditions not in the original 8 (from Pro review):
- `target_invalid`: target object left zone (ActionManager.cs:927-933)
- `path_not_found`: FindPath failed (ActionManager.cs:998-1009)
- `door_failure`: AutoAct couldn't open door (AutoAct.cs:507-524)
- `dig_stalled`: digging blocked (AutoAct.cs:530-560)

`interrupt_reason` tells the LLM *why* navigation was interrupted, enabling it to
respond appropriately (e.g., switch to combat mode on `"hostile_perceived"`).
Telemetry logs navigation duration, steps completed, and interrupt reason.

**v4.0: Navigation idle timeout**: If Python Brain receives no `turn_start` message
within `AUTOACT_HARD_TIMEOUT_S` (15 seconds) after a `navigate_to` was accepted,
it sends a heartbeat:
`{"type": "heartbeat", "session_epoch": 3, "message_id": "msg_hb_001"}`.
C# responds with:
`{"type": "heartbeat_ack", "session_epoch": 3, "message_id": "msg_hb_ack_001", "in_reply_to": "msg_hb_001", "auto_act_active": true, "state_version": 285, "tid": 147}`.
If no heartbeat_ack within 10 seconds, Python triggers the reconnect protocol.
This prevents indefinite hangs when AutoAct encounters an unexpected C# state.

**v5.1: AutoAct step callback timing**:
During AutoAct, `CallBeginPlayerTurnCallbacks()` is called EVERY step (ActionManager.cs:848),
BEFORE interrupt/arrival checks (L850-1014). This means the callback fires even on steps
where AutoAct will be interrupted. The C# MOD should NOT send `turn_start` on every callback
during AutoAct — instead, it should only notify Python Brain when:
(a) AutoAct completes (arrived), or
(b) AutoAct is interrupted (interrupt_reason set), or
(c) Heartbeat timeout expires (AUTOACT_HARD_TIMEOUT_S).
This preserves the "bounded autonomy" design: AutoAct steps are C#-internal.

### Protocol Idempotency (v3.3: from Pro review #3)

The wire protocol must prevent duplicate execution, out-of-order messages,
and replay after partial action. `snapshot_hash` alone only prevents stale
candidate execution — it does not cover these failure modes.

**Added fields** (all messages):
- `message_id`: UUID, unique per message. Used for deduplication.
- `session_epoch`: Monotonic counter, incremented on WebSocket reconnect.
  C# rejects messages from a stale epoch.

**Added fields** (terminal action messages: execute, navigate_to, choose):
- `action_nonce`: UUID, generated by Python Brain per terminal action attempt.
  C# tracks consumed nonces and rejects duplicates.
  Combined with `snapshot_hash`, this prevents both stale AND duplicate execution.
- `state_version`: Monotonic counter incremented on every **observable game state change**.
  C# rejects terminal actions where `state_version` doesn't match current.

  **v4.0: Increment triggers** (exhaustive list):
  - Entity enters or leaves player's visible range
  - Player or any visible entity takes damage
  - Player's HP or status effects change
  - Player's **visible** ability cooldowns change (i.e., a cooldown reaches 0 / becomes
    available, or a new cooldown starts). Per-turn countdown ticks that don't cross the
    0 boundary are timer ticks, NOT state changes — they do not increment state_version.
  - An item is picked up, dropped, consumed, or equipped
  - A modal opens or closes
  - AutoAct starts, stops, or is interrupted
  - Zone transition occurs

  NOT incremented for: turn counter advancing alone, NPC movement that doesn't
  change visible state, background timers ticking down.

**Reconnect protocol**:
1. Python Brain detects WebSocket disconnect
2. On reconnect, Python sends `{"type": "reconnect", "session_epoch": 4, "message_id": "msg_reconn_004"}`
3. C# responds with `reconnect_ack` (full game state snapshot, see below)
4. **v4.0**: Python Brain invalidates `previous_response_id` (set to `None`).
   The Responses API server-side context from the pre-disconnect session is
   no longer usable. Python rebuilds full LLM context from the reconnect snapshot
   + active memory notes + current turn's tool call history (if any).
5. Python resumes tool loop with a fresh Responses API call (`input=` rebuilt context)
6. Any in-flight terminal actions from epoch N are rejected by C#
7. Non-terminal tool calls from epoch N that are still in-flight are ignored
   (C# discards tool_call messages with stale session_epoch)

**Duplicate rejection rule** (C# side):
```
if msg.session_epoch < current_epoch → REJECT with acceptance_status: "stale_epoch"
    Cross-epoch duplicates are ALWAYS rejected as stale_epoch — nonce cache is NOT consulted.
    After reconnect, Python reconciles via reconnect_ack.last_applied_action_nonce instead.
if msg.session_epoch == current_epoch AND msg.action_nonce in consumed_nonces
    → return CACHED PRIOR RESULT (same-epoch duplicate recovery)
if msg.state_version != current_state_version → REJECT with acceptance_status: "stale"
else → ACCEPT and add action_nonce to consumed_nonces, cache result keyed by nonce
```

**v3.4: Remaining idempotency gaps** (from Pro review #4):

1. **All wire messages** must include `message_id`. Update `tool_call` and `tool_result`
   messages to include `message_id` and add `in_reply_to` (echoes the `message_id` of
   the request being answered). This enables correlation when the same tool is called
   multiple times per turn.

2. ~~**Duplicate terminal actions return cached prior result** instead of bare REJECT.~~ **RESOLVED in v4.0d**: The duplicate rejection rule above now returns the cached prior result
   directly. Python can distinguish "action was committed" (cached result with `accepted: true`)
   from "action was rejected" (stale/stale_epoch). Cache is keyed by `action_nonce` and retained
   for `max(current_session_epoch - 1, 0)` epochs (i.e., kept through at most one reconnect cycle).

3. **Reconnect snapshot shape** must be defined:
   ```json
   {"type": "reconnect_ack", "session_epoch": 4,
    "message_id": "msg_reconn_ack_004", "in_reply_to": "msg_reconn_004",
    "state_version": 285, "snapshot_hash": "b4e1d2",
    "game_state": "combat", "snapshot": {<full game state>},
    "last_applied_action_nonce": "f7a1b2c3",
    "last_applied_message_id": "msg_142_exec_01"}
   ```

4. **`write_note` idempotency**: `write_note` has side effects but is not a terminal
   action. Deduplicate via `message_id` on the `tool_call` message, or use
   `(rid, tid, key, normalized_content_hash)` as a natural upsert key.

   **v4.0d: write_note idempotency resolved**: Deduplicate via `message_id` on the `tool_call`
   envelope. C# tracks seen `message_id` values per session_epoch and returns the cached
   `tool_result` for duplicates. Since `write_note` uses the standard `tool_call` envelope,
   this follows the same deduplication path as all other tool calls.

5. **CONFIRM does NOT consume `action_nonce`**: The first CONFIRM response is
   informational only. The retry with `confirmed: true` generates a fresh nonce.

6. **`action_nonce` echo**: `exec_result` and reconnect responses must echo
   `action_nonce` so Python can reconcile which action was applied.

---

## 9. Phase Plan

### Phase 0: Spike — "Can We See and Act?" (2-3 weeks)

**Goal**: Verify C# MOD loads, observes game state, issues commands. No LLM.

**Task ordering (v5.5: Codex finding)**: 0-A (skeleton) and 0-A2 (packaging) are
**sequential prerequisites** for everything else. 0-B/0-C can only run once 0-A2
confirms the MOD loads. Subsequent 0-B … 0-H may be parallelized freely.

Tasks:
- 0-A: MOD skeleton (`LLMOfQudSystem : IPlayerSystem`, registered via `The.Game.RequireSystem<T>()`).
  `RegisterPlayer()` explicitly calls `Registrar.Register(SingletonEvent<BeginTakeActionEvent>.ID)`
  and implements `HandleEvent(BeginTakeActionEvent)` (see §5, Codex Must-Fix #2).
  `RegisterOnBeginPlayerTurnCallback` for per-turn hook (XRLCore.cs:576), with a
  static "already registered" guard before re-register on mod reload (Should-Fix S1).
  Harmony reserved for: AutoAct.TryToMove AllowDigging coercion, Popup interception,
  ScreenBuffer post-render, edge cases only.
  **Important**: `BeginTakeActionEvent` is object-level, NOT game-level. IGameSystem alone
  cannot receive it — IPlayerSystem is required (verified: BeginTakeActionEvent.cs:37-52).
  **Acceptance (v5.8)**: reload the mod once during a single in-game session and
  verify exactly one begin-turn callback fires per player decision point. No
  duplicate registrations, no missed turn_start notifications.
- **0-A2: MOD packaging / source compilation / load verification (v5.5 Must-Fix
  #6, v5.6 rewrite after reading ModInfo/ModManager/ModManifest/ModFile).**
  **Verified flow (do not deviate):**
  - CoQ scans mod directories via `ModManager.RefreshModDirectory(path)`
    (`decompiled/XRL/ModManager.cs:475-497`). Each subdirectory becomes one
    `ModInfo`. Mods live under the user's CoQ Mods folder (location is platform-
    and install-specific — confirm on the user's machine at implementation time).
  - Each mod is a **directory of source files**, NOT a prebuilt DLL.
    `ModManager.BuildMods()` (`ModManager.cs:417-464`) iterates mods and calls
    `mod.TryBuildAssembly(compiler, pathList, out Assembly)` for every mod with
    `IsScripting == true`. `IsScripting` becomes true as soon as any `.cs` file
    is found during `InitializeFiles()` (`ModInfo.cs:478-481`).
  - `TryBuildAssembly()` (`ModInfo.cs:757-823`) collects **all `.cs` files** in
    the mod directory and feeds their paths to
    `RoslynCSharpCompiler.CompileFromFiles(array)`. The output is an in-memory
    `Assembly`. `.dll` files classified as `ModFileType.Assembly`
    (`ModFile.cs:42`) are not loaded by any code path visible in the decompiled
    source — **do not ship a prebuilt DLL**.
  - After successful compile, `ApplyHarmonyPatches()` (`ModInfo.cs:847-864`)
    runs `Harmony.PatchAll(Assembly)` if the assembly contains any type with
    `[HarmonyAttribute]` (i.e. `[HarmonyPatch]`). Use of `HarmonyLib` does not
    require a manual assembly reference — the Roslyn compiler auto-references
    all `AppDomain.CurrentDomain.GetAssemblies()` that pass `MainAssemblyPredicate`
    (`ModManager.cs:402-405`), which includes CoQ's bundled HarmonyLib.
  - Roslyn `DefineSymbols` pre-set by CoQ: `VERSION_<major>_<minor>`,
    `BUILD_<major>_<minor>_<build>` (`ModManager.cs:408-413`), and per-enabled-mod
    `MOD_<ID_UPPER>` (`ModManager.cs:458-460`). Useful for version-conditional code.

  **Deliverables for 0-A2:**
  - `Mods/LLMOfQud/manifest.json` using only `ModManifest` fields verified at
    `decompiled/XRL/ModManifest.cs`: `ID` (required; `[^\w ]` stripped per
    `ModInfo.cs:288`), `Title`, `Description`, `Version`, `Author`, `Tags`,
    `PreviewImage`, `Dependencies` (dict of `{other_mod_id: version_spec}`),
    `LoadBefore`, `LoadAfter`. No `entry assembly` field — it does not exist.
  - `Mods/LLMOfQud/*.cs` source files (recursive subdirectories allowed —
    `InitializeFiles()` recurses). No separate `.csproj` is required by CoQ.
    Authoring with a `.csproj` for IDE / type-check / CI is optional and kept
    out of the mod directory, because unknown files co-located with the mod
    may be scanned.
  - Minimal load probe: `LLMOfQudSystem` logs once on game-start via
    `Logger.buildLog.Info("[LLMOfQud] loaded v<semver> at " + DateTime.UtcNow)`
    from its static ctor or from the first `RegisterPlayer()` call.
  - Author the mod under `Assembly:` reference-equivalent code that expects
    CoQ-side HarmonyLib; **do not redistribute HarmonyLib**.

  **Exit criteria for 0-A2:**
  - CoQ's mod list shows `LLMOfQud` as active after launch.
  - `Logger.buildLog` records `Compiling 1 file...` or `Compiling <N> files...`
    (singular/plural per `ModInfo.cs:768-769`) followed by `Success :)` for the mod.
    Use a regex such as `^Compiling \d+ files?\.\.\.$` rather than a literal string
    match when automating the check.
  - Load probe line appears exactly once per game launch.
  - No `COMPILER ERRORS` for the mod.

  This task blocks 0-B/0-C — if the MOD doesn't compile and load, nothing
  downstream can be verified.
- 0-B: ScreenBuffer observation (ASCII map dump to log)
- 0-C: Internal API observation (HP, position, zone, entities)
- 0-D: RuntimeCapabilityProfile capture (mutations, abilities, cooldowns)
- 0-E: BirthBuildProfile capture (genotype, calling, attributes)
- 0-F: Movement/attack command issuance via CommandEvent.Send()
- 0-G: Simple heuristic bot (flee if hurt, attack if adjacent, explore otherwise)
- 0-H: TurnSnapshot DTO + snapshot_hash prototype (v4.0: from Pro first-week plan)
- 0-I: **Reduced (v5.5: Codex Should-Fix #4)** — snapshot fixture + one replay
  smoke test. The original "Golden trace ×10 + full C# replay test harness +
  crash dashboard" is too heavy for Phase 0; the harness and crash dashboard
  move to Phase 2b (2-M).

Exit criteria:
- Heuristic bot survives ≥50 turns on Warden (Roleplay mode, standard preset mutations)
  in 3/5 runs. Warden = Mutated Human, Warden calling (the game's default starting build).
- All logged data matches in-game display (spot-check 20 random turns)
- No game crashes in any of the 5 runs
- Observation accuracy ≥99% (spot-check logged HP/position/entities vs actual game state)
- Interrupt detection latency <1 game turn (enemy appears → interrupt fires within same turn)

### Phase 0b: Spike — "Can We Act on Abilities?" (1-2 weeks)

> **v3.2 note**: Ability activation and AutoAct interrupt are deceptively difficult.
> CoQ's ability system has many edge cases (cooldowns, resources, target selection,
> mutation-specific UI). Budget extra time here.

Tasks:
- Ability activation (active mutations/cybernetics)
- AutoAct + Interrupt
- Conversation detection + choice reading
- Build-specific ability registry (hand-curated for Warden/Pyrokinetic/Praetorian)
  (v3.2-lite: general auto-classification deferred to Phase 3)

Exit criteria:
- Heuristic bot with abilities survives ≥50 turns on Pyrokinetic
- AutoAct interrupt works on hostile detection

### Phase 1: Pipeline — "Can We Connect?" (2-3 weeks)

**Goal**: C# MOD ↔ WebSocket ↔ Python Brain pipeline.

Tasks:
- 1-A: WebSocket bridge (BrainClient.cs ↔ app.py)
- 1-B: Tool call message format (request/response)
- 1-C: Codex Auth (device_flow, token_store, broker)
- 1-D: SQLite telemetry tables
- 1-E: ToolRouter.cs (dispatch tool calls to handlers)
- 1-F: Error handling & retry infrastructure (v4.0: tool errors, API rate-limit/5xx, output truncation)
- 1-G: **Terminal-action idempotency (v5.5: Codex Must-Fix #5 — promoted from 2b
  to Phase 1 so Phase 2a Gate 1 operates on idempotent terminal actions).**
  Required before Phase 2a Gate 1:
  - `action_nonce` cache keyed by `(session_epoch, action_nonce)` →
    returns cached `tool_result` on duplicate tool_call with same nonce
  - `state_version` guard — reject terminal actions whose `state_version` is stale
    (`acceptance_status: "stale"`)
  - `session_epoch` guard — reject actions from a previous epoch
    (`acceptance_status: "stale_epoch"`)
  - `message_id` dedup scope: at minimum on terminal actions; full coverage in 2b
  - duplicate turn suppression, snapshot_hash check, reconnect on new
    session_epoch (carry-overs from v5.3)

  Non-terminal tool-call deduplication (inspect/check/assess/notes) and reconnect
  hardening remain in Phase 2b (see 2-L below).
Exit criteria:
- Full round-trip: C# → WebSocket → Python → tool call → C# → result → Python
- Latency <100ms for tool call round-trip (no LLM)

### Phase 2a: LLM Integration Core — "Can the LLM Play?" (4-5 weeks)

**Goal**: LLM plays CoQ via tool-calling loop. First playable demo.

**Task Dependency DAG** (v4.0c):
```
Phase 2a:
  2-A (tool schemas) ─────────┬──→ 2-C (tool loop) ──→ 2-G (feedback) ──→ Gate 1
  2-B (system prompt) ────────┘         │
  2-D (CandidateGenerator) ──→ 2-E-core (SafetyGate post) ──→ Gate 1
                                        │
  2-I (navigate_to) ──┬──→ 2-E-ext (SafetyGate pre) ──→ Gate 2
  2-J (choose) ────────┘         │
  2-K (cancel_or_back) ──────────┘──→ Gate 2
  2-F (knowledge base + goal ledger) ──→ Gate 1
  2-H (overlay + agency share) ──→ Gate 2 ──→ Gate 3

Phase 2b:
  2-L (full idempotency) ──→ Gate 5 (reconnect test)
  2-M (micro-eval fixtures) ──→ Gate 4 (20-run eval)
  2-N (20-run baseline) ──→ Gate 4
  2-O (supervisor controls: pause/kill/fallback) ──→ Gate 4

Phase 2b depends on Phase 2a Gate 3 completion.
Phase 1-G (terminal-action idempotency: action_nonce + state_version +
session_epoch + cached duplicate result) is a hard prerequisite for Phase 2a
Gate 1 — without it, duplicate terminal actions can double-execute on retry
or reconnect during LLM integration debugging.
```

Tasks:
- 2-A: Tool schemas (11 tools in Responses API format, including cancel_or_back)
- 2-B: System prompt (gameplay instructions + build block + notes injection).
  Includes: verify `instructions` sent on every Responses API continuation call
  (previous_response_id does NOT inherit instructions).
- 2-C: Tool-calling loop (tool_loop.py with timeout, max_calls, state-aware fallback)
- 2-D: CandidateGenerator as tool backend
- 2-E-core: SafetyGate post-validation on execute (BLOCK/CONFIRM/WARN/PASS)
  Note: Pre-filters on navigate_to and choose depend on 2-I/2-J.
- 2-F: Knowledge base (write_note/read_notes with validation + confidence-axis admission control
  for dangerous keys, 10-turn evidence window)
- 2-G: ActionOutcome + EncounterResult feedback (includes risk_delta computation)
- 2-H: Stream overlay (web page + OBS source)
- 2-I: navigate_to tool + AutoActHandler.cs (AutoAct integration + interrupt + idle timeout)
- 2-J: choose tool + ChoiceHandler.cs (modal choice dispatch)
- 2-E-ext: SafetyGate pre-filters on navigate_to (zone danger) and choose (CONFIRM on irreversible).
  Depends on 2-I and 2-J being complete.
- 2-K: cancel_or_back tool + modal deadlock prevention
- 2-K2: Minimum supervisor handoff (v5.4: prerequisite for level-up):
  pause, notify (supervisor_request message), resume/select/abort (supervisor_response).
  Required because first demo allows supervisor intervention for level-up.

**v5.3: "First Demo" definition** (MVP acceptance criteria):
- 30 minutes continuous play without modal deadlock or crash
- 1 build only (Warden, Roleplay mode)
- Supervisor may intervene for level-up selections
- Trade, quantity input, string input, complex inventory submenus are out of scope
- Targeted abilities limited to ≤3 hand-curated for Warden build
- `agency_share_llm > 50%` for First Demo (LLM is making most terminal-action
  decisions, not AutoAct/fallback). The §10 streaming target of `> 60%` applies
  to post-2b steady-state, not First Demo — see Codex advisor note that AutoAct
  long-distance navigation makes 60% unrealistic for Warden at Phase 2a Gate 3.

Exit criteria (staged):
- Gate 1: LLM survives ≥50 turns on Warden via tool-calling
- Gate 2: Overlay displays correctly, 0 modal deadlocks (requires cancel_or_back)
- Gate 3: stall-free for ≥30 minutes continuous play

### Phase 2b: Hardening — "Is It Robust?" (2-3 weeks)

**Goal**: Protocol robustness, idempotency, and evaluation readiness.

Tasks:
- 2-L: **Protocol idempotency hardening (v5.5)** — non-terminal tool_call
  deduplication (inspect/check/assess/read_notes/write_note), full `message_id`
  dedup, reconnect protocol with `previous_response_id` replay, and
  session_start/session_end handshake. Terminal-action idempotency is now
  delivered in Phase 1-G.
- 2-M: Micro-evaluation fixture suite (encounter, navigation interrupt, modal, SafetyGate boundary)
- 2-N: 20-run evaluation baseline: median survival >100 turns (Roleplay mode, Warden build),
  p95 latency <5s, fallback rate <15%
- 2-O: Minimum supervisor controls (v5.3: moved from Phase 4):
  pause, kill_switch, force_safe_fallback, provider_outage_fallback display.
  Required before any extended soak testing. Full supervisor UI (camera, chat
  integration) remains in Phase 4.

Exit criteria:
- Gate 4: 20-run evaluation meets targets (median survival >100 turns Roleplay,
  p95 latency <5s, fallback_rate <15%)
- Gate 5: Reconnect protocol tested — survives 3 simulated WebSocket disconnections
  during a single run without data loss

### Phase 3: Learning — "Can It Get Better?" (4-6 weeks)

**Goal**: Cross-run improvement via death analysis and notes.

**Task Dependency DAG** (v4.0c):
```
Phase 3:
  3-0 (N-run infrastructure) ──→ 3-E (cross-run seeding) ──→ Exit criteria
                                      │
  3-A (death taxonomy) ──→ 3-B (death recap) ──→ 3-C (CLIN abstractions)
  3-D (ExpeL importance) ──→ 3-E
  3-F (search_archive) ──→ 3-G (spatial_log)
  3-H (assess_escape) ──┐
  3-I (assess_ability) ──┘──→ independent, no downstream dependency
  3-J (weight calibration) ──→ requires 3-0 + 20 runs of data

Phase 3 depends on Phase 2b Gate 4 completion.
```

Tasks:
- 3-0: N-run evaluation infrastructure (v4.0: batch runner script, eval_score computation,
  before/after comparison report generator). Required for all Phase 3 exit criteria.
- 3-A: Death taxonomy (3-tier classification)
- 3-B: Auto-generated death recap → notes injection for next run
- 3-C: CLIN-style causal abstraction in learned_tactics notes
- 3-D: ExpeL-style importance management (success/fail counting)
- 3-E: Cross-run note seeding (≥2/5 runs with confirm > contradict carry forward)
- 3-F: search_archive tool implementation (SQLite FTS5 keyword search)
- 3-G: spatial_log auto-population (C# records zone visits, enemies, danger ratings)
- 3-H: assess_escape tool (standalone, split from request_candidates metadata)
- 3-I: assess_ability tool (standalone, split from request_candidates metadata)
- 3-J: Weight calibration for net_value formula (regression analysis using encounter_log
  as target variable, requires 20+ runs of data from Phase 2b)

Exit criteria:
- For at least 2 of the top-3 death causes (by frequency), `adaptation_rate` < 3
  (i.e., agent adapts within 3 deaths of the same root_cause_key). Measured over
  a 10-run moving window (single-run comparison too noisy due to CoQ run variance).
- `eval_score` shows statistically significant improvement (>1 std dev) comparing
  the first 10 runs vs the last 10 runs of Phase 3 development.
- Note accuracy ≥80% on manual spot-check (20 random notes vs actual game state).
- No evidence-counted note with contradict_count >= 3 persists across runs.

### Phase 4: Streaming Demo — "Can We Go Live?" (2-3 weeks)

**Goal**: Production-quality streaming setup.

Tasks:
- 4-A: OBS integration (game capture + overlay browser source)
- 4-B: Build selection for streaming (1-2 entertaining builds)
- 4-C: Roleplay mode for sustained play + Classic for special events
- 4-D: Chat integration (optional: Twitch chat → influence goals?)
- 4-G: Full supervisor UI (v5.3: basic controls moved to 2-O):
  safe_camera_state, chat integration, supervisor dashboard.
  Basic controls (pause, kill_switch, force_safe_fallback) already available from Phase 2b.
- 4-E: Stability testing (4-hour unattended run with supervisor controls active)
- 4-F: Death counter, run statistics overlay

Exit criteria (staged):
- Gate 1: 30 minutes unattended stable streaming (supervisor controls active)
- Gate 2: 2 hours unattended stable streaming
- Gate 3: 4+ hours unattended stable streaming
- Overlay is informative and entertaining
- No unrecoverable crashes in any Gate test
- 24-hour unattended run: Phase 5 prerequisite (not Phase 4 exit criteria)

### Phase 5+: Future Scope

- Merchant interaction, equipment management, quest tracking
- Social systems (faction, water ritual)
- Multiple concurrent builds on screen
- Community voting on build/goal selection
- **Trusted macros / named skills** (v5.3, inspired by Voyager skill library):
  Safe, named subroutines for recurring dangerous patterns. Unlike Voyager's generated code,
  these are hand-verified C# implementations that the LLM can invoke by name:
  - `retreat_to_stairs`: Navigate to nearest known stairs, flee if engaged
  - `kite_to_cover`: Lure ranged enemy around corner for melee engagement
  - `safe_loot_local`: Check for hostiles, loot adjacent corpses/items if safe
  - `door_fight_setup`: Position at door, wait for enemy to enter chokepoint
  - `escape_if_critical`: If HP<20% or burning, use best escape ability or flee
  These are Phase 5+ because they require stable Phase 3 encounter data to identify
  which patterns are worth codifying. They are NOT free-form code generation.

---

## 10. Telemetry (Streaming + Research KPIs)

### Streaming KPIs (Phase 2+)

| Metric | Target | Purpose |
|--------|--------|---------|
| decision_latency_ms | <5000 (p95) | Stream doesn't feel slow |
| stall_rate | <1% of turns | No frozen screen |
| fallback_rate | <15% | LLM is actually making decisions |
| modal_deadlock_rate | 0% | Never stuck on popup |
| tool_calls_per_turn | 2-4 (median), ≤3 for p95 <5s | v5.3: p95 budget requires median ≤3 calls. Combat turns (inspect+assess+request+execute=4) may exceed p95 target — acceptable if ≤15% of turns. |
| crash_rate | 0 per 8 hours | Stable enough for streaming |
| agency_share_llm | >60% | v5.3: Fraction of terminal actions originating from LLM (not fallback/AutoAct) |
| agency_share_autoact | <30% | v5.3: Fraction of turns spent in AutoAct bounded autonomy |
| agency_share_fallback | <10% | v5.3: Fraction of actions from state_fallback() |
| agency_share_supervisor | <5% | v5.3: Fraction of actions requiring human supervisor intervention |

### Research KPIs (Phase 3+, logged for future papers)

| Metric | Purpose |
|--------|---------|
| survival_turns per run | Basic progress metric |
| death_cause_diversity | Are we dying to new things? (good) |
| adaptation_rate | Deaths per root_cause before adapting |
| counter_exploitation | counter_was_used / build_had_counter |
| note_accuracy | Manual spot-check of notes vs game state |
| milestone_completion | Route-agnostic progress milestones (defined below) |

**v5.3: KPI measurement scope**:
KPIs must be measured separately by turn type to be meaningful:
- **LLM-owned turns**: Turns where the LLM makes a terminal action decision.
  `decision_latency_ms` and `tool_calls_per_turn` apply here.
- **AutoAct turns**: Turns where C# AutoAct is driving. These are near-zero latency
  and should NOT dilute the LLM p95 measurement.
- **Fallback turns**: Turns resolved by `state_fallback()`. Track separately.
- **Supervisor turns**: Turns requiring human intervention. Track separately.

The headline p95 <5s applies to **LLM-owned turns only**.
Overall turn latency (including AutoAct) will be much lower and is less meaningful.

### Logging (always on, from Phase 1)

Everything is logged to SQLite with versioned harness ID:
- All tool calls + results + latency
- All action outcomes + net_value
- All note changes (before/after)
- All deaths with full taxonomy
- Harness version + seed + model + config

This enables future research without changing the streaming setup.

### v3.2: Evaluation Strategy

Two complementary evaluation approaches:

**1. C# Component Regression Tests** (deterministic, per-commit):
- Recorded input → expected output for individual components
- SafetyGate: given state X, should return block/confirm/warn/pass
  (API responses use lowercase; `safety_gate_log.decision` stores UPPERCASE for SQL readability.
  Canonical mapping: block↔BLOCK, confirm↔CONFIRM, warn↔WARN, pass↔PASS)
- CandidateGenerator: given state X, should produce candidates with expected properties
- DeltaTracker: given pre/post state, should compute expected net_value and tags
- These are standard unit test fixtures — golden traces, not full-game replays.

**2. N-Run Statistical Comparison** (stochastic, per-improvement-cycle):
- Run agent 5-10 times, compare averages before/after a change
- Primary metric: `eval_score = survival_turns × milestone_completion × (1 - flee_rate)`
- **`milestone_completion`** (v4.0, embedded from v2.1):
  Weighted sum of 10 route-agnostic milestones, each scored 0 or 1:
  ```
  0.05 × survived_50_turns
  + 0.05 × survived_100_turns
  + 0.10 × reached_level_5
  + 0.10 × reached_level_10
  + 0.10 × first_zone_transition
  + 0.15 × completed_first_quest
  + 0.10 × acquired_artifact
  + 0.10 × defeated_named_enemy
  + 0.15 × reached_mid_game_zone (Grit Gate / Six Day Stilt / Bethesda Susa entrance)
  + 0.10 × survived_first_legendary_encounter
  ```
  Range: [0.0, 1.0]. A run that reaches mid-game with quests completed scores ~0.70+.
- Secondary metrics: death_cause_distribution, counter_exploitation, adaptation_rate
- Statistical significance: improvement must exceed 1 standard deviation across runs

**3. Micro-Evaluation (scenario fixtures, per-improvement-cycle)**:
- Scripted encounter templates that test agent behavior at intermediate granularity:
  - **Encounter fixture**: Spawn specific enemy configuration → verify flee/fight/ability decision
  - **Navigation interrupt fixture**: AutoAct path with scripted enemy appearance → verify interrupt response
  - **Modal fixture**: Present dialogue/level-up choice → verify reasonable selection
  - **SafetyGate boundary fixture**: HP at exact BLOCK/WARN thresholds → verify correct gating
- These fill the gap between unit tests (component-level) and N-run statistics (full-game-level)
- Self-improvement Issue verification becomes faster: test a threshold change against
  10 scenario fixtures in seconds, rather than waiting for N full runs

**CoQ Seed Limitation**:
World seed (`XRLCore.Core.Game.GetWorldSeed(null)`) controls map generation but
combat RNG is a separate channel (`Stat.GetSeededRandomGenerator()`). Identical
full-game replay is NOT possible — even with the same seed, enemy behavior varies
based on turn-of-entry and combat RNG rolls. Therefore:
- "Fixed-seed identical replay" = C# component unit tests only
- Agent improvement comparison = statistical (N-run averages), not paired replay
- Golden traces = C# unit test fixtures, not full-game replays

---

## 11. Codex Auth & API (from v2.1 Section 14)

### Retained as-is

- CLIENT_ID, AUTH_ISSUER, RESPONSES_ENDPOINT
- Device Code Flow
- Token reuse from ~/.codex/auth.json
- Refresh strategy (60s before expiry)
- 401 recovery state machine

### Changes for v3

- Request body uses `tools` + `tool_choice: "auto"` instead of `text.format.type: json_schema`
- `parallel_tool_calls: false` (sequential tool calling for game turn coherence)
- `stream: true` (for latency measurement and overlay updates)
- `reasoning` field: omitted for spark, `effort: none` for gpt-5.4 normal play,
  `effort: medium` for post-death reflection

---

## Appendix A: Meta-Agent — Future Scope (Phase 5+)

**Not needed for streaming MVP.** Included as design direction only.

### Concept
An outer-loop LLM periodically reviews aggregated gameplay logs (SQL queries,
not raw logs) and proposes bounded improvements via structured issue templates.
Human approves or rejects each proposal.

### Allowed changes
- Safety thresholds, scoring weights, tool descriptions, system prompt tweaks

### Not allowed
- CandidateGenerator logic, new tools, architectural changes

### Prerequisites (from Phase 3)
- 20+ runs of structured logs
- N-run statistical comparison infrastructure
- Eval metric: `survival_turns × milestone_completion × (1 - flee_rate)`

See `docs/memo/v3.2-revision-plan.md` §10 for full issue template and failure modes.

---

## Appendix B: Build Selection for Initial Streaming

### Recommended Starting Builds

| Build | Genotype | Why it's entertaining |
|-------|----------|---------------------|
| **Warden** | Mutated Human | v2.1 reference build. All passive mutations. Stable baseline. |
| **Pyrokinetic** | Mutated Human | Active fire abilities. Visually dramatic. Tests ability usage. |
| **Praetorian** | True Kin | Cybernetics. Different action space. Tests build diversity. |

Start with Warden (safest), graduate to Pyrokinetic (more dramatic).
Praetorian only after the system handles True Kin cybernetics.

### Game Mode

- **Development**: Roleplay (checkpoint recovery)
- **Normal streaming**: Roleplay (sustained play, less frustrating)
- **Special events**: Classic (permadeath, high stakes drama)
- **Research evaluation**: Classic (true permadeath for honest metrics)

---

## Appendix C: Prior Art (abbreviated)

| System | Relation to LLM-of-Qud |
|--------|------------------------|
| Claude Plays Pokemon | Same tool-calling pattern, simpler game, 3 tools |
| Gemini Plays Pokemon | Richer harness (mental map, sub-agents), hobby→official report |
| GPT Plays Pokemon | Fastest completion, companion website for transparency |
| BRAID (NetHack) | Code generation sandbox, 12.56% progress, "harness matters" |
| NetPlay (NetHack) | Skill selection, closest to v2.1's candidate design |
| BALROG (benchmark) | Direct action output, 1.5% progress, knowing-doing gap |
| Voyager (Minecraft) | Code generation + skill library, iterative verification |
| Mindcraft (Minecraft) | 47 parameterized tools, code generation hybrid |
| CLIN | Structured causal abstractions, cross-episode learning |
| Motif | Offline LLM reward shaping for RL |
| AutoHarness | LLM synthesizes game harness code |

---

## Appendix D: Canonical Wire Message Schemas (v4.0e)

All messages are JSON over WebSocket. Every message includes `message_id` and `session_epoch`.

### TurnStart (C# → Python)
```json
{
  "type": "turn_start",
  "tid": 142,
  "rid": "run_007",
  "snapshot_hash": "a3f2c1",
  "state_version": 284,
  "message_id": "msg_142_ts",
  "session_epoch": 3,
  "game_state": "combat",
  "hostile_visible": true,
  "visible_hostile_count": 2,
  "hostile_perceived": true,
  "modal_active": false,
  "modal": null,
  "auto_act_active": false,
  "interrupt_reason": null,
  "prev_outcome": {
    "hp_delta": 0, "risk_delta": -15, "net_value": 2.5,
    "tags": ["broke_los", "maintained_cover"]
  }
}
```

When `modal_active == true`, `modal` contains:
```json
{
  "type": "dialogue",
  "title": "Mehmet",
  "prompt": "Live and drink, friend.",
  "choices": [
    {"id": "ch1", "label": "Ask about water ritual", "is_default": false, "is_irreversible": false},
    {"id": "ch2", "label": "Trade", "is_default": false, "is_irreversible": false},
    {"id": "ch3", "label": "Leave", "is_default": true, "is_irreversible": false}
  ],
  "fallback_choice_id": "ch3"
}
```

When `interrupt_reason` is set (AutoAct was interrupted):
```json
{
  "type": "turn_start",
  "tid": 147,
  "rid": "run_007",
  "snapshot_hash": "b4e1d2",
  "state_version": 290,
  "message_id": "msg_147_ts",
  "session_epoch": 3,
  "game_state": "combat",
  "hostile_visible": true,
  "visible_hostile_count": 1,
  "hostile_perceived": true,
  "modal_active": false,
  "modal": null,
  "auto_act_active": false,
  "interrupt_reason": "hostile_perceived",
  "prev_outcome": {"hp_delta": 0, "net_value": 0, "tags": []}
}
```

### ReconnectAck (C# → Python)
```json
{
  "type": "reconnect_ack",
  "session_epoch": 4,
  "message_id": "msg_reconn_ack_004",
  "in_reply_to": "msg_reconn_004",
  "state_version": 285,
  "snapshot_hash": "b4e1d2",
  "game_state": "combat",
  "hostile_visible": true,
  "visible_hostile_count": 1,
  "hostile_perceived": true,
  "modal_active": false,
  "modal": null,
  "auto_act_active": false,
  "last_applied_action_nonce": "f7a1b2c3",
  "last_applied_message_id": "msg_142_exec_01",
  "snapshot": {
    "map": {"rows": ["###.....###", "...@....##."], "axes": "x_right_y_down"},
    "entities": [{"id": "e1", "name": "snapjaw", "pos": [2, -1], "threat": "moderate"}],
    "player": {"hp": [18, 24], "level": 3, "pos": [5, 5]},
    "notes": {"current_objective": "explore:stairs_down:JoppaWorld.10.25 — Find stairs"},
    "zone_id": "JoppaWorld.10.25.1.1.10"
  }
}
```

### HeartbeatAck (C# → Python)
```json
{
  "type": "heartbeat_ack",
  "session_epoch": 3,
  "message_id": "msg_hb_ack_001",
  "in_reply_to": "msg_hb_001",
  "auto_act_active": true,
  "state_version": 287,
  "tid": 149,
  "navigate_destination": "stairs_down at [8, 0]",
  "steps_remaining": 2
}
```

### SupervisorRequest (C# → Python)
```json
{
  "type": "supervisor_request",
  "session_epoch": 3,
  "message_id": "msg_sup_001",
  "tid": 142,
  "reason": "level_up",
  "game_state": "modal",
  "modal": {
    "type": "level_up",
    "title": "Level Up!",
    "prompt": "Choose a mutation to acquire:",
    "choices": [
      {"id": "ch1", "label": "Flaming Hands (Fire mutation)", "is_default": false, "is_irreversible": true},
      {"id": "ch2", "label": "Teleportation (Space mutation)", "is_default": false, "is_irreversible": true},
      {"id": "ch3", "label": "Heightened Hearing (Sensory)", "is_default": false, "is_irreversible": true}
    ],
    "fallback_choice_id": null
  },
  "timeout_s": 300
}
```

### SupervisorResponse (Python → C#)
```json
{
  "type": "supervisor_response",
  "session_epoch": 3,
  "message_id": "msg_sup_resp_001",
  "in_reply_to": "msg_sup_001",
  "action": "select",
  "choice_id": "ch2",
  "reason": "Teleportation synergizes with our Pyrokinetic build — blink + fire combo"
}
```

`action` values: `"select"` (choose specific option), `"resume"` (let LLM retry),
`"abort"` (force safe fallback). On supervisor timeout (300s), apply the same
state-aware timeout policy as `WAIT_FOR_SUPERVISOR`: non-modal falls through to
`Action.WAIT`; cancellable modals try `cancel_or_back`; level-up / uncancellable
modal / `modal_fallback_failed` / `modal_desync` remain paused and renew
`supervisor_request` — modal states MUST NOT fall through to `Action.WAIT`.
