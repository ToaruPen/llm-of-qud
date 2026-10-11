import json
import unittest

from harness import wire
from harness.overlay import OverlayFeed
from harness.verify import verify_ledger
from tests.test_broker import BrokerTestCase, FakeConn, ledger_rows
from tests.support import RUN_ID, request_frame, result_frame


class MacroTests(BrokerTestCase):
    async def test_overlay_keeps_macro_destination_and_rest_mode(self):
        feed = OverlayFeed(self.broker, self.ledger)
        self.start()
        await self.broker.act(1, "goto", target={"x": 41, "y": 12}, budget=3)
        self.assertEqual(feed.snapshot()["decision"]["target"], {"x": 41, "y": 12})
        self.broker.handle_frame(self.conn, result_frame(1, action="goto"))
        self.broker.handle_frame(self.conn, request_frame(2))
        await self.broker.act(2, "rest", until="morning", budget=2)
        self.assertEqual(feed.snapshot()["decision"]["until"], "morning")

    async def test_goto_target_survives_reconnect_and_ledger_verification(self):
        self.start()
        target = {"x": 40, "y": 10}
        result = await self.broker.act(1, "goto", budget=12, target=target)
        self.assertTrue(result["ok"])
        frame = self.conn.sent[-1]
        self.assertEqual(json.loads(frame)["target"], target)
        self.broker.detach(self.conn)
        self.conn = FakeConn()
        self.broker.attach(self.conn)
        replay = self.broker.handle_frame(self.conn, request_frame(1))
        self.assertEqual(replay, frame)
        self.broker.handle_frame(self.conn, result_frame(1, action="goto"))
        self.broker.handle_frame(self.conn, request_frame(2))
        report = verify_ledger(self.ledger_path, require_completed=1, m1=True)
        self.assertTrue(report["m1"])
        decision = next(row for row in ledger_rows(self.ledger_path) if row["kind"] == "decision")
        self.assertEqual(decision["body"]["target"], target)

    async def test_rest_default_and_morning_are_bounded(self):
        self.start()
        result = await self.broker.act(1, "rest", budget=4)
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(self.conn.sent[-1])["until"], "healed")
        self.broker.handle_frame(self.conn, result_frame(1, action="rest"))
        self.broker.handle_frame(self.conn, request_frame(2))
        result = await self.broker.act(2, "rest", budget=7, until="morning")
        self.assertTrue(result["ok"])
        sent = json.loads(self.conn.sent[-1])
        self.assertEqual((sent["until"], sent["budget"]), ("morning", 7))
        self.broker.handle_frame(self.conn, result_frame(2, action="rest"))
        self.broker.handle_frame(self.conn, request_frame(3))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=2)["completed"], 2)

    async def test_invalid_macro_parameters_never_consume_seq(self):
        self.start()
        for args in [
            {"action": "goto"},
            {"action": "goto", "target": {"x": True, "y": 2}},
            {"action": "goto", "target": {"x": 80, "y": 2}},
            {"action": "goto", "target": {"x": 2, "y": 25}},
            {"action": "goto", "target": {"x": 2, "y": 2, "zone": "hidden"}},
            {"action": "goto", "target": {"x": 2, "y": 2}, "until": "morning"},
            {"action": "rest", "until": "forever"},
            {"action": "rest", "budget": 0},
            {"action": "rest", "budget": 41},
            {"action": "wait", "target": {"x": 2, "y": 2}},
            {"action": "explore", "until": "healed"},
        ]:
            with self.subTest(args=args):
                result = await self.broker.act(1, **args)
                self.assertEqual(result["status"], "invalid")
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertEqual(self.conn.sent, [])


class MacroWireTests(unittest.TestCase):
    def test_legacy_decision_bytes_remain_unchanged(self):
        self.assertEqual(wire.serialize_decision(RUN_ID, 1, "wait", None, 1),
                         '{"kind":"decision","run_id":"' + RUN_ID +
                         '","seq":1,"action":"wait","dir":null,"budget":1}')
