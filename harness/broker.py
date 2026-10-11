"""Single-game, single-run seq broker between the game WebSocket and the MCP tools.

Everything runs on one asyncio event loop. Accepting a decision (seq check, ledger
append + fsync, state change) contains no ``await``, so it is atomic with respect to
every other handler. Decisions are sent from broker-owned tasks: cancelling an MCP tool
call only stops that call's waiting, never an accepted operation. No default or
fallback action is ever produced.

Lifecycle: a ``recovery`` frame (the game reloaded a save/checkpoint) interrupts the
current request seq and any decision accepted for it. No result is ever manufactured
for that seq; the run stays bound and the next request must be seq+1. A ``game_fault``
frame is terminal: it is journaled and the run is faulted. A ``suspended`` frame (the
controlled game stopped running, e.g. it exited to the main menu) voids the current
request without ending the run: nothing is actionable until a recovery of that seq (a
verified reload) or a game_fault; any decision accepted earlier stays unresolved until then.
"""

import asyncio
import logging
import math
import time

from harness import modal_wire, wire
from harness.modal_broker import ModalCoordinator

log = logging.getLogger("harness.broker")

MAX_WAIT_S = 45.0
NEXT_REQUEST_GRACE_S = 0.5


class Refused(Exception):
    """Close only this connection; the bound run is unaffected."""


class ProtocolViolation(Exception):
    """The bound run broke the contract (or the ledger failed); the run is now faulted."""


def _fail(status, reason, **extra):
    return {"ok": False, "status": status, "reason": reason, **extra}


def _printable(text):
    """Game-supplied text for logs and MCP reasons: no control characters (log forging)."""
    return "".join(ch if ch.isprintable() else "�" for ch in text)


RECOVERING_REASON = ("the game reloaded a save and interrupted the current request; "
                     "no result exists for it. Wait for the game's fresh decision request "
                     "(poll get_state)")
SUSPENDED_REASON = ("the game is not running (it left play, e.g. exited to the main menu); "
                    "the previous observation is void and no action or answer is accepted. "
                    "Poll get_state until the game reloads a save and sends a new seq")
INTERRUPTED_REASON = ("the game reloaded a save before this operation finished; it has no "
                      "result and is not retried")


