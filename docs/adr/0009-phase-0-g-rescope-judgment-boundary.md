# ADR 0009: Phase 0-G rescope — judgment boundary実証 (partial-supersede of ADR 0008)

Status: Accepted (2026-04-26)

## Context

Phase 0-G was framed in PR-G1 (ADR 0008 + spec + plan, merged 2026-04-26
as PR #15) as a heuristic-bot implementation that locked specific
decision logic at the spec level: `hurt = max(8, floor(max_hp * 0.60))`,
Chebyshev-distance flee tiebreak, east-bias direction priority
`E → SE → NE → S → N → W → SW → NW`, a 4-condition `IsSafeCell`
predicate, and a `boxed_in_attack` escalation tactic.

After the merge, the first empirical observation of Phase 0-F's
existing behavior (the PROBE 1 BASELINE in the merged plan) revealed
a critical misalignment:

- Phase 0-F's existing handler (east-Move + adjacent-attack only, no
  decision branching) ran 9919 turns on a Warden Joppa run.
- 124 turns (1.3%) actual Move success.
- **9788 turns (98.7%)** Move-blocked-by-wall → `pass_turn` fallback.
- 7 turns (0.07%) `AttackDirection` (a giant amoeba encountered by
  chance).
- `ERR_* = 0` across all 6 channels; cross-channel parity perfect.
- Player ended at HP 1/15 still alive.

This satisfies `docs/architecture-v5.md:2812` ("Heuristic bot survives
≥50 turns on Warden in 3/5 runs") read literally — 9919 turns is 198×
the gate. But the system is not a "heuristic bot" by any meaningful
reading: it ignores observation when choosing actions, exhibits zero
situation responsiveness, and shows no feedback loop (9788 turns of
identical "Move E fails → pass_turn" with no behavior change). The
gate passes by coincidence of degenerate behavior.

The codex 2026-04-26 redesign consultation (operator-local capture
referenced in §Related Artifacts) confirmed the misalignment and
recommended a rescope. The core insight: Phase 0-G's value is NOT a
"good flee formula" — it is the **closed-loop boundary** that Phase 1
(Python brain via WebSocket bridge,
`docs/architecture-v5.md:2836-2855`) and Phase 2+ (LLM tool-call loop)
will replace. Locking implementation tactics (Chebyshev distance,
east-bias direction order, the `boxed_in_attack` invented tactic name)
in an ADR makes short-lived implementation details carry more inertia
than the boundary they sit behind.

PR-G1 therefore optimized for the wrong object: heuristic specifics
that LLM-time will discard, instead of the judgment boundary that
LLM-time will inherit. ADR 0009 rescopes Phase 0-G accordingly.

## Decision

1. **Purpose redefined.** Phase 0-G's purpose is to prove the
   closed-loop boundary "observation DTO → judgment policy → terminal
   action → result feedback" works end-to-end with a minimal
   in-process policy implementation. The heuristic bot is the
   validation vehicle, NOT the deliverable. Phase 1's
   WebSocket-bridged Python brain replaces only the policy
   implementation; the boundary, telemetry, and feedback path persist
   verbatim.

2. **Decisions KEPT from ADR 0008** (still authoritative):
   - **Decision #1** (`:2817` interpretation): the policy's same-turn
     branch satisfies the interrupt-latency criterion; engine-level
     `AutoAct.Interrupt` remains under Phase 0b.
   - **Decision #2** (new `[decision]` channel): `command_issuance.v1`
     stays untouched; the policy emits its own observation channel.
   - **Decision #4 principle** (empirical probe before spec lock):
     probes still gate spec lock. The specific PROBE 2-4 framing is
     superseded (see #3 below); the principle stays.
   - **Decision #5** (no deviation from architecture-v5.md frozen
     text).
   - **Decision #6** (`:2814` + `:2816` joint reading: 19/20 at N=20,
     escalation to N=100 for the 99% spirit).

