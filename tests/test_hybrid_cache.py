import copy
import json
import unittest

from harness import hybrid_models
from harness.hybrid_policy import History, candidates, evidence_state
from tests.test_hybrid_strategy import growth_state


def expand_payload(payload):
    envelope = json.loads(payload)
    if envelope.get("encoding") == "inline-v1":
        return envelope["data"]
    if envelope.get("encoding") != "shared-values-v1":
        return envelope
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$ref"}:
                return expand(envelope["definitions"][value["$ref"]])
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    return expand(envelope["data"])


class CacheInputTests(unittest.TestCase):
    def request(self):
        s = growth_state()
        return {"reason": "initial_build_review", "evidence": evidence_state(s, {}, History()),
                "candidates": candidates(s, {}, strategic=True), "jev_answer": None}

    def test_dynamic_growth_and_seq_do_not_change_reference_prefix(self):
        self.assertTrue(hasattr(hybrid_models, "claude_input"))
        before = self.request()
        saved = copy.deepcopy(before)
        system, payload = hybrid_models.claude_input(before)
        after = copy.deepcopy(before)
        after["reason"] = "character_changed"
        after["evidence"]["identity"]["seq"] += 1
        c = after["evidence"]["current_observation"]["character"]
        c["skill_points"] -= 50
        c["skill_catalog"][1].update(owned=True, eligible=False, requirements=["Strength 17 (met)"])
        after_system, after_payload = hybrid_models.claude_input(after)
        self.assertEqual(system, after_system)
        self.assertNotEqual(payload, after_payload)
        self.assertEqual(before, saved)

    def test_split_preserves_every_current_catalogue_field_and_candidate(self):
        self.assertTrue(hasattr(hybrid_models, "claude_input"))
        request = self.request()
        system, payload = hybrid_models.claude_input(request)
        reference = json.loads(system.split("\nREFERENCE_DATA_JSON\n", 1)[1])
        dynamic = expand_payload(payload)
        static = {e["id"]: e for e in reference["skill_definitions"]}
        current = dynamic["evidence"]["current_observation"]["character"]["skill_catalog"]
        rebuilt = [static[e["id"]] | e for e in current]
        self.assertEqual(rebuilt, request["evidence"]["current_observation"]["character"]["skill_catalog"])
        self.assertEqual(dynamic["candidates"], request["candidates"])
        self.assertEqual(reference["executor_contract"], request["evidence"]["executor_contract"])
        self.assertNotIn("executor_contract", dynamic["evidence"])

    def test_reference_changes_invalidate_prefix_and_old_observation_remains_valid(self):
        self.assertTrue(hasattr(hybrid_models, "claude_input"))
        request = self.request()
        before, _ = hybrid_models.claude_input(request)
        request["evidence"]["current_observation"]["character"]["skill_catalog"][1]["description"] = "Changed definition"
        after, _ = hybrid_models.claude_input(request)
        self.assertNotEqual(before, after)
        del request["evidence"]["current_observation"]["character"]
        _, payload = hybrid_models.claude_input(request)
        self.assertNotIn("character", expand_payload(payload)["evidence"]["current_observation"])

    def test_repeated_values_are_lossless_and_smaller_without_mutating_request(self):
        request = self.request()
        repeated = {"description": "Visible fact. " * 100, "requirements": ["Strength 17 (met)"]}
        request["evidence"]["repeated_facts"] = [repeated] * 8
        _, payload = hybrid_models.claude_input(request)
        expanded = expand_payload(payload)
        self.assertEqual(expanded["evidence"]["repeated_facts"], [repeated] * 8)
        self.assertLess(len(payload), len(json.dumps(expanded)))
        self.assertEqual(json.loads(payload)["encoding"], "shared-values-v1")

    def test_literal_reference_shaped_data_is_not_interpreted_as_encoding(self):
        request = self.request()
        request["evidence"]["literal"] = {"$ref": 0}
        _, payload = hybrid_models.claude_input(request)
        self.assertEqual(expand_payload(payload)["evidence"]["literal"], {"$ref": 0})
