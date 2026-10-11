"""Modal exchanges share the run ledger but never create a second game decision."""
import asyncio
import json

from harness import modal_wire, wire


class ModalCoordinator:
    def __init__(self, broker):
        self.broker = broker
        self.current = None
        self.snapshots = {}
        self.answers = {}
        self.events = {}
        self.last_result = None
        self.next_answer_id = 1
        self.watchdog = None

    def _append(self, kind, seq, body):
        try:
            return self.broker.ledger.append(kind, seq, self.broker.run_id, body)
        except Exception as exc:
            raise self.broker._violate(f"modal ledger write failed: {type(exc).__name__}: {exc}") from None

    def handle(self, message, frame):
        kind, seq = message["kind"], message["seq"]
        if seq > self.broker.seq:
            raise self.broker._violate("modal frame precedes its decision request")
        # A recovery interrupted this seq: exact historical replays are still recognised
        # below (dedup indexes are kept), but no new modal data may be accepted for it.
        interrupted = seq in self.broker._interrupted
        if kind == "modal_watchdog":
            key = (kind, seq, message["view"], message["elapsed_ms"])
            if key not in self.events:
                if interrupted:
                    raise self.broker._violate("modal watchdog belongs to an interrupted seq")
                self._append(kind, seq, modal_wire.frame_body(message, frame))
                self.events[key] = frame
                if seq == self.broker.seq:
                    self.watchdog = {"ok": False, "status": "unhandled_modal",
                                     "reason": message["reason"], "view": message["view"], "seq": seq}
                self.broker._notify()
            elif self.events[key] != frame:
                raise self.broker._violate("conflicting watchdog replay")
            return None
        token = message["token"]
        if kind == "modal":
            previous = self.snapshots.get(token)
            if previous:
                if previous["frame"] != frame:
                    raise self.broker._violate("modal token reused with different content")
                answer = previous.get("answer")
                return (answer["frame"] if self.current is previous and answer
                        and answer["result"] is None else None)
            if interrupted:
                raise self.broker._violate("new modal belongs to an interrupted seq")
            if seq != self.broker.seq:
                raise self.broker._violate("new modal belongs to an obsolete seq")
            if self.current is not None:
                raise self.broker._violate("new modal did not close the previous modal")
            row = self._append(kind, seq, modal_wire.frame_body(message, frame))
            self.current = {"frame": frame, "seq": seq, "token": token, "modal": message["modal"],
                            "hash": row["hash"], "answer": None}
            self.snapshots[token] = self.current
            self.watchdog = None
        else:
            event_key = (kind, token, message.get("answer_id"))
            if event_key in self.events:
                if self.events[event_key] != frame:
                    raise self.broker._violate("conflicting modal event replay")
                return None
            if interrupted:
                raise self.broker._violate(f"{kind} belongs to an interrupted seq")
            body = modal_wire.frame_body(message, frame)
            if kind == "modal_result":
                answer = self.answers.get(message["answer_id"])
                if not answer or answer["token"] != token or answer["seq"] != seq:
                    raise self.broker._violate("modal result has no matching answer")
                body["answer_hash"] = answer["hash"]
                self._append(kind, seq, body)
                answer["result"] = {"ok": True, "completed": True, "answer_id": message["answer_id"],
                                    "accepted": message["accepted"], "reason": message["reason"]}
                self.last_result = answer["result"]
                answer["done"].set()
                if self.current and self.current["token"] == token:
                    if message["accepted"]:
                        self.current = None
                    else:
                        self.current["answer"] = None
            elif kind == "modal_clear":
                snapshot = self.snapshots.get(token)
                if not snapshot or snapshot["seq"] != seq:
                    raise self.broker._violate("modal clear has no matching snapshot")
                self._append(kind, seq, body)
                answer = snapshot.get("answer")
                if answer and answer["result"] is None:
                    answer["result"] = {"ok": False, "status": "modal_closed",
                                        "answer_id": answer["id"], "reason": message["reason"]}
                    self.last_result = answer["result"]
                    answer["done"].set()
                if self.current and self.current["token"] == token:
                    self.current = None
            else:
                self._append(kind, seq, body)
            self.events[event_key] = frame
        self.broker._notify()
        return None

    def advance(self, seq):
        # A UI callback can resume the game before its acknowledgement reaches the socket.
        # Keep outstanding answers addressable; a late acknowledgement must not clear a new UI.
        if self.current and self.current["seq"] < seq:
            self.current = None
        self.watchdog = None

    def interrupt(self, seq, recovery):
        """A recovery reloaded the game: the modal of ``seq`` and its pending answer are gone.

        Indexes (snapshots, answers, events) are kept so exact historical replays stay
        recognisable; the interrupted answer can never receive a result afterwards.
        """
        if self.current and self.current["seq"] == seq:
            self.current = None
        for answer in self.answers.values():
            if answer["seq"] == seq and answer["result"] is None:
                answer["result"] = {"ok": False, "status": "interrupted", "completed": False,
                                    "answer_id": answer["id"],
                                    "reason": "the game reloaded a save before the UI acknowledged "
                                              "this answer",
                                    "recovery_id": recovery["recovery_id"]}
                self.last_result = answer["result"]
                answer["done"].set()
        self.watchdog = None

    def state(self):
        if self.current is None:
            return None
        answer = self.current.get("answer")
        return {"token": self.current["token"], **self.current["modal"],
                "answer_pending": bool(answer and answer["result"] is None)}

    async def respond(self, expect_seq, token, response):
        broker = self.broker
        if broker.fault:
            return broker._faulted()
        if broker.closed:
            return {"ok": False, "status": "shutdown"}
        if broker._recovery is not None:
            return broker._recovering()
        if type(expect_seq) is not int or expect_seq != broker.seq:
            return {"ok": False, "status": "stale_seq"}
        if not self.current or self.current["token"] != token:
            return {"ok": False, "status": "stale_modal"}
        if not broker.game_connected:
            return {"ok": False, "status": "disconnected"}
        if self.current["answer"]:
            return {"ok": False, "status": "answer_pending", "answer_id": self.current["answer"]["id"]}
        try:
            modal_wire.validate_response(self.current["modal"], response)
        except wire.WireError as exc:
            return {"ok": False, "status": "invalid", "reason": str(exc)}
        answer_id = self.next_answer_id
        frame = json.dumps({"kind": "modal_answer", "run_id": broker.run_id, "seq": expect_seq,
                            "token": token, "answer_id": answer_id, "response": response},
                           ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        body = {"token": token, "answer_id": answer_id, "response": response,
                "modal_hash": self.current["hash"]}
        try:
            row = self._append("modal_answer", expect_seq, body)
        except Exception:
            return broker._faulted()
        answer = {"id": answer_id, "seq": expect_seq, "token": token, "frame": frame,
                  "hash": row["hash"], "result": None, "done": asyncio.Event()}
        self.next_answer_id += 1
        self.current["answer"] = answer
        self.answers[answer_id] = answer
        broker._spawn(broker._send(broker.conn, frame,
                                   lambda: (not broker.fault and answer["result"] is None
                                            and broker._suspended != expect_seq)))
        deadline = asyncio.get_running_loop().time() + broker.act_wait_s
        # Wakes on the UI acknowledgement, a recovery (interrupted), a fault or shutdown.
        await broker._wait_until(
            lambda: (answer["result"] is not None or broker.fault or broker.closed
                     or broker._suspended == expect_seq), deadline)
        if broker.fault:
            return broker._faulted(answer_id=answer_id)
        if answer["result"] is not None:
            return answer["result"]
        if broker._suspended == expect_seq:
            return broker._suspended_state(answer_id=answer_id)
        if broker.closed:
            return {"ok": False, "status": "shutdown", "answer_id": answer_id}
        return {"ok": True, "pending": True, "answer_id": answer_id}
