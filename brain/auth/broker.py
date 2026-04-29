"""Token refresh gate for Phase 1 auth scaffolding.

See docs/architecture-v5.md:1838-1864.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.auth.token_store import TokenRecord

from brain.auth.device_flow import Phase2aAuthUnavailableError


def refresh_if_expired(record: TokenRecord, *, now: datetime | None = None) -> TokenRecord:
    current_time = now or datetime.now(UTC)
    if record.expires_at > current_time:
        return record
    raise Phase2aAuthUnavailableError
