# ADR Decision Record

timestamp: 2026-04-26T23:21:56Z
change: PR-G2 CodeRabbit follow-up: add :line citations for FindPath (ADR 0010) and AttackDirection/Move (LLMOfQudSystem.cs)
adr_required: false
rationale: CodeRabbit P2 (Major) flagged 2 missing decompiled :line citations: (1) ADR 0010 references decompiled/XRL.World.AI.Pathfinding/FindPath.cs without :line at lines 125 and 252, (2) LLMOfQudSystem.cs invokes player.AttackDirection and player.Move without inline :line comments (Phase 0-F precedent at line 482 already uses 'Mirrors decompiled/.../XRLCore.cs:1108' format). Added FindPath.cs:10 (class declaration), GameObject.cs:17882 (AttackDirection signature), GameObject.cs:15719 (Move signature without out-param overload). The OppositeDir trivial nitpick (return null vs throw ArgumentException) intentionally not adopted: per project policy, no validation for unreachable internal cases.
files:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
  - mod/LLMOfQud/LLMOfQudSystem.cs
adr_paths: []
