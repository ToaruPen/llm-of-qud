# Phase 1 PR-2 Readiness Precedent Survey

Date: 2026-04-29

Status: Readiness memo, not an implementation plan

## Purpose

ADR 0011 requires explicit precedent research before PR-2 locks the
tool-call envelope, prompt-cache posture, and operational message layer.
This memo records the provider precedents that PR-2.1 must respect
without copying any single provider's wire shape into the game protocol.

External provider sources below are official provider documentation
accessed on 2026-04-29. Repo-local sources are cited separately as the
current v5.9 CodexProvider precedent and remain higher priority than
public product docs for this harness.

## OpenAI Responses API Findings

### Function-call shape

OpenAI's Responses API emits function calls as response output items
whose `type` is `function_call`. The call item carries provider-scoped
metadata including `id`, `call_id`, `name`, and JSON `arguments`.
Tool results are sent back as input items whose `type` is
`function_call_output`; the `call_id` must match the model's prior call
and `output` carries the tool result payload.

Implication for PR-2.1: the harness envelope should own its portable
`call_id` correlation and retain OpenAI's `id`, `call_id`, response ID,
and raw output item only as adapter metadata.

Sources:

- OpenAI, "Create a model response", Responses API reference,
  https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAI, "Function calling",
  https://developers.openai.com/api/docs/guides/function-calling
- OpenAI, "Reasoning models", function-calling context guidance,
  https://developers.openai.com/api/docs/guides/reasoning

### Tool-choice and parallel-call controls

OpenAI documents `tool_choice` modes for `none`, `auto`, `required`,
forcing a specific tool, and constraining selection with
`allowed_tools`. The `allowed_tools` mode keeps the full tools list
stable while limiting which tools may be called, which is useful for
prompt-cache stability because tools are part of cacheable prompt prefix
material.

OpenAI also documents `parallel_tool_calls=false` as the way to prevent
multiple function calls in one model turn, yielding exactly zero or one
tool call.

Implication for PR-2.1: start with deterministic sequential terminal
action posture. The internal protocol may represent an array of calls so
parallelism can be added later, but adapters should request zero-or-one
function call initially when a terminal action is expected.

Sources:

- OpenAI, "Function calling",
  https://developers.openai.com/api/docs/guides/function-calling
- OpenAI, "Create a model response", Responses API reference,
  https://developers.openai.com/api/reference/resources/responses/methods/create

### Continuation and local conversation ownership

OpenAI supports `previous_response_id` for server-side continuation.
The frozen architecture already records the critical integration rule:
`previous_response_id` does not inherit instructions, so provider
developer/system instructions must be resent on every continuation request
(`docs/architecture-v5.md:2898-2900`). OpenAI reasoning guidance also
allows either `previous_response_id` or manual re-sending of prior output
items when continuing tool-use reasoning.

The public docs do not clearly state that tool definitions are inherited
through `previous_response_id`. Because tools affect both behavior and
prompt-cache prefix identity, PR-2.1 must resend tool definitions
whenever provider tool use is enabled rather than relying on undocumented
inheritance.

Implication for PR-2.1: the local conversation log is canonical.
Provider continuation IDs are an optimization for cost and reasoning
continuity only; they are not the durable source of game state,
conversation state, or tool availability.

Sources:

- OpenAI, "Conversation state",
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI, "Reasoning models",
  https://developers.openai.com/api/docs/guides/reasoning
- OpenAI, "Text generation",
  https://developers.openai.com/api/docs/guides/text
- `docs/architecture-v5.md:2898-2900`

### Prompt caching

OpenAI prompt caching is automatic for supported recent models once the
cacheable prompt is long enough. Cache hits require exact prefix matches.
The docs recommend placing static content such as instructions, examples,
images, and tools first, with dynamic user-specific content at the end.
They also document `prompt_cache_key` for stable routing and cached-token
usage metrics. The generic prompt-caching guide shows
`usage.prompt_tokens_details.cached_tokens`, while current Responses API
examples show `usage.input_tokens_details.cached_tokens`; PR-2.1 should
record cached-token metrics as provider metadata and verify the actual
field name against the SDK/API response used by the implementation.

For this harness, the stable prefix should be provider instructions,
tool definitions, schema descriptions, and static gameplay rules.
Dynamic game state, current turn observations, and volatile notes belong
after that prefix. The adapter should log cached-token metrics, but the
core game protocol should not know which provider cache mechanism was
used.

