# ADR Decision Record

timestamp: 2026-04-26T02:47:30Z
change: PR-13 follow-up: spec citation canonicalization and ADR 0006 future-artifact placeholder fix
adr_required: false
rationale: Address two remaining CodeRabbit findings on PR-13: (1) MAJOR finding on docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md - normalize all in-prose CoQ API citations from bare-tail shorthand (':NNN-NNN' / 'ActionManager.cs:NNN' / 'Statistic.cs:NNN' etc.) to canonical full decompiled/PATH.cs:LINE form throughout (lines 5, 9-13, 147, 149, 154, 168, 179, 181, 242-247, 251, 262, 270-281); (2) MINOR finding on ADR 0006 - replace placeholder docs/memo/phase-0-f-exit-YYYY-MM-DD.md path inside Related Artifacts list with explicit 'Future artifact (not yet produced)' note outside the artifact list, mirroring the same change in the plan's embedded ADR template. No ADR re-open required (mechanical compliance).
files:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
  - docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md
  - docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md
adr_paths:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
