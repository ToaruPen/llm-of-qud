# AGENTS.md — docs/
# Purpose: Access rules and conventions for the docs/ directory.
# Root rules still apply; this file adds docs-specific constraints.

## Frozen Files (DO NOT MODIFY)

| File | Status |
|------|--------|
| `docs/architecture-v5.md` | Frozen at v5.9. Read-only for all agentic workers. |
| `docs/superpowers/plans/*.md` | Frozen once approved. Do not edit without explicit user instruction. |

If a spec inconsistency is detected, stop and report with explicit file:line references.
Do not silently resolve contradictions.

## Spec Navigation

| Section | Lines | Content |
|---------|-------|---------|
| C# MOD Design | 1710-1829 | Component table, event system, safety gate, thread routing |
| Python Brain Design | 1831-1920 | Directory layout, tool-loop constants, Codex API client |
| Streaming Overlay | 2249-2361 | Screen layout, overlay JSON schema, mode values |
| Phase Plan | 2720+ | Phase 0-H tasks, exit criteria |

## Memo Naming Convention

Files in `docs/memo/` use:
```
<topic>-<YYYY-MM-DD>.md
```
Examples: `v5.9-codex-review-2026-04-23.md`, `phase-0-a-exit-2026-04-23.md`

## Plan Workflow

To write a new plan, use the `superpowers:writing-plans` skill.
Plans live under `docs/superpowers/plans/` with filename:
```
<YYYY-MM-DD>-<phase-or-topic>-<short-title>.md
```

## Research Files

`docs/research/` holds reference research (CoQ API behavior, streaming infra, etc.).
These are informational; they do not override `docs/architecture-v5.md`.

## ADR Workflow

Architectural decisions are recorded in `docs/adr/`.

| File | Role |
|------|------|
| `docs/adr/0000-adr-template.md` | Template for new ADRs |
| `docs/adr/decision-log.md` | Append-only index of decision records |
| `docs/adr/decisions/` | Machine-readable decision records (one per ADR-triggering change) |

To create a new ADR decision record:
```
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Short description" \
  --rationale "Why this decision was made" \
  --adr docs/adr/NNNN-title.md
```

ADR triggers: changes to `scripts/`, `harness/`, `docs/adr/`, `pyproject.toml`, `package.json`
require a decision record. The pre-commit and pre-push hooks enforce this via
`scripts/check_adr_decision.py`. See `harness/policy.yaml` for the full trigger policy.

## Future sections

<!-- Phase 0-B: add plan file reference when 0-B plan is written -->
<!-- Phase 1: add WebSocket protocol spec reference -->
