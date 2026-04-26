# Phase 0-G: Judgment Boundary Validation — Design Spec

**Goal:** Prove the closed-loop boundary
"observation DTO → judgment policy → terminal action → result feedback"
works end-to-end with a minimal in-process policy. The heuristic bot
is the validation vehicle, not the deliverable. The boundary,
telemetry, and feedback path persist into Phase 1 (Python brain via
WebSocket bridge, `docs/architecture-v5.md:2836-2855`); the policy
implementation is the only thing Phase 1 replaces.

**Spec line `docs/architecture-v5.md:2804`** ("Simple heuristic bot
(flee if hurt, attack if adjacent, explore otherwise)") **is
implemented as written.** No pivot. The interrupt-detection-latency
exit criterion (`docs/architecture-v5.md:2817`) is satisfied by the
policy's same-turn branch under ADR 0008 Decision #1 (kept by
ADR 0009). AutoAct's engine-level interrupt remains owned by Phase 0b.

**Re-scope notice (ADR 0009):** PR-G1 (merged 2026-04-26 as PR #15)
locked specific heuristic logic at the spec level (`hurt` formula,
Chebyshev flee, east-bias scan, `boxed_in_attack` escalation,
4-condition `IsSafeCell`). The PROBE 1 BASELINE empirical run
revealed that locking implementation tactics in spec is misaligned
with Phase 0-G's true purpose. ADR 0009 partial-supersedes ADR 0008
and this spec is the rewritten version. See ADR 0009 §Decision and
§Supersedes for the full diff.

---

## Architecture

### Boundary

Inside `HandleEvent(CommandTakeActionEvent E)` (interface declaration:
`decompiled/XRL/IEventHandler.cs:882`) in
`mod/LLMOfQud/LLMOfQudSystem.cs`, the per-turn flow is three explicit
phases with a single boundary contract:

1. **`BuildDecisionInput`** (game thread): reads CoQ APIs and produces
   a `DecisionInput` DTO. This is the only phase that touches CoQ
   APIs.
2. **`Decide(DecisionInput) → Decision`** (game thread): pure
   function over the DTO. Reads no CoQ APIs. Returns a `Decision`
   value.
3. **`Execute(Decision)`** (game thread): dispatches the chosen
   terminal CoQ call (`Move` — `decompiled/XRL.World/GameObject.cs:15719`
   — or `AttackDirection` —
   `decompiled/XRL.World/GameObject.cs:17882` — the locked
   `decision.v1` action enum) and runs the 3-layer drain pattern
   (`PassTurn()` —
   `decompiled/XRL.World/GameObject.cs:17543` — is the Layer-2
   fallback when a Move fails without draining energy; it is engine
   bookkeeping, never a Decision-level action).

`Decide` is implemented behind the `IDecisionPolicy` interface
(Decision #4 below). The Phase 0-G in-process implementation is
`HeuristicPolicy : IDecisionPolicy`. Phase 1's `WebSocketPolicy` and
Phase 2+'s `LLMPolicy` will be drop-in replacements behind the same
interface; nothing in `BuildDecisionInput` or `Execute` changes.

### Per-turn output

7 log lines per CTA dispatch, unchanged from PR-G1's count:

- `[LLMOfQud][screen]` BEGIN + END (2 lines, multi-line LogInfo)
- `[LLMOfQud][state]` (1 line)
- `[LLMOfQud][caps]` (1 line)
- `[LLMOfQud][build]` (1 line)
- `[LLMOfQud][decision]` (1 line, NEW in 0-G)
- `[LLMOfQud][cmd]` (1 line)

Order inside `HandleEvent(CommandTakeActionEvent)`:
`[decision]` MUST emit BEFORE `[cmd]` on the same handler invocation
(both are game-thread direct emits). Order across the four
render-thread channels and the two game-thread channels remains
unconstrained — parser correlation is by `turn` field, never
adjacency.

### Hooks and inherited posture

- **Hook**: `CommandTakeActionEvent` (Phase 0-F;
  `decompiled/XRL/IEventHandler.cs:882`). `BeginTakeActionEvent`
  continues to drive `[state]/[caps]/[build]` observation.
- **Direct API path**: `Move(string Direction, bool DoConfirmations = true)`
  (`decompiled/XRL.World/GameObject.cs:15719`) and
  `AttackDirection(...)` (`decompiled/XRL.World/GameObject.cs:17882`)
  (ADR 0006). No `CommandEvent.Send`.
- **`PreventAction` scope**: success path leaves `PreventAction = false`
  so render-fallback fires per turn (ADR 0007). `PreventAction = true`
  is set ONLY when post-recovery `Energy.Value >= 1000`
  (`Energy` ≡ the `Statistic` named "Energy"; `Statistic.Value`
  accessor at `decompiled/XRL.World/Statistic.cs:238`; Layer 4
  abnormal-energy defense).
- **3-layer drain**: terminal action → `PassTurn()`
  (`decompiled/XRL.World/GameObject.cs:17543`) fallback →
  `Energy.BaseValue = 0`
  (`Statistic.BaseValue` accessor at
  `decompiled/XRL.World/Statistic.cs:218`) last-ditch (Phase 0-F).
- **Game-thread direct emit**: `[decision]` and `[cmd]` are emitted
  via `MetricsManager.LogInfo` synchronously from `HandleEvent`.
  `PendingSnapshot` continues to carry only the four render-thread
  channels.

---

## Schemas (locked — Phase 1 bridge marshals these)

### `DecisionInput` (in-process DTO; not directly logged)

A C# record passed to `Decide`. Field set is locked at the spec level
because the Phase 1 WebSocket bridge will marshal it to the Python
brain.

```
DecisionInput {
  int      turn
  string   schema      = "decision_input.v1"
  Player   player {
    int    hp
    int    max_hp
    Pos    pos { int x, int y, string zone }
  }
  Adj      adjacent {           // 8-direction snapshot
    string hostile_dir          // null | "N"|"NE"|...|"NW", first hostile wins
    string hostile_id           // null if hostile_dir is null
    string blocked_dirs[]       // accumulated directions where prior
                                // Move attempts hit the pass_turn
                                // fallback (i.e., bumped a wall /
                                // blocker). Maintained by
                                // BuildDecisionInput across turns.
                                // This is the ONLY safe-cell signal
                                // in the locked DTO.
  }
  History  recent {             // single-turn snapshot of last action
    int    last_action_turn
    string last_action           // "Move" | "AttackDirection"
                                 // (matches the locked Decision.action enum)
    string last_dir              // null | direction
    bool   last_result            // direct return value of the
                                  // terminal API call; false also
                                  // covers the engine-PassTurn
                                  // fallback case
  }
}
```

The DTO is not emitted verbatim on the wire (too large). A small
`input_summary` is emitted in `[decision]` (see below).

### `Decision` (in-process return; serialized into `[decision]`)

```
Decision {
  string intent          // "attack" | "escape" | "explore"
  string action          // "Move" | "AttackDirection"
  string dir             // never null when action != null
  string reason_code     // small enum, see below
  string error           // null on the success path; non-null
                         // serializes the policy-returned error
                         // string (distinct from Decide-throws,
                         // which emits the sentinel form below)
}
```

`intent` enum is wire-locked: `attack` / `escape` / `explore`.
`action` enum is wire-locked to the same set as `command_issuance.v1`:
`Move` / `AttackDirection`. `PassTurn` is NOT a Decision.Action — it
is engine bookkeeping that the 3-layer drain pattern emits as
`fallback="pass_turn"` on the `[cmd]` line when a Move fails without
draining energy (Phase 0-F invariant). When all 8 directions are
blocked, the policy still returns `explore: Move <some-dir>`; the
Move fails, the layered drain calls `PassTurn()`, and `[cmd]`
records `action="Move", result=false, fallback="pass_turn"`. This
preserves `command_issuance.v1` unchanged (Phase 0-F spec lines 150,
175, 218: action ∈ {Move, AttackDirection}, dir non-null, hard
failure otherwise).

The policy is free to pick which intent to return for any situation;
acceptance criterion 5.3 only constrains the mapping for three
specific probe scenarios. Adding a new intent value (e.g., `"hunt"`,
`"wait"`) or action value (e.g., `"PassTurn"` for resting) is a
wire-schema change and requires BOTH `decision.v2` AND
`command_issuance.v2` (joint bump) plus a new ADR — the locked enums
are what Phase 1's WebSocket bridge and any downstream parser will
dispatch on, and the two schemas are coupled by the action-set
shared lock.

`reason_code` enum is wire-locked: `adj_hostile` (a hostile is adjacent),
`low_hp_adj_hostile` (hurt classification triggered), `blocked_dir`
(blocked-direction memory triggered an alternative), `default_explore`
(no special signal, default action), `policy_error` (Decide threw or
returned invalid). Adding new reason codes is a wire-schema change
and requires `decision.v2` + a new ADR.

### `decision.v1` (wire schema for `[LLMOfQud][decision]`)

```json
{
  "turn": <int>,
  "schema": "decision.v1",
  "input_summary": {
    "hp": <int>,
    "max_hp": <int>,
    "adjacent_hostile_dir": "<dir>" | null,
    "blocked_dirs_count": <int>
  },
  "intent": "attack" | "escape" | "explore",
  "action": "Move" | "AttackDirection",
  "dir": "<dir>" | null,
  "reason_code": "<enum>",
  "error": null | "<message>"
}
```

Sentinel form (when `Decide` throws or `BuildDecisionInput` fails):

```json
{ "turn": <int>, "schema": "decision.v1", "error": "<type>: <message>" }
```

Field-additions or order changes require `decision.v2` + a new ADR,
following the same convention as `command_issuance.v1` (Phase 0-F
memo §"locked invariants").

---

## Acceptance criteria (5, replacing PR-G1's 13)

1. **Decision boundary exists.**
   `BuildDecisionInput → Decide → Execute` is the explicit per-turn
   flow inside `HandleEvent(CommandTakeActionEvent)`. `Decide` is
   declared as `IDecisionPolicy.Decide(DecisionInput) → Decision` and
   reads only the supplied DTO (no `The.Player`, no `Cell.*` calls,
   no `MetricsManager`). The `HeuristicPolicy` implementation is the
   only `IDecisionPolicy` consumer in 0-G; no Phase 1 stub yet.

2. **Decision telemetry is observable.**
   Every CTA-dispatched turn emits one `[LLMOfQud][decision]` line
   with `decision.v1` schema. JSON-valid in 100% of emitted lines.
   `cmd`/`decision` correlation by `turn` field: every `[cmd]` turn
   has a matching `[decision]` turn (and vice versa).

3. **Situation responsiveness — three controlled probes pass.**
   Run after the policy implementation lands; gates PR-G2 acceptance.
   Probes are deterministic in-game scenarios (`wish` console-driven)
   that exercise specific input → intent mappings:

   - **3a — Adjacent hostile elicits non-explore intent.**
     Setup: full-HP Warden, spawn an adjacent hostile via
     `wish testhero:Snapjaw scavenger`. Observe the next `[decision]`.
     PASS: `intent ∈ {"attack", "escape"}`. The executed `action`
     is `AttackDirection` toward the hostile (attack) OR `Move` away
     from the hostile (escape) — NOT `Move` into the hostile cell
     and NOT a `Move` toward an obvious wall.

   - **3b — Low HP elicits non-attack intent.**
     Setup: Warden with HP ≤ 30% of max (`wish damage:N`), adjacent
     hostile via `wish testhero:...`. Observe the next `[decision]`.
     PASS: `intent != "attack"`. The specific escape `action` is
     implementation discretion.

   - **3c — Blocked-direction memory.**
     Setup: position the Warden with a wall to the east, let the
     policy attempt `Move E` (or whatever the policy picks for
     "explore" default) for 1 turn (the bump appends `"E"` to
     `adjacent.blocked_dirs[]` on the FIRST failure — see "How
     PROBE 3c is satisfied" below). Observe the SECOND
     `[decision]` (1 turn into wall + 1 immediately after).
     PASS: the second decision returns either `action == "Move"`
     with a `dir` different from the prior blocked direction OR a
     non-`Move` `action`, with `reason_code == "blocked_dir"` on
     the post-bump turn. NOT another attempt in the blocked
     direction.

4. **Meaningful interaction gate.**
   Run on each of the 5 Warden survival runs (`docs/architecture-v5.md:2812`
   — 3-of-5 must survive ≥50 turns):

   - `pass_turn_fallback_rate ≤ 20%` over the run's `[cmd]` lines.
     Computed as `count([cmd] where action == "Move" and result == false and fallback == "pass_turn") / count([cmd])`.
   - `successful_terminal_action_rate ≥ 70%`. Computed as
     `count([cmd] where (action == "AttackDirection" and result == true) or (action == "Move" and pos_after != pos_before)) / count([cmd])`.
   - Across all 5 runs combined: `count(distinct [decision].intent) >= 2`.
     Proves the policy is not a constant function.

5. **Inherited safety gates** (Phase 0-F + ADR 0007 + ADR 0008
   Decision #6):
   - Compile clean (Roslyn in-game build, `Success :)` in
     `build_log.txt`).
   - Zero game crashes across all 5 runs.
   - Observation accuracy: 19/20 sampled turns match in-game display
     across `[state]` HP / pos / entities (ADR 0008 Decision #6;
     escalate to N=100 if tighter precision needed).
   - Cross-channel correlation: 6 channels' counts and `turn`-field
     parity hold per the ADR 0008 §criterion 9 rule (cmd/decision
     strict; others soft-warn on deviation).
   - JSON validity: 100% of structured-channel lines parse as JSON.
     `[screen]` is text framing per ADR 0008 (BEGIN/END/ERROR
     pattern), validated separately.
   - CTA hook + direct-API path + `PreventAction` posture preserved
     (no regression vs Phase 0-F's locked invariants).

---

## What's NOT spec-locked (implementation discretion)

The policy implementation (`HeuristicPolicy.Decide`) is free to
choose any of the following, as long as Decision #5's acceptance
criteria pass and the boundary contract (criterion 1: input-only
`Decide`) is preserved:

- HP threshold for the "hurt" classification. Probe 3b uses 30% as
  the *probe threshold*; the policy may use any threshold that
  satisfies the probe.
- Direction priority for explore. Any deterministic order.
- Escape tactic when surrounded ("boxed-in"). No spec-locked tactic
  name; just satisfy 3a/3b.
- How to interpret `adjacent.blocked_dirs[]` (treat as hard-block,
  soft-deprioritize, or ignore). The DTO field is provided; the
  policy chooses how to use it.

### What `Decide` MUST NOT do (boundary contract)

`Decide` reads only `DecisionInput`. It MUST NOT call any CoQ API:
no `The.*`, no `MetricsManager`, no `Cell.GetCellFromDirection`, no
`IsEmptyOfSolidFor`, no `GetCombatTarget`, no
`GetDangerousOpenLiquidVolume`, no `GameObject.*`. PROBE 2' enforces
this by static grep against the `Decide` method body.

If a policy needs richer per-direction safety information than
`adjacent.blocked_dirs[]` provides (e.g., walkable-vs-wall, hostile
in adjacent cell other than the first one wins), that information
MUST be pre-baked into `DecisionInput` by `BuildDecisionInput`. Adding
fields to `DecisionInput` is a `decision_input.v2` change and
requires a new ADR. Phase 0-G locks `decision_input.v1` to the field
set above; richer signals are deferred to Phase 1+ design.

### How PROBE 3c (blocked-direction memory) is satisfied

PROBE 3c is satisfied via `adjacent.blocked_dirs[]`, NOT via
`recent.last_*`. `recent` is a single-turn snapshot of the last
action; it does not carry K-deep history.
`UpdateBlockedDirsMemory` (in `BuildDecisionInput`) appends the
attempted `dir` to `adjacent.blocked_dirs[]` on the FIRST `Move`
failure, so by the very next turn the membership check is decisive
and the policy switches to a different `dir` (or a non-`Move`
action). No multi-turn lookback inside `Decide` is required.

---

## Empirical probe gate (revised — replaces PR-G1 PROBE 2-4)

Per ADR 0008 Decision #4 principle (kept by ADR 0009): probes gate
spec lock. The PR-G1 probes (PROBE 1-5) addressed the now-superseded
heuristic-specifics lock; they are replaced by:

- **PROBE 1' — Pre-impl baseline (BASELINE ONLY).** Already executed
  on Phase 0-F's `main` HEAD MOD: 9919 turns survived; 98.7%
  pass_turn fallback; ERR=0; full channel parity. Baseline informs
  the implementation but does NOT gate it. Recorded in ADR 0009
  §Context.
- **PROBE 2' — Decide-is-input-only (PRE-IMPL, design-time check).**
  Static review of the `IDecisionPolicy` definition + Phase 0-G
  `HeuristicPolicy` implementation: confirm `Decide` does not
  reference `The.*`, `MetricsManager`, or any `Cell.*` directly.
  Catches the most common boundary violation. PASS = grep
  confirms zero forbidden references in the `Decide` method body.
- **PROBE 3' — Three responsiveness probes (POST-IMPL).** As
  defined in Decision #5.3 above. Run after `HeuristicPolicy` lands;
  gates 5-run acceptance.

PROBE 4'/5' from PR-G1 (formula sweet-spot, channel correlation
under branch mix) are folded into Decision #5.4 (anti-degeneracy
gate) and Decision #5.2 (cmd/decision correlation), respectively;
they are no longer separate probes.

---

## Open hazards / deferred to Phase 0-G+

- **Engine-speed autonomy** still inherited from Phase 0-F. The
  WebSocket bridge (Phase 1) owns the fix.
- **Cooldown decrement** (`[caps].cooldown_segments_raw`) still not
  exercised through Phase 0-F. Phase 0-G runs Warden with standard
  preset mutations; if any passively-decrementing cooldown is
  observed, this phase is the first to exercise the field. Re-open
  trigger if `[caps].cooldown_segments_raw > 0` ever observed.
- **Multi-mod coexistence** still untested.
- **Save/load resilience** still untested.
- **Tutorial intercept on first turn** (Phase 0-F open hazard at
  `mod/LLMOfQud/LLMOfQudSystem.cs:245-247`). Operator instruction:
  skip the tutorial before the 50-turn run begins.
- **Hostile-interrupt path in ActionManager remains no-op** (Phase
  0-F open observation). 0-G's same-turn `Decide` IS the interrupt
  per ADR 0008 Decision #1.

---

## ADR 0009 timing — separate prerequisite docs PR

ADR 0009 + this revised spec + the revised plan land as docs-only
**PR-G1.5** on branch `docs/phase-0-g-rescope` cut from `main`.
Implementation PR (PR-G2) opens against `main` after PR-G1.5 merges
AND PROBE 2' (static check) passes against the implementation
draft. Same convergence shape as Phase 0-C / 0-E / 0-F / PR-G1.
