# ADR Decision Record

timestamp: 2026-04-26T23:50:02Z
change: PR-G2 CodeRabbit follow-up: canonical citations — replace 259+ with 259-299 + add :10 to FindPath in memo
adr_required: false
rationale: CodeRabbit P2 (Minor) flagged 2 non-canonical citations: (1) ADR 0010 lines 20+256 used '42-46, 259+' open-ended range; replaced with explicit '42-55, 259-299' covering field block (42-55) + UpdateBlockedDirsMemory + LookupBlockedDirsForCell methods (259-299). (2) Phase 0-G exit memo lines 222 + 425 referenced FindPath.cs without :line; added :10 (class declaration) matching ADR 0010 §Decision #5 canonical form. Memo line 183 also updated from '42-46' to '42-55' for consistency.
files:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
  - docs/memo/phase-0-g-exit-2026-04-27.md
adr_paths: []
