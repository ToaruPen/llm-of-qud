# ADR Decision Record

timestamp: 2026-04-26T02:12:01Z
change: Phase 0-F command-issuance API pivot from CommandEvent.Send to direct Move/AttackDirection
adr_required: true
rationale: CommandEvent.Send has no registered handler for CmdMoveE/CmdAttackE; engine itself dispatches via direct GameObject.Move/AttackDirection in XRLCore.PlayerTurn(). Hook is CommandTakeActionEvent (not BeginTakeActionEvent) to keep the inner action loop's bookkeeping intact.
files:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
adr_paths:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