Sources:

- OpenAI, "Prompt caching",
  https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI, "Create a model response", Responses API reference,
  https://developers.openai.com/api/reference/resources/responses/methods/create

Note: OpenAI Codex model pages are not used as design authority for
PR-2.1 prompt-cache behavior. They are historical/provider product
context only; the generic prompt-caching and Responses API docs control
the adapter design.

### OpenAI documentation gaps

- Tool-definition inheritance through `previous_response_id` is unclear.
  PR-2.1 should resend tool definitions whenever tool use is enabled.
- Prompt-cache retention terminology varies between in-memory and
  extended retention docs. PR-2.1 should treat retention as
  provider-adapter configuration, not as game-protocol state.
- There is no official Codex loop document that settles
  `previous_response_id` versus stateless unroll for this harness's
  game-loop shape. PR-2.1 should keep both possible by making the local
  conversation log canonical.

## Anthropic Messages API Findings

### Tool-use and tool-result shape

Anthropic represents assistant tool requests as `tool_use` content
blocks. Each block carries `id`, `name`, and structured `input`. Client
tool results are sent in a following user message as `tool_result`
blocks with `tool_use_id`, `content`, and optional `is_error`.

The formatting rules are strict: `tool_result` blocks must immediately
follow the corresponding assistant `tool_use` message in conversation
history, and in the user message the `tool_result` blocks must come
before any text content.

Implication for PR-2.1: the harness envelope should not expose
Anthropic's role/content-block ordering as a game protocol rule.
Anthropic block IDs, raw blocks, and stop reasons should be metadata on
the provider adapter's local conversation record.

Sources:

- Anthropic, "Define tools",
  https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use
- Anthropic, "Handle tool calls",
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls

### Tool-choice and parallel-call controls

Anthropic supports `tool_choice` values `auto`, `any`, `tool`, and
`none`. By default, Claude may use multiple tools in one turn.
`disable_parallel_tool_use=true` constrains `auto` to at most one tool
and constrains `any` or `tool` to exactly one tool.

Implication for PR-2.1: sequential terminal action posture is portable.
The provider-neutral schema can allow multiple calls structurally, but
the initial provider adapters should disable parallel terminal actions by
default.

Sources:

- Anthropic, "Define tools",
  https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use
- Anthropic, "Parallel tool use",
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use

### Prompt caching

Anthropic prompt caching is controlled with `cache_control` breakpoints
over the `tools`, `system`, then `messages` prefix. The default TTL is
5 minutes; a 1-hour TTL is available at additional cost. Anthropic
usage metrics include `cache_creation_input_tokens`,
`cache_read_input_tokens`, `input_tokens`, and a `cache_creation` object
with TTL-specific token counts.

Anthropic's caching docs call out that changes to `tool_choice`, image
usage, and other request features can invalidate cache reuse. Treat
`disable_parallel_tool_use` changes the same way for PR-2.1 because it
changes tool-call behavior and should not vary inside the cacheable
tool-use prefix. Tool-use with prompt caching specifically recommends
caching the tool-definition prefix and understanding what invalidates
that prefix.

Implication for PR-2.1: caching strategy must live in provider adapters.
The core tool-call protocol should expose telemetry fields sufficient to
record cache reads/writes, but it should not encode Anthropic
`cache_control` breakpoints or TTLs as wire-contract requirements.

Sources:

- Anthropic, "Prompt caching",
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Anthropic, "Tool use with prompt caching",
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-use-with-prompt-caching
- Anthropic, "Create a Message",
  https://platform.claude.com/docs/en/api/messages/create

### Errors and truncation

Client tool execution errors are represented as `tool_result` blocks
with `is_error: true`. Stop reasons must be inspected separately from
HTTP errors. Anthropic documents `max_tokens` as a successful stop
reason that may require continuing or retrying with larger `max_tokens`
when the response was truncated.

Implication for PR-2.1: the provider-adapter normalized result payload
needs `status: "ok" | "error"` plus `output`, `error_code`, and
`error_message`, but those fields belong inside the v5.9
`tool_result.result` object on the C# wire. Anthropic maps
`status=error` to `is_error: true`; OpenAI maps it to a
`function_call_output.output` payload that carries the structured error
object.

Sources:

- Anthropic, "Handle tool calls",
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
- Anthropic, "Troubleshooting tool use",
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/troubleshooting-tool-use
- Anthropic, "Handling stop reasons",
  https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons

