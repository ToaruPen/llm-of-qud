from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def method_body(source: str, signature: str) -> str:
    start = source.find(signature)
    assert start >= 0
    brace = source.find("{", start)
    assert brace >= 0
    depth = 0
    in_string = False
    in_char = False
    escaping = False
    for index in range(brace, len(source)):
        char = source[index]
        if escaping:
            escaping = False
            continue
        if char == "\\" and (in_string or in_char):
            escaping = True
            continue
        if char == '"' and not in_char:
            in_string = not in_string
            continue
        if char == "'" and not in_string:
            in_char = not in_char
            continue
        if in_string or in_char:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"method body not closed: {signature}")


def csharp_mod_sources() -> dict[str, str]:
    source_root = ROOT / "mod/LLMOfQud"
    return {
        path.relative_to(source_root).as_posix(): path.read_text()
        for path in sorted(source_root.rglob("*.cs"))
    }


def test_disconnect_pause_does_not_emit_decision_channel() -> None:
    source = (ROOT / "mod/LLMOfQud/LLMOfQudSystem.cs").read_text()
    match = re.search(
        r"catch \(DisconnectedException ex\)\s*\{(?P<body>.*?)\n\s*\}\n\s*catch \(Exception ex\)",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    body = match.group("body")

    assert "[LLMOfQud][decision]" not in body
    assert "[LLMOfQud][disconnect_pause]" in body


def test_brainclient_response_log_includes_round_trip_elapsed_ms() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    body = method_body(source, "private void RunLoop()")

    assert "Stopwatch.StartNew()" in body
    assert "elapsed_ms=" in body


def test_brainclient_receive_path_round_trips_tool_call_before_decision() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    run_loop_body = method_body(source, "private void RunLoop()")
    receive_decision_body = method_body(source, "private static string ReceiveDecision")

    assert "ToolRouter toolRouter = new ToolRouter()" in run_loop_body
    assert "ReceiveDecision(socket, pending.TimeoutMs, toolRouter)" in run_loop_body
    assert "ToolRouter.IsToolCallMessage(responseJson)" in receive_decision_body
    assert "ToolRouter.ParseToolCallEnvelope(responseJson)" in receive_decision_body
    assert "toolRouter.Dispatch(call)" in receive_decision_body
    assert "new ToolRouter().Dispatch(call)" not in receive_decision_body
    assert "ToolRouter.BuildToolResultJson(result)" in receive_decision_body
    assert 'RemainingTimeoutMs(deadline, "decision timed out")' in receive_decision_body
    assert "Receive(socket, remainingMs)" in receive_decision_body
    assert "Send(socket, resultJson, remainingMs)" in receive_decision_body
    assert "Receive(socket, timeoutMs)" not in receive_decision_body
    assert "Send(socket, resultJson, timeoutMs)" not in receive_decision_body
    assert "continue;" in receive_decision_body
    assert "return responseJson;" in receive_decision_body


def test_brainclient_receive_path_does_not_accept_supervisor_request_from_python() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    receive_decision_body = method_body(source, "private static string ReceiveDecision")

    assert "ToolRouter.IsSupervisorRequestMessage(responseJson)" not in receive_decision_body
    assert "ToolRouter.ParseSupervisorRequestEnvelope(responseJson)" not in receive_decision_body
    assert "ToolRouter.BuildUnsupportedSupervisorResponseJson" not in receive_decision_body
    assert "supervisorResponseJson" not in receive_decision_body


def test_brainclient_receive_path_rejects_supervisor_response_before_parse_decision() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    policy_source = (ROOT / "mod/LLMOfQud/WebSocketPolicy.cs").read_text()
    receive_decision_body = method_body(source, "private static string ReceiveDecision")
    decide_body = method_body(policy_source, "public Decision Decide")

    assert "ToolRouter.IsSupervisorResponseMessage(responseJson)" in receive_decision_body
    assert "ToolRouter.ParseSupervisorResponseEnvelope(responseJson)" in receive_decision_body
    assert "throw new DisconnectedException" in receive_decision_body
    assert receive_decision_body.index(
        "ToolRouter.IsSupervisorResponseMessage(responseJson)"
    ) < receive_decision_body.index("return responseJson;")
    assert "ParseDecision(responseJson, input.Turn)" in decide_body
    assert "SupervisorResponse" not in decide_body


def test_brainclient_runtime_logs_cite_metrics_manager_source() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()

    assert "decompiled/MetricsManager.cs:407-409 (LogInfo -> Player.log)" in source


def test_brainclient_rehydrates_all_nonserialized_runtime_state() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    body = method_body(source, "private void InitializeRuntimeFields()")

    assert "_gate = new object()" in body
    assert "_requests = new Queue<PendingRequest>()" in body
    assert "_requestReady = new AutoResetEvent(false)" in body


def test_brainclient_stop_fails_pending_requests_and_blocks_new_work() -> None:
    source = (ROOT / "mod/LLMOfQud/BrainClient.cs").read_text()
    stop_body = method_body(source, "public void Stop()")
    send_body = method_body(source, "public DecisionRequest SendDecisionInput")

    assert "_stopped = true" in stop_body
    assert "FailPendingRequestsLocked" in stop_body
    assert 'throw new DisconnectedException("BrainClient stopped")' in send_body


def test_reconnect_wake_skips_player_turn_without_key_command() -> None:
    source = (ROOT / "mod/LLMOfQud/LLMOfQudSystem.cs").read_text()
    reconnect_body = method_body(source, "private static void OnBrainReconnected()")
    apply_body = method_body(source, "private static void ApplyPendingReconnectWake()")

    assert "Interlocked.Exchange(ref _pendingReconnectWake, 1)" in reconnect_body
    assert "Keyboard.KeyEvent.Set()" in reconnect_body
    assert "SkipPlayerTurn = true" not in reconnect_body
    assert "SkipPlayerTurn = true" in apply_body
    assert "Keyboard.PushKey(UnityEngine.KeyCode.None)" not in reconnect_body
    assert "Keyboard.PushKey(UnityEngine.KeyCode.None)" not in apply_body


def test_reconnect_wake_game_queue_call_cites_decompiled_sources() -> None:
    source = (ROOT / "mod/LLMOfQud/LLMOfQudSystem.cs").read_text()

    assert "decompiled/GameManager.cs:144" in source
    assert "decompiled/QupKit/ThreadTaskQueue.cs:102-103" in source


def test_websocket_policy_rejects_unsupported_decision_fields_and_non_integer_turns() -> None:
    source = (ROOT / "mod/LLMOfQud/WebSocketPolicy.cs").read_text()
    parse_body = method_body(source, "private static Decision ParseDecision")
    validate_body = method_body(source, "private static void ValidateDecisionFields")
    read_int_body = method_body(source, "private static int ReadInt")

    assert "ValidateDecisionFields(intent, action, dir)" in parse_body
    assert "Unsupported decision action" in validate_body
    assert "JSON field is not a strict integer" in read_int_body


def test_csharp_mod_sources_are_keyed_by_relative_path() -> None:
    sources = csharp_mod_sources()
    source_keys = [Path(key) for key in sources]

    assert "ToolRouter.cs" in sources
    assert all(not key.is_absolute() for key in source_keys)
    assert all(key.suffix == ".cs" for key in source_keys)


def test_toolrouter_dispatch_boundary_exists() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert "public sealed class ToolRouter" in source
    assert "public ToolResultEnvelope Dispatch(ToolCallEnvelope call)" in source


def test_mod_protocol_contract_avoids_provider_specific_top_level_fields() -> None:
    source = "\n".join(csharp_mod_sources().values())

    assert "function_call" not in source
    assert "FunctionCall" not in source
    assert "tool_use" not in source
    assert "ToolUse" not in source


def test_tool_call_envelope_declares_required_wire_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert 'FieldType = "type"' in source
    assert 'TypeToolCall = "tool_call"' in source
    assert 'FieldCallId = "call_id"' in source
    assert 'FieldTool = "tool"' in source
    assert 'FieldArgs = "args"' in source
    assert 'FieldMessageId = "message_id"' in source
    assert 'FieldSessionEpoch = "session_epoch"' in source
    assert "public string CallId;" in source
    assert "public string Tool;" in source
    assert "public Dictionary<string, object> Args;" in source
    assert "public string MessageId;" in source
    assert "public int SessionEpoch;" in source


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
    assert (
        'return sessionEpoch.ToString(CultureInfo.InvariantCulture) + ":" + actionNonce;'
        in source
    )


def test_tool_call_envelope_rejects_legacy_top_level_tid() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    parse_body = method_body(source, "public static ToolCallEnvelope ParseToolCallEnvelope")
    tool_call_body = method_body(source, "public sealed class ToolCallEnvelope")
    tool_result_body = method_body(source, "public sealed class ToolResultEnvelope")

    assert 'FieldLegacyTid = "tid"' in source
    assert "RejectTopLevelField(json, ToolProtocolFields.FieldLegacyTid)" in parse_body
    assert '"Unsupported legacy tool_call field: "' in source
    assert "SupervisorRequestEnvelope" in source
    assert "public int Tid;" not in tool_call_body
    assert "public int Tid;" not in tool_result_body


def test_tool_result_envelope_declares_required_wire_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert 'TypeToolResult = "tool_result"' in source
    assert 'FieldResult = "result"' in source
    assert 'FieldInReplyTo = "in_reply_to"' in source
    assert "public ToolResult Result;" in source
    assert "public string InReplyTo;" in source


def test_tool_result_error_envelopes_assign_non_null_message_id() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    envelope_body = method_body(source, "public sealed class ToolResultEnvelope")
    body = method_body(source, "public static ToolResultEnvelope FromError")

    assert "public string MessageId = CreateMessageId(" in envelope_body
    assert "MessageId = CreateMessageId(" in body
    assert "MessageId = null" not in body
    assert "public static string CreateMessageId(" in source


def test_tool_result_declares_normalized_status_output_and_error_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert 'StatusOk = "ok"' in source
    assert 'StatusError = "error"' in source
    assert 'FieldStatus = "status"' in source
    assert 'FieldOutput = "output"' in source
    assert 'FieldErrorCode = "error_code"' in source
    assert 'FieldErrorMessage = "error_message"' in source
    assert "public string Status;" in source
    assert "public object Output;" in source
    assert "public string ErrorCode;" in source
    assert "public string ErrorMessage;" in source


def test_supervisor_response_helper_declares_top_level_python_to_csharp_contract() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    build_body = method_body(source, "public static string BuildUnsupportedSupervisorResponseJson")

    assert 'TypeSupervisorRequest = "supervisor_request"' in source
    assert 'TypeSupervisorResponse = "supervisor_response"' in source
    assert 'SupervisorActionResume = "resume"' in source
    assert "public sealed class SupervisorRequestEnvelope" in source
    assert "public sealed class SupervisorResponseEnvelope" in source
    assert "public string MessageId;" in source
    assert "public string InReplyTo;" in source
    assert "public int SessionEpoch;" in source
    assert "public string Action;" in source
    assert "public string ChoiceId;" in source
    assert "public string Reason;" in source
    assert "public string Status;" not in method_body(
        source, "public sealed class SupervisorResponseEnvelope"
    )
    assert "public SupervisorResponseResult Result;" not in source
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldType, envelope.Type)" in build_body
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldMessageId, envelope.MessageId)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldInReplyTo, envelope.InReplyTo)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldSessionEpoch, envelope.SessionEpoch)"
        in build_body
    )
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldAction, envelope.Action)" in build_body
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldChoiceId, envelope.ChoiceId)" in build_body
    )
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldReason, envelope.Reason)" in build_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldStatus" not in build_body
    assert "FieldResult" not in build_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldTool" not in build_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldCallId" not in build_body


