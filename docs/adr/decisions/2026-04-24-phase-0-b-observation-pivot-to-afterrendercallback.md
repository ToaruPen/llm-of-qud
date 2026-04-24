# ADR Decision Record

timestamp: 2026-04-24T23:43:02Z
change: Phase 0-B observation pivot to AfterRenderCallback
adr_required: true
rationale: ConsoleChar.Copy drops BackupChar; only Zone.Render source buffer (via XRLCore.RegisterAfterRenderCallback) preserves tile-mode ASCII
files:
  - docs/adr/0002-phase-0-b-render-callback-pivot.md
  - docs/adr/decision-log.md
  - docs/adr/decisions/2026-04-24-phase-0-b-observation-pivot-to-afterrendercallback.md
  - mod/LLMOfQud/LLMOfQudSystem.cs
adr_paths:
  - docs/adr/0002-phase-0-b-render-callback-pivot.md
