"""Append-only, hash-chained JSONL ledger.

Row fields: index, kind, seq, run_id, body, prev_hash, hash.
Canonical form: JSON with sorted keys, separators (",", ":"), UTF-8 without ASCII
escaping, NaN/Infinity forbidden. ``hash`` is the SHA-256 hex digest of the canonical
form of the row without its ``hash`` field; the first row's ``prev_hash`` is
GENESIS_HASH. Each line on disk is the canonical form of the full row.
"""

import hashlib
import json
import os

GENESIS_HASH = "0" * 64
ROW_FIELDS = ("index", "kind", "seq", "run_id", "body", "prev_hash", "hash")


def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def row_hash(row_without_hash):
    return hashlib.sha256(canonical_bytes(row_without_hash)).hexdigest()


class Ledger:
    """Exclusive writer for one fresh ledger file. Every append is written and fsynced."""

    def __init__(self, fd, path):
        self._fd = fd
        self.path = path
        self.next_index = 0
        self.head_hash = GENESIS_HASH
        # Optional read-only observer, called with each row once it is durable. It must
        # not raise: callers treat any exception from append as a failed write.
        self.on_append = None

    @classmethod
    def create(cls, path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.close(fd)
            raise
        return cls(fd, path)

    def append(self, kind, seq, run_id, body):
        if self._fd is None:
            raise ValueError("ledger is closed")
        row = {
            "index": self.next_index,
            "kind": kind,
            "seq": seq,
            "run_id": run_id,
            "body": body,
            "prev_hash": self.head_hash,
        }
        row["hash"] = row_hash(row)
        data = memoryview(canonical_bytes(row) + b"\n")
        while data:
            written = os.write(self._fd, data)
            data = data[written:]
        os.fsync(self._fd)
        self.next_index += 1
        self.head_hash = row["hash"]
        if self.on_append is not None:
            self.on_append(row)
        return row

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
