from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from brain.auth.broker import refresh_if_expired
from brain.auth.device_flow import DeviceCodeResponse, poll_token, request_device_code
from brain.auth.token_store import TokenRecord, read_token_record, write_token_record


def synthetic_record(expires_at: datetime | None = None) -> TokenRecord:
    return TokenRecord(
        access_token="synthetic-access-token",
        refresh_token="synthetic-refresh-token",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
    )


def test_token_store_round_trips_synthetic_record(tmp_path) -> None:
    path = tmp_path / "auth.json"
    record = synthetic_record()

    write_token_record(path, record)

    assert read_token_record(path) == record


@pytest.mark.asyncio
async def test_device_flow_network_functions_are_phase_2a_placeholders() -> None:
    device_code = DeviceCodeResponse(
        device_code="synthetic-device-code",
        user_code="ABCD-EFGH",
        verification_uri="https://example.invalid/device",
        expires_in=600,
        interval=5,
    )

    assert device_code.interval == 5
    with pytest.raises(NotImplementedError, match="Phase 2a"):
        await request_device_code()
    with pytest.raises(NotImplementedError, match="Phase 2a"):
        await poll_token(device_code)


def test_broker_passes_through_unexpired_record() -> None:
    record = synthetic_record(datetime.now(UTC) + timedelta(minutes=5))

    assert refresh_if_expired(record) is record


def test_broker_raises_for_expired_record() -> None:
    record = synthetic_record(datetime.now(UTC) - timedelta(seconds=1))

    with pytest.raises(NotImplementedError, match="Phase 2a"):
        refresh_if_expired(record)
