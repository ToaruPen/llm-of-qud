# ADR Decision Record

timestamp: 2026-04-29T05:16:27Z
change: Add ADR 0016 for PR-2.1 tool envelope call_id identity
adr_required: true
rationale: Frozen architecture-v5 tool envelope examples conflicted with PR-2.1 call_id implementation; ADR 0016 amends v5.9 to make call_id the canonical tool invocation identity and reject legacy tid on tool envelopes.
files:
  - brain/app.py
  - docs/adr/0016-pr-2-1-tool-envelope-call-id.md
  - docs/architecture-v5.md
  - docs/memo/phase-1-pr-2-readiness-precedent-survey-2026-04-29.md
  - mod/LLMOfQud/BrainClient.cs
  - mod/LLMOfQud/ToolRouter.cs
  - tests/test_brain_app.py
  - tests/test_mod_static_contracts.py
  - tests/test_protocol_messages.py
adr_paths:
  - docs/adr/0016-pr-2-1-tool-envelope-call-id.md
