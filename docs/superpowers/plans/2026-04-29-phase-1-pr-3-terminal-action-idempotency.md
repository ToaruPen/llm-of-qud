# Phase 1 PR-3 Terminal Action Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Phase 1-G terminal-action idempotency so duplicate or stale terminal tool calls cannot double-execute before Phase 2a.

**Architecture:** PR-3 extends the PR-2 provider-neutral `tool_call` / `tool_result` envelope without changing provider-specific adapter semantics. Python validates and emits terminal-action idempotency fields; C# parses them, rejects stale terminal actions, and returns cached terminal `tool_result` envelopes for duplicate `(session_epoch, action_nonce)` calls. Non-terminal tools keep the PR-2 shape and are not deduplicated in this slice.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, websockets 16.0, SQLite via aiosqlite, Roslyn-compatible C# source under `mod/LLMOfQud/`.

---

## Source of Truth

- `docs/architecture-v5.md:2411-2424` defines the normalized `tool_call` / `tool_result` envelope and says terminal actions include top-level `action_nonce` and `state_version`.
- `docs/architecture-v5.md:2486-2516` shows the terminal action example and the terminal result output contract.
- `docs/architecture-v5.md:2863-2877` defines Phase 1-G: cache by `(session_epoch, action_nonce)`, reject stale `state_version`, reject stale `session_epoch`, minimum terminal-action `message_id` dedup, duplicate turn suppression, and defer non-terminal deduplication to Phase 2b.
- `docs/architecture-v5.md:2905-2909` makes Phase 1-G a hard prerequisite before Phase 2a Gate 1.
- `docs/adr/0011-phase-1-pr-1-scope.md:85-89` says PR-3 requires no new ADR because v5.9 carries the contract.
- `docs/adr/0015-phase-1-pr-2-readiness-scope.md:94-99` confirms PR-2 intentionally deferred this behavior.

## File Structure

- Modify `brain/protocol.py`: add optional top-level `action_nonce` and `state_version` to `ToolCallMessage`, add optional top-level `action_nonce` to `ToolResultMessage`, plus an `is_terminal_action_tool()` helper and after-validation requiring both call-side fields only for `execute`, `navigate_to`, and `choose`.
- Modify `brain/app.py`: make probe terminal tool calls include deterministic `action_nonce`, `state_version`, and `args.snapshot_hash` derived from the exact decision-input JSON received by the probe server.
- Modify `brain/db/schema.py`: add nullable terminal-idempotency telemetry columns to `tool_call_sent` and `tool_call_received`, plus migrations for existing PR-2 DBs.
- Modify `brain/db/writer.py`: accept and persist terminal idempotency telemetry without making non-terminal writes pass extra arguments.
- Modify `mod/LLMOfQud/ToolRouter.cs`: parse terminal idempotency fields, enforce session/state guards, cache terminal results keyed by `(session_epoch, action_nonce)`, and return cached results on duplicate calls.
- Modify `mod/LLMOfQud/BrainClient.cs`: update the long-lived `ToolRouter` with the current `decision_input.v1.turn` before processing tool calls. PR-3 uses the current turn as the Phase 1 state-version approximation until `turn_start.state_version` exists on the live wire.
- Modify tests: `tests/test_protocol_messages.py`, `tests/test_brain_app.py`, `tests/test_brain_db.py`, and `tests/test_mod_static_contracts.py`.

## Locked Semantics

- Terminal tools are exactly `execute`, `navigate_to`, and `choose`; `cancel_or_back` remains non-terminal in PR-3.
- A duplicate terminal action with the same `(session_epoch, action_nonce)` returns the previously cached `tool_result` envelope. It does not call the handler again.
- A duplicate terminal `message_id` returns the previously cached `tool_result` envelope for that message. This is the minimum terminal-action `message_id` dedup scope required by v5.9; non-terminal `message_id` dedup remains Phase 2b.
- Duplicate cached results preserve the original `result.output`; `message_id` and `in_reply_to` may be regenerated to match the duplicate request's transport edge.
- A second terminal action for an already-completed state version with a different nonce is rejected with `acceptance_status == "duplicate"`.
- A stale `state_version` terminal action returns `result.status == "ok"` with `result.output.acceptance_status == "stale"` and `accepted == false`.
- A terminal action whose `args.snapshot_hash` does not match the current decision-input snapshot hash returns `result.status == "ok"` with `result.output.acceptance_status == "stale"` and `accepted == false`.
- Terminal `tool_result` envelopes echo the terminal `action_nonce` at top level, matching `docs/architecture-v5.md:2517`.
- A stale `session_epoch` terminal action returns `result.status == "ok"` with `result.output.acceptance_status == "stale_epoch"` and `accepted == false`.
- Non-terminal tool calls may include no `action_nonce` / `state_version`; PR-3 does not add non-terminal deduplication.
- In Phase 1 PR-3 live transport, `state_version` maps to the current `decision_input.v1.turn`, and `snapshot_hash` maps to a deterministic hash of the exact `decision_input.v1` JSON. Frozen v5.9's `turn_start.state_version` / `turn_start.snapshot_hash` remain the future richer sources once `turn_start` is introduced on the WebSocket wire.
- No Phase 2a provider client, real game action execution, pathfinding, or LLM call is introduced.

