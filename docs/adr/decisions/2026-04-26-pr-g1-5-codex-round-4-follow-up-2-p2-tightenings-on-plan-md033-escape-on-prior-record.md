# ADR Decision Record

timestamp: 2026-04-26T11:35:26Z
change: PR-G1.5 codex round-4 follow-up: 2 P2 tightenings on plan + MD033 escape on prior record
adr_required: false
rationale: Codex round-4 review on PR-G1.5 flagged 2 more P2 implementation-plan defects. Fixed in-PR. (1) plan:685-692 — Execute pseudocode applied the Layer-2 PassTurn drain only after a failed Move; a failed AttackDirection (e.g., target moved, paralyzed, invalid dir) would fall through with energy >= 1000, triggering PreventAction and breaking the inherited 3-layer drain / render-cadence posture. Restructured to apply the !result && !energySpent drain check uniformly after BOTH terminal actions, mirroring the Phase 0-F LLMOfQudSystem.cs:288-300 shape exactly. (2) plan:1037-1039 — Task 7 Step 5 invoked /tmp/phase-0-g-acceptance/validate.py before any step actually wrote it (prior version put the validator inline as a python3 stdin heredoc in Step 4, never persisted; the trailing operator note 'copy the heredoc body' was easy to miss). Step 4 now writes the validator to disk via cat-redirected heredoc first, then runs it once for smoke; Step 5's loop reuses the same file. Operator-note removed (no longer needed). Also: amended round-2 follow-up record to escape HashSet&lt;string&gt;/List&lt;string&gt; as HTML entities — markdownlint MD033 was flagging the raw angle brackets as inline HTML. files: list includes ADR 0009 + spec + plan to satisfy push-mode branch-cumulative gate coverage (round-3 lesson) — only the plan file content changed in THIS commit's diff; the others are listed for cumulative-coverage purposes.
files:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
  - docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
adr_paths:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
