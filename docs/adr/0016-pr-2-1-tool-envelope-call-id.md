# ADR 0016: PR-2.1 tool envelope call identity

Status: Accepted (2026-04-29)

Amend marker: Amend v5.9

## Context

Frozen v5.9 normalized all WebSocket tools onto the shared
`tool_call` / `tool_result` envelope, but the examples still used
top-level `tid` inside tool envelopes. ADR 0015 then locked PR-2.1 as a
provider-neutral protocol-core slice and named `call_id` as the portable
harness correlation key.

That left a spec contradiction: `tid` is a turn-context identifier, while
PR-2.1 needs a per-tool-call invocation identifier that can map cleanly to
provider-native call IDs without making provider item IDs the transport
contract.

## Decision

PR-2.1 WebSocket `tool_call` and `tool_result` envelopes use required
top-level `call_id` as the canonical per-tool-call invocation identity.

`tool_result.result` is the normalized provider-adapter result object:
`status`, `output`, `error_code`, and `error_message`. Tool-specific
domain payloads live under `result.output`.

Legacy `tid` is not accepted on `tool_call` or `tool_result` envelopes.
There is no backward compatibility path for `tid` in tool envelopes.

`message_id` and `in_reply_to` remain transport correlation and
deduplication fields. They do not replace `call_id` as the invocation
identity.

Turn-level `tid` remains valid outside tool envelopes for turn context,
including `turn_start`, heartbeat messages, confirmation expiry payloads,
and supervisor examples where turn context is needed.

## Alternatives Considered

- Keep accepting `tid` on tool envelopes as a legacy alias. Rejected
  because it would preserve the contradiction and make two identifiers
  appear canonical.
- Use `message_id` / `in_reply_to` as the tool invocation identity.
  Rejected because those fields identify transport messages and reply
  edges, not the logical provider-neutral tool call.
- Globally remove `tid`. Rejected because turn-level messages still need
  stable turn context independent of individual tool invocations.

## Consequences

PR-2.1 schema validation can require `call_id` on every `tool_call` and
`tool_result`, while rejecting `tid` on those envelopes.

Tool-result schema validation can require normalized result fields without
flattening tool-specific payloads into the envelope result object.

Provider adapters can map OpenAI `call_id`, Anthropic `tool_use_id`, or
future provider-native identifiers into the harness `call_id` without
changing the C# WebSocket contract.

Existing docs and tests for turn-level `tid` remain valid where they do
not describe `tool_call` or `tool_result` envelopes.

## Related Artifacts

- `docs/adr/0015-phase-1-pr-2-readiness-scope.md` - PR-2.1
  provider-neutral protocol-core scope.
- `docs/architecture-v5.md:2399-2505` - WebSocket
  `tool_call` / `tool_result` envelope examples.
- `docs/memo/phase-1-pr-2-readiness-precedent-survey-2026-04-29.md`
  - PR-2.1 provider precedent survey and provider-neutral implications.

## Supersedes

None.
