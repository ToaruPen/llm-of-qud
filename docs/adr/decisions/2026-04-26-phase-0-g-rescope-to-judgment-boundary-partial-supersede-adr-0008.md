# ADR Decision Record

timestamp: 2026-04-26T11:01:36Z
change: Phase 0-G rescope to judgment boundary実証 — partial-supersede ADR 0008
adr_required: true
rationale: PROBE 1 BASELINE empirical run revealed that PR-G1's heuristic-specifics lock optimizes for short-lived implementation tactics (HP threshold, direction priority, escape rules) instead of the closed-loop boundary (observation DTO → judgment policy → terminal action → result feedback) that Phase 1 (WebSocket bridge) and Phase 2+ (LLM brain) actually need. The 'always go east' heuristic literally satisfies :2811-2817 'survive 1000 turns' (9919 turns survived) but is degenerate: 98.7% pass_turn fallback, never demonstrates the judgment slot. ADR 0009 partial-supersedes ADR 0008: keeps Decisions #1, #2, #4-principle, #5, #6 (KISS, in-process Python-free, idempotent, non-interactive, ADR amendment process); supersedes Decision #3 (heuristic specifics) and PROBE 2-4 specifics. New spec lock is the IDecisionPolicy boundary + DecisionInput/Decision DTOs + decision.v1 wire schema. Anti-degeneracy gate (pass_turn_fallback_rate ≤ 20%, successful_terminal_action_rate ≥ 70%, ≥2 distinct intents across 5 runs) operationalizes :2811-2817 to mean 'interact meaningfully' rather than 'spam pass_turn'. Codex APPROVE on the redesign. PR-G1.5 carries ADR 0009 + revised spec + revised plan.
files:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
  - docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
adr_paths:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
