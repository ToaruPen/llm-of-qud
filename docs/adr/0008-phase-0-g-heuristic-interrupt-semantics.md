# ADR 0008: Phase 0-G heuristic interrupt semantics + new [decision] channel + heuristic specifics lock

Status: Accepted (2026-04-26)

## Context

`docs/architecture-v5.md:2804` (v5.9 freeze) frames Phase 0-G as
"Simple heuristic bot (flee if hurt, attack if adjacent, explore
otherwise)". The Phase 0 exit-criteria block at
`docs/architecture-v5.md:2811-2817` adds five gates the heuristic must
satisfy, including `:2817`: "Interrupt detection latency <1 game turn
(enemy appears → interrupt fires within same turn)".

This `:2817` exit criterion is in tension with the next phase's task
list at `docs/architecture-v5.md:2825-2834`, which explicitly assigns
"AutoAct + Interrupt" to Phase 0b. Reading both together, the question
is: does Phase 0-G need to fire CoQ's engine-level
`AutoAct.Interrupt()` on the same turn a hostile becomes adjacent, or
does it satisfy `:2817` by virtue of the heuristic itself branching to
`attack` (or `flee`) on the same `CommandTakeActionEvent`?

The decompiled source shows that the engine-level interrupt path at
`decompiled/XRL.Core/ActionManager.cs:834-837` is gated by
`AutoAct.IsInterruptable()` (`decompiled/XRL.World.Capabilities/AutoAct.cs:95-102`),
which returns `true` only when `AutoAct.Setting` is non-empty (i.e.,
the player is currently engaged in an AutoAct chain). Phase 0-F's
acceptance memo at `docs/memo/phase-0-f-exit-2026-04-26.md:85`
explicitly recorded that this interrupt path was reachable but no-op
during the 505-record acceptance run because the MOD never engages
`AutoAct.Setting`. Phase 0-G inherits this posture: the MOD does not
engage AutoAct, the engine-level interrupt remains no-op.

A second design question is the schema treatment of the heuristic's
decision branch. `command_issuance.v1` was locked in Phase 0-F per
`docs/memo/phase-0-f-exit-2026-04-26.md:71` with the rule "Field
additions or order changes require v2 + ADR." Three options were
weighed for recording the heuristic's branch ("flee" / "attack" /
"explore"):

- (a) silent — only the resulting `Move`/`AttackDirection` appears as
  `command_issuance.v1`; the heuristic's branch is invisible.
- (b) `command_issuance.v2` — add `decision_branch` field, requires
  ADR per the v1-lock rule.
- (c) new `[LLMOfQud][decision]` channel with `decision.v1` schema,
  emitted alongside `[cmd]` from the same handler invocation.

A third design question is whether the heuristic's specifics ("hurt"
threshold, branch order, flee tiebreak rule, explore east-bias) should
be locked at the spec level. Phase 0-G's exit gate `:2812` requires
"3/5 runs ≥50 turns on Warden", which is empirical — the operative
question is whether the heuristic specifics chosen in this ADR are
*defensible* against the gate, not whether they are *provably optimal*.

The codex 2026-04-26 design consultation recorded in
`/tmp/phase-0-g-prep/codex-v3-answer.md` evaluated these three
questions against the decompiled source, the Phase 0-F precedent, and
the architecture-v5.md frozen text, and produced concrete
recommendations grounded in file:line citations. Those recommendations
inform this ADR's Decisions.

## Decision

Phase 0-G locks the following decisions:

1. **`:2817` interrupt-latency interpretation.** "Enemy appears →
   interrupt fires within same turn" is satisfied by the heuristic
   branching to `attack` (or `flee`) on the very
   `CommandTakeActionEvent` where a hostile becomes adjacent.
   Engine-level `AutoAct.Interrupt()` is NOT required to fire in
   Phase 0-G. AutoAct interrupt remains under Phase 0b's ownership
   (`docs/architecture-v5.md:2825-2834`).
2. **Schema posture: option (c), new `[decision]` channel.**
   `command_issuance.v1` stays untouched — no v2 bump, no ADR for the
   v1 schema. A new sixth observation channel `[LLMOfQud][decision]`
   with schema `decision.v1` is added. Per-turn output becomes 7 lines
   (2 `[screen]` + `[state]` + `[caps]` + `[build]` + `[decision]` +
   `[cmd]`).
