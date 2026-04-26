# Phase 0-G Implementation Plan — Judgment Boundary

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the `IDecisionPolicy` interface from Phase 0-F's
`HandleEvent(CommandTakeActionEvent)`, write a minimal in-process
`HeuristicPolicy` that satisfies the 5 acceptance criteria of the
revised spec at
`docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`,
add the `[decision]` channel with `decision.v1` schema, run 3
controlled responsiveness probes (post-impl) + 5-run Warden survival
gate with anti-degeneracy metrics, write the exit memo.

**Architecture:** Phase 0-F's monolithic `HandleEvent(CommandTakeActionEvent)`
becomes three explicit phases inside the same handler:
`BuildDecisionInput → Decide(via IDecisionPolicy) → Execute`. The
boundary is the deliverable; `HeuristicPolicy` is the validation
vehicle (NOT the deliverable). Phase 1 will replace `HeuristicPolicy`
with `WebSocketPolicy` behind the same interface.

**Tech Stack:** C# (Roslyn-compiled in-process by CoQ), `IPlayerSystem`
extension, `MetricsManager.LogInfo` for `[decision]` telemetry. No
new dependencies vs Phase 0-F.

**Re-scope notice (ADR 0009):** This plan replaces the PR-G1 plan
(merged 2026-04-26). The PR-G1 plan locked detailed heuristic
implementation steps (Chebyshev flee, `boxed_in_attack` escalation,
detailed `HandleEvent` refactor pseudocode). ADR 0009 partial-supersedes
those locks; this rewrite reflects the new scope.

---

## Definitions

- **Single gate before pushing**: `pre-commit run --all-files && uv run pytest tests/`.
  CI runs the same set + governance + C# analyzer + markdownlint.
- **PR convergence**: PR-G1.5 (this docs PR, ADR 0009 + revised spec
  + revised plan) merges first; impl PR-G2 opens after PROBE 2'
  static-check passes against the implementation draft.
- **Anti-degeneracy gate** = ADR 0009 Decision #5.4 metrics:
  `pass_turn_fallback_rate ≤ 20%`, `successful_terminal_action_rate ≥ 70%`,
  `count(distinct intent across all 5 runs) >= 2`.
- **PROBE 2' static check**: grep that `Decide` method body has zero
  references to `The.*`, `MetricsManager`, `Cell.*`, or any other
  CoQ API outside the `DecisionInput` DTO.

## Files affected

- **Modify**: `mod/LLMOfQud/LLMOfQudSystem.cs` — extract
  `BuildDecisionInput`, route `Decide` through `IDecisionPolicy`,
  emit `[decision]` before `[cmd]`.
- **Create**: `mod/LLMOfQud/IDecisionPolicy.cs` — interface +
  `DecisionInput` / `Decision` records.
- **Create**: `mod/LLMOfQud/HeuristicPolicy.cs` — the in-process
  `IDecisionPolicy` implementation for Phase 0-G validation.
- **Modify**: `mod/LLMOfQud/SnapshotState.cs` — add `BuildDecisionJson`
  and `BuildDecisionSentinelJson` for the `decision.v1` wire schema.

---

## Task 0: ADR 0009 + revised spec + revised plan landing (PR-G1.5)

This task is what PR-G1.5 IS. The branch is `docs/phase-0-g-rescope`
cut from `main`.

**Files for PR-G1.5:**

- Create: `docs/adr/0009-phase-0-g-rescope-judgment-boundary.md`
- Modify: `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`
  (rewritten for the judgment-boundary spec lock).
- Modify: `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`
  (this file).
- Modify: `docs/adr/decision-log.md` (append ADR 0009 entry).
- Create: `docs/adr/decisions/2026-04-26-...-rescope-...md` (decision
  record from `scripts/create_adr_decision.py`).

- [ ] **Step 1: Verify branch state.**

```bash
git branch --show-current   # expect: docs/phase-0-g-rescope
git log --oneline main..HEAD   # expect: empty (no commits yet)
```

- [ ] **Step 2: Verify all four artifact files are on disk.**

```bash
ls -la docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
wc -l docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
wc -l docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
wc -l docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
```

Expected sizes: ADR 0009 ~285 lines, spec ~330 lines, plan ~600 lines.

- [ ] **Step 3: Generate the machine-readable decision record.**

```bash
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Phase 0-G rescope to judgment boundary実証 — partial-supersede ADR 0008" \
  --rationale "PROBE 1 BASELINE empirical run revealed that PR-G1's heuristic-specifics lock optimizes for wrong object (short-lived implementation tactics) instead of the closed-loop boundary (observation DTO → judgment policy → terminal action → result feedback) that Phase 1 WebSocket bridge and Phase 2+ LLM tool-loop will inherit. ADR 0009 redefines purpose, locks IDecisionPolicy interface + decision.v1 schema, replaces 13 criteria with 5, replaces formula-validation probes with 3 controlled responsiveness probes, adds anti-degeneracy gate. Keeps ADR 0008 Decisions #1, #2, #4-principle, #5, #6." \
  --adr docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
```

The script creates `docs/adr/decisions/2026-04-26-...rescope...md`
and appends the index line. Edit the generated decision file's
`files:` list to include the ADR + spec + plan paths so the
pre-commit ADR gate passes.

- [ ] **Step 4: Commit + push.**

Single commit per Phase 0-F precedent (squash-merge collapses
multi-commit anyway):

```bash
git add docs/adr/0009-phase-0-g-rescope-judgment-boundary.md \
        docs/adr/decision-log.md \
        docs/adr/decisions/2026-04-26-*rescope*.md \
        docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md \
        docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
git status
git commit -m "docs: Phase 0-G rescope — ADR 0009 + revised spec + revised plan (PR-G1.5)"
git push -u origin docs/phase-0-g-rescope
```

