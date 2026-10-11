import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import verify_r7 as v

BEFORE = {"energy": 1000, "turns": 10, "stats": {"Strength": [16, 16, 0], "AP": [1, 1, 0]},
          "inventory": ["Dagger|x1", "Waterskin|x1"], "equipment": ["Hand:Dagger"], "skills": [],
          "position": "JoppaWorld.11.22.1.1.10@40,20", "journal": {}, "askForOneItem": False,
          "confirmDangerousLiquid": True}


def branch(case, name, after_energy=0, **extra):
    direct_path, ui_path, _ = v.CASES[case]
    after = copy.deepcopy(BEFORE)
    after["energy"] = after_energy
    after["turns"] = 10
    rec = {"kind": "branch_result", "run": f"t-{case}-{name}", "case": case, "branch": name,
           "status": "executed", "path": direct_path if name == "direct" else ui_path,
           "saveSha256": "ab" * 32, "fixture": "r7-fixture-a",
           "load": {"gameId": "g", "zoneId": "z", "turns": 10, "randomSeed": 5, "nextRandomSeed": 7},
           "args": {"x": 41, "y": 20}, "before": copy.deepcopy(BEFORE), "after": after,
           "messages": ["You wait."], "popups": [], "errors": [],
           "directSteps": None if name == "ui" else ["direct_call " + case + " returned"],
           "uiReceipt": None if name == "direct" else {
               "path": ui_path, "completed": True, "directCall": False, "handlerInvoked": True,
               "engineSteps": ui_steps(case)}}
    rec.update(extra)
    return rec


def ui_steps(case):
    out = []
    for marker, count in v.UI_MARKERS.get(case, ()):
        out += [marker + " x"] * count
    return out


def pair(case, **ui_extra):
    return [branch(case, "direct"), branch(case, "ui", **ui_extra)]


NOTE = "$note_fixture_1"
EFFECTS = {
    "SelectNode": ("skills", "Tactics"),
    "EquipObject": ("equipment", "Hand:Dagger|x1"),
    "Look": ("journal", "JournalMapNote:" + NOTE),
}


def effect_pair(case, **ui_extra):
    """A pair whose after-fingerprints carry the case's required effect in both branches."""
    recs = pair(case, **ui_extra)
    key, value = EFFECTS[case]
    for rec in recs:
        rec["before"][key] = []
        rec["after"][key] = [value]
        if case == "Look":
            rec["args"] = {"dx": 1, "dy": 0, "noteId": NOTE}
    return recs


def all_cases_pass():
    recs = []
    for case in v.CASES:
        recs += effect_pair(case) if case in v.REQUIRED_EFFECT else pair(case)
    return recs