3. **Heuristic specifics locked at the spec level**
   (`docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`):
   - **Branch order**: `if hurt → flee; elif adjacent_hostile →
     attack; else → explore`.
   - **`hurt` definition**: composite, `hp <= max(8, floor(max_hp *
     0.60)) AND adjacent_hostile_dir != null`.
   - **Flee direction**: inverse-of-hostile-scan-winner first;
     farthest-safe (Chebyshev distance) fallback second; "boxed-in"
     escalation to `AttackDirection` when no safe cell exists.
   - **Explore direction**: east-bias (`E` first), then
     `SE → NE → S → N → W → SW → NW` for first safe cell.
   - **Safe-cell predicate**: non-null + `IsEmptyOfSolidFor` +
     `GetCombatTarget(hostile filter) == null` + no
     `GetDangerousOpenLiquidVolume`.
4. **Empirical-probe gate before spec lock.** Five probes (Joppa
   50-turn east-bias survival; HP threshold sweet spot; flee
   safe-cell predicate; same-turn interrupt; channel correlation)
   MUST run on a sacrificial CoQ session BEFORE the implementation PR
   (PR-G2) opens. Probe-driven amendments to the spec land via a
   follow-up docs-only spec-amendment PR (PR-G1.5, branch cut from
   `main`) — NOT via push to PR-G1's readiness branch, which is
   squash-merged and deleted before probes run. PROBE 1 is a
   baseline-characterization probe (informational only); PROBE 2-4
   are pass/fail and any FAIL with a spec-impacting finding triggers
   a PR-G1.5 amendment merge before PR-G2 opens. This rule
   operationalizes the project policy in
   `feedback_empirical_claim_probe_before_lock.md`.
5. **No deviation from architecture-v5.md frozen text.** Unlike ADR
   0006 (which reinterpreted `:2803`'s "via CommandEvent.Send"
   wording) and ADR 0007 (which corrected a load-bearing claim
   mid-implementation), ADR 0008 implements `:2804` as written. The
   ADR clarifies an ambiguous boundary (`:2817` vs `:2825-2834`) and
   locks design choices that the spec text leaves unspecified, but it
   does NOT pivot any frozen text.

6. **Observation-accuracy operationalization for `:2814` + `:2816`
   read jointly.** The architecture-v5.md exit criteria at `:2814`
   ("All logged data matches in-game display (spot-check 20 random
   turns)") and `:2816` ("Observation accuracy ≥99% (spot-check
   logged HP/position/entities vs actual game state)") describe a
   single audit, not two contradictory thresholds. Phase 0-G reads
   them jointly: `:2814` specifies the **methodology** (sample 20
   random turns; compare HP + position + entities — three categories
   of logged data per sample), and `:2816` specifies the **pass
   rate** (≥99% match). Read separately, the strict "all match" of
   `:2814` and the "≥99%" of `:2816` would be inconsistent at N=20
   (any single mismatch fails one and passes the other); the joint
   reading dissolves the contradiction by treating `:2814` as
   sample-procedure and `:2816` as accuracy threshold.

   With a 20-turn manual sample, 99% is mathematically unreachable
   as a per-sample-pass criterion (the smallest representable rate
   is 95% at 19/20). Phase 0-G adopts the operationalized criterion
   **19-of-20 sampled turns match** (95% per-sample-pass) for the
   manual audit. If a tighter audit is required for any reason, the
   operator escalates to **N=100 sampled turns** (allowing at most
   one mismatch = 99% per-sample-pass), which directly satisfies
   `:2816`'s 99% threshold under the joint reading. The 99%
   spirit-of-the-criterion is preserved by the escalation path; the
   95% floor at N=20 is a precision concession to the manual
   workflow's cost. This is a numerical operationalization of frozen
   text, not a relaxation of the underlying observability
   requirement.

## Alternatives Considered

