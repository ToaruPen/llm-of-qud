from __future__ import annotations

import sys
from pathlib import Path

import aiosqlite
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.db.writer import TelemetryWriter, TelemetryWriterConfig


async def table_count(db_path, table: str) -> int:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cursor.fetchone()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
async def test_telemetry_writer_creates_schema_and_records_all_pr1_events(tmp_path) -> None:
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
async def test_telemetry_writer_rejects_double_open(tmp_path) -> None:
    writer = TelemetryWriter(TelemetryWriterConfig(path=tmp_path / "telemetry.db"))
    await writer.open()
    try:
        with pytest.raises(RuntimeError, match="already open"):
            await writer.open()
    finally:
        await writer.close()
