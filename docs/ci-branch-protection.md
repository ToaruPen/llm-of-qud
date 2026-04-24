# CI & Branch Protection — Operator Guide

This document describes the GitHub Actions CI setup for `llm-of-qud` and explains how to
configure branch protection rules once the repo is pushed to GitHub.

---

## Required Status Checks

Branch protection is configured to require **one aggregator check**:

| Check name | Source |
|---|---|
| `required-checks-gate` | `.github/workflows/required-checks-gate.yml` → job `gate` |

The `gate` job fans out to the following leaf workflows via `workflow_call`:

| Leaf workflow | Job(s) inside | Purpose |
|---|---|---|
| `ci-python.yml` | `lint-python`, `typecheck-python`, `test-python` | ruff, basedpyright, mypy strict, pytest |
| `ci-cs.yml` | `lint-cs` | Roslyn analyzers on netstandard2.0 side projects (Phase 0: skips if no .csproj) |
| `ci-docs-and-governance.yml` | `markdown-lint`, `adr-checks`, `harness-lint`, `frozen-file-guard` | Docs quality + ADR + frozen-spec guard |
| `ci-security.yml` | `secret-scan` | secretlint + semgrep |
| `pre-commit.yml` | `pre-commit-meta` | Full-tree pre-commit run as defense-in-depth |

### Why a single aggregator?

`needs:` only works within one workflow file. The aggregator (`required-checks-gate.yml`)
is the **only** file with `pull_request` / `push` triggers. All leaf workflows use
`on: workflow_call` only, preventing double-runs.

---

## Apply Branch Protection

### Prerequisites

1. Repo pushed to GitHub: `git remote add origin git@github.com:ToaruPen/llm-of-qud.git && git push -u origin main`
2. `gh` CLI installed and authenticated: `gh auth login`
3. **Trigger a CI run first.** GitHub cannot require a status check that has never reported.
   Push a test commit or open a draft PR to main so `required-checks-gate` appears at least once
   in the Checks list. Then run the protection script.

### Run the configuration script

```bash
# Inspect payload without applying
DRY_RUN=1 bash scripts/configure-branch-protection.sh

# Apply
bash scripts/configure-branch-protection.sh
```

### Equivalent `gh api` command (manual)

```bash
REPO="$(gh repo view --json nameWithOwner -q '.nameWithOwner')"

gh api \
  -X PUT "repos/${REPO}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -F required_status_checks='{"strict":true,"checks":[{"context":"required-checks-gate","app_id":-1}]}' \
  -F enforce_admins=true \
  -F required_pull_request_reviews='{"dismiss_stale_reviews":true,"require_code_owner_reviews":false,"require_last_push_approval":true,"required_approving_review_count":1}' \
  -F restrictions=null \
  -F required_conversation_resolution=true \
  -F allow_force_pushes=false \
  -F allow_deletions=false
```

> **Note:** Nested JSON objects like `required_status_checks` must be passed as a single
> JSON string with `-F` (not with individual flags). The `configure-branch-protection.sh`
> script uses `--input -` to pipe the full JSON body for reliability.

---

## Protection Settings Summary

| Setting | Value | Rationale |
|---|---|---|
| `required_status_checks.strict` | `true` | Branch must be up-to-date before merging |
| Required check | `required-checks-gate` | Single aggregator = single required name |
| `enforce_admins` | `true` | Admins must also go through PR flow |
| `required_approving_review_count` | `1` | At least one human approval |
| `dismiss_stale_reviews` | `true` | New commits invalidate prior approval |
| `require_code_owner_reviews` | `false` | CODEOWNERS populated later; enable when ready |
| `require_last_push_approval` | `true` | Prevents self-approval after final push |
| `allow_force_pushes` | `false` | Protect commit history |
| `allow_deletions` | `false` | Protect main from accidental deletion |
| `required_conversation_resolution` | `true` | All review threads must be resolved |

---

## Signed Commits

Require signed commits is a **separate** API endpoint and is **not** included in the
main protection payload above. It is **not enabled** at Phase 0.

Enable when all contributors have GPG or SSH signing configured:

```bash
REPO="$(gh repo view --json nameWithOwner -q '.nameWithOwner')"

# Enable required signed commits
gh api -X POST "repos/${REPO}/branches/main/protection/required_signatures" \
  -H "Accept: application/vnd.github+json"

# Disable required signed commits
gh api -X DELETE "repos/${REPO}/branches/main/protection/required_signatures" \
  -H "Accept: application/vnd.github+json"

# Check current status
gh api "repos/${REPO}/branches/main/protection/required_signatures" \
  -H "Accept: application/vnd.github+json" | jq '.enabled'
```

---

## CodeRabbit

CodeRabbit is configured via `.coderabbit.yaml` (SaaS integration). It does **not** run
as a GitHub Action and there is no `.github/workflows/coderabbit.yml`. CodeRabbit appears
in the PR review UI automatically once the GitHub App is installed on the repo.

To enable: visit [coderabbit.ai](https://coderabbit.ai) → install GitHub App →
select `ToaruPen/llm-of-qud`.

---

## Frozen-file Guard

`docs/architecture-v5.md` is frozen at spec version v5.9.

Any PR that modifies this file will fail the `frozen-file-guard` CI job unless the PR
body contains the literal string `Amend v5.9`.

To bypass intentionally, add this to your PR description:

```
Amend v5.9: <reason for amendment>
```

---

## Verify Protection is Applied

```bash
REPO="$(gh repo view --json nameWithOwner -q '.nameWithOwner')"
gh api "repos/${REPO}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" | jq '{
    required_status_checks: .required_status_checks.checks,
    enforce_admins: .enforce_admins.enabled,
    pr_reviews: .required_pull_request_reviews,
    allow_force_pushes: .allow_force_pushes.enabled,
    allow_deletions: .allow_deletions.enabled,
    required_conversation_resolution: .required_conversation_resolution.enabled
  }'
```

---

## Dependabot

Dependency updates are configured in `.github/dependabot.yml`:

| Ecosystem | Directory | Cadence |
|---|---|---|
| `github-actions` | `/` | Weekly (Monday) |
| `uv` (Python) | `/brain` | Weekly (Monday) |
| `nuget` (C#) | `/mod` | Weekly (Monday — no-ops if no .csproj) |
