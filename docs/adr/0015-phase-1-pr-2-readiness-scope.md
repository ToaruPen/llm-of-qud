# ADR 0015: Phase 1 PR-2 readiness scope — provider-neutral protocol core

Status: Accepted (2026-04-29)

Amend marker: Amend v5.9

## Context

ADR 0011 split frozen v5.9 Phase 1 into PR-1, PR-2, and PR-3 without
editing `docs/architecture-v5.md`. PR-1 proved the WebSocket boundary
and plumbing. PR-2 is the next slice and inherits the v5.9 requirements
for the `tool_call` / `tool_result` request-response envelope,
`ToolRouter.cs`, error/retry infrastructure, and
`supervisor_request` / `supervisor_response`
(`docs/architecture-v5.md:2399-2424`,
`docs/architecture-v5.md:2840-2864`).

ADR 0011 also added a forward-looking rule for PR-2: the tool-call
envelope and prompt-cache strategy are harness-core surfaces and must
be surveyed against current provider precedent before any plan or ADR
locks the shape (`docs/adr/0011-phase-1-pr-1-scope.md:160-193`).

The 2026-04-29 precedent survey confirms that OpenAI and Anthropic have
different provider-native shapes, and that frozen v5.9 already defines a
repo-local CodexProvider/tool-loop precedent:

- OpenAI Responses API uses `function_call` output items and
  `function_call_output` input items correlated by provider `call_id`.
- Anthropic Messages API uses assistant `tool_use` blocks and user
  `tool_result` blocks correlated by `tool_use_id`.
- Both providers support disabling parallel tool calls, but the knobs
  and guarantees differ.
- Both providers have prompt caching, but OpenAI uses automatic prefix
  caching plus request routing controls while Anthropic uses explicit or
  automatic `cache_control` breakpoints over `tools`, `system`, and
  `messages`.
- v5.9's CodexProvider precedent is OpenAI-shaped inside the provider
  adapter, but the C# WebSocket wire remains Python `tool_call` to C#
  and C# `tool_result` to Python with top-level `result`
  (`docs/architecture-v5.md:1872-2003`,
  `docs/architecture-v5.md:2399-2424`).

Copying either provider shape directly into the C# WebSocket protocol
would leak adapter assumptions into the game harness. PR-2 therefore
needs a provider-neutral protocol core first.

ADR 0012 consumed the next ADR number after ADR 0011 and explicitly
renumbered the deferred PR-1 backfill ADRs: ADR 0013 is reserved for
async `IDecisionPolicy.Decide` threading, and ADR 0014 is reserved for
disconnect=pause plus reconnect wake. Those PR-1 backfill ADRs remain
deferred. This readiness ADR intentionally uses ADR 0015.

## Decision

Lock PR-2.0 as docs-only readiness. PR-2.0 creates the precedent survey,
this ADR, the PR-2.1 implementation plan, and the required ADR decision
record. It does not edit implementation files.

Lock PR-2.1 as the protocol-core implementation slice. PR-2.1 may
implement only these surfaces:

1. A provider-neutral `tool_call` / `tool_result` envelope used by the
   WebSocket protocol, preserving v5.9's Python-to-C# `tool_call` and
   C#-to-Python `tool_result` direction. `tool_result` keeps top-level
   `result`; normalized status/output/error details live inside
   `result` or provider-adapter metadata.
2. A C# `ToolRouter` boundary that routes named tool calls to handlers
   without binding the protocol to OpenAI or Anthropic item formats.
3. An error/retry envelope sufficient for provider-neutral tool errors,
   transport failures, timeout classification, and output truncation
   classification.
4. `supervisor_request` / `supervisor_response` transport and schema as
   non-tool operational messages.
5. Telemetry fields needed by the protocol, error/retry, and supervisor
   messages above, including provider cache metrics as optional adapter
   metadata.

PR-2.1 must keep the local conversation log canonical. Provider
continuation IDs, including OpenAI `previous_response_id`, are
optimizations only and must not become the durable source of game state,
conversation state, or tool availability.

PR-2.1 must resend provider instructions and tool definitions whenever
provider docs require or leave inheritance undocumented. In particular,
do not assume `previous_response_id` carries current instructions or
tool definitions.

PR-2.1 must start with sequential terminal action posture. Terminal
actions must not be parallel by default. The schema may represent
multiple tool calls structurally so a later ADR can enable safe
parallelism, but PR-2.1 adapters, Python emission/intake code, and C#
routing must preserve zero-or-one terminal action execution.

