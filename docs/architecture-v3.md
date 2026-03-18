# LLM-of-Qud v3: Implementation Plan

**Status**: v3.2-lite (streaming MVP spec)
**Date**: 2026-03-18
**Supersedes**: architecture-v2.1 (research-focused candidate selection design)
**Design shift**: Candidate selection → Hybrid tool-calling agent + safe candidate executor
**Reviews**: Pro review ×4 (2026-03-17, 2026-03-18 ×2, 2026-03-19), 5-agent independent verification

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

**stall-free minutes** — the stream must never freeze. 30 seconds of silence kills viewership.
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
│   request_candidates("combat") → execute("c2") →   │
│   write_note("snapjaws are dangerous in groups")    │
│                                                     │
│   navigate_to("stairs_down") ← direct movement     │
│   choose("option_2") ← dialogue/level-up/modal     │
├─────────────────────────────────────────────────────┤
│              Python Brain (localhost:4040)           │
│   Tool schema hosting, session management,          │
│   knowledge base, Codex API client                  │
├─────────────────────────────────────────────────────┤
│              C# MOD (Harmony patched)               │
│   Tool implementations, CandidateGenerator,         │
│   SafetyGate (multi-layer), ModalInterceptor,       │
│   ToolExecutor, AutoAct integration,                │
│   Snapshotter, DeltaTracker, DeathLogger            │
├─────────────────────────────────────────────────────┤
│              Caves of Qud (Unity/Mono)              │
└─────────────────────────────────────────────────────┘
```

### Turn Loop (per game turn)

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
3e. AutoAct interrupts on: enemy_visible, took_damage, hazard, popup → new turn_start

PATH C: Dialogue / Level-up / Modal
1-3a. Same as above
3b. LLM sees choices via inspect_surroundings (canonical source for modal state)
3c. LLM calls choose(choice_id, reason)
3d. C# SafetyGate pre-filter checks for irreversible options → WARN if detected
3e. C# applies choice → next turn
```

### Fallback Chain (unified through CandidateGenerator)

All fallback paths converge through CandidateGenerator. There is no separate
"heuristic fallback" that bypasses candidates. This prevents split-personality behavior.

```
Combat:    LLM calls execute()          → normal execution
Combat:    LLM timeout/max_calls        → force request_candidates("combat") → auto-pick highest-scored
Combat:    WebSocket disconnected       → C# CandidateGenerator → auto-pick highest-scored
Navigation: LLM timeout/max_calls      → continue current AutoAct (C#-driven, no LLM needed)
Navigation: WebSocket disconnected     → continue current AutoAct
Modal:     LLM timeout/max_calls       → choose default/first option
Modal:     WebSocket disconnected      → C# selects default/cancel option
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
| **Navigation** | Continue current AutoAct (already C#-driven) | Continue current AutoAct |
| **Modal** | `choose` first option (safe default) | C# selects default/cancel option |
| **Idle** (no enemies, no modal) | `navigate_to` nearest unexplored area | C# triggers AutoAct explore |

All fallback actions go through SafetyGate. Combat fallback goes through CandidateGenerator.
Non-combat fallback uses safe defaults (continue navigation, select default modal option).

### Bounded Autonomy: AutoAct Exploration

When navigate_to delegates to AutoAct, C# runs the pathfinder without LLM involvement.
This is explicitly a **bounded autonomy region** — the LLM chose the destination,
but C# handles the step-by-step movement. AutoAct is interrupted by guard conditions
(enemy visible, damage taken, hazard, popup), at which point control returns to the LLM.

---

## 2. Tool Definitions

### Tool Inventory (10 tools, Phase 2 MVP)

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

Phase 3 additions: assess_escape, assess_ability, search_archive (13 tools total)

### Situation-Based Tool Filtering (v3.2-lite)

Each turn, the tool loop restricts available tools based on game state
(Pro: "12 tools every turn is heavy; filter by situation"):

| Situation | Available Tools | Count |
|-----------|----------------|-------|
| Combat | inspect_surroundings, check_status, check_inventory, assess_threat, request_candidates, execute, write_note | 7 |
| Navigation | inspect_surroundings, check_status, check_inventory, navigate_to, request_candidates, execute, write_note, read_notes | 8 |
| Modal (dialogue/level-up) | inspect_surroundings, check_status, choose, write_note | 4 |
| Fallback (unknown) | All 10 tools | 10 |

Implemented via `allowed_tools` in the Responses API `tool_choice` parameter.

**v3.3: `request_candidates("utility")` boundary** (from Pro review #3):
- `combat`: attack, retreat, use_ability (offensive/defensive)
- `utility`: heal, consume_item, wait, use_item (non-combat)
- Movement uses `navigate_to` directly — NOT utility candidates
- Modal choices use `choose` directly — NOT utility candidates
- If the LLM is unsure whether to use `navigate_to` or `request_candidates`,
  the game_state filtering resolves it: combat state → candidates, non-combat → navigate_to

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

#### Observation Tools

**`inspect_surroundings`**
Returns: ASCII map (21×21), entity list with positions, terrain features, hazards.
Uses: ScreenBuffer._Char reading + zone.GetObjects() internally.

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
Move to a target location using AutoAct pathfinder.
C# handles step-by-step movement internally. Interrupts on guard conditions.

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
  "started": true,
  "destination": "stairs_down at [8, 0]",
  "estimated_steps": 5,
  "safety_warning": null
}
```

