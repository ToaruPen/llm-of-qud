# ADR Decision Record

timestamp: 2026-04-26T09:05:49Z
change: Phase 0-G heuristic interrupt semantics + new [decision] channel + heuristic specifics lock
adr_required: true
rationale: Architecture-v5.md :2817 interrupt criterion is satisfied by heuristic same-turn branch interruption (NOT engine-level AutoAct.Interrupt, which remains Phase 0b). New [decision] channel keeps command_issuance.v1 untouched. Branch order, hurt threshold composite formula, flee tiebreak, and explore east-bias are locked.
files:
  - docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
adr_paths:
  - docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
