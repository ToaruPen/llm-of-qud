"""Provider-neutral protocol messages for Phase 1 PR-2.

See docs/superpowers/plans/2026-04-29-phase-1-pr-2-protocol-core.md.
"""

# mypy: disable-error-code=explicit-any
from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

TERMINAL_ACTION_TOOLS = frozenset({"execute", "navigate_to", "choose"})


def is_terminal_action_tool(tool: str) -> bool:
    return tool in TERMINAL_ACTION_TOOLS


class ToolResultStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class ToolResultMissingErrorCodeError(ValueError):
    def __init__(self) -> None:
        super().__init__("error status requires result.error_code")


class ToolResultMissingErrorMessageError(ValueError):
    def __init__(self) -> None:
        super().__init__("error status requires result.error_message")


class TerminalToolCallMissingActionNonceError(ValueError):
    def __init__(self) -> None:
        super().__init__("terminal tool_call requires action_nonce")


class TerminalToolCallMissingStateVersionError(ValueError):
    def __init__(self) -> None:
        super().__init__("terminal tool_call requires state_version")


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str | None = None
    request_id: str | None = None
    response_id: str | None = None
    raw: JsonObject | None = None


class ToolResultPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ToolResultStatus
    output: JsonValue = None
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def require_error_details(self) -> Self:
        if self.status is not ToolResultStatus.ERROR:
            return self
        if self.error_code is None:
            raise ToolResultMissingErrorCodeError
        if self.error_message is None:
            raise ToolResultMissingErrorMessageError
        return self


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
            raise TerminalToolCallMissingActionNonceError
        if self.state_version is None:
            raise TerminalToolCallMissingStateVersionError
        return self


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


class SupervisorRequestMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_type: Literal["supervisor_request"] = Field(
        default="supervisor_request",
        alias="type",
    )
    session_epoch: int
    message_id: str
    tid: int
    reason: str
    game_state: str | None = None
    modal: JsonObject | None = None
    diagnostic: str | None = None
    timeout_s: int | None = None


class SupervisorResponseMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    message_type: Literal["supervisor_response"] = Field(
        default="supervisor_response",
        alias="type",
    )
    session_epoch: int
    message_id: str
    in_reply_to: str
    action: Literal["select", "resume", "abort"]
    choice_id: str | None = None
    reason: str | None = None