## Task 1: Python Protocol Fields

**Files:**
- Modify: `brain/protocol.py`
- Test: `tests/test_protocol_messages.py`

- [ ] **Step 1: Write failing protocol tests**

Add these tests to `tests/test_protocol_messages.py`:

```python
def test_terminal_tool_call_requires_action_nonce_and_state_version() -> None:
    base_message: JsonObject = {
        "type": "tool_call",
        "call_id": "turn-7-call-1",
        "tool": "execute",
        "args": {"candidate_id": "c1"},
        "message_id": "msg-7-call-1",
        "session_epoch": 3,
    }

    with pytest.raises(ValidationError, match="action_nonce"):
        ToolCallMessage.model_validate(base_message)
    with pytest.raises(ValidationError, match="state_version"):
        ToolCallMessage.model_validate(base_message | {"action_nonce": "nonce-7"})

    message = ToolCallMessage.model_validate(
        base_message | {"action_nonce": "nonce-7", "state_version": 284},
    )

    assert message.action_nonce == "nonce-7"
    assert message.state_version == 284


def test_non_terminal_tool_call_does_not_require_terminal_idempotency_fields() -> None:
    message = ToolCallMessage.model_validate(
        {
            "type": "tool_call",
            "call_id": "turn-7-call-1",
            "tool": "inspect_surroundings",
            "args": {},
            "message_id": "msg-7-call-1",
            "session_epoch": 3,
        },
    )

    assert message.action_nonce is None
    assert message.state_version is None


def test_terminal_tool_result_can_echo_action_nonce() -> None:
    message = ToolResultMessage.model_validate(
        {
            "type": "tool_result",
            "call_id": "turn-7-call-1",
            "tool": "execute",
            "result": {"status": "ok", "output": {"acceptance_status": "accepted"}},
            "message_id": "msg-7-result-1",
            "in_reply_to": "msg-7-call-1",
            "session_epoch": 3,
            "action_nonce": "nonce-7",
        },
    )

    assert message.action_nonce == "nonce-7"
```

- [ ] **Step 2: Run protocol tests to verify RED**

Run:

```bash
uv run pytest tests/test_protocol_messages.py -k 'terminal_tool_call_requires_action_nonce or non_terminal_tool_call or terminal_tool_result_can_echo_action_nonce' -q
```

Expected: FAIL because `ToolCallMessage` has no `action_nonce` / `state_version` fields and `ToolResultMessage` has no `action_nonce` field.

- [ ] **Step 3: Implement minimal protocol validation**

In `brain/protocol.py`, add:

```python
TERMINAL_ACTION_TOOLS = frozenset({"execute", "navigate_to", "choose"})


def is_terminal_action_tool(tool: str) -> bool:
    return tool in TERMINAL_ACTION_TOOLS
```

Then extend `ToolCallMessage`:

```python
class ToolCallMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_type: Literal["tool_call"] = Field(default="tool_call", alias="type")
    call_id: str
    tool: str
    args: JsonObject
    message_id: str
    session_epoch: int
    action_nonce: str | None = None
    state_version: int | None = None
    metadata: ProviderMetadata | None = None

    @model_validator(mode="after")
    def require_terminal_idempotency_fields(self) -> Self:
        if not is_terminal_action_tool(self.tool):
            return self
        if self.action_nonce is None:
            raise ValueError("terminal tool_call requires action_nonce")
        if self.state_version is None:
            raise ValueError("terminal tool_call requires state_version")
        return self
```

Then extend `ToolResultMessage`:

```python
class ToolResultMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_type: Literal["tool_result"] = Field(default="tool_result", alias="type")
    call_id: str
    tool: str
    result: ToolResultPayload
    message_id: str
    in_reply_to: str
    session_epoch: int
    action_nonce: str | None = None
    metadata: ProviderMetadata | None = None
```

