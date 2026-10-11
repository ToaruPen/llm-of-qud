import json

from harness.overlay import OverlayFeed
from harness.verify import verify_ledger
from tests.test_broker import BrokerTestCase, FakeConn, ledger_rows
from tests.support import request_frame, result_frame


class ItemActionTests(BrokerTestCase):
    async def test_open_container_uses_current_kit_handle_and_records_completion(self):
        self.broker.attach(self.conn)
        request = json.loads(request_frame(1))
        request["observation"]["kit"] = [{"id": "i1", "name": "chest", "slot": None}]
        self.broker.handle_frame(self.conn, json.dumps(request))
        for item in ("p1", "i2"):
            self.assertEqual((await self.broker.act(1, "open", item=item))["status"], "invalid")
        self.assertTrue((await self.broker.act(1, "open", item="i1"))["ok"])
        sent = json.loads(self.conn.sent[-1])
        self.assertEqual((sent["action"], sent["item"], sent["budget"]), ("open", "i1", 1))
        self.broker.handle_frame(self.conn, result_frame(1, action="open", reason="dispatched"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["completed"], 1)
        self.assertEqual((await self.broker.act(2, "open", item="i1"))["status"], "invalid")

    async def test_equipment_action_uses_current_handle_and_preserves_result_cost(self):
        self.start_with_kit()
        self.assertFalse((await self.broker.act(1, "equip", item="i2"))["ok"])
        accepted = await self.broker.act(1, "equip", item="i1")
        self.assertTrue(accepted["ok"])
        sent = json.loads(self.conn.sent[-1])
        self.assertEqual((sent["action"], sent["item"], sent["budget"]), ("equip", "i1", 1))
        self.broker.handle_frame(self.conn, result_frame(1, action="equip", reason="dispatched"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["completed"], 1)
        self.assertFalse((await self.broker.act(2, "equip", item="i1"))["ok"])

    def start_with_kit(self):
        self.broker.attach(self.conn)
        frame = json.loads(request_frame(1))
        frame["observation"]["kit"] = [{"id": "i1", "name": "food", "slot": None}]
        self.request = json.dumps(frame)
        self.broker.handle_frame(self.conn, self.request)

    async def test_item_action_replay_and_ledger_keep_the_observed_handle(self):
        self.start_with_kit()
        result = await self.broker.act(1, "eat", item="i1")
        self.assertTrue(result["ok"])
        sent = self.conn.sent[-1]
        self.assertEqual(json.loads(sent)["item"], "i1")
        self.broker.detach(self.conn)
        self.conn = FakeConn()
        self.broker.attach(self.conn)
        self.assertEqual(self.broker.handle_frame(self.conn, self.request), sent)
        self.broker.handle_frame(self.conn, result_frame(1, action="eat"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["completed"], 1)
        decision = next(x for x in ledger_rows(self.ledger_path) if x["kind"] == "decision")
        self.assertEqual(decision["body"]["item"], "i1")
        # The previous handle must not address the new observation, which has no kit.
        self.assertEqual((await self.broker.act(2, "eat", item="i1"))["status"], "invalid")

    async def test_only_allowlisted_actions_and_current_handles_can_be_sent(self):
        self.start_with_kit()
        for args in [
            {"action": "eat"}, {"action": "eat", "item": "i2"},
            {"action": "drink", "item": 1}, {"action": "apply", "item": "i01"},
            {"action": "wait", "item": "i1"}, {"action": "Read", "item": "i1"},
            {"action": "eat", "item": "i1", "dir": "N"},
        ]:
            with self.subTest(args=args):
                self.assertEqual((await self.broker.act(1, **args))["status"], "invalid")
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertEqual(self.conn.sent, [])

    async def test_drink_and_apply_are_single_actions_and_overlay_keeps_item(self):
        self.start_with_kit()
        feed = OverlayFeed(self.broker, self.ledger)
        for seq, action in enumerate(("drink", "apply"), 1):
            with self.subTest(action=action):
                self.assertTrue((await self.broker.act(seq, action, item="i1", budget=20))["ok"])
                sent = json.loads(self.conn.sent[-1])
                self.assertEqual((sent["action"], sent["item"], sent["budget"]), (action, "i1", 1))
                self.assertEqual(feed.snapshot()["decision"]["item"], "i1")
                self.broker.handle_frame(self.conn, result_frame(seq, action=action))
                next_request = json.loads(self.request)
                next_request["seq"] = seq + 1
                self.broker.handle_frame(self.conn, json.dumps(next_request))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=2)["completed"], 2)
