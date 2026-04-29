# Phase 1 PR-2 Protocol Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement PR-2.1 protocol core: provider-neutral
`tool_call` / `tool_result`, `ToolRouter` boundary, error/retry envelope,
supervisor messages, and telemetry fields needed for those docs.

**Architecture:** Keep PR-1's WebSocket boundary intact and add a
provider-neutral message layer above it. Python owns provider mapping
and local conversation state; Python emits `tool_call` messages to C#,
and C# owns game-tool dispatch and returns `tool_result` messages with a
top-level `result` object. Provider-specific IDs, response IDs, raw
blocks, cache metrics, and continuation IDs remain metadata, never the
core game protocol.

**Tech Stack:** C# in `mod/LLMOfQud/`; Python 3.13 with uv, pydantic,
websockets, aiosqlite, pytest, and existing static-contract tests.

---

## Scope Locks

- Implement PR-2.1 only. Do not implement code in this docs-readiness
  PR.
- Do not edit `docs/architecture-v5.md`.
- Do not edit existing approved plans.
- Do not implement PR-3 / Phase 1-G idempotency: no `action_nonce`
  cache, no `state_version` stale enforcement, no duplicate-result
  cache, and no stale `session_epoch` enforcement.
- Do not implement Phase 2a provider client execution. No live OpenAI,
  Anthropic, or Codex API call is part of PR-2.1.
- Do not make terminal actions parallel by default. Represent multiple
  calls structurally only; dispatch terminal actions sequentially.
- Preserve frozen v5.9 wire direction and shape:
  Python Brain -> C# MOD `tool_call`; C# MOD -> Python Brain
  `tool_result` with top-level `result`.

## File Ownership

**Python tests first:**

- Modify or extend: `tests/test_brain_app.py`
- Modify or extend: `tests/test_brain_db.py`
- Create: `tests/test_protocol_messages.py` for protocol schema and
  fake C# harness tests used by the targeted PR-2.1 commands.

**Python implementation:**

- Modify: `brain/app.py` — WebSocket message parsing, provider-adapter
  mapping, Python emission of `tool_call`, and intake of C#-shaped
  `tool_result`.
- Modify: `brain/db/schema.py` — telemetry tables/columns for protocol
  core events.
- Modify: `brain/db/writer.py` — telemetry writer methods.
- Create only if justified by test readability and ADR 0015:
  `brain/protocol.py` for pydantic schemas and provider-neutral
  message helpers.

**C# tests first:**

- Modify: `tests/test_mod_static_contracts.py`

**C# implementation:**

- Modify: `mod/LLMOfQud/BrainClient.cs` — transport of envelope
  messages if current PR-1 direct decision transport needs a protocol
  wrapper.
- Modify: `mod/LLMOfQud/WebSocketPolicy.cs` — bridge from PR-1
  `DecisionInput` / `Decision` to PR-2 tool call/result flow.
- Create if planned by the task: `mod/LLMOfQud/ToolRouter.cs` —
  dispatch named tool calls to handlers without provider-specific logic.

## Task 1: Python Provider-Neutral Schema and Message Tests

**Files:**

- Test: `tests/test_brain_app.py`
- Create test: `tests/test_protocol_messages.py`
- Modify: `brain/app.py`
- Optional create: `brain/protocol.py`

- [ ] **Step 1: Write failing tests for schema parsing**

  Add tests that parse a minimal `tool_call`, an error `tool_result`
  with top-level `result`, and provider metadata without exposing
  OpenAI or Anthropic fields as top-level protocol requirements.

  Required assertions:

  - `tool_call.call_id` is required and stable.
  - `tool_result.result.status` accepts only `ok` or `error`.
  - `tool_result.result.status == "error"` requires
    `result.error_code` and `result.error_message`.
  - Provider metadata is optional and round-trips as a nested object.
  - Multiple calls can be represented as a list but are not dispatched
    in parallel.

