"""Save/checkpoint recovery and fatal game faults.

A recovery interrupts the current request seq (and any accepted decision) without a
result; the game's next request must be seq+1. A game_fault ends the run. Neither may
ever be reported as a completed action.
"""
import asyncio
import copy
import json
import unittest
from pathlib import Path

from harness import wire
from harness.broker import Broker, ProtocolViolation, Refused
from harness.ledger import Ledger
from harness.verify import VerifyError, verify_ledger
from tests.support import (OTHER_RECOVERY_ID, RECOVERY_ID, RUN_ID, SAVE_SHA256, game_fault_frame,
                           heartbeat_frame, recovery_frame, request_frame, result_frame,
                           suspended_frame)
from tests.test_broker import BrokerTestCase, FakeConn, ledger_rows
from tests.test_ledger_verify import read_rows, write_rows
from tests.test_modal_broker import modal_frame, modal_result


# ----- wire -----

class RecoveryWireTests(unittest.TestCase):
    def test_valid_recovery_frames_parse(self):
        for reason in ("checkpoint_reload", "save_reload"):
            with self.subTest(reason=reason):
                message = wire.parse_game_frame(recovery_frame(3, reason=reason))
                self.assertEqual(message["kind"], "recovery")
                self.assertEqual(message["lost_turns"], 20)
        forward = wire.parse_game_frame(recovery_frame(1, turn_before=5, loaded_turn=9))
        self.assertEqual(forward["lost_turns"], 0)
        wire.parse_game_frame(recovery_frame(1, turn_before=0, loaded_turn=0))

    def test_invalid_recovery_frames_are_rejected(self):
        cases = {
            "seq zero": recovery_frame(0),
            "seq bool": recovery_frame(True),
            "unknown reason": recovery_frame(1, reason="death"),
            "checkpoint with Primary": recovery_frame(1, save_file="Primary"),
            "save with Checkpoint": recovery_frame(1, reason="save_reload", save_file="Checkpoint"),
            "unknown save file": recovery_frame(1, save_file="Autosave"),
            "empty game id": recovery_frame(1, game_id=""),
            "long game id": recovery_frame(1, game_id="g" * 129),
            "game id int": recovery_frame(1, game_id=7),
            "sha uppercase": recovery_frame(1, save_sha256=SAVE_SHA256.upper()),
            "sha short": recovery_frame(1, save_sha256=SAVE_SHA256[:63]),
            "sha non hex": recovery_frame(1, save_sha256="g" * 64),
            "sha underscore": recovery_frame(1, save_sha256="0_" * 32),
            "negative turn_before": recovery_frame(1, turn_before=-1, loaded_turn=0, lost_turns=0),
            "negative loaded_turn": recovery_frame(1, turn_before=1, loaded_turn=-1, lost_turns=2),
            "bool turn": recovery_frame(1, turn_before=True, loaded_turn=0, lost_turns=1),
            "wrong lost_turns": recovery_frame(1, lost_turns=19),
            "negative lost_turns": recovery_frame(1, turn_before=5, loaded_turn=9, lost_turns=-4),
            "recovery id not uuid": recovery_frame(1, recovery_id="checkpoint-1"),
            "recovery id int": recovery_frame(1, recovery_id=1),
            "run id not uuid": recovery_frame(1, run_id="run"),
            "extra key": recovery_frame(1, observation={}),
        }
        missing = json.loads(recovery_frame(1))
        del missing["save_sha256"]
        cases["missing key"] = json.dumps(missing)
        for name, frame in cases.items():
            with self.subTest(case=name), self.assertRaises(wire.WireError):
                wire.parse_game_frame(frame)

    def test_game_fault_frames(self):
        self.assertEqual(wire.parse_game_frame(game_fault_frame(2))["reason"],
                         "player died with no checkpoint to reload")
        extra = json.loads(game_fault_frame(1))
        extra["observation"] = {}
        for name, frame in {"empty reason": game_fault_frame(1, reason=""),
                            "long reason": game_fault_frame(1, reason="x" * 1025),
                            "reason int": game_fault_frame(1, reason=3),
                            "seq zero": game_fault_frame(0),
                            "extra key": json.dumps(extra)}.items():
            with self.subTest(case=name), self.assertRaises(wire.WireError):
                wire.parse_game_frame(frame)
        wire.parse_game_frame(game_fault_frame(1, reason="x" * 1024))


# ----- broker: recovery -----