- [ ] **Step 4: Run protocol tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_protocol_messages.py -k 'terminal_tool_call_requires_action_nonce or non_terminal_tool_call or terminal_tool_result_can_echo_action_nonce' -q
```

Expected: PASS.

## Task 2: Python Probe Emission and Round Trip

**Files:**
- Modify: `brain/app.py`
- Test: `tests/test_brain_app.py`

- [ ] **Step 1: Write failing terminal emission tests**

Add these tests to `tests/test_brain_app.py`:

```python
@pytest.mark.asyncio
async def test_terminal_tool_call_probe_includes_action_nonce_and_state_version() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(
        phase="tool_call_probe:execute",
    )

    assert tool_call["tool"] == "execute"
    assert tool_call["action_nonce"] == "turn-7-execute-nonce"
    assert tool_call["state_version"] == 7
    assert isinstance(tool_call["args"]["snapshot_hash"], str)
    assert response["schema"] == "decision.v1"


def test_terminal_tool_call_batch_uses_deterministic_nonce_and_state_version() -> None:
    (message,) = build_tool_call_messages(
        [{"tool": "execute", "args": {"candidate_id": "c1"}, "call_id": "call-1"}],
        turn=7,
        session_epoch=3,
        snapshot_hash="snapshot-7",
    )

    assert message.action_nonce == "turn-7-execute-nonce"
    assert message.state_version == 7
    assert message.args["snapshot_hash"] == "snapshot-7"
```

- [ ] **Step 2: Run app tests to verify RED**

Run:

```bash
uv run pytest tests/test_brain_app.py -k 'terminal_tool_call_probe_includes_action_nonce or terminal_tool_call_batch' -q
```

Expected: FAIL because `build_tool_call_messages()` does not set terminal idempotency fields.

- [ ] **Step 3: Implement deterministic probe fields**

In `brain/app.py`, import `hashlib` and `is_terminal_action_tool` from `brain.protocol`. Add a snapshot hash to `DecisionRequest`, computed from the exact inbound JSON:

```python
class DecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    turn: int
    request_schema: str = Field(alias="schema")
    summary: DecisionInputSummary
    snapshot_hash: str
```

In `parse_decision_input()`, pass:

```python
snapshot_hash=decision_input_snapshot_hash(message),
```

Define the helper with SHA-256 so the C# transport can compute the same value from the exact request JSON it sent:

```python
def decision_input_snapshot_hash(message: str | bytes) -> str:
    data = message.encode("utf-8") if isinstance(message, str) else message
    return hashlib.sha256(data).hexdigest()
```

Change the `build_tool_call_messages()` signature:

```python
def build_tool_call_messages(
    provider_tool_calls: list[dict[str, object]],
    *,
    turn: int,
    session_epoch: int,
    snapshot_hash: str | None = None,
) -> tuple[ToolCallMessage, ...]:
```

Then change the `ToolCallMessage(...)` construction:

```python
        terminal_action = is_terminal_action_tool(tool)
        args = require_protocol_json_object(
            call.get("args", {}),
            f"provider_tool_calls[{index}].args",
        )
        if terminal_action and snapshot_hash is not None:
            args = args | {"snapshot_hash": snapshot_hash}
        messages.append(
            ToolCallMessage(
                call_id=call_id,
                tool=tool,
                args=args,
                message_id=f"msg-{turn}-tool-call-{index}",
                session_epoch=session_epoch,
                action_nonce=(
                    f"turn-{turn}-{tool}-nonce" if terminal_action else None
                ),
                state_version=turn if terminal_action else None,
            ),
        )
```

In `emit_probe_tool_call()`, pass the request hash:

```python
    (tool_call,) = build_tool_call_messages(
        [{"tool": tool, "args": args}],
        turn=request.turn,
        session_epoch=PROBE_SESSION_EPOCH,
        snapshot_hash=request.snapshot_hash,
    )
```

- [ ] **Step 4: Run app tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_brain_app.py -k 'terminal_tool_call_probe_includes_action_nonce or terminal_tool_call_batch' -q
```

Expected: PASS.

## Task 3: C# Envelope Parsing and Static Contract

**Files:**
- Modify: `mod/LLMOfQud/ToolRouter.cs`
- Test: `tests/test_mod_static_contracts.py`

- [ ] **Step 1: Write failing static parsing tests**

Add these tests to `tests/test_mod_static_contracts.py`:

