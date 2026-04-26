# ADR Decision Record

timestamp: 2026-04-26T02:37:00Z
change: Address PR-13 review findings on ADR 0006, Phase 0-F plan, and design spec
adr_required: false
rationale: "CodeRabbit + Devin + internal code-review combined fix: (1) reorder ADR 0006 sections to match docs/adr/0000-adr-template.md (Alternatives Considered before Consequences) and merge non-template Section-References into Section-Related-Artifacts (matches ADRs 0001-0005); (2) remove copy-paste errors '(this file)' and 'this plan's Task N' pronoun leaks from ADR 0006; (3) normalize in-prose CoQ citations in plan to canonical decompiled/PATH.cs:LINE form including bare-tail expansions; (4) sync embedded ADR template in plan with corrected ADR 0006 ordering; (5) fix Cell.GetCombatTarget signature in spec line 102: return-type Cell to GameObject and parameter Looker to Attacker with corrected parameter list per decompiled/XRL.World/Cell.cs:8511-8558. No ADR re-open required (mechanical compliance)."
files:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
  - docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md
  - docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md
adr_paths:
  - docs/adr/0006-phase-0-f-command-issuance-api-pivot.md
