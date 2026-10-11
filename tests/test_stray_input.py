import tempfile
import unittest
from pathlib import Path

from harness import wire
from harness.verify import VerifyError, verify_ledger
from tests.support import make_telemetry
from tests.test_ledger_verify import build_ledger


class StrayInputTests(unittest.TestCase):
    def test_missing_sensor_is_unknown_and_complete_sensor_counts_are_reported(self):
        for request, result, expected in ((None, None, None),
                                          (0, None, None),
                                          (0, 0, 0),
                                          (2, 2, 2)):
            with self.subTest(request=request, result=result), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "ledger.jsonl"
                req = make_telemetry()
                res = make_telemetry()
                if request is not None:
                    req["stray_keys"] = request
                if result is not None:
                    res["stray_keys"] = result
                build_ledger(path, request_telemetry=req, result_telemetry=res)
                self.assertEqual(verify_ledger(path)["stray_keys"], expected)

    def test_stray_key_count_must_be_a_nonnegative_integer(self):
        for value in (-1, True, 0.5, "0"):
            with self.subTest(value=value), self.assertRaises(wire.WireError):
                wire.validate_telemetry({**make_telemetry(), "stray_keys": value})

    def test_a_measured_count_cannot_decrease(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            build_ledger(path, request_telemetry={**make_telemetry(), "stray_keys": 2},
                         result_telemetry={**make_telemetry(), "stray_keys": 1})
            with self.assertRaisesRegex(VerifyError, "stray_keys decreased"):
                verify_ledger(path)