```python
def test_tool_call_envelope_declares_terminal_idempotency_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    parse_body = method_body(source, "public static ToolCallEnvelope ParseToolCallEnvelope")
    build_body = method_body(source, "public static string BuildToolResultJson")

    assert 'FieldActionNonce = "action_nonce"' in source
    assert 'FieldStateVersion = "state_version"' in source
    assert "ActionNonce = ReadOptionalString(json, ToolProtocolFields.FieldActionNonce)" in parse_body
    assert "StateVersion = ReadNullableInt(json, ToolProtocolFields.FieldStateVersion)" in parse_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldActionNonce, envelope.ActionNonce)" in build_body
    assert "public string ActionNonce;" in source
    assert "public int? StateVersion;" in source
    assert "private static string ReadOptionalString" in source


def test_toolrouter_parses_non_terminal_tool_call_without_idempotency_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    parse_body = method_body(source, "public static ToolCallEnvelope ParseToolCallEnvelope")

    assert "ActionNonce = ReadOptionalString(json, ToolProtocolFields.FieldActionNonce)" in parse_body
    assert "StateVersion = ReadNullableInt(json, ToolProtocolFields.FieldStateVersion)" in parse_body
    assert "JSON field missing: \" + name" in source


def test_terminal_idempotency_cache_key_is_session_epoch_and_action_nonce() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert "private readonly Dictionary<string, ToolResultEnvelope> _terminalActionCache" in source
    assert "TerminalActionCacheKey(call.SessionEpoch, call.ActionNonce)" in source
    assert "return call.SessionEpoch.ToString(CultureInfo.InvariantCulture) + \":\" + call.ActionNonce;" in source
```

- [ ] **Step 2: Run static tests to verify RED**

Run:

```bash
uv run pytest tests/test_mod_static_contracts.py -k 'terminal_idempotency_fields or terminal_idempotency_cache_key' -q
```

Expected: FAIL because C# envelope fields and cache are absent.

- [ ] **Step 3: Implement parsing fields and cache key only**

In `mod/LLMOfQud/ToolRouter.cs`:

```csharp
private readonly Dictionary<string, ToolResultEnvelope> _terminalActionCache =
    new Dictionary<string, ToolResultEnvelope>();
```

Add constants:

```csharp
public const string FieldActionNonce = "action_nonce";
public const string FieldStateVersion = "state_version";
```

Extend `ParseToolCallEnvelope`:

```csharp
ActionNonce = ReadOptionalString(json, ToolProtocolFields.FieldActionNonce),
StateVersion = ReadNullableInt(json, ToolProtocolFields.FieldStateVersion),
```

Extend `BuildToolResultJson()` after `session_epoch`, but only for terminal results that actually carry a nonce:

```csharp
if (envelope.ActionNonce != null)
{
    sb.Append(',');
    AppendJsonProperty(sb, ToolProtocolFields.FieldActionNonce, envelope.ActionNonce);
}
```

Add:

```csharp
private static string ReadOptionalString(string json, string name)
{
    try
    {
        return ReadStringOrNull(json, name);
    }
    catch (DisconnectedException ex)
    {
        if (ex.Message == "JSON field missing: " + name)
        {
            return null;
        }
        throw;
    }
}

private static int? ReadNullableInt(string json, string name)
{
    try
    {
        return ReadInt(json, name);
    }
    catch (DisconnectedException ex)
    {
        if (ex.Message == "JSON field missing: " + name)
        {
            return null;
        }
        throw;
    }
}

private static string TerminalActionCacheKey(int sessionEpoch, string actionNonce)
{
    return sessionEpoch.ToString(CultureInfo.InvariantCulture) + ":" + actionNonce;
}
```

Extend `ToolCallEnvelope`:

```csharp
public string ActionNonce;
public int? StateVersion;
```

Extend `ToolResultEnvelope`:

```csharp
public string ActionNonce;
```

- [ ] **Step 4: Run static tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_mod_static_contracts.py -k 'terminal_idempotency_fields or terminal_idempotency_cache_key' -q
```

Expected: PASS.

## Task 4: C# Stale and Duplicate Behavior

**Files:**
- Modify: `mod/LLMOfQud/ToolRouter.cs`
- Modify: `mod/LLMOfQud/BrainClient.cs`
- Test: `tests/test_mod_static_contracts.py`

- [ ] **Step 1: Write failing stale/duplicate static tests**

Add these tests to `tests/test_mod_static_contracts.py`:

```python
def test_toolrouter_rejects_stale_terminal_actions_before_dispatch() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    dispatch_body = method_body(source, "public ToolResultEnvelope Dispatch")

    assert "_sessionEpochProvider" in source
    assert 'TerminalActionOutput.Stale("stale_epoch")' in dispatch_body
    assert 'TerminalActionOutput.Stale("stale")' in dispatch_body
    assert "call.SessionEpoch != _sessionEpochProvider()" in dispatch_body
    assert "call.StateVersion.Value != _expectedStateVersion" in dispatch_body