- [ ] **Step 5: Open PR-G1.5 + codex APPROVE + merge.**

Run codex final-approval review on the package; if APPROVE, merge
with `--admin` per docs-PR fast-merge policy. If BLOCK, fix once,
re-verify.

---

## Task 1: PROBE 1' BASELINE — already done

**Why this task is here:** Documents that the PROBE 1 BASELINE has
already been executed against Phase 0-F's `main` HEAD (the empirical
observation that triggered ADR 0009). No re-run required; results
inform implementation but do not gate it.

**Result summary** (full data in operator's 2026-04-26 Player.log):

- Total: 9919 turns survived on Warden Joppa run.
- 124 turns (1.3%) `Move` success.
- **9788 turns (98.7%)** `Move result=false fallback=pass_turn`.
- 7 turns (0.07%) `AttackDirection`.
- ERR_* = 0 across all 6 channels.
- Cross-channel parity: complete.
- Player ended at HP 1/15 still alive.

**Implication for Phase 0-G implementation:**

- The `explore` policy needs blocked-direction memory and
  alternative-direction logic — pure east-bias degenerates.
- The `attack` branch needs HP-awareness — attacking adjacent hostile
  at HP=1 is NOT the right behavior (PROBE 3b).
- Phase 0-F's literal-50-turn-survival passes by coincidence of
  degenerate behavior; the new anti-degeneracy gate
  (`pass_turn_fallback_rate ≤ 20%`) is the operational `:2812` floor.

- [ ] **Step 1: Confirm PROBE 1 result is documented in ADR 0009 §Context.**

```bash
grep -A 20 "^## Context" docs/adr/0009-phase-0-g-rescope-judgment-boundary.md | head -25
```

Expected: §Context contains the 9919 / 1.3% / 98.7% / ERR=0 metrics.

---

## Task 2: `IDecisionPolicy` interface + DTO records

**Why this task exists:** The boundary IS the deliverable. This task
creates the type that Phase 1 will plug into. Implementing it before
the policy implementation prevents the policy from sneaking direct
CoQ API calls in (PROBE 2' static check requires the interface to
exist for the grep to be meaningful).

**Files:**

- Create: `mod/LLMOfQud/IDecisionPolicy.cs`

- [ ] **Step 1: Write the interface + DTO records.**

```csharp
// mod/LLMOfQud/IDecisionPolicy.cs
using System.Collections.Generic;

namespace LLMOfQud
{
    public sealed class Pos
    {
        public int X;
        public int Y;
        public string Zone;
    }

    public sealed class DecisionInput
    {
        public int Turn;
        public string Schema = "decision_input.v1";
        public PlayerSnapshot Player;
        public AdjacencySnapshot Adjacent;
        public RecentHistory Recent;
    }

    public sealed class PlayerSnapshot
    {
        public int Hp;
        public int MaxHp;
        public Pos Pos;
    }

    public sealed class AdjacencySnapshot
    {
        public string HostileDir;
        public string HostileId;
        public List<string> BlockedDirs;
    }

    public sealed class RecentHistory
    {
        public int LastActionTurn;
        public string LastAction;
        public string LastDir;
        public bool LastResult;
    }

    public sealed class Decision
    {
        // Intent enum: "attack" | "escape" | "explore"
        // Action enum: "Move" | "AttackDirection"
        // Locked together with command_issuance.v1's action enum;
        // PassTurn is engine bookkeeping (3-layer drain fallback),
        // never a Decision.Action. Adding wait/PassTurn requires a
        // joint decision.v2 + command_issuance.v2 bump per spec.
        public string Intent;
        public string Action;
        public string Dir;
        public string ReasonCode;
        public string Error;
    }

    public interface IDecisionPolicy
    {
        Decision Decide(DecisionInput input);
    }
}
```

The XML-doc comments are intentionally omitted to keep this file
short; the spec
(`docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`)
is the authoritative description of each field's semantics. The
critical invariant is repeated as a one-line comment above the
`IDecisionPolicy` declaration:

```csharp
// IDecisionPolicy.Decide MUST NOT reference The.*, Cell.*,
// MetricsManager, or any CoQ API outside the supplied DecisionInput.
// PROBE 2' (Task 4 Step 2) enforces this by grep.
public interface IDecisionPolicy
```

- [ ] **Step 2: Compile-check via in-game launch.**

```bash
grep -E "(=== LLM OF QUD ===|Success :\)|COMPILER ERRORS)" \
  "$HOME/Library/Application Support/Freehold Games/CavesOfQud/build_log.txt" \
  | tail -10
```

Expected: a fresh `Success :)` for the LLMOfQud build.

- [ ] **Step 3: Commit Task 2.**

```bash
git add mod/LLMOfQud/IDecisionPolicy.cs
git status
git commit -m "feat(mod): IDecisionPolicy interface + DecisionInput/Decision DTOs (Phase 0-G Task 2)"
```

---

## Task 3: `BuildDecisionJson` + `BuildDecisionSentinelJson` in SnapshotState

**Why this task exists:** The wire `decision.v1` schema needs a
builder that mirrors `BuildCmdJson`'s structure (Phase 0-F). Adding
it before the policy implementation lets the policy hook be wired up
without touching SnapshotState in the same commit.

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` — add two new static
  methods after `BuildCmdSentinelJson`.

- [ ] **Step 1: Read SnapshotState's existing builder shape.**

```bash
grep -n "BuildCmdJson\|BuildCmdSentinelJson\|AppendJsonStringOrNull\|AppendJsonIntOrNull" \
  mod/LLMOfQud/SnapshotState.cs
```

Note the helper functions and the brace style. Mirror them.

- [ ] **Step 2: Add `BuildDecisionJson` after `BuildCmdSentinelJson`.**

```csharp
internal static string BuildDecisionJson(int turn, Decision decision, DecisionInput input)
{
    StringBuilder sb = new StringBuilder();
    sb.Append("{");
    sb.Append("\"turn\":").Append(turn).Append(',');
    sb.Append("\"schema\":\"decision.v1\",");
    sb.Append("\"input_summary\":{");
    sb.Append("\"hp\":").Append(input.Player.Hp).Append(',');
    sb.Append("\"max_hp\":").Append(input.Player.MaxHp).Append(',');
    sb.Append("\"adjacent_hostile_dir\":");
    AppendJsonStringOrNull(sb, input.Adjacent.HostileDir);
    sb.Append(',');
    sb.Append("\"blocked_dirs_count\":")
      .Append(input.Adjacent.BlockedDirs == null ? 0 : input.Adjacent.BlockedDirs.Count);
    sb.Append("},");
    sb.Append("\"intent\":");
    AppendJsonStringOrNull(sb, decision.Intent);
    sb.Append(',');
    sb.Append("\"action\":");
    AppendJsonStringOrNull(sb, decision.Action);
    sb.Append(',');
    sb.Append("\"dir\":");
    AppendJsonStringOrNull(sb, decision.Dir);
    sb.Append(',');
    sb.Append("\"reason_code\":");
    AppendJsonStringOrNull(sb, decision.ReasonCode);
    sb.Append(',');
    // Serialize policy-returned Decision.Error (distinct from the
    // Decide-throws path, which uses BuildDecisionSentinelJson). A
    // policy may return a non-throwing error Decision (e.g.,
    // ReasonCode="policy_error" with a structured Error message);
    // dropping it here would hide failure from the acceptance gate.
    sb.Append("\"error\":");
    AppendJsonStringOrNull(sb, decision.Error);
    sb.Append("}");
    return sb.ToString();
}
```

- [ ] **Step 3: Add `BuildDecisionSentinelJson`.**

```csharp
internal static string BuildDecisionSentinelJson(int turn, Exception ex)
{
    StringBuilder sb = new StringBuilder();
    sb.Append("{");
    sb.Append("\"turn\":").Append(turn).Append(',');
    sb.Append("\"schema\":\"decision.v1\",");
    sb.Append("\"error\":");
    AppendJsonStringOrNull(sb, ex.GetType().Name + ": " + ex.Message);
    sb.Append("}");
    return sb.ToString();
}
```

- [ ] **Step 4: Compile-check via in-game launch.**

Same procedure as Task 2 Step 2. Expected: `Success :)`. Methods are
still unused at runtime; compilation validates syntax.

- [ ] **Step 5: Commit Task 3.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): BuildDecisionJson + BuildDecisionSentinelJson for decision.v1 wire schema (Phase 0-G Task 3)"
```

