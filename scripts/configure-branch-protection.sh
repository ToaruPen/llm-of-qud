#!/usr/bin/env bash
# configure-branch-protection.sh
# Applies branch protection rules to the main branch of the llm-of-qud repo.
#
# Prerequisites:
#   - gh CLI installed and authenticated (gh auth login)
#   - Repo must already be pushed to GitHub
#
# Usage:
#   bash scripts/configure-branch-protection.sh
#
# Dry-run (inspect payload without applying):
#   DRY_RUN=1 bash scripts/configure-branch-protection.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve repo identifier
# ---------------------------------------------------------------------------
REPO="$(gh repo view --json nameWithOwner -q '.nameWithOwner')"
echo "Configuring branch protection for: ${REPO} (branch: main)"

# ---------------------------------------------------------------------------
# Build JSON payload
# ---------------------------------------------------------------------------
# Required status checks: branch protection requires the aggregator job name
# "required-checks-gate" (from .github/workflows/required-checks-gate.yml).
# The context string is the job name as it appears in GitHub Checks UI.
PAYLOAD="$(cat <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {
        "context": "required-checks-gate",
        "app_id": -1
      }
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "require_last_push_approval": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "lock_branch": false,
  "block_creations": false
}
JSON
)"

# ---------------------------------------------------------------------------
# Apply or dry-run
# ---------------------------------------------------------------------------
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN=1: would send the following payload to PUT /repos/${REPO}/branches/main/protection"
  echo "${PAYLOAD}" | python3 -m json.tool
  exit 0
fi

echo "${PAYLOAD}" | gh api \
  -X PUT \
  "repos/${REPO}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  --input -

echo ""
echo "Branch protection applied successfully."
echo ""
echo "Note: signed commits (require_signed_commits) is a separate API endpoint."
echo "To ENABLE required signed commits:"
echo "  gh api -X POST \"repos/${REPO}/branches/main/protection/required_signatures\" \\"
echo "    -H 'Accept: application/vnd.github+json'"
echo ""
echo "To DISABLE required signed commits:"
echo "  gh api -X DELETE \"repos/${REPO}/branches/main/protection/required_signatures\" \\"
echo "    -H 'Accept: application/vnd.github+json'"
echo ""
echo "Current recommendation: keep signed commits OPTIONAL at Phase 0."
echo "Enable once all contributors have GPG/SSH commit signing configured."
