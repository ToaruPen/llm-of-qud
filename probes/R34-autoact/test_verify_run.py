"""Acceptance tests for run-scoped R3/R4 evidence in Player.log."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_run.py")


def event(kind, run_id="target", **fields):
    return {"kind": kind, "id": run_id, **fields}


def r4_events():
    rows = [event("armed", mode="r4", seconds=60, turns=500, focus="focused"),
            event("begin", mode="r4", focus="focused", seconds=60,
                  targetTurns=500, turn=100)]
    turn = 100
    for seq in range(1, 18):
        action = ("explore", "goto", "rest", "rest")[(seq - 1) % 4]
        turns = 20 if seq == 17 else 30
        rows.append(event("decision", seq=seq, action=action, turn=turn))
        rows.append(event("macro_result", seq=seq, action=action,
                          reason="RUN_BUDGET" if seq == 17 else "BUDGET",
                          turnStart=turn, turnEnd=turn + turns, turns=turns,
                          moves=3 if action == "goto" else 0))
        turn += turns
    rows.append(event("result", mode="r4", focus="focused", reason="COMPLETE",
                      elapsedMs=45000, turnStart=100, turnEnd=600, turns=500,
                      moves=50, ctas=520, decisions=17,
                      playerTurnEntries=0, endPlayerTurns=0, **{"pass": True}))
    return rows


def r3_events(run_id="target", focus="unfocused", moves=80):
    rows = [event("armed", run_id, mode="r3", seconds=10, turns=500, focus=focus),
            event("begin", run_id, mode="r3", focus=focus, seconds=10,
                  targetTurns=500, turn=100)]
    for second in range(1, 10):
        rows.append(event("heartbeat", run_id, elapsedMs=second * 1000,
                          moves=second * moves // 10, actualFocused=focus == "focused",
                          frame=1000 + 60 * second, frameDelta=60, heartbeatMs=1000,
                          playerTurnEntries=0, endPlayerTurns=0))
    rows.append(event("decision", run_id, seq=1, action="goto", turn=100))
    rows.append(event("macro_result", run_id, seq=1, action="goto", reason="RUN_BUDGET",
                      turnStart=100, turnEnd=200, turns=100, moves=moves))
    rows.append(event("result", run_id, mode="r3", focus=focus, reason="COMPLETE",
                      elapsedMs=10000, turnStart=100, turnEnd=200, turns=100,
                      moves=moves, ctas=150, decisions=1,
                      playerTurnEntries=0, endPlayerTurns=0, **{"pass": True}))
    return rows


class RunVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name) / "Player.log"

    def write(self, rows):
        self.log.write_text("\n".join("INFO - [R34] " + json.dumps(row) for row in rows) + "\n")

    def verify(self, run_id="target", *extra):
        return subprocess.run([sys.executable, str(SCRIPT), "--player-log", str(self.log),
                               "--run-id", run_id, *extra], text=True, capture_output=True)

    def test_r4_complete_500_turns_reports_distribution(self):
        self.write(r4_events())
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = json.loads(result.stdout)
        self.assertEqual(metrics["turns"], 500)
        self.assertEqual(metrics["decisions"], 17)
        self.assertEqual(metrics["action_counts"], {"explore": 5, "goto": 4, "rest": 8})
        self.assertEqual(len(metrics["turns_per_decision"]), 17)
        self.assertEqual(metrics["scope"], "runtime_log_only")
        self.assertTrue(metrics["external_input_unverified"])

    def test_r4_rejects_short_requested_target_even_if_result_claims_complete(self):
        rows = r4_events()
        rows[0]["turns"] = rows[1]["targetTurns"] = 499
        self.write(rows)
        self.assertIn("500", self.verify().stderr)

    def test_r4_rejects_missing_macro_result(self):
        rows = [row for row in r4_events() if not (row["kind"] == "macro_result" and row["seq"] == 7)]
        self.write(rows)
        self.assertIn("pair", self.verify().stderr)

    def test_r4_rejects_missing_rest_action(self):
        rows = r4_events()
        for row in rows:
            if row["kind"] in ("decision", "macro_result") and row["action"] == "rest":
                row["action"] = "goto"
        self.write(rows)
        self.assertIn("rest", self.verify().stderr)

    def test_r4_rejects_leaked_player_turn(self):
        rows = r4_events()
        rows[-1]["playerTurnEntries"] = 1
        self.write(rows)
        self.assertIn("PlayerTurn", self.verify().stderr)

    def test_r4_rejects_heartbeat_sensor_leak_even_if_result_claims_zero(self):
        rows = r4_events()
        rows.insert(3, event("heartbeat", elapsedMs=1000, frame=100, frameDelta=50,
                             heartbeatMs=1000, actualFocused=True,
                             playerTurnEntries=0, endPlayerTurns=1))
        self.write(rows)
        self.assertIn("PlayerTurn", self.verify().stderr)

    def test_r4_rejects_macro_result_without_reason(self):
        rows = r4_events()
        next(row for row in rows if row["kind"] == "macro_result")["reason"] = None
        self.write(rows)
        self.assertIn("reason", self.verify().stderr)

    def test_r4_rejects_unaccounted_turn_after_last_macro(self):
        rows = r4_events()
        rows[-1]["turnEnd"] = 601
        rows[-1]["turns"] = 501
        self.write(rows)
        self.assertIn("coverage", self.verify().stderr)

    def test_selected_run_ignores_failed_other_run(self):
        failed = [event("armed", "old", mode="r4", seconds=60, turns=500, focus="focused"),
                  event("game_error", "old", error="System.Exception: failed"),
                  event("result", "old", mode="r4", reason="EXCEPTION", **{"pass": False})]
        self.write(failed + r4_events())
        self.assertEqual(self.verify().returncode, 0)

    def test_r4_rejects_error_during_selected_run(self):
        rows = r4_events()
        rows.insert(3, event("game_error", error="System.Exception: broken"))
        self.write(rows)
        self.assertIn("error", self.verify().stderr)

    def test_r3_complete_short_unfocused_run(self):
        self.write(r3_events())
        result = self.verify("target", "--expected-focus", "unfocused")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["max_heartbeat_gap_ms"], 1000)

    def test_r3_rejects_early_completion(self):
        rows = r3_events()
        rows[-1]["elapsedMs"] = 9749
        self.write(rows)
        self.assertIn("duration", self.verify("target", "--expected-focus", "unfocused").stderr)

    def test_r3_rejects_stale_frame_and_blind_gap(self):
        rows = r3_events()
        rows[5]["frameDelta"] = 0
        self.write(rows)
        self.assertIn("frame", self.verify("target", "--expected-focus", "unfocused").stderr)
        rows[5]["frameDelta"] = 60
        rows[5]["heartbeatMs"] = 2500
        self.write(rows)
        self.assertIn("heartbeat gap", self.verify("target", "--expected-focus", "unfocused").stderr)

    def test_r3_rejects_long_move_stall_despite_fresh_ui_frames(self):
        rows = r3_events()
        for row in rows:
            if row["kind"] == "heartbeat" and 2000 <= row["elapsedMs"] <= 8000:
                row["moves"] = 8
        self.write(rows)
        self.assertIn("move stall", self.verify("target", "--expected-focus", "unfocused").stderr)

    def test_r3_rejects_actual_focus_mismatch(self):
        rows = r3_events()
        rows[4]["actualFocused"] = True
        self.write(rows)
        self.assertIn("focus", self.verify("target", "--expected-focus", "unfocused").stderr)

    def test_r3_baseline_requires_80_percent_move_rate(self):
        rows = r3_events() + r3_events("baseline", "focused", moves=100)
        self.write(rows)
        result = self.verify("target", "--expected-focus", "unfocused",
                             "--baseline-run-id", "baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["move_rate_ratio"], 0.8)
        rows = r3_events(moves=79) + r3_events("baseline", "focused", moves=100)
        self.write(rows)
        self.assertIn("move rate", self.verify("target", "--expected-focus", "unfocused",
                                                "--baseline-run-id", "baseline").stderr)

    def test_r3_rejects_sustained_late_slowdown_hidden_by_overall_average(self):
        rows = [row for row in r3_events(moves=1080) if row["kind"] != "heartbeat"]
        rows[0]["seconds"] = rows[1]["seconds"] = 120
        rows[-1]["elapsedMs"] = 120000
        beats = [event("heartbeat", elapsedMs=second * 1000,
                       moves=min(second, 60) * 12 + max(second - 60, 0) * 6,
                       actualFocused=False, frame=1000 + 60 * second,
                       frameDelta=60, heartbeatMs=1000,
                       playerTurnEntries=0, endPlayerTurns=0)
                 for second in range(1, 120)]
        rows[2:2] = beats
        self.write(rows + r3_events("baseline", "focused", moves=100))
        result = self.verify("target", "--expected-focus", "unfocused",
                             "--baseline-run-id", "baseline")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("movement window", result.stderr)

    def test_even_decision_count_reports_arithmetic_median(self):
        rows = r3_events()
        rows = [row for row in rows if row["kind"] not in ("decision", "macro_result")]
        result = rows.pop()
        rows.extend([
            event("decision", seq=1, action="goto", turn=100),
            event("macro_result", seq=1, action="goto", reason="ARRIVED",
                  turnStart=100, turnEnd=102, turns=2, moves=1),
            event("decision", seq=2, action="goto", turn=102),
            event("macro_result", seq=2, action="goto", reason="RUN_BUDGET",
                  turnStart=102, turnEnd=106, turns=4, moves=1),
        ])
        result.update(turnEnd=106, turns=6, decisions=2)
        rows.append(result)
        self.write(rows)
        actual = self.verify("target", "--expected-focus", "unfocused")
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(json.loads(actual.stdout)["turn_distribution"]["median"], 3.0)


if __name__ == "__main__":
    unittest.main()
