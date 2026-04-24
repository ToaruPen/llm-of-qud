# AGENTS.md — harness/
# Purpose: Documents what the harness YAML files govern.
# Root rules still apply.

## What lives here

| File | Role |
|------|------|
| `policy.yaml` | ADR trigger policy, approval gates, and change limits. |

## What was NOT copied from the template

- `manifest.yaml` — template intake scaffolding (all TBDs); superseded by frozen `docs/architecture-v5.md`.
- `context-index.yaml`, `review.yaml`, `oracles.yaml`, `rules.yaml` — template-generic scaffolding; no Phase 0 need.
- `capability-profile.yaml`, `compatibility-matrix.yaml` — vendor capability mapping for template rollout; not needed here.
- `projections/` — vendor adapter generation; not needed while CLAUDE.md → AGENTS.md symlink suffices.

## ADR policy

`harness/policy.yaml` documents when an ADR is required (boundary, dependency,
error-policy, fallback, compatibility, security, or performance decisions).
See `docs/adr/` for decision records and `scripts/check_adr.rb` for structural checks.
