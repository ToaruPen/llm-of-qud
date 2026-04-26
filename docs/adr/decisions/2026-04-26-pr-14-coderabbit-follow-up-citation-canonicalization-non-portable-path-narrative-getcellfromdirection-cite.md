# ADR Decision Record

timestamp: 2026-04-26T07:24:21Z
change: PR-14 CodeRabbit follow-up: citation canonicalization, non-portable path narrative, GetCellFromDirection cite
adr_required: false
rationale: Address CodeRabbit minor findings on PR-F2 (PR-14): (1) ADR 0007 Related Artifacts move /tmp/phase-0-f-acceptance/raw-player-15-05-08.log narrative text (non-portable operator-local path, matches PR-13 follow-up policy on Related Artifacts hygiene); (2) ADR 0007 decision record expand :1806-1808 to decompiled/XRL.Core/ActionManager.cs:1806-1808 (canonical citation); (3) design spec lines 12 and 247 expand bare-tail citations (:838 :1797-1799 :1806-1808 :829-832 :834-837) to full decompiled/XRL.Core/ActionManager.cs:LINE form; (4) mod/LLMOfQud/LLMOfQudSystem.cs:216 add GetCellFromDirection citation comment pointing to decompiled/XRL.World/Cell.cs:7322. Mechanical compliance only; no behavioral or architectural change.
files:
  - docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md
  - docs/adr/decisions/2026-04-26-phase-0-f-adr-0007-scope-e-preventaction-to-abnormal-energy-catch-path-render-fallback-restoration.md
  - docs/superpowers/specs/2026-04-26-phase-0-f-command-issuance-design.md
  - mod/LLMOfQud/LLMOfQudSystem.cs
adr_paths:
  - docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md