- [ ] **Step 2: Run the failing targeted tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k 'tool_call or tool_result or protocol' -q
  ```

  Expected: FAIL because PR-2.1 protocol schemas do not exist yet.

- [ ] **Step 3: Implement minimal Python schemas**

  Implement provider-neutral pydantic models in `brain/app.py` or
  `brain/protocol.py`:

  - `ToolCallMessage`
  - `ToolResultMessage`
  - `ToolResultPayload`
  - `ProviderMetadata`
  - `ToolResultStatus`

  Keep OpenAI `response_id` / `item_id` / raw item and Anthropic
  `tool_use_id` / raw blocks inside provider metadata only.

- [ ] **Step 4: Run targeted tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k 'tool_call or tool_result or protocol' -q
  ```

  Expected: PASS.

## Task 2: C# Wire Envelope and Static Contracts

**Files:**

- Test: `tests/test_mod_static_contracts.py`
- Modify: `mod/LLMOfQud/BrainClient.cs`
- Modify: `mod/LLMOfQud/WebSocketPolicy.cs`
- Create: `mod/LLMOfQud/ToolRouter.cs` if routing is implemented as a
  dedicated class.

- [ ] **Step 1: Write failing static-contract tests**

  Add tests that inspect C# source for:

  - `ToolRouter` dispatch boundary.
  - No OpenAI-specific `function_call` or Anthropic-specific
    `tool_use` as C# protocol top-level fields.
  - `tool_call` includes `call_id`, `tool`, `args`, `message_id`, and
    `session_epoch`.
  - `tool_result` includes `call_id`, top-level `result`,
    `message_id`, and `in_reply_to`.
  - `result` includes normalized `status`, `output`, `error_code`, and
    `error_message` when applicable.
  - Terminal-action parallel dispatch is not enabled by default.

- [ ] **Step 2: Run failing C# static-contract tests**

  Run:

  ```bash
  uv run pytest tests/test_mod_static_contracts.py -q
  ```

  Expected: FAIL on missing PR-2.1 protocol contracts.

- [ ] **Step 3: Implement minimal C# envelope contracts**

  Add the smallest C# structures/helpers needed for source-level static
  checks and PR-1 bridge compatibility. Keep JSON construction patterns
  consistent with existing `SnapshotState` helpers. Do not add PR-3
  idempotency behavior.

- [ ] **Step 4: Run C# static-contract tests**

  Run:

  ```bash
  uv run pytest tests/test_mod_static_contracts.py -q
  ```

  Expected: PASS.

## Task 3: Python Tool-Call Emission and Fake C# Harness Boundary

**Files:**

- Test: `tests/test_brain_app.py`
- Test: `tests/test_protocol_messages.py`
- Modify: `brain/app.py`
- Optional create: `brain/protocol.py`

- [ ] **Step 1: Write failing fake C# harness tests**

  Add async tests that model Python as the tool-call emitter and a fake
  C# client/harness as the responder. Python sends `tool_call` over the
  local WebSocket; the fake C# side returns a matching `tool_result`
  with the same `call_id`, `in_reply_to`, and top-level `result`.

  Include cases for:

  - Fake C# returns unknown-tool failure as `result.status: "error"`
    with `result.error_code: "unknown_tool"`.
  - Fake C# returns malformed-args failure as `result.status: "error"`
    with a deterministic validation code.
  - Python does not dispatch game tools locally except provider-adapter
    mapping and the explicit v5.9 notes relay path.
  - A list containing more than one terminal action is rejected or
    serialized before emission, not executed in parallel.

- [ ] **Step 2: Run failing fake-harness tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k 'fake_csharp or emit_tool_call or unknown_tool or terminal' -q
  ```

  Expected: FAIL until Python tool-call emission and C#-shaped result
  intake exist.

- [ ] **Step 3: Implement minimal emission/result-intake path**

  Extend `brain/app.py` so PR-1 direct decision input still works, while
  PR-2.1 provider-adapter mapping emits `tool_call` messages to C# and
  accepts C# `tool_result` messages. Keep provider-client calls out of
  scope. Keep Python-side local handling limited to adapter mapping and
  the v5.9 notes relay if that relay is included in PR-2.1.

- [ ] **Step 4: Run targeted fake-harness tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k 'fake_csharp or emit_tool_call or unknown_tool or terminal' -q
  ```

  Expected: PASS.