## Current v5.9 CodexProvider and Wire Envelope Precedent

This repo's frozen v5.9 architecture is the local design authority for
PR-2.1. It defines a Phase 2 `CodexProvider` wrapper as a direct
Responses API client, with multi-provider support deferred because
continuation semantics, caching behavior, and streaming event shapes are
not uniform (`docs/architecture-v5.md:1872-1883`). The tool loop uses
`previous_response_id`, OpenAI-style `call_id` matching, and
`parallel_tool_calls=false`; after `FORCE_ACTION_AFTER`, it constrains
`tool_choice` to state-appropriate terminal actions with
`allowed_tools` (`docs/architecture-v5.md:1885-1962`).

The same pseudocode requires `instructions` on every Responses API call
because `previous_response_id` does not inherit instructions
(`docs/architecture-v5.md:1964-1966`). If a previous response is no
longer available, the loop rebuilds the full context and starts fresh
within the same turn (`docs/architecture-v5.md:1974-1988`). For each
OpenAI `function_call`, it dispatches the requested tool and sends back
a `function_call_output` with the provider `call_id`
(`docs/architecture-v5.md:1991-2003`).

The C# WebSocket wire, however, is not the OpenAI item shape. v5.9
requires Python Brain to emit `tool_call` messages to C# MOD, and C# MOD
to return `tool_result` messages. The `tool_result` has a top-level
`result` object; terminal-action `exec_result` examples are the content
of that `result`, not separate top-level fields
(`docs/architecture-v5.md:2399-2424`). All tools, including Python-owned
knowledge tools, travel through this WebSocket envelope for one
deduplication and telemetry path; for Python-owned notes tools, C# acts
as a transparent relay back to Python's notes endpoint
(`docs/architecture-v5.md:2405-2409`).

Implication for PR-2.1: provider-adapter normalization may use internal
fields such as status, output, error code, and error message, but the
C# wire must preserve the v5.9 top-level `result` field on
`tool_result`. Python tests should model a fake C# client/harness that
receives Python-emitted `tool_call` messages and returns C#-shaped
`tool_result` messages.

Sources:

- `docs/architecture-v5.md:1872-2003`
- `docs/architecture-v5.md:2399-2424`

## Provider-Neutral Implications for PR-2.1

1. The internal WebSocket protocol owns portable call correlation. Use
   `call_id` as the harness correlation key, with provider item IDs,
   response IDs, raw blocks, and stop reasons preserved only as adapter
   metadata.
2. `tool_call` should carry at least `type`, `call_id`, `tool`, `args`,
   `tid`, `message_id`, `session_epoch`, and a provider metadata object
   that may be empty in PR-2.1.
3. `tool_result` should preserve the v5.9 top-level `result` object:
   carry at least `type`, `call_id`, `tool`, `result`, `message_id`,
   `in_reply_to`, `session_epoch`, and provider metadata. The `result`
   object should contain normalized `status`, `output`, `error_code`,
   and `error_message` fields when needed.
4. PR-2.1 should start with sequential terminal action posture:
   parallel provider calls disabled by default, zero-or-one terminal
   action expected per model turn, and multiple calls represented
   structurally for a future ADR rather than executed by default.
5. Prompt caching is an adapter capability, not a core game protocol.
   The shared schema should include telemetry fields for provider cache
   metrics but should not expose OpenAI `prompt_cache_key`, Anthropic
   `cache_control`, or TTL policy on the C# wire.
6. The local conversation log is canonical. Provider continuation IDs
   such as OpenAI `previous_response_id` are optimizations only. They
   can be dropped, invalidated, or regenerated without changing game
   protocol correctness.
7. Provider instructions and tool definitions must be resent when
   provider docs require them, and PR-2.1 must not assume continuation
   IDs carry current instructions or tool availability.
8. `supervisor_request` and `supervisor_response` remain non-tool
   operational messages, matching `docs/architecture-v5.md:2421-2424`.

## PR-2.1 Handoff

The next implementation PR should lock the provider-neutral protocol
core, not a real provider client:

- Add Python schema/message tests before implementation.
- Add C# static contract coverage for the wire envelope and
  `ToolRouter` boundary.
- Extend telemetry only for the fields the new protocol emits.
- Add supervisor message schema and transport tests.
- Defer Phase 2a provider-client execution and PR-3 idempotency.