---

## Task 4: `HeuristicPolicy` minimal implementation

**Why this task exists:** Phase 0-G needs ONE `IDecisionPolicy`
implementation to validate the boundary. The implementation is
minimal — its purpose is to satisfy the 3 controlled probes (3a, 3b,
3c) and the anti-degeneracy gate, NOT to be optimal. Implementation
choices (HP threshold, direction priority, escape tactic) are
discretionary per spec §"What's NOT spec-locked".

**Files:**

- Create: `mod/LLMOfQud/HeuristicPolicy.cs`

- [ ] **Step 1: Write the minimal heuristic.**

```csharp
// mod/LLMOfQud/HeuristicPolicy.cs
using System.Collections.Generic;

namespace LLMOfQud
{
    // IMPORTANT: Decide MUST NOT reference The.*, Cell.*, MetricsManager,
    // or any CoQ API outside the supplied DecisionInput. PROBE 2' (Task 4
    // Step 2) enforces this by grep.
    public sealed class HeuristicPolicy : IDecisionPolicy
    {
        // Probe 3b uses 30% as the probe threshold; the policy may use
        // any threshold that satisfies the probe. 50% is a conservative
        // midpoint — passes 3b with margin.
        private const double LowHpRatio = 0.50;
        private const int LowHpFloor = 6;

        // Default explore direction priority. Any deterministic order
        // works as long as probe 3c passes (blocked-direction memory).
        private static readonly string[] ExploreOrder =
            new[] { "E", "SE", "NE", "S", "N", "W", "SW", "NW" };

        public Decision Decide(DecisionInput input)
        {
            string hostileDir = input.Adjacent.HostileDir;
            bool adjacentHostile = (hostileDir != null);

            int hp = input.Player.Hp;
            int maxHp = input.Player.MaxHp;
            int hurtThreshold = (int)System.Math.Max(LowHpFloor, System.Math.Floor(maxHp * LowHpRatio));
            bool lowHp = (hp <= hurtThreshold);

            if (adjacentHostile && lowHp)
            {
                return new Decision
                {
                    Intent = "escape",
                    Action = "Move",
                    Dir = OppositeDir(hostileDir),
                    ReasonCode = "low_hp_adj_hostile",
                    Error = null,
                };
            }

            if (adjacentHostile)
            {
                return new Decision
                {
                    Intent = "attack",
                    Action = "AttackDirection",
                    Dir = hostileDir,
                    ReasonCode = "adj_hostile",
                    Error = null,
                };
            }

            HashSet<string> blocked = (input.Adjacent.BlockedDirs == null)
                ? new HashSet<string>()
                : new HashSet<string>(input.Adjacent.BlockedDirs);

            foreach (string d in ExploreOrder)
            {
                if (!blocked.Contains(d))
                {
                    return new Decision
                    {
                        Intent = "explore",
                        Action = "Move",
                        Dir = d,
                        ReasonCode = (blocked.Count > 0) ? "blocked_dir" : "default_explore",
                        Error = null,
                    };
                }
            }

            // All 8 explore directions are in BlockedDirs. Don't
            // return a wait/PassTurn Decision — that would violate
            // the locked decision.v1 enum (intent ∈ {attack, escape,
            // explore}, action ∈ {Move, AttackDirection}, both lock
            // command_issuance.v1's action set). Instead, return
            // explore: Move ExploreOrder[0] and let the 3-layer drain
            // emit fallback="pass_turn" on the [cmd] line.
            return new Decision
            {
                Intent = "explore",
                Action = "Move",
                Dir = ExploreOrder[0],
                ReasonCode = "blocked_dir",
                Error = null,
            };
        }

        private static string OppositeDir(string dir)
        {
            switch (dir)
            {
                case "N":  return "S";
                case "NE": return "SW";
                case "E":  return "W";
                case "SE": return "NW";
                case "S":  return "N";
                case "SW": return "NE";
                case "W":  return "E";
                case "NW": return "SE";
                default:   return null;
            }
        }
    }
}
```

