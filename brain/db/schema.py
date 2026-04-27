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
    error TEXT
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
"""


async def create_all(conn: aiosqlite.Connection) -> None:
    await conn.executescript(DDL)
