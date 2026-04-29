from __future__ import annotations

# ruff: noqa: E402, PLR2004, S101
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.app import (
    MALFORMED_TOOL_ARGS_ERROR_CODE,
    PHASE_ACCEPTANCE_ECHO,
    DuplicateToolCallIdError,
    ServerConfig,
    ToolResultMismatchError,
    build_tool_call_messages,
    delay_for_phase,
    parse_decision_input,
    parse_delay_ms,
    phase_for_phase1_acceptance,
    require_int,
    require_matching_tool_result,
    require_object,
    start_probe_server,
)
from brain.protocol import ToolResultMessage, ToolResultPayload, ToolResultStatus

if TYPE_CHECKING:
    from brain.protocol import JsonObject, JsonValue


def minimal_decision_input(turn: int = 7) -> JsonObject:
    return {
        "schema": "decision_input.v1",
        "turn": turn,
        "player": {"hp": 12, "max_hp": 20, "pos": {"x": 1, "y": 2, "zone": "Joppa"}},
        "adjacent": {
            "hostile_dir": None,
            "hostile_id": None,
            "blocked_dirs": ["N", "W"],
        },
        "recent": {
            "last_action_turn": 6,
            "last_action": "Move",
            "last_dir": "E",
            "last_result": True,
        },
    }


def with_adjacent_hostile(payload: JsonObject, direction: str) -> JsonObject:
    adjacent = payload["adjacent"]
    assert isinstance(adjacent, dict)
    adjacent["hostile_dir"] = direction
    adjacent["hostile_id"] = "hostile-1"
    return payload


def with_blocked_dirs(payload: JsonObject, blocked_dirs: list[str]) -> JsonObject:
    adjacent = payload["adjacent"]
    assert isinstance(adjacent, dict)
    blocked_dir_values = cast("list[JsonValue]", list(blocked_dirs))
    adjacent["blocked_dirs"] = blocked_dir_values
    return payload


async def run_fake_csharp_tool_roundtrip(
    *,
    phase: str,
    result_status: str = "ok",
    error_code: str | None = None,
    error_message: str | None = None,
) -> tuple[JsonObject, JsonObject]:
    server = await start_probe_server(ServerConfig(host="127.0.0.1", port=0, initial_phase=phase))
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(json.dumps(minimal_decision_input()))
            tool_call = cast("JsonObject", json.loads(await websocket.recv()))
            result: JsonObject = {"status": result_status}
            if result_status == "ok":
                result["output"] = {"visible_tiles": 8}
            else:
                result["error_code"] = error_code
                result["error_message"] = error_message
            await websocket.send(
                json.dumps(
                    {
                        "type": "tool_result",
                        "call_id": tool_call["call_id"],
                        "tool": tool_call["tool"],
                        "result": result,
                        "message_id": "fake-csharp-result-1",
                        "in_reply_to": tool_call["message_id"],
                        "session_epoch": tool_call["session_epoch"],
                    },
                ),
            )
            response = cast("JsonObject", json.loads(await websocket.recv()))
            return tool_call, response
    finally:
        await server.close()


def test_parse_decision_input_rejects_unexpected_schema() -> None:
    payload = minimal_decision_input()
    payload["schema"] = "decision_input.v2"

    with pytest.raises(ValueError, match="unsupported decision input schema"):
        parse_decision_input(json.dumps(payload))


def test_parse_decision_input_normalizes_invalid_hostile_direction() -> None:
    request = parse_decision_input(
        json.dumps(with_adjacent_hostile(minimal_decision_input(), "INVALID")),
    )

    assert request.summary.adjacent_hostile_dir is None


def test_delay_phase_errors_include_offending_phase() -> None:
    with pytest.raises(ValueError, match="unsupported phase: mystery"):
        delay_for_phase("mystery")
    with pytest.raises(ValueError, match="invalid sleep value for phase: sleep:abc"):
        parse_delay_ms("sleep:abc")
    with pytest.raises(ValueError, match="negative sleep value for phase: sleep:-1"):
        parse_delay_ms("sleep:-1")


def test_json_helpers_raise_informative_type_errors() -> None:
    with pytest.raises(TypeError, match="require_object: expected key 'player' to be object"):
        require_object({"player": 1}, "player")
    with pytest.raises(TypeError, match="require_int: expected key 'turn' to be int"):
        require_int({"turn": True}, "turn")


