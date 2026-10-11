import json

from harness.verify import verify_ledger
from tests.test_broker import BrokerTestCase
from tests.support import request_frame, result_frame


class TalkTests(BrokerTestCase):
    async def test_talk_requires_adjacent_direction_and_sends_one_decision(self):
        self.start()
        for direction in (None, "U", "D", "", "CmdTalk"):
            self.assertEqual((await self.broker.act(1, "talk", dir=direction))["status"], "invalid")
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertTrue((await self.broker.act(1, "talk", dir="NE"))["ok"])
        frame = json.loads(self.conn.sent[-1])
        self.assertEqual((frame["action"], frame["dir"], frame["budget"]), ("talk", "NE", 1))
        self.assertEqual((await self.broker.act(1, "talk", dir="NE"))["status"], "already_accepted")
        self.broker.handle_frame(self.conn, result_frame(1, action="talk"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["completed"], 1)