def test_toolrouter_returns_cached_duplicate_terminal_action_result() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    dispatch_body = method_body(source, "public ToolResultEnvelope Dispatch")

    assert "_terminalActionCache.TryGetValue(cacheKey, out cached)" in dispatch_body
    assert "_terminalMessageCache.TryGetValue(call.MessageId, out cached)" in dispatch_body
    assert "CloneForDuplicateRequest(cached, call)" in dispatch_body
    assert "_terminalActionCache[cacheKey] = CloneForCache(result)" in dispatch_body
    assert "_terminalMessageCache[call.MessageId] = CloneForCache(result)" in dispatch_body
    assert "TerminalActionOutput.Accepted(call.Tool)" in dispatch_body


def test_toolrouter_suppresses_duplicate_terminal_turn_and_checks_snapshot_hash() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    dispatch_body = method_body(source, "public ToolResultEnvelope Dispatch")

    assert "_completedTerminalStateVersions.Contains(call.StateVersion.Value)" in dispatch_body
    assert 'TerminalActionOutput.Stale("duplicate")' in dispatch_body
    assert 'ReadStringArgOrNull(call.Args, "snapshot_hash")' in dispatch_body
    assert "!= _expectedSnapshotHash" in dispatch_body
    assert "_completedTerminalStateVersions.Add(call.StateVersion.Value)" in dispatch_body


def test_brainclient_sets_expected_state_version_and_snapshot_hash_before_receive() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    run_loop_body = method_body(source, "private void RunLoop()")

    assert "toolRouter.SetExpectedTurnContext(" in run_loop_body
    assert "ParseDecisionInputTurn(pending.RequestJson)" in run_loop_body
    assert "ComputeDecisionInputSnapshotHash(pending.RequestJson)" in run_loop_body


def test_tool_result_message_id_factory_is_public_for_cached_terminal_results() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert "public static string CreateMessageId(" in source
    assert "private static string CreateMessageId(" not in source
```

- [ ] **Step 2: Run static tests to verify RED**

Run:

```bash
uv run pytest tests/test_mod_static_contracts.py -q
```

Expected: FAIL because stale/duplicate behavior, BrainClient context wiring, and public message-id factory behavior are absent.

- [ ] **Step 3: Implement minimal stale/duplicate behavior**

Add state fields and constructor overloads to `ToolRouter`:

```csharp
private readonly Func<int> _sessionEpochProvider;
private readonly Dictionary<string, ToolResultEnvelope> _terminalMessageCache =
    new Dictionary<string, ToolResultEnvelope>();
private readonly HashSet<int> _completedTerminalStateVersions = new HashSet<int>();
private int _expectedStateVersion;
private string _expectedSnapshotHash;

public ToolRouter() : this(() => 1)
{
}

public ToolRouter(Func<int> sessionEpochProvider)
{
    _sessionEpochProvider = sessionEpochProvider ?? (() => 1);
    _expectedStateVersion = 0;
    _expectedSnapshotHash = null;
}