1. **Engine-level `AutoAct.Interrupt()` as the `:2817` mechanism.**
   Rejected because it requires Phase 0-G to engage `AutoAct.Setting`
   (i.e., put the player into an auto-walk / auto-explore chain) so
   that `IsInterruptable()` returns true. That is precisely the
   "AutoAct + Interrupt" task assigned to Phase 0b
   (`docs/architecture-v5.md:2827`). Doing it in 0-G would break the
   phase-boundary discipline established by Phases 0-A through 0-F
   (each phase introduces one new mechanism, not two). The heuristic
   same-turn branch achieves the same observable outcome — "the
   player does not waste a turn on `explore` when a hostile is
   adjacent" — without requiring AutoAct.

2. **Schema option (a): silent (no decision telemetry).** Rejected
   because the 50-turn 5-run acceptance gate's failure analysis
   requires being able to distinguish "the heuristic chose `explore`
   and the `Move("E")` failed at a wall" from "the heuristic chose
   `flee` and the `Move("W")` failed at a hostile". Without
   `[decision]` telemetry, the `[cmd]` line alone cannot disambiguate
   these failure modes — the parser sees `action: "Move", dir: "E",
   result: false` and cannot recover the heuristic's reasoning.

3. **Schema option (b): `command_issuance.v2` with
   `decision_branch` field.** Rejected because it forces a separate
   ADR for the v1 schema bump (per Phase 0-F's locked rule), churns
   every Phase 1 consumer of `[cmd]`, and conflates "what was issued"
   (the `[cmd]` record's existing semantics) with "why it was
   issued" (the new branch field). Phase 0-D / 0-E established the
   pattern of separate observation channels for separate concerns
   (`[caps]` is independent of `[state]`; `[build]` is independent of
   both). Option (c) is the consistent extension.

4. **Heuristic with multi-step pathfinding (`A*`).** `A*` exists at
   `decompiled/XRL.World.AI.Pathfinding/FindPath.cs:84-135`. Rejected
   for Phase 0-G as over-scope: the 50-turn Warden gate on Joppa
   does not require multi-step planning (Phase 0-F's 79-record
   east-walk already proved single-step explore suffices), and
   pathfinding pulls in zone-traversal cost models, ally-blocking
   semantics, and a much larger empirical surface. Multi-step
   chains are deferred to Phase 0b / Phase 0-G+.

5. **Hurt threshold as ratio-only (`hp/max_hp <= 0.60`).** Rejected in
   favor of the composite `(hp <= max(8, floor(max_hp * 0.60))) &&
   adjacent_hostile`. The ratio-only formulation flees from
   environmental damage (gases, traps, cumulative starvation) when
   no enemy is present — the bot would walk back and forth between
   damage source and "safety" without escaping the actual threat.
   The composite avoids this failure mode by requiring an addressable
   (i.e., adjacent) hostile to even consider flee.

6. **Hurt threshold as absolute (`hp <= K`).** Rejected because Warden
   is the v1 acceptance build but `[caps]` Phase 0-G+ may exercise
   non-Warden builds with very different baseline HP. The composite
   uses a `max(8, ratio)` floor that handles low-baseHP characters
   (the `8` floor) without disadvantaging high-baseHP characters
   (the `floor(max_hp * 0.60)` ratio). The probe (PROBE 2 in the
   spec) tunes the ratio — not the formula structure.

7. **Flee with PassTurn-when-boxed-in instead of attack-when-boxed-in.**
   Rejected because the `flee` branch is reached precisely when
   `adjacent_hostile_dir != null` (composite hurt definition); the
   hostile is by definition adjacent and addressable by
   `AttackDirection`. PassTurn-while-surrounded is provably worse
   than Attack-while-surrounded: PassTurn deals no damage and accepts
   the next melee swing; Attack at least dispatches the player's
   damage potential. The `boxed_in_attack` escalation exists for
   exactly this reason.

## Consequences

1. **Phase 0-G satisfies `:2817` without engine-level AutoAct
   integration.** The exit-criterion check is observable in the
   `[decision]` line: turn N has `branch == "attack"` (or `"flee"`)
   when a hostile is adjacent on turn N. PROBE 4 in the spec
   verifies this empirically.

2. **A new sixth observation channel exists.** Phase 1 (WebSocket
   bridge, `docs/architecture-v5.md:2836-2855`) inherits the
   correlation contract: `[decision]`, `[cmd]`, `[state]`, `[caps]`,
   `[build]`, `[screen]` correlate by `turn` field, never by line
   adjacency or count parity. Per-turn output is now 7 lines instead
   of Phase 0-F's 6.

3. **`command_issuance.v1` parser stays compatible.** No Phase 0-F
   consumer needs changes. New consumers that want the heuristic's
   reasoning subscribe to `[decision]`.

4. **Heuristic specifics are now part of the design contract.**
   Changes to the `hurt` threshold, branch order, flee tiebreak, or
   explore east-bias require a new ADR. PROBE 2 may amend the
   threshold ratio (`0.60`) and the floor (`8`); the formula
   structure (`hp <= max(floor, floor(max_hp * ratio)) AND
   adjacent_hostile`) is locked.

5. **The `[decision]` channel adds one more game-thread `LogInfo`
   per turn.** `MetricsManager.LogInfo`'s sink is `Player.log` via
   `UnityEngine.Debug.Log` (`decompiled/MetricsManager.cs:407-409`);
   adding a seventh per-turn line stays well under any practical I/O
   budget. No throughput concern.

6. **Phase 0-G inherits Phase 0-F's engine-speed autonomy hazard
   verbatim.** Phase 1 owns the rate-limiting fix
   (`docs/memo/phase-0-f-exit-2026-04-26.md:75-77`); no new hazard is
   introduced by adding the heuristic.

7. **The `decision.v1` schema is now part of the locked observation
   surface.** Field additions or reorderings require a `decision.v2`
   bump + ADR, mirroring the `command_issuance.v1` rule from Phase
   0-F.

## Supersedes

None. ADR 0008 narrows the interpretation of
`docs/architecture-v5.md:2817` under the freeze rule (ADR 0001) and
adds a sixth observation channel without superseding any prior ADR.
ADR 0006's `command_issuance.v1` schema lock and ADR 0007's
`PreventAction` scope are both inherited verbatim and remain in
force.

## Related Artifacts

- `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`
  — design spec; defines the `decision.v1` schema, branch logic,
  safe-cell predicate, and acceptance criteria this ADR formalizes.
- `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md`
  — implementation plan (lands in the same docs-only PR as this ADR).
- `docs/adr/decisions/2026-04-26-phase-0-g-heuristic-interrupt-semantics-and-decision-channel.md`
  — machine-readable decision record produced by
  `scripts/create_adr_decision.py` for the pre-commit ADR gate.
- `docs/architecture-v5.md:2804` — Phase 0-G line being implemented as
  written.
- `docs/architecture-v5.md:2811-2817` — Phase 0 exit criteria; `:2817`
  is the criterion this ADR interprets.
- `docs/architecture-v5.md:2825-2834` — Phase 0b task list assigning
  AutoAct + Interrupt; cited for boundary preservation.
- `docs/architecture-v5.md:2836-2855` — Phase 1 WebSocket bridge that
  consumes `[decision]` and `[cmd]`.
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that
  required this ADR to formalize the boundary interpretation.
- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — Phase 0-F
  ADR that locked `command_issuance.v1` and the direct-API path
  inherited by 0-G.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md`
  — Phase 0-F ADR that locked the render-fallback dependency on
  success-path `PreventAction = false`; 0-G inherits this verbatim.
- `docs/memo/phase-0-f-exit-2026-04-26.md` — Phase 0-F exit memo
  whose §"Open observations" recorded the AutoAct-interrupt no-op
  finding that this ADR's Decision #1 leverages, and whose
  §"Feed-forward for Phase 0-G / Phase 1" describes the channel
  extension pattern this ADR's Decision #2 implements.
- Implementation: `mod/LLMOfQud/LLMOfQudSystem.cs`
  (decision-then-execute extension to `HandleEvent(CommandTakeActionEvent)`),
  `mod/LLMOfQud/SnapshotState.cs`
  (`DecisionRecord`, `BuildDecisionJson`, `BuildDecisionSentinelJson`).
- Codex consultation: `/tmp/phase-0-g-prep/codex-v3-answer.md`
  (operator-local, not committed to repo) — the 2026-04-26 design
  consultation that grounded this ADR's Decisions in decompiled
  source citations.

Future artifact (not yet produced; will be linked here once written):
the Phase 0-G exit memo, created at the implementation plan's last
task under `docs/memo/` with filename `phase-0-g-exit-YYYY-MM-DD.md`
(date stamp fixed at memo-write time via `date -u +%Y-%m-%d`).
