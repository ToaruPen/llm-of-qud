"""Phase 1 PR-1 WebSocket probe server.

See docs/architecture-v5.md:1838-1864.
"""

# mypy: disable-error-code=explicit-any
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from typing import TYPE_CHECKING, TypeGuard, cast

import structlog
from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.server import Server, ServerConnection, serve

from brain.protocol import JsonObject as ProtocolJsonObject
from brain.protocol import ToolCallMessage, ToolResultMessage

if TYPE_CHECKING:
    from collections.abc import Mapping


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 4040
DEFAULT_PHASE = "echo"
PHASE_COMMAND_PREFIX = "PHASE "
PHASE_SCRIPT_PR1 = "phase1-pr1"
PHASE_SCRIPT_PR1_ACCEPTANCE = "phase1-pr1-acceptance"
PHASE_ACCEPTANCE_ECHO = f"{PHASE_SCRIPT_PR1_ACCEPTANCE}:echo"
TOOL_CALL_PROBE_PHASE_PREFIX = "tool_call_probe:"
TOOL_CALL_PROBE_MALFORMED_ARGS_PHASE_PREFIX = "tool_call_probe_malformed_args:"
MALFORMED_TOOL_ARGS_ERROR_CODE = "invalid_tool_args"
ACCEPTANCE_DISCONNECT_REQUEST = 6
EXPLORE_DIR_ORDER = ("E", "SE", "NE", "S", "N", "W", "SW", "NW")
VALID_COMPASS_DIRS = frozenset(EXPLORE_DIR_ORDER)
TERMINAL_ACTIONS = frozenset({"execute", "navigate_to", "choose", "cancel_or_back"})
PROBE_SESSION_EPOCH = 1
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


class UnsupportedDecisionInputSchemaError(ValueError):
    def __init__(self, schema: str) -> None:
        super().__init__(f"unsupported decision input schema: {schema}")


class ProbeServerNotListeningError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("no listening sockets available on RunningProbeServer")


class UnsupportedPhaseError(ValueError):
    def __init__(self, phase: str) -> None:
        super().__init__(f"unsupported phase: {phase}")


class InvalidSleepPhaseError(ValueError):
    def __init__(self, phase: str) -> None:
        super().__init__(f"invalid sleep value for phase: {phase}")


class NegativeSleepPhaseError(ValueError):
    def __init__(self, phase: str) -> None:
        super().__init__(f"negative sleep value for phase: {phase}")


class MultipleTerminalActionsError(ValueError):
    def __init__(self, tools: list[str]) -> None:
        super().__init__(f"multiple terminal actions cannot be emitted in parallel: {tools}")


class ToolResultMismatchError(ValueError):
    def __init__(self, field: str, expected: str | None, actual: str | None) -> None:
        super().__init__(f"tool_result {field} mismatch: expected {expected!r}, got {actual!r}")


class DecisionInputPayloadTypeError(TypeError):
    def __init__(self, value: object) -> None:
        super().__init__(
            f"parse_decision_input: expected JSON object, got {json_type_name(value)}",
        )


class JsonFieldTypeError(TypeError):
    def __init__(self, helper: str, key: str, expected: str, value: object) -> None:
        super().__init__(
            f"{helper}: expected key {key!r} to be {expected}, got {json_type_name(value)}",
        )


class ServerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    initial_phase: str = DEFAULT_PHASE


class DecisionInputSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    hp: int | None
    max_hp: int | None
    adjacent_hostile_dir: str | None
    blocked_dirs: tuple[str, ...]
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
            if self._phase == f"phase_script:{PHASE_SCRIPT_PR1_ACCEPTANCE}":
                return phase_for_phase1_acceptance(self._request_count)
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
            raise ProbeServerNotListeningError()
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

    server = await serve(handler, config.host, config.port, ping_interval=None)
    return RunningProbeServer(server, controller, config.host)


async def handle_connection(connection: ServerConnection, controller: PhaseController) -> None:
    logger.info("connection_open")
    close_reason = "normal"
    close_already_logged = False
    try:
        async for message in connection:
            phase = await controller.current_for_request()
            request = parse_decision_input(message)
            logger.info(
                "decision_request",
                turn=request.turn,
                schema=request.request_schema,
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
        close_already_logged = True
        raise
    finally:
        if not close_already_logged:
            logger.info("connection_close", reason=close_reason)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    turn: int
    request_schema: str = Field(alias="schema")
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
    if is_tool_call_probe_phase(phase):
        result = await emit_probe_tool_call(connection, request, phase)
        response = canned_decision(request, phase)
        response["tool_result"] = cast(
            "JsonValue",
            result.result.model_dump(mode="json", exclude_none=True),
        )
        await connection.send(json.dumps(response, separators=(",", ":")))
        logger.info("decision_response", turn=request.turn, delay_ms=0)
        return "normal"

    delay_ms = delay_for_phase(phase)
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)

    await connection.send(json.dumps(canned_decision(request, phase), separators=(",", ":")))
    logger.info("decision_response", turn=request.turn, delay_ms=delay_ms)
    return "normal"


