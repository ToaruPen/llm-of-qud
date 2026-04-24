# ADR Decision Record

timestamp: 2026-04-24T21:46:02Z
change: Relax approval=0 and last-push-approval=false for solo+CodeRabbit gate
adr_required: false
rationale: GitHub forbids self-approval even with require_last_push_approval=false, so a mandatory human-approval setting deadlocks single-maintainer PRs. Replace human approval with CodeRabbit request_changes_workflow + required_conversation_resolution=true; the latter is now load-bearing for merge gating.
files:
  - docs/ci-branch-protection.md
  - scripts/configure-branch-protection.sh
adr_paths: []