- [ ] **Step 2: Run PROBE 2' static check.**

```bash
awk '/public Decision Decide\(DecisionInput input\)/,/^        }$/' mod/LLMOfQud/HeuristicPolicy.cs \
  | grep -E "The\.|MetricsManager|Cell\.|GameObject\." \
  && echo "FAIL: forbidden CoQ reference inside Decide" \
  || echo "PASS: Decide is input-only"
```

Expected: `PASS: Decide is input-only`. If FAIL, refactor the
offending references out of `Decide` and into `BuildDecisionInput`
(Task 5).

- [ ] **Step 3: Compile-check via in-game launch.**

Same procedure as Task 2 Step 2. Expected: `Success :)`.
`HeuristicPolicy` is still unused at runtime (no caller in Phase 0-F
handler yet); compilation alone validates the code.

- [ ] **Step 4: Commit Task 4.**

```bash
git add mod/LLMOfQud/HeuristicPolicy.cs
git commit -m "feat(mod): HeuristicPolicy minimal IDecisionPolicy implementation (Phase 0-G Task 4)"
```

---

## Task 5: `HandleEvent(CTA)` refactor — wire the boundary

**Why this task exists:** Phase 0-F's `HandleEvent(CommandTakeActionEvent)`
is monolithic (Move-east + adjacent-attack inlined). Task 5
refactors it into the three explicit phases, with the policy plugged
in via the field-level `IDecisionPolicy` reference. This is the
deliverable.

**Files:**

- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs` — refactor body of
  `HandleEvent(CommandTakeActionEvent)`.

- [ ] **Step 1: Add the policy field + builder helpers.**

First, add `using System.Collections.Generic;` to the using
declarations at the top of `LLMOfQudSystem.cs` if it is not already
present (Phase 0-F's file currently imports only `System`,
`System.Text`, `System.Threading`, `ConsoleLib.Console`, `XRL`,
`XRL.Core`, `XRL.UI`, `XRL.World`, `XRL.World.Capabilities`). The
new fields and `BuildDecisionInput` use `HashSet<string>` and
`List<string>`; without the using, Roslyn will fail with
"The type or namespace name 'HashSet&lt;&gt;' could not be found".

Then add at the top of `LLMOfQudSystem`:

```csharp
private readonly IDecisionPolicy _policy = new HeuristicPolicy();

// Recent state for DecisionInput.Adjacent.BlockedDirs and .Recent.
// These are part of the boundary input; updated by Execute, read by
// BuildDecisionInput.
private readonly HashSet<string> _blockedDirs = new HashSet<string>();
private int _lastActionTurn = -1;
private string _lastAction;
private string _lastDir;
private bool _lastResult;
```

Add `BuildDecisionInput` as a private instance method, AFTER
extracting `ScanAdjacentHostile` from the current handler if it's
not already a private method:

```csharp
private DecisionInput BuildDecisionInput(GameObject player, int turn)
{
    Cell cell = player.CurrentCell;
    string hostileDir;
    GameObject hostileObj;
    ScanAdjacentHostile(cell, player, out hostileDir, out hostileObj);

    return new DecisionInput
    {
        Turn = turn,
        Player = new PlayerSnapshot
        {
            Hp = player.hitpoints,
            MaxHp = player.baseHitpoints,
            Pos = new Pos { X = cell.X, Y = cell.Y, Zone = cell.ParentZone.ZoneID },
        },
        Adjacent = new AdjacencySnapshot
        {
            HostileDir = hostileDir,
            HostileId = (hostileObj != null) ? hostileObj.ID : null,
            BlockedDirs = new List<string>(_blockedDirs),
        },
        Recent = new RecentHistory
        {
            LastActionTurn = _lastActionTurn,
            LastAction = _lastAction,
            LastDir = _lastDir,
            LastResult = _lastResult,
        },
    };
}

private void UpdateBlockedDirsMemory(string action, string dir, bool result, string fallback)
{
    if (action == "Move" && fallback == "pass_turn" && dir != null)
    {
        _blockedDirs.Add(dir);
        // Cap at 8 (one per cardinal direction).
        if (_blockedDirs.Count > 8)
        {
            // Drop oldest by clearing — coarse, fine for Phase 0-G.
            _blockedDirs.Clear();
            _blockedDirs.Add(dir);
        }
    }
    else if (action == "Move" && result)
    {
        // Player moved; old blockages may no longer apply.
        _blockedDirs.Clear();
    }
}

