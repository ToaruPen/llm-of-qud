# AGENTS.md — scripts/
# Purpose: Rules for automation scripts in this directory.
# Root rules still apply.

## Secret Scanning

All commits run `npx secretlint .` via pre-commit hook.
Never commit credentials, tokens, or API keys. If secretlint fails, fix before retrying.

## ADR Scripts (active)

| Script | Purpose |
|--------|---------|
| `scripts/create_adr_decision.py` | Create a new ADR decision record and append to decision-log.md |
| `scripts/check_adr_decision.py` | Gate: verify staged/pushed files have a matching decision record |
| `scripts/check_adr.rb` | Structural check of docs/adr/*.md (requires ruby) |

These are invoked by `.githooks/pre-commit` and `.githooks/pre-push`.

## CI & Governance Scripts (added)

| Script | Purpose |
|--------|---------|
| `scripts/configure-branch-protection.sh` | Apply GitHub branch protection rules to `main` via `gh api`. Run manually after pushing repo to GitHub. Supports `DRY_RUN=1`. |

## Planned Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| `scripts/check-mod.sh` | Verify CoQ log for successful mod compile | Planned Phase 0-A2 |
| `scripts/launch-brain.sh` | Start Python Brain server | Planned Phase 1 |
| `scripts/verify-overlay.sh` | Smoke test overlay output | Planned Phase 2 |

Do not add scripts outside this table without updating this file.

## Style

- Bash scripts: `#!/usr/bin/env bash`, `set -euo pipefail`
- Python scripts: use `uv run` for isolation
- No hardcoded absolute paths; use env vars or relative paths from repo root

## Future sections

<!-- Phase 0-A2: add check-mod.sh usage instructions -->
<!-- Phase 1: add launch-brain.sh and environment variable documentation -->
<!-- CI: GitHub Actions configured — see .github/workflows/ and docs/ci-branch-protection.md -->
