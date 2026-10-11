import copy
import unittest
import tempfile
from pathlib import Path

from harness import wire
from harness.hybrid_policy import candidates, decision_gate, evidence_state, History
from harness.hybrid import select_operation, execute_selected, play
from tests.support import make_observation


def state():
    obs = make_observation()
    obs.update(kit=[{"id": "i1", "name": "jerky", "slot": None}],
               place={"name": "Joppa", "world_map": False, "lost": False},
               item_details=[{"id": "i1", "description": "Food.", "actions": ["eat"]}])
    obs["threats"] = []
    return {"ok": True, "run_id": "run", "seq": 1, "observation": obs}


class ObservationDetailTests(unittest.TestCase):
    def test_additive_details_accept_old_observations_and_visible_item_actions(self):
        wire.validate_observation(make_observation())
        wire.validate_observation(state()["observation"])

    def test_details_cannot_refer_to_absent_items_or_unsupported_actions(self):
        for field, value in [("id", "i99"), ("actions", ["wish"]), ("description", "x" * 8193)]:
            obs = state()["observation"]
            obs["item_details"][0][field] = value
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                wire.validate_observation(obs)


class HybridPolicyTests(unittest.TestCase):
    def test_world_map_excludes_local_macros(self):
        s = state()
        s["observation"]["place"]["world_map"] = True
        options = candidates(s, {"target": {"x": 3, "y": 4}, "horizon": 10})
        self.assertTrue(any(c["args"].get("action") == "move" for c in options))
        self.assertFalse(any(c["args"].get("action") in wire.MACRO_ACTIONS for c in options))

    def test_zone_change_does_not_reuse_the_old_local_target(self):
        s = state()
        s["observation"]["map"][3] = "." * 80
        old = {"target": {"x": 3, "y": 3}, "zone": "another-zone"}
        self.assertFalse(any(c["args"].get("action") == "goto" for c in candidates(s, old)))
        current = old | {"zone": s["observation"]["vitals"]["zone"]}
        self.assertTrue(any(c["args"].get("action") == "goto" for c in candidates(s, current)))

    def test_item_actions_are_bound_to_current_handles_and_native_affordances(self):
        options = candidates(state(), {})
        item_calls = [c["args"] for c in options if "item" in c["args"]]
        self.assertEqual(item_calls, [{"action": "eat", "item": "i1"}])

    def test_macros_are_excluded_near_hostiles(self):
        s = state()
        s["observation"]["threats"] = [dict(id="e1", name="snapjaw", wound="Perfect", x=1, y=1, hostile=True)]
        options = candidates(s, {"target": {"x": 2, "y": 2}})
        self.assertFalse(any(c["args"].get("action") in wire.MACRO_ACTIONS for c in options))

    def test_gate_uses_selected_probability_not_confidence(self):
        answer = {"type": "choice", "choice": "a", "probabilities": {"a": .5, "b": .3, "c": .2}, "confidence": .2}
        self.assertIsNone(decision_gate(answer, ["a", "b", "c"], .5))
        answer["probabilities"] = {"a": .49, "b": .31, "c": .2}
        self.assertEqual(decision_gate(answer, ["a", "b", "c"], .5), "low_probability")

    def test_malformed_distribution_never_authorizes_an_action(self):
        good = {"type": "choice", "choice": "a", "probabilities": {"a": .7, "b": .3}, "confidence": .4}
        for update in [{"choice": "invented"}, {"probabilities": {"a": 1.0}},
                       {"probabilities": {"a": float("nan"), "b": .3}},
                       {"probabilities": {"a": .2, "b": .8}},
                       {"probabilities": {"a": .9, "b": .9}}]:
            with self.subTest(update=update):
                self.assertEqual(decision_gate(good | update, ["a", "b"], .5), "invalid_jev_response")

    def test_evidence_has_no_audit_or_hidden_telemetry_and_computes_distances(self):
        s = state()
        s["telemetry"] = {"secret_oracle": True}
        s["observation"]["vitals"].update(x=10, y=10, hp=5, max_hp=20)
        s["observation"]["threats"] = [dict(id="e1", name="enemy", wound="Perfect", x=12, y=13, hostile=True)]
        evidence = evidence_state(s, {}, History())
        self.assertNotIn("telemetry", evidence)
        self.assertEqual(evidence["derived"]["hp_fraction"], .25)
        self.assertEqual(evidence["derived"]["creatures"][0]["distance"], 3)

    def test_map_marker_coordinates_count_control_glyphs_without_guessing_hidden_stairs(self):
        # Recorded surface maps contain legacy control glyphs. Visual column
        # counting mislocated the stairs at (58, 11) in the live planner.
        s = state()
        s["observation"]["vitals"].update(x=50, y=5)
        rows = [" " * 80 for _ in range(25)]
        rows[11] = "\x9d\t" * 29 + ">" + "." * 21
        rows[5] = "." * 50 + "@" + "." * 29
        rows[3] = "<" + " " * 79
        s["observation"]["map"] = rows
        before = copy.deepcopy(s)
        evidence = evidence_state(s, {}, History())
        self.assertEqual(evidence["derived"]["map_markers"], [
            {"glyph": "<", "x": 0, "y": 3, "distance": 50},
            {"glyph": ">", "x": 58, "y": 11, "distance": 8},
        ])
        self.assertEqual(s, before)
        self.assertEqual(evidence["current_observation"]["map"], rows)

    def test_history_detects_repeated_failure_and_resets_on_recovery(self):
        history = History()
        s = state()
        call = {"action": "move", "dir": "N"}
        for seq in range(1, 4):
            before = copy.deepcopy(s)
            before["seq"] = seq
            history.record(before, call, {"executed": False, "reason": "blocked", "turns_elapsed": 0}, s)
        self.assertEqual(history.problem(), "repeated_failure")
        history.reset()
        self.assertIsNone(history.problem())
        self.assertEqual(history.records, [])

    def test_conversation_history_distinguishes_continue_from_dismissal(self):
        s = state()
        s["modal"] = {"token": "dialog-1", "type": "conversation", "text": "I have work for you.",
                      "choices": [{"id": "option:0", "label": "..."}, {"id": "button:2", "label": "[Esc] Cancel"}]}
        options = candidates(s, {})
        self.assertEqual(options[0]["dialog_effect"], "Continue listening to this conversation")
        self.assertEqual(options[1]["dialog_effect"], "Close this conversation without selecting a dialogue branch")
        history = History()
        history.record_modal(s, options[1], {"ok": True, "accepted": True})
        evidence = evidence_state(s, {}, history)
        self.assertEqual(evidence["submitted_modal_responses"][0]["selected_label"], "[Esc] Cancel")
        self.assertEqual(evidence["submitted_modal_responses"][0]["dialog_text"], "I have work for you.")
        self.assertIsNone(history.problem())
        history.reset()
        self.assertEqual(history.modal_records, [])

    def test_history_keeps_actual_changes_without_repeating_unchanged_inventory(self):
        before, after = state(), state()
        before["observation"]["digest"] = ["The enemy hits you."]
        after["observation"]["digest"] = ["The enemy hits you.", "The enemy hits you."]
        after["seq"] = 2
        after["observation"]["vitals"]["x"] += 1
        history = History()
        history.record(before, {"action": "move", "dir": "E"}, {"executed": True}, after)
        record = history.records[-1]
        self.assertNotIn("kit", record["before"])
        self.assertNotIn("kit", record["after"])
        self.assertEqual(record["changes"], {})
        self.assertEqual(record["messages"], after["observation"]["digest"])
        consumed = copy.deepcopy(after)
        consumed["observation"]["kit"] = []
        history.record(after, {"action": "eat", "item": "i1"}, {"executed": True}, consumed)
        self.assertEqual(history.records[-1]["changes"]["kit"],
                         {"before": after["observation"]["kit"], "after": []})


class HybridControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_envelopes_escalate_instead_of_crashing(self):
        for response in ([], None, {"answers": []}, {"answers": None}):
            async def jev(request, response=response):
                return response

            async def claude(request):
                self.assertEqual(request["reason"], "invalid_jev_response")
                return {"goal": "Recover", "guidance": "Choose an available step", "horizon": 2,
                        "target": None, "selection": request["candidates"][0]["id"], "stop": False}

            with self.subTest(response=response):
                chosen, _, _ = await select_operation(state(), {"goal": "Explore"}, History(), jev, claude)
                self.assertIsNotNone(chosen)

    async def test_option_limit_hands_off_without_truncating_available_actions(self):
        s = state()
        s["modal"] = {"choices": [{"id": f"option:{i}", "label": f"Option {i}"} for i in range(256)]}

        async def jev(request):
            self.fail("Jev choice supports at most 255 options")

        async def claude(request):
            self.assertEqual(request["reason"], "too_many_candidates")
            self.assertEqual(len(request["candidates"]), 256)
            return {"goal": "Choose last option", "guidance": "Proceed", "horizon": 2,
                    "target": None, "selection": request["candidates"][-1]["id"], "stop": False}

        chosen, _, _ = await select_operation(s, {"goal": "Explore"}, History(), jev, claude)
        self.assertEqual(chosen["args"]["response"]["choice"], "option:255")

    async def test_action_limit_finishes_pending_modal_and_records_last_outcome(self):
        current = state()
        phase = "ready"
        calls = []

        async def call(name, **args):
            nonlocal current, phase
            calls.append(name)
            if name == "get_state":
                return copy.deepcopy(current)
            if name == "act":
                phase = "modal"
                current["modal"] = {"token": "test", "choices": [{"id": "option:0", "label": "Accept"}]}
                return {"ok": True, "pending": True, "op_id": 1}
            if name == "respond":
                phase = "done"
                current.pop("modal")
                current["seq"] = 2
                return {"ok": True, "accepted": True, "completed": True}
            if name == "wait_for_turn":
                return {"ok": True, "completed": phase == "done", "result": {"executed": True, "reason": "ok"}}
            self.fail(name)

        class TestModels:
            jev_calls = 0
            claude_calls = 0

            async def jev(self, request):
                self.jev_calls += 1
                ids = list(request["questions"]["action"]["criteria"])
                return {"answers": {"action": {"type": "choice", "choice": ids[0], "confidence": 1,
                        "probabilities": {key: float(key == ids[0]) for key in ids}}}}

            async def claude(self, request):
                self.claude_calls += 1
                return {"goal": "Test", "guidance": "Proceed", "horizon": 5, "target": None,
                        "selection": request["candidates"][0]["id"], "stop": False}

        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, TestModels(), Path(directory), max_actions=1)
            self.assertEqual(report["modal_responses"], 1)
            self.assertIsNone(report["pending_seq"])
            self.assertEqual(calls.count("act"), 1)
            self.assertTrue((Path(directory) / "outcome-00001.json").exists())

    async def test_low_probability_invokes_claude_and_executes_its_concrete_choice(self):
        calls = []

        async def jev(request):
            ids = list(request["questions"]["action"]["criteria"])
            return {"answers": {"action": {"type": "choice", "choice": ids[0],
                    "confidence": .01, "probabilities": dict.fromkeys(ids, 1 / len(ids))}}}

        async def claude(request):
            calls.append(request)
            return {"goal": "Move safely", "guidance": "Move north", "target": None,
                    "horizon": 5, "selection": request["candidates"][1]["id"], "stop": False}

        choice, plan, audit = await select_operation(state(), {"goal": "Explore"}, History(), jev, claude)
        self.assertEqual(choice, candidates(state(), {})[1])
        self.assertEqual(audit["escalation"], "low_probability")
        self.assertEqual(len(calls), 1)
        self.assertEqual(plan["horizon"], 5)

    async def test_high_probability_avoids_claude(self):
        async def jev(request):
            ids = list(request["questions"]["action"]["criteria"])
            return {"answers": {"action": {"type": "choice", "choice": ids[0],
                    "confidence": 1, "probabilities": {key: float(key == ids[0]) for key in ids}}}}

        async def claude(request):
            self.fail("Claude must not run for a confident current plan")

        choice, _, audit = await select_operation(state(), {"goal": "Explore"}, History(), jev, claude)
        self.assertIsNotNone(choice)
        self.assertEqual(audit["actor"], "jev")

    async def test_changed_state_is_not_executed(self):
        calls = []
        newer = state()
        newer["seq"] += 1

        async def call(name, **args):
            calls.append(name)
            return newer

        result = await execute_selected(call, state(), {"args": {"action": "wait"}})
        self.assertEqual(result["status"], "stale_selection")
        self.assertEqual(calls, ["get_state"])

    async def test_modal_selection_uses_current_token_without_new_act(self):
        s = state()
        s["modal"] = {"token": "live", "choices": [{"id": "option:0", "label": "Accept"}]}
        calls = []

        async def call(name, **args):
            calls.append((name, args))
            return s if name == "get_state" else {"ok": True, "completed": True}

        await execute_selected(call, s, candidates(s, {})[0])
        self.assertEqual(calls[-1], ("respond", {"expect_seq": 1, "token": "live", "response": {"choice": "option:0"}}))