def test_toolrouter_recognizes_supervisor_response_not_request_from_python() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    recognize_body = method_body(source, "public static bool IsSupervisorResponseMessage")
    parse_body = method_body(
        source, "public static SupervisorResponseEnvelope ParseSupervisorResponseEnvelope"
    )

    assert "public static bool IsSupervisorResponseMessage(string json)" in source
    assert "public static bool IsSupervisorRequestMessage(string json)" not in source
    assert "ReadStringOrNull(json, ToolProtocolFields.FieldType)" in recognize_body
    assert "ToolProtocolFields.TypeSupervisorResponse" in recognize_body
    assert "MessageId = ReadStringOrNull(json, ToolProtocolFields.FieldMessageId)" in parse_body
    assert "InReplyTo = ReadStringOrNull(json, ToolProtocolFields.FieldInReplyTo)" in parse_body
    assert "SessionEpoch = ReadInt(json, ToolProtocolFields.FieldSessionEpoch)" in parse_body
    assert "Action = ReadStringOrNull(json, ToolProtocolFields.FieldAction)" in parse_body
    assert "ChoiceId = ReadStringOrNull(json, ToolProtocolFields.FieldChoiceId)" in parse_body
    assert "Reason = ReadStringOrNull(json, ToolProtocolFields.FieldReason)" in parse_body


