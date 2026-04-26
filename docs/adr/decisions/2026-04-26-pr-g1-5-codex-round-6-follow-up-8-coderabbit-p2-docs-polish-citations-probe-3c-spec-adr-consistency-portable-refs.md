# ADR Decision Record

timestamp: 2026-04-26T11:58:45Z
change: PR-G1.5 codex round-6 follow-up: 8 CodeRabbit P2 docs polish — citations + PROBE 3c spec/ADR consistency + portable refs
adr_required: false
rationale: CodeRabbit posted 8 unresolved review threads on PR-G1.5. Per user instruction (address findings before merge): (1) Cite decompiled CoQ sources adjacent to API references in spec lines 33-89 (HandleEvent/Move/AttackDirection/PassTurn/Statistic) and ADR 0009 boundary clauses. IDecisionPolicy is a new mod-internal interface (no decompiled equivalent — explicitly noted). (2) Spec PROBE 3c said '3 consecutive turns / 4th decision' but UpdateBlockedDirsMemory adds dir to blocked_dirs on the FIRST failure and HeuristicPolicy.Decide skips blocked dirs on its next call — so the policy switches on turn 2, not turn 4. R5 fixed the plan; this round fixes the spec AND ADR 0009 to match (1 turn into wall + observe SECOND decision, reason_code='blocked_dir' on post-bump turn). (3) ADR 0009 :2812 → :2811-2817 (R0 record line 6) per canonical line-range citation rule. (4) ADR 0009:289-293 /tmp/phase-0-g-prep/codex-redesign-answer.md → 'operator-local working note (intentionally not committed)' for repo-portability. (5) R1 record line 6 added inline citations for PassTurn/Energy/Cell APIs named in the rationale. Skipped: decision.v1 → v2 bump (CodeRabbit suggestion rejected — ADR 0009:241-247 already explains why fresh v1 stands; no Phase 1 consumer has built against the prior shape, no compatibility owed). MD033 on R2 record line 6: already escaped in R4 commit (HashSet&lt;string&gt; / List&lt;string&gt;). PROBE 3c on plan: already fixed in R5. files: list includes ADR 0009 + spec + plan for branch-cumulative push-mode coverage (rounds 3-5 lesson).
files:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
  - docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
adr_paths:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
