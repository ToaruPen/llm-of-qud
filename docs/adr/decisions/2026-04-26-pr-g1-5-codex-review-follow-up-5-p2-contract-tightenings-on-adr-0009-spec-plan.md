# ADR Decision Record

timestamp: 2026-04-26T11:11:06Z
change: PR-G1.5 codex-review follow-up: 5 P2 contract tightenings on ADR 0009 + spec + plan
adr_required: false
rationale: Codex final-approval review (run before PR-G1.5 merge) flagged 5 P2 contract issues that would cause the post-merge implementation to violate the newly defined judgment boundary or fail to compile. Fixed in-PR rather than amending post-merge. (1) plan:567 used hostileObj.id where MOD convention is .ID — non-canonical though both compile. (2) plan catch-path pseudocode unconditionally set Energy.BaseValue = 0, violating ADR 0007's energy-guarded layered drain (BaseValue reset is last-ditch only when Energy.Value >= 1000 after PassTurn recovery; PassTurn at decompiled/XRL.World/GameObject.cs:17543, Statistic.Value at decompiled/XRL.World/Statistic.cs:238, Statistic.BaseValue at decompiled/XRL.World/Statistic.cs:218, Cell.GetCellFromDirection at decompiled/XRL.World/Cell.cs:7322, Cell.IsEmptyOfSolidFor at decompiled/XRL.World/Cell.cs:5290). (3) spec described RecentHistory as 'bounded; last K turns ≥3' but the actual fields only carry single-turn snapshot; PROBE 3c is satisfied by adjacent.blocked_dirs[] accumulation, not Recent. Removed misleading K≥3 phrasing and made the satisfaction path explicit. (4) spec's 'NOT spec-locked' allowed safe-cell predicate detail (Cell.GetCellFromDirection / IsEmptyOfSolidFor / GetCombatTarget / GetDangerousOpenLiquidVolume) inside HeuristicPolicy.Decide, contradicting criterion 1's input-only boundary. Removed the discretion bullet, locked the boundary explicitly, and documented that richer signals require decision_input.v2 + new ADR. (5) spec allowed intent enum extensions under same decision.v1 — wire-contract laxity that would break Phase 1 consumers. Locked intent + reason_code wire enums; extensions require decision.v2 + new ADR. ADR 0009 Decision #7 was also tightened to match.
files:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
  - docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
adr_paths:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
