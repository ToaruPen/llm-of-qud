# ADR Decision Record

timestamp: 2026-04-26T23:15:12Z
change: PR-G2 markdown-lint follow-up: MD018 fix on ADR 0010 (line-wrap '#5.4' off line start)
adr_required: false
rationale: GitHub Actions markdown-lint flagged MD018/no-missing-space-atx on ADR 0010 line 39 because '#5.4' fell at the start of a line after a soft wrap, causing the linter to interpret it as an empty-spaced ATX heading. Re-wrapped the paragraph so '#5.4' sits mid-line. No semantic change.
files:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
adr_paths: []
