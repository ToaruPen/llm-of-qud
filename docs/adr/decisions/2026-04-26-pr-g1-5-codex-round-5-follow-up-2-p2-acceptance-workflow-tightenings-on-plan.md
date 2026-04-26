# ADR Decision Record

timestamp: 2026-04-26T11:43:11Z
change: PR-G1.5 codex round-5 follow-up: 2 P2 acceptance-workflow tightenings on plan
adr_required: false
rationale: Codex round-5 review on PR-G1.5 flagged 2 more P2 acceptance-workflow defects. Fixed in-PR. (1) Task 7 Step 2 captured each acceptance run via cp of the entire Player.log. Phase 0-D plan explicitly allows multiple runs in a single CoQ launch (quit to main menu, new game, beginTurnCount field resets per-run). cp would copy ALL accumulated runs into runs 2-5's raw-player.log; the validator would compute one run's metrics over cumulative data, and cmd_by_turn / dec_by_turn dict-builds would silently collapse duplicate turn ids — a bad individual run could be hidden by an earlier good one's data. Fix: capture wc -c byte-offset BEFORE each chargen, then slice with tail -c +OFFSET | head -c LEN after the run. Works whether operator quits-to-menu or fully relaunches CoQ between runs. (2) PROBE 3c operator workflow specified 'attempt 3 consecutive turns in the wall direction, observe the 4th decision'. But UpdateBlockedDirsMemory adds dir to BlockedDirs on the FIRST Move failure, and HeuristicPolicy skips any blocked dir on its next Decide call — so the policy is DESIGNED to stop attempting the wall on turn 2, not turn 4. The probe-as-described conflicts with the impl-as-described. Fix: changed PROBE 3c to observe the SECOND decision (1 turn into wall + 1 immediately after). PASS criteria updated to expect ReasonCode='blocked_dir' on the post-bump turn. files: list includes ADR 0009 + spec + plan for branch-cumulative push-mode coverage (rounds 3-4 lesson).
files:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
  - docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
  - docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md
adr_paths:
  - docs/adr/0009-phase-0-g-rescope-judgment-boundary.md
