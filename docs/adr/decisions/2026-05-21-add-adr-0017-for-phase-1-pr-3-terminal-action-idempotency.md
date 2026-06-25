# ADR Decision Record

timestamp: 2026-05-21T12:34:57Z
change: Add ADR 0017 for Phase 1 PR-3 terminal action idempotency
adr_required: true
rationale: PR-3 adds a governed terminal-action idempotency plan and implementation for frozen Phase 1 scope; the ADR records the plan authority and mutation-safety contract.
files:
  - brain/app.py:347-389
  - brain/protocol.py:17-21
  - docs/adr/0017-phase-1-pr-3-terminal-action-idempotency.md:1-113
  - mod/LLMOfQud/ToolRouter.cs:51-112
  - mod/LLMOfQud/ToolRouter.cs:1088-1093
  - tests/test_mod_static_contracts.py:471-500
adr_paths:
  - docs/adr/0017-phase-1-pr-3-terminal-action-idempotency.md:1