SafetyGate pre-filter:
- **WARN** on dangerous zone: `{"started": true, "safety_warning": "Entering zone tier 4 (your level: 3). Proceed with caution."}`
- Zone danger is computed as: `zone_tier > player_level / 3`

When AutoAct is interrupted, the next `turn_start` message includes `interrupt_reason`
(e.g., `"enemy_visible"`, `"took_damage"`, `"popup"`).

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
- **WARN** on irreversible options (if detectable by C#, e.g., permanent mutation selection)

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

`fallback_choice_id` (v3.4): The guaranteed-safe fallback choice. Invariant: exactly one
must exist per modal. Used by state_fallback() and auto-fallback when CONFIRM times out.
Replaces the ambiguous `choice_id: "default"` convention in fallback code.

Modal types: `"dialogue"`, `"level_up"`, `"confirmation"`, `"merchant"` (Phase 5+).
`is_default` marks the safe fallback option (used when LLM times out).
`is_irreversible` triggers SafetyGate WARN on `choose`.
`inspect_surroundings` is the **canonical source** for modal state (not `check_status`).

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
  "executed": true,
  "action": "retreat NW",
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
- **BLOCKED** (fatal actions): `{"executed": false, "reason": "AoE would hit self", "alternatives": ["c2", "c4"]}`
- **CONFIRM** (v3.4, irreversible non-fatal): `{"accepted": false, "acceptance_status": "confirm_required", "safety_decision": "confirm", "confirmation_id": "cfm_123", "reason": "Permanent mutation choice", "expires_at": {"tid": 142, "state_version": 284, "session_epoch": 3}}`
- **WARNING** (risky): `{"executed": true, "safety_warning": "HP critically low (15%), attack is risky"}`
- **OK**: `{"executed": true, "safety_warning": null}`
- **STALE** (hash mismatch): `{"executed": false, "reason": "Game state changed since candidates were generated. Call request_candidates again."}`

**v3.3: CONFIRM flow** (from Pro review #3): BLOCK/WARN/PASS alone is insufficient for
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

### Action Tool Terminal Contract (v3.2-lite)

`execute`, `navigate_to`, and `choose` are all **terminal actions** — they end the tool-calling
loop for the current turn. The C# response for all three uses a common result structure:

```json
{
  "accepted": true,
  "turn_complete": true,
  "action_kind": "navigate_to",
  "execution_status": "accepted",
  "action_summary": "Move toward stairs_down at [8, 0]",
  "outcome": {"hp_delta": 0, "net_value": 0, "tags": []},
  "safety_warning": null
}
```

| Field | Description |
|-------|------------|
| `accepted` | Whether the action was accepted (false = BLOCKED, STALE, or CONFIRM-pending) |
| `turn_complete` | Always true for accepted actions. LLM loop must exit. |
| `action_kind` | `"execute"`, `"navigate_to"`, or `"choose"` |
| `action_summary` | Human-readable summary for overlay |
| `outcome` | ActionOutcome (only for execute; null for navigate_to/choose) |
| `safety_warning` | SafetyGate warning message, or null |
| `execution_status` | v3.3: `"accepted"` \| `"in_progress"` \| `"arrived"` \| `"interrupted"` \| `"aborted"`. For navigate_to, distinguishes command acceptance from destination arrival. For execute/choose, always `"accepted"` on success. |
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

**v3.2: Plateau Detection** (for self-improvement loop):
Plateau is defined as **fixed-seed C# component replay shows same behavioral pattern**,
not just `survival_turns` stagnation. 3 consecutive improvement cycles with no measurable
change on the eval suite → escalate to human. This avoids the flee-bot trap where
`survival_turns` improves but gameplay quality degrades.

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
  NeutralEscape        → ambiguous (fled with significant damage)
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
  RANGED_ALPHA, SWARM, STATUS, HAZARD, RESOURCE, MELEE_SPIKE

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
when the archive layer is implemented.

### Design Principles (from research)

1. **Structured > unstructured** — CLIN's templates outperform free-form by 23 points
2. **Observation masking > summarization** — JetBrains found masking old observations saves 52% cost with +2.6% success
3. **Importance-based retention** — ExpeL's ADD/UPVOTE/DOWNVOTE/EDIT for noise control
4. **Self-reinforcing error is the #1 risk** — false beliefs persist and worsen over time

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
   - **Confidence**: Does the note have supporting evidence in recent game events?
     (e.g., writing "X is weak to fire" requires a fire attack on X in recent turns)
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
CREATE TABLE death_events (...);      -- root_cause_key, build_id, etc.
CREATE TABLE build_runs (...);        -- per-run statistics
CREATE TABLE encounter_log (...);     -- per-encounter outcomes

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
```

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
| Bootstrap.cs + Harmony.PatchAll() | §2 | No change |
| Snapshotter.cs | §2 | Returns data for inspect tools instead of TurnRequest |
| BuildProfileCapture.cs | §1, §2 | No change (BirthBuildProfile + RuntimeCapabilityProfile) |
| CandidateGenerator.cs | §7 | **Now a tool backend**: called via `request_candidates` |
| SafetyGate.cs | §8 | **Role change**: validates `execute` tool calls, 4-tier response (v3.3: BLOCK/CONFIRM/WARN/PASS) |
| ToolExecutor.cs | §18 | No change (verb dispatch) |
| ModalInterceptor.cs | §8b | No change (state machine for popups/dialogue/level-up) |
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

### Safety Design (v3.2: multi-layer)

SafetyGate is **multi-layer**: pre-filter on `navigate_to` (zone danger) and `choose`
(irreversible options), plus post-validation on `execute` (BLOCK/CONFIRM/WARN/PASS).
This aligns with Pro's recommendation: "pre-filter + post-validation, not single gate."

**v3.3: CONFIRM level** (from Pro review #3): BLOCK/WARN/PASS alone is insufficient for
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

def select_allowed_tools(game_state: str) -> list[dict]:
    """Select available tools based on current game state."""
    COMBAT_TOOLS = ["inspect_surroundings", "check_status", "check_inventory",
                    "assess_threat", "request_candidates", "execute", "write_note"]
    NAVIGATION_TOOLS = ["inspect_surroundings", "check_status", "check_inventory",
                        "navigate_to", "request_candidates", "execute",
                        "write_note", "read_notes"]
    MODAL_TOOLS = ["inspect_surroundings", "check_status", "choose", "write_note"]

    tools = {
        "combat": COMBAT_TOOLS,
        "navigation": NAVIGATION_TOOLS,
        "modal": MODAL_TOOLS,
        "idle": NAVIGATION_TOOLS,  # idle uses navigation tools
    }.get(game_state, NAVIGATION_TOOLS)
    return [{"type": "function", "name": t} for t in tools]

def force_action_tools(game_state: str) -> list[dict]:
    """After FORCE_ACTION_AFTER calls, restrict to terminal actions only."""
    forced = {
        "combat": ["request_candidates", "execute"],
        "navigation": ["navigate_to", "request_candidates", "execute"],  # v3.4: utility fallback for low HP
        "modal": ["choose"],
        "idle": ["navigate_to", "request_candidates", "execute"],  # v3.4: utility fallback for low HP
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

            elif output_item.type == "message":
                # v3.3: Do NOT display raw model "thinking" to stream viewers.
                # LLM extended thinking faithfulness is not guaranteed (Anthropic).
                # Only public_reason (from terminal actions) is shown on overlay.
                overlay.update_status("thinking")  # shows spinner, not content

    # Max calls exceeded — state-aware fallback
    return await state_fallback(game_state, overlay)

async def state_fallback(game_state: str, overlay) -> Action:
    """State-aware fallback when LLM exceeds max tool calls."""
    if game_state == "combat":
        candidates = await dispatch_tool("request_candidates", {"situation": "combat"})
        best = max(candidates.internal_candidates, key=lambda c: c.score)
        result = await dispatch_tool("execute", {
            "candidate_id": best.id,
            "candidate_set_id": candidates.candidate_set_id,
            "snapshot_hash": candidates.snapshot_hash,
            "public_reason": f"[AUTO] Timeout, picking best: {best.desc}"
        })
        if result.accepted:
            return result.action
        # If BLOCKED/STALE, use safest candidate (lowest risk_score)
        safest = min(candidates.internal_candidates, key=lambda c: c.risk_score)
        return (await dispatch_tool("execute", {
            "candidate_id": safest.id,
            "candidate_set_id": candidates.candidate_set_id,
            "snapshot_hash": candidates.snapshot_hash,
            "public_reason": "[AUTO] Fallback to safest option"
        })).action
    elif game_state == "modal":
        # Choose the modal's guaranteed-safe fallback option
        return (await dispatch_tool("choose", {
            "choice_id": current_modal.fallback_choice_id,
            "reason": "[AUTO] Timeout, choosing safe fallback"
        })).action
    else:
        # Navigation or Idle — explore nearest unexplored
        return (await dispatch_tool("navigate_to", {
            "target": "nearest_unexplored", "reason": "[AUTO] Timeout, exploring"
        })).action
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
6. State-aware fallback: combat→best candidate, modal→default, navigation/idle→explore
7. Safe fallback uses `risk_score` (not `min(score)`) to pick the safest option when best is BLOCKED/STALE
8. `result.to_llm_view()` strips scores — LLM never sees internal scoring

### Model Selection

| Situation | Model | Reasoning | Latency target |
|-----------|-------|-----------|---------------|
| Normal gameplay | gpt-5.4 | tool_choice="auto", effort=none | <5s per turn |
| Safe exploration (auto-explore active) | None (C# heuristic) | No LLM needed | 0ms |
| Post-death reflection | gpt-5.4 | effort=medium, offline | <30s |
| Note compaction (background) | gpt-5.3-codex-spark | Cheap summarization | <5s |

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

**`mode`** values: `"llm"` (normal), `"fallback"` (LLM timeout/error), `"autoact"` (batch exploration).
**`top_candidates`**: Top 3 by score from the last `request_candidates` call.
**`interrupt_reason`**: Set when AutoAct is interrupted (e.g., `"enemy_visible"`, `"took_damage"`).
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

Consumed by a lightweight web page (localhost:8080) displayed as OBS browser source.

---

## 8. Communication Protocol

### WebSocket Messages (C# ↔ Python)

**C# → Python: Turn Start** (v3.2: removed `active_plan`, kept `interrupt_reason`; v3.2-lite: added `game_state`)
```json
{"type": "turn_start", "tid": 142, "rid": "run_007",
 "snapshot_hash": "a3f2c1", "state_version": 284,
 "message_id": "msg_142_ts", "session_epoch": 3,
 "game_state": "combat",
 "hostile_visible": true,
 "visible_hostile_count": 2,
 "modal_active": false,
 "auto_act_active": false,
 "interrupt_reason": null,
 "prev_outcome": {"hp_delta": 0, "risk_delta": -15, "net_value": 2.5,
                   "tags": ["broke_los", "maintained_cover"]}}
```

**Game state determination** (C# computes, canonical):
- `modal_active == true` → **Modal**
- `hostile_visible == true` → **Combat**
- `auto_act_active == true` → **Navigation**
- else → **Idle**

Priority: Modal > Combat > Navigation > Idle.
`game_state` is the pre-computed result. `select_allowed_tools()` in Python uses this directly.

**Python → C#: Tool Call Request**
```json
{"type": "tool_call", "tid": 142, "tool": "inspect_surroundings", "args": {},
 "message_id": "msg_142_tc_01", "session_epoch": 3}
```

**C# → Python: Tool Call Response**
```json
{"type": "tool_result", "tid": 142, "tool": "inspect_surroundings",
 "result": {"map": {...}, "entities": [...], ...},
 "message_id": "msg_142_tr_01", "in_reply_to": "msg_142_tc_01"}
```

**Python → C#: Execute Action**
```json
{"type": "execute", "tid": 142, "candidate_id": "c2",
 "candidate_set_id": "cs_142_01", "snapshot_hash": "a3f2c1",
 "action_nonce": "f7a1b2c3", "state_version": 284,
 "message_id": "msg_142_exec_01", "session_epoch": 3,
 "public_reason": "Ranged enemy, need LOS break"}
```

**C# → Python: Execution Result**
```json
{"type": "exec_result", "tid": 142, "executed": true,
 "execution_status": "accepted",
 "action_nonce": "f7a1b2c3",
 "outcome": {"hp_delta": 0, "net_value": 2.5, "tags": ["broke_los", "maintained_cover"]},
 "safety_warning": null}
```

### AutoAct Integration (v3.2: navigate_to replaces PlanState/Batch)

v3.2 removes PlanState, horizon, and batch_ok from the wire protocol entirely.
Movement delegation is handled by `navigate_to`, which creates an AutoAct session
internally in C#. There is no LLM-visible PlanState.

**navigate_to → AutoAct flow:**
1. LLM calls `navigate_to(target, reason)`
2. C# SafetyGate pre-filter checks zone danger → WARN if `zone_tier > player_level / 3`
3. C# creates AutoAct session with guard conditions:
   - `enemy_visible` → interrupt
   - `took_damage` → interrupt
   - `hazard_detected` → interrupt
   - `popup/modal` → interrupt
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
 "interrupt_reason": "enemy_visible",
 "prev_outcome": {"hp_delta": 0, "net_value": 0, "tags": []}}
```

`interrupt_reason` tells the LLM *why* navigation was interrupted, enabling it to
respond appropriately (e.g., switch to combat mode on `"enemy_visible"`).
Telemetry logs navigation duration, steps completed, and interrupt reason.

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
- `state_version`: Monotonic counter incremented on every game state change.
  C# rejects terminal actions where `state_version` doesn't match current.

**Reconnect protocol**:
1. Python Brain detects WebSocket disconnect
2. On reconnect, Python sends `{"type": "reconnect", "session_epoch": N+1}`
3. C# responds with current game state snapshot (full, not delta)
4. Python Brain rebuilds context from snapshot and resumes tool loop
5. Any in-flight terminal actions from epoch N are rejected by C#

**Duplicate rejection rule** (C# side):
```
if msg.session_epoch < current_epoch → REJECT (stale session)
if msg.action_nonce in consumed_nonces → REJECT (duplicate)
if msg.state_version != current_state_version → REJECT (stale state)
else → ACCEPT and add action_nonce to consumed_nonces
```

**v3.4: Remaining idempotency gaps** (from Pro review #4):

1. **All wire messages** must include `message_id`. Update `tool_call` and `tool_result`
   messages to include `message_id` and add `in_reply_to` (echoes the `message_id` of
   the request being answered). This enables correlation when the same tool is called
   multiple times per turn.

2. **Duplicate terminal actions return cached prior result** instead of bare REJECT.
   This lets Python determine "was my action committed?" after a disconnect.
   Rule: `if action_nonce in consumed_nonces → return cached_result(action_nonce)`

3. **Reconnect snapshot shape** must be defined:
   ```json
   {"type": "reconnect_ack", "session_epoch": 4,
    "state_version": 285, "snapshot_hash": "b4e1d2",
    "game_state": "combat", "snapshot": {<full game state>},
    "last_applied_action_nonce": "f7a1b2c3",
    "last_applied_message_id": "msg_142_exec_01"}
   ```

4. **`write_note` idempotency**: `write_note` has side effects but is not a terminal
   action. Deduplicate via `message_id` on the `tool_call` message, or use
   `(rid, tid, key, normalized_content_hash)` as a natural upsert key.

5. **CONFIRM does NOT consume `action_nonce`**: The first CONFIRM response is
   informational only. The retry with `confirmed: true` generates a fresh nonce.

6. **`action_nonce` echo**: `exec_result` and reconnect responses must echo
   `action_nonce` so Python can reconcile which action was applied.

---

## 9. Phase Plan

### Phase 0: Spike — "Can We See and Act?" (2-3 weeks)

**Goal**: Verify C# MOD loads, observes game state, issues commands. No LLM.

Tasks:
- 0-A: MOD skeleton (Bootstrap.cs + Harmony.PatchAll)
- 0-B: ScreenBuffer observation (ASCII map dump to log)
- 0-C: Internal API observation (HP, position, zone, entities)
- 0-D: RuntimeCapabilityProfile capture (mutations, abilities, cooldowns)
- 0-E: BirthBuildProfile capture (genotype, calling, attributes)
- 0-F: Movement/attack command issuance via CommandEvent.Send()
- 0-G: Simple heuristic bot (flee if hurt, attack if adjacent, explore otherwise)

Exit criteria:
- Heuristic bot survives ≥50 turns on Warden
- All logged data matches in-game display
- No game crashes
- v3.3: Observation accuracy ≥99% (spot-check logged HP/position/entities vs actual)
- v3.3: Interrupt detection latency <1 game turn (enemy appears → interrupt fires)

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
Exit criteria:
- Full round-trip: C# → WebSocket → Python → tool call → C# → result → Python
- Latency <100ms for tool call round-trip (no LLM)

### Phase 2: LLM Integration — "Can the LLM Play?" (4-6 weeks, v3.1: extended per Pro review)

**Goal**: LLM plays CoQ via tool-calling loop. First playable demo.

Tasks:
- 2-A: Tool schemas (10 tools in Responses API format)
- 2-B: System prompt (gameplay instructions + build block + notes injection)
- 2-C: Tool-calling loop (tool_loop.py with timeout, max_calls, fallback)
- 2-D: CandidateGenerator as tool backend
- 2-E: SafetyGate multi-layer (pre-filter on navigate_to/choose + post-validation on execute)
- 2-F: Knowledge base (write_note/read_notes with validation + minimum admission control for dangerous keys)
- 2-G: ActionOutcome + EncounterResult feedback
- 2-H: Stream overlay (web page + OBS source)
- 2-I: navigate_to tool + AutoActHandler.cs (AutoAct integration + interrupt)
- 2-J: choose tool + ChoiceHandler.cs (modal choice dispatch)
- 2-K: Protocol idempotency (v3.3): message_id, action_nonce, state_version, session_epoch,
  duplicate rejection, reconnect protocol
- 2-L: cancel_or_back tool (v3.4): prerequisite for Gate 2, prevents modal deadlock

Exit criteria (staged):
- Gate 1: LLM survives ≥50 turns on Warden via tool-calling
- Gate 2: Overlay displays correctly, 0 modal deadlocks
- Gate 3: stall-free for ≥30 minutes continuous play
- Gate 4: 20-run evaluation: median survival >100 turns, p95 latency <5s, fallback rate <15%

### Phase 3: Learning — "Can It Get Better?" (4-6 weeks)

**Goal**: Cross-run improvement via death analysis and notes.

Tasks:
- 3-A: Death taxonomy (3-tier classification)
- 3-B: Auto-generated death recap → notes injection for next run
- 3-C: CLIN-style causal abstraction in learned_tactics notes
- 3-D: ExpeL-style importance management (success/fail counting)
- 3-E: Cross-run note seeding (≥2/5 runs with confirm > contradict carry forward)
- 3-F: search_archive tool implementation (SQLite FTS5 keyword search)
- 3-G: spatial_log auto-population (C# records zone visits, enemies, danger ratings)
- 3-H: assess_escape tool (standalone, split from request_candidates metadata)
- 3-I: assess_ability tool (standalone, split from request_candidates metadata)

Exit criteria:
- v3.3: Same death cause shows decreasing trend within 3/5 run window
  (single-run comparison too noisy due to CoQ run variance)
- Notes contain actionable, accurate tactical information
- Note quality doesn't degrade over 10+ runs

### Phase 4: Streaming Demo — "Can We Go Live?" (2-3 weeks)

**Goal**: Production-quality streaming setup.

Tasks:
- 4-A: OBS integration (game capture + overlay browser source)
- 4-B: Build selection for streaming (1-2 entertaining builds)
- 4-C: Roleplay mode for sustained play + Classic for special events
- 4-D: Chat integration (optional: Twitch chat → influence goals?)
- 4-E: Stability testing (24-hour unattended run)
- 4-F: Death counter, run statistics overlay
- 4-G: Human supervisor controls (v3.3): pause, skip_turn, force_safe_fallback,
  kill_switch, provider_outage_fallback, safe_camera_state. Essential for live streaming.

Exit criteria (staged):
- Gate 1: 30 minutes unattended stable streaming
- Gate 2: 2 hours unattended stable streaming
- Gate 3: 4+ hours unattended stable streaming
- Overlay is informative and entertaining
- No unrecoverable crashes

### Phase 5+: Future Scope

- Merchant interaction, equipment management, quest tracking
- Social systems (faction, water ritual)
- Multiple concurrent builds on screen
- Community voting on build/goal selection

---

## 10. Telemetry (Streaming + Research KPIs)

### Streaming KPIs (Phase 2+)

| Metric | Target | Purpose |
|--------|--------|---------|
| decision_latency_ms | <5000 (p95) | Stream doesn't feel slow |
| stall_rate | <1% of turns | No frozen screen |
| fallback_rate | <15% | LLM is actually making decisions |
| modal_deadlock_rate | 0% | Never stuck on popup |
| tool_calls_per_turn | 2-5 (median) | Not over-thinking or under-thinking |
| crash_rate | 0 per 8 hours | Stable enough for streaming |

### Research KPIs (Phase 3+, logged for future papers)

| Metric | Purpose |
|--------|---------|
| survival_turns per run | Basic progress metric |
| death_cause_diversity | Are we dying to new things? (good) |
| adaptation_rate | Deaths per root_cause before adapting |
| counter_exploitation | counter_was_used / build_had_counter |
| note_accuracy | Manual spot-check of notes vs game state |
| milestone_completion | Route-agnostic progress milestones (from v2.1) |

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
- SafetyGate: given state X, should return BLOCK/WARN/PASS
- CandidateGenerator: given state X, should produce candidates with expected properties
- DeltaTracker: given pre/post state, should compute expected net_value and tags
- These are standard unit test fixtures — golden traces, not full-game replays.

**2. N-Run Statistical Comparison** (stochastic, per-improvement-cycle):
- Run agent 5-10 times, compare averages before/after a change
- Primary metric: `eval_score = survival_turns × milestone_completion × (1 - flee_rate)`
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
