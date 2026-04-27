# ADR Decision Record

timestamp: 2026-04-26T22:39:05Z
change: Phase 0-G heuristic exploration quality declared non-goal — sharpen ADR 0009 Decision #5.4 interpretation, no policy/metric patches
adr_required: true
rationale: Run 5 of Task 7 acceptance produced 99% successful_terminal_action_rate via 2-cell oscillation in a U-shape wall pocket (technically PASS under ADR 0009 §5.4 thresholds). Adding anti-cycle metrics or anti-backtrack policy patches builds a better bot, not a better harness; both are category errors against ADR 0009 §Decision #1 (Phase 0-G deliverable is the IDecisionPolicy boundary, not heuristic quality). Operator reframe: this is an LLM harness foundation, not an autonomous exploration bot. Phase 1 LLM owns exploration quality.
files:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
adr_paths:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
