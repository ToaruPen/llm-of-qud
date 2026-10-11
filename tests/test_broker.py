import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from harness import wire
from harness.broker import Broker, ProtocolViolation, Refused
from harness.ledger import Ledger
from harness.verify import verify_ledger
from tests.support import (OTHER_RUN_ID, RUN_ID, contains_key, heartbeat_frame, make_telemetry,
                           request_frame, result_frame)


class FakeConn:
    def __init__(self, on_send=None):
        self.sent = []
        self.on_send = on_send
        self.closed = False

    async def send(self, text):
        if self.closed:
            raise ConnectionError("closed")
        if self.on_send:
            self.on_send(text)
        self.sent.append(text)


def ledger_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class BrokerTestCase(unittest.IsolatedAsyncioTestCase):
    act_wait_s = 0.05

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger_path = Path(self.tmp.name) / "ledger.jsonl"
        self.ledger = Ledger.create(self.ledger_path)
        self.broker = Broker(self.ledger, act_wait_s=self.act_wait_s)
        self.conn = FakeConn()

    async def asyncTearDown(self):
        self.broker.shutdown()
        await self.broker.drain()
        self.ledger.close()
        self.tmp.cleanup()

    def start(self, conn=None):
        conn = conn or self.conn
        self.broker.attach(conn)
        self.assertIsNone(self.broker.handle_frame(conn, request_frame(1)))
        return conn

    def kinds(self):
        return [(row["kind"], row["seq"]) for row in ledger_rows(self.ledger_path)]


class StateTests(BrokerTestCase):
    async def test_not_ready_before_any_request(self):
        state = self.broker.get_state()
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "not_ready")
        result = await self.broker.act(1, "wait")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(self.kinds(), [])

    async def test_heartbeat_before_request_does_not_bind(self):
        self.broker.attach(self.conn)
        self.assertIsNone(self.broker.handle_frame(self.conn, heartbeat_frame(0)))
        self.assertEqual(self.broker.get_state()["status"], "not_ready")
        self.assertIsNone(self.broker.run_id)

    async def test_get_state_exposes_observation_without_telemetry(self):
        self.start()
        state = self.broker.get_state()
        self.assertEqual(state["ok"], True)
        self.assertEqual(state["seq"], 1)
        self.assertEqual(len(state["observation"]["map"]), 25)
        self.assertFalse(contains_key(state, "telemetry"))
        self.assertFalse(contains_key(state, "game_queue"))
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertEqual(self.broker.get_state(), state, "get_state must not change state")
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_disconnected_status(self):
        self.start()
        self.broker.detach(self.conn)
        state = self.broker.get_state()
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "disconnected")
        result = await self.broker.act(1, "wait")
        self.assertFalse(result["ok"])
        self.assertEqual(self.kinds(), [("request", 1)])


class ActTests(BrokerTestCase):
    async def test_decision_is_in_ledger_before_it_is_sent(self):
        seen_rows = []
        conn = FakeConn(on_send=lambda text: seen_rows.append(ledger_rows(self.ledger_path)))
        self.start(conn)
        result = await self.broker.act(1, "move", "N")
        self.assertEqual(result, {"ok": True, "pending": True, "op_id": 1})
        self.assertEqual(conn.sent, [wire.serialize_decision(RUN_ID, 1, "move", "N", 1)])
        rows = seen_rows[0]
        self.assertEqual([r["kind"] for r in rows], ["request", "decision"])
        self.assertEqual(rows[1]["body"]["request_hash"], rows[0]["hash"])
        self.assertEqual(rows[1]["body"]["budget"], 1)

    async def test_act_accepts_exactly_once(self):
        self.start()
        first = await self.broker.act(1, "explore", None, 12)
        second = await self.broker.act(1, "wait")
        self.assertTrue(first["pending"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["status"], "already_accepted")
        self.assertEqual(len(self.conn.sent), 1)
        self.assertEqual(json.loads(self.conn.sent[0])["budget"], 12)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        state = self.broker.get_state()
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["op_id"], 1)

    async def test_stale_and_invalid_act_are_rejected_without_side_effects(self):
        self.start()
        cases = [
            ((2, "wait"), "stale_seq"),
            ((0, "wait"), "stale_seq"),
            ((True, "wait"), "invalid"),
            ((1, "wait", "N"), "invalid"),
            ((1, "move", None), "invalid"),
            ((1, "attack", "U"), "invalid"),
            ((1, "explore", None, 41), "invalid"),
            ((1, "wish"), "invalid"),
        ]
        for args, status in cases:
            with self.subTest(args=args):
                result = await self.broker.act(*args)
                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], status)
                self.assertIn("reason", result)
        self.assertEqual(self.conn.sent, [])
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertTrue(self.broker.get_state()["ok"])

    async def test_result_is_returned_without_telemetry_and_advances(self):
        self.start()
        task = asyncio.create_task(self.broker.act(1, "move", "E"))
        await asyncio.sleep(0)
        self.assertIsNone(self.broker.handle_frame(self.conn, result_frame(1, "move", px=41)))
        self.assertIsNone(self.broker.handle_frame(self.conn, request_frame(2, px=41)))
        result = await asyncio.wait_for(task, 5)
        self.assertTrue(result["ok"])
        self.assertTrue(result["completed"])
        self.assertEqual(result["op_id"], 1)
        self.assertEqual(result["next_seq"], 2)
        self.assertEqual(result["result"]["observation"]["vitals"]["x"], 41)
        self.assertTrue(result["result"]["executed"])
        self.assertFalse(contains_key(result, "telemetry"))
        self.assertEqual(self.broker.get_state()["seq"], 2)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("result", 1), ("request", 2)])
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1, m1=True)["m1_seq"], 1)
        stale = await self.broker.act(1, "wait")
        self.assertEqual(stale["status"], "stale_seq")

    async def test_wait_for_turn_returns_result_and_validates_arguments(self):
        self.start()
        await self.broker.act(1, "wait")
        for bad in (-1, 46, float("nan"), float("inf")):
            with self.subTest(timeout=bad):
                self.assertFalse((await self.broker.wait_for_turn(1, bad))["ok"])
        unknown = await self.broker.wait_for_turn(7, 0.01)
        self.assertFalse(unknown["ok"])
        pending = await self.broker.wait_for_turn(1, 0.01)
        self.assertEqual(pending, {"ok": True, "pending": True, "op_id": 1})
        waiter = asyncio.create_task(self.broker.wait_for_turn(1, 5))
        await asyncio.sleep(0)
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, request_frame(2))
        result = await asyncio.wait_for(waiter, 5)
        self.assertTrue(result["completed"])
        self.assertEqual(result["next_seq"], 2)
        again = await self.broker.wait_for_turn(1, 0)
        self.assertTrue(again["completed"])
        self.assertFalse(contains_key(again, "telemetry"))

    async def test_ledger_failure_faults_and_sends_nothing(self):
        self.start()

        def broken_append(*args, **kwargs):
            raise OSError("disk full")

        self.ledger.append = broken_append
        result = await self.broker.act(1, "wait")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "faulted")
        self.assertEqual(self.conn.sent, [])
        self.assertEqual(self.broker.get_state()["status"], "faulted")


