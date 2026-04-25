# ADR Decision Record

timestamp: 2026-04-25T14:30:00Z
change: Correct DeathLogger / cross-run learning citation from :1683-1687 to :1696-1710
adr_required: false
rationale: PR #11 code review flagged that docs/architecture-v5.md:1683-1687 cited as "DeathLogger / cross-run learning" actually contains Layer 2 note_evidence counter rules. The real DeathLogger / cross-run learning content (Layer 3 Cross-Run Knowledge, death_events + encounter_log, Phase 3+ gate) is at :1696-1710. Citation-only fix; no semantic change to the ADR, spec, or plan decisions.
files:
  - docs/adr/0005-phase-0-e-current-build-state-pivot.md
  - docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md
  - docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md
adr_paths: []