def delay_for_phase(phase: str) -> int:
    if phase in {"echo", PHASE_ACCEPTANCE_ECHO}:
        return 0
    if phase.startswith("sleep:"):
        return parse_delay_ms(phase)
    raise UnsupportedPhaseError(phase)


def is_tool_call_probe_phase(phase: str) -> bool:
    return phase.startswith(
        (TOOL_CALL_PROBE_PHASE_PREFIX, TOOL_CALL_PROBE_MALFORMED_ARGS_PHASE_PREFIX),
    )


async def emit_probe_tool_call(
    connection: ServerConnection,
    request: DecisionRequest,
    phase: str,
) -> ToolResultMessage:
    tool = tool_name_for_probe_phase(phase)
    args: ProtocolJsonObject = (
        {"candidate_id": 123}
        if phase.startswith(TOOL_CALL_PROBE_MALFORMED_ARGS_PHASE_PREFIX)
        else {}
    )
    (tool_call,) = build_tool_call_messages(
        [{"tool": tool, "args": args}],
        turn=request.turn,
        session_epoch=PROBE_SESSION_EPOCH,
    )
    return await emit_tool_call(connection, tool_call)


def tool_name_for_probe_phase(phase: str) -> str:
    if phase.startswith(TOOL_CALL_PROBE_MALFORMED_ARGS_PHASE_PREFIX):
        return phase.removeprefix(TOOL_CALL_PROBE_MALFORMED_ARGS_PHASE_PREFIX)
    if phase.startswith(TOOL_CALL_PROBE_PHASE_PREFIX):
        return phase.removeprefix(TOOL_CALL_PROBE_PHASE_PREFIX)
    raise UnsupportedPhaseError(phase)


async def emit_tool_call(
    connection: ServerConnection,
    tool_call: ToolCallMessage,
) -> ToolResultMessage:
    await connection.send(tool_call.model_dump_json(by_alias=True, exclude_none=True))
    raw_result = await connection.recv()
    text = raw_result.decode("utf-8") if isinstance(raw_result, bytes) else raw_result
    result = ToolResultMessage.model_validate(json.loads(text))
    require_matching_tool_result(tool_call, result)
    return result


def require_matching_tool_result(
    tool_call: ToolCallMessage,
    tool_result: ToolResultMessage,
) -> None:
    if tool_result.call_id != tool_call.call_id:
        raise ToolResultMismatchError("call_id", tool_call.call_id, tool_result.call_id)
    if tool_result.tool != tool_call.tool:
        raise ToolResultMismatchError("tool", tool_call.tool, tool_result.tool)
    if tool_result.in_reply_to != tool_call.message_id:
        raise ToolResultMismatchError("in_reply_to", tool_call.message_id, tool_result.in_reply_to)


def build_tool_call_messages(
    provider_tool_calls: list[dict[str, object]],
    *,
    turn: int,
    session_epoch: int,
) -> tuple[ToolCallMessage, ...]:
    tool_names = [
        require_provider_tool_name(call, index)
        for index, call in enumerate(provider_tool_calls, start=1)
    ]
    terminal_tools = [tool for tool in tool_names if tool in TERMINAL_ACTIONS]
    if len(terminal_tools) > 1:
        raise MultipleTerminalActionsError(terminal_tools)

    messages: list[ToolCallMessage] = []
    for index, (call, tool) in enumerate(
        zip(provider_tool_calls, tool_names, strict=True), start=1
    ):
        call_id = optional_provider_string(call, "call_id") or f"turn-{turn}-call-{index}"
        messages.append(
            ToolCallMessage(
                call_id=call_id,
                tool=tool,
                args=require_protocol_json_object(
                    call.get("args", {}),
                    f"provider_tool_calls[{index}].args",
                ),
                message_id=f"msg-{turn}-tool-call-{index}",
                session_epoch=session_epoch,
            ),
        )
    return tuple(messages)


def require_provider_tool_name(call: dict[str, object], index: int) -> str:
    value = call.get("tool", call.get("name"))
    if not isinstance(value, str):
        raise JsonFieldTypeError(
            "require_provider_tool_name",
            f"provider_tool_calls[{index}].tool",
            "string",
            value,
        )
    return value


def optional_provider_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise JsonFieldTypeError("optional_provider_string", key, "string or None", value)


def require_protocol_json_object(value: object, key: str) -> ProtocolJsonObject:
    if is_json_object(value):
        return value
    raise JsonFieldTypeError("require_protocol_json_object", key, "JSON object", value)