PR-2.1 must defer PR-3 / Phase 1-G terminal-action idempotency:
`action_nonce`, `state_version`, duplicate-result cache, stale
`state_version` enforcement, and stale `session_epoch` enforcement
remain out of scope except where docs cite them as future envelope
extensions. PR-2.1 may keep `session_epoch` as an existing routing field
on every message; it must not implement stale-epoch idempotency behavior.

ADR 0013 and ADR 0014 are deferred PR-1 backfill numbers and are
intentionally skipped by this PR.

## Alternatives Considered

1. **Implement OpenAI Responses API shape directly in the WebSocket
   protocol.** Rejected because it would make provider `function_call`
   item IDs, `call_id`, and `function_call_output` payload conventions
   load-bearing for C# MOD logic before Phase 2a provider-client work.
2. **Implement Anthropic Messages API shape directly in the WebSocket
   protocol.** Rejected because Anthropic's assistant/user content-block
   ordering rules are provider conversation-history rules, not game
   transport rules.
3. **Include PR-3 idempotency in PR-2.1.** Rejected because
   ADR 0011 already split PR-2 envelope/ops from PR-3 idempotency, and
   v5.9 makes Phase 1-G a hard prerequisite before Phase 2a Gate 1,
   not before PR-2 protocol-core review.
4. **Make terminal actions parallel-ready by default.** Rejected for
   game-turn coherence. Both surveyed providers expose ways to constrain
   parallel tool calls, and `docs/architecture-v5.md:3162` already locks
   sequential tool calling for game turn coherence.
5. **Treat prompt caching as a core protocol feature.** Rejected because
   OpenAI and Anthropic cache controls differ. The core protocol should
   record cache telemetry and preserve stable prompt-prefix ordering in
   provider adapters, not encode provider cache knobs on the C# wire.

## Consequences

Easier:

- PR-2.1 can be reviewed as a transport/schema slice before real
  provider execution enters in Phase 2a.
- C# MOD and Python Brain share a provider-neutral correlation model.
- The protocol can retain provider raw IDs and blocks for debugging
  without making them the public harness contract.
- Prompt-cache experiments can happen inside provider adapters without
  changing the C# WebSocket message schema.

Harder:

- PR-2.1 must write more adapter-mapping tests because provider-native
  shapes are intentionally not the wire contract, and fake C# harness
  tests are needed to keep Python emission direction honest.
- The telemetry schema must allow optional provider metadata while
  keeping the core protocol deterministic.
- PR-3 must still implement terminal-action idempotency before Phase 2a
  Gate 1.

Re-open triggers:

- If PR-2.1 cannot satisfy the v5.9 no-LLM round-trip exit criterion
  with the provider-neutral envelope
  (`docs/architecture-v5.md:2862-2864`), this ADR must be revisited
  before Phase 2a opens.
- If provider docs later specify tool-definition inheritance through
  continuation IDs clearly enough to make resend materially harmful,
  provider adapters may revisit their resend behavior under a new ADR.
- If terminal action parallelism becomes necessary before Phase 2a
  Gate 1, a new ADR must define coherence, ordering, and retry
  semantics before enabling it.

## Supersedes

None. This ADR is additive and sequences PR-2.0 / PR-2.1. It does not
supersede ADR 0011, ADR 0012, or the deferred ADR 0013 / ADR 0014
backfills.

## Related Artifacts

- `docs/memo/phase-1-pr-2-readiness-precedent-survey-2026-04-29.md`
  — provider precedent survey for OpenAI Responses API and Anthropic
  Messages API.
- `docs/superpowers/plans/2026-04-29-phase-1-pr-2-protocol-core.md`
  — PR-2.1 implementation plan.
- `docs/adr/0011-phase-1-pr-1-scope.md` — PR cascade and PR-2
  precedent-research requirement.
- `docs/adr/0012-phase-1-pr-1-plan-hotfix-probe-set-revision.md` —
  renumbers the deferred PR-1 backfill ADRs to 0013 / 0014.
- `docs/architecture-v5.md:2399-2424` — frozen v5.9 WebSocket envelope
  and supervisor message baseline.
- `docs/architecture-v5.md:1872-2003` — current v5.9 CodexProvider and
  Responses API tool-loop precedent.
- `docs/architecture-v5.md:2840-2864` — frozen Phase 1 task list and
  no-LLM round-trip exit criterion.