class RecoveryBrokerTests(BrokerTestCase):
    def rows(self):
        return ledger_rows(self.ledger_path)

    def recover(self, seq=1, conn=None, **kwargs):
        return self.broker.handle_frame(conn or self.conn, recovery_frame(seq, **kwargs))

    async def test_accepted_decision_is_interrupted_without_a_result(self):
        self.start()
        self.assertTrue((await self.broker.act(1, "move", "N"))["pending"])
        frame = recovery_frame(1)
        self.assertIsNone(self.broker.handle_frame(self.conn, frame))
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("recovery", 1)])
        rows = self.rows()
        body = rows[2]["body"]
        self.assertEqual(body["request_hash"], rows[0]["hash"])
        self.assertEqual(body["decision_hash"], rows[1]["hash"])
        self.assertEqual(body["frame_sha256"], wire.frame_sha256(frame))
        self.assertEqual({k: v for k, v in body.items()
                          if k not in ("request_hash", "decision_hash", "frame_sha256")},
                         {k: v for k, v in json.loads(frame).items()
                          if k not in ("kind", "run_id", "seq")})

        state = self.broker.get_state()
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "recovering")
        self.assertEqual(state["interrupted_seq"], 1)
        self.assertEqual(state["recovery"]["lost_turns"], 20)
        self.assertEqual(state["recovery"]["recovery_id"], RECOVERY_ID)
        self.assertNotIn("observation", state)
        for args in ((1, "wait"), (2, "wait")):
            with self.subTest(args=args):
                refused = await self.broker.act(*args)
                self.assertFalse(refused["ok"])
                self.assertEqual(refused["status"], "recovering")
        interrupted = await self.broker.wait_for_turn(1, 0)
        self.assertFalse(interrupted["ok"])
        self.assertFalse(interrupted["completed"])
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["op_id"], 1)
        self.assertIsNone(interrupted["next_seq"])
        self.assertEqual(interrupted["recovery"]["loaded_turn"], 100)
        self.assertNotIn("result", interrupted)

        self.assertIsNone(self.broker.handle_frame(self.conn, request_frame(2, turn=100)))
        self.assertEqual(self.kinds()[-1], ("request", 2))
        self.assertNotIn("result", [kind for kind, _ in self.kinds()])
        state = self.broker.get_state()
        self.assertTrue(state["ok"])
        self.assertEqual(state["seq"], 2)
        after = await self.broker.wait_for_turn(1, 0)
        self.assertEqual(after["status"], "interrupted")
        self.assertFalse(after["completed"])
        self.assertEqual(after["next_seq"], 2)
        self.assertEqual((await self.broker.act(1, "wait"))["status"], "stale_seq")
        self.assertEqual(len(self.conn.sent), 1, "the interrupted decision is never resent")

        await self.broker.act(2, "wait")
        self.broker.handle_frame(self.conn, result_frame(2, "wait"))
        self.broker.handle_frame(self.conn, request_frame(3))
        summary = verify_ledger(self.ledger_path, require_completed=1)
        self.assertEqual(summary["recoveries"], 1)
        self.assertEqual(summary["interrupted_decisions"], 1)
        self.assertEqual(summary["lost_turns"], 20)
        self.assertIsNone(summary["recovering_seq"])
        self.assertIsNone(summary["game_fault"])

    async def test_unaccepted_request_is_interrupted(self):
        self.start()
        self.assertIsNone(self.recover(reason="save_reload", turn_before=7, loaded_turn=9))
        body = self.rows()[-1]["body"]
        self.assertIsNone(body["decision_hash"])
        self.assertEqual(body["lost_turns"], 0)
        self.assertEqual(self.broker.get_state()["status"], "recovering")
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "unknown_op")
        summary = verify_ledger(self.ledger_path)
        self.assertEqual(summary["recovering_seq"], 1)
        self.assertEqual(summary["interrupted_decisions"], 0)
        self.assertIsNone(summary["pending"])
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertTrue(self.broker.get_state()["ok"])
        summary = verify_ledger(self.ledger_path)
        self.assertEqual((summary["recoveries"], summary["lost_turns"]), (1, 0))
        self.assertEqual(summary["pending"], "request")
        self.assertEqual(summary["pending_seq"], 2)

    async def test_result_for_interrupted_seq_is_never_accepted(self):
        for fresh in (False, True):
            with self.subTest(after_fresh_request=fresh):
                broker, conn, path = self.fresh_broker()
                broker.handle_frame(conn, request_frame(1))
                await broker.act(1, "wait")
                broker.handle_frame(conn, recovery_frame(1))
                if fresh:
                    broker.handle_frame(conn, request_frame(2))
                with self.assertRaises(ProtocolViolation):
                    broker.handle_frame(conn, result_frame(1, "wait"))
                self.assertNotIn("result", [row["kind"] for row in ledger_rows(path)])
                self.assertEqual(broker.get_state()["status"], "faulted")
                self.assertNotEqual((await broker.wait_for_turn(1, 0)).get("ok"), True)

    async def test_request_replay_after_recovery_never_resends_interrupted_decision(self):
        self.start()
        await self.broker.act(1, "attack", "NE")
        self.recover()
        self.assertIsNone(self.broker.handle_frame(self.conn, request_frame(1)))
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        # The bridge replays its latest recovery, then its latest request.
        self.assertIsNone(self.broker.handle_frame(conn2, recovery_frame(1)))
        self.assertIsNone(self.broker.handle_frame(conn2, request_frame(1)))
        await self.broker.drain()
        self.assertEqual(conn2.sent, [])
        self.assertEqual(self.broker.get_state()["status"], "recovering")
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("recovery", 1)])
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(conn2, request_frame(1, hp=3))

    async def test_exact_recovery_replay_is_idempotent_after_next_seqs_and_reconnect(self):
        self.start()
        await self.broker.act(1, "wait")
        self.recover()
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertIsNone(self.recover())
        await self.broker.act(2, "move", "S")
        self.broker.handle_frame(self.conn, result_frame(2, "move"))
        self.broker.handle_frame(self.conn, request_frame(3))
        await self.broker.act(3, "wait")
        before = self.kinds()
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        self.assertIsNone(self.broker.handle_frame(conn2, recovery_frame(1)))
        self.assertEqual(self.broker.handle_frame(conn2, request_frame(3)), self.conn.sent[-1],
                         "the current seq's accepted decision is still replayed")
        self.assertIsNone(self.broker.handle_frame(conn2, recovery_frame(1)))
        self.assertEqual(self.kinds(), before)
        self.assertEqual(self.broker.get_state()["status"], "pending")
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_changed_recovery_replay_is_a_violation(self):
        variants = [recovery_frame(1, turn_before=121, loaded_turn=100),
                    recovery_frame(1, recovery_id=RECOVERY_ID.upper()),
                    json.dumps(json.loads(recovery_frame(1)), separators=(",", ":"))]
        for index, changed in enumerate(variants):
            with self.subTest(variant=index):
                broker, conn, path = self.fresh_broker()
                broker.handle_frame(conn, request_frame(1))
                broker.handle_frame(conn, recovery_frame(1))
                broker.handle_frame(conn, request_frame(2))
                with self.assertRaises(ProtocolViolation):
                    broker.handle_frame(conn, changed)
                self.assertEqual(broker.get_state()["status"], "faulted")
                self.assertEqual([row["kind"] for row in ledger_rows(path)],
                                 ["request", "recovery", "request"])

    async def test_invalid_recovery_sequences_fail_closed(self):
        async def accepted_then_result(broker, conn):
            await broker.act(1, "wait")
            broker.handle_frame(conn, result_frame(1, "wait"))
            return recovery_frame(1)

        async def undelivered(broker, conn):
            return recovery_frame(2)

        async def second_recovery(broker, conn):
            broker.handle_frame(conn, recovery_frame(1))
            return recovery_frame(1, recovery_id=OTHER_RECOVERY_ID)

        async def old_seq(broker, conn):
            broker.handle_frame(conn, recovery_frame(1))
            broker.handle_frame(conn, request_frame(2))
            return recovery_frame(1, recovery_id=OTHER_RECOVERY_ID)

        async def bad_loss(broker, conn):
            return recovery_frame(1, lost_turns=3)

        async def bad_pairing(broker, conn):
            return recovery_frame(1, reason="save_reload", save_file="Checkpoint")

        async def unknown_reason(broker, conn):
            return recovery_frame(1, reason="rewind", save_file="Checkpoint")

        async def seq_zero(broker, conn):
            return recovery_frame(0)

        for setup in (accepted_then_result, undelivered, second_recovery, old_seq, bad_loss,
                      bad_pairing, unknown_reason, seq_zero):
            with self.subTest(case=setup.__name__):
                broker, conn, path = self.fresh_broker()
                broker.handle_frame(conn, request_frame(1))
                frame = await setup(broker, conn)
                before = ledger_rows(path)
                with self.assertRaises(ProtocolViolation):
                    broker.handle_frame(conn, frame)
                self.assertEqual(ledger_rows(path), before)
                self.assertEqual(broker.get_state()["status"], "faulted")
                self.assertTrue(verify_ledger(path)["ok"])

    async def test_unbound_lifecycle_frames_are_refused(self):
        self.broker.attach(self.conn)
        for frame in (recovery_frame(1), game_fault_frame(1)):
            with self.subTest(kind=json.loads(frame)["kind"]), self.assertRaises(Refused):
                self.broker.handle_frame(self.conn, frame)
        self.assertIsNone(self.broker.run_id)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.broker.get_state()["status"], "not_ready")
        self.assertIsNone(self.broker.handle_frame(self.conn, request_frame(1)))
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_next_request_must_be_seq_plus_one(self):
        for seq in (3, 1_000):
            with self.subTest(seq=seq):
                broker, conn, path = self.fresh_broker()
                broker.handle_frame(conn, request_frame(1))
                broker.handle_frame(conn, recovery_frame(1))
                with self.assertRaises(ProtocolViolation):
                    broker.handle_frame(conn, request_frame(seq))
                self.assertEqual([r["kind"] for r in ledger_rows(path)], ["request", "recovery"])

    async def test_decision_not_yet_sent_is_dropped_after_recovery(self):
        self.start()
        act = asyncio.create_task(self.broker.act(1, "wait"))
        await asyncio.sleep(0)  # act accepted and journaled; its send task has not run yet
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        self.recover()
        self.assertEqual((await asyncio.wait_for(act, 1))["status"], "interrupted")
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [], "an interrupted decision is not sent afterwards")

    async def test_answer_not_yet_sent_is_dropped_after_recovery(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        task = asyncio.create_task(self.broker.respond(1, "popup-1", {"choice": "button:1"}))
        await asyncio.sleep(0)
        self.recover()
        self.assertEqual((await asyncio.wait_for(task, 1))["status"], "interrupted")
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [])

    async def test_recovery_ledger_failure_faults(self):
        self.start()
        await self.broker.act(1, "wait")

        def broken_append(*args, **kwargs):
            raise OSError("disk full")

        self.ledger.append = broken_append
        with self.assertRaises(ProtocolViolation):
            self.recover()
        self.assertEqual(self.broker.get_state()["status"], "faulted")
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "faulted")

    async def test_heartbeat_during_recovery_keeps_recovering(self):
        self.start()
        self.recover()
        self.broker.handle_frame(self.conn, heartbeat_frame(1))
        self.assertEqual(self.broker.get_state()["status"], "recovering")

    def fresh_broker(self):
        name = f"ledger-{len(self._extra)}.jsonl"
        path = Path(self.tmp.name) / name
        ledger = Ledger.create(path)
        broker = Broker(ledger, act_wait_s=self.act_wait_s)
        conn = FakeConn()
        broker.attach(conn)
        self._extra.append((broker, ledger))
        return broker, conn, path

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._extra = []

    async def asyncTearDown(self):
        for broker, ledger in self._extra:
            broker.shutdown()
            await broker.drain()
            ledger.close()
        await super().asyncTearDown()


