# ADR 0001: Architecture v5.9 freeze

Status: Accepted (2026-04-23)

## Context

The `llm-of-qud` architecture was iterated through 5 rounds of Codex review
(v5.4 → v5.9). After the v5.9 review the design was declared stable enough for
Phase 0 implementation. All review memos live under `docs/memo/`.

## Decision

Freeze the architecture at v5.9 (`docs/architecture-v5.md`) for Phase 0
implementation. No spec edits without a new ADR.

## Alternatives Considered

- Continue iteration beyond v5.9 — rejected; reviews converged with no blockers.
- Start implementation without freezing — rejected; risk of spec drift.

## Consequences

- Phase 0-A and 0-A2 plans in `docs/superpowers/plans/2026-04-23-phase-0-a-mod-skeleton.md`
  depend on this frozen spec.
- Agents must not modify `docs/architecture-v5.md` or `docs/superpowers/plans/*.md`.
- Any spec change requires a new ADR before implementation.

## Related Artifacts

- `docs/architecture-v5.md` — frozen spec (v5.9)
- `docs/memo/v5.4-codex-review-2026-04-23.md`
- `docs/memo/v5.5-codex-review-2026-04-23.md`
- `docs/memo/v5.6-codex-review-2026-04-23.md`
- `docs/memo/v5.7-codex-review-2026-04-23.md`
- `docs/memo/v5.8-codex-review-2026-04-23.md`
- `docs/superpowers/plans/2026-04-23-phase-0-a-mod-skeleton.md`

## Supersedes

None