class Broker:
    def __init__(self, ledger, *, act_wait_s=2.0, episode_gate=None):
        self.ledger = ledger
        self.act_wait_s = act_wait_s
        self.episode_gate = episode_gate
        self.run_id = None
        self.fault = None
        self.closed = False
        self.conn = None
        self.last_heartbeat = None
        self._conn_verified = False
        # Current seq.
        self.seq = 0
        self._request_frame = None
        self._request_hash = None
        self._observation = None
        self._decision_action = None
        self._decision_frame = None
        self._decision_hash = None
        self._result_frame = None
        self._result_public = None
        # Last completed seq (seq - 1), kept for duplicate results and late wait_for_turn.
        self._prev_result_frame = None
        self._prev_result_public = None
        # Recovery of the current seq, set until the game's fresh request (seq + 1).
        self._recovery = None
        # canonical recovery_id -> exact frame, so replays stay idempotent for the process.
        self._recoveries = {}
        # interrupted seq -> {"recovery": public metadata, "op": a decision was accepted}.
        self._interrupted = {}
        # Seq whose request was voided because the game stopped running, until its recovery.
        self._suspended = None
        # suspended seq -> exact frame, so replays stay idempotent for the process.
        self._suspensions = {}
        # Terminal game fault: public details and the exact frame (harmless duplicate).
        self.game_fault = None
        self._fault_frame = None
        self._changed = asyncio.Event()
        self._tasks = set()
        self.modals = ModalCoordinator(self)

    # ----- connection lifecycle (called by the WebSocket listener) -----

    def attach(self, conn):
        if self.fault:
            raise Refused("run is faulted")
        if self.closed:
            raise Refused("harness is shutting down")
        if self.conn is not None:
            raise Refused("another game connection is active")
        self.conn = conn
        self._conn_verified = False
        self._notify()

    def detach(self, conn):
        if self.conn is conn:
            self.conn = None
            self._conn_verified = False
            self._notify()

    def handle_frame(self, conn, frame):
        """Process one frame; return a frame to send back on this connection, or None."""
        if conn is not self.conn:
            raise Refused("connection is not attached")
        if self.closed:
            raise Refused("harness is shutting down")
        if self.fault:
            if self._fault_frame is not None and frame == self._fault_frame:
                return None  # exact duplicate of the recorded game_fault: nothing to do
            raise ProtocolViolation(self.fault)
        try:
            message = modal_wire.parse_optional(frame) or wire.parse_game_frame(frame)
        except wire.WireError as exc:
            if self._conn_verified:
                raise self._violate(f"invalid frame: {exc}") from None
            raise Refused(f"invalid frame: {exc}") from None

        kind = message["kind"]
        if self.run_id is None:
            if kind == "heartbeat":
                self.last_heartbeat = time.monotonic()
                return None
            if kind != "request" or message["seq"] != 1:
                raise Refused("a new run must start with request seq 1")
        elif message["run_id"] != self.run_id:
            raise Refused("frame belongs to a different run")
        else:
            self._conn_verified = True

        if kind == "request":
            return self._on_request(message, frame)
        if kind == "result":
            return self._on_result(message, frame)
        if kind == "recovery":
            return self._on_recovery(message, frame)
        if kind == "game_fault":
            return self._on_game_fault(message, frame)
        if kind == "suspended":
            return self._on_suspended(message, frame)
        if kind in modal_wire.GAME_KINDS:
            return self.modals.handle(message, frame)
        self.last_heartbeat = time.monotonic()
        return None

    def _on_request(self, message, frame):
        seq = message["seq"]
        if self.seq and seq == self.seq:
            if frame != self._request_frame:
                raise self._violate(f"request seq {seq} replayed with different bytes")
            if self._recovery is not None or self._suspended is not None:
                # Historical bytes of the interrupted or suspended request: never revive it
                # and never resend its decision into a reloaded or ended game.
                return None
            if self._result_frame is not None:
                raise self._violate(f"request seq {seq} replayed after its result")
            # The game re-sends its pending request only when it lacks the decision, so
            # answer every identical replay with the cached bytes. A duplicate that races
            # the act-time send carries the same seq and is dropped by the game's gate.
            return self._decision_frame
        if self._suspended is not None:
            raise self._violate(f"request seq {seq} arrived while request seq {self._suspended} "
                                "is suspended without a recovery")
        if self.seq:
            if seq != self.seq + 1:
                raise self._violate(f"unexpected request seq {seq} (current {self.seq})")
            if self._result_frame is None and self._recovery is None:
                raise self._violate(f"request seq {seq} arrived before result seq {self.seq}")
        try:
            row = self.ledger.append("request", seq, message["run_id"], wire.request_body(message, frame))
        except Exception as exc:
            raise self._violate(f"ledger write failed: {type(exc).__name__}: {exc}") from None
        if self.run_id is None:
            self.run_id = message["run_id"]
            self._conn_verified = True
        # After a recovery there is no result for the previous seq; nothing is kept for it.
        self._prev_result_frame = self._result_frame
        self._prev_result_public = self._result_public
        self._recovery = None
        self.seq = seq
        self.modals.advance(seq)
        self._request_frame = frame
        self._request_hash = row["hash"]
        self._observation = message["observation"]
        self._decision_action = self._decision_frame = None
        self._decision_hash = None
        self._result_frame = self._result_public = None
        self._notify()
        return None

    def _on_result(self, message, frame):
        seq = message["seq"]
        if seq in self._interrupted:
            raise self._violate(f"result seq {seq} belongs to a request interrupted by a recovery")
        if self._prev_result_frame is not None and seq == self.seq - 1:
            if frame == self._prev_result_frame:
                return None
            raise self._violate(f"conflicting duplicate result for seq {seq}")
        if self._suspended is not None:
            raise self._violate(f"result seq {seq} arrived after the game stopped running")
        if seq != self.seq or self._decision_frame is None:
            raise self._violate(f"result seq {seq} has no accepted decision")
        if self._result_frame is not None:
            if frame == self._result_frame:
                return None
            raise self._violate(f"conflicting result for seq {seq}")
        if message["action"] != self._decision_action:
            raise self._violate(f"result action {message['action']!r} differs from the decision")
        try:
            self.ledger.append("result", seq, self.run_id,
                               wire.result_body(message, frame, self._decision_hash))
        except Exception as exc:
            raise self._violate(f"ledger write failed: {type(exc).__name__}: {exc}") from None
        self._result_frame = frame
        self._result_public = wire.public_result(message)
        self._notify()
        return None

    def _on_recovery(self, message, frame):
        recovery_id = wire.canonical_uuid(message["recovery_id"])
        known = self._recoveries.get(recovery_id)
        if known is not None:
            if frame == known:
                return None  # exact replay (after later seqs or a reconnect): idempotent
            raise self._violate(f"recovery {recovery_id} replayed with different bytes")
        seq = message["seq"]
        if seq != self.seq:
            # Includes a recovery for a request that was never delivered: fail closed
            # rather than inventing its observation.
            raise self._violate(f"recovery seq {seq} is not the current request seq {self.seq}")
        if self._recovery is not None:
            raise self._violate(f"request seq {seq} was already interrupted by a recovery")
        if self._result_frame is not None:
            raise self._violate(f"recovery seq {seq} arrived after its result")
        decision_hash = self._decision_hash
        try:
            self.ledger.append("recovery", seq, self.run_id,
                               wire.recovery_body(message, frame, self._request_hash, decision_hash))
        except Exception as exc:
            raise self._violate(f"ledger write failed: {type(exc).__name__}: {exc}") from None
        public = wire.public_recovery(message)
        self._recoveries[recovery_id] = frame
        self._recovery = public
        self._interrupted[seq] = {"recovery": public, "op": decision_hash is not None}
        self._suspended = None
        log.warning("seq %d interrupted by %s (lost %d turns, decision accepted: %s)",
                    seq, message["reason"], message["lost_turns"], decision_hash is not None)
        # The old observation, decision and modal are no longer actionable. The decision
        # hash stays as the link target for a game_fault of this seq.
        self._observation = None
        self._decision_action = self._decision_frame = None
        self.modals.interrupt(seq, public)
        self._notify()
        return None

    def _on_suspended(self, message, frame):
        seq = message["seq"]
        known = self._suspensions.get(seq)
        if known is not None:
            if frame == known:
                return None  # exact replay (after a reconnect or later seqs): idempotent
            raise self._violate(f"suspension of seq {seq} replayed with different bytes")
        if seq != self.seq:
            raise self._violate(f"suspended seq {seq} is not the current request seq {self.seq}")
        if self._recovery is not None:
            raise self._violate(f"suspended seq {seq} arrived after its recovery")
        if self._result_frame is not None:
            raise self._violate(f"suspended seq {seq} arrived after its result")
        try:
            self.ledger.append("suspended", seq, self.run_id,
                               wire.suspended_body(message, frame, self._request_hash,
                                                   self._decision_hash))
        except Exception as exc:
            raise self._violate(f"ledger write failed: {type(exc).__name__}: {exc}") from None
        self._suspensions[seq] = frame
        self._suspended = seq
        log.warning("seq %d suspended: the game stopped running (decision accepted: %s)",
                    seq, self._decision_hash is not None)
        # The old observation is void. An accepted decision stays unresolved (never
        # completed, never resent) until a recovery interrupts it or a fault ends the run.
        self._observation = None
        self._notify()
        return None

    def _on_game_fault(self, message, frame):
        seq = message["seq"]
        if seq != self.seq:
            raise self._violate(f"game_fault seq {seq} is not the current request seq {self.seq}")
        try:
            self.ledger.append("game_fault", seq, self.run_id,
                               wire.game_fault_body(message, frame, self._request_hash,
                                                    self._decision_hash))
        except Exception as exc:
            raise self._violate(f"ledger write failed: {type(exc).__name__}: {exc}") from None
        reason = _printable(message["reason"])
        self.game_fault = {"seq": seq, "reason": reason}
        self._fault_frame = frame
        self._observation = None
        self.fault = f"game reported a fatal fault at seq {seq}: {reason}"
        log.error("run faulted by the game: %s", self.fault)
        self._notify()
        return None

    def _violate(self, reason):
        if self.fault is None:
            self.fault = reason
            log.error("run faulted: %s", reason)
        self._notify()
        return ProtocolViolation(reason)

    # ----- MCP-facing operations -----

    @property
    def game_connected(self):
        """A connection is attached and has sent a valid frame of the bound run."""
        return self.conn is not None and self._conn_verified

    def get_state(self):
        """Read-only view; never advances the game."""
        state = self._state()
        # A faulted run exposes nothing that reads as ok:true (not even an old UI ack).
        if self.modals.last_result is not None and not self.fault:
            state["last_modal_result"] = self.modals.last_result
        return state

    def _faulted(self, **extra):
        if self.game_fault is not None:
            extra["game_fault"] = dict(self.game_fault)
        return _fail("faulted", self.fault, **extra)

    def _recovering(self, **extra):
        seq = self.seq
        return _fail("recovering", RECOVERING_REASON, interrupted_seq=seq,
                     interrupted_op=seq if self._interrupted[seq]["op"] else None,
                     recovery=dict(self._recovery), **extra)

    def _suspended_state(self, **extra):
        return _fail("not_ready", SUSPENDED_REASON, suspended_seq=self._suspended, **extra)

    def _interrupted_op(self, op_id):
        entry = self._interrupted.get(op_id)
        return entry if entry is not None and entry["op"] else None

    def _state(self):
        connected = self.game_connected
        if self.fault:
            return self._faulted()
        if self.closed:
            return _fail("shutdown", "harness is shutting down")
        if self.seq == 0:
            return _fail("not_ready", "no decision request from the game yet", connected=connected)
        if self._recovery is not None:
            return self._recovering(connected=connected)
        if self._suspended is not None:
            return self._suspended_state(connected=connected)
        if self.modals.watchdog is not None:
            return dict(self.modals.watchdog)
        modal = self.modals.state()
        if modal is not None and connected:
            return {"ok": True, "seq": self.seq, "observation": self._observation, "modal": modal}
        if self._decision_frame is not None and self._result_frame is None:
            return _fail("pending", "a decision for this seq was accepted; call wait_for_turn",
                         op_id=self.seq, connected=connected)
        if self._result_frame is not None:
            return _fail("not_ready", "result recorded; waiting for the next decision request",
                         last_op_id=self.seq, connected=connected)
        if not connected:
            return _fail("disconnected", "game is disconnected; its pending request is kept",
                         seq=self.seq)
        return {"ok": True, "seq": self.seq, "observation": self._observation}

    async def act(self, expect_seq, action, dir=None, budget=20, target=None, until=None, item=None, rationale=None,
                  skill=None, attribute=None):
        if self.fault:
            return self._faulted()
        if self.closed:
            return _fail("shutdown", "harness is shutting down")
        if type(expect_seq) is not int:
            return _fail("invalid", "expect_seq must be an integer")
        if self.seq == 0:
            return _fail("not_ready", "no decision request from the game yet")
        if self._recovery is not None:
            return self._recovering()
        if self._suspended is not None:
            return self._suspended_state()
        if expect_seq != self.seq:
            return _fail("stale_seq", f"expect_seq {expect_seq} is not the current seq {self.seq}",
                         current_seq=self.seq)
        if self.modals.current is not None:
            return _fail("modal_required", "answer the current modal with respond before acting")
        if self._decision_frame is not None:
            return _fail("already_accepted", "a decision for this seq was already accepted; "
                         "call wait_for_turn", op_id=self.seq)
        if not self.game_connected:
            return _fail("disconnected", "game is disconnected; retry after it reconnects")
        try:
            action, dir, budget = wire.normalize_decision(action, dir, budget, target, until, item, skill, attribute)
            wire.validate_observed_item(action, item, self._observation)
            wire.validate_observed_growth(action, skill, attribute, self._observation)
            wire.validate_rationale(rationale)
        except wire.WireError as exc:
            return _fail("invalid", str(exc))

        if self.episode_gate is not None:
            refusal = self.episode_gate.refusal(self.run_id, self.seq)
            if refusal is not None:
                return refusal

        seq = self.seq
        frame = wire.serialize_decision(self.run_id, seq, action, dir, budget, target, until, item, skill, attribute)
        try:
            row = self.ledger.append("decision", seq, self.run_id,
                                     wire.decision_body(self._request_hash, action, dir, budget, target, until, item,
                                                        rationale, skill, attribute))
        except Exception as exc:
            self._violate(f"ledger write failed: {type(exc).__name__}: {exc}")
            return self._faulted()
        self._decision_action = action
        self._decision_frame = frame
        self._decision_hash = row["hash"]
        self._spawn(self._send(self.conn, frame,
                               lambda: (not self.fault and seq not in self._interrupted
                                        and self._suspended != seq)))
        self._notify()
        return await self._await_op(seq, self.act_wait_s)

    async def respond(self, expect_seq, token, response):
        if self._suspended is not None and not self.fault and not self.closed:
            return self._suspended_state()
        return await self.modals.respond(expect_seq, token, response)

    async def wait_for_turn(self, op_id, timeout_s=MAX_WAIT_S):
        if type(op_id) is not int:
            return _fail("invalid", "op_id must be an integer")
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
                or not 0 <= timeout_s <= MAX_WAIT_S):
            return _fail("invalid", f"timeout_s must be within 0..{MAX_WAIT_S:g}")
        known = ((op_id == self.seq and self._decision_frame is not None)
                 or (op_id == self.seq - 1 and self._prev_result_public is not None)
                 or self._interrupted_op(op_id) is not None)
        if not known:
            if self.fault:
                return self._faulted(op_id=op_id)
            return _fail("unknown_op", f"no accepted operation with op_id {op_id}")
        return await self._await_op(op_id, timeout_s)

    def shutdown(self):
        self.closed = True
        self._notify()

    async def drain(self):
        """Wait for broker-owned send tasks (used on shutdown and in tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ----- internals -----

    async def _await_op(self, op_id, timeout):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        def settled():
            return (self.fault or self.closed or self.seq != op_id or self._result_frame is not None
                    or self._interrupted_op(op_id) is not None)

        await self._wait_until(settled, deadline)
        if self.seq == op_id and self._result_frame is not None:
            # The game sends request seq+1 right after the result; give it a moment so the
            # caller learns next_seq without polling.
            grace = min(deadline, loop.time() + NEXT_REQUEST_GRACE_S)
            await self._wait_until(
                lambda: self.fault or self.closed or self.conn is None or self.seq != op_id, grace)
        return self._op_report(op_id)

    def _op_report(self, op_id):
        # A faulted run never reports ok:true, even for a result recorded before the fault.
        if self.fault:
            return self._faulted(op_id=op_id)
        interrupted = self._interrupted_op(op_id)
        if interrupted is not None:
            return _fail("interrupted", INTERRUPTED_REASON, op_id=op_id, completed=False,
                         recovery=dict(interrupted["recovery"]),
                         next_seq=op_id + 1 if self.seq > op_id else None)
        if op_id == self.seq and self._result_frame is not None:
            return {"ok": True, "op_id": op_id, "completed": True, "result": self._result_public,
                    "next_seq": None}
        if op_id == self.seq - 1 and self._prev_result_public is not None:
            return {"ok": True, "op_id": op_id, "completed": True,
                    "result": self._prev_result_public, "next_seq": self.seq}
        if self.closed:
            return _fail("shutdown", "harness is shutting down", op_id=op_id)
        if op_id == self.seq and self._decision_frame is not None:
            return {"ok": True, "pending": True, "op_id": op_id}
        return _fail("unknown_op", f"no accepted operation with op_id {op_id}")

    async def _wait_until(self, predicate, deadline):
        loop = asyncio.get_running_loop()
        while not predicate():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError:
                pass
        return True

    def _notify(self):
        self._changed.set()
        self._changed = asyncio.Event()

    def _spawn(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, conn, frame, still_valid=None):
        if still_valid is not None and not still_valid():
            # A recovery, suspension or fault arrived between acceptance and this send task
            # running; never deliver it into a reloaded, ended (or dead) game.
            log.info("dropped an unsent frame whose operation was interrupted, suspended or faulted")
            return
        try:
            await conn.send(frame)
        except Exception as exc:
            log.warning("decision send failed (%s); it is replayed when the game re-sends "
                        "the pending request", type(exc).__name__)