## Task 4: Telemetry Schema and Writer Updates

**Files:**

- Test: `tests/test_brain_db.py`
- Modify: `brain/db/schema.py`
- Modify: `brain/db/writer.py`

- [ ] **Step 1: Write failing telemetry tests**

  Extend DB tests to require rows for:

  - tool call sent/received with `call_id`, `tool`,
    `result_status`, and `latency_ms`.
  - provider metadata fields for `provider_name`, `provider_response_id`,
    `provider_item_id`, and cache token counters.
  - supervisor request/response telemetry.
  - error/retry classification fields.

- [ ] **Step 2: Run failing telemetry tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_db.py -q
  ```

  Expected: FAIL until schema and writer methods exist.

- [ ] **Step 3: Implement schema and writer methods**

  Add tables or columns with stable names. Keep provider cache metrics
  nullable and adapter-owned. Do not require OpenAI or Anthropic
  metadata in the core writer API.

- [ ] **Step 4: Run telemetry tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_db.py -q
  ```

  Expected: PASS.

## Task 5: Supervisor Message Schema and Transport Tests

**Files:**

- Test: `tests/test_brain_app.py`
- Test: `tests/test_protocol_messages.py`
- Modify: `brain/app.py`
- Modify: `mod/LLMOfQud/BrainClient.cs`
- Modify or create as needed: `mod/LLMOfQud/ToolRouter.cs`

- [ ] **Step 1: Write failing supervisor schema tests**

  Assert that `supervisor_request` and `supervisor_response` are
  non-tool messages with their own `message_id` and `session_epoch`.
  They must not use `tool_call` / `tool_result`, and they must preserve
  prompt/choice payloads needed for human-in-the-loop escalation.

- [ ] **Step 2: Run failing supervisor tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k supervisor -q
  ```

  Expected: FAIL until supervisor schema support exists.

- [ ] **Step 3: Implement supervisor schema and local transport**

  Add schema parsing and local transport handling only. Do not implement
  overlay UI or human controls beyond the message contract.

- [ ] **Step 4: Run supervisor tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py -k supervisor -q
  ```

  Expected: PASS.

## Task 6: Integration, Static Verification, and Runtime Acceptance Notes

**Files:**

- Modify tests only as required by Tasks 1-5.
- Create: `docs/memo/phase-1-pr-2-1-acceptance-YYYY-MM-DD.md` after
  PR-2.1 implementation runs.

- [ ] **Step 1: Run targeted tests**

  Run:

  ```bash
  uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py tests/test_brain_db.py tests/test_mod_static_contracts.py -q
  ```

  Expected: PASS.

- [ ] **Step 2: Run full Python tests**

  Run:

  ```bash
  uv run pytest tests/
  ```

  Expected: PASS.

- [ ] **Step 3: Run repository hooks**

  Run:

  ```bash
  pre-commit run --all-files
  ```

  Expected: PASS.

- [ ] **Step 4: Run ADR checks if any ADR/docs/adr files changed**

  Run:

  ```bash
  ruby scripts/check_adr.rb
  python3 scripts/check_adr_decision.py --mode staged
  ```

  Expected: PASS when staged files include the required ADR decision
  record.

- [ ] **Step 5: Record runtime acceptance notes**

  Write `docs/memo/phase-1-pr-2-1-acceptance-YYYY-MM-DD.md` with:

  - test commands and results;
  - no-LLM round-trip result for the provider-neutral envelope;
  - confirmation that terminal actions remained sequential;
  - explicit deferral of PR-3 idempotency and Phase 2a provider-client
    execution.

## Verification Commands for PR-2.1

Run these before requesting review:

```bash
uv run pytest tests/test_brain_app.py tests/test_protocol_messages.py tests/test_brain_db.py tests/test_mod_static_contracts.py -q
uv run pytest tests/
pre-commit run --all-files
ruby scripts/check_adr.rb
python3 scripts/check_adr_decision.py --mode staged
```
