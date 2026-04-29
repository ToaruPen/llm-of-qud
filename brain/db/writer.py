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


class TelemetryWriterNotOpenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("No active DB connection: call open() before using DB writer")


class TelemetryWriterConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path = Field(default=DEFAULT_DB_PATH)


class ProviderTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_name: str | None = None
    provider_response_id: str | None = None
    provider_item_id: str | None = None
    provider_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    provider_cached_input_tokens: int | None = None
    provider_cache_creation_input_tokens: int | None = None
    provider_cache_read_input_tokens: int | None = None


class ErrorRetryTelemetry(BaseModel):
    model_config = ConfigDict(frozen=True)

    error_class: str | None = None
    retry_class: str | None = None
    retry_attempt: int = 0


class TelemetryWriter:
    def __init__(self, config: TelemetryWriterConfig | None = None) -> None:
        self._config = config or TelemetryWriterConfig()
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        if self._conn is not None:
            raise TelemetryWriterAlreadyOpenError()
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
        provider: ProviderTelemetry | None = None,
        classification: ErrorRetryTelemetry | None = None,
    ) -> None:
        conn = self._require_conn()
        provider = provider or ProviderTelemetry()
        classification = classification or ErrorRetryTelemetry()
        await conn.execute(
            """
            INSERT INTO decision_response (
                turn, schema, delay_ms, error, provider_name,
                provider_response_id, provider_item_id, provider_input_tokens,
                provider_output_tokens, provider_cached_input_tokens,
                provider_cache_creation_input_tokens,
                provider_cache_read_input_tokens, error_class, retry_class,
                retry_attempt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn,
                schema,
                delay_ms,
                error,
                provider.provider_name,
                provider.provider_response_id,
                provider.provider_item_id,
                provider.provider_input_tokens,
                provider.provider_output_tokens,
                provider.provider_cached_input_tokens,
                provider.provider_cache_creation_input_tokens,
                provider.provider_cache_read_input_tokens,
                classification.error_class,
                classification.retry_class,
                classification.retry_attempt,
            ),
        )
        await conn.commit()

    async def record_tool_call_sent(
        self,
        *,
        call_id: str,
        tool: str,
        provider: ProviderTelemetry | None = None,
    ) -> None:
        conn = self._require_conn()
        provider = provider or ProviderTelemetry()
        await conn.execute(
            """
            INSERT INTO tool_call_sent (
                call_id, tool, provider_name, provider_response_id,
                provider_item_id, provider_input_tokens, provider_output_tokens,
                provider_cached_input_tokens,
                provider_cache_creation_input_tokens,
                provider_cache_read_input_tokens
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                tool,
                provider.provider_name,
                provider.provider_response_id,
                provider.provider_item_id,
                provider.provider_input_tokens,
                provider.provider_output_tokens,
                provider.provider_cached_input_tokens,
                provider.provider_cache_creation_input_tokens,
                provider.provider_cache_read_input_tokens,
            ),
        )
        await conn.commit()

    async def record_tool_call_received(
        self,
        *,
        call_id: str,
        tool: str,
        result_status: str,
        latency_ms: int,
        classification: ErrorRetryTelemetry | None = None,
    ) -> None:
        conn = self._require_conn()
        classification = classification or ErrorRetryTelemetry()
        await conn.execute(
            """
            INSERT INTO tool_call_received (
                call_id, tool, result_status, latency_ms, error_class,
                retry_class, retry_attempt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                tool,
                result_status,
                latency_ms,
                classification.error_class,
                classification.retry_class,
                classification.retry_attempt,
            ),
        )
        await conn.commit()

    async def record_supervisor_request(
        self,
        *,
        message_id: str,
        turn: int,
        reason: str,
        game_state: str,
        timeout_s: int | None,
        classification: ErrorRetryTelemetry | None = None,
    ) -> None:
        conn = self._require_conn()
        classification = classification or ErrorRetryTelemetry()
        await conn.execute(
            """
            INSERT INTO supervisor_request (
                message_id, turn, reason, game_state, timeout_s, error_class,
                retry_class, retry_attempt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                turn,
                reason,
                game_state,
                timeout_s,
                classification.error_class,
                classification.retry_class,
                classification.retry_attempt,
            ),
        )
        await conn.commit()

    async def record_supervisor_response(
        self,
        *,
        message_id: str,
        in_reply_to: str,
        turn: int,
        action: str,
        result_status: str,
        latency_ms: int | None,
        choice_id: str | None = None,
        reason: str | None = None,
        classification: ErrorRetryTelemetry | None = None,
    ) -> None:
        conn = self._require_conn()
        classification = classification or ErrorRetryTelemetry()
        await conn.execute(
            """
            INSERT INTO supervisor_response (
                message_id, in_reply_to, turn, action, result_status,
                latency_ms, choice_id, reason, error_class, retry_class,
                retry_attempt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                in_reply_to,
                turn,
                action,
                result_status,
                latency_ms,
                choice_id,
                reason,
                classification.error_class,
                classification.retry_class,
                classification.retry_attempt,
            ),
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
            raise TelemetryWriterNotOpenError()
        return self._conn
