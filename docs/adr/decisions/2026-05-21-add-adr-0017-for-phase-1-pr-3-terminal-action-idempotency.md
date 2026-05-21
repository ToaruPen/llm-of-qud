# ADR Decision Record

timestamp: 2026-05-21T12:34:57Z
change: Add ADR 0017 for Phase 1 PR-3 terminal action idempotency
adr_required: true
rationale: PR-3 adds a governed terminal-action idempotency plan and implementation for frozen Phase 1 scope; the ADR records the plan authority and mutation-safety contract.
files:
  - brain/app.py
  - brain/protocol.py
  - docs/adr/0017-phase-1-pr-3-terminal-action-idempotency.md
  - mod/LLMOfQud/ToolRouter.cs
  - tests/test_mod_static_contracts.py
adr_paths:
  - docs/adr/0017-phase-1-pr-3-terminal-action-idempotency.md
