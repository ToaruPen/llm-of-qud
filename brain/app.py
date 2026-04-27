from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeGuard, cast

import structlog
from websockets.asyncio.server import Server, ServerConnection, serve

if TYPE_CHECKING:
    from collections.abc import Mapping


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4040
DEFAULT_PHASE = "echo"
PHASE_COMMAND_PREFIX = "PHASE "
PHASE_SCRIPT_PR1 = "phase1-pr1"
SCRIPT_PROBE_1_TURNS = 25
SCRIPT_PROBE_6_END = 160
SCRIPT_TIMEOUT_END = 210
SCRIPT_PHASES: tuple[tuple[int, str], ...] = (
    (SCRIPT_PROBE_1_TURNS, "echo"),
    (SCRIPT_PROBE_1_TURNS * 2, "sleep:50"),
    (SCRIPT_PROBE_1_TURNS * 3, "sleep:100"),
    (SCRIPT_PROBE_1_TURNS * 4, "sleep:250"),
    (SCRIPT_PROBE_6_END, "sleep:200"),
    (SCRIPT_TIMEOUT_END, "sleep:10000"),
)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ServerConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    initial_phase: str = DEFAULT_PHASE


@dataclass(frozen=True)
class DecisionInputSummary:
    hp: int | None
    max_hp: int | None
    adjacent_hostile_dir: str | None
    blocked_dirs_count: int


class PhaseController:
    def __init__(self, initial_phase: str) -> None:
        self._phase = initial_phase
        self._request_count = 0
        self._lock = asyncio.Lock()

    async def current_for_request(self) -> str:
        async with self._lock:
            self._request_count += 1
            if self._phase == f"phase_script:{PHASE_SCRIPT_PR1}":
                return phase_for_phase1_pr1(self._request_count)
            return self._phase

    async def switch(self, phase: str) -> None:
        async with self._lock:
            self._phase = phase
            self._request_count = 0
        logger.info("phase_switch", phase=phase)


class RunningProbeServer:
    def __init__(self, server: Server, controller: PhaseController, host: str) -> None:
        self._server = server
        self._controller = controller
        self.host = host

    @property
    def port(self) -> int:
        sockets = self._server.sockets
        if not sockets:
            raise RuntimeError
        return int(sockets[0].getsockname()[1])

    async def switch_phase(self, phase: str) -> None:
        await self._controller.switch(phase)

    def create_admin_task(self) -> asyncio.Task[None]:
        return asyncio.create_task(stdin_admin_loop(self._controller))

    async def close(self) -> None:
        self._server.close()
        await self._server.wait_closed()


async def start_probe_server(config: ServerConfig) -> RunningProbeServer:
    controller = PhaseController(config.initial_phase)

    async def handler(connection: ServerConnection) -> None:
        await handle_connection(connection, controller)

    server = await serve(handler, config.host, config.port)
    return RunningProbeServer(server, controller, config.host)


async def handle_connection(connection: ServerConnection, controller: PhaseController) -> None:
    logger.info("connection_open")
    close_reason = "normal"
    try:
        async for message in connection:
            phase = await controller.current_for_request()
            request = parse_decision_input(message)
            logger.info(
                "decision_request",
                turn=request.turn,
                schema=request.schema,
                phase=phase,
            )
            close_reason = await respond_for_phase(connection, request, phase)
            if close_reason != "normal":
                return
    except asyncio.CancelledError:
        close_reason = "cancelled"
        raise
    except Exception as exc:
        close_reason = type(exc).__name__
        logger.warning("connection_close", reason=close_reason)
        raise
    finally:
        logger.info("connection_close", reason=close_reason)


@dataclass(frozen=True)
class DecisionRequest:
    turn: int
    schema: str
    summary: DecisionInputSummary


async def respond_for_phase(
    connection: ServerConnection,
    request: DecisionRequest,
    phase: str,
) -> str:
    if phase == "disconnect":
        await connection.close(reason="probe_disconnect")
        return "probe_disconnect"
    if phase == "late_stale":
        await connection.close(reason="probe_late_stale")
        await asyncio.sleep(0.05)
        return "probe_late_stale"

    delay_ms = delay_for_phase(phase)
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    await connection.send(json.dumps(canned_decision(request), separators=(",", ":")))
    logger.info("decision_response", turn=request.turn, delay_ms=delay_ms)
    return "normal"


def delay_for_phase(phase: str) -> int:
    if phase == "echo":
        return 0
    if phase.startswith("sleep:"):
        return parse_delay_ms(phase)
    raise ValueError


def parse_delay_ms(phase: str) -> int:
    value = phase.removeprefix("sleep:")
    delay_ms = int(value)
    if delay_ms < 0:
        raise ValueError
    return delay_ms


def phase_for_phase1_pr1(request_count: int) -> str:
    for end_count, phase in SCRIPT_PHASES:
        if request_count <= end_count:
            return phase
    return "disconnect"


def canned_decision(request: DecisionRequest) -> dict[str, JsonValue]:
    summary = request.summary
    return {
        "turn": request.turn,
        "schema": "decision.v1",
        "input_summary": {
            "hp": summary.hp,
            "max_hp": summary.max_hp,
            "adjacent_hostile_dir": summary.adjacent_hostile_dir,
            "blocked_dirs_count": summary.blocked_dirs_count,
        },
        "intent": "explore",
        "action": "Move",
        "dir": "E",
        "reason_code": "canned_no_llm",
        "error": None,
    }


def parse_decision_input(message: str | bytes) -> DecisionRequest:
    text = message.decode("utf-8") if isinstance(message, bytes) else message
    parsed = json.loads(text)
    if not is_json_object(parsed):
        raise TypeError

    schema = require_string(parsed, "schema")
    turn = require_int(parsed, "turn")
    player = require_object(parsed, "player")
    adjacent = require_object(parsed, "adjacent")
    blocked_dirs = require_list(adjacent, "blocked_dirs")
    return DecisionRequest(
        turn=turn,
        schema=schema,
        summary=DecisionInputSummary(
            hp=optional_int(player, "hp"),
            max_hp=optional_int(player, "max_hp"),
            adjacent_hostile_dir=optional_string(adjacent, "hostile_dir"),
            blocked_dirs_count=len(blocked_dirs),
        ),
    )


def is_json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    if not isinstance(value, dict):
        return False
    for key, item in cast("dict[object, object]", value).items():
        if not isinstance(key, str) or not is_json_value(item):
            return False
    return True


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in cast("list[object]", value))
    return is_json_object(value)


def require_object(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise TypeError
    return value


def require_list(payload: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TypeError
    return value


def require_string(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError
    return value


def optional_string(payload: Mapping[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise TypeError


def require_int(payload: Mapping[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def optional_int(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


async def stdin_admin_loop(controller: PhaseController) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return
        stripped = line.strip()
        if stripped.startswith(PHASE_COMMAND_PREFIX):
            await controller.switch(stripped.removeprefix(PHASE_COMMAND_PREFIX))


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    parser = argparse.ArgumentParser(description="LLM-of-Qud Phase 1 PR-1 probe server")
    parser.add_argument("--phase", default=DEFAULT_PHASE)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parsed = parser.parse_args(argv)
    return ServerConfig(port=parsed.port, initial_phase=parsed.phase)


async def run(config: ServerConfig) -> None:
    server = await start_probe_server(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    admin_task = server.create_admin_task()
    try:
        await stop.wait()
    finally:
        admin_task.cancel()
        await server.close()


def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(0))
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
