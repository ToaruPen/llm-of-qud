from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeGuard, cast

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
DEFAULT_TOKEN_PATH = Path("~/.codex/auth.json")


@dataclass(frozen=True)
class TokenRecord:
    access_token: str
    refresh_token: str
    expires_at: datetime


def default_token_path() -> Path:
    return DEFAULT_TOKEN_PATH.expanduser()


def write_token_record(path: Path, record: TokenRecord) -> None:
    payload = asdict(record)
    payload["expires_at"] = record.expires_at.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
