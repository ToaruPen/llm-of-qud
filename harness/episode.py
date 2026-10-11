"""Local supervisor-owned action windows, unavailable through player MCP tools."""
import fcntl
import json
import os
from pathlib import Path


class EpisodeGate:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = None

    def refusal(self, run_id, seq):
        try:
            with self.path.open() as handle:
                window = json.loads(handle.read(4096))
            if (not isinstance(window, dict)
                    or set(window) != {"run_id", "first_seq", "stop_seq"}
                    or window["run_id"] != run_id
                    or type(window["first_seq"]) is not int
                    or type(window["stop_seq"]) is not int
                    or window["first_seq"] < 1
                    or window["stop_seq"] - window["first_seq"] != 10
                    or seq < window["first_seq"]):
                raise ValueError("invalid episode window")
        except (OSError, ValueError):
            return {"ok": False, "status": "episode_unavailable",
                    "reason": "The supervisor has not opened a valid episode for this run/seq."}
        if seq >= window["stop_seq"]:
            return {"ok": False, "status": "episode_complete",
                    "reason": "Ten decisions are complete. Save the handoff and end this context; do not act again.",
                    "stop_seq": window["stop_seq"]}
        return None

    def __enter__(self):
        fd = os.open(self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        self._lock = os.fdopen(fd, "a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            self._lock = None
            raise ValueError("another episode controller is active") from None
        self.clear()
        return self

    def publish(self, run_id, first_seq):
        if self._lock is None:
            raise ValueError("episode controller lock is required")
        pending = self.path.with_suffix(".pending")
        fd = os.open(pending, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"run_id": run_id, "first_seq": first_seq, "stop_seq": first_seq + 10}, handle)
        pending.replace(self.path)

    def clear(self):
        if self._lock is None:
            raise ValueError("episode controller lock is required")
        self.path.unlink(missing_ok=True)

    def __exit__(self, *_):
        try:
            self.clear()
        finally:
            self._lock.close()
            self._lock = None
