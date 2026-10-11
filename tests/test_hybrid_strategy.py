import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from harness.hybrid import play, select_operation
from harness.hybrid_policy import History, candidates, evidence_state
from tests.test_hybrid import state
from tests.test_character import character


def growth_state():
    s = state()
    s["observation"]["character"] = character()
    s["observation"]["kit"].append({"id": "i2", "name": "steel sword", "slot": None})
    s["observation"]["item_details"].append({"id": "i2", "description": "A long blade.", "actions": ["equip"]})
    return s


class StrategicPolicyTests(unittest.TestCase):
    def test_avoidance_preserves_navigation_and_rechecks_changed_danger(self):
        from harness.hybrid_strategy import BuildReview, tactical_evidence
        obs = growth_state()["observation"]
        obs["threats"] = [{"id": "e1", "name": "plant", "x": 8, "y": 4, "hostile": True}]
        review = BuildReview()
        review.accept(obs, {})
        same = copy.deepcopy(obs)
        same["threats"][0]["id"] = "e9"
        same["vitals"]["x"] += 1
        self.assertFalse(review.avoidance_changed(same))
        for change in ("hp", "enemy", "zone", "position"):
            changed = copy.deepcopy(same)
            if change == "hp":
                changed["vitals"]["hp"] -= 1
            elif change == "enemy":
                changed["threats"].append({"id": "e2", "name": "snapjaw", "x": 9, "y": 4, "hostile": True})
            elif change == "position":
                changed["threats"][0]["x"] += 1
            else:
                changed["vitals"]["zone"] += "changed"
            self.assertEqual(review.avoidance_changed(changed), change != "position", change)
        s = growth_state()
        s["observation"] = obs
        plan = {"goal": "Return", "guidance": "Bypass the plant", "target": {"x": 70, "y": 4},
                "tactics": {"mode": "travel", "hostile_response": "avoid", "retreat_hp_fraction": .2}}
        evidence = tactical_evidence(evidence_state(s, plan, History()))
        self.assertEqual(evidence["derived"]["effective_tactics"]["mode"], "avoid")
        self.assertEqual(evidence["claude_plan"]["guidance"], plan["guidance"])
        self.assertEqual(evidence["claude_plan"]["target"], plan["target"])
        self.assertTrue(any("distance_to_plan_target" in c for c in candidates(s, plan)))

    def test_escalation_preserves_every_jev_candidate_id(self):
        s = growth_state()
        s["observation"]["item_details"][0]["actions"].append("equip")
        s["observation"]["ground"] = [{"id": "p1", "name": "stone", "x": 1, "y": 1}]
        lower = candidates(s, {})
        upper = candidates(s, {}, strategic=True)
        self.assertEqual(upper[:len(lower)], lower)

    def test_combat_candidates_do_not_reward_obsolete_travel_target(self):
        s = growth_state()
        s["observation"]["threats"] = [{"id": "e1", "name": "enemy", "x": 41, "y": 12, "hostile": True}]
        plan = {"target": {"x": 70, "y": 1}, "tactics": {"hostile_response": "fight"}}
        self.assertFalse(any("distance_to_plan_target" in c for c in candidates(s, plan)))

    def test_numeric_equipment_properties_are_not_erased(self):
        from harness.hybrid_strategy import BuildReview
        review = BuildReview()
        obs = growth_state()["observation"]
        obs["kit"][1]["name"] = "+1 sword"
        review.accept(obs, {})
        obs["kit"][1]["name"] = "+2 sword"
        self.assertEqual(review.reason(obs), "new_equipment_option")

    def test_tactical_candidates_cannot_spend_points_or_replace_equipment(self):
        options = candidates(growth_state(), {})
        self.assertFalse(any(c["args"].get("action") in ("equip", "learn_skill", "raise_attribute") for c in options))

    def test_claude_can_choose_only_current_eligible_growth_operations(self):
        self.assertNotIn("equip", [c["args"].get("action") for c in candidates(growth_state(), {})])
        options = candidates(growth_state(), {}, strategic=True)
        calls = [c["args"] for c in options]
        self.assertIn({"action": "learn_skill", "skill": "LongBlades_Test"}, calls)
        self.assertNotIn({"action": "learn_skill", "skill": "LongBlades"}, calls)
        self.assertIn({"action": "raise_attribute", "attribute": "Strength"}, calls)
        self.assertIn({"action": "equip", "item": "i2"}, calls)

    def test_growth_review_waits_for_safety_and_rechecks_actual_effect(self):
        self.assertIsNotNone(importlib.util.find_spec("harness.hybrid_strategy"))
        from harness.hybrid_strategy import BuildReview
        review = BuildReview()
        s = growth_state()
        obs = s["observation"]
        self.assertEqual(review.reason(obs), "initial_build_review")
        review.accept(obs, {"build_goal": "Sword and shield"})
        self.assertIsNone(review.reason(obs))
        after = copy.deepcopy(obs)
        after["character"]["level"] = 3
        after["character"]["skill_points"] += 94
        after["threats"] = [{"id": "e1", "name": "enemy", "x": 1, "y": 1, "hostile": True}]
        self.assertIsNone(review.reason(after))
        after["threats"] = []
        self.assertEqual(review.reason(after), "character_changed")
        review.accept(after, {"build_goal": "Sword and shield"})
        # A canceled equip leaves the observed context unchanged.
        self.assertIsNone(review.reason(after))
        after["kit"][1]["slot"] = "Hand"
        self.assertEqual(review.reason(after), "equipment_changed")

    def test_handle_renumbering_does_not_trigger_equipment_review(self):
        self.assertIsNotNone(importlib.util.find_spec("harness.hybrid_strategy"))
        from harness.hybrid_strategy import BuildReview
        review = BuildReview()
        obs = growth_state()["observation"]
        review.accept(obs, {})
        obs["kit"][1]["id"] = "i3"
        obs["item_details"][1]["id"] = "i3"
        self.assertIsNone(review.reason(obs))
        obs["kit"].append({"id": "i4", "name": "carbide sword", "slot": None})
        obs["item_details"].append({"id": "i4", "description": "A stronger long blade.", "actions": ["equip"]})
        self.assertEqual(review.reason(obs), "new_equipment_option")

    def test_jev_receives_confirmed_growth_and_policy_without_catalogue_or_old_selection(self):
        self.assertIsNotNone(importlib.util.find_spec("harness.hybrid_strategy"))
        from harness.hybrid_strategy import tactical_evidence
        s = growth_state()
        plan = {"goal": "Explore", "guidance": "Always move east", "memory": "Killed 999 enemies", "selection": "c2",
                "tactics": {"mode": "travel", "hostile_response": "fight", "retreat_hp_fraction": .3,
                            "heal_hp_fraction": .5}, "target": {"x": 70, "y": 1}}
        s["observation"]["threats"] = [{"id": "e1", "name": "enemy", "x": 41, "y": 12, "hostile": True}]
        source = evidence_state(s, plan, History())
        actual = tactical_evidence(source)
        self.assertNotIn("skill_catalog", actual["current_observation"]["character"])
        self.assertNotIn("memory", actual["claude_plan"])
        self.assertNotIn("selection", actual["claude_plan"])
        self.assertNotIn("guidance", actual["claude_plan"])
        self.assertIsNone(actual["claude_plan"]["target"])
        self.assertEqual(actual["derived"]["effective_tactics"]["mode"], "combat")
        self.assertEqual(actual["current_observation"]["character"]["owned_skills"], ["LongBlades"])
        self.assertIn("skill_catalog", source["current_observation"]["character"])


class StrategicControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_high_probability_attack_cannot_override_retreat_threshold(self):
        s = growth_state()
        s["observation"]["vitals"].update(hp=8, max_hp=27, x=10, y=10)
        s["observation"]["threats"] = [{"id": "e1", "name": "enemy", "x": 11, "y": 10, "hostile": True}]
        async def jev(request):
            criteria = request["questions"]["action"]["criteria"]
            chosen = next(key for key, value in criteria.items() if value["args"].get("action") == "attack")
            return {"answers": {"action": {"type": "choice", "choice": chosen, "confidence": .99,
                    "probabilities": {key: float(key == chosen) for key in criteria}}}}
        async def claude(request):
            self.assertEqual(request["reason"], "tactical_policy_conflict")
            selected = next(c for c in request["candidates"] if c["args"] == {"action": "move", "dir": "W"})
            return {"goal": "Retreat", "guidance": "Retreat west", "target": None, "horizon": 2,
                    "selection": selected["id"], "stop": False}
        chosen, _, audit = await select_operation(s, {"goal": "Fight", "tactics": {
            "hostile_response": "fight", "retreat_hp_fraction": .4}}, History(), jev, claude)
        self.assertEqual(chosen["args"], {"action": "move", "dir": "W"})
        self.assertEqual(audit["actor"], "claude")

    async def test_native_growth_modal_and_confirmed_change_stay_with_claude(self):
        current = growth_state()
        requests = []
        phase = "ready"
        async def call(name, **args):
            nonlocal phase
            if name == "get_state":
                return copy.deepcopy(current)
            if name == "act":
                if args["action"] == "learn_skill":
                    phase = "modal"
                    current["modal"] = {"token": "purchase", "choices": [{"id": "yes", "label": "Yes"}]}
                else:
                    phase = "done"
                    current["seq"] += 1
                return {"ok": True, "pending": True, "op_id": args["expect_seq"]}
            if name == "respond":
                self.assertEqual(args["response"], {"choice": "yes"})
                current.pop("modal")
                growth = current["observation"]["character"]
                growth["owned_skills"].append("LongBlades_Test")
                growth["skill_points"] -= 50
                growth["skill_catalog"][1].update(owned=True, eligible=False)
                current["seq"] += 1
                phase = "done"
                return {"ok": True, "accepted": True, "completed": True}
            if name == "wait_for_turn":
                return {"ok": True, "completed": phase == "done", "result": {"executed": True, "reason": "purchased"}}
            self.fail(name)
        class TestModels:
            jev_calls = 0
            claude_calls = 0
            async def jev(self, request):
                raise AssertionError("All three event-driven steps belong to Claude")
            async def claude(self, request):
                self.claude_calls += 1
                requests.append(request)
                options = request["candidates"]
                chosen = next(c for c in options if
                              c["args"].get("skill") == "LongBlades_Test") if self.claude_calls == 1 else options[0]
                return {"goal": "Grow", "guidance": "Apply confirmed growth", "target": None, "horizon": 12,
                        "selection": chosen["id"], "stop": False}
        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, TestModels(), Path(directory), max_actions=2)
        self.assertEqual([r["reason"] for r in requests],
                         ["initial_build_review", "strategic_action_modal", "character_changed"])
        observed = requests[-1]["evidence"]["current_observation"]["character"]
        self.assertEqual(observed["skill_points"], 44)
        self.assertIn("LongBlades_Test", observed["owned_skills"])
        self.assertEqual(report["modal_responses"], 1)
        self.assertIsNone(report["pending_seq"])

    async def test_replan_on_hostile_policy_is_enforced_before_jev(self):
        s = growth_state()
        s["observation"]["threats"] = [{"id": "e1", "name": "enemy", "x": 1, "y": 1, "hostile": True}]
        async def jev(request):
            self.fail("The upper-level policy explicitly requested replanning")
        async def claude(request):
            self.assertEqual(request["reason"], "hostile_requires_replan")
            return {"goal": "Fight", "guidance": "Fight", "target": None, "horizon": 12,
                    "selection": request["candidates"][0]["id"], "stop": False}
        _, _, audit = await select_operation(s, {"goal": "Travel", "tactics": {"hostile_response": "replan"}},
                                             History(), jev, claude)
        self.assertEqual(audit["actor"], "claude")

    async def test_acknowledged_avoidance_uses_jev_but_never_attacks(self):
        from harness.hybrid_strategy import BuildReview
        s = growth_state()
        v = s["observation"]["vitals"]
        s["observation"]["threats"] = [{"id": "e1", "name": "plant", "x": v["x"] + 1,
                                          "y": v["y"], "hostile": True}]
        review = BuildReview()
        review.accept(s["observation"], {})
        plan = {"goal": "Return", "tactics": {"hostile_response": "avoid"}}
        picked = "wait"
        requests = []
        async def jev(request):
            options = request["questions"]["action"]["criteria"]
            choice = next(k for k, c in options.items() if c["args"].get("action") == picked)
            return {"answers": {"action": {"type": "choice", "choice": choice, "confidence": 1,
                    "probabilities": {k: float(k == choice) for k in options}}}}
        async def claude(request):
            requests.append(request["reason"])
            return {"goal": "Reassess", "guidance": "Proceed", "target": None, "horizon": 12,
                    "selection": None, "stop": False}
        _, _, audit = await select_operation(s, plan, History(), jev, claude, review=review)
        self.assertEqual(audit["actor"], "jev")
        picked = "attack"
        await select_operation(s, plan, History(), jev, claude, review=review)
        s["observation"]["vitals"]["hp"] -= 1
        await select_operation(s, plan, History(), jev, claude, review=review)
        self.assertEqual(requests, ["tactical_policy_conflict", "avoidance_context_changed"])

    async def test_growth_choice_is_claude_only_and_returned_without_a_jev_call(self):
        self.assertNotIn("equip", [c["args"].get("action") for c in candidates(growth_state(), {})])

        async def jev(request):
            self.fail("A growth review belongs to Claude")

        async def claude(request):
            chosen = next(c for c in request["candidates"] if c["args"].get("skill") == "LongBlades_Test")
            return {"goal": "Grow", "guidance": "Learn this skill", "target": None, "horizon": 12,
                    "selection": chosen["id"], "stop": False}

        selected, _, audit = await select_operation(growth_state(), {}, History(), jev, claude,
                                                     force_reason="initial_build_review")
        self.assertEqual(selected["args"], {"action": "learn_skill", "skill": "LongBlades_Test"})
        self.assertEqual(audit["actor"], "claude")
