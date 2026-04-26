# ADR 0010: Phase 0-G heuristic exploration quality is a non-goal — harness boundary integrity is the deliverable

Status: Proposed (2026-04-27)

## Context

Phase 0-G Task 7 (`docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`)
ran a 5-run Warden Joppa acceptance gate against the
`IDecisionPolicy → HeuristicPolicy` boundary established by ADR 0009.
Two runs exposed two distinct categories of `HeuristicPolicy`
degeneracy:

- **Run 2** — feedback-memory bug. `_blockedDirs.Clear()` on a
  successful `Move` discarded wall knowledge, so the policy re-learned
  and re-bumped the same wall every cycle. `pass_turn_fallback_rate`
  reached 0.490 and the run failed ADR 0009 Decision #5.4
  (`pass_turn_fallback_rate ≤ 20%`,
  `successful_terminal_action_rate ≥ 70%`). Fixed by switching to
  per-cell `Dictionary<cellKey, HashSet<string>>` blocked-direction
  memory (`mod/LLMOfQud/LLMOfQudSystem.cs:42-46, 259+`,
  commit `b726814`).

- **Run 5** — policy algorithm oscillation. The deterministic
  `ExploreOrder = {E, SE, NE, S, N, W, SW, NW}` of `HeuristicPolicy`
  (`mod/LLMOfQud/HeuristicPolicy.cs:18-19`) creates a 2-cell N⇄S
  ping-pong inside a U-shape (コの字) wall pocket: at one cell
  E/SE/NE are wall-blocked so policy chooses S; at the next cell
  E/SE/NE/S are blocked so policy chooses N; back to start.
  Per-cell memory works correctly (no relearning). Player spent
  96.4% of turns oscillating between (55,3) and (55,4) of one zone.
  **The run technically passes ADR 0009 Decision #5.4**:
  `pass_turn_fallback_rate = 0.010`,
  `successful_terminal_action_rate = 0.990` — every Move had
  `pos_after != pos_before`, so the metric counts each step as a
  "successful terminal action".

The codex 2026-04-27 design consultation (operator-local capture
referenced in §Related Artifacts) recommended sharpening
Decision #5.4 with anti-cycle metrics
(`longest_two_cell_cycle_streak ≤ 20`, `two_cell_cycle_rate ≤ 0.30`,
`max_cell_visit_share ≤ 0.60`) plus an `Recent.LastDir`-aware
anti-backtrack policy patch (Option A+B in the consultation).

The operator rejected this direction with a reframing:

> LLMが操作するハーネスの基盤作りをしているのであって、自動で
> 探索する bot を作成しているわけではない