private void UpdateRecentHistory(string action, string dir, bool result, int turn)
{
    _lastActionTurn = turn;
    _lastAction = action;
    _lastDir = dir;
    _lastResult = result;
}
```

- [ ] **Step 2: Refactor `HandleEvent(CommandTakeActionEvent E)`.**

Replace the existing scan + branch + dispatch logic with the
three-phase boundary. Outer try/catch/finally + 3-layer drain
(ADR 0007 PreventAction posture) is preserved verbatim.

The new body shape (pseudocode — implementer fills concrete C#
following Phase 0-F's existing brace style):

```
HandleEvent(CommandTakeActionEvent E):
  int turn = _beginTurnCount
  GameObject player = The.Player
  if player == null:
    emit decision-sentinel; emit cmd-sentinel
    if player != null: PreventAction = true
    return true

  bool decisionEmitted = false
  try:
    int energyBefore = player.Energy.Value
    Pos posBefore = { player.CurrentCell.X, .Y, .ParentZone.ZoneID }

    # ---- BuildDecisionInput ----
    DecisionInput input = BuildDecisionInput(player, turn)

    # ---- Decide ----
    Decision decision
    try:
      decision = _policy.Decide(input)
    catch (Exception policyEx):
      MetricsManager.LogInfo("[LLMOfQud][decision] " + BuildDecisionSentinelJson(turn, policyEx))
      decisionEmitted = true
      throw  # falls into outer catch

    MetricsManager.LogInfo("[LLMOfQud][decision] " + BuildDecisionJson(turn, decision, input))
    decisionEmitted = true

    # ---- Execute ----
    bool result = false
    string fallback = null
    string actualAction = decision.Action
    string actualDir = decision.Dir

    # decision.v1 locks Action ∈ {"Move", "AttackDirection"}.
    # PassTurn is engine bookkeeping, not a Decision.Action; it
    # is reachable only via Layer 2 fallback below or the catch-path
    # recovery. See spec §"Decision wire schema".
    if decision.Action == "AttackDirection":
      result = player.AttackDirection(decision.Dir)
    elif decision.Action == "Move":
      result = player.Move(decision.Dir, DoConfirmations: false)

    # 3-layer drain — applies UNIFORMLY to BOTH terminal actions
    # (Phase 0-F invariant; see LLMOfQudSystem.cs:288-300). Either
    # action can return false without spending energy (Move bumps
    # a wall on the unforced path; AttackDirection misses a moved /
    # invalid target). The fallback check must be outside the
    # action-dispatch branch, not inside Move's branch only.
    bool energySpent = (player.Energy != null and player.Energy.Value < energyBefore)
    if !result and !energySpent:
      player.PassTurn()
      energySpent = true
      fallback = "pass_turn"
    elif !result:
      # Action drained energy on its own fail path; record fallback
      # for log honesty (Phase 0-F spec line 153 invariant).
      fallback = "pass_turn"

    UpdateBlockedDirsMemory(decision.Action, decision.Dir, result, fallback)
    UpdateRecentHistory(decision.Action, decision.Dir, result, turn)

    # Emit [cmd] (Phase 0-F shape, command_issuance.v1 unchanged)
    Pos posAfter = { player.CurrentCell.X, .Y, .ParentZone.ZoneID }
    CmdRecord cmd = { turn, "command_issuance.v1", "CommandTakeActionEvent",
                      actualAction, actualDir, result, fallback,
                      energyBefore, player.Energy.Value, posBefore, posAfter,
                      target_id, target_name, target_pos_before, target_hp_before, target_hp_after,
                      error: null }
    MetricsManager.LogInfo("[LLMOfQud][cmd] " + BuildCmdJson(cmd))

  catch (Exception ex):
    if !decisionEmitted:
      MetricsManager.LogInfo("[LLMOfQud][decision] " + BuildDecisionSentinelJson(turn, ex))
    MetricsManager.LogInfo("[LLMOfQud][cmd] " + BuildCmdSentinelJson(turn, ex))

    # 3-layer drain — energy-guarded recovery (Phase 0-F invariant /
    # ADR 0007). Catch-path threshold is the literal 1000 (NOT
    # energyBefore), because the exception may fire before
    # energyBefore is captured. The autonomy invariant depends on
    # Energy.Value < 1000 after this handler returns.
    if player != null and player.Energy != null and player.Energy.Value >= 1000:
      try { player.PassTurn() } catch { /* swallow */ }
      # BaseValue=0 is the last-ditch step ONLY if PassTurn did not
      # drain to < 1000. Do NOT clobber BaseValue when an action has
      # already spent energy.
      if player.Energy.Value >= 1000:
        player.Energy.BaseValue = 0

  finally:
    # ADR 0007: PreventAction is Layer-4 abnormal-energy defense, not
    # the primary autonomy mechanism. Set ONLY when post-recovery
    # Energy.Value >= 1000 (Layers 1/2/3 all failed to drain).
    if player != null and player.Energy != null and player.Energy.Value >= 1000:
      E.PreventAction = true

  return true
```

The `target_*` fields in the `[cmd]` line populate from `hostileObj`
captured during `BuildDecisionInput` (the implementer should pass
`hostileObj` through — either by holding a reference at the
LLMOfQudSystem instance level for the duration of one CTA dispatch,
or by re-scanning at `Execute` time using the `decision.Dir`).

- [ ] **Step 3: Compile-check via in-game launch.**

Same procedure as Task 2 Step 2. Expected:

- `build_log.txt` shows `Success :)` for the LLMOfQud build.
- Player.log shows ONE `[decision]` line and ONE `[cmd]` line per
  turn during the first few turns of a fresh chargen.
- `[decision]` lines parse as JSON; `intent ∈ {attack, escape, explore}` (locked enum, see spec).
- `[cmd]` lines retain the Phase 0-F `command_issuance.v1` shape.

```bash
PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
grep "INFO - \[LLMOfQud\]\[decision\]" "$PLAYER_LOG" | head -3 \
  | sed 's/^.*\[decision\] //' | jq .
grep "INFO - \[LLMOfQud\]\[cmd\]" "$PLAYER_LOG" | head -3 \
  | sed 's/^.*\[cmd\] //' | jq .
```

- [ ] **Step 4: Commit Task 5.**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "feat(mod): HandleEvent(CTA) refactor — BuildDecisionInput + IDecisionPolicy.Decide + Execute (Phase 0-G Task 5)"
```