class VerifyTests(unittest.TestCase):
    def test_throw_uses_missile_picker_receipt(self):
        recs = pair("ThrowWeapon")
        ui = recs[1]
        ui["path"] = ui["uiReceipt"]["path"] = "Keyboard.PushCommand:CmdThrow+FireMissileWeapon"
        ui["uiReceipt"]["engineSteps"] = ["Keyboard.PushCommand(CmdThrow)",
            "FireMissileWeapon PointerOver(36,22)", "FireMissileWeapon PointerOver(36,22)",
            "FireMissileWeapon CmdFire", "consumed_by_PlayerTurn energy=143"]
        self.assertEqual(v.verify(recs, ["ThrowWeapon"])["overall"], "PASS")
        ui["path"] = ui["uiReceipt"]["path"] = "Keyboard.PushCommand:CmdThrow+PickTarget"
        self.assertEqual(v.verify(recs, ["ThrowWeapon"])["overall"], "FAIL")

    def test_missing_fingerprint_fields_cannot_pass_as_equal(self):
        recs = pair("CmdWait")
        for rec in recs:
            rec["before"] = {}
            rec["after"] = {}
        self.assertEqual(v.verify(recs, ["CmdWait"])["overall"], "FAIL")

    def test_identical_invalid_save_hashes_are_rejected(self):
        recs = pair("CmdWait", saveSha256="unverified")
        recs[0]["saveSha256"] = "unverified"
        self.assertEqual(v.verify(recs, ["CmdWait"])["overall"], "FAIL")

    def test_equivalent_pair_passes_case(self):
        report = v.verify(pair("CmdWait"), ["CmdWait"])
        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["cases"]["CmdWait"]["status"], "EQUIVALENT")

    def test_unequal_energy_fails(self):
        report = v.verify(pair("CmdWait", after_energy=100), ["CmdWait"])
        self.assertEqual(report["overall"], "FAIL")
        self.assertTrue(any(e.startswith("DIFF:energy") for e in report["cases"]["CmdWait"]["errors"]))

    def test_absent_ui_proof_fails(self):
        report = v.verify(pair("CmdWait", uiReceipt=None), ["CmdWait"])
        self.assertIn("ui:NO_UI_RECEIPT", report["cases"]["CmdWait"]["errors"])
        self.assertEqual(report["overall"], "FAIL")

    def test_ui_receipt_marked_direct_fails(self):
        recs = pair("CmdWait")
        recs[1]["uiReceipt"]["directCall"] = True
        self.assertIn("ui:DIRECT_CALL_NOT_EXCLUDED", v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"])

    def test_direct_branch_relabelled_as_ui_fails(self):
        recs = pair("CmdWait")
        recs[1]["path"] = v.CASES["CmdWait"][0]
        recs[1]["uiReceipt"]["path"] = v.CASES["CmdWait"][0]
        self.assertEqual(v.verify(recs, ["CmdWait"])["overall"], "FAIL")

    def test_direct_with_receipt_fails(self):
        recs = pair("CmdWait")
        recs[0]["uiReceipt"] = {"path": "x"}
        self.assertIn("direct:HAS_UI_RECEIPT", v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"])

    def test_missing_case_is_incomplete(self):
        report = v.verify(pair("CmdWait"), ["CmdWait", "BuyStat"])
        self.assertEqual(report["cases"]["BuyStat"]["status"], "MISSING")
        self.assertEqual(report["overall"], "INCOMPLETE")

    def test_missing_ui_branch(self):
        report = v.verify([branch("CmdWait", "direct")], ["CmdWait"])
        self.assertEqual(report["cases"]["CmdWait"]["status"], "MISSING")

    def test_non_equivalent_baseline_fingerprint(self):
        recs = pair("CmdWait")
        recs[1]["before"]["stats"]["Strength"] = [17, 17, 0]
        recs[1]["after"]["stats"]["Strength"] = [17, 17, 0]
        self.assertIn("BASELINE:FINGERPRINT", v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"])

    def test_different_save_bytes_or_seed(self):
        recs = pair("CmdWait", saveSha256="cd" * 32)
        recs[1]["load"]["randomSeed"] = 6
        errors = v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"]
        self.assertIn("BASELINE:SAVE_SHA256", errors)
        self.assertIn("BASELINE:LOAD:randomSeed", errors)

    def test_missing_sha_is_not_baseline(self):
        recs = pair("CmdWait", saveSha256=None)
        recs[0]["saveSha256"] = None
        self.assertIn("BASELINE:SAVE_SHA256", v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"])

    def test_fabricated_random_fields_rejected(self):
        recs = pair("ThrowWeapon")
        recs[1]["after"]["targetHp"] = 3
        recs[0]["damage"] = 4
        errors = v.verify(recs, ["ThrowWeapon"])["cases"]["ThrowWeapon"]["errors"]
        self.assertIn("ui:RANDOM_FIELD:after.targetHp", errors)
        self.assertIn("direct:RANDOM_FIELD:damage", errors)

    def test_throw_messages_not_compared(self):
        recs = pair("ThrowWeapon", messages=["You hit for 3 damage."])
        report = v.verify(recs, ["ThrowWeapon"])
        self.assertEqual(report["cases"]["ThrowWeapon"]["status"], "EQUIVALENT")
        self.assertNotIn("messages", report["cases"]["ThrowWeapon"]["compared"])

    def test_non_random_message_difference_fails(self):
        report = v.verify(pair("CmdWait", messages=["Something else."]), ["CmdWait"])
        self.assertEqual(report["overall"], "FAIL")

    def test_inventory_delta_difference_fails(self):
        recs = pair("CommandGet")
        recs[0]["after"]["inventory"].append("Rock|x1")
        self.assertTrue(any(e.startswith("DIFF:inventory") for e in
                            v.verify(recs, ["CommandGet"])["cases"]["CommandGet"]["errors"]))

    def test_direct_style_steps_under_ui_label_fail(self):
        recs = pair("Drink")
        recs[1]["uiReceipt"]["engineSteps"] = ["actions=Drink:Drink", "direct_call Process returned event=x"]
        errors = v.verify(recs, ["Drink"])["cases"]["Drink"]["errors"]
        self.assertIn("ui:FORBIDDEN_STEP:direct_call ", errors)
        self.assertTrue(any(e.startswith("ui:MARKER:") for e in errors))

    def test_throw_needs_two_pointer_overs(self):
        recs = pair("ThrowWeapon")
        recs[1]["uiReceipt"]["engineSteps"].remove("FireMissileWeapon PointerOver( x")
        self.assertIn("ui:MARKER:FireMissileWeapon PointerOver(:1!=2",
                      v.verify(recs, ["ThrowWeapon"])["cases"]["ThrowWeapon"]["errors"])

    def test_deadline_step_fails(self):
        recs = pair("ThrowWeapon")
        recs[1]["uiReceipt"]["engineSteps"].append("deadline Escape on FireMissileWeapon")
        self.assertEqual(v.verify(recs, ["ThrowWeapon"])["overall"], "FAIL")

    def test_direct_without_call_step_fails(self):
        recs = pair("CmdWait")
        recs[0]["directSteps"] = []
        self.assertIn("direct:NO_DIRECT_CALL_STEP", v.verify(recs, ["CmdWait"])["cases"]["CmdWait"]["errors"])

    def test_screen_handler_flag_required(self):
        recs = pair("BuyStat")
        recs[1]["uiReceipt"]["handlerInvoked"] = False
        self.assertIn("ui:HANDLER_NOT_INVOKED", v.verify(recs, ["BuyStat"])["cases"]["BuyStat"]["errors"])

    def test_unsupported_without_records(self):
        # All 10 UI routes now exist, so absent records are MISSING, never a pass.
        report = v.verify([], ["SelectNode", "EquipObject", "Look"])
        self.assertEqual({r["status"] for r in report["cases"].values()}, {"MISSING"})
        self.assertEqual(report["overall"], "INCOMPLETE")

    def test_ui_path_none_is_unsupported_without_records(self):
        with mock.patch.dict(v.CASES, {"Look": (v.CASES["Look"][0], None, v.LOOK_KEYS)}):
            report = v.verify([], ["Look"])
        self.assertEqual(report["cases"]["Look"]["status"], "UNSUPPORTED")
        self.assertEqual(report["overall"], "INCOMPLETE")

    def test_subset_flagged(self):
        self.assertTrue(v.verify(pair("CmdWait"), ["CmdWait"])["subset"])

    def test_unsupported_is_not_pass(self):
        reason = "UI_UNAVAILABLE: Look ui needs Options.ModernUI"
        recs = [branch("Look", "direct"),
                branch("Look", "ui", status="unsupported", reason=reason, uiReceipt=None)]
        report = v.verify(recs, ["Look"])
        self.assertEqual(report["cases"]["Look"]["status"], "UNSUPPORTED")
        self.assertEqual(report["overall"], "INCOMPLETE")

    def test_explicit_unsupported_even_when_all_paths_exist(self):
        recs = effect_pair("SelectNode")
        recs[1].update(status="unsupported", reason="UI_UNAVAILABLE: classic character sheet", uiReceipt=None)
        report = v.verify(recs, ["SelectNode"])
        self.assertEqual(report["cases"]["SelectNode"]["status"], "UNSUPPORTED")
        self.assertNotEqual(report["overall"], "PASS")

    def test_ui_path_unsupported_even_if_record_claims_executed(self):
        with mock.patch.dict(v.CASES, {"SelectNode": (v.CASES["SelectNode"][0], None, v.DETERMINISTIC)}):
            report = v.verify(effect_pair("SelectNode"), ["SelectNode"])
        self.assertEqual(report["cases"]["SelectNode"]["status"], "UNSUPPORTED")

    def test_selectnode_equivalent_with_effect(self):
        report = v.verify(effect_pair("SelectNode"), ["SelectNode"])
        self.assertEqual(report["cases"]["SelectNode"]["status"], "EQUIVALENT", report)

    def test_selectnode_noop_pair_fails(self):
        errors = v.verify(pair("SelectNode"), ["SelectNode"])["cases"]["SelectNode"]["errors"]
        self.assertIn("direct:NO_EFFECT:skills", errors)
        self.assertIn("ui:NO_EFFECT:skills", errors)

    def test_selectnode_needs_active_line_and_handler(self):
        recs = effect_pair("SelectNode")
        recs[1]["uiReceipt"]["engineSteps"] = [x for x in recs[1]["uiReceipt"]["engineSteps"]
                                              if "SkillsAndPowersLine active=True" not in x]
        recs[1]["uiReceipt"]["handlerInvoked"] = False
        errors = v.verify(recs, ["SelectNode"])["cases"]["SelectNode"]["errors"]
        self.assertIn("ui:MARKER:SkillsAndPowersLine active=True:0!=1", errors)
        self.assertIn("ui:HANDLER_NOT_INVOKED", errors)

    def test_equip_equivalent_and_one_sided_effect_fails(self):
        self.assertEqual(v.verify(effect_pair("EquipObject"), ["EquipObject"])["overall"], "PASS")
        recs = effect_pair("EquipObject")
        recs[1]["after"]["equipment"] = []
        errors = v.verify(recs, ["EquipObject"])["cases"]["EquipObject"]["errors"]
        self.assertIn("ui:NO_EFFECT:equipment", errors)

    def test_look_requires_the_requested_note(self):
        recs = effect_pair("Look")
        for rec in recs:
            rec["after"]["journal"] = ["JournalMapNote:other"]
        errors = v.verify(recs, ["Look"])["cases"]["Look"]["errors"]
        self.assertIn("direct:NOTE_NOT_REVEALED:" + NOTE, errors)
        self.assertIn("ui:NOTE_NOT_REVEALED:" + NOTE, errors)

    def test_look_popups_recorded_not_compared(self):
        recs = effect_pair("Look")
        recs[0]["popups"] = [{"text": "description", "answer": "Accept"}]
        report = v.verify(recs, ["Look"])
        self.assertEqual(report["cases"]["Look"]["status"], "EQUIVALENT", report)
        self.assertNotIn("popups", report["cases"]["Look"]["compared"])

    def test_look_messages_still_compared(self):
        recs = effect_pair("Look", messages=["Something else."])
        self.assertIn("messages", v.LOOK_KEYS)
        self.assertEqual(v.verify(recs, ["Look"])["overall"], "FAIL")

    def test_look_ui_needs_escape_after_tooltip(self):
        recs = effect_pair("Look")
        recs[1]["uiReceipt"]["engineSteps"] = [x for x in recs[1]["uiReceipt"]["engineSteps"] if "Looker Escape" not in x]
        self.assertIn("ui:MARKER:Looker Escape:0!=1", v.verify(recs, ["Look"])["cases"]["Look"]["errors"])

    def test_look_deadline_escape_fails(self):
        recs = effect_pair("Look")
        recs[1]["uiReceipt"]["engineSteps"].append("deadline Escape on Looker")
        self.assertEqual(v.verify(recs, ["Look"])["overall"], "FAIL")

    def test_look_noteid_must_match_between_branches(self):
        recs = effect_pair("Look")
        recs[1]["args"] = {"dx": 1, "dy": 0, "noteId": "other"}
        self.assertIn("BASELINE:ARGS", v.verify(recs, ["Look"])["cases"]["Look"]["errors"])

    def test_all_ten_cases_full_pass(self):
        report = v.verify(all_cases_pass())
        self.assertEqual(report["overall"], "PASS", report)
        self.assertFalse(report["subset"])

    def test_failed_branch_status_not_satisfied(self):
        recs = pair("BuyStat", status="precondition_failed", reason="AP<1")
        self.assertEqual(v.verify(recs, ["BuyStat"])["overall"], "FAIL")

    def test_branch_errors_fail(self):
        recs = pair("BuyStat", errors=["UI_TIMEOUT"])
        self.assertEqual(v.verify(recs, ["BuyStat"])["overall"], "FAIL")

    def test_duplicate_branch_fails(self):
        recs = pair("CmdWait") + [branch("CmdWait", "ui")]
        self.assertEqual(v.verify(recs, ["CmdWait"])["overall"], "FAIL")

    def test_unexpected_fingerprint_field(self):
        recs = pair("CmdWait")
        recs[0]["before"]["bogus"] = 1
        self.assertEqual(v.verify(recs, ["CmdWait"])["overall"], "FAIL")

    def test_default_requires_all_cases(self):
        report = v.verify(pair("CmdWait"))
        self.assertEqual(set(report["cases"]), set(v.CASES))
        self.assertEqual(report["overall"], "INCOMPLETE")

    def test_reads_player_log_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "Player.log"
            lines = ["noise", *("INFO - [R7] " + json.dumps(r) for r in pair("CmdWait")), "[R7] {broken"]
            log.write_text("\n".join(lines), encoding="utf-8")
            self.assertEqual(v.main(["--player-log", str(log), "--case", "CmdWait"]), 0)


class CrossLanguageTableTests(unittest.TestCase):
    def test_mod_paths_and_reasons_match_verifier(self):
        src = (Path(__file__).parent / "mod" / "R7Policy.cs").read_text(encoding="utf-8")
        for case, (direct, ui, _) in v.CASES.items():
            self.assertIn('"' + case + '"', src)
            head = direct.split(":")[0] + ":" if direct.startswith("InventoryAction.Process:") else direct
            self.assertIn(head, src, case)
            if ui is not None:
                self.assertIn('"' + ui + '"', src, case)
        for reason in v.UNSUPPORTED_UI.values():
            self.assertIn('"' + reason + '"', src)
        probe = (Path(__file__).parent / "mod" / "R7Probe.cs").read_text(encoding="utf-8")
        for literal in v.SOURCE_LITERALS:
            self.assertIn(literal, probe)


if __name__ == "__main__":
    unittest.main()
