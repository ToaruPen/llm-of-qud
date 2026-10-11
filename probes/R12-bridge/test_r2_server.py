import json
import unittest

from r2_server import ReplayOracle


def observation(seq, value="日本語🌵"):
    return json.dumps({"kind": "observation", "seq": seq, "observation": {"text": value}})


class ReplayTests(unittest.TestCase):
    def test_disconnect_requires_same_pending_request_before_advancing(self):
        oracle = ReplayOracle(count=3, drop_seq=2)
        self.assertEqual(oracle.accept(observation(1))["seq"], 1)
        self.assertIsNone(oracle.accept(observation(2)))
        with self.assertRaises(ValueError):
            oracle.accept(observation(3))
        with self.assertRaises(ValueError):
            oracle.accept(observation(2, "changed"))
        self.assertEqual(oracle.accept(observation(2))["seq"], 2)
        self.assertTrue(oracle.replayed)
        self.assertEqual(oracle.accept(observation(3))["seq"], 3)
        self.assertTrue(oracle.complete)

    def test_duplicate_decision_request_is_not_counted_twice(self):
        oracle = ReplayOracle(count=3, drop_seq=2)
        oracle.accept(observation(1))
        with self.assertRaises(ValueError):
            oracle.accept(observation(1))
        self.assertEqual(oracle.completed, 1)

    def test_wrong_envelope_is_rejected(self):
        oracle = ReplayOracle(count=3, drop_seq=2)
        for raw in ['{}', 'null', '{"kind":"decision","seq":1}', '{"kind":"observation","seq":true,"observation":{}}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                oracle.accept(raw)


if __name__ == "__main__":
    unittest.main()