3. **Decisions SUPERSEDED from ADR 0008:**
   - **Decision #3** (heuristic specifics lock): `hurt` formula,
     Chebyshev flee tiebreak, east-bias direction priority,
     `IsSafeCell` 4-condition predicate, `boxed_in_attack`
     escalation — ALL become implementation-discretion details of the
     in-process policy, NOT spec-locked. Phase 0-G implementations
     may choose any alternative that satisfies the new acceptance
     criteria in Decision #5 below.
   - **PROBE 2-4 specifics from Decision #4:** these were validation
     gates for the now-superseded specifics. Replaced by 3 controlled
     responsiveness probes (Decision #5.3 below) that target
     boundary-level invariants instead of formula values.

4. **Judgment boundary is the new spec lock.** The revised spec locks
   ONLY the boundary, not the policy:
   - **Interface:** `IDecisionPolicy.Decide(DecisionInput) → Decision`.
     `Decide` is **input-only** — it does NOT read CoQ APIs directly;
     it operates only on the supplied DTO.
   - **`DecisionInput` schema:** a snapshot of per-turn state
     (player HP/pos, adjacent hostile directions/IDs, blocked-direction
     memory, recent action history). Field-level `decision_input.v1`
     schema is locked at the spec level so the Phase 1 bridge can
     marshal it.
   - **`Decision` schema:** `{intent, action, dir, reason_code, error}`
     where `intent` is the policy-level branch (e.g., `"attack"` /
     `"escape"` / `"explore"`), `action` is the terminal CoQ call
     name, `reason_code` is a small enum classifying why the decision
     was made.
   - **Wire `[decision]` channel** (`decision.v1`): carries
     `{turn, schema, input_summary, intent, action, dir, reason_code, error}`.
     `input_summary` is a small operator-readable digest of the
     `DecisionInput`; full DTO is NOT logged (too large). Summary keys
     are implementation discretion.

5. **Acceptance criteria reduced to 5** (from ADR 0008's 13):
   1. **Decision boundary exists.**
      `BuildDecisionInput → Decide → Execute` is the explicit
      per-turn flow inside `HandleEvent(CommandTakeActionEvent)`.
      `Decide` reads only the `DecisionInput` DTO. The
      implementation is self-contained and replaceable by an
      out-of-process call without changing `BuildDecisionInput` or
      `Execute`.
   2. **Decision telemetry is observable.** `[decision]` channel
      emits per turn with the `decision.v1` schema. `cmd`/`decision`
      correlation by `turn` field; one `[decision]` line per `[cmd]`
      line.
   3. **Situation responsiveness.** Three controlled probes pass
      (run after the policy implementation lands; gates PR-G2
      acceptance):
      - **3a — Adjacent hostile elicits non-explore intent.** Player
        at full HP with a hostile adjacent in any direction. The next
        `Decide` returns `intent ∈ {"attack", "escape"}`; the executed
        action is NOT `Move` toward a wall, NOT `pass_turn`.
      - **3b — Low HP elicits non-attack intent.** Player at low HP
        (probe threshold: HP ≤ 30% of max) with a hostile adjacent.
        The next `Decide` returns `intent != "attack"`. The specific
        escape action is implementation discretion.
      - **3c — Blocked-direction memory.** Player attempts a Move in
        a wall-blocked direction for 3 consecutive turns. The 4th
        `Decide` returns either a `Move` with a different `dir` OR a
        non-`Move` `action`. NOT another `Move` in the blocked
        direction.
   4. **Meaningful interaction gate** (operationalizes `:2812`):
      For each surviving run in the 5-run gate:
      - `pass_turn_fallback_rate ≤ 20%` over the run's `[cmd]` lines.
      - `successful_terminal_action_rate ≥ 70%`, where "successful
        terminal action" is `AttackDirection` with `result == true`
        OR `Move` with `pos_after != pos_before`.
      Across all 5 runs combined: at least 2 distinct `intent` values
      are observed (proves the policy is not a constant function).
   5. **Inherited safety gates** (from Phase 0-F + ADR 0007):
      compile clean, no game crashes, observation-accuracy audit per
      ADR 0008 Decision #6, cross-channel correlation, JSON validity,
      CTA hook + direct-API path, `PreventAction` posture preserved.

6. **Anti-degeneracy gate operationalizes `:2812`.**
   `docs/architecture-v5.md:2812` reads "Heuristic bot survives ≥50
   turns on Warden in 3/5 runs". Decision #5.4 above adds
   anti-degeneracy metrics (`pass_turn_fallback_rate ≤ 20%`,
   `successful_terminal_action_rate ≥ 70%`, ≥2 intents observed) that
   operationalize "survive" as "survive while interacting meaningfully
   with the world". This excludes the degenerate "wall-bumping
   pass_turn loop" reading exposed by the PROBE 1 BASELINE. The
   architecture text is not changed; only its operational
   interpretation is sharpened. Same pattern as ADR 0008 Decision #6
   sharpening `:2816`'s "≥99%" as "19/20 at N=20".

7. **Implementation discretion.** Inside `Decide`, the policy
   implementation is free to choose: HP threshold for escape (3b uses
   30% as the *probe* threshold only; the policy may use any
   threshold that passes the probe), direction priority for explore,
   safe-cell predicate detail, escape tactic when surrounded
   (no spec-locked `boxed_in_attack` name), and whether to maintain
   blocked-direction memory in `DecisionInput` or recompute per turn.
   The only constraints are the boundary (Decision #4) and the
   acceptance criteria (Decision #5).

## Alternatives Considered

1. **Patch ADR 0008 in place.** Rejected: ADR 0008 is merged + cited;
   in-place edits break the immutability convention. New ADR with
   explicit partial-supersede is the project pattern.

2. **Total rewrite of ADR 0008.** Rejected: ADR 0008 contains
   valuable kept-decisions (`:2817` interpretation, `[decision]`
   channel, `:2814+:2816` joint reading). Partial-supersede preserves
   them.

3. **Rescope by ADR alone, leave PR-G1's spec/plan as-is.** Rejected:
   the spec/plan lock-in is in PR-G1's merged artifacts; the new
   acceptance criteria require the spec/plan to be rewritten. ADR
   alone cannot operationalize the new gate.

4. **Revert PR-G1 entirely.** Rejected: PR-G1 contains the kept
   decisions and the merged docs already inform downstream
   citations. Partial-supersede preserves the good work.

5. **Add anti-degeneracy gate as ADR 0008 amendment without scope
   change.** Rejected: anti-degeneracy is the symptom; locking
   implementation tactics is the disease. Patching the gate without
   rescoping leaves the heuristic-specifics lock in place — that lock
   is the actual problem.

6. **Skip ADR; just rewrite spec/plan in a docs PR.** Rejected: the
   freeze-rule (ADR 0001) requires an ADR for any decision that
   could be revisited later. Phase 0-G's purpose redefinition is
   exactly such a decision.

7. **Defer rescope to Phase 0-G+ / Phase 1.** Rejected: implementing
   the merged ADR 0008's heuristic specifics first and rescoping
   later would (a) waste implementation effort, (b) make the eventual
   Phase 1 bridge harder (the boundary needs to be stable BEFORE the
   bridge), (c) embed the misaligned `[decision]` schema in the wire
   contract.

## Consequences

- **PR-G1.5** (this ADR + revised spec + revised plan) lands as a
  docs-only PR per the PR-G1.5 amendment pattern documented in
  ADR 0008 Decision #4. Branch: `docs/phase-0-g-rescope` from `main`.
- ADR 0008's heuristic-specifics lock (Decision #3) is no longer
  authoritative. Future references to "Phase 0-G heuristic specifics"
  cite ADR 0009 + the revised spec.
- The implementation work (Tasks 2-4 in PR-G1's plan) is replaced
  with a smaller scope: extract `IDecisionPolicy` interface, build
  `BuildDecisionInput`, write a minimal heuristic implementation,
  wire telemetry. The 3-layer drain pattern, ADR 0007 `PreventAction`
  scope, and Phase 0-F invariants remain inherited verbatim.
- Phase 1 (WebSocket bridge) inherits a stable boundary:
  `IDecisionPolicy` becomes the natural plug-in point for a
  `WebSocketPolicy` implementation. Phase 2+ LLM tool-loop becomes a
  `LLMPolicy` implementation. No re-architecture needed at the bridge.
- The empirical-probe-before-spec-lock principle
  (`feedback_empirical_claim_probe_before_lock.md`) was correctly
  invoked but failed at a higher level: PROBE 1 revealed the spec was
  misaligned with the phase's true purpose, not just a parameter
  value. Recorded as a meta-lesson: probes can falsify framing as
  well as claims.
- The `decision.v1` schema field set is now substantively different
  from ADR 0008's spec (added `intent`, `input_summary`,
  `reason_code`; dropped `hp`, `max_hp`, `hurt`, `adjacent_hostile_dir`,
  `adjacent_hostile_id`, `chosen_dir`, `fallback`). The schema label
  remains `decision.v1` because no Phase 1 consumer has built against
  the prior shape; renaming would suggest backward compatibility we
  do not owe.

## Supersedes

Partially supersedes
`docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md`:

- **Supersedes**: Decision #3 (heuristic specifics lock) entirely;
  PROBE 2-4 specifics from Decision #4.
- **Keeps**: Decision #1 (`:2817` interpretation), Decision #2
  (`[decision]` channel as concept), Decision #4 principle
  (probe-before-lock), Decision #5 (no frozen-text deviation),
  Decision #6 (`:2814+:2816` joint reading).

Does NOT supersede `docs/adr/0001-architecture-v5-9-freeze.md`,
`docs/adr/0006-phase-0-f-command-issuance-api-pivot.md`, or
`docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md`.

## Related Artifacts

- `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`
  — revised in PR-G1.5 to lock the judgment boundary and 5
  acceptance criteria.
- `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`
  — revised in PR-G1.5 to drop PROBE 2-4 and detailed heuristic
  pseudocode; replaced with `IDecisionPolicy` interface extraction
  and 3 controlled responsiveness probes (post-implementation).
- `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` —
  partially superseded by this ADR (see §Supersedes).
- `docs/architecture-v5.md:2804` — Phase 0-G line implemented as
  written.
- `docs/architecture-v5.md:2811-2817` — Phase 0 exit criteria;
  `:2812` operationalized by Decision #6 above (anti-degeneracy
  gate).
- `docs/architecture-v5.md:2836-2855` — Phase 1 WebSocket bridge that
  consumes the `IDecisionPolicy` boundary established here.
- `mod/LLMOfQud/LLMOfQudSystem.cs:181-378` — current
  `HandleEvent(CommandTakeActionEvent)` body to be refactored into
  `BuildDecisionInput → Decide → Execute`.
- `mod/LLMOfQud/SnapshotState.cs` — site for `DecisionInput`,
  `Decision` types and `BuildDecisionJson` builder.

The codex 2026-04-26 redesign consultation that grounded this ADR is
captured operator-local at `/tmp/phase-0-g-prep/codex-redesign-answer.md`
(not in repo). The PROBE 1 BASELINE empirical run that triggered the
rescope is in the operator's 2026-04-26 acceptance Player.log
(operator-local; key metrics inlined into §Context above).