class RecoveryWaiterTests(BrokerTestCase):
    act_wait_s = 30

    async def test_waiting_act_and_wait_for_turn_wake_as_interrupted(self):
        self.start()
        act = asyncio.create_task(self.broker.act(1, "explore", None, 20))
        for _ in range(3):
            await asyncio.sleep(0)
        waiter = asyncio.create_task(self.broker.wait_for_turn(1, 30))
        await asyncio.sleep(0)
        self.broker.handle_frame(self.conn, recovery_frame(1))
        for task in (act, waiter):
            report = await asyncio.wait_for(task, 1)
            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "interrupted")
            self.assertFalse(report["completed"])
            self.assertEqual(report["recovery"]["save_file"], "Checkpoint")

    async def test_pending_respond_is_released_as_interrupted(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        task = asyncio.create_task(self.broker.respond(1, "popup-1", {"choice": "button:1"}))
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertEqual(len(self.conn.sent), 1)
        self.broker.handle_frame(self.conn, recovery_frame(1))
        report = await asyncio.wait_for(task, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["answer_id"], 1)
        state = self.broker.get_state()
        self.assertEqual(state["status"], "recovering")
        self.assertNotIn("modal", state)
        self.assertEqual(state["last_modal_result"]["status"], "interrupted")

    async def test_pending_respond_is_released_by_game_fault(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        task = asyncio.create_task(self.broker.respond(1, "popup-1", {"choice": "button:1"}))
        for _ in range(3):
            await asyncio.sleep(0)
        self.broker.handle_frame(self.conn, game_fault_frame(1))
        report = await asyncio.wait_for(task, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "faulted")
        self.assertIn("reason", report)

    async def test_waiting_act_wakes_as_faulted_on_game_fault(self):
        self.start()
        act = asyncio.create_task(self.broker.act(1, "wait"))
        for _ in range(3):
            await asyncio.sleep(0)
        self.broker.handle_frame(self.conn, game_fault_frame(1))
        report = await asyncio.wait_for(act, 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "faulted")
        rows = ledger_rows(self.ledger_path)
        self.assertEqual(rows[-1]["body"]["decision_hash"], rows[1]["hash"])


class RecoveryModalTests(BrokerTestCase):
    async def test_interrupted_modal_cannot_be_revived(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        answer = await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.assertTrue(answer["pending"])
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.assertEqual(self.broker.modals.answers[1]["result"]["status"], "interrupted")
        # A historical exact modal replay is ignored and never becomes current again.
        self.assertIsNone(self.broker.handle_frame(self.conn, modal_frame()))
        state = self.broker.get_state()
        self.assertEqual(state["status"], "recovering")
        self.assertNotIn("modal", state)
        stale = await self.broker.respond(1, "popup-1", {"choice": "button:0"})
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["status"], "recovering")
        self.assertEqual(len(self.conn.sent), 1, "no answer is resent or re-submitted")
        before = ledger_rows(self.ledger_path)
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, modal_result())
        self.assertEqual(ledger_rows(self.ledger_path), before)
        self.assertEqual(self.broker.modals.answers[1]["result"]["status"], "interrupted")
        self.assertEqual(self.broker.get_state()["status"], "faulted")

    async def test_new_modal_data_for_interrupted_seq_is_rejected(self):
        clear = json.dumps({"kind": "modal_clear", "run_id": RUN_ID, "seq": 1,
                            "token": "popup-1", "reason": "external_close"})
        watchdog = json.dumps({"kind": "modal_watchdog", "run_id": RUN_ID, "seq": 1,
                               "reason": "unhandled_modal", "view": "DeathScreen",
                               "type": "unknown", "elapsed_ms": 30001})
        auto = json.dumps({"kind": "modal_auto", "run_id": RUN_ID, "seq": 1, "token": "auto-1",
                           "rule": "dismiss", "modal": json.loads(modal_frame())["modal"],
                           "accepted": True, "reason": "auto"})
        cases = {"new modal": modal_frame(token="popup-2"), "clear": clear,
                 "watchdog": watchdog, "auto": auto}
        for name, frame in cases.items():
            for fresh in (False, True):
                with self.subTest(case=name, after_fresh_request=fresh):
                    tmp = Path(self.tmp.name) / f"{name}-{fresh}.jsonl"
                    ledger = Ledger.create(tmp)
                    broker = Broker(ledger, act_wait_s=self.act_wait_s)
                    conn = FakeConn()
                    try:
                        broker.attach(conn)
                        broker.handle_frame(conn, request_frame(1))
                        broker.handle_frame(conn, modal_frame())
                        broker.handle_frame(conn, recovery_frame(1))
                        if fresh:
                            broker.handle_frame(conn, request_frame(2))
                        before = ledger_rows(tmp)
                        with self.assertRaises(ProtocolViolation):
                            broker.handle_frame(conn, frame)
                        self.assertEqual(ledger_rows(tmp), before)
                    finally:
                        broker.shutdown()
                        await broker.drain()
                        ledger.close()

    async def test_modal_exchange_resumes_on_fresh_request(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertIsNone(self.broker.handle_frame(self.conn, modal_frame()), "historical replay")
        self.assertNotIn("modal", self.broker.get_state())
        self.assertEqual((await self.broker.respond(1, "popup-1", {"choice": "button:0"}))["status"],
                         "stale_seq")
        self.broker.handle_frame(self.conn, modal_frame(token="popup-2", seq=2))
        self.assertEqual(self.broker.get_state()["modal"]["token"], "popup-2")
        second = await self.broker.respond(2, "popup-2", {"choice": "button:0"})
        self.assertEqual(second["answer_id"], 2)
        self.broker.handle_frame(self.conn, modal_result(answer_id=2, token="popup-2", seq=2))
        self.assertTrue(self.broker.get_state()["last_modal_result"]["accepted"])
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_acknowledged_modal_before_recovery_is_kept(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, modal_frame())
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.broker.handle_frame(self.conn, modal_result())
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.assertTrue(self.broker.modals.answers[1]["result"]["accepted"])
        self.assertIsNone(self.broker.handle_frame(self.conn, modal_result()), "exact replay")
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])


