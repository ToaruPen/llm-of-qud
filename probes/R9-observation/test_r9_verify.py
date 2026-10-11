"""Negative/positive tests for the R9 verifier on synthetic audit records (not runtime evidence)."""

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("r9_verify", HERE / "r9_verify.py")
r9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r9)

from tests.support import RUN_ID, make_map, make_telemetry  # noqa: E402

LOG = [f"message {n}" for n in range(20)]


def oracle(turn):
    return {
        "vitals": {"hp": 14, "max_hp": 14, "x": 40, "y": 12, "zone": "JoppaWorld.11.22.1.1.10",
                   "turn": turn, "energy": 1000},
        "entities": [
            {"x": 41, "y": 12, "visible": True, "shown": "pig", "true_name": "pig", "blueprint": "Pig",
             "wound": "{{Y|Perfect}}", "scanned": False, "hp": 8, "max_hp": 8, "hostile": False},
            {"x": 43, "y": 12, "visible": True, "shown": "turret", "true_name": "turret",
             "blueprint": "Turret", "wound": "{{Y|20/20}} {{b|\u0004}}4 {{K|\t}}2", "scanned": True,
             "hp": 20, "max_hp": 20, "hostile": True},
            {"x": 5, "y": 5, "visible": False, "shown": "goatfolk sower", "true_name": "goatfolk sower",
             "blueprint": "Goatfolk Sower", "wound": "{{Y|Perfect}}", "scanned": False, "hp": 30,
             "max_hp": 30, "hostile": True},
        ],
        "kit": [
            {"shown": "bronze dagger", "true_name": "bronze dagger", "blueprint": "Dagger",
             "understood": True, "slot": "Hand"},
            {"shown": "{{c|weird knife}}", "true_name": "{{c|vibro dagger}}", "blueprint": "Vibro Dagger",
             "understood": False, "slot": None},
        ],
        "digest_log_tail": LOG[-12:], "digest_log_since_arm": 20, "modal_notices": [],
        "effects": [{"class": "Bleeding", "description": "{{r|bleeding}}"}, {"class": "Hidden", "description": ""}],
        "zone_name": "Joppa", "world_map": False, "lost": False,
    }


def observation_from(o, frame):
    return {
        "vitals": dict(o["vitals"]),
        "threats": [{"id": f"e{n + 1}", "name": e["shown"], "wound": e["wound"], "x": e["x"], "y": e["y"],
                     "hostile": e["hostile"]} for n, e in enumerate(x for x in o["entities"] if x["visible"])],
        "digest": list(o["digest_log_tail"]),
        "map": make_map(),
        "map_frame": frame,
        "kit": [{"id": f"i{n + 1}", "name": k["shown"], "slot": k["slot"]} for n, k in enumerate(o["kit"])],
        "status": {"effects": ["{{r|bleeding}}"], "food_water": "Sated Quenched"},
        "place": {"name": "Joppa", "world_map": False, "lost": False},
    }


def record(seq, turn, obs=None, o=None, renders=(0, 1)):
    o = o or oracle(turn)
    obs = obs or observation_from(o, seq)
    request = json.dumps({"kind": "request", "run_id": RUN_ID, "seq": seq, "observation": obs,
                          "telemetry": make_telemetry(cta=seq)}, ensure_ascii=False)
    return {"kind": "r9_audit", "header": {"run_id": RUN_ID, "seq": seq, "cta": seq, "result_seq": None},
            "request_sha256": hashlib.sha256(request.encode()).hexdigest(), "request": request,
            "renders_before": renders[0], "renders_after": renders[1], "oracle": o}


def run(n=201):
    return [record(seq, seq) for seq in range(1, n + 1)]


def mutate(records, index, fn):
    records = copy.deepcopy(records)
    rec = records[index]
    message = json.loads(rec["request"])
    fn(message["observation"], rec["oracle"])
    fixed = record(rec["header"]["seq"], rec["oracle"]["vitals"]["turn"], message["observation"], rec["oracle"],
                   (rec["renders_before"], rec["renders_after"]))
    records[index] = fixed
    return records


