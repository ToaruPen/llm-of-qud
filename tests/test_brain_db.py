# ruff: noqa: S101

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import aiosqlite
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.db.writer import (  # noqa: E402
    ErrorRetryTelemetry,
    ProviderTelemetry,
    TelemetryWriter,
    TelemetryWriterConfig,
)

TableName = Literal[
    "connection_lifecycle",
    "decision_request",
    "decision_response",
    "disconnect_pause",
    "reconnect_wake",
]

TABLE_COUNT_QUERIES: dict[TableName, str] = {
    "connection_lifecycle": "SELECT COUNT(*) FROM connection_lifecycle",
    "decision_request": "SELECT COUNT(*) FROM decision_request",
    "decision_response": "SELECT COUNT(*) FROM decision_response",
    "disconnect_pause": "SELECT COUNT(*) FROM disconnect_pause",
    "reconnect_wake": "SELECT COUNT(*) FROM reconnect_wake",
}


async def table_count(db_path: Path, table: TableName) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(TABLE_COUNT_QUERIES[table])
        row = await cursor.fetchone()
    assert row is not None
    count = row[0]
    assert isinstance(count, int)
    return count


async def fetch_one(db_path: Path, query: str) -> aiosqlite.Row:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(query)
        row = await cursor.fetchone()
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_telemetry_writer_creates_schema_and_records_all_pr1_events(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "telemetry.db"
    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_connection_lifecycle(event="OPEN", detail="connected")
        await writer.record_decision_request(
            turn=1,
            schema="decision_input.v1",
            payload_size_bytes=128,
        )
        await writer.record_decision_response(
            turn=1,
            schema="decision.v1",
            delay_ms=50,
            error=None,
        )
        await writer.record_disconnect_pause(turn=2, reason="socket_close")
        await writer.record_reconnect_wake(turn=3, mechanism="PUSH_KEY_NONE")
    finally:
        await writer.close()

    assert await table_count(db_path, "connection_lifecycle") == 1
    assert await table_count(db_path, "decision_request") == 1
    assert await table_count(db_path, "decision_response") == 1
    assert await table_count(db_path, "disconnect_pause") == 1
    assert await table_count(db_path, "reconnect_wake") == 1


@pytest.mark.asyncio
async def test_telemetry_writer_records_tool_call_sent_and_received(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"
    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_tool_call_sent(
            call_id="call-1",
            tool="inspect_surroundings",
            provider=ProviderTelemetry(
                provider_name="fixture-provider",
                provider_response_id="resp-1",
                provider_item_id="item-1",
                provider_input_tokens=120,
                provider_output_tokens=24,
                provider_cached_input_tokens=80,
                provider_cache_creation_input_tokens=None,
                provider_cache_read_input_tokens=80,
            ),
        )
        await writer.record_tool_call_received(
            call_id="call-1",
            tool="inspect_surroundings",
            result_status="ok",
            latency_ms=42,
            classification=ErrorRetryTelemetry(
                error_class=None,
                retry_class=None,
                retry_attempt=0,
            ),
        )
        await writer.record_tool_call_sent(call_id="call-2", tool="check_status")
    finally:
        await writer.close()

    sent = await fetch_one(
        db_path,
        """
        SELECT call_id, tool, provider_name, provider_response_id, provider_item_id,
               provider_input_tokens, provider_output_tokens,
               provider_cached_input_tokens, provider_cache_creation_input_tokens,
               provider_cache_read_input_tokens
        FROM tool_call_sent
        WHERE call_id = 'call-1'
        """,
    )
    assert dict(sent) == {
        "call_id": "call-1",
        "tool": "inspect_surroundings",
        "provider_name": "fixture-provider",
        "provider_response_id": "resp-1",
        "provider_item_id": "item-1",
        "provider_input_tokens": 120,
        "provider_output_tokens": 24,
        "provider_cached_input_tokens": 80,
        "provider_cache_creation_input_tokens": None,
        "provider_cache_read_input_tokens": 80,
    }
    minimal_sent = await fetch_one(
        db_path,
        """
        SELECT provider_name, provider_response_id, provider_item_id,
               provider_cached_input_tokens, provider_cache_creation_input_tokens,
               provider_cache_read_input_tokens
        FROM tool_call_sent
        WHERE call_id = 'call-2'
        """,
    )
    assert dict(minimal_sent) == {
        "provider_name": None,
        "provider_response_id": None,
        "provider_item_id": None,
        "provider_cached_input_tokens": None,
        "provider_cache_creation_input_tokens": None,
        "provider_cache_read_input_tokens": None,
    }
    received = await fetch_one(
        db_path,
        """
        SELECT call_id, tool, result_status, latency_ms, error_class,
               retry_class, retry_attempt
        FROM tool_call_received
        WHERE call_id = 'call-1'
        """,
    )
    assert dict(received) == {
        "call_id": "call-1",
        "tool": "inspect_surroundings",
        "result_status": "ok",
        "latency_ms": 42,
        "error_class": None,
        "retry_class": None,
        "retry_attempt": 0,
    }


@pytest.mark.asyncio
async def test_decision_response_records_optional_provider_and_retry_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "telemetry.db"
    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_decision_response(
            turn=4,
            schema="decision.v2",
            delay_ms=120,
            error="provider timeout",
            provider=ProviderTelemetry(
                provider_name="fixture-provider",
                provider_response_id="resp-2",
                provider_item_id="item-2",
                provider_input_tokens=500,
                provider_output_tokens=75,
                provider_cached_input_tokens=None,
                provider_cache_creation_input_tokens=250,
                provider_cache_read_input_tokens=None,
            ),
            classification=ErrorRetryTelemetry(
                error_class="provider_timeout",
                retry_class="retryable",
                retry_attempt=1,
            ),
        )
        await writer.record_decision_response(
            turn=5,
            schema="decision.v2",
            delay_ms=55,
            error=None,
        )
    finally:
        await writer.close()

    provider_row = await fetch_one(
        db_path,
        """
        SELECT provider_name, provider_response_id, provider_item_id,
               provider_input_tokens, provider_output_tokens,
               provider_cached_input_tokens, provider_cache_creation_input_tokens,
               provider_cache_read_input_tokens, error_class, retry_class,
               retry_attempt
        FROM decision_response
        WHERE turn = 4
        """,
    )
    assert dict(provider_row) == {
        "provider_name": "fixture-provider",
        "provider_response_id": "resp-2",
        "provider_item_id": "item-2",
        "provider_input_tokens": 500,
        "provider_output_tokens": 75,
        "provider_cached_input_tokens": None,
        "provider_cache_creation_input_tokens": 250,
        "provider_cache_read_input_tokens": None,
        "error_class": "provider_timeout",
        "retry_class": "retryable",
        "retry_attempt": 1,
    }
    core_row = await fetch_one(
        db_path,
        """
        SELECT provider_name, provider_response_id, provider_item_id,
               provider_cached_input_tokens, provider_cache_creation_input_tokens,
               provider_cache_read_input_tokens, error_class, retry_class,
               retry_attempt
        FROM decision_response
        WHERE turn = 5
        """,
    )
    assert dict(core_row) == {
        "provider_name": None,
        "provider_response_id": None,
        "provider_item_id": None,
        "provider_cached_input_tokens": None,
        "provider_cache_creation_input_tokens": None,
        "provider_cache_read_input_tokens": None,
        "error_class": None,
        "retry_class": None,
        "retry_attempt": 0,
    }


@pytest.mark.asyncio
async def test_telemetry_writer_migrates_pr1_decision_response_table(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE decision_response (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                turn INTEGER NOT NULL,
                schema TEXT NOT NULL,
                delay_ms INTEGER NOT NULL,
                error TEXT
            )
            """,
        )
        await conn.commit()

    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_decision_response(
            turn=6,
            schema="decision.v2",
            delay_ms=75,
            error=None,
            provider=ProviderTelemetry(provider_name="fixture-provider"),
            classification=ErrorRetryTelemetry(retry_attempt=2),
        )
    finally:
        await writer.close()

    row = await fetch_one(
        db_path,
        """
        SELECT provider_name, retry_attempt
        FROM decision_response
        WHERE turn = 6
        """,
    )
    assert dict(row) == {
        "provider_name": "fixture-provider",
        "retry_attempt": 2,
    }


@pytest.mark.asyncio
async def test_telemetry_writer_records_supervisor_request_and_response(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.db"
    writer = TelemetryWriter(TelemetryWriterConfig(path=db_path))
    await writer.open()
    try:
        await writer.record_supervisor_request(
            message_id="msg-sup-1",
            turn=8,
            reason="level_up",
            game_state="modal",
            timeout_s=300,
            classification=ErrorRetryTelemetry(
                error_class=None,
                retry_class=None,
                retry_attempt=0,
            ),
        )
        await writer.record_supervisor_response(
            message_id="msg-sup-resp-1",
            in_reply_to="msg-sup-1",
            turn=8,
            action="select",
            result_status="ok",
            latency_ms=1500,
            choice_id="ch2",
            reason="selected by supervisor",
            classification=ErrorRetryTelemetry(
                error_class=None,
                retry_class=None,
                retry_attempt=0,
            ),
        )
    finally:
        await writer.close()

    request = await fetch_one(
        db_path,
        """
        SELECT message_id, turn, reason, game_state, timeout_s,
               error_class, retry_class, retry_attempt
        FROM supervisor_request
        """,
    )
    assert dict(request) == {
        "message_id": "msg-sup-1",
        "turn": 8,
        "reason": "level_up",
        "game_state": "modal",
        "timeout_s": 300,
        "error_class": None,
        "retry_class": None,
        "retry_attempt": 0,
    }
    response = await fetch_one(
        db_path,
        """
        SELECT message_id, in_reply_to, turn, action, result_status,
               latency_ms, choice_id, reason, error_class, retry_class,
               retry_attempt
        FROM supervisor_response
        """,
    )
    assert dict(response) == {
        "message_id": "msg-sup-resp-1",
        "in_reply_to": "msg-sup-1",
        "turn": 8,
        "action": "select",
        "result_status": "ok",
        "latency_ms": 1500,
        "choice_id": "ch2",
        "reason": "selected by supervisor",
        "error_class": None,
        "retry_class": None,
        "retry_attempt": 0,
    }


@pytest.mark.asyncio
async def test_telemetry_writer_rejects_double_open(tmp_path: Path) -> None:
    writer = TelemetryWriter(TelemetryWriterConfig(path=tmp_path / "telemetry.db"))
    await writer.open()
    try:
        with pytest.raises(RuntimeError, match="already open"):
            await writer.open()
    finally:
        await writer.close()


@pytest.mark.asyncio
async def test_telemetry_writer_requires_open_connection(tmp_path: Path) -> None:
    writer = TelemetryWriter(TelemetryWriterConfig(path=tmp_path / "telemetry.db"))

    with pytest.raises(RuntimeError, match="No active DB connection"):
        await writer.record_connection_lifecycle(event="OPEN", detail=None)
