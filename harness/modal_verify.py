"""Semantic links for modal events interleaved with the primary action ledger."""
import json

from harness import modal_wire, wire


class ModalVerifier:
    def __init__(self):
        self.snapshots = {}
        self.answers = {}
        self.events = set()
        self.current = None
        self.interrupted = set()
        self.external_answers = 0
        self.watchdogs = 0

    def interrupt(self, seq):
        """A recovery row interrupted ``seq``: its modal is gone and it takes no more rows."""
        self.interrupted.add(seq)
        if self.current and self.current["seq"] == seq:
            self.current = None

    def check(self, row, request_seqs):
        kind, seq, body = row["kind"], row["seq"], row["body"]
        wire._int(seq, "modal seq", 1)
        wire._require(seq in request_seqs, "modal precedes its request")
        wire._require(seq not in self.interrupted, "modal row belongs to an interrupted seq")
        latest = max(request_seqs)
        if self.current and self.current["seq"] < latest:
            self.current = None
        if kind == "modal_answer":
            wire._exact_keys(body, {"token", "answer_id", "response", "modal_hash"}, kind)
            wire._int(body["answer_id"], "answer_id", 1)
            wire._require(body["answer_id"] == len(self.answers) + 1, "answer IDs are not contiguous")
            snapshot = self.current
            wire._require(snapshot is not None and seq == latest and snapshot["seq"] == seq
                          and body["token"] == snapshot["token"], "answer has no current modal")
            wire._require(not snapshot["pending"], "modal already has a pending answer")
            wire._require(body["modal_hash"] == snapshot["hash"], "modal_hash does not link to snapshot")
            modal_wire.validate_response(snapshot["modal"], body["response"])
            self.answers[body["answer_id"]] = row
            snapshot["pending"] = True
            return
        frame_body = dict(body)
        digest = frame_body.pop("frame_sha256", None)
        wire._require(isinstance(digest, str) and len(digest) == 64
                      and all(c in "0123456789abcdef" for c in digest), "invalid modal frame hash")
        answer_hash = frame_body.pop("answer_hash", None) if kind == "modal_result" else None
        message = {"kind": kind, "seq": seq, "run_id": row["run_id"], **frame_body}
        modal_wire.parse_optional(json.dumps(message))
        if kind == "modal_watchdog":
            key = (kind, seq, body["view"], body["elapsed_ms"])
            wire._require(key not in self.events, "duplicate modal watchdog in ledger")
            self.events.add(key)
            self.watchdogs += 1
            return
        token = body["token"]
        if kind == "modal":
            wire._require(token not in self.snapshots, "modal token reused")
            wire._require(seq == latest and self.current is None, "modal replaces an active modal")
            self.current = {"seq": seq, "token": token, "modal": body["modal"],
                            "hash": row["hash"], "pending": False, "answered": False}
            self.snapshots[token] = self.current
            return
        key = (kind, token, body.get("answer_id"))
        wire._require(key not in self.events, "duplicate modal event in ledger")
        self.events.add(key)
        if kind == "modal_auto":
            return
        snapshot = self.snapshots.get(token)
        wire._require(snapshot is not None and snapshot["seq"] == seq, "event has no matching modal")
        if kind == "modal_result":
            answer = self.answers.get(body["answer_id"])
            wire._require(answer is not None and answer["hash"] == answer_hash
                          and answer["seq"] == seq and answer["body"]["token"] == token,
                          "answer_hash does not link to matching answer")
            if not body["accepted"]:
                snapshot["pending"] = False
                return
            snapshot["answered"] = True
        elif kind == "modal_clear" and not snapshot["answered"]:
            # Conservative attribution: the driver did not acknowledge this closure.
            # It could be human input or another engine path; the ledger cannot identify who.
            self.external_answers += 1
        if self.current is snapshot:
            self.current = None
