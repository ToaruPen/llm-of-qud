# ADR Decision Record

timestamp: 2026-04-24T13:54:50Z
change: CI pre-commit, lint, and branch-protection tooling
adr_required: false
rationale: Wire secretlint/semgrep/pre-commit/GitHub workflows and branch-protection helper alongside pyproject.toml and editor/build configs; no architectural change, so adr_required=false
files:
  - .coderabbit.yaml
  - .editorconfig
  - .github/CODEOWNERS
  - .github/ISSUE_TEMPLATE/bug.md
  - .github/ISSUE_TEMPLATE/decision.md
  - .github/ISSUE_TEMPLATE/phase.md
  - .github/dependabot.yml
  - .github/pull_request_template.md
  - .github/workflows/ci-cs.yml
  - .github/workflows/ci-docs-and-governance.yml
  - .github/workflows/ci-python.yml
  - .github/workflows/ci-security.yml
  - .github/workflows/pre-commit.yml
  - .github/workflows/required-checks-gate.yml
  - .gitignore
  - .pre-commit-config.yaml
  - .secretlintignore
  - .secretlintrc.json
  - .vulture_whitelist.py
  - Directory.Build.props
  - decompiled/Directory.Build.props
  - harness/CLAUDE.md
  - pyproject.toml
  - pyrightconfig.json
  - scripts/CLAUDE.md
  - scripts/configure-branch-protection.sh
  - semgrep.yml
adr_paths: []