# ----- broker: game_fault -----

class GameFaultTests(BrokerTestCase):
    async def test_game_fault_is_terminal_and_never_reports_stale_readiness(self):
        self.start()
        frame = game_fault_frame(1)
        self.assertIsNone(self.broker.handle_frame(self.conn, frame))
        rows = ledger_rows(self.ledger_path)
        self.assertEqual([r["kind"] for r in rows], ["request", "game_fault"])
        self.assertEqual(rows[1]["body"], {"reason": "player died with no checkpoint to reload",
                                           "frame_sha256": wire.frame_sha256(frame),
                                           "request_hash": rows[0]["hash"],
                                           "decision_hash": None})
        state = self.broker.get_state()
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "faulted")
        self.assertIn("player died with no checkpoint to reload", state["reason"])
        self.assertNotIn("observation", state)
        self.assertEqual((await self.broker.act(1, "wait"))["status"], "faulted")
        self.assertEqual((await self.broker.respond(1, "t", {"cancel": True}))["status"], "faulted")
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "faulted")
        self.assertIsNone(self.broker.handle_frame(self.conn, frame), "exact duplicate is harmless")
        self.assertEqual(len(ledger_rows(self.ledger_path)), 2)
        for later in (game_fault_frame(1, reason="another"), request_frame(2), recovery_frame(1)):
            with self.subTest(frame=later[:40]), self.assertRaises(ProtocolViolation):
                self.broker.handle_frame(self.conn, later)
        self.assertEqual(len(ledger_rows(self.ledger_path)), 2)
        self.broker.detach(self.conn)
        with self.assertRaises(Refused):
            self.broker.attach(FakeConn())
        self.assertEqual(self.conn.sent, [])
        summary = verify_ledger(self.ledger_path)
        self.assertEqual(summary["game_fault"], {"seq": 1,
                                                 "reason": "player died with no checkpoint to reload"})
        self.assertIsNone(summary["pending"])

    async def test_faulted_state_carries_no_nested_ok_true(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.broker.handle_frame(self.conn, modal_result())
        self.assertTrue(self.broker.get_state()["last_modal_result"]["ok"])
        self.broker.handle_frame(self.conn, game_fault_frame(1))

        def has_ok_true(value):
            if isinstance(value, dict):
                return value.get("ok") is True or any(has_ok_true(v) for v in value.values())
            if isinstance(value, list):
                return any(has_ok_true(v) for v in value)
            return False

        state = self.broker.get_state()
        self.assertEqual(state["status"], "faulted")
        self.assertFalse(has_ok_true(state), state)

    async def test_game_fault_after_result_does_not_report_completion(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, game_fault_frame(1))
        report = await self.broker.wait_for_turn(1, 0)
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "faulted")
        rows = ledger_rows(self.ledger_path)
        self.assertEqual(rows[-1]["body"]["decision_hash"], rows[1]["hash"])
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["game_fault"]["seq"], 1)

    async def test_game_fault_during_recovery_links_the_interrupted_decision(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.broker.handle_frame(self.conn, game_fault_frame(1, reason="checkpoint reload failed"))
        rows = ledger_rows(self.ledger_path)
        self.assertEqual(rows[-1]["body"]["decision_hash"], rows[1]["hash"])
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "faulted")
        summary = verify_ledger(self.ledger_path)
        self.assertEqual(summary["recoveries"], 1)
        self.assertEqual(summary["game_fault"]["reason"], "checkpoint reload failed")

    async def test_game_fault_for_other_seq_is_a_protocol_violation(self):
        self.start()
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, game_fault_frame(2))
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertEqual(self.broker.get_state()["status"], "faulted")