---

## Task 6: PROBE 3' — three controlled responsiveness probes (post-impl)

**Why this task exists:** ADR 0009 Decision #5.3. Verifies the
implementation passes the three input → intent mappings before
opening PR-G2 acceptance.

**Files:** None (operator-driven in-game work). Captures land in
`/tmp/phase-0-g-probes/probe-3-prime/{3a,3b,3c}/result.md`.

- [ ] **Step 1: Set up probe scratch dir.**

```bash
mkdir -p /tmp/phase-0-g-probes/probe-3-prime/{3a,3b,3c}
```

- [ ] **Step 2: PROBE 3a — Adjacent hostile elicits non-explore intent.**

Operator workflow:
1. Launch CoQ. New game: Mutated Human + Warden + Roleplay + standard
   preset mutations. Skip tutorial.
2. In Joppa starting zone, find an empty adjacent cell. Use
   `wish testhero:Snapjaw scavenger` to spawn one hostile adjacent.
3. Take ONE turn (the policy will pick an action).
4. Capture the next `[decision]` line:

```bash
PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
grep "INFO - \[LLMOfQud\]\[decision\]" "$PLAYER_LOG" | tail -1 \
  > /tmp/phase-0-g-probes/probe-3-prime/3a/decision-line.txt
cat /tmp/phase-0-g-probes/probe-3-prime/3a/decision-line.txt | sed 's/^.*\[decision\] //' | jq .
```

PASS criteria:
- `intent ∈ {"attack", "escape"}` (NOT `explore`).
- `action ∈ {"AttackDirection", "Move"}` (locked decision.v1 enum).
  The policy must not return a Move into the hostile cell or away
  in a clearly-blocked direction.

Document outcome in `/tmp/phase-0-g-probes/probe-3-prime/3a/result.md`.

- [ ] **Step 3: PROBE 3b — Low HP elicits non-attack intent.**

Operator workflow:
1. Fresh Warden, drop HP to ≤ 30% of max via `wish damage:N`. Verify
   in-game HP matches.
2. Spawn an adjacent hostile via `wish testhero:Snapjaw scavenger`.
3. Take ONE turn.
4. Capture:

```bash
grep "INFO - \[LLMOfQud\]\[decision\]" "$PLAYER_LOG" | tail -1 \
  > /tmp/phase-0-g-probes/probe-3-prime/3b/decision-line.txt
cat /tmp/phase-0-g-probes/probe-3-prime/3b/decision-line.txt | sed 's/^.*\[decision\] //' | jq .
```

PASS criteria:
- `intent != "attack"`. The specific escape `action` is
  implementation discretion.

Document outcome in `/tmp/phase-0-g-probes/probe-3-prime/3b/result.md`.

- [ ] **Step 4: PROBE 3c — Blocked-direction memory.**

Operator workflow:
1. Fresh Warden, walk to a position with a wall directly east (or
   whatever direction the policy picks for default explore).
2. Let the policy attempt 3 consecutive turns in the wall direction
   (the policy will Move E → fail → pass_turn × 3).
3. Observe the 4th `[decision]`.

```bash
grep "INFO - \[LLMOfQud\]\[decision\]" "$PLAYER_LOG" | tail -4 \
  > /tmp/phase-0-g-probes/probe-3-prime/3c/decisions.log
cat /tmp/phase-0-g-probes/probe-3-prime/3c/decisions.log \
  | sed 's/^.*\[decision\] //' | jq -c '{turn, intent, action, dir, reason_code}'
```

PASS criteria:
- The 4th decision shows `action == "Move"` with `dir != <blocked
  direction>`. (decision.v1 locks Action ∈ {Move, AttackDirection};
  PassTurn is engine bookkeeping and never appears as a Decision
  action.)
- NOT another `Move` in the previously-blocked direction.

Document outcome in `/tmp/phase-0-g-probes/probe-3-prime/3c/result.md`.

- [ ] **Step 5: Tally + decide PR-G2 readiness.**

```bash
for sub in 3a 3b 3c; do
  echo "=== PROBE 3' $sub ==="
  cat /tmp/phase-0-g-probes/probe-3-prime/$sub/result.md
done
```

If all 3 PASS: proceed to Task 7 (5-run acceptance). If any FAIL:
revise `HeuristicPolicy.Decide` (the boundary stays unchanged; only
the in-process policy adjusts), re-run the failing probe.

---

## Task 7: 5-run Warden acceptance with anti-degeneracy gate

**Why this task exists:** `docs/architecture-v5.md:2812` — 3/5 runs
must survive ≥50 turns. ADR 0009 Decision #5.4 adds anti-degeneracy
metrics to operationalize "survive" as "interact meaningfully".

**Files:** None (operator-driven). Captures live in
`/tmp/phase-0-g-acceptance/run-{1..5}/`.

- [ ] **Step 1: Setup capture dir.**

```bash
mkdir -p /tmp/phase-0-g-acceptance/run-{1,2,3,4,5}
```

- [ ] **Step 2: Run RUN 1.**

Operator workflow:
1. Quit CoQ if running. Launch CoQ fresh.
2. New Game → Mutated Human → Warden → Roleplay → Standard preset.
   Skip tutorial.
3. Once in Joppa, do NOT press keys — the policy dispatches
   automatically.
4. Watch for ≥50 `[cmd]` lines OR player death. Once turn 50 is
   crossed (or player dies), quit CoQ.

Capture all 6 channels:

```bash
RUN=1
RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN
PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
cp "$PLAYER_LOG" "$RUNDIR/raw-player.log"
for ch in screen state caps build decision cmd; do
  grep "INFO - \[LLMOfQud\]\[$ch\]" "$RUNDIR/raw-player.log" > "$RUNDIR/$ch.log"
done
echo "Run $RUN: $(for ch in screen state caps build decision cmd; do
  echo -n "$ch=$(wc -l < $RUNDIR/$ch.log) "
done)"
```

