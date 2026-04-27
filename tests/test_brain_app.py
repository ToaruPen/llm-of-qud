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

from brain.app import ServerConfig, start_probe_server


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
