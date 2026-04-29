"""Codex device-code auth scaffolding.

See docs/architecture-v5.md:1838-1864.
"""

# mypy: disable-error-code=explicit-any
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from brain.auth.token_store import TokenRecord


class Phase2aAuthUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Phase 2a")


class DeviceCodeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

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
