# ADR Decision Record

timestamp: 2026-04-25T13:59:06Z
change: Phase 0-E pivot from BirthBuildProfile to current build state
adr_required: true
rationale: check_status (architecture-v5.md:443-468) consumes CURRENT attributes/level/hunger/thirst, not birth-time values; literal Birth capture would ship dead code
files:
  - docs/adr/0005-phase-0-e-current-build-state-pivot.md
adr_paths:
  - docs/adr/0005-phase-0-e-current-build-state-pivot.md
