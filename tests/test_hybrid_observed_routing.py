import copy
import json
from pathlib import Path
import unittest

from harness.hybrid_policy import History, candidates
from harness.hybrid_routing import routing_threshold, tactical_scope
from harness.hybrid_strategy import BuildReview
from tests.test_hybrid_routing import navigation
from tests.test_character import character


class ObservedRoutingTests(unittest.TestCase):
    def test_actual_food_and_torch_changes_do_not_trigger_build_review(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/jev_gear_events.json").read_text())
        for event in ("food", "torch"):
            before, after = (fixture[f"{phase}_{event}"] | {"character": character()}
                             for phase in ("before", "after"))
            review = BuildReview()
            review.accept(before, {})
            with self.subTest(event=event):
                self.assertIsNone(review.pending_reason(after))
                upgraded = copy.deepcopy(after)
                upgraded["item_details"][0]["description"] += "\nImproved armor protection."
                self.assertEqual(review.pending_reason(upgraded), "equipment_changed")

    def test_avoidance_survives_visibility_loss_but_rejects_new_position_and_damage(self):
        s, _, review = navigation()
        obs = s["observation"]
        v = obs["vitals"]
        a = {"id": "e1", "name": "dreadroot", "x": v["x"] + 4, "y": v["y"], "hostile": True}
        b = a | {"id": "e2", "x": v["x"] + 5}
        obs["threats"] = [a, b]
        review.accept(obs, {})
        for threats in ([a], [], [b], [a, b]):
            obs["threats"] = threats
            self.assertFalse(review.avoidance_changed(obs))
        obs["threats"] = [a | {"x": a["x"] + 1, "name": "snapjaw"}]
        self.assertTrue(review.avoidance_changed(obs))
        obs["threats"] = []
        v["hp"] -= 1
        self.assertTrue(review.avoidance_changed(obs))

    def test_acknowledged_avoidance_step_gets_no_blanket_hostile_surcharge(self):
        for case, expected in (("separating", .5), ("approaching", .6), ("wall", .6),
                               ("low_hp", .7), ("unknown_effect", .7), ("fight", .6)):
            s, plan, _ = navigation()
            obs = s["observation"]
            v = obs["vitals"]
            plan["tactics"]["hostile_response"] = "avoid" if case != "fight" else "fight"
            obs["threats"] = [{"id": "e1", "name": "plant", "x": v["x"] - 3, "y": v["y"], "hostile": True}]
            direction = "W" if case == "approaching" else "E"
            if case == "wall":
                row = obs["map"][v["y"]]
                obs["map"][v["y"]] = row[:v["x"]+1] + "#" + row[v["x"]+2:]
            elif case == "low_hp":
                v["hp"] = 1
            elif case == "unknown_effect":
                obs["status"] = {"effects": ["unknown curse"]}
            selected = next(c for c in candidates(s, plan) if c["args"] == {"action": "move", "dir": direction})
            result = routing_threshold(s, plan, History(), selected, .5)
            with self.subTest(case=case):
                self.assertEqual(result["threshold"], expected)

    def test_safe_exploration_uses_narrow_updates_but_growth_and_new_threats_do_not(self):
        s, plan, review = navigation()
        plan["tactics"]["mode"] = "explore"
        self.assertTrue(tactical_scope("low_probability", s, plan, History(), review))
        self.assertFalse(tactical_scope("quest_progress_changed", s, plan, History(), review))
        s["observation"]["character"]["skill_points"] += 1
        self.assertFalse(tactical_scope("low_probability", s, plan, History(), review))
