from __future__ import annotations

# ruff: noqa: E402, PLR2004, S101
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.protocol import (
    JsonObject,
    ProviderMetadata,
    SupervisorRequestMessage,
    SupervisorResponseMessage,
    ToolCallMessage,
    ToolResultMessage,
    ToolResultPayload,
    ToolResultStatus,
)


def test_tool_call_requires_stable_call_id() -> None:
    base_message: JsonObject = {
        "type": "tool_call",
        "call_id": "turn-7-call-1",
        "tool": "inspect_surroundings",
        "args": {},
        "message_id": "msg-7-call-1",
        "session_epoch": 3,
    }

    with pytest.raises(ValidationError, match="call_id"):
        ToolCallMessage.model_validate(
            {
                "type": "tool_call",
                "tool": "inspect_surroundings",
                "args": {},
                "message_id": "msg-7-call-1",
                "session_epoch": 3,
            },
        )
    with pytest.raises(ValidationError, match="message_id"):
        ToolCallMessage.model_validate(base_message | {"message_id": None})
    with pytest.raises(ValidationError, match="session_epoch"):
        ToolCallMessage.model_validate(base_message | {"session_epoch": None})

    message = ToolCallMessage.model_validate(base_message)

    assert message.call_id == "turn-7-call-1"
    assert message.message_id == "msg-7-call-1"
    assert message.session_epoch == 3
    assert message.model_copy().call_id == "turn-7-call-1"


def test_tool_result_requires_top_level_result_object_and_correlation_fields() -> None:
    base_message = {
        "type": "tool_result",
        "call_id": "turn-7-call-1",
        "tool": "inspect_surroundings",
        "result": {"status": "ok", "output": {"visible_tiles": 8}},
        "message_id": "msg-7-result-1",
        "in_reply_to": "msg-7-call-1",
        "session_epoch": 3,
    }

    with pytest.raises(ValidationError, match="result"):
        ToolResultMessage.model_validate(
            {
                "type": "tool_result",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "status": "ok",
                "message_id": "msg-7-result-1",
                "in_reply_to": "msg-7-call-1",
                "session_epoch": 3,
            },
        )
    with pytest.raises(ValidationError, match="message_id"):
        ToolResultMessage.model_validate(base_message | {"message_id": None})
    with pytest.raises(ValidationError, match="in_reply_to"):
        ToolResultMessage.model_validate(base_message | {"in_reply_to": None})
    with pytest.raises(ValidationError, match="session_epoch"):
        ToolResultMessage.model_validate(base_message | {"session_epoch": None})

    message = ToolResultMessage.model_validate(base_message)

    assert message.result.status is ToolResultStatus.OK
    assert message.result.output == {"visible_tiles": 8}


def test_emit_tool_call_result_preserves_in_reply_to_message_id() -> None:
    message = ToolResultMessage.model_validate(
        {
            "type": "tool_result",
            "call_id": "turn-7-call-1",
            "tool": "inspect_surroundings",
            "result": {"status": "ok", "output": {"visible_tiles": 8}},
            "message_id": "msg-7-result-1",
            "in_reply_to": "msg-7-call-1",
            "session_epoch": 3,
        },
    )

    assert message.in_reply_to == "msg-7-call-1"
    assert message.message_id == "msg-7-result-1"
    assert message.session_epoch == 3


def test_tool_result_status_accepts_only_ok_or_error() -> None:
    ToolResultPayload.model_validate({"status": "ok", "output": {"visible_tiles": 8}})
    ToolResultPayload.model_validate(
        {"status": "error", "error_code": "mod_failure", "error_message": "boom"}
    )

    with pytest.raises(ValidationError, match="status"):
        ToolResultPayload.model_validate({"status": "retry"})


def test_error_tool_result_requires_error_code_and_message() -> None:
    with pytest.raises(ValidationError, match="error_code"):
        ToolResultPayload.model_validate({"status": "error", "error_message": "boom"})

    with pytest.raises(ValidationError, match="error_message"):
        ToolResultPayload.model_validate({"status": "error", "error_code": "mod_failure"})


def test_provider_metadata_is_optional_and_nested() -> None:
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
    assert message.metadata is None

    with_metadata = ToolCallMessage.model_validate(
        {
            "type": "tool_call",
            "call_id": "turn-7-call-1",
            "tool": "inspect_surroundings",
            "args": {},
            "message_id": "msg-7-call-1",
            "session_epoch": 3,
            "metadata": {
                "provider": "openai",
                "raw": {"openai_call_id": "call_abc", "anthropic_tool_use_id": "toolu_abc"},
            },
        },
    )

    assert isinstance(with_metadata.metadata, ProviderMetadata)
    assert with_metadata.metadata.raw == {
        "openai_call_id": "call_abc",
        "anthropic_tool_use_id": "toolu_abc",
    }