- [ ] **Step 3: Repeat for RUN 2 through RUN 5.**

Within a single CoQ launch, multiple runs are possible by quitting
back to the main menu and starting a new game (`_beginTurnCount`
resets per Phase 0-E behavior).

- [ ] **Step 4: Write the validator to disk, then validate per-run.**

The validator is reused by Step 5's tally loop, so write it to a file
once instead of piping the heredoc to python3 stdin per invocation.

```bash
mkdir -p /tmp/phase-0-g-acceptance
cat > /tmp/phase-0-g-acceptance/validate.py <<'PY'
import json, os, sys, re

run = int(os.environ["RUN"])
rundir = os.environ["RUNDIR"]
hard_failures = []
soft_warnings = []

def parse_json_line(line):
    parts = line.split("] ", 1)
    if len(parts) != 2: return None
    try: return json.loads(parts[1].strip())
    except: return None

def parse_screen_line(line):
    parts = line.split("[LLMOfQud][screen] ", 1)
    if len(parts) != 2: return None
    m = re.match(r"(BEGIN|ERROR)\s+turn=(\d+)", parts[1].strip())
    return (m.group(1).lower(), int(m.group(2))) if m else None

# 1. Load 5 structured channels + screen.
channels = {}
for ch in ("state", "caps", "build", "decision", "cmd"):
    raw = open(f"{rundir}/{ch}.log").readlines()
    parsed = [parse_json_line(l) for l in raw]
    n_invalid = sum(1 for p in parsed if p is None)
    channels[ch] = {"raw": raw, "parsed": parsed, "n_total": len(raw), "n_invalid": n_invalid}
    if n_invalid > 0: hard_failures.append(f"[{ch}] {n_invalid} JSON-invalid lines")
screen_raw = open(f"{rundir}/screen.log").readlines()
screen_parsed = [parse_screen_line(l) for l in screen_raw]
begin_turns = sorted({p[1] for p in screen_parsed if p and p[0] == "begin"})
error_turns = sorted({p[1] for p in screen_parsed if p and p[0] == "error"})
channels["screen"] = {"n_total": len(begin_turns), "error_turns": error_turns}

# 2. Survival (criterion 1 = :2812 literal gate).
n_cmd = channels["cmd"]["n_total"]
last_state = next((p for p in reversed(channels["state"]["parsed"]) if p), None)
last_hp = (last_state or {}).get("player", {}).get("hp")
if isinstance(last_hp, list): last_hp = last_hp[0]   # Phase 0-D state shape: hp = [current, max]
print(f"Survival: n_cmd={n_cmd} last_hp={last_hp}")
if n_cmd < 50: hard_failures.append(f"survival: {n_cmd} cmd lines (need ≥50)")
if last_hp is None or last_hp <= 0: hard_failures.append(f"survival: last_hp={last_hp!r}")

# 3. ERR_SCREEN == 0 + soft ERRs (criterion 5 inherited).
err = {ch: sum(1 for p in channels[ch]["parsed"] if p and p.get("error")) for ch in ("state","caps","build","decision","cmd")}
err["screen"] = len(channels["screen"]["error_turns"])
print(f"ERRs: {err}")
if err["screen"] > 0: hard_failures.append(f"ERR_SCREEN={err['screen']}")
for ch in ("state","caps","build","decision","cmd"):
    if err[ch] > 0: soft_warnings.append(f"ERR_{ch.upper()}={err[ch]}")

# 4. Channel parity (criterion 2 + inherited).
counts = {ch: channels[ch]["n_total"] for ch in channels}
ref = counts["cmd"]
for ch in ("screen","state","caps","build","decision"):
    if counts[ch] != ref:
        msg = f"parity: {ch}={counts[ch]} vs cmd={ref}"
        (hard_failures if ch == "decision" else soft_warnings).append(msg)

# 5. Anti-degeneracy gate (criterion 4 — ADR 0009 §5.4).
cmd_parsed = [p for p in channels["cmd"]["parsed"] if p]
if cmd_parsed:
    n_pass_turn = sum(1 for c in cmd_parsed if c.get("action") == "Move" and c.get("result") is False and c.get("fallback") == "pass_turn")
    pass_turn_rate = n_pass_turn / len(cmd_parsed)
    n_terminal = sum(
        1 for c in cmd_parsed
        if (c.get("action") == "AttackDirection" and c.get("result") is True)
        or (c.get("action") == "Move" and c.get("pos_before") and c.get("pos_after") and c.get("pos_before") != c.get("pos_after"))
    )
    terminal_rate = n_terminal / len(cmd_parsed)
    print(f"Anti-degeneracy: pass_turn_fallback_rate={pass_turn_rate:.3f} successful_terminal_action_rate={terminal_rate:.3f}")
    if pass_turn_rate > 0.20:
        hard_failures.append(f"pass_turn_fallback_rate={pass_turn_rate:.3f} (need ≤0.20)")
    if terminal_rate < 0.70:
        hard_failures.append(f"successful_terminal_action_rate={terminal_rate:.3f} (need ≥0.70)")

# 6. Branch ↔ action invariant (criterion 2 + decision/cmd correlation).
cmd_by_turn = {p["turn"]: p for p in cmd_parsed if "turn" in p}
dec_by_turn = {p["turn"]: p for p in (channels["decision"]["parsed"] or []) if p and "turn" in p}
mismatches = 0
# decision.v1 locks Action ∈ {Move, AttackDirection}; PassTurn is
# engine bookkeeping (recorded as fallback="pass_turn" on the [cmd]
# line when a Move fails without draining energy). The validator
# therefore checks Decision-level intent → command_issuance.v1 action
# mapping only.
permitted = {
    "attack":  {"AttackDirection"},
    "escape":  {"Move", "AttackDirection"},
    "explore": {"Move"},
}
for t, dec in dec_by_turn.items():
    cmd = cmd_by_turn.get(t)
    if cmd is None:
        print(f"turn {t}: decision present but cmd MISSING"); mismatches += 1; continue
    intent, action = dec.get("intent"), cmd.get("action")
    if intent not in permitted or action not in permitted.get(intent, set()):
        print(f"turn {t}: intent={intent!r} action={action!r} (not permitted)")
        mismatches += 1
for t in cmd_by_turn:
    if t not in dec_by_turn:
        print(f"turn {t}: cmd present but decision MISSING"); mismatches += 1
if mismatches > 0: hard_failures.append(f"branch/action mismatches: {mismatches}")

# 7. Report.
print("=" * 60)
for w in soft_warnings: print(f"WARN: {w}")
for f in hard_failures: print(f"FAIL: {f}")
if hard_failures:
    print(f"Run {run}: FAIL"); sys.exit(1)
print(f"Run {run}: PASS"); sys.exit(0)
PY

# Per-run smoke check (run for one RUN before the Step-5 loop).
RUN=1   # or 2..5
RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN
RUN=$RUN RUNDIR=$RUNDIR python3 /tmp/phase-0-g-acceptance/validate.py
```

