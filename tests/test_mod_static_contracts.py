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
