"""Token persistence for Codex auth scaffolding.

See docs/architecture-v5.md:1849.
"""

# mypy: disable-error-code=explicit-any
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeGuard, cast

from pydantic import BaseModel, ConfigDict, field_validator

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
DEFAULT_TOKEN_PATH = Path("~/.codex/auth.json")


class NaiveTokenExpiryError(ValueError):
    def __init__(self) -> None:
        super().__init__("expires_at must be timezone-aware")


class TokenRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise NaiveTokenExpiryError
        return value.astimezone(UTC)


def default_token_path() -> Path:
    return DEFAULT_TOKEN_PATH.expanduser()


def write_token_record(path: Path, record: TokenRecord) -> None:
    payload = record.model_dump()
    payload["expires_at"] = record.expires_at.astimezone(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def read_token_record(path: Path) -> TokenRecord | None:
    if not path.exists():
        return None

    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not is_json_object(parsed):
        raise TypeError

    access_token = require_string(parsed, "access_token")
    refresh_token = require_string(parsed, "refresh_token")
    expires_at = datetime.fromisoformat(require_string(parsed, "expires_at"))
    return TokenRecord(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )


def is_json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    if not isinstance(value, dict):
        return False
    for key, item in cast("dict[object, object]", value).items():
        if not isinstance(key, str) or not is_json_value(item):
            return False
    return True


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(is_json_value(item) for item in cast("list[object]", value))
    return is_json_object(value)


def require_string(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError
    return value
