"""SQLite schema for Phase 1 telemetry.

See docs/architecture-v5.md:1838-1864.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


TIMESTAMP_DEFAULT = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

DDL = f"""
CREATE TABLE IF NOT EXISTS connection_lifecycle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    event TEXT NOT NULL CHECK (event IN ('OPEN', 'CLOSE', 'RECONNECT')),
    detail TEXT
);

CREATE TABLE IF NOT EXISTS decision_request (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    turn INTEGER NOT NULL,
    schema TEXT NOT NULL,
    payload_size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_response (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    turn INTEGER NOT NULL,
    schema TEXT NOT NULL,
    delay_ms INTEGER NOT NULL,
    error TEXT,
    provider_name TEXT,
    provider_response_id TEXT,
    provider_item_id TEXT,
    provider_input_tokens INTEGER,
    provider_output_tokens INTEGER,
    provider_cached_input_tokens INTEGER,
    provider_cache_creation_input_tokens INTEGER,
    provider_cache_read_input_tokens INTEGER,
    error_class TEXT,
    retry_class TEXT,
    retry_attempt INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS disconnect_pause (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    turn INTEGER NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconnect_wake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    turn INTEGER NOT NULL,
    mechanism TEXT NOT NULL CHECK (
        mechanism IN ('PUSH_KEY_NONE', 'PUSH_KEY_OTHER', 'PASS_TURN')
    )
);

CREATE TABLE IF NOT EXISTS tool_call_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    call_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    provider_name TEXT,
    provider_response_id TEXT,
    provider_item_id TEXT,
    provider_input_tokens INTEGER,
    provider_output_tokens INTEGER,
    provider_cached_input_tokens INTEGER,
    provider_cache_creation_input_tokens INTEGER,
    provider_cache_read_input_tokens INTEGER,
    action_nonce TEXT,
    state_version INTEGER,
    session_epoch INTEGER
);

CREATE TABLE IF NOT EXISTS tool_call_received (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    call_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    result_status TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    action_nonce TEXT,
    state_version INTEGER,
    session_epoch INTEGER,
    acceptance_status TEXT,
    error_class TEXT,
    retry_class TEXT,
    retry_attempt INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS supervisor_request (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    message_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    reason TEXT NOT NULL,
    game_state TEXT NOT NULL,
    timeout_s INTEGER,
    error_class TEXT,
    retry_class TEXT,
    retry_attempt INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS supervisor_response (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT ({TIMESTAMP_DEFAULT}),
    message_id TEXT NOT NULL,
    in_reply_to TEXT NOT NULL,
    turn INTEGER NOT NULL,
    action TEXT NOT NULL,
    result_status TEXT NOT NULL,
    latency_ms INTEGER,
    choice_id TEXT,
    reason TEXT,
    error_class TEXT,
    retry_class TEXT,
    retry_attempt INTEGER NOT NULL DEFAULT 0
);
"""

DECISION_RESPONSE_COLUMN_MIGRATIONS = {
    "provider_name": "ALTER TABLE decision_response ADD COLUMN provider_name TEXT",
    "provider_response_id": "ALTER TABLE decision_response ADD COLUMN provider_response_id TEXT",
    "provider_item_id": "ALTER TABLE decision_response ADD COLUMN provider_item_id TEXT",
    "provider_input_tokens": (
        "ALTER TABLE decision_response ADD COLUMN provider_input_tokens INTEGER"
    ),
    "provider_output_tokens": (
        "ALTER TABLE decision_response ADD COLUMN provider_output_tokens INTEGER"
    ),
    "provider_cached_input_tokens": (
        "ALTER TABLE decision_response ADD COLUMN provider_cached_input_tokens INTEGER"
    ),
    "provider_cache_creation_input_tokens": (
        "ALTER TABLE decision_response ADD COLUMN provider_cache_creation_input_tokens INTEGER"
    ),
    "provider_cache_read_input_tokens": (
        "ALTER TABLE decision_response ADD COLUMN provider_cache_read_input_tokens INTEGER"
    ),
    "error_class": "ALTER TABLE decision_response ADD COLUMN error_class TEXT",
    "retry_class": "ALTER TABLE decision_response ADD COLUMN retry_class TEXT",
    "retry_attempt": (
        "ALTER TABLE decision_response ADD COLUMN retry_attempt INTEGER NOT NULL DEFAULT 0"
    ),
}

TOOL_CALL_SENT_COLUMN_MIGRATIONS = {
    "action_nonce": "ALTER TABLE tool_call_sent ADD COLUMN action_nonce TEXT",
    "state_version": "ALTER TABLE tool_call_sent ADD COLUMN state_version INTEGER",
    "session_epoch": "ALTER TABLE tool_call_sent ADD COLUMN session_epoch INTEGER",
}

TOOL_CALL_RECEIVED_COLUMN_MIGRATIONS = {
    "action_nonce": "ALTER TABLE tool_call_received ADD COLUMN action_nonce TEXT",
    "state_version": "ALTER TABLE tool_call_received ADD COLUMN state_version INTEGER",
    "session_epoch": "ALTER TABLE tool_call_received ADD COLUMN session_epoch INTEGER",
    "acceptance_status": "ALTER TABLE tool_call_received ADD COLUMN acceptance_status TEXT",
}


async def create_all(conn: aiosqlite.Connection) -> None:
    await conn.executescript(DDL)
    await _migrate_table(conn, "decision_response", DECISION_RESPONSE_COLUMN_MIGRATIONS)
    await _migrate_table(conn, "tool_call_sent", TOOL_CALL_SENT_COLUMN_MIGRATIONS)
    await _migrate_table(conn, "tool_call_received", TOOL_CALL_RECEIVED_COLUMN_MIGRATIONS)


async def _migrate_table(
    conn: aiosqlite.Connection,
    table_name: str,
    migrations: dict[str, str],
) -> None:
    cursor = await conn.execute(f"PRAGMA table_info({table_name})")
    rows = await cursor.fetchall()
    existing_columns = {str(row[1]) for row in rows}
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            await conn.execute(statement)