@pytest.mark.asyncio
async def test_echo_phase_returns_canned_decision_on_random_port() -> None:
    server = await start_probe_server(ServerConfig(host="127.0.0.1", port=0))
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(json.dumps(minimal_decision_input()))
            response = json.loads(await websocket.recv())
    finally:
        await server.close()

    assert response == {
        "turn": 7,
        "schema": "decision.v1",
        "input_summary": {
            "hp": 12,
            "max_hp": 20,
            "adjacent_hostile_dir": None,
            "blocked_dirs_count": 2,
        },
        "intent": "explore",
        "action": "Move",
        "dir": "E",
        "reason_code": "canned_no_llm",
        "error": None,
    }


@pytest.mark.asyncio
async def test_fake_csharp_harness_emit_tool_call_round_trips_tool_result() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(
        phase="tool_call_probe:inspect_surroundings",
    )

    assert tool_call["type"] == "tool_call"
    assert tool_call["tool"] == "inspect_surroundings"
    assert tool_call["args"] == {}
    assert tool_call["call_id"] == "turn-7-call-1"
    assert tool_call["message_id"] == "msg-7-tool-call-1"
    assert tool_call["session_epoch"] == 1
    assert "tid" not in tool_call
    assert response["tool_result"] == {
        "status": "ok",
        "output": {"visible_tiles": 8},
    }


@pytest.mark.asyncio
async def test_unknown_tool_result_uses_normalized_error_payload() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(
        phase="tool_call_probe:not_a_real_tool",
        result_status="error",
        error_code="unknown_tool",
        error_message="unknown tool: not_a_real_tool",
    )

    assert tool_call["tool"] == "not_a_real_tool"
    assert response["tool_result"] == {
        "status": "error",
        "error_code": "unknown_tool",
        "error_message": "unknown tool: not_a_real_tool",
    }


@pytest.mark.asyncio
async def test_fake_csharp_malformed_args_failure_uses_deterministic_validation_code() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(
        phase="tool_call_probe_malformed_args:execute",
        result_status="error",
        error_code=MALFORMED_TOOL_ARGS_ERROR_CODE,
        error_message="candidate_id must be a string",
    )

    assert tool_call["tool"] == "execute"
    assert tool_call["args"] == {"candidate_id": 123}
    tool_result = response["tool_result"]
    assert isinstance(tool_result, dict)
    assert tool_result["error_code"] == MALFORMED_TOOL_ARGS_ERROR_CODE


@pytest.mark.asyncio
async def test_python_emits_game_tool_call_instead_of_dispatching_it_locally() -> None:
    tool_call, response = await run_fake_csharp_tool_roundtrip(phase="tool_call_probe:check_status")

    assert tool_call["type"] == "tool_call"
    assert tool_call["tool"] == "check_status"
    assert response["schema"] == "decision.v1"


def test_more_than_one_terminal_action_is_rejected_before_emission() -> None:
    with pytest.raises(ValueError, match="multiple terminal actions"):
        build_tool_call_messages(
            [
                {"tool": "execute", "args": {"candidate_id": "c1"}, "call_id": "call-1"},
                {"tool": "navigate_to", "args": {"target": "stairs_down"}, "call_id": "call-2"},
            ],
            turn=7,
            session_epoch=3,
        )


def test_cancel_or_back_is_non_terminal_for_parallel_terminal_guard() -> None:
    messages = build_tool_call_messages(
        [
            {"tool": "execute", "args": {"candidate_id": "c1"}, "call_id": "call-1"},
            {"tool": "cancel_or_back", "args": {}, "call_id": "call-2"},
        ],
        turn=7,
        session_epoch=3,
    )

    assert [message.tool for message in messages] == ["execute", "cancel_or_back"]


def test_tool_result_session_epoch_must_match_tool_call() -> None:
    (tool_call,) = build_tool_call_messages(
        [{"tool": "check_status", "args": {}, "call_id": "call-1"}],
        turn=7,
        session_epoch=3,
    )
    tool_result = ToolResultMessage(
        call_id=tool_call.call_id,
        tool=tool_call.tool,
        result=ToolResultPayload(status=ToolResultStatus.OK),
        message_id="result-1",
        in_reply_to=tool_call.message_id,
        session_epoch=4,
    )

    with pytest.raises(
        ToolResultMismatchError,
        match=r"tool_result session_epoch mismatch: expected 3, got 4",
    ):
        require_matching_tool_result(tool_call, tool_result)


def test_duplicate_provider_call_id_is_rejected_before_emission() -> None:
    with pytest.raises(
        DuplicateToolCallIdError,
        match="duplicate tool call_id in emission batch: call-1",
    ):
        build_tool_call_messages(
            [
                {"tool": "check_status", "args": {}, "call_id": "call-1"},
                {"tool": "inspect_surroundings", "args": {}, "call_id": "call-1"},
            ],
            turn=7,
            session_epoch=3,
        )


