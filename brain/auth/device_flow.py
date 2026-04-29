from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain.auth.token_store import TokenRecord


class Phase2aAuthUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Phase 2a")


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


async def request_device_code() -> DeviceCodeResponse:
    raise Phase2aAuthUnavailableError


async def poll_token(device_code: DeviceCodeResponse) -> TokenRecord:
    _ = device_code
    raise Phase2aAuthUnavailableError