public void SetExpectedTurnContext(int stateVersion, string snapshotHash)
{
    _expectedStateVersion = stateVersion;
    _expectedSnapshotHash = snapshotHash;
}
```

At the start of `Dispatch`, after the null-call guard:

```csharp
if (IsTerminalAction(call.Tool))
{
    if (call.ActionNonce == null || !call.StateVersion.HasValue)
    {
        return TerminalActionResult(
            call,
            TerminalActionOutput.Stale("stale"),
            "terminal action requires action_nonce and state_version");
    }

    if (call.SessionEpoch != _sessionEpochProvider())
    {
        return TerminalActionResult(
            call,
            TerminalActionOutput.Stale("stale_epoch"),
            "terminal action belongs to a stale session epoch");
    }

    ToolResultEnvelope cached;
    if (_terminalMessageCache.TryGetValue(call.MessageId, out cached))
    {
        return CloneForDuplicateRequest(cached, call);
    }

    string cacheKey = TerminalActionCacheKey(call.SessionEpoch, call.ActionNonce);
    if (_terminalActionCache.TryGetValue(cacheKey, out cached))
    {
        return CloneForDuplicateRequest(cached, call);
    }

    if (call.StateVersion.Value != _expectedStateVersion)
    {
        return TerminalActionResult(
            call,
            TerminalActionOutput.Stale("stale"),
            "terminal action belongs to a stale state version");
    }

    if (ReadStringArgOrNull(call.Args, "snapshot_hash") != _expectedSnapshotHash)
    {
        return TerminalActionResult(
            call,
            TerminalActionOutput.Stale("stale"),
            "terminal action snapshot_hash does not match current state");
    }

    if (_completedTerminalStateVersions.Contains(call.StateVersion.Value))
    {
        return TerminalActionResult(
            call,
            TerminalActionOutput.Stale("duplicate"),
            "terminal action already completed for this state version");
    }

    ToolResultEnvelope result = TerminalActionResult(
        call,
        TerminalActionOutput.Accepted(call.Tool),
        null);
    _terminalActionCache[cacheKey] = CloneForCache(result);
    _terminalMessageCache[call.MessageId] = CloneForCache(result);
    _completedTerminalStateVersions.Add(call.StateVersion.Value);
    return result;
}
```

Add small helpers in `ToolRouter.cs`:

```csharp
private static ToolResultEnvelope TerminalActionResult(
    ToolCallEnvelope call,
    Dictionary<string, object> output,
    string errorMessage)
{
    return new ToolResultEnvelope
    {
        CallId = call.CallId,
        Tool = call.Tool,
        Result = ToolResult.Ok(output),
        MessageId = ToolResultEnvelope.CreateMessageId(call.CallId, call.Tool, call.SessionEpoch),
        InReplyTo = call.MessageId,
        SessionEpoch = call.SessionEpoch,
        ActionNonce = call.ActionNonce,
    };
}

private static ToolResultEnvelope CloneForDuplicateRequest(
    ToolResultEnvelope cached,
    ToolCallEnvelope call)
{
    return new ToolResultEnvelope
    {
        CallId = call.CallId,
        Tool = call.Tool,
        Result = cached.Result,
        MessageId = ToolResultEnvelope.CreateMessageId(call.CallId, call.Tool, call.SessionEpoch),
        InReplyTo = call.MessageId,
        SessionEpoch = call.SessionEpoch,
        ActionNonce = cached.ActionNonce,
    };
}

private static ToolResultEnvelope CloneForCache(ToolResultEnvelope result)
{
    return new ToolResultEnvelope
    {
        CallId = result.CallId,
        Tool = result.Tool,
        Result = result.Result,
        MessageId = result.MessageId,
        InReplyTo = result.InReplyTo,
        SessionEpoch = result.SessionEpoch,
        ActionNonce = result.ActionNonce,
    };
}

private static string ReadStringArgOrNull(Dictionary<string, object> args, string name)
{
    if (args == null || !args.ContainsKey(name))
    {
        return null;
    }
    return args[name] as string;
}
```

Change `ToolResultEnvelope.CreateMessageId` to `public static`.

Update the existing `tests/test_mod_static_contracts.py::test_tool_result_error_envelopes_assign_non_null_message_id` assertion from:

```python
assert "private static string CreateMessageId(" in source
```

to:

```python
assert "public static string CreateMessageId(" in source
```

Add:

```csharp
public static class TerminalActionOutput
{
    public static Dictionary<string, object> Accepted(string actionKind)
    {
        Dictionary<string, object> output = Base(actionKind, true, "accepted");
        output["execution_status"] = "accepted";
        return output;
    }

    public static Dictionary<string, object> Stale(string acceptanceStatus)
    {
        Dictionary<string, object> output = Base("terminal_action", false, acceptanceStatus);
        output["execution_status"] = "rejected";
        return output;
    }

    private static Dictionary<string, object> Base(
        string actionKind,
        bool accepted,
        string acceptanceStatus)
    {
        return new Dictionary<string, object>
        {
            { "accepted", accepted },
            { "turn_complete", accepted },
            { "action_kind", actionKind },
            { "acceptance_status", acceptanceStatus },
            { "safety_decision", accepted ? "pass" : "block" },
        };
    }
}
```

In `BrainClient.RunLoop`, set the expected state version from the request before receiving tool calls:

Add `using System.Globalization;` and `using System.Security.Cryptography;` to `BrainClient.cs`.

```csharp
toolRouter.SetExpectedTurnContext(
    ParseDecisionInputTurn(pending.RequestJson),
    ComputeDecisionInputSnapshotHash(pending.RequestJson));