def test_missing_provider_call_id_uses_unique_generated_ids() -> None:
    messages = build_tool_call_messages(
        [
            {"tool": "check_status", "args": {}},
            {"tool": "inspect_surroundings", "args": {}},
        ],
        turn=7,
        session_epoch=3,
    )

    assert [message.call_id for message in messages] == ["turn-7-call-1", "turn-7-call-2"]


@pytest.mark.asyncio
async def test_sleep_phase_delays_response_by_configured_milliseconds() -> None:
    server = await start_probe_server(
        ServerConfig(host="127.0.0.1", port=0, initial_phase="sleep:50"),
    )
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            start = perf_counter()
            await websocket.send(json.dumps(minimal_decision_input()))
            await websocket.recv()
            elapsed_ms = (perf_counter() - start) * 1000
    finally:
        await server.close()

    assert elapsed_ms >= 50


@pytest.mark.asyncio
async def test_canned_policy_attacks_adjacent_hostile() -> None:
    server = await start_probe_server(ServerConfig(host="127.0.0.1", port=0))
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(json.dumps(with_adjacent_hostile(minimal_decision_input(), "NW")))
            response = json.loads(await websocket.recv())
    finally:
        await server.close()

    assert response["intent"] == "attack"
    assert response["action"] == "AttackDirection"
    assert response["dir"] == "NW"
    assert response["reason_code"] == "canned_adjacent_hostile"


@pytest.mark.asyncio
async def test_canned_policy_ignores_invalid_adjacent_hostile_direction() -> None:
    server = await start_probe_server(ServerConfig(host="127.0.0.1", port=0))
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(
                json.dumps(with_adjacent_hostile(minimal_decision_input(), "northwest")),
            )
            response = json.loads(await websocket.recv())
    finally:
        await server.close()

    assert response["intent"] == "explore"
    assert response["action"] == "Move"
    assert response["dir"] == "E"
    assert response["reason_code"] == "canned_no_llm"


@pytest.mark.asyncio
async def test_canned_policy_uses_first_unblocked_direction() -> None:
    server = await start_probe_server(ServerConfig(host="127.0.0.1", port=0))
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(
                json.dumps(with_blocked_dirs(minimal_decision_input(), ["E", "SE"])),
            )
            response = json.loads(await websocket.recv())
    finally:
        await server.close()

    assert response["intent"] == "explore"
    assert response["action"] == "Move"
    assert response["dir"] == "NE"
    assert response["reason_code"] == "canned_no_llm"


@pytest.mark.asyncio
async def test_disconnect_phase_closes_socket_without_response() -> None:
    server = await start_probe_server(
        ServerConfig(host="127.0.0.1", port=0, initial_phase="disconnect"),
    )
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(json.dumps(minimal_decision_input()))
            with pytest.raises(ConnectionClosed):
                await websocket.recv()
    finally:
        await server.close()


def test_phase1_acceptance_script_disconnects_once_then_recovers() -> None:
    assert [phase_for_phase1_acceptance(i) for i in range(1, 9)] == [
        PHASE_ACCEPTANCE_ECHO,
        PHASE_ACCEPTANCE_ECHO,
        PHASE_ACCEPTANCE_ECHO,
        PHASE_ACCEPTANCE_ECHO,
        PHASE_ACCEPTANCE_ECHO,
        "disconnect",
        PHASE_ACCEPTANCE_ECHO,
        PHASE_ACCEPTANCE_ECHO,
    ]


@pytest.mark.asyncio
async def test_phase1_acceptance_script_oscillates_to_avoid_zone_edge() -> None:
    server = await start_probe_server(
        ServerConfig(host="127.0.0.1", port=0, initial_phase="phase_script:phase1-pr1-acceptance"),
    )
    try:
        async with connect(f"ws://127.0.0.1:{server.port}") as websocket:
            await websocket.send(json.dumps(with_blocked_dirs(minimal_decision_input(turn=1), [])))
            first = json.loads(await websocket.recv())
            await websocket.send(json.dumps(with_blocked_dirs(minimal_decision_input(turn=2), [])))
            second = json.loads(await websocket.recv())
    finally:
        await server.close()

    assert first["dir"] == "E"
    assert second["dir"] == "W"


def test_probe_server_disables_websocket_keepalive_for_chargen_idle() -> None:
    source = (ROOT / "brain/app.py").read_text()

    assert "ping_interval=None" in source