class VerifierTests(unittest.TestCase):
    def assertFailsWith(self, records, fragment, **kw):
        summary = r9.verify(records, **kw)
        self.assertFalse(summary["ok"], summary)
        self.assertTrue(any(fragment in f for f in summary["failures"]), summary["failures"])

    def test_valid_run_passes_with_case_counts_from_oracle(self):
        summary = r9.verify(run())
        self.assertTrue(summary["ok"], summary["failures"])
        self.assertEqual(summary["advancing_turns"], 200)
        self.assertTrue(all(v == 201 for v in summary["case_records"].values()))

    def test_scanned_numeric_wound_is_allowed(self):
        self.assertTrue(r9.verify(run())["ok"])  # turret carries 20/20 while scanned

    def test_leaked_true_name_of_unidentified_item_fails(self):
        records = mutate(run(), 50, lambda obs, o: obs["kit"][1].update(name="vibro dagger"))
        self.assertFailsWith(records, "true name leaked")

    def test_hidden_entity_in_threats_fails(self):
        def leak(obs, o):
            obs["threats"].append({"id": "e9", "name": "goatfolk sower", "wound": "{{Y|Perfect}}", "x": 5,
                                   "y": 5, "hostile": True})
        self.assertFailsWith(mutate(run(), 10, leak), "hidden entity leaked")

    def test_unsolicited_numeric_hp_fails(self):
        records = mutate(run(), 7, lambda obs, o: obs["threats"][0].update(wound="8/8"))
        self.assertFailsWith(records, "numeric HP shown without Scanning")

    def test_numeric_hp_fails_even_if_oracle_wound_agrees(self):
        def both(obs, o):
            o["entities"][0]["wound"] = "8/8"
            obs["threats"][0]["wound"] = "8/8"
        self.assertFailsWith(mutate(run(), 7, both), "numeric HP shown without Scanning")

    def test_each_missing_case_fails_despite_200_records(self):
        removers = {
            "unidentified_item": lambda o: o["kit"][1].update(understood=True, true_name=o["kit"][1]["shown"]),
            "nonvisible_creature": lambda o: o["entities"].pop(2),
            "nonscanned_visible_creature": lambda o: o["entities"][0].update(scanned=True),
        }
        for case, remove in removers.items():
            with self.subTest(case=case):
                records = []
                for seq in range(1, 202):
                    o = oracle(seq)
                    remove(o)
                    records.append(record(seq, seq, o=o))
                summary = r9.verify(records)
                self.assertEqual(summary["failures"], [f"required case absent: {case}"])

    def test_stale_map_frame_fails(self):
        records = mutate(run(), 30, lambda obs, o: obs.update(map_frame=29))
        self.assertFailsWith(records, "stale map")

    def test_no_render_between_capture_points_fails(self):
        records = run()
        records[40] = record(41, 41, renders=(5, 5))
        self.assertFailsWith(records, "no AfterRender")

    def test_fewer_than_200_distinct_turns_fails(self):
        self.assertFailsWith(run(200), "only 199 distinct advancing world turns")

    def test_repeated_cta_at_same_turn_is_not_counted(self):
        records = [record(seq, (seq + 1) // 2) for seq in range(1, 260)]
        summary = r9.verify(records)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["advancing_turns"], 129)

    def test_vitals_threat_kit_digest_mismatches_fail(self):
        cases = {
            "vitals.hp": lambda obs, o: obs["vitals"].update(hp=13),
            "threats differ": lambda obs, o: obs["threats"][0].update(x=42),
            "kit differs": lambda obs, o: obs["kit"].pop(0),
            "digest": lambda obs, o: obs["digest"].reverse(),
            "place differs": lambda obs, o: obs["place"].update(lost=True),
            "status.effects": lambda obs, o: obs["status"].update(effects=[]),
        }
        for fragment, fn in cases.items():
            with self.subTest(case=fragment):
                self.assertFailsWith(mutate(run(), 3, fn), fragment)

    def test_modal_notice_in_digest_is_tolerated(self):
        def modal(obs, o):
            o["modal_notices"] = ["You feel a presence."]
            obs["digest"] = obs["digest"][1:] + ["You feel a presence."]
        self.assertTrue(r9.verify(mutate(run(), 5, modal))["ok"])

    def test_ledger_hash_linkage(self):
        records = run()
        ledger = {rec["header"]["seq"]: {"frame_sha256": rec["request_sha256"]} for rec in records}
        self.assertTrue(r9.verify(records, ledger)["ok"])
        ledger[9]["frame_sha256"] = "0" * 64
        self.assertFailsWith(records, "ledger frame_sha256 differs", ledger=ledger)

    def test_tampered_request_text_fails(self):
        records = run()
        records[2]["request"] = records[2]["request"].replace('"hp": 14', '"hp": 15', 1)
        self.assertFailsWith(records, "request_sha256")


if __name__ == "__main__":
    unittest.main()
