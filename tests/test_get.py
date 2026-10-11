import copy
import json
import unittest

from harness import wire
from harness.verify import verify_ledger
from tests.test_broker import BrokerTestCase, FakeConn
from tests.support import request_frame, result_frame


def ground_request(seq=1):
    frame = json.loads(request_frame(seq))
    frame["observation"]["ground"] = [
        {"id": "p1", "name": "corpse", "x": 11, "y": 10},
        {"id": "p2", "name": "scrap", "x": 11, "y": 10},
    ]
    return frame


class GetTests(BrokerTestCase):
    async def test_selected_ground_item_replays_once_and_old_handle_is_rejected(self):
        self.broker.attach(self.conn)
        request = json.dumps(ground_request())
        self.broker.handle_frame(self.conn, request)
        for item in (None, "i1", "p3", "p01"):
            self.assertEqual((await self.broker.act(1, "get", item=item))["status"], "invalid")
        self.assertTrue((await self.broker.act(1, "get", item="p2"))["ok"])
        sent = self.conn.sent[-1]
        self.assertEqual((json.loads(sent)["item"], json.loads(sent)["budget"]), ("p2", 1))
        self.broker.detach(self.conn)
        self.conn = FakeConn()
        self.broker.attach(self.conn)
        self.assertEqual(self.broker.handle_frame(self.conn, request), sent)
        self.broker.handle_frame(self.conn, result_frame(1, action="get"))
        self.broker.handle_frame(self.conn, request_frame(2))
        self.assertEqual((await self.broker.act(2, "get", item="p2"))["status"], "invalid")
        self.assertEqual(verify_ledger(self.ledger_path, require_completed=1)["completed"], 1)


class GroundObservationTests(unittest.TestCase):
    def test_ground_shape_is_bounded_and_old_observations_remain_valid(self):
        wire.validate_observation(json.loads(request_frame(1))["observation"])
        observation = ground_request()["observation"]
        wire.validate_observation(observation)
        for changes in ({"id": "i1"}, {"id": "p01"}, {"x": 80}, {"y": -1},
                        {"x": True}, {"blueprint": "hidden"}):
            invalid = copy.deepcopy(observation)
            invalid["ground"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(wire.WireError):
                wire.validate_observation(invalid)
        for items in ([observation["ground"][0]] * 2, observation["ground"] * 33):
            invalid = {**observation, "ground": items}
            with self.assertRaises(wire.WireError):
                wire.validate_observation(invalid)