- [ ] **Step 5: Tally 3-of-5 gate + intent-distinct check.**

The validator file written in Step 4 is reused by this loop.

```bash
PASSING=0
for RUN in 1 2 3 4 5; do
  RUN=$RUN RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN python3 /tmp/phase-0-g-acceptance/validate.py \
    > /tmp/phase-0-g-acceptance/run-$RUN/validate.out 2>&1 \
    && PASSING=$((PASSING+1)) && echo "Run $RUN: PASS" \
    || echo "Run $RUN: FAIL"
done
echo "Passing: $PASSING/5"

ALL_INTENTS=$(for RUN in 1 2 3 4 5; do
  cat /tmp/phase-0-g-acceptance/run-$RUN/decision.log
done | sed 's/^.*\[decision\] //' \
  | jq -r 'select(.intent != null and .intent != "") | .intent' 2>/dev/null \
  | sort -u)
echo "Distinct intents observed: $ALL_INTENTS"
# Count only non-empty lines so missing-intent (sentinel) decisions
# do not falsely satisfy the >=2 gate. `grep -c .` already filters
# empty lines, but we also drop nulls explicitly above to belt-and-
# suspenders against jq's "null" stringification.
DISTINCT=$(echo "$ALL_INTENTS" | grep -cE '.+')
[ "$DISTINCT" -ge 2 ] && echo "Intent-diversity: PASS ($DISTINCT)" || echo "Intent-diversity: FAIL ($DISTINCT < 2)"
```

PASS gate: `PASSING >= 3` AND `Intent-diversity: PASS`. If FAIL,
revise `HeuristicPolicy` and re-run the failing run(s) — the
boundary does not change, only the in-process policy.

---

## Task 8: 99% observation accuracy audit

Inherited from PR-G1 plan; unchanged.

ADR 0008 Decision #6 (kept by ADR 0009): 19/20 sampled turns match
in-game display across `[state].player.hp/pos` and `[state].entities`.
Escalate to N=100 (allowing 1 mismatch) if tighter precision needed.

- [ ] **Step 1: Pick the audit run** (preferably the longest-running
  surviving run from Task 7).
- [ ] **Step 2: Sample 20 random turns** with `shuf -i 1-N -n 20`
  (or `python3 -c "..."` on macOS without `gshuf`).
- [ ] **Step 3: Compare each sampled turn's `[state]` against
  in-game display** (manual; replay or screen-record).
- [ ] **Step 4: Validate ≥19/20 match.** If <19/20, identify the
  failing field and open a follow-up issue.

---

## Task 9: Exit memo

Mirror `docs/memo/phase-0-f-exit-2026-04-26.md` shape; include:

1. Outcome (5-run survival count, anti-degeneracy metrics, audit
   accuracy, ADR 0009 rescope notes).
2. Acceptance counts table (per-run channel counts + ERR + intents
   observed).
3. Verified environment (CoQ build, mod load order, paths).
4. Sample shapes (one `[decision]` per intent value; one sentinel).
5. Phase 0-G implementation rules to carry forward to Phase 0-G+ /
   Phase 1:
   - `IDecisionPolicy` boundary (input-only `Decide`).
   - `decision.v1` schema field set.
   - Anti-degeneracy gate as the operationalization of `:2812`.
   - PROBE 3' three-probe pattern as the responsiveness contract.
6. Provisional cadence — future revisit triggers.
7. Open observations.
8. Open hazards (engine-speed autonomy, cooldown decrement,
   multi-mod, save/load, tutorial intercept).
9. Files created/modified in Phase 0-G.
10. References (ADR 0008, ADR 0009, decompiled APIs verified, spec).

---

## Self-review checklist (run after writing this plan)

- [ ] **Spec coverage**: each ADR 0009 §Decision item has a task that
  implements it.
- [ ] **No placeholders**: every step contains the actual content
  (code, command, expected output) an engineer needs.
- [ ] **Type consistency**: `IDecisionPolicy` / `DecisionInput` /
  `Decision` field names match between Tasks 2, 3, 4, 5.
- [ ] **Probe sequencing**: Task 1 (PROBE 1' done) → Task 2-5
  (build) → Task 6 (PROBE 3' validates impl) → Task 7 (5-run
  acceptance with anti-degeneracy) → Task 8 (audit) → Task 9 (memo).
- [ ] **Inherited invariants**: ADR 0006 direct-API path, ADR 0007
  PreventAction scope, Phase 0-F 3-layer drain, command_issuance.v1
  schema — all preserved in Task 5 refactor.
