from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.auth.token_store import TokenRecord


def refresh_if_expired(record: TokenRecord, *, now: datetime | None = None) -> TokenRecord:
    current_time = now or datetime.now(UTC)
    if record.expires_at > current_time:
        return record
    raise NotImplementedError("Phase 2a")