def parse_delay_ms(phase: str) -> int:
    value = phase.removeprefix("sleep:")
    try:
        delay_ms = int(value)
    except ValueError as exc:
        raise InvalidSleepPhaseError(phase) from exc
    if delay_ms < 0:
        raise NegativeSleepPhaseError(phase)
    return delay_ms


def phase_for_phase1_pr1(request_count: int) -> str:
    for end_count, phase in SCRIPT_PHASES:
        if request_count <= end_count:
            return phase
    return "disconnect"


def phase_for_phase1_acceptance(request_count: int) -> str:
    if request_count == ACCEPTANCE_DISCONNECT_REQUEST:
        return "disconnect"
    return PHASE_ACCEPTANCE_ECHO


def canned_decision(request: DecisionRequest, phase: str = "echo") -> dict[str, JsonValue]:
    summary = request.summary
    hostile_dir = normalize_hostile_dir(summary.adjacent_hostile_dir)
    if hostile_dir is not None:
        intent = "attack"
        action = "AttackDirection"
        direction = hostile_dir
        reason_code = "canned_adjacent_hostile"
    else:
        intent = "explore"
        action = "Move"
        direction = (
            acceptance_dir(request.turn, summary.blocked_dirs)
            if phase == PHASE_ACCEPTANCE_ECHO
            else first_unblocked_dir(summary.blocked_dirs)
        )
        reason_code = "canned_no_llm"
    return {
        "turn": request.turn,
        "schema": "decision.v1",
        "input_summary": {
            "hp": summary.hp,
            "max_hp": summary.max_hp,
            "adjacent_hostile_dir": hostile_dir,
            "blocked_dirs_count": summary.blocked_dirs_count,
        },
        "intent": intent,
        "action": action,
        "dir": direction,
        "reason_code": reason_code,
        "error": None,
    }


def first_unblocked_dir(blocked_dirs: tuple[str, ...]) -> str:
    blocked = set(blocked_dirs)
    for direction in EXPLORE_DIR_ORDER:
        if direction not in blocked:
            return direction
    return EXPLORE_DIR_ORDER[0]


def acceptance_dir(turn: int, blocked_dirs: tuple[str, ...]) -> str:
    desired = "E" if turn % 2 else "W"
    if desired not in blocked_dirs:
        return desired
    return first_unblocked_dir(blocked_dirs)


def normalize_hostile_dir(direction: str | None) -> str | None:
    if direction in VALID_COMPASS_DIRS:
        return direction
    return None


def parse_decision_input(message: str | bytes) -> DecisionRequest:
    text = message.decode("utf-8") if isinstance(message, bytes) else message
    parsed = json.loads(text)
    if not is_json_object(parsed):
        raise DecisionInputPayloadTypeError(parsed)

    schema = require_string(parsed, "schema")
    if schema != "decision_input.v1":
        raise UnsupportedDecisionInputSchemaError(schema)
    turn = require_int(parsed, "turn")
    player = require_object(parsed, "player")
    adjacent = require_object(parsed, "adjacent")
    blocked_dirs = require_list(adjacent, "blocked_dirs")
    blocked_dir_strings = tuple(
        require_json_string(item, f"blocked_dirs[{index}]")
        for index, item in enumerate(blocked_dirs)
    )
    adjacent_hostile_dir = normalize_hostile_dir(optional_string(adjacent, "hostile_dir"))
    return DecisionRequest(
        turn=turn,
        schema=schema,
        summary=DecisionInputSummary(
            hp=optional_int(player, "hp"),
            max_hp=optional_int(player, "max_hp"),
            adjacent_hostile_dir=adjacent_hostile_dir,
            blocked_dirs=blocked_dir_strings,
            blocked_dirs_count=len(blocked_dir_strings),
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


def json_type_name(value: object) -> str:
    if value is None:
        return "None"
    return type(value).__name__


def require_object(payload: Mapping[str, JsonValue], key: str) -> Mapping[str, JsonValue]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise JsonFieldTypeError("require_object", key, "object", value)
    return value


def require_list(payload: Mapping[str, JsonValue], key: str) -> list[JsonValue]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise JsonFieldTypeError("require_list", key, "list", value)
    return value


def require_string(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise JsonFieldTypeError("require_string", key, "string", value)
    return value


def require_json_string(value: JsonValue, key: str = "<value>") -> str:
    if not isinstance(value, str):
        raise JsonFieldTypeError("require_json_string", key, "string", value)
    return value


def optional_string(payload: Mapping[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise JsonFieldTypeError("optional_string", key, "string or None", value)


def require_int(payload: Mapping[str, JsonValue], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise JsonFieldTypeError("require_int", key, "int", value)
    return value


def optional_int(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise JsonFieldTypeError("optional_int", key, "int or None", value)
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
