# ADR Decision Record

timestamp: 2026-04-26T09:11:51Z
change: PR-15 markdown-lint follow-up: MD037 + MD029 fixes on ADR 0008 + Phase 0-G plan
adr_required: false
rationale: CI markdown-lint failures on docs-only PR-G1 readiness PR. ADR 0008 line 175 had bare A* outside backticks (MD037 emphasis space). Plan PROBE 3 step 4 was renumbered as 4 after a paragraph break inside a nested list (MD029). Both fixed without altering technical content.
files:
  - docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
adr_paths:
  - docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