# ----- suspension: the controlled game stopped running (e.g. exited to the main menu) -----

def death_auto_frame(seq=1, token="death-1"):
    modal = {"type": "popup", "title": "", "text": "You died.", "input_kind": "none",
             "constraints": {},
             "choices": [{"id": "option:0", "label": "Reload from checkpoint"},
                         {"id": "option:1", "label": "Quit to main menu"}]}
    return json.dumps({"kind": "modal_auto", "run_id": RUN_ID, "seq": seq, "token": token,
                       "rule": "death_reload_checkpoint", "modal": modal, "accepted": True,
                       "reason": "rule"})


class SuspensionWireTests(unittest.TestCase):
    def test_valid_suspended_frame_parses(self):
        message = wire.parse_game_frame(suspended_frame(3))
        self.assertEqual((message["kind"], message["seq"], message["reason"]),
                         ("suspended", 3, "game_not_running"))

    def test_invalid_suspended_frames_are_rejected(self):
        missing = json.loads(suspended_frame(1))
        del missing["reason"]
        cases = {"seq zero": suspended_frame(0), "seq bool": suspended_frame(True),
                 "unknown reason": suspended_frame(1, reason="menu"),
                 "reason int": suspended_frame(1, reason=1),
                 "run id not uuid": suspended_frame(1, run_id="run"),
                 "extra key": suspended_frame(1, observation={}),
                 "missing key": json.dumps(missing)}
        for name, frame in cases.items():
            with self.subTest(case=name), self.assertRaises(wire.WireError):
                wire.parse_game_frame(frame)