class CancellationTests(BrokerTestCase):
    act_wait_s = 30

    async def test_accepted_operation_survives_tool_cancellation(self):
        self.start()
        task = asyncio.create_task(self.broker.act(1, "explore", None, 20))
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.broker.drain()
        self.assertEqual(len(self.conn.sent), 1, "decision must be sent exactly once")
        self.assertEqual(self.broker.get_state()["status"], "pending")
        retry = await asyncio.wait_for(self.broker.act(1, "explore", None, 20), 5)
        self.assertEqual(retry["status"], "already_accepted")
        self.assertEqual(len(self.conn.sent), 1, "no automatic retry")
        self.broker.handle_frame(self.conn, result_frame(1, "explore", turns_elapsed=7, steps=7))
        self.broker.handle_frame(self.conn, request_frame(2))
        result = await asyncio.wait_for(self.broker.wait_for_turn(1, 5), 5)
        self.assertEqual(result["result"]["steps"], 7)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("result", 1), ("request", 2)])

    async def test_fault_wakes_waiters_immediately(self):
        self.start()
        task = asyncio.create_task(self.broker.act(1, "wait"))
        await asyncio.sleep(0)
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, result_frame(1, "attack"))
        result = await asyncio.wait_for(task, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "faulted")

    async def test_shutdown_wakes_waiters_immediately(self):
        self.start()
        task = asyncio.create_task(self.broker.act(1, "wait"))
        await asyncio.sleep(0)
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        self.broker.shutdown()
        result = await asyncio.wait_for(task, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "shutdown")


