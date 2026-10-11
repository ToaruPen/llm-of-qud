"""Reject incomplete or faulty experiments when evidence spans game sessions."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from verify_run import verify


def r1_run(seconds, focus):
    yield {"kind": "r1_begin"}
    for second in range(1, seconds):
        yield {"kind": "r1_sample", "elapsedMs": second * 1000,
               "actualFocused": focus == "focused", "uiMs": 10}
    yield {"kind": "r1_result", "requestedSeconds": seconds, "focus": focus,
           "focusMismatches": 0, "pass": True, "actions": 1, "endPlayerTurns": 0,
           "elapsedMs": seconds * 1000, "turnStart": 0, "turnEnd": 1,
           "energyStart": 1000, "energyAfter": 50}


class MultiSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.first, self.second, self.server = [root / name for name in
                                                ("first.log", "second.log", "server.jsonl")]
        rounds = [{"kind": "r2_roundtrip", "seq": seq, "rttMs": .5}
                  for seq in range(1, 1001)]
        rounds.append({"kind": "r2_result", "pass": True, "replayed501": True})
        self.write_game(self.first, [{"kind": "r2_begin"},
                                    {"kind": "r2_reconnect", "seq": 501,
                                     "error": "WebSocketException"},
                                    *rounds, *r1_run(60, "focused"),
                                    *r1_run(600, "focused")])
        self.write_game(self.second, [*r1_run(60, "unfocused"),
                                     *r1_run(600, "unfocused")])
        observations = [{"kind": "observation", "seq": seq, "sha256": str(seq),
                         "connection": connection}
                        for connection, sequences in ((1, range(1, 502)), (2, range(501, 1001)))
                        for seq in sequences]
        observations.append({"kind": "server_result", "passed": True})
        self.server.write_text("\n".join(json.dumps(event) for event in observations))

    @staticmethod
    def write_game(path, events):
        path.write_text("Known startup DllNotFoundException\n" + "\n".join(
            "INFO - [R12] " + json.dumps(event, separators=(",", ":")) for event in events))

    def test_complete_matrix_across_restarts_ignores_only_pre_probe_errors(self):
        result = verify(self.first, self.server, additional_player_logs=[self.second])
        self.assertEqual(len(result["r1"]), 4)
        self.assertEqual(result["verified_p95_ms"], .5)

    def test_first_session_alone_does_not_establish_the_matrix(self):
        with self.assertRaisesRegex(AssertionError, "missing R1 matrix"):
            verify(self.first, self.server)

    def test_second_session_runtime_exception_is_not_lost(self):
        with self.second.open("a") as output:
            output.write("\nNullReferenceException during probe\n")
        with self.assertRaisesRegex(AssertionError, "Probe runtime exception"):
            verify(self.first, self.server, additional_player_logs=[self.second])

    def test_runtime_exception_during_r2_before_r1_is_rejected(self):
        self.first.write_text(self.first.read_text().replace(
            '{"kind":"r2_begin"}\n',
            '{"kind":"r2_begin"}\nNullReferenceException during R2\n'))
        with self.assertRaisesRegex(AssertionError, "runtime exception"):
            verify(self.first, self.server, additional_player_logs=[self.second])

    def test_ui_samples_bunched_after_a_gap_do_not_establish_coverage(self):
        lines = self.second.read_text().splitlines()
        for index, line in enumerate(lines):
            if '"kind":"r1_sample"' in line:
                event = json.loads(line.split("[R12] ", 1)[1])
                # Preserve sample count and fast UI responses, but create a 5s
                # blind interval followed by catch-up samples in the 60s run.
                if 10000 <= event["elapsedMs"] <= 19000:
                    event["elapsedMs"] = 15000 + (event["elapsedMs"] - 10000) // 2
                    lines[index] = "INFO - [R12] " + json.dumps(event)
            if '"kind":"r1_result"' in line:
                break
        self.second.write_text("\n".join(lines))
        with self.assertRaisesRegex(AssertionError, "sample coverage"):
            verify(self.first, self.server, additional_player_logs=[self.second])


if __name__ == "__main__":
    unittest.main()