class SuspensionBrokerTests(BrokerTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._extra = []

    async def asyncTearDown(self):
        for broker, ledger in self._extra:
            broker.shutdown()
            await broker.drain()
            ledger.close()
        await super().asyncTearDown()

    def fresh_broker(self):
        path = Path(self.tmp.name) / f"suspend-{len(self._extra)}.jsonl"
        ledger = Ledger.create(path)
        broker = Broker(ledger, act_wait_s=self.act_wait_s)
        conn = FakeConn()
        broker.attach(conn)
        self._extra.append((broker, ledger))
        return broker, conn, path

    def suspend(self, seq=1, conn=None, **kwargs):
        return self.broker.handle_frame(conn or self.conn, suspended_frame(seq, **kwargs))

    def assertSuspended(self, seq=1):
        state = self.broker.get_state()
        self.assertFalse(state["ok"], state)
        self.assertEqual(state["status"], "not_ready")
        self.assertEqual(state["suspended_seq"], seq)
        for key in ("observation", "modal", "last_op_id", "seq"):
            self.assertNotIn(key, state)
        return state

    async def test_stale_request_is_not_actionable_after_suspension(self):
        self.start()
        self.assertTrue(self.broker.get_state()["ok"])
        frame = suspended_frame(1)
        self.assertIsNone(self.broker.handle_frame(self.conn, frame))
        rows = ledger_rows(self.ledger_path)
        self.assertEqual([(r["kind"], r["seq"]) for r in rows], [("request", 1), ("suspended", 1)])
        self.assertEqual(rows[1]["body"], {"reason": "game_not_running",
                                           "frame_sha256": wire.frame_sha256(frame),
                                           "request_hash": rows[0]["hash"],
                                           "decision_hash": None})
        self.assertSuspended()
        # Heartbeats keep flowing from the menu; they never revive the old request.
        self.broker.handle_frame(self.conn, heartbeat_frame(1))
        self.assertSuspended()
        for args in ((1, "wait"), (2, "wait"), (1, "move", "N")):
            with self.subTest(args=args):
                refused = await self.broker.act(*args)
                self.assertFalse(refused["ok"])
                self.assertEqual(refused["status"], "not_ready")
        # A reconnect replays the historical request bytes: never an actionable request.
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        self.assertIsNone(self.broker.handle_frame(conn2, request_frame(1)))
        self.assertIsNone(self.broker.handle_frame(conn2, frame), "exact replay is idempotent")
        self.assertSuspended()
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "unknown_op")
        await self.broker.drain()
        self.assertEqual(self.conn.sent + conn2.sent, [])
        self.assertEqual(len(ledger_rows(self.ledger_path)), 2)
        summary = verify_ledger(self.ledger_path)
        self.assertEqual(summary["suspended_seq"], 1)
        self.assertIsNone(summary["pending"])

    async def test_primary_reload_after_suspension_continues_next_seq(self):
        self.start()
        self.suspend()
        self.assertIsNone(self.broker.handle_frame(
            self.conn, recovery_frame(1, reason="save_reload", turn_before=3, loaded_turn=3)))
        state = self.broker.get_state()
        self.assertEqual(state["status"], "recovering")
        self.assertNotIn("suspended_seq", state)
        self.broker.handle_frame(self.conn, request_frame(2, turn=3))
        state = self.broker.get_state()
        self.assertTrue(state["ok"])
        self.assertEqual(state["seq"], 2)
        await self.broker.act(2, "wait")
        self.broker.handle_frame(self.conn, result_frame(2, "wait"))
        self.broker.handle_frame(self.conn, request_frame(3))
        self.assertIsNone(self.suspend(), "historical exact replay after later seqs")
        self.assertEqual(self.kinds(), [("request", 1), ("suspended", 1), ("recovery", 1),
                                        ("request", 2), ("decision", 2), ("result", 2),
                                        ("request", 3)])
        summary = verify_ledger(self.ledger_path, require_completed=1)
        self.assertEqual((summary["recoveries"], summary["suspensions"]), (1, 1))
        self.assertIsNone(summary["suspended_seq"])

    async def test_late_decision_is_interrupted_never_completed(self):
        self.start()
        self.assertTrue((await self.broker.act(1, "move", "N"))["pending"])
        self.assertEqual(len(self.conn.sent), 1)
        self.suspend()
        self.assertSuspended()
        self.assertIsNone(self.broker.handle_frame(self.conn, request_frame(1)),
                          "the accepted decision is never resent into an ended game")
        pending = await self.broker.wait_for_turn(1, 0)
        self.assertNotIn("completed", pending)
        self.assertNotIn("result", pending)
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, result_frame(1, "move"))
        self.assertEqual(self.broker.get_state()["status"], "faulted")

        broker, conn, path = self.fresh_broker()
        broker.handle_frame(conn, request_frame(1))
        await broker.act(1, "move", "N")
        broker.handle_frame(conn, suspended_frame(1))
        waiter = asyncio.create_task(broker.wait_for_turn(1, 5))
        await asyncio.sleep(0)
        broker.handle_frame(conn, recovery_frame(1, reason="save_reload"))
        report = await asyncio.wait_for(waiter, 1)
        self.assertEqual(report["status"], "interrupted")
        self.assertFalse(report["completed"])
        rows = ledger_rows(path)
        self.assertEqual([r["kind"] for r in rows], ["request", "decision", "suspended", "recovery"])
        self.assertEqual(rows[2]["body"]["decision_hash"], rows[1]["hash"])
        self.assertEqual(rows[3]["body"]["decision_hash"], rows[1]["hash"])
        broker.handle_frame(conn, request_frame(2))
        self.assertTrue(broker.get_state()["ok"])
        self.assertEqual(len(conn.sent), 1)
        self.assertEqual(verify_ledger(path)["interrupted_decisions"], 1)

    async def test_decision_not_yet_sent_is_dropped_after_suspension(self):
        self.start()
        act = asyncio.create_task(self.broker.act(1, "wait"))
        await asyncio.sleep(0)  # act accepted and journaled; its send task has not run yet
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        self.suspend()
        self.assertNotIn("completed", await asyncio.wait_for(act, 1))
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [], "a decision is never sent into a suspended game")

    async def test_modal_is_not_answerable_while_suspended(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        self.assertIn("modal", self.broker.get_state())
        self.suspend()
        self.assertSuspended()
        refused = await self.broker.respond(1, "popup-1", {"choice": "button:1"})
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["status"], "not_ready")
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [])
        self.assertNotIn("modal_answer", [kind for kind, _ in self.kinds()])

    async def test_unsent_modal_answer_is_dropped_when_game_suspends(self):
        self.start()
        self.broker.handle_frame(self.conn, modal_frame())
        answer = asyncio.create_task(self.broker.respond(1, "popup-1", {"choice": "button:1"}))
        await asyncio.sleep(0)
        self.assertIn("modal_answer", [kind for kind, _ in self.kinds()])
        self.suspend()
        response = await asyncio.wait_for(answer, 1)
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [], "a queued modal answer must not reach an ended game")
        self.assertEqual(response["status"], "not_ready")
        self.assertNotIn("completed", response)

    async def test_menu_modal_during_suspension_is_journaled_but_never_exposed(self):
        self.start()
        self.suspend()
        self.assertIsNone(self.broker.handle_frame(self.conn, modal_frame()))
        self.assertSuspended()
        self.assertEqual((await self.broker.respond(1, "popup-1", {"choice": "button:0"}))["status"],
                         "not_ready")
        self.broker.handle_frame(self.conn, recovery_frame(1, reason="save_reload"))
        self.broker.handle_frame(self.conn, request_frame(2))
        state = self.broker.get_state()
        self.assertTrue(state["ok"])
        self.assertNotIn("modal", state)
        await self.broker.drain()
        self.assertEqual(self.conn.sent, [])
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_death_menu_rule_and_checkpoint_reload_after_suspension(self):
        self.start()
        self.suspend()
        # The automatic death-menu rule keeps running; its record is journaled.
        self.assertIsNone(self.broker.handle_frame(self.conn, death_auto_frame()))
        self.assertSuspended()
        self.broker.handle_frame(self.conn, recovery_frame(1))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertTrue(self.broker.get_state()["ok"])
        self.assertEqual(self.kinds(), [("request", 1), ("suspended", 1), ("modal_auto", 1),
                                        ("recovery", 1), ("request", 2)])
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])

    async def test_game_fault_after_suspension_is_terminal(self):
        self.start()
        await self.broker.act(1, "wait")
        self.suspend()
        self.broker.handle_frame(self.conn, game_fault_frame(1, reason="load_recovery:Invalid"))
        self.assertEqual(self.broker.get_state()["status"], "faulted")
        self.assertEqual((await self.broker.wait_for_turn(1, 0))["status"], "faulted")
        rows = ledger_rows(self.ledger_path)
        self.assertEqual(rows[-1]["body"]["decision_hash"], rows[1]["hash"])
        self.assertEqual(verify_ledger(self.ledger_path)["game_fault"]["seq"], 1)

    async def test_invalid_suspension_sequences_fail_closed(self):
        async def next_request(broker, conn):
            broker.handle_frame(conn, suspended_frame(1))
            return request_frame(2)

        async def result_after(broker, conn):
            await broker.act(1, "wait")
            broker.handle_frame(conn, suspended_frame(1))
            return result_frame(1, "wait")

        async def changed_replay(broker, conn):
            broker.handle_frame(conn, suspended_frame(1))
            return json.dumps(json.loads(suspended_frame(1)), separators=(",", ":"))

        async def changed_replay_after_recovery(broker, conn):
            broker.handle_frame(conn, suspended_frame(1))
            broker.handle_frame(conn, recovery_frame(1))
            broker.handle_frame(conn, request_frame(2))
            return json.dumps(json.loads(suspended_frame(1)), separators=(",", ":"))

        async def other_seq(broker, conn):
            return suspended_frame(2)

        async def after_recovery(broker, conn):
            broker.handle_frame(conn, recovery_frame(1))
            return suspended_frame(1)

        async def after_result(broker, conn):
            await broker.act(1, "wait")
            broker.handle_frame(conn, result_frame(1, "wait"))
            return suspended_frame(1)

        for setup in (next_request, result_after, changed_replay, changed_replay_after_recovery,
                      other_seq, after_recovery, after_result):
            with self.subTest(case=setup.__name__):
                broker, conn, path = self.fresh_broker()
                broker.handle_frame(conn, request_frame(1))
                frame = await setup(broker, conn)
                before = ledger_rows(path)
                with self.assertRaises(ProtocolViolation):
                    broker.handle_frame(conn, frame)
                self.assertEqual(ledger_rows(path), before)
                self.assertEqual(broker.get_state()["status"], "faulted")
                self.assertTrue(verify_ledger(path)["ok"])

    async def test_unbound_suspension_is_refused(self):
        self.broker.attach(self.conn)
        with self.assertRaises(Refused):
            self.broker.handle_frame(self.conn, suspended_frame(1))
        self.assertIsNone(self.broker.run_id)
        self.assertEqual(self.kinds(), [])


