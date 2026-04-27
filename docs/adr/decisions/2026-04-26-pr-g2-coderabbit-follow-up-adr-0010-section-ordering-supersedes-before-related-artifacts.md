# ADR Decision Record

timestamp: 2026-04-26T23:32:39Z
change: PR-G2 CodeRabbit follow-up: ADR 0010 section ordering (Supersedes before Related Artifacts)
adr_required: false
rationale: Per project ADR convention (PR-15 CodeRabbit precedent for ADR 0008), Supersedes section must precede Related Artifacts even though the docs/adr/0000-adr-template.md template places Related Artifacts first. ADR 0010 originally followed the template literally; reordered to match project convention. ADR 0009 already conforms (Supersedes at line 260, Related Artifacts at line 276). The CodeRabbit second finding (decision record needs Related Artifacts section) is a false positive — decision records under docs/adr/decisions/ use a frontmatter-only format (timestamp/change/adr_required/rationale/files/adr_paths), not prose markdown sections. Verified against the existing decision record corpus.
files:
  - docs/adr/0010-phase-0-g-heuristic-exploration-quality-non-goal.md
adr_paths: []
