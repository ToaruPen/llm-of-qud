# ADR Decision Record

timestamp: 2026-04-26T06:30:03Z
change: Phase 0-F ADR 0007 — scope E.PreventAction to abnormal-energy catch path (render-fallback restoration)
adr_required: true
rationale: Empirical 488-turn autonomous run on commit be2e6b2 showed cross-channel parity broken: [cmd]=488, [screen]/[state]/[caps]/[build]=~0x during run. Root cause: success-path finally { E.PreventAction = true; } flips CommandTakeActionEvent.Check to false at decompiled/XRL.Core/ActionManager.cs:829-832, iteration continues, render fallback at :1806-1808 unreachable. ADR 0007: scope PreventAction=true to catch path with post-recovery Energy.Value >= 1000 only; success path leaves PreventAction at default false. ADR 0006 Consequence #3 cadence framing partially superseded (parser correlation by turn retained; per-turn flush is now load-bearing on render fallback :1806-1808).
files:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
  - docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md
  - docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md
  - docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md
adr_paths:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
  - docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md
