import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.hybrid import play, select_operation
from harness.hybrid_models import Models, claude_input
from harness.hybrid_policy import History, candidates, evidence_state
from harness.hybrid_routing import route_event, tactical_scope
from harness.hybrid_strategy import BuildReview
from tests.test_hybrid_cache import expand_payload
from tests.test_hybrid_strategy import growth_state


def navigation():
    s = growth_state()
    plan = {"goal": "Return to the stairs", "guidance": "Travel to the known stairs",
            "memory": "Corpse retained; return to Mehmet", "target": {"x": 50, "y": 12},
            "zone": s["observation"]["vitals"]["zone"], "horizon": 24,
            "automatic_goto": True, "selection": None, "stop": False,
            "strategy": {"build_goal": "Long blades", "next_upgrades": "Hold points", "resource_policy": "Save healing"},
            "tactics": {"mode": "travel", "hostile_response": "fight",
                        "retreat_hp_fraction": .3, "heal_hp_fraction": .6}}
    review = BuildReview()
    review.accept(s["observation"], plan["strategy"])
    return s, plan, review


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_safe_engine_stop_and_arrival_are_narrow_but_danger_is_not(self):
        for result, expected in (("ENGINE_STOP", "navigation_interrupted"), ("ARRIVED", "target_reached"),
                                 ("NEW_HOSTILE", "navigation_interrupted")):
            s, plan, review = navigation()
            after = copy.deepcopy(s)
            after["seq"] += 1
            after["observation"]["vitals"]["x"] = 50
            history = History()
            history.record(s, {"action": "goto", "target": plan["target"]},
                           {"executed": True, "reason": result}, after)
            self.assertEqual(route_event(after, history, review), expected)
            self.assertEqual(tactical_scope(expected, after, plan, history, review), result != "NEW_HOSTILE")

    def test_lost_change_is_navigation_review_not_unknown_danger(self):
        s, plan, review = navigation()
        s["observation"]["place"]["lost"] = True
        s["observation"]["status"] = {"effects": ["lost"], "effect_details": [
            {"name": "lost", "description": "Can't fast travel."}]}
        self.assertEqual(route_event(s, History(), review), "navigation_constraints_changed")
        self.assertTrue(tactical_scope("navigation_constraints_changed", s, plan, History(), review))
        review.accept(s["observation"], plan["strategy"])
        self.assertIsNone(route_event(s, History(), review))
        self.assertTrue(any(c["args"].get("action") == "goto" for c in candidates(s, plan)))

    def test_verified_events_outlive_recent_history_and_explicit_resume(self):
        s, plan, review = navigation()
        s["modal"] = {"token": "offer", "type": "conversation", "text": "Another artifact!", "choices": [
            {"id": "accept", "label": "If I must. [Accept Quest]"}, {"id": "cancel", "label": "[Esc] Cancel"}]}
        history = History()
        cancel = {"label": "[Esc] Cancel", "args": {"response": {"choice": "cancel"}}}
        history.record_modal(s, cancel, {"accepted": True})
        del s["modal"]
        for i in range(12):
            before = copy.deepcopy(s)
            s["seq"] += 1
            if i == 0:
                s["observation"]["goals"] = [{"title": "Observed quest", "steps": []}]
            history.record(before, {"action": "move", "dir": "E"}, {"executed": True}, s)
        evidence = evidence_state(s, plan, history, review)
        events = evidence.get("verified_events", [])
        self.assertTrue(any(e["kind"] == "quest_dialogue" and e["selected_label"] == "[Esc] Cancel" for e in events))
        self.assertTrue(any(e["kind"] == "quest_log_changed" for e in events))
        restored = History(events=events)
        self.assertEqual(evidence_state(s, plan, restored)["verified_events"], events)
        self.assertTrue(all("source" in e for e in events))

    async def test_quest_and_artifact_commitments_always_belong_to_claude(self):
        for title, label in (("", "If I must. [Accept Quest]"), ("", "Live and drink. [Complete Quest]"),
                             ("", "Here is your knickknack. [give artifact]"),
                             ("Choose an artifact to give.", "weird artifact")):
            s, plan, review = navigation()
            s["modal"] = {"token": "offer", "type": "popup" if title else "conversation", "title": title,
                          "text": "Go fetch me another!", "choices": [{"id": "yes", "label": label},
                          {"id": "cancel", "label": "[Esc] Cancel"}]}
            async def jev(request):
                return {"answers": {"action": {"type": "choice", "choice": "c1", "confidence": .99,
                        "probabilities": {"c0": .06, "c1": .94}}}}
            async def claude(request, plan=plan):
                self.assertEqual(request["reason"], "strategic_dialogue")
                self.assertEqual(request["decision_scope"], "strategic")
                return plan | {"selection": "c0"}
            with self.subTest(label=label):
                chosen, _, audit = await select_operation(s, plan, History(), jev, claude, review=review)
                self.assertEqual(chosen["args"], {"response": {"choice": "yes"}})
                self.assertEqual(audit["actor"], "claude")

    def test_dialogue_history_preserves_options_that_were_not_selected(self):
        s, _, _ = navigation()
        s["modal"] = {"token": "offer", "type": "conversation", "text": "Another!", "choices": [
            {"id": "accept", "label": "If I must. [Accept Quest]"}, {"id": "cancel", "label": "[Esc] Cancel"}]}
        history = History()
        history.record_modal(s, {"label": "[Esc] Cancel", "args": {"response": {"choice": "cancel"}}},
                             {"accepted": True})
        self.assertEqual(history.modal_records[0].get("offered_choices"), s["modal"]["choices"])

    async def test_resume_keeps_memory_but_requires_fresh_upper_review(self):
        s, plan, _ = navigation()
        original = copy.deepcopy(plan)
        requests = []
        class ResumeModels:
            claude_calls = 0
            jev_calls = 0
            async def claude(self, request):
                self.claude_calls += 1
                requests.append(request)
                return plan | {"selection": None, "stop": True}
            async def jev(self, request):
                raise AssertionError("A resumed permission must be reviewed before use")
        async def call(name, **args):
            self.assertEqual(name, "get_state")
            return s
        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, ResumeModels(), Path(directory), initial_plan=plan)
        self.assertEqual(requests[0]["reason"], "initial_build_review")
        self.assertEqual(requests[0]["evidence"]["claude_plan"]["memory"], original["memory"])
        self.assertEqual(report["accepted_actions"], 0)
        self.assertEqual(plan, original)

    async def test_arrival_consumes_permission_even_after_a_step_away(self):
        s, plan, review = navigation()
        before = copy.deepcopy(s)
        before["observation"]["vitals"]["x"] = 49
        s["observation"]["vitals"]["x"] = 50
        s["seq"] = 2
        history = History()
        history.record(before, {"action": "goto", "target": plan["target"], "budget": 12},
                       {"executed": True, "reason": "ARRIVED"}, s)
        after = copy.deepcopy(s)
        after["seq"] = 3
        after["observation"]["vitals"]["y"] = 11
        history.record(s, {"action": "move", "dir": "N"}, {"executed": True, "reason": "ok"}, after)
        async def jev(request):
            options = request["questions"]["action"]["criteria"]
            selected = next(k for k, c in options.items() if c["args"] == {"action": "move", "dir": "N"})
            return {"answers": {"action": {"type": "choice", "choice": selected, "confidence": .9,
                    "probabilities": {k: float(k == selected) for k in options}}}}
        async def claude(request):
            self.fail("A next step after arrival does not itself require a new plan")
        chosen, _, audit = await select_operation(after, plan, history, jev, claude, review=review)
        self.assertEqual(chosen["args"], {"action": "move", "dir": "N"})
        self.assertEqual(audit["actor"], "jev")
        # A later upper-level decision may explicitly authorize revisiting the cell.
        chosen, _, audit = await select_operation(after, plan | {"issued_seq": 3}, history, jev, claude, review=review)
        self.assertEqual(chosen["args"]["action"], "goto")
        self.assertEqual(audit["actor"], "plan_executor")

    def test_drinking_changes_volume_without_inventing_an_equipment_upgrade(self):
        s, _, _ = navigation()
        obs = s["observation"]
        obs["kit"][1]["name"] = "waterskin [30 drams of fresh water]"
        detail = obs["item_details"][1]
        detail.update(comparison_name="waterskin [30 drams of fresh water]", description="A goat's bladder.\nWeight: 8 lbs.")
        review = BuildReview()
        review.accept(obs, {})
        obs["kit"][1]["name"] = "waterskin [29 drams of fresh water]"
        detail["comparison_name"] = "waterskin [29 drams of fresh water]"
        self.assertIsNone(review.reason(obs))
        detail["comparison_name"] = "waterskin [29 drams of acid]"
        self.assertEqual(review.reason(obs), "new_equipment_option")

    async def test_repeated_conversation_branch_escalates_even_at_high_probability(self):
        s, plan, review = navigation()
        history = History()
        for number, node in enumerate(("A", "B", "A", "B")):
            s["modal"] = {"token": str(number), "type": "conversation", "text": node,
                          "choices": [{"id": "again", "label": "Repeat"}, {"id": "next", "label": "Next"}]}
            history.record_modal(s, {"label": "Repeat", "args": {"response": {"choice": "again"}}},
                                 {"ok": True, "accepted": True})
        s["modal"] = s["modal"] | {"token": "4", "text": "A"}
        async def jev(request):
            options = request["questions"]["action"]["criteria"]
            return {"answers": {"action": {"type": "choice", "choice": "c0", "confidence": .99,
                    "probabilities": {k: float(k == "c0") for k in options}}}}
        async def claude(request):
            self.assertEqual(request["reason"], "repeated_dialogue")
            return plan | {"selection": "c1"}
        chosen, _, audit = await select_operation(s, plan, history, jev, claude, review=review)
        self.assertEqual(chosen["args"], {"response": {"choice": "next"}})
        self.assertEqual(audit["actor"], "claude")

    async def test_authorized_goto_continues_after_budget_without_model_call(self):
        s, plan, review = navigation()
        before = copy.deepcopy(s)
        before["observation"]["vitals"]["x"] = 28
        s["seq"] = 2
        history = History()
        history.record(before, {"action": "goto", "target": plan["target"], "budget": 12},
                       {"executed": True, "reason": "BUDGET", "steps": 12, "turns_elapsed": 12}, s)
        async def forbidden(request):
            self.fail("A progressing authorized native route does not require a fresh model decision")
        chosen, _, audit = await select_operation(s, plan, history, forbidden, forbidden, review=review)
        self.assertEqual(chosen["args"], {"action": "goto", "target": {"x": 50, "y": 12}, "budget": 12})
        self.assertEqual(audit["actor"], "plan_executor")

    async def test_goto_permission_never_overrides_changed_safety_or_expiry(self):
        for change in ("enemy", "damage", "effect", "build", "expired", "stuck"):
            s, plan, review = navigation()
            before = copy.deepcopy(s)
            s["seq"] = 2
            s["observation"]["vitals"]["x"] += 1
            reason = "BUDGET"
            forced = None
            if change == "enemy":
                s["observation"]["threats"] = [{"id": "e1", "name": "snapjaw", "x": 42, "y": 12, "hostile": True}]
            elif change == "damage":
                s["observation"]["vitals"]["hp"] -= 1
            elif change == "effect":
                s["observation"]["status"] = {"effects": ["Unknown curse"]}
            elif change == "build":
                s["observation"]["character"]["skill_points"] += 100
            elif change == "expired":
                forced = "plan_expired"
            else:
                reason = "STUCK"
            history = History()
            history.record(before, {"action": "goto", "target": plan["target"], "budget": 12},
                           {"executed": True, "reason": reason, "steps": 1}, s)
            async def jev(request):
                self.fail("Changed route conditions must return to Claude")
            async def claude(request, plan=plan):
                return plan | {"selection": None}
            with self.subTest(change=change):
                _, _, audit = await select_operation(s, plan, history, jev, claude,
                                                     force_reason=forced, review=review)
                self.assertEqual(audit["actor"], "claude")

    async def test_context_threshold_relaxes_only_clear_goal_directed_steps(self):
        for case, expected_actor in (("safe", "jev"), ("wall", "claude"), ("enemy", "claude"),
                                     ("low_hp", "claude"), ("no_target", "claude")):
            s, plan, review = navigation()
            plan["automatic_goto"] = False
            if case == "wall":
                row = s["observation"]["map"][12]
                s["observation"]["map"][12] = row[:41] + "±" + row[42:]
            elif case == "enemy":
                s["observation"]["threats"] = [{"id": "e1", "name": "plant", "x": 60, "y": 12, "hostile": True}]
            elif case == "low_hp":
                s["observation"]["vitals"]["hp"] = 5
            elif case == "no_target":
                plan["target"] = None
            async def jev(request):
                criteria = request["questions"]["action"]["criteria"]
                selected = next(k for k, c in criteria.items() if c["args"] == {"action": "move", "dir": "E"})
                return {"answers": {"action": {"type": "choice", "choice": selected, "confidence": .99,
                        "probabilities": {k: .4 if k == selected else .6 / (len(criteria)-1) for k in criteria}}}}
            async def claude(request, plan=plan):
                return plan | {"selection": None}
            with self.subTest(case=case):
                _, _, audit = await select_operation(s, plan, History(), jev, claude, review=review)
                self.assertEqual(audit["actor"], expected_actor)
                self.assertEqual(audit["routing"]["base_threshold"], .5)

    def test_counts_distinguish_native_stop_from_following_visibility(self):
        s, _, _ = navigation()
        history = History()
        for reason in ("NEW_HOSTILE", "NEW_HOSTILE", "BUDGET"):
            history.record(s, {"action": "goto"}, {"executed": True, "reason": reason}, s)
        verified = evidence_state(s, {}, history)["verified_session"]
        self.assertEqual(verified["macro_stop_counts"], {"NEW_HOSTILE": 2, "BUDGET": 1})
        self.assertEqual(verified["hostile_stops_without_following_visible_enemy"], 2)


class TacticalPlanTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        s, plan, review = navigation()
        return {"reason": "low_probability", "decision_scope": "tactical",
                "evidence": evidence_state(s, plan, History(), review),
                "candidates": candidates(s, plan), "jev_answer": None}

    def test_tactical_input_omits_catalogue_but_retains_observed_build_and_hazards(self):
        request = self.request()
        original = copy.deepcopy(request)
        system, payload = claude_input(request)
        current = expand_payload(payload)["evidence"]["current_observation"]
        self.assertNotIn("skill_catalog", current["character"])
        self.assertEqual(current["character"]["owned_skills"], original["evidence"]["current_observation"]["character"]["owned_skills"])
        self.assertEqual(request, original)
        reference = json.loads(system.split("\nREFERENCE_DATA_JSON\n", 1)[1])
        self.assertEqual(reference["skill_definitions"], [])

    async def test_tactical_patch_preserves_strategy_and_uses_medium_effort(self):
        request = self.request()
        previous = copy.deepcopy(request["evidence"]["claude_plan"])
        update = {"goal": "Reach the newly observed elder", "guidance": "Continue east", "target": {"x": 51, "y": 12}, "automatic_goto": True,
                  "horizon": 12, "selection": request["candidates"][0]["id"], "stop": False}
        async def transport(command, payload, record):
            self.assertEqual(command[command.index("--effort")+1], "medium")
            self.assertEqual(command[command.index("--model")+1], "opus")
            self.assertEqual(record['requested_model'], 'opus')
            schema = json.loads(command[command.index("--json-schema")+1])
            self.assertNotIn("strategy", schema["properties"])
            return {"structured_output": update}
        with tempfile.TemporaryDirectory() as directory, patch("harness.hybrid_models.run_cli", transport):
            models = Models(Path(directory), "unused", "claude")
            result = await models.claude(request)
        self.assertEqual(result, previous | update)
        self.assertEqual(request["evidence"]["claude_plan"], previous)

    async def test_tactical_output_cannot_overwrite_build_policy(self):
        request = self.request()
        async def transport(command, payload, record):
            return {"structured_output": request["evidence"]["claude_plan"]}
        with tempfile.TemporaryDirectory() as directory, patch("harness.hybrid_models.run_cli", transport):
            with self.assertRaises(ValueError):
                await Models(Path(directory), "unused", "claude").claude(request)