(*"We are building a harness foundation for LLM-driven operation,
NOT building an autonomous exploration bot."*)

The reframing inverts the diagnostic frame:

- The Phase 0-G deliverable per ADR 0009 §Decision #1 is the
  **closed-loop boundary** "observation DTO → judgment policy →
  terminal action → result feedback", validated by a minimal
  in-process policy. The boundary is what Phase 1 (Python brain via
  WebSocket bridge, `docs/architecture-v5.md:2836-2855`) and Phase 2+
  (LLM tool-call loop) inherit.
- `HeuristicPolicy` exists as scaffolding to exercise that boundary.
  Its exploration quality is not a deliverable — Phase 1's LLM
  trivially solves U-shape pockets by reasoning over `screen.log`
  context that no heuristic can replicate.
- Adding anti-cycle metrics to ADR 0009 Decision #5.4, or
  patching `HeuristicPolicy` with anti-backtrack/symmetry-break
  logic, builds a better bot — not a better harness. Both are
  category errors against the Phase 0-G purpose redefined in ADR
  0009 §Decision #1.

The empirical-probe-before-spec-lock principle
(`feedback_empirical_claim_probe_before_lock.md`) was correctly
invoked. PROBE 1 BASELINE (ADR 0009 §Context) falsified the original
"good heuristic" framing. Run 5 now falsifies the auxiliary
"acceptance metric measures meaningful interaction" framing in
ADR 0009 Decision #5.4 — but the right correction is to **declare
exploration quality a non-goal**, not to layer more quality metrics
on top.

## Decision

1. **Heuristic exploration quality is an explicit non-goal of
   Phase 0-G.** `HeuristicPolicy` is a boundary-validation scaffold.
   Cycles, oscillation, U-shape-pocket trapping, suboptimal direction
   priorities, and similar exploration pathologies are acceptable as
   long as boundary integrity (Decision #2 below) holds. Phase 1
   LLM ownership (`docs/architecture-v5.md:2836-2855`) absorbs all
   exploration quality concerns.

2. **ADR 0009 Decision #5.4 is sharpened, not extended.** The
   existing thresholds stand:
   - `pass_turn_fallback_rate ≤ 20%`
   - `successful_terminal_action_rate ≥ 70%` (Move with
     `pos_after != pos_before` OR `AttackDirection` with
     `result == true`)
   - `≥ 2 distinct intent values across the 5-run combined trace`

   Their **operational meaning is reframed**: these are
   *boundary-integrity sanity checks* (the harness is not stuck in
   wall-bump → pass_turn loops, the policy is not a constant
   function, telemetry is exercised across branches). They are
   explicitly NOT measures of exploration competence. A run that
   passes the thresholds via 2-cell oscillation in a wall pocket
   (Run 5 pattern) is an acceptable PASS.

3. **No new acceptance metrics are added.** In particular:
   - `longest_two_cell_cycle_streak` — REJECTED.
   - `two_cell_cycle_rate` — REJECTED.
   - `max_cell_visit_share` — REJECTED.
   - `distinct_cells_visited` — REJECTED.

   Future ADRs introducing exploration-quality gates require an
   explicit Phase 1+ scope that has the capability to pursue them
   (LLM observation reasoning OR Phase 1 System-layer pathfinder
   safety-net introduction with new ADR).

4. **No `HeuristicPolicy` quality patches.** The codex-recommended
   anti-backtrack via `Recent.LastDir` and `input.Turn`-keyed
   deterministic ExploreOrder rotation (Options A and B from the
   2026-04-27 consultation) are NOT adopted. `HeuristicPolicy`
   stays at its current minimal logic
   (`mod/LLMOfQud/HeuristicPolicy.cs`), including the deterministic
   ExploreOrder that produced the Run 5 U-pocket oscillation.

5. **CoQ-side pathfinder (`XRL.World.AI.Pathfinding.FindPath`,
   `decompiled/XRL.World.AI.Pathfinding/FindPath.cs:10`) integration
   is out of Phase 0-G scope.** The CoQ engine ships a navigation
   path solver used by mouse-click move and AI traversal. It is a
   plausible Phase 1+ System-layer safety-net candidate (e.g., when
   the policy reports a cycle-detection signal, the System layer
   could request a pathfind to a known unexplored cell). Phase 0-G
   does NOT take this dependency: doing so would require either
   policy-layer access (violating ADR 0009 §Decision #4 boundary —
   `Decide` reads only `DecisionInput`) or System-layer escape
   logic (extending the action enum or the boundary contract,
   which is `decision_input.v2` / `decision.v2` territory and out
   of Phase 0-G's locked schema).

6. **Phase 0-G exit memo (Task 9) documents the limitation
   explicitly.** The exit memo MUST contain a "Known Limitations"
   section stating:
   - `HeuristicPolicy` does not implement cycle detection or
     anti-backtrack, by design.
   - U-shape wall pockets and similar geometries can trap the
     policy in 2-cell oscillation indefinitely; this is observed
     in Run 5 of the Task 7 acceptance trace.
   - Exploration quality is owned by Phase 1 LLM; harness boundary
     integrity is the Phase 0-G deliverable.

   This makes the non-goal status part of the durable record so
   later phases do not re-litigate it.

## Alternatives Considered

1. **Add anti-cycle metrics (codex Option per 2026-04-27
   consultation).** Rejected: builds a better bot acceptance gate,
   not a better harness. Once the gate exists, the next degenerate
   pattern (3-cycle, 4-cycle, longer-period orbit, zone-boundary
   thrash) re-opens the question. There is no natural stopping
   point short of "is the explorer good", which Phase 0-G has
   already declared not its concern (ADR 0009 §Decision #1).

2. **Patch `HeuristicPolicy` with A+B (anti-backtrack +
   `Turn`-keyed deterministic shuffle).** Rejected: same category
   error. Further: per the patch-history meta-evaluation in the
   codex consultation, two consecutive policy patches (target_*
   gating, per-cell blocked memory) each exposed a new bug class.
   A third patch is statistically likely to expose a fourth, and
   none of them advance the boundary-validation deliverable.

3. **Drop the 5-run gate entirely.** Rejected: the gate
   (`docs/architecture-v5.md:2812`) is in the frozen architecture
   and operationalized by ADR 0009. Some minimum survival/parity
   sanity must remain to catch boundary-integrity regressions
   (crashes, ERR sentinels, JSON invalidity, decision/cmd parity
   loss). The 3 thresholds in ADR 0009 Decision #5.4 already
   provide that minimum; the issue is purely interpretive.

4. **Integrate CoQ `FindPath` in the System layer as a
   safety-net.** Rejected for Phase 0-G; explicitly flagged as a
   plausible Phase 1+ System-layer extension. Doing it now would
   either (a) violate the ADR 0009 §Decision #4 boundary (`Decide`
   must read only `DecisionInput`), or (b) require an action-enum
   extension that bumps `decision.v1` schema, both of which are
   out-of-scope churn for Phase 0-G's deliverable.

5. **Re-run Task 7 until 5 runs avoid wall pockets by chance.**
   Rejected: papers over the design-intent question. The right
   outcome is the explicit non-goal declaration; chance avoidance
   would leave the same misframing in place.

6. **Defer the rescope to Phase 0-H or Phase 1 entry.** Rejected:
   the misframing is already harming work-in-progress (the
   in-flight policy patches and metric proposals are concrete
   evidence). Locking the non-goal now prevents continued churn
   and unblocks Phase 0-G closure.

## Consequences

- **Run 5 from the Task 7 acceptance set is treated as PASS** under
  the sharpened interpretation in Decision #2. The 4-5 runs of the
  current acceptance set close Phase 0-G's `:2812` gate.
- **No further `HeuristicPolicy` changes** are made for Phase 0-G.
  The current `mod/LLMOfQud/HeuristicPolicy.cs` is the final Phase
  0-G policy.
- **No `validate.py` changes** at `/tmp/phase-0-g-acceptance/validate.py`.
  The validator's existing 7 checks remain authoritative.
- **Phase 0-G exit memo (Task 9)** must include the Known
  Limitations section per Decision #6.
- **Phase 1 inherits the boundary unchanged.** When the WebSocket
  bridge / LLMPolicy lands, exploration quality concerns activate
  for the first time. At that point, Phase 1 may choose to
  introduce a CoQ `FindPath` System-layer safety-net (per
  Decision #5) under a new ADR, or to rely entirely on LLM
  reasoning over `screen.log` context.
- **Acceptance criterion enumeration in ADR 0009 is unchanged.**
  ADR 0009 Decision #5 still has 5 acceptance criteria; only the
  operational interpretation of #5.4 is sharpened by this ADR.
  Future readers should read ADR 0009 §Decision #5.4 in
  conjunction with this ADR's §Decision #2.
- **Empirical-probe-before-lock meta-lesson is reinforced.**
  PROBE 1 BASELINE (ADR 0009) falsified the heuristic-specifics
  framing. Run 5 (this ADR) falsified the
  acceptance-metric-measures-quality framing. The meta-lesson:
  empirical runs can falsify framings at multiple levels of
  abstraction, and the right correction is sometimes "narrow the
  goal" rather than "tighten the gate".
- **Project memory `feedback_harness_not_bot.md` records the
  reframing** so the same category error does not recur in later
  phases.

## Supersedes

None. This ADR sharpens the operational interpretation of
ADR 0009 Decision #5.4 without amending its text. Future readers
should read both together.

## Related Artifacts

- `docs/adr/0009-phase-0-g-rescope-judgment-boundary.md` —
  established the judgment boundary and 5 acceptance criteria;
  this ADR sharpens the interpretation of Decision #5.4 without
  amending it.
- `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`
  — Task 7 acceptance methodology unchanged; Task 9 exit memo
  template extended per Decision #6.
- `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`
  — boundary contract unchanged.
- `docs/architecture-v5.md:2812` — Phase 0 exit criterion the
  acceptance gate operationalizes.
- `docs/architecture-v5.md:2836-2855` — Phase 1 WebSocket bridge
  that inherits the boundary and absorbs exploration quality.
- `mod/LLMOfQud/HeuristicPolicy.cs` — final Phase 0-G policy
  (no further changes per Decision #4).
- `mod/LLMOfQud/LLMOfQudSystem.cs:42-46, 259+` — per-cell
  blocked-direction memory introduced for the Run 2 fix
  (commit `b726814`); kept as the boundary-correct form of
  feedback memory.
- `decompiled/XRL.World.AI.Pathfinding/FindPath.cs:10` — CoQ engine
  pathfinder noted as plausible Phase 1+ System-layer safety-net
  candidate; not adopted in Phase 0-G.

The codex 2026-04-27 design consultation that grounded this ADR
exists as an operator-local working note (file name
`codex-phase-0-g-design-eval.md`, intentionally not committed —
it is verbatim chat output and adds no information beyond what is
inlined into §Context above). The Run 5 trace that triggered the
rescope is in the operator's 2026-04-27 acceptance Player.log
(operator-local; key metrics inlined into §Context above).