def test_toolrouter_parse_and_send_helpers_preserve_round_trip_fields() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    parse_body = method_body(source, "public static ToolCallEnvelope ParseToolCallEnvelope")
    build_body = method_body(source, "public static string BuildToolResultJson")
    unescape_body = method_body(source, "private static string UnescapeSimple")

    assert "public static bool IsToolCallMessage(string json)" in source
    assert (
        "ReadStringOrNull(json, ToolProtocolFields.FieldType) == ToolProtocolFields.TypeToolCall"
        in source
    )
    assert "CallId = ReadRequiredString(json, ToolProtocolFields.FieldCallId)" in parse_body
    assert "CallId = ReadStringOrNull(json, ToolProtocolFields.FieldCallId)" not in parse_body
    assert "Tool = ReadStringOrNull(json, ToolProtocolFields.FieldTool)" in parse_body
    assert "Args = ReadArgs(json)" in parse_body
    assert "MessageId = ReadStringOrNull(json, ToolProtocolFields.FieldMessageId)" in parse_body
    assert "SessionEpoch = ReadInt(json, ToolProtocolFields.FieldSessionEpoch)" in parse_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldCallId, envelope.CallId)" in build_body
    assert "AppendJsonProperty(sb, ToolProtocolFields.FieldTool, envelope.Tool)" in build_body
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldMessageId, envelope.MessageId)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldInReplyTo, envelope.InReplyTo)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldSessionEpoch, envelope.SessionEpoch)"
        in build_body
    )
    assert "AppendJsonPropertyName(sb, ToolProtocolFields.FieldResult)" in build_body
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldStatus, envelope.Result.Status)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldOutput, envelope.Result.Output)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldErrorCode, envelope.Result.ErrorCode)"
        in build_body
    )
    assert (
        "AppendJsonProperty(sb, ToolProtocolFields.FieldErrorMessage, envelope.Result.ErrorMessage)"
        in build_body
    )
    assert "case 'n': sb.Append('\\n'); break;" in unescape_body
    assert "case 'r': sb.Append('\\r'); break;" in unescape_body
    assert "case 't': sb.Append('\\t'); break;" in unescape_body
    assert "case 'u':" in unescape_body
    assert "NumberStyles.HexNumber" in unescape_body
    assert "int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture" in unescape_body
    assert "throw new DisconnectedException(\"JSON unicode escape is invalid: \" + hex)" in unescape_body


