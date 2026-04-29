from __future__ import annotations

import json
import sys
from time import perf_counter
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.app import PHASE_ACCEPTANCE_ECHO, ServerConfig, phase_for_phase1_acceptance, start_probe_server


def minimal_decision_input(turn: int = 7) -> dict[str, object]:
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


def with_adjacent_hostile(payload: dict[str, object], direction: str) -> dict[str, object]:
    adjacent = payload["adjacent"]
    assert isinstance(adjacent, dict)
    adjacent["hostile_dir"] = direction
    adjacent["hostile_id"] = "hostile-1"
    return payload


def with_blocked_dirs(payload: dict[str, object], blocked_dirs: list[str]) -> dict[str, object]:
    adjacent = payload["adjacent"]
    assert isinstance(adjacent, dict)
    adjacent["blocked_dirs"] = blocked_dirs
    return payload


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
