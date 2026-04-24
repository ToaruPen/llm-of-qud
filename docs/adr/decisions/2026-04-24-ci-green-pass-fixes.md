# ADR Decision Record

timestamp: 2026-04-24T14:22:42Z
change: CI green pass fixes
adr_required: false
rationale: Resolve 5 failing CI jobs from initial push: ruff I001/E501/PLR2004 on adr scripts, mypy empty-brain guard via run-mypy.sh, secretlint preset package in npx invocation, markdownlint config disabling noisy rules for memo-style content, and check_adr.rb excluding decision-log.md from ADR filename pattern
files:
  - .github/workflows/ci-security.yml
  - .markdownlint-cli2.jsonc
  - .pre-commit-config.yaml
  - scripts/check_adr.rb
  - scripts/check_adr_decision.py
  - scripts/create_adr_decision.py
  - scripts/run-mypy.sh
  - uv.lock
adr_paths: []
