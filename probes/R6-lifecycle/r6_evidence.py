"""R6 probe evidence: strict parsing of the hash-chained JSONL files the probe mod writes.

One file per game process (``<profile>/r6-evidence/<utc>-<pid>-<session>.jsonl``). Every
line is a compact JSON object with the header fields below; ``prev`` is the SHA-256 of the
previous line's exact UTF-8 bytes (without the newline), 64 zeros for ``n == 0``.

Shared by ``r6_verify.py`` (offline verifier) and ``r6_operator.py`` (operator runner).
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
HEADER = ("v", "session", "n", "prev", "utc", "kind", "thread", "epoch", "boundary")
EVIDENCE_DIR = "r6-evidence"
OPTIN_FILE = "r6-dev-optin.json"
CONTROL_FILE = "llm-control.json"


class EvidenceError(ValueError):
    """Evidence cannot be parsed or its chain is broken."""


def _unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise EvidenceError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def _reject_constant(name):
    raise EvidenceError(f"non-finite number {name}")


def loads(text: str):
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_reject_constant)
    except EvidenceError:
        raise
    except ValueError as exc:
        raise EvidenceError(f"invalid JSON: {exc}") from None


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"utc must be an ISO-8601 string ending in Z: {value!r}")
    try:
        return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
    except ValueError:
        raise EvidenceError(f"invalid utc {value!r}") from None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Session:
    path: Path
    session: str
    records: list = field(default_factory=list)
    truncated_tail: bool = False

    @property
    def init(self):
        return self.records[0] if self.records else None

    @property
    def pid(self):
        return self.init.get("pid") if self.init else None

    @property
    def first_utc(self) -> datetime:
        return parse_utc(self.records[0]["utc"])

    @property
    def last_utc(self) -> datetime:
        return parse_utc(self.records[-1]["utc"])


def load_session(path: Path) -> Session:
    """Parse one evidence file and verify its hash chain.

    A partial final line (no trailing newline) is dropped and reported as
    ``truncated_tail``; the caller decides whether a crash receipt explains it.
    """
    data = Path(path).read_bytes()
    lines = data.split(b"\n")
    truncated = False
    if lines and lines[-1] == b"":
        lines.pop()
    elif lines:
        lines.pop()  # final line lacks its newline: written when the process died
        truncated = True
    prev = GENESIS
    session = None
    records = []
    for index, raw in enumerate(lines):
        try:
            record = loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, EvidenceError) as exc:
            raise EvidenceError(f"{path.name} line {index}: {exc}") from None
        if not isinstance(record, dict):
            raise EvidenceError(f"{path.name} line {index}: record is not an object")
        missing = [key for key in HEADER if key not in record]
        if missing:
            raise EvidenceError(f"{path.name} line {index}: missing header fields {missing}")
        if record["v"] != 1:
            raise EvidenceError(f"{path.name} line {index}: unsupported version {record['v']!r}")
        if record["n"] != index:
            raise EvidenceError(f"{path.name} line {index}: n is {record['n']!r}")
        if record["prev"] != prev:
            raise EvidenceError(f"{path.name} line {index}: prev hash does not match previous line")
        if session is None:
            session = record["session"]
            if record["kind"] != "init":
                raise EvidenceError(f"{path.name}: first record must be init")
        elif record["session"] != session:
            raise EvidenceError(f"{path.name} line {index}: session changed within one file")
        parse_utc(record["utc"])
        prev = sha256_hex(raw)
        records.append(record)
    if not records:
        raise EvidenceError(f"{path.name}: no complete records")
    return Session(Path(path), session, records, truncated)


def load_sessions(directory: Path) -> list[Session]:
    files = sorted(Path(directory).glob("*.jsonl"))
    if not files:
        raise EvidenceError(f"no evidence files in {directory}")
    sessions = [load_session(path) for path in files]
    ids = [s.session for s in sessions]
    if len(set(ids)) != len(ids):
        raise EvidenceError("two evidence files share one session id")
    sessions.sort(key=lambda s: (s.first_utc, s.path.name))
    return sessions


def latest_session(directory: Path) -> Session:
    sessions = load_sessions(directory)
    return max(sessions, key=lambda s: (s.first_utc, s.path.name))


def last_game(records):
    """The most recent ``game`` snapshot in a sequence of records, or None."""
    for record in reversed(records):
        game = record.get("game")
        if isinstance(game, dict) and isinstance(game.get("turns"), int):
            return game
    return None
