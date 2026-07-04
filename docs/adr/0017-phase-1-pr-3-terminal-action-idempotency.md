# ADR 0017: Phase 1 PR-3 terminal action idempotency

Status: Accepted (2026-05-21)

Amend marker: Amend v5.9

## Context

ADR 0015 locked PR-2.1 as the provider-neutral protocol-core slice and
explicitly deferred terminal-action idempotency to PR-3. ADR 0016 then
clarified `call_id` as the canonical tool invocation identity for the
`tool_call` / `tool_result` envelope.

Frozen v5.9 still requires terminal action safety before provider-backed
tool execution becomes load-bearing. Terminal actions such as `execute`,
`navigate_to`, and `choose` can mutate the game state, so duplicate
transport delivery, stale provider responses, or cross-session replay
must not execute a second game action.

The PR-3 plan records the implementation details in
`docs/superpowers/plans/2026-04-29-phase-1-pr-3-terminal-action-idempotency.md`.
Because plan files are governed artifacts, this ADR records the decision
that authorizes the PR-3 plan and implementation scope without editing
`docs/architecture-v5.md`.

## Decision

Phase 1 PR-3 implements terminal action idempotency for exactly these
terminal tools:

- `execute`
- `navigate_to`
- `choose`

Terminal `tool_call` messages carry:

- `action_nonce`: a Python Brain generated per-action idempotency key.
- `state_version`: the decision-turn state version the action applies to.
- `snapshot_hash`: the SHA-256 hash of the exact decision-input JSON bytes,
  carried inside terminal tool arguments.

C# computes the expected `state_version` and `snapshot_hash` from the
outbound decision input before it accepts a terminal action. `ToolRouter`
rejects terminal actions that are missing idempotency fields, use a stale
`session_epoch`, target a stale state version, present a mismatched
snapshot hash, or duplicate a completed terminal state version.

C# caches terminal results by transport `message_id` and by
`session_epoch:action_nonce`. Replayed duplicate requests return the
cached result instead of executing another terminal action.

Non-terminal tools keep the PR-2.1 envelope shape and do not require
`action_nonce`, `state_version`, or `snapshot_hash`.

## Alternatives Considered

- **Use only `message_id` for duplicate suppression.** Rejected because
  provider retries can arrive as a new transport message for the same
  logical terminal action. `action_nonce` is the logical idempotency key.
- **Use only `call_id` for duplicate suppression.** Rejected because
  `call_id` identifies the provider-neutral tool invocation, not the
  terminal-action execution attempt across reconnects and transport
  retries.
- **Apply idempotency fields to every tool.** Rejected because PR-3 only
  needs mutation safety for terminal actions. Read-only and operational
  tools should not inherit unnecessary required fields.
- **Allow parallel terminal actions now.** Rejected for turn coherence.
  Terminal action dispatch remains sequential until a future ADR defines
  ordering and conflict semantics.

## Consequences

Easier:

- Duplicate terminal delivery is safe across transport message replay and
  provider retry surfaces.
- The Python Brain can detect mismatched terminal results by `action_nonce`.
- Telemetry can record terminal idempotency fields and acceptance status
  for later replay analysis.

Harder:

- Terminal action probes must provide a current `snapshot_hash` when they
  exercise `execute`, `navigate_to`, or `choose`.
- A dedicated adversarial in-game probe is still needed if runtime evidence
  for each rejection branch is required; the PR-3 E2E run covers the
  happy path, while automated tests cover duplicate and stale branches.

Re-open triggers:

- If provider adapters need parallel terminal action emission before
  Phase 2a Gate 1.
- If `snapshot_hash` over exact JSON bytes proves unstable across the
  C# and Python boundary in a supported runtime.
- If terminal tools are added or reclassified beyond `execute`,
  `navigate_to`, and `choose`.

## Related Artifacts

- `docs/superpowers/plans/2026-04-29-phase-1-pr-3-terminal-action-idempotency.md`
  - PR-3 implementation plan.
- `docs/memo/phase-1-pr-3-e2e-acceptance-2026-04-30.md` - PR-3
  happy-path E2E acceptance memo.
- `docs/adr/0015-phase-1-pr-2-readiness-scope.md` - PR-2.1 scope and
  PR-3 idempotency deferral.
- `docs/adr/0016-pr-2-1-tool-envelope-call-id.md` - tool envelope
  invocation identity.
- `docs/architecture-v5.md:2634-2677` - terminal action idempotency and
  stale-response requirements.

## Supersedes

None.
