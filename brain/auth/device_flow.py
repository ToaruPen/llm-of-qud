from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.auth.token_store import TokenRecord


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


async def request_device_code() -> DeviceCodeResponse:
    raise NotImplementedError("Phase 2a")


async def poll_token(device_code: DeviceCodeResponse) -> TokenRecord:
    _ = device_code
    raise NotImplementedError("Phase 2a")
