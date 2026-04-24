# ADR Decision Record

timestamp: 2026-04-24T14:10:00Z
change: Repo bootstrap push consolidation
adr_required: false
rationale: Pre-push hook validates all triggered files across unpushed commits against the latest decision record; for the initial push of a repo bootstrapped across multiple commits (v5.9 freeze governance + CI tooling), this record unions the trigger sets from 2026-04-23-architecture-v5-9-freeze.md and 2026-04-24-ci-pre-commit-lint-and-branch-protection-tooling.md. Prior records remain as separate audit entries; no new architectural decision is introduced.
files:
  - docs/adr/0000-adr-template.md
  - docs/adr/0001-architecture-v5-9-freeze.md
  - harness/AGENTS.md
  - harness/CLAUDE.md
  - harness/policy.yaml
  - pyproject.toml
  - scripts/AGENTS.md
  - scripts/CLAUDE.md
  - scripts/check_adr.rb
  - scripts/check_adr_decision.py
  - scripts/configure-branch-protection.sh
  - scripts/create_adr_decision.py
adr_paths: []
