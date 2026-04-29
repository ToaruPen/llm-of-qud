"""Async SQLite telemetry writer for Phase 1.

See docs/architecture-v5.md:1838-1864.
"""

# mypy: disable-error-code=explicit-any
from __future__ import annotations

from pathlib import Path

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field

from brain.db.schema import create_all

DEFAULT_DB_PATH = Path("~/.local/share/llm-of-qud/phase-1-pr-1.db")


class TelemetryWriterAlreadyOpenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("TelemetryWriter is already open")


class TelemetryWriterConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path = Field(default=DEFAULT_DB_PATH)


class TelemetryWriter:
    def __init__(self, config: TelemetryWriterConfig | None = None) -> None:
        self._config = config or TelemetryWriterConfig()
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self._conn is not None:
            raise TelemetryWriterAlreadyOpenError
        db_path = self._config.path.expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(db_path)
        await create_all(self._conn)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is None:
            return
        await self._conn.close()
        self._conn = None

    async def record_connection_lifecycle(self, *, event: str, detail: str | None) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO connection_lifecycle (event, detail) VALUES (?, ?)",
            (event, detail),
        )
        await conn.commit()

    async def record_decision_request(
        self,
        *,
        turn: int,
        schema: str,
        payload_size_bytes: int,
    ) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO decision_request (turn, schema, payload_size_bytes)
            VALUES (?, ?, ?)
            """,
            (turn, schema, payload_size_bytes),
        )
        await conn.commit()

    async def record_decision_response(
        self,
        *,
        turn: int,
        schema: str,
        delay_ms: int,
        error: str | None,
    ) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO decision_response (turn, schema, delay_ms, error)
            VALUES (?, ?, ?, ?)
            """,
            (turn, schema, delay_ms, error),
        )
        await conn.commit()

    async def record_disconnect_pause(self, *, turn: int, reason: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO disconnect_pause (turn, reason) VALUES (?, ?)",
            (turn, reason),
        )
        await conn.commit()

    async def record_reconnect_wake(self, *, turn: int, mechanism: str) -> None:
        conn = self._require_conn()
        await conn.execute(
            "INSERT INTO reconnect_wake (turn, mechanism) VALUES (?, ?)",
            (turn, mechanism),
        )
        await conn.commit()

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError
        return self._conn