string response = ReceiveDecision(socket, pending.TimeoutMs, toolRouter);
```

Add a private helper to `BrainClient`:

```csharp
private static int ParseDecisionInputTurn(string requestJson)
{
    return ToolRouter.ReadTopLevelIntForTransport(requestJson, "turn");
}

private static string ComputeDecisionInputSnapshotHash(string requestJson)
{
    using (SHA256 sha = SHA256.Create())
    {
        byte[] bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(requestJson ?? ""));
        StringBuilder sb = new StringBuilder(bytes.Length * 2);
        for (int i = 0; i < bytes.Length; i++)
        {
            sb.Append(bytes[i].ToString("x2", CultureInfo.InvariantCulture));
        }
        return sb.ToString();
    }
}
```

Expose the existing C# integer reader through a narrow `ToolRouter` helper:

```csharp
public static int ReadTopLevelIntForTransport(string json, string name)
{
    return ReadInt(json, name);
}
```

- [ ] **Step 4: Run static tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_mod_static_contracts.py -q
```

Expected: PASS.

## Task 5: Python Telemetry Columns

**Files:**
- Modify: `brain/db/schema.py`
- Modify: `brain/db/writer.py`
- Test: `tests/test_brain_db.py`

- [ ] **Step 1: Write failing telemetry tests**

Add `"terminal_action"` to `TableName` only if a new table is created. This plan uses columns on existing tables, so keep `TableName` unchanged.

Add this test to `tests/test_brain_db.py`:

```python
@pytest.mark.asyncio
async def test_telemetry_writer_records_terminal_idempotency_fields(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "telemetry.db"
    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_tool_call_sent(
            call_id="call-exec-1",
            tool="execute",
            action_nonce="nonce-1",
            state_version=284,
            session_epoch=3,
        )
        await writer.record_tool_call_received(
            call_id="call-exec-1",
            tool="execute",
            result_status="ok",
            latency_ms=9,
            action_nonce="nonce-1",
            state_version=284,
            session_epoch=3,
            acceptance_status="stale",
        )
    finally:
        await writer.close()

    sent = await fetch_one(
        db_path,
        """
        SELECT action_nonce, state_version, session_epoch
        FROM tool_call_sent
        WHERE call_id = 'call-exec-1'
        """,
    )
    received = await fetch_one(
        db_path,
        """
        SELECT action_nonce, state_version, session_epoch, acceptance_status
        FROM tool_call_received
        WHERE call_id = 'call-exec-1'
        """,
    )

    assert dict(sent) == {
        "action_nonce": "nonce-1",
        "state_version": 284,
        "session_epoch": 3,
    }
    assert dict(received) == {
        "action_nonce": "nonce-1",
        "state_version": 284,
        "session_epoch": 3,
        "acceptance_status": "stale",
    }
```

- [ ] **Step 2: Run telemetry test to verify RED**

Run:

```bash
uv run pytest tests/test_brain_db.py -k terminal_idempotency_fields -q
```

Expected: FAIL because writer methods do not accept terminal idempotency keyword arguments.

- [ ] **Step 3: Implement telemetry columns and writer arguments**

In `brain/db/schema.py`, add nullable columns to both `tool_call_sent` and `tool_call_received`:

```sql
action_nonce TEXT,
state_version INTEGER,
session_epoch INTEGER
```

Add this extra column only to `tool_call_received`:

```sql
acceptance_status TEXT
```

Add migration dictionaries for both tables:

```python
TOOL_CALL_SENT_COLUMN_MIGRATIONS = {
    "action_nonce": "ALTER TABLE tool_call_sent ADD COLUMN action_nonce TEXT",
    "state_version": "ALTER TABLE tool_call_sent ADD COLUMN state_version INTEGER",
    "session_epoch": "ALTER TABLE tool_call_sent ADD COLUMN session_epoch INTEGER",
}

TOOL_CALL_RECEIVED_COLUMN_MIGRATIONS = {
    "action_nonce": "ALTER TABLE tool_call_received ADD COLUMN action_nonce TEXT",
    "state_version": "ALTER TABLE tool_call_received ADD COLUMN state_version INTEGER",
    "session_epoch": "ALTER TABLE tool_call_received ADD COLUMN session_epoch INTEGER",
    "acceptance_status": "ALTER TABLE tool_call_received ADD COLUMN acceptance_status TEXT",
}
```

Ensure `create_all()` applies all three migration dictionaries.

