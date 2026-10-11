import json
import unittest

from harness import wire
from tests.support import make_observation, request_frame, result_frame
from tests.test_broker import BrokerTestCase
from harness.verify import verify_ledger


class GoalsShapeTests(unittest.TestCase):
    def test_goals_accept_public_text_and_bound_truncation_without_requiring_old_writers(self):
        old = make_observation()
        wire.validate_observation(old)
        for goals in ({"text": "", "truncated": False},
                      {"text": "What's Eating the Watervine?\nFind the source.", "truncated": False},
                      {"text": "x" * 16384, "truncated": True}):
            wire.validate_observation({**old, "goals": goals})
        for goals in ([], {}, {"text": "x" * 16385, "truncated": True},
                      {"text": 1, "truncated": False}, {"text": "quest", "truncated": 0},
                      {"text": "quest", "truncated": False, "hiddenSteps": ["secret"]}):
            with self.subTest(goals=str(goals)[:80]), self.assertRaises(wire.WireError):
                wire.validate_observation({**old, "goals": goals})


class GoalsRoundTripTests(BrokerTestCase):
    async def test_goals_survive_request_result_and_ledger_validation(self):
        self.broker.attach(self.conn)
        goals = {"text": "Visible quest\nVisible step", "truncated": False}
        request = json.loads(request_frame(1))
        request["observation"]["goals"] = goals
        self.broker.handle_frame(self.conn, json.dumps(request))
        self.assertEqual(self.broker.get_state()["observation"]["goals"], goals)
        await self.broker.act(1, "wait")
        result = json.loads(result_frame(1, "wait"))
        result["observation"]["goals"] = goals
        self.broker.handle_frame(self.conn, json.dumps(result))
        self.assertTrue(verify_ledger(self.ledger_path, require_completed=1)["ok"])