# ----- verifier: tampering with recomputed hashes -----

class LifecycleVerifyTests(BrokerTestCase):
    async def build(self, *, accept=True, modal=False, fault=False, second_recovery=False):
        self.start()
        if modal:
            self.broker.handle_frame(self.conn, modal_frame())
        if accept:
            await self.broker.act(1, "move", "N")
        self.broker.handle_frame(self.conn, recovery_frame(1))
        if fault:
            self.broker.handle_frame(self.conn, game_fault_frame(1))
            return read_rows(self.ledger_path)
        self.broker.handle_frame(self.conn, request_frame(2))
        await self.broker.act(2, "wait")
        self.broker.handle_frame(self.conn, result_frame(2, "wait"))
        self.broker.handle_frame(self.conn, request_frame(3))
        if second_recovery:
            self.broker.handle_frame(self.conn, recovery_frame(3, recovery_id=OTHER_RECOVERY_ID,
                                                               turn_before=140, loaded_turn=130))
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])
        return read_rows(self.ledger_path)

    def assertTamperRejected(self, rows, mutate, fragment=None):
        rows = copy.deepcopy(rows)
        mutate(rows)
        write_rows(self.ledger_path, rows)
        with self.assertRaises(VerifyError) as ctx:
            verify_ledger(self.ledger_path)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))

    def index_of(self, rows, kind, nth=0):
        return [i for i, row in enumerate(rows) if row["kind"] == kind][nth]

    async def test_recovery_body_tampering_is_rejected(self):
        rows = await self.build()
        r = self.index_of(rows, "recovery")

        def setter(key, value):
            return lambda rs: rs[r]["body"].__setitem__(key, value)

        def dropper(key):
            return lambda rs: rs[r]["body"].pop(key)

        cases = {
            "lost_turns": setter("lost_turns", 19),
            "loaded_turn": setter("loaded_turn", 90),
            "pairing": setter("reason", "save_reload"),
            "save_file": setter("save_file", "Primary"),
            "sha": setter("save_sha256", SAVE_SHA256.upper()),
            "frame sha": setter("frame_sha256", "z" * 64),
            "recovery id": setter("recovery_id", "not-a-uuid"),
            "game id": setter("game_id", ""),
            "request link": setter("request_hash", rows[1]["hash"]),
            "decision link": setter("decision_hash", rows[0]["hash"]),
            "decision null": setter("decision_hash", None),
            "extra": setter("observation", {}),
            "missing": dropper("frame_sha256"),
            "missing decision": dropper("decision_hash"),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate)

    async def test_unaccepted_recovery_must_have_null_decision_hash(self):
        rows = await self.build(accept=False)
        r = self.index_of(rows, "recovery")
        self.assertIsNone(rows[r]["body"]["decision_hash"])
        self.assertTamperRejected(rows, lambda rs: rs[r]["body"].__setitem__(
            "decision_hash", rs[0]["hash"]), "decision_hash")

    async def test_interruption_sequence_transitions_are_enforced(self):
        rows = await self.build(second_recovery=True)
        r = self.index_of(rows, "recovery")
        first_result = self.index_of(rows, "result")

        def delete_recovery(rs):
            del rs[r]

        def result_for_interrupted(rs):
            forged = copy.deepcopy(rs[first_result])
            forged["seq"] = 1
            forged["body"]["decision_hash"] = rs[1]["hash"]
            forged["body"]["action"] = "move"
            rs.insert(r + 1, forged)

        def duplicate_recovery_same_seq(rs):
            again = copy.deepcopy(rs[r])
            again["body"]["recovery_id"] = "11111111-2222-4333-8444-555555555555"
            rs.insert(r + 1, again)

        def reused_recovery_id(rs):
            last = self.index_of(rs, "recovery", 1)
            rs[last]["body"]["recovery_id"] = rs[r]["body"]["recovery_id"]

        def reused_recovery_id_other_spelling(rs):
            last = self.index_of(rs, "recovery", 1)
            rs[last]["body"]["recovery_id"] = rs[r]["body"]["recovery_id"].upper()

        def skip_seq(rs):
            nxt = r + 1
            rs[nxt]["seq"] = 3

        def recovery_after_result(rs):
            # Correctly linked to request/decision seq 2, but placed after result seq 2.
            request2 = self.index_of(rs, "request", 1)
            forged = copy.deepcopy(rs[r])
            forged["seq"] = 2
            forged["body"]["recovery_id"] = "11111111-2222-4333-8444-555555555555"
            forged["body"]["request_hash"] = rs[request2]["hash"]
            forged["body"]["decision_hash"] = rs[request2 + 1]["hash"]
            rs.insert(first_result + 1, forged)

        def recovery_seq_mismatch(rs):
            rs[r]["seq"] = 2

        cases = {"delete recovery": (delete_recovery, "expected result for seq 1"),
                 "result for interrupted seq": (result_for_interrupted, "expected request for seq 2"),
                 "second recovery for seq": (duplicate_recovery_same_seq, "only once"),
                 "reused recovery id": (reused_recovery_id, "reused"),
                 "reused recovery id other spelling": (reused_recovery_id_other_spelling, "reused"),
                 "seq gap after recovery": (skip_seq, "expected seq 2"),
                 "recovery after result": (recovery_after_result, "before its result"),
                 "recovery seq mismatch": (recovery_seq_mismatch, "not the current request seq")}
        for name, (mutate, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate, fragment)

    async def test_summary_counts_multiple_recoveries(self):
        await self.build(second_recovery=True)
        summary = verify_ledger(self.ledger_path, require_completed=1)
        self.assertEqual(summary["recoveries"], 2)
        self.assertEqual(summary["interrupted_decisions"], 1)
        self.assertEqual(summary["lost_turns"], 30)
        self.assertEqual(summary["recovering_seq"], 3)

    async def test_modal_rows_for_interrupted_seq_are_rejected(self):
        rows = await self.build(modal=True, accept=False)
        r = self.index_of(rows, "recovery")
        m = self.index_of(rows, "modal")

        def answer_after_recovery(rs):
            rs.insert(r + 1, {"index": 0, "kind": "modal_answer", "seq": 1, "run_id": RUN_ID,
                              "body": {"token": "popup-1", "answer_id": 1,
                                       "response": {"choice": "button:1"},
                                       "modal_hash": rs[m]["hash"]},
                              "prev_hash": "", "hash": ""})

        def modal_moved_after_recovery(rs):
            rs.insert(r, rs.pop(m))

        for name, mutate in {"answer": answer_after_recovery,
                             "modal": modal_moved_after_recovery}.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate, "interrupted")

    async def test_game_fault_is_terminal_and_strict(self):
        rows = await self.build(fault=True)
        f = self.index_of(rows, "game_fault")
        self.assertEqual(verify_ledger(self.ledger_path)["game_fault"]["seq"], 1)

        def append_after(rs):
            rs.append(copy.deepcopy(rs[0]))

        def duplicate_fault(rs):
            rs.append(copy.deepcopy(rs[f]))

        def setter(key, value):
            return lambda rs: rs[f]["body"].__setitem__(key, value)

        cases = {"row after fault": append_after,
                 "duplicate fault": duplicate_fault,
                 "decision null": setter("decision_hash", None),
                 "request link": setter("request_hash", rows[1]["hash"]),
                 "empty reason": setter("reason", ""),
                 "long reason": setter("reason", "x" * 1025),
                 "extra": setter("observation", {}),
                 "bad frame sha": setter("frame_sha256", "A" * 64),
                 "wrong seq": lambda rs: rs[f].__setitem__("seq", 2)}
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate)

    async def test_game_fault_before_first_request_is_rejected(self):
        rows = await self.build(fault=True)
        f = self.index_of(rows, "game_fault")
        self.assertTamperRejected(rows, lambda rs: rs.insert(0, rs.pop(f)))

    async def build_suspended(self, *, accept=True):
        self.start()
        if accept:
            await self.broker.act(1, "move", "N")
        self.broker.handle_frame(self.conn, suspended_frame(1))
        self.broker.handle_frame(self.conn, death_auto_frame())
        self.broker.handle_frame(self.conn, recovery_frame(1, reason="save_reload"))
        self.broker.handle_frame(self.conn, request_frame(2))
        await self.broker.act(2, "wait")
        self.broker.handle_frame(self.conn, result_frame(2, "wait"))
        self.broker.handle_frame(self.conn, request_frame(3))
        summary = verify_ledger(self.ledger_path, require_completed=1)
        self.assertEqual((summary["suspensions"], summary["recoveries"]), (1, 1))
        return read_rows(self.ledger_path)

    async def check_suspended_body_tampering(self, accept):
        rows = await self.build_suspended(accept=accept)
        s = self.index_of(rows, "suspended")
        self.assertEqual(rows[s]["body"]["decision_hash"], rows[1]["hash"] if accept else None)

        def setter(key, value):
            return lambda rs: rs[s]["body"].__setitem__(key, value)

        cases = {"reason": setter("reason", "menu"),
                 "frame sha": setter("frame_sha256", "Z" * 64),
                 "request link": setter("request_hash", rows[-1]["hash"]),
                 "decision link": setter("decision_hash", None if accept else rows[0]["hash"]),
                 "extra": setter("observation", {}),
                 "missing": lambda rs: rs[s]["body"].pop("request_hash"),
                 "wrong seq": lambda rs: rs[s].__setitem__("seq", 2)}
        for name, mutate in cases.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate)

    async def test_suspended_body_tampering_is_rejected(self):
        await self.check_suspended_body_tampering(accept=True)

    async def test_unaccepted_suspended_body_tampering_is_rejected(self):
        await self.check_suspended_body_tampering(accept=False)

    async def test_suspension_sequence_transitions_are_enforced(self):
        rows = await self.build_suspended()
        s = self.index_of(rows, "suspended")
        r = self.index_of(rows, "recovery")

        def delete_recovery(rs):
            del rs[r]

        def decision_after_suspension(rs):
            forged = copy.deepcopy(rs[1])
            rs.insert(s + 1, forged)

        def second_suspension(rs):
            rs.insert(s + 1, copy.deepcopy(rs[s]))

        def suspension_after_recovery(rs):
            rs.insert(r + 1, rs.pop(s))

        def suspension_after_result(rs):
            result = self.index_of(rs, "result")
            forged = copy.deepcopy(rs[s])
            forged["seq"] = 2
            forged["body"]["request_hash"] = rs[result - 2]["hash"]
            forged["body"]["decision_hash"] = rs[result - 1]["hash"]
            rs.insert(result + 1, forged)

        def suspension_after_fault(rs):
            fault = copy.deepcopy(rs[r])
            fault["kind"] = "game_fault"
            fault["body"] = {"reason": "x", "frame_sha256": rs[s]["body"]["frame_sha256"],
                             "request_hash": rs[0]["hash"], "decision_hash": rs[1]["hash"]}
            rs[r] = fault
            del rs[r + 1:]
            rs.append(copy.deepcopy(rs[s]))

        cases = {"delete recovery": (delete_recovery, "suspended"),
                 "decision after suspension": (decision_after_suspension, "suspended"),
                 "second suspension": (second_suspension, "suspended"),
                 "suspension after recovery": (suspension_after_recovery, None),
                 "suspension after result": (suspension_after_result, None),
                 "suspension after fault": (suspension_after_fault, "terminal")}
        for name, (mutate, fragment) in cases.items():
            with self.subTest(case=name):
                self.assertTamperRejected(rows, mutate, fragment)

    async def test_trailing_suspension_is_reported(self):
        self.start()
        self.broker.handle_frame(self.conn, suspended_frame(1))
        summary = verify_ledger(self.ledger_path)
        self.assertEqual((summary["suspended_seq"], summary["suspensions"]), (1, 1))
        self.assertIsNone(summary["pending"])


if __name__ == "__main__":
    unittest.main()
