"""R6 verifier: the golden five-case scenario passes; each required failure is detected by code."""

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import r6_scenario as sc
import r6_verify as rv


def codes(summary):
    found = {e["code"] for e in summary["global_errors"]}
    for case in summary["cases"]:
        found |= {e["code"] for e in case["errors"]}
    return found


def case_codes(summary, name):
    return {e["code"] for c in summary["cases"] if c["case"] == name for e in c["errors"]}


class VerifierTests(unittest.TestCase):
    def test_explicit_recovery_clears_pending_without_fabricated_result(self):
        s = self.golden(lifecycle_recovery=True)
        summary = self.run_verify(s)
        self.assertTrue(summary["ok"], summary)
        checkpoint = next(c for c in summary["cases"] if c["case"] == "checkpoint_reload")
        self.assertIsNone(checkpoint["facts"]["first_cta"]["pending_seq"])
        self.assertIn("recovery", checkpoint["facts"])

    def test_recovery_save_hash_must_match_actual_loaded_save(self):
        s = self.golden(lifecycle_recovery=True, recovery_overrides={"save_sha256":sc.sha("wrong")})
        summary = self.run_verify(s)
        self.assertIn("recovery_mismatch", case_codes(summary, "checkpoint_reload"))

    def test_recovery_game_identity_must_match_probe(self):
        s = self.golden(lifecycle_recovery=True, recovery_overrides={"game_id":"foreign"})
        summary = self.run_verify(s)
        self.assertIn("recovery_mismatch", case_codes(summary, "checkpoint_reload"))

    def test_load_time_baseline_is_not_evidence_of_a_prior_save(self):
        s = self.golden()
        load = s.marks["menu_load"]
        digest = sc.sha("unobserved replacement")
        load["candidates"]["Primary"]["sha256"] = digest
        records = s.sessions[0]["records"]
        observed = dict(load)
        observed.update(kind="save_observed", file="Primary", game_id=sc.GAME_ID,
                        sha256=digest, baseline=True)
        records.insert(records.index(load), observed)
        self.assertIn("save_hash", case_codes(self.run_verify(s, claims=False), "menu_reenter"))

    def test_ambiguous_loaded_save_identity_is_rejected(self):
        s = self.golden()
        s.marks["process_load"]["loaded_file_basis"] = "json_turn_tie_different_hash"
        self.assertIn("save_hash", case_codes(self.run_verify(s), "save_quit_load"))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_verify(self, scenario, claims=True, **kwargs):
        paths = scenario.write(claims=claims)
        return rv.verify(paths["evidence_dir"], paths["ledger_paths"], paths["receipts_dir"],
                         paths["claims_path"], **kwargs)

    def golden(self, **kwargs):
        return sc.golden(self.root / "s", **kwargs)

    # ------------------------------------------------------------ positive
    def test_golden_scenario_passes_all_five_cases(self):
        summary = self.run_verify(self.golden(), require_claims=True)
        self.assertTrue(summary["ok"], json.dumps(summary, indent=1)[:4000])
        self.assertEqual(sorted(c["case"] for c in summary["cases"]), sorted(rv.CASES))
        facts = {c["case"]: c["facts"] for c in summary["cases"]}
        self.assertEqual(facts["crash_restart"]["lost_turns"], 2)
        self.assertEqual(facts["crash_restart"]["raw_turn_delta"], 2)
        self.assertEqual(facts["save_quit_load"]["lost_turns"], 0)
        self.assertEqual(facts["menu_reenter"]["lost_turns"], 0)
        self.assertEqual(facts["hotload"]["lost_turns"], 0)
        self.assertEqual(facts["checkpoint_reload"]["checkpoint_rewind_turns"], 9)
        self.assertEqual(facts["checkpoint_reload"]["reload_label_evidence"], "probe_label")
        self.assertTrue(facts["checkpoint_reload"]["artificial_death"])
        self.assertEqual(facts["menu_reenter"]["run_continuity"], "continued")
        self.assertEqual(facts["crash_restart"]["run_continuity"], "new_run")
        self.assertEqual(facts["checkpoint_reload"]["loaded_sha256"], sc.sha("C0"))
        self.assertFalse(summary["gameplay_claim_eligible"])
        self.assertIn("artificial death fixture", summary["not_claimable_because"])
        self.assertLessEqual(summary["budget"]["played_turns"], 110)

    def test_external_label_answer_from_ledger_modal_auto_is_accepted(self):
        summary = self.run_verify(self.golden(death_by_probe=False))
        self.assertTrue(summary["ok"], summary)
        facts = {c["case"]: c["facts"] for c in summary["cases"]}
        self.assertEqual(facts["checkpoint_reload"]["reload_label_evidence"], "ledger_modal_auto")

    def test_cli_emits_recovery_rows_and_exit_code(self):
        s = self.golden()
        paths = s.write()
        out = self.root / "recovery.jsonl"
        argv = ["--evidence-dir", str(paths["evidence_dir"]), "--receipts-dir", str(paths["receipts_dir"]),
                "--claims", str(paths["claims_path"]), "--require-recovery-claims", "--emit-recovery", str(out)]
        for ledger in paths["ledger_paths"]:
            argv += ["--ledger", str(ledger)]
        self.assertEqual(rv.main(argv), 0)
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        self.assertEqual({r["case"] for r in rows}, set(rv.CASES))
        crash = next(r for r in rows if r["case"] == "crash_restart")
        self.assertEqual((crash["lost_turns"], crash["loaded_sha256"]), (2, sc.sha("P3")))

    # ------------------------------------------------------------ callbacks
    def test_missing_production_callbacks_after_hotload(self):
        s = self.golden()
        for key in ("begin", "end", "after_render", "message"):
            s.marks["hotload_cta"]["callbacks"]["production"][key] = 0
        summary = self.run_verify(s)
        self.assertFalse(summary["ok"])
        self.assertIn("production_callback_count", case_codes(summary, "hotload"))

    def test_duplicate_production_callback(self):
        s = self.golden()
        s.marks["menu_cta"]["callbacks"]["production"]["end"] = 2
        summary = self.run_verify(s)
        self.assertIn("production_callback_count", case_codes(summary, "menu_reenter"))

    def test_duplicate_own_callback_anywhere_in_window(self):
        s = self.golden()
        s.marks["checkpoint_heartbeat"]["callbacks"]["own"]["message"] = 2
        summary = self.run_verify(s)
        self.assertIn("own_callback_count", case_codes(summary, "checkpoint_reload"))

    def test_hotload_own_reregistration_missing(self):
        s = self.golden()
        s.marks["hotload_init"]["callbacks"]["own"]["begin"] = 0
        summary = self.run_verify(s)
        self.assertIn("own_callback_count", case_codes(summary, "hotload"))

    # ------------------------------------------------------------ bridge
    def test_bridge_count_mismatch(self):
        s = self.golden()
        s.marks["crash_cta"]["bridge_live"] = 2
        summary = self.run_verify(s)
        self.assertIn("bridge_count", case_codes(summary, "crash_restart"))

    def test_bridge_count_unavailable(self):
        s = self.golden()
        s.marks["menu_cta"]["bridge_live"] = None
        summary = self.run_verify(s)
        self.assertIn("bridge_count_unavailable", case_codes(summary, "menu_reenter"))

    # ------------------------------------------------------------ first request
    def test_duplicated_first_request_in_probe_evidence(self):
        s = self.golden()
        dup = dict(s.marks["crash_cta"])
        dup["first_after_boundary"] = False
        records = s.sessions[-1]["records"]
        records.insert(records.index(s.marks["crash_cta"]) + 1, dup)
        summary = self.run_verify(s)
        self.assertIn("first_request_duplicated", case_codes(summary, "crash_restart"))

    def test_duplicated_first_request_in_two_ledgers(self):
        s = self.golden()
        paths = s.write()
        original = paths["ledger_paths"][-1]
        copy = self.root / "copy-ledger.jsonl"
        copy.write_bytes(original.read_bytes())
        summary = rv.verify(paths["evidence_dir"], paths["ledger_paths"] + [copy], paths["receipts_dir"],
                            paths["claims_path"])
        self.assertIn("first_request_duplicated", case_codes(summary, "crash_restart"))

    def test_missing_first_request(self):
        s = self.golden()
        records = s.sessions[-1]["records"]
        index = records.index(s.marks["crash_cta"])
        del records[index:]
        summary = self.run_verify(s)
        self.assertIn("first_request_missing", case_codes(summary, "crash_restart"))

    def test_stale_pending_seq_on_continuing_run(self):
        s = self.golden()
        s.marks["menu_cta"]["production"]["seq"] = 1
        s.marks["menu_cta"]["production"]["pending_seq"] = 1
        summary = self.run_verify(s)
        self.assertIn("stale_pending_seq", case_codes(summary, "menu_reenter"))

    def test_lost_pending_decision_is_stale(self):
        s = self.golden()
        s.marks["hotload_cta"]["production"]["pending_seq"] = None
        summary = self.run_verify(s)
        self.assertIn("stale_pending_seq", case_codes(summary, "hotload"))

    def test_new_run_must_start_at_seq_one(self):
        s = self.golden()
        s.marks["crash_cta"]["production"]["pending_seq"] = 1
        summary = self.run_verify(s)
        self.assertIn("stale_pending_seq", case_codes(summary, "crash_restart"))

    def test_unlinkable_without_production_fields(self):
        s = self.golden()
        s.marks["menu_cta"]["production"]["run_id"] = None
        s.marks["menu_cta"]["game"]["x"] = 1
        summary = self.run_verify(s)
        self.assertIn("unlinkable", case_codes(summary, "menu_reenter"))

    # ------------------------------------------------------------ identity and saves
    def test_wrong_loaded_save_hash(self):
        s = self.golden()
        s.marks["process_load"]["candidates"]["Primary"]["sha256"] = sc.sha("other")
        summary = self.run_verify(s)
        self.assertIn("save_hash", case_codes(summary, "save_quit_load"))

    def test_wrong_loaded_file_for_checkpoint(self):
        s = self.golden()
        s.marks["checkpoint_load"]["loaded_file"] = "Primary"
        summary = self.run_verify(s)
        self.assertIn("save_hash", case_codes(summary, "checkpoint_reload"))

    def test_receipt_hash_differs_from_loaded(self):
        s = self.golden()
        path = s.marks["crash_receipt"]
        receipt = json.loads(path.read_text())
        receipt["saves"]["Primary"]["sha256"] = sc.sha("tampered")
        path.write_text(json.dumps(receipt))
        summary = self.run_verify(s)
        self.assertIn("save_hash", case_codes(summary, "crash_restart"))

    def test_wrong_game_identity(self):
        s = self.golden()
        s.marks["crash_cta"]["game"]["game_id"] = "another-character"
        summary = self.run_verify(s)
        self.assertIn("game_identity", case_codes(summary, "crash_restart"))

    def test_first_cta_cannot_precede_loaded_turns(self):
        s = self.golden()
        s.marks["process_load"]["game"]["turns"] = 7
        s.marks["process_load"]["candidates"]["Primary"]["json_turn"] = 7
        summary = self.run_verify(s)
        self.assertIn("game_identity", case_codes(summary, "save_quit_load"))

    def test_load_and_first_cta_turns_are_distinct_when_energy_recharges(self):
        s = self.golden(lifecycle_recovery=True, checkpoint_advance=1)
        summary = self.run_verify(s)
        self.assertTrue(summary["ok"], summary)
        facts = next(c["facts"] for c in summary["cases"] if c["case"] == "checkpoint_reload")
        self.assertEqual(facts["loaded_turn"], 5)
        self.assertEqual(facts["first_cta"]["turns"], 6)
        self.assertEqual(facts["load_to_cta_turns"], 1)
        self.assertEqual(facts["recovery"]["loaded_turn"], 5)
        self.assertEqual(facts["checkpoint_rewind_turns"], 9)

    def test_load_advance_does_not_excuse_player_input(self):
        original = sc.Scenario.telemetry
        def entered(scenario):
            return {**original(scenario), "player_turn_entries": 1}
        with patch.object(sc.Scenario, "telemetry", entered):
            s = self.golden(lifecycle_recovery=True, checkpoint_advance=1)
        summary = self.run_verify(s)
        self.assertFalse(summary["ok"])
        self.assertIn("unexpected_player_turn", case_codes(summary, "checkpoint_reload"))

    # ------------------------------------------------------------ lost turns and claims
    def test_incorrect_lost_turns_claim(self):
        s = self.golden()
        for claim in s.claims:
            if claim["case"] == "crash_restart":
                claim["lost_turns"] = 0
        summary = self.run_verify(s)
        self.assertIn("lost_turns_claim", case_codes(summary, "crash_restart"))

    def test_required_claims_absent(self):
        summary = self.run_verify(self.golden(), claims=False, require_claims=True)
        self.assertIn("recovery_claims_absent", codes(summary))
        self.assertFalse(summary["ok"])

    # ------------------------------------------------------------ real death and crash
    def test_absent_real_death_menu_only(self):
        s = self.golden()
        records = s.sessions[0]["records"]
        records.remove(s.marks["die_path"])
        summary = self.run_verify(s)
        self.assertIn("real_death_absent", case_codes(summary, "checkpoint_reload"))

    def test_absent_reload_label_evidence(self):
        s = self.golden()
        s.sessions[0]["records"].remove(s.marks["death_answer"])
        summary = self.run_verify(s)
        self.assertIn("death_label_absent", case_codes(summary, "checkpoint_reload"))

    def test_fixture_must_not_create_a_production_decision(self):
        s = self.golden()
        records = s.sessions[0]["records"]
        extra = dict(s.marks["hotload_cta"])
        extra["first_after_boundary"] = False
        records.insert(records.index(s.marks["die_path"]), extra)
        summary = self.run_verify(s)
        self.assertIn("fixture_created_decision", case_codes(summary, "checkpoint_reload"))

    def test_absent_crash_receipt(self):
        s = self.golden()
        s.marks["crash_receipt"].unlink()
        summary = self.run_verify(s)
        self.assertIn("crash_receipt_absent", case_codes(summary, "crash_restart"))

    def test_crash_receipt_must_be_sigkill_not_dry_run(self):
        for change in ({"signal": "SIGTERM"}, {"dry_run": True}, {"verified": {"profile": False}},
                       {"pid": 1}, {"process_gone": False}, {"last_probe_turn": 3}):
            with self.subTest(change=change):
                root = self.root / ("c" + str(abs(hash(json.dumps(change, sort_keys=True)))))
                s = sc.golden(root)
                path = s.marks["crash_receipt"]
                receipt = json.loads(path.read_text())
                receipt.update(change)
                path.write_text(json.dumps(receipt))
                summary = self.run_verify(s)
                self.assertIn("crash_receipt_absent", case_codes(summary, "crash_restart"))

    def test_absent_exit_receipt(self):
        s = self.golden()
        s.marks["exit_receipt"].unlink()
        summary = self.run_verify(s)
        self.assertIn("exit_receipt_absent", case_codes(summary, "save_quit_load"))

    def test_truncated_tail_requires_crash_receipt(self):
        s = self.golden()
        s.marks["crash_receipt"].unlink()
        paths = s.write()
        evidence = sorted(paths["evidence_dir"].glob("*.jsonl"))[1]
        evidence.write_bytes(evidence.read_bytes() + b'{"v":1,"partial')
        summary = rv.verify(paths["evidence_dir"], paths["ledger_paths"], paths["receipts_dir"],
                            paths["claims_path"])
        self.assertIn("evidence_chain", codes(summary))

    # ------------------------------------------------------------ hotload realism
    def test_hotload_without_wish_evidence_is_not_real(self):
        s = self.golden()
        s.marks["hotload_init"]["wish_frame"] = False
        records = s.sessions[0]["records"]
        begin = next(r for r in records if r["kind"] == "fixture_begin" and r["fixture"] == "reload")
        records.remove(begin)
        summary = self.run_verify(s)
        self.assertIn("hotload_not_real", case_codes(summary, "hotload"))

    def test_cache_reset_alone_or_plain_reinit_is_not_real(self):
        for key in ("lists_replaced", "sentinel_reset", "hotload_frame"):
            with self.subTest(key=key):
                s = sc.golden(self.root / key)
                s.marks["hotload_init"][key] = False
                summary = self.run_verify(s)
                self.assertIn("hotload_not_real", case_codes(summary, "hotload"))

    # ------------------------------------------------------------ integrity and scope
    def test_tampered_evidence_line_breaks_chain(self):
        s = self.golden()
        paths = s.write()
        evidence = sorted(paths["evidence_dir"].glob("*.jsonl"))[0]
        lines = evidence.read_bytes().split(b"\n")
        lines[3] = lines[3].replace(b'"thread":"', b'"thread":"x')
        evidence.write_bytes(b"\n".join(lines))
        summary = rv.verify(paths["evidence_dir"], paths["ledger_paths"], paths["receipts_dir"],
                            paths["claims_path"])
        self.assertFalse(summary["ok"])
        self.assertIn("evidence_chain", codes(summary))

    def test_tampered_ledger_is_invalid(self):
        s = self.golden()
        paths = s.write()
        ledger = paths["ledger_paths"][0]
        ledger.write_text(ledger.read_text().replace('"turn":10', '"turn":11', 1))
        summary = rv.verify(paths["evidence_dir"], paths["ledger_paths"], paths["receipts_dir"],
                            paths["claims_path"])
        self.assertIn("ledger_invalid", codes(summary))
        self.assertFalse(summary["ok"])

    def test_budget_exceeded(self):
        summary = self.run_verify(self.golden(), max_turns=5)
        self.assertIn("budget_exceeded", codes(summary))

    def test_missing_cases_are_reported(self):
        s = self.golden()
        del s.sessions[1:]
        s.ledger_paths = s.ledger_paths[:1]
        summary = self.run_verify(s)
        self.assertEqual(set(summary["missing_cases"]), {"save_quit_load", "crash_restart"})
        self.assertIn("case_missing", codes(summary))
        self.assertFalse(summary["ok"])

    def test_subset_of_cases_can_pass(self):
        s = self.golden()
        del s.sessions[1:]
        s.ledger_paths = s.ledger_paths[:1]
        summary = self.run_verify(s, cases=("menu_reenter", "hotload", "checkpoint_reload"))
        self.assertTrue(summary["ok"], summary["global_errors"])


if __name__ == "__main__":
    unittest.main()
