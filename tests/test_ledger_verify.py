import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness import wire
from harness.ledger import GENESIS_HASH, Ledger, canonical_bytes, row_hash
from harness.verify import VerifyError, verify_ledger
from tests.support import OTHER_RUN_ID, RUN_ID, make_telemetry, request_frame, result_frame

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def build_ledger(path, completed=1, trailing="request", action="wait", dir=None, budget=1,
                 executed=True, result_telemetry=None, request_telemetry=None):
    """Write a ledger the same way the broker does: request, decision, result per seq."""
    ledger = Ledger.create(path)
    seq = 1
    try:
        for _ in range(completed):
            frame = request_frame(seq, telemetry=request_telemetry)
            request_row = ledger.append("request", seq, RUN_ID,
                                        wire.request_body(wire.parse_game_frame(frame), frame))
            decision_row = ledger.append("decision", seq, RUN_ID,
                                         wire.decision_body(request_row["hash"], action, dir, budget))
            frame = result_frame(seq, action, executed=executed, telemetry=result_telemetry)
            ledger.append("result", seq, RUN_ID,
                          wire.result_body(wire.parse_game_frame(frame), frame, decision_row["hash"]))
            seq += 1
        if trailing in ("request", "decision"):
            frame = request_frame(seq, telemetry=request_telemetry)
            request_row = ledger.append("request", seq, RUN_ID,
                                        wire.request_body(wire.parse_game_frame(frame), frame))
            if trailing == "decision":
                ledger.append("decision", seq, RUN_ID,
                              wire.decision_body(request_row["hash"], "explore", None, 20))
    finally:
        ledger.close()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def write_rows(path, rows, rehash=True, reindex=True):
    """Rewrite a ledger; with rehash=True this is what a careful forger would do."""
    prev = GENESIS_HASH
    lines = []
    for index, row in enumerate(rows):
        row = dict(row)
        if reindex:
            row["index"] = index
        if rehash:
            row["prev_hash"] = prev
            row.pop("hash", None)
            row["hash"] = row_hash(row)
        prev = row["hash"]
        lines.append(canonical_bytes(row) + b"\n")
    Path(path).write_bytes(b"".join(lines))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_exclusive_creation_with_mode_0600(self):
        ledger = Ledger.create(self.path)
        ledger.close()
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            Ledger.create(self.path)

    def test_rows_are_canonical_and_chained(self):
        build_ledger(self.path, completed=1, trailing="request")
        raw_lines = self.path.read_bytes().splitlines()
        rows = [json.loads(line) for line in raw_lines]
        self.assertEqual([r["kind"] for r in rows], ["request", "decision", "result", "request"])
        self.assertEqual(rows[0]["prev_hash"], GENESIS_HASH)
        for index, (line, row) in enumerate(zip(raw_lines, rows)):
            self.assertEqual(set(row), {"index", "kind", "seq", "run_id", "body", "prev_hash", "hash"})
            self.assertEqual(row["index"], index)
            self.assertEqual(line, canonical_bytes(row))
            unhashed = {k: v for k, v in row.items() if k != "hash"}
            self.assertEqual(row["hash"], row_hash(unhashed))
            if index:
                self.assertEqual(row["prev_hash"], rows[index - 1]["hash"])
        self.assertEqual(rows[1]["body"]["request_hash"], rows[0]["hash"])
        self.assertEqual(rows[2]["body"]["decision_hash"], rows[1]["hash"])
        self.assertNotIn("frame", rows[0]["body"])
        self.assertEqual(rows[0]["body"]["telemetry"]["end_player_turns"], 0)

    def test_append_after_close_fails(self):
        ledger = Ledger.create(self.path)
        ledger.close()
        with self.assertRaises(ValueError):
            ledger.append("request", 1, RUN_ID, {})


class VerifyChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def assertRejected(self, fragment=None):
        with self.assertRaises(VerifyError) as ctx:
            verify_ledger(self.path)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))
        return ctx.exception

    def test_trailing_pending_request_is_valid(self):
        build_ledger(self.path, completed=2, trailing="request")
        summary = verify_ledger(self.path, require_completed=2)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["pending"], "request")
        self.assertEqual(summary["pending_seq"], 3)
        self.assertIsNone(summary["m1"])
        self.assertEqual(summary["rows"], 7)
        self.assertEqual(summary["head_hash"], read_rows(self.path)[-1]["hash"])

    def test_trailing_pending_decision_is_reported(self):
        build_ledger(self.path, completed=1, trailing="decision")
        summary = verify_ledger(self.path)
        self.assertEqual(summary["pending"], "decision")
        self.assertEqual(summary["pending_seq"], 2)

    def test_ledger_ending_after_result_has_no_pending(self):
        build_ledger(self.path, completed=1, trailing=None)
        summary = verify_ledger(self.path)
        self.assertIsNone(summary["pending"])
        self.assertEqual(summary["completed"], 1)

    def test_require_completed(self):
        build_ledger(self.path, completed=0, trailing="request")
        self.assertEqual(verify_ledger(self.path)["completed"], 0)
        with self.assertRaises(VerifyError):
            verify_ledger(self.path, require_completed=1)

    def test_body_tamper_is_detected(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[0]["body"]["observation"]["vitals"]["hp"] = 99
        write_rows(self.path, rows, rehash=False)
        self.assertRejected("hash")

    def test_broken_prev_hash_is_detected(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[2]["prev_hash"] = "f" * 64
        rows[2].pop("hash")
        rows[2]["hash"] = row_hash(rows[2])
        write_rows(self.path, rows, rehash=False)
        self.assertRejected("prev_hash")

    def test_reordered_rows_fail_even_when_rehashed(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[1], rows[2] = rows[2], rows[1]
        write_rows(self.path, rows)
        self.assertRejected()

    def test_decision_must_link_to_request_hash(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[1]["body"]["request_hash"] = "a" * 64
        write_rows(self.path, rows)
        self.assertRejected("request_hash")

    def test_result_must_link_to_decision_hash(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[2]["body"]["decision_hash"] = rows[0]["hash"]
        write_rows(self.path, rows)
        self.assertRejected("decision_hash")

    def test_missing_decision_is_detected(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        del rows[1]
        write_rows(self.path, rows)
        self.assertRejected()

    def test_seq_gap_is_detected(self):
        build_ledger(self.path, completed=1, trailing="request")
        rows = read_rows(self.path)
        rows[3]["seq"] = 3
        write_rows(self.path, rows)
        self.assertRejected("seq")

    def test_first_seq_must_be_one(self):
        build_ledger(self.path, completed=0, trailing="request")
        rows = read_rows(self.path)
        rows[0]["seq"] = 2
        write_rows(self.path, rows)
        self.assertRejected("seq")

    def test_run_id_change_is_detected(self):
        build_ledger(self.path, completed=1, trailing="request")
        rows = read_rows(self.path)
        rows[3]["run_id"] = OTHER_RUN_ID
        write_rows(self.path, rows)
        self.assertRejected("run_id")

    def test_unknown_kind_and_extra_fields_are_rejected(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows.append(dict(rows[0], kind="note"))
        write_rows(self.path, rows)
        self.assertRejected("kind")
        build_path = Path(self.tmp.name) / "extra.jsonl"
        build_ledger(build_path, completed=1)
        rows = read_rows(build_path)
        rows[0]["note"] = "x"
        write_rows(self.path, rows)
        self.assertRejected("fields")

    def test_truncated_last_line_is_rejected(self):
        build_ledger(self.path, completed=1, trailing="request")
        data = self.path.read_bytes()
        self.path.write_bytes(data[:-15])
        self.assertRejected()

    def test_direct_action_decision_with_explore_budget_is_rejected(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[1]["body"]["budget"] = 20
        write_rows(self.path, rows)
        self.assertRejected("budget")

    def test_result_action_must_match_decision(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[2]["body"]["action"] = "explore"
        write_rows(self.path, rows)
        self.assertRejected("action")

    def test_observation_shape_is_checked(self):
        build_ledger(self.path, completed=1)
        rows = read_rows(self.path)
        rows[0]["body"]["observation"]["threats"][0]["hp"] = 12
        write_rows(self.path, rows)
        self.assertRejected()


class VerifyM1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_m1_passes_with_executed_action_zero_counters_and_next_request(self):
        build_ledger(self.path, completed=1, trailing="request", action="move", dir="N")
        summary = verify_ledger(self.path, m1=True)
        self.assertTrue(summary["m1"])
        self.assertEqual(summary["m1_seq"], 1)

    def test_m1_requires_executed_action(self):
        build_ledger(self.path, completed=1, trailing="request", executed=False)
        self.assertTrue(verify_ledger(self.path)["ok"])
        with self.assertRaises(VerifyError):
            verify_ledger(self.path, m1=True)

    def test_m1_requires_zero_end_player_turns_in_result(self):
        build_ledger(self.path, completed=1, trailing="request",
                     result_telemetry=make_telemetry(cta=2, end_player_turns=1))
        with self.assertRaises(VerifyError):
            verify_ledger(self.path, m1=True)

    def test_m1_requires_zero_player_turn_entries_everywhere(self):
        build_ledger(self.path, completed=1, trailing="request",
                     request_telemetry=make_telemetry(cta=2, player_turn_entries=1))
        with self.assertRaises(VerifyError):
            verify_ledger(self.path, m1=True)

    def test_m1_requires_next_request(self):
        build_ledger(self.path, completed=1, trailing=None)
        with self.assertRaises(VerifyError):
            verify_ledger(self.path, m1=True)


class VerifyCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([PYTHON, "-m", "harness.verify", str(self.path), *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)

    def test_cli_success_does_not_claim_m1(self):
        build_ledger(self.path, completed=1, trailing="request")
        proc = self.run_cli("--require-completed", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = json.loads(proc.stdout)
        self.assertTrue(summary["ok"])
        self.assertIsNone(summary["m1"])

    def test_cli_failure_exit_code(self):
        build_ledger(self.path, completed=1, trailing=None, executed=False)
        proc = self.run_cli("--m1")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["ok"])
        proc = self.run_cli("--require-completed", "2")
        self.assertEqual(proc.returncode, 1)

    def test_verifier_does_not_import_server_dependencies(self):
        code = ("import sys, harness.verify; "
                "print(sorted(m for m in ('mcp','uvicorn','websockets','starlette') if m in sys.modules))")
        proc = subprocess.run([PYTHON, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
