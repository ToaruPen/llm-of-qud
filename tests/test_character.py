import copy
import json
import unittest

from harness import wire
from tests.support import make_observation, RUN_ID


def character():
    return {
        "level": 2, "xp": 250, "next_level_xp": 750, "skill_points": 94, "attribute_points": 1,
        "attributes": {name: {"value": 18, "base": 18} for name in
                       ("Strength", "Agility", "Toughness", "Intelligence", "Willpower", "Ego")},
        "owned_skills": ["LongBlades"], "catalog_truncated": False,
        "skill_catalog": [
            {"id": "LongBlades", "name": "Long Blades", "kind": "skill", "parent_id": None,
             "cost": 100, "description": "Use long blades.", "requirements": [], "owned": True, "eligible": False},
            {"id": "LongBlades_Test", "name": "Practice", "kind": "power", "parent_id": "LongBlades",
             "cost": 50, "description": "Improve accuracy.", "requirements": ["Strength 17"],
             "owned": False, "eligible": True},
        ],
    }


class CharacterWireTests(unittest.TestCase):
    def test_optional_public_mutations_are_preserved_and_bounded(self):
        from harness.hybrid_strategy import BuildReview, tactical_evidence
        from harness.hybrid_policy import History, evidence_state
        from tests.test_hybrid_strategy import growth_state
        s = growth_state()
        c = s["observation"]["character"]
        c.update(genotype="Mutated Human", subtype="Watervine Farmer", mutation_points=2,
                 mutations_truncated=False, mutations=[{"name": "Carapace", "level": 1,
                 "description": "You are covered in a shell.", "level_text": "+3 AV", "defect": False}])
        wire.validate_observation(s["observation"])
        review = BuildReview()
        review.accept(s["observation"], {})
        c["mutations"][0]["level"] = 2
        self.assertEqual(review.pending_reason(s["observation"]), "character_changed")
        lower = tactical_evidence(evidence_state(s, {}, History()))
        self.assertEqual(lower["current_observation"]["character"]["mutations"], c["mutations"])
        for change in (lambda x: x.pop("mutation_points"),
                       lambda x: x["mutations"][0].update(description="x" * 4097),
                       lambda x: x["mutations"][0].update(defect="false")):
            invalid = copy.deepcopy(c)
            change(invalid)
            with self.assertRaises(wire.WireError):
                wire.validate_character(invalid)

    def test_additive_public_growth_data_preserves_old_observations(self):
        wire.validate_observation(make_observation())
        obs = make_observation() | {"character": character()}
        self.assertEqual(wire.validate_observation(obs), obs)

    def test_growth_commands_are_registered_and_only_use_their_own_arguments(self):
        self.assertIn("learn_skill", wire.ACTIONS)
        self.assertIn("raise_attribute", wire.ACTIONS)
        self.assertEqual(wire.normalize_decision("learn_skill", None, 20, skill="LongBlades_Test"),
                         ("learn_skill", None, 1))
        self.assertEqual(wire.normalize_decision("raise_attribute", None, 20, attribute="Strength"),
                         ("raise_attribute", None, 1))
        for args in ({"action": "wait", "skill": "LongBlades_Test"},
                     {"action": "learn_skill", "skill": "LongBlades_Test", "attribute": "Strength"},
                     {"action": "raise_attribute", "attribute": "HP"}):
            with self.subTest(args=args), self.assertRaises(wire.WireError):
                wire.normalize_decision(dir=None, budget=20, **args)

    def test_growth_frame_and_ledger_keep_exact_scoped_fields(self):
        self.assertIn("learn_skill", wire.ACTIONS)
        frame = json.loads(wire.serialize_decision(RUN_ID, 7, "learn_skill", None, 1, skill="LongBlades_Test"))
        self.assertEqual(frame["skill"], "LongBlades_Test")
        self.assertNotIn("attribute", frame)
        self.assertNotIn("skill", json.loads(wire.serialize_decision(RUN_ID, 7, "wait", None, 1)))

    def test_live_growth_validation_rejects_unseen_owned_or_unaffordable_options(self):
        self.assertTrue(hasattr(wire, "validate_observed_growth"))
        obs = make_observation() | {"character": character()}
        wire.validate_observed_growth("learn_skill", "LongBlades_Test", None, obs)
        for skill in ("HiddenClass", "LongBlades"):
            with self.subTest(skill=skill), self.assertRaises(wire.WireError):
                wire.validate_observed_growth("learn_skill", skill, None, obs)
        for field, value in (("eligible", False), ("cost", 95), ("cost", -999)):
            changed = copy.deepcopy(obs)
            changed["character"]["skill_catalog"][1][field] = value
            with self.subTest(field=field), self.assertRaises(wire.WireError):
                wire.validate_observed_growth("learn_skill", "LongBlades_Test", None, changed)
        obs["character"]["attribute_points"] = 0
        with self.assertRaises(wire.WireError):
            wire.validate_observed_growth("raise_attribute", None, "Strength", obs)

    def test_catalogue_rejects_ambiguous_ids_and_unbounded_descriptions(self):
        self.assertIn("character", wire.OPTIONAL_OBSERVATION_KEYS)
        for change in (lambda c: c["skill_catalog"].append(copy.deepcopy(c["skill_catalog"][0])),
                       lambda c: c["skill_catalog"][0].update(description="x" * 4097)):
            obs = make_observation() | {"character": character()}
            change(obs["character"])
            with self.assertRaises(wire.WireError):
                wire.validate_observation(obs)
