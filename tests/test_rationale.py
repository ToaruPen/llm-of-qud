import json

from harness.overlay import OverlayFeed
from harness.verify import VerifyError, verify_ledger
from tests.test_broker import BrokerTestCase
from tests.test_ledger_verify import read_rows, write_rows
from tests.support import request_frame, result_frame


class RationaleTests(BrokerTestCase):
    async def test_rationale_is_ledger_metadata_and_survives_result_in_overlay(self):
        self.start()
        feed = OverlayFeed(self.broker, self.ledger)
        reason = "HPを回復するため休む。 <script>game text</script>"
        self.assertTrue((await self.broker.act(1, "rest", rationale=reason))["ok"])
        self.assertNotIn("rationale", json.loads(self.conn.sent[-1]))
        self.assertEqual(read_rows(self.ledger_path)[-1]["body"]["rationale"], reason)
        self.broker.handle_frame(self.conn, result_frame(1, action="rest"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual(feed.snapshot()["decision"]["rationale"], reason)
        self.assertTrue(verify_ledger(self.ledger_path)["ok"])
        rows = read_rows(self.ledger_path)
        rows[1]["body"]["rationale"] = 42
        write_rows(self.ledger_path, rows)
        with self.assertRaises(VerifyError):
            verify_ledger(self.ledger_path)

    async def test_invalid_rationale_cannot_consume_a_seq(self):
        self.start()
        for reason in (12, True, "", " " * 2, "x" * 2001):
            with self.subTest(reason=str(reason)[:10]):
                self.assertEqual((await self.broker.act(1, "wait", rationale=reason))["status"], "invalid")
        self.assertEqual(self.kinds(), [("request", 1)])
        self.assertTrue((await self.broker.act(1, "wait"))["ok"])
        self.assertNotIn("rationale", read_rows(self.ledger_path)[-1]["body"])