class ReplayTests(BrokerTestCase):
    async def test_identical_request_replay_after_reconnect_resends_cached_decision(self):
        self.start()
        await self.broker.act(1, "attack", "NE")
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        reply = self.broker.handle_frame(conn2, request_frame(1))
        self.assertEqual(reply, self.conn.sent[0])
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])
        self.assertEqual(self.broker.handle_frame(conn2, request_frame(1)), self.conn.sent[0],
                         "every identical replay gets the cached decision (no silent stall)")
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1)])

    async def test_identical_replay_before_decision_is_ignored(self):
        self.start()
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        self.assertIsNone(self.broker.handle_frame(conn2, request_frame(1)))
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertTrue(self.broker.get_state()["ok"])

    async def test_conflicting_replay_faults(self):
        self.start()
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, request_frame(1, hp=9))
        self.assertEqual(self.broker.get_state()["status"], "faulted")
        self.assertFalse((await self.broker.act(1, "wait"))["ok"])
        self.assertEqual(self.kinds(), [("request", 1)])
        self.broker.detach(self.conn)
        with self.assertRaises(Refused):
            self.broker.attach(FakeConn())

    async def test_replay_is_compared_on_raw_bytes_not_parsed_json(self):
        self.start()
        same_content = json.dumps(json.loads(request_frame(1)), ensure_ascii=False,
                                  separators=(",", ":"))
        self.assertNotEqual(same_content, request_frame(1))
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, same_content)
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_duplicate_identical_result_is_not_recorded_twice(self):
        self.start()
        await self.broker.act(1, "wait")
        frame = result_frame(1, "wait")
        self.broker.handle_frame(self.conn, frame)
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        self.assertIsNone(self.broker.handle_frame(conn2, frame))
        self.broker.handle_frame(conn2, request_frame(2))
        self.assertIsNone(self.broker.handle_frame(conn2, frame), "late duplicate of last result")
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("result", 1), ("request", 2)])

    async def test_conflicting_result_faults(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, result_frame(1, "wait", executed=False))
        self.assertEqual(self.kinds(), [("request", 1), ("decision", 1), ("result", 1)])

    async def test_result_without_decision_faults(self):
        self.start()
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_next_request_before_result_faults(self):
        self.start()
        await self.broker.act(1, "wait")
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, request_frame(2))

    async def test_old_seq_never_reexecuted(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.broker.detach(self.conn)
        conn2 = FakeConn()
        self.broker.attach(conn2)
        self.assertIsNone(self.broker.handle_frame(conn2, request_frame(2)))
        await self.broker.drain()
        self.assertEqual(conn2.sent, [], "no stale decision may be sent")
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(conn2, request_frame(1))
        self.assertEqual(conn2.sent, [])

    async def test_request_seq_gap_faults(self):
        self.start()
        await self.broker.act(1, "wait")
        self.broker.handle_frame(self.conn, result_frame(1, "wait"))
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, request_frame(3))

    async def test_result_action_mismatch_faults(self):
        self.start()
        await self.broker.act(1, "move", "S")
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, result_frame(1, "wait"))


class ConnectionPolicyTests(BrokerTestCase):
    async def test_second_active_socket_is_refused(self):
        self.start()
        with self.assertRaises(Refused):
            self.broker.attach(FakeConn())
        self.assertTrue(self.broker.get_state()["ok"])

    async def test_foreign_run_is_refused_without_faulting(self):
        self.start()
        self.broker.detach(self.conn)
        intruder = FakeConn()
        self.broker.attach(intruder)
        with self.assertRaises(Refused):
            self.broker.handle_frame(intruder, request_frame(1, run_id=OTHER_RUN_ID))
        self.broker.detach(intruder)
        self.assertEqual(self.broker.get_state()["status"], "disconnected")
        self.broker.attach(self.conn)
        self.broker.handle_frame(self.conn, heartbeat_frame(1))
        self.assertTrue(self.broker.get_state()["ok"])
        self.assertEqual(self.kinds(), [("request", 1)])

    async def test_decision_is_never_sent_to_an_unverified_connection(self):
        self.start()
        self.broker.detach(self.conn)
        stranger = FakeConn()
        self.broker.attach(stranger)
        self.assertEqual(self.broker.get_state()["status"], "disconnected")
        result = await self.broker.act(1, "wait")
        self.assertEqual(result["status"], "disconnected")
        await self.broker.drain()
        self.assertEqual(stranger.sent, [])
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertIsNone(self.broker.handle_frame(stranger, request_frame(1)))
        self.assertTrue((await self.broker.act(1, "wait"))["ok"])
        self.assertEqual(len(stranger.sent), 1)

    async def test_first_request_must_be_seq_one(self):
        self.broker.attach(self.conn)
        with self.assertRaises(Refused):
            self.broker.handle_frame(self.conn, request_frame(5))
        self.assertIsNone(self.broker.run_id)
        self.assertEqual(self.kinds(), [])

    async def test_malformed_first_frame_refuses_but_bound_connection_faults(self):
        self.broker.attach(self.conn)
        with self.assertRaises(Refused):
            self.broker.handle_frame(self.conn, "{garbage")
        self.broker.detach(self.conn)
        self.start(FakeConn())
        conn = self.broker.conn
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(conn, "{garbage")
        self.assertEqual(self.broker.get_state()["status"], "faulted")

    async def test_binary_frame_on_bound_connection_faults(self):
        self.start()
        with self.assertRaises(ProtocolViolation):
            self.broker.handle_frame(self.conn, request_frame(1).encode())

    async def test_telemetry_is_retained_in_ledger(self):
        telemetry = make_telemetry(cta=1)
        telemetry["game_queue"].append({"task_id": "LookedAt123", "type": "Qud.UI.BaseLineWithTooltip",
                                        "method": "<Update>b__4", "classification": "ui_task"})
        telemetry["ui_tasks"] = 1
        self.broker.attach(self.conn)
        self.broker.handle_frame(self.conn, request_frame(1, telemetry=telemetry))
        row = ledger_rows(self.ledger_path)[0]
        self.assertEqual(row["body"]["telemetry"], telemetry)
        self.assertFalse(contains_key(self.broker.get_state(), "telemetry"))


if __name__ == "__main__":
    unittest.main()