In `brain/db/writer.py`, extend `record_tool_call_sent()` and `record_tool_call_received()` with keyword-only optional arguments:

```python
action_nonce: str | None = None,
state_version: int | None = None,
session_epoch: int | None = None,
acceptance_status: str | None = None,
```

Only `record_tool_call_received()` receives `acceptance_status`.

- [ ] **Step 4: Run telemetry tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_brain_db.py -k terminal_idempotency_fields -q
```

Expected: PASS.

## Task 6: WebSocket Terminal Result Probe Coverage

**Files:**
- Modify: `brain/app.py`
- Test: `tests/test_brain_app.py`

- [ ] **Step 1: Write terminal result probe tests**

Add fake-C# helper code and this test to `tests/test_brain_app.py`:

```python
@pytest.mark.asyncio
async def test_terminal_tool_call_result_is_exposed_to_decision_response() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(
        phase="tool_call_probe:execute",
        result_status="ok",
    )

    assert tool_call["tool"] == "execute"
    assert response["tool_result"]["action_nonce"] == tool_call["action_nonce"]
    assert response["tool_result"]["output"]["acceptance_status"] == "accepted"
```

Then update `run_fake_csharp_tool_roundtrip()` to emit top-level `action_nonce` and `result.output` for terminal tools:

```python
if result_status == "ok" and tool_call["tool"] in {"execute", "navigate_to", "choose"}:
    result["output"] = {
        "accepted": True,
        "turn_complete": True,
        "action_kind": tool_call["tool"],
        "execution_status": "accepted",
        "acceptance_status": "accepted",
        "safety_decision": "pass",
    }
    tool_result_action_nonce = tool_call["action_nonce"]
elif result_status == "ok":
    result["output"] = {"visible_tiles": 8}
    tool_result_action_nonce = None
```

When building the fake `tool_result` JSON, include:

```python
                        "action_nonce": tool_result_action_nonce,
```

In `respond_for_phase()`, expose terminal result nonce in the probe response projection:

```python
        tool_result_payload = cast(
            "JsonObject",
            result.result.model_dump(mode="json", exclude_none=True),
        )
        if result.action_nonce is not None:
            tool_result_payload["action_nonce"] = result.action_nonce
        response["tool_result"] = cast("JsonValue", tool_result_payload)
```

- [ ] **Step 2: Run probe tests**

Run:

```bash
uv run pytest tests/test_brain_app.py -k terminal_tool_call_result_is_exposed -q
```

Expected: PASS after Task 2. If it fails because `tool_result.output` is missing, finish the helper update above.

- [ ] **Step 3: Run focused PR-3 test set**

Run:

```bash
uv run pytest tests/test_protocol_messages.py tests/test_brain_app.py tests/test_brain_db.py tests/test_mod_static_contracts.py -q
```

Expected: PASS.

## Task 7: Full Verification

**Files:**
- No source files changed in this task.

- [ ] **Step 1: Run full Python tests**

Run:

```bash
uv run pytest tests/
```

Expected: PASS.

- [ ] **Step 2: Run repo static gate**

Run:

```bash
pre-commit run --all-files
```

Expected: PASS.

- [ ] **Step 3: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- docs/superpowers/plans/2026-04-29-phase-1-pr-3-terminal-action-idempotency.md brain/protocol.py brain/app.py brain/db/schema.py brain/db/writer.py mod/LLMOfQud/ToolRouter.cs mod/LLMOfQud/BrainClient.cs tests/test_protocol_messages.py tests/test_brain_app.py tests/test_brain_db.py tests/test_mod_static_contracts.py
```

Expected: Only PR-3 scoped files are changed. Do not commit unless the user explicitly requests a commit.

## Self-Review

- Spec coverage: Tasks 1-2 cover top-level terminal envelope fields and probe `snapshot_hash`; Task 3 covers optional C# parsing that preserves non-terminal PR-2 calls; Task 4 covers stale epoch, nonce cache, minimum terminal `message_id` dedup, duplicate turn suppression, snapshot hash checking, and terminal output; Task 5 covers telemetry; Task 6 covers no-LLM WebSocket exposure; Task 7 covers verification.
- Explicit deferrals: Non-terminal deduplication, Phase 2a provider execution, real game action handlers, pathfinding, reconnect hardening beyond stale epoch rejection, and `cancel_or_back` terminalization are out of scope.
- ADR status: No ADR is created because ADR 0011 states PR-3 needs no new ADR; this plan follows the frozen v5.9 contract.