def test_toolrouter_rejects_unsupported_raw_args_values() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    body = method_body(source, "private static object ReadSimpleJsonValue")

    assert "return raw;" not in body
    assert "raw[0] == '{' || raw[0] == '['" in body
    assert "JSON args value type is unsupported" in body
    assert "int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture" in body
    assert "throw new DisconnectedException" in body


def test_toolrouter_read_int_rejects_overflow_and_preserves_strict_parsing() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    body = method_body(source, "private static int ReadInt")

    assert "long maxMagnitude" in body
    assert "int.MaxValue" in body
    assert "int.MinValue" in body
    assert "value > maxMagnitude" in body
    assert "JSON field integer is out of Int32 range" in body
    assert "JSON field is not a strict integer" in body


def test_tool_call_detection_preserves_direct_decision_messages_without_type() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    body = method_body(source, "public static bool IsToolCallMessage")

    assert "catch (DisconnectedException)" in body
    assert "return false;" in body


def test_terminal_action_parallel_dispatch_is_disabled_by_default() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()

    assert "public const bool TerminalActionParallelDispatchEnabled = false;" in source


def test_only_execute_navigate_to_and_choose_are_terminal_actions() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    terminal_body = method_body(source, "private static bool IsTerminalAction")
    parallel_body = method_body(source, "public static bool CanDispatchInParallel")

    assert 'case "execute":' in terminal_body
    assert 'case "navigate_to":' in terminal_body
    assert 'case "choose":' in terminal_body
    assert 'case "cancel_or_back":' not in terminal_body
    assert "return TerminalActionParallelDispatchEnabled;" in parallel_body


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


def test_unknown_tool_errors_use_protocol_error_code() -> None:
    source = (ROOT / "mod/LLMOfQud/ToolRouter.cs").read_text()
    dispatch_body = method_body(source, "public ToolResultEnvelope Dispatch")

    assert '"unknown_tool"' in dispatch_body
    assert '"unsupported_tool"' not in dispatch_body