def test_provider_specific_ids_are_not_top_level_protocol_fields() -> None:
    with pytest.raises(ValidationError, match="openai_call_id"):
        ToolCallMessage.model_validate(
            {
                "type": "tool_call",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "args": {},
                "message_id": "msg-7-call-1",
                "session_epoch": 3,
                "openai_call_id": "call_abc",
            },
        )

    with pytest.raises(ValidationError, match="anthropic_tool_use_id"):
        ToolResultMessage.model_validate(
            {
                "type": "tool_result",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "result": {"status": "ok", "output": None},
                "message_id": "msg-7-result-1",
                "in_reply_to": "msg-7-call-1",
                "session_epoch": 3,
                "anthropic_tool_use_id": "toolu_abc",
            },
        )


def test_tool_call_rejects_legacy_top_level_tid() -> None:
    with pytest.raises(ValidationError, match="tid"):
        ToolCallMessage.model_validate(
            {
                "type": "tool_call",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "args": {},
                "message_id": "msg-7-call-1",
                "session_epoch": 3,
                "tid": 142,
            },
        )


def test_tool_result_rejects_legacy_top_level_tid() -> None:
    with pytest.raises(ValidationError, match="tid"):
        ToolResultMessage.model_validate(
            {
                "type": "tool_result",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "result": {"status": "ok", "output": None},
                "message_id": "msg-7-result-1",
                "in_reply_to": "msg-7-call-1",
                "session_epoch": 3,
                "tid": 142,
            },
        )


def test_multiple_tool_calls_are_structurally_representable_as_a_list() -> None:
    calls = [
        ToolCallMessage.model_validate(
            {
                "type": "tool_call",
                "call_id": "turn-7-call-1",
                "tool": "inspect_surroundings",
                "args": {},
                "message_id": "msg-7-call-1",
                "session_epoch": 3,
            },
        ),
        ToolCallMessage.model_validate(
            {
                "type": "tool_call",
                "call_id": "turn-7-call-2",
                "tool": "check_status",
                "args": {},
                "message_id": "msg-7-call-2",
                "session_epoch": 3,
            },
        ),
    ]

    assert [call.call_id for call in calls] == ["turn-7-call-1", "turn-7-call-2"]


def test_supervisor_messages_are_non_tool_envelopes_with_modal_payload() -> None:
    request = SupervisorRequestMessage.model_validate(
        {
            "type": "supervisor_request",
            "session_epoch": 3,
            "message_id": "msg-sup-1",
            "tid": 142,
            "reason": "level_up",
            "game_state": "modal",
            "modal": {
                "type": "level_up",
                "title": "Level Up!",
                "prompt": "Choose a mutation to acquire:",
                "choices": [
                    {
                        "id": "ch1",
                        "label": "Flaming Hands",
                        "is_default": False,
                        "is_irreversible": True,
                    },
                ],
                "fallback_choice_id": None,
            },
            "timeout_s": 300,
        },
    )
    response = SupervisorResponseMessage.model_validate(
        {
            "type": "supervisor_response",
            "session_epoch": 3,
            "message_id": "msg-sup-resp-1",
            "in_reply_to": "msg-sup-1",
            "action": "select",
            "choice_id": "ch1",
            "reason": "Preserve the intended fire build.",
        },
    )

    assert request.message_type == "supervisor_request"
    assert request.message_type not in {"tool_call", "tool_result"}
    assert request.modal is not None
    assert request.modal["prompt"] == "Choose a mutation to acquire:"
    assert request.modal["choices"] == [
        {
            "id": "ch1",
            "label": "Flaming Hands",
            "is_default": False,
            "is_irreversible": True,
        },
    ]
    assert response.message_type == "supervisor_response"
    assert response.in_reply_to == request.message_id
    assert response.action == "select"
    assert response.choice_id == "ch1"


def test_supervisor_messages_reject_tool_envelope_fields() -> None:
    with pytest.raises(ValidationError, match="tool"):
        SupervisorRequestMessage.model_validate(
            {
                "type": "supervisor_request",
                "session_epoch": 3,
                "message_id": "msg-sup-1",
                "tid": 142,
                "reason": "level_up",
                "tool": "choose",
            },
        )
