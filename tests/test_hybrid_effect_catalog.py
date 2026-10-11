import json
from pathlib import Path
import unittest

from harness.hybrid_hazards import assess_hazards
from harness.hybrid_strategy import BuildReview
from tests.test_hybrid import state


class EffectCatalogueTests(unittest.TestCase):
    def risk(self, effects, *, enemies=False, hp=20, details=(), liquids=()):
        obs = state()['observation']
        obs['vitals'].update(hp=hp, max_hp=20, x=10, y=10)
        obs['status'] = dict(effects=effects, effect_details=list(details), nearby_liquids=list(liquids))
        if enemies:
            obs['threats'] = [dict(id='e1', name='snapjaw', x=11, y=10, hostile=True)]
        return assess_hazards(obs)

    def test_observed_witchwood_healing_does_not_trigger_unknown_review(self):
        obs = state()['observation']
        review = BuildReview()
        review.accept(obs, {})
        obs['status'] = dict(effects=['healing'], effect_details=[
            dict(name='healing', description='Recovering 10 hit points over 2 turns.')])
        self.assertEqual(assess_hazards(obs)['unknown_effects'], [])
        self.assertEqual(assess_hazards(obs)['priority'], 0)
        self.assertIsNone(review.reason(obs))
        self.assertEqual(self.risk(['healing curse'])['unknown_effects'], ['healing curse'])

    def test_wiki_index_has_explicit_classification_including_conditional_effects(self):
        index = json.loads(Path('tests/fixtures/jev_effects_wiki_index.json').read_text())
        from harness.hybrid_hazards import EFFECTS
        self.assertEqual(set(index['names']) - set(EFFECTS), set())
        for name in index['names']:
            with self.subTest(name=name):
                self.assertTrue(EFFECTS[name]['sources'])
                self.assertTrue(EFFECTS[name]['category'])

    def test_damage_and_recovery_blocking_are_separate(self):
        for name in ['choking on ash', 'covered in spores', 'phase spider venom', 'syphoned']:
            with self.subTest(name=name):
                self.assertEqual(self.risk([name], hp=4)['priority'], 4)
        self.assertEqual(self.risk(['poisoned by gas'])['unknown_effects'], [])
        for name in ['poisoned', 'phase spider venom', 'ill']:
            with self.subTest(name=name):
                ids = [m['id'] for m in self.risk([name, 'healing'])['matches']]
                self.assertIn('recovery_suppressed', ids)

    def test_identical_damage_names_do_not_create_multiple_damage_sources(self):
        risk = self.risk(['bleeding', '{{r|bleeding}}'])
        self.assertNotIn('stacked_damage', [m['id'] for m in risk['matches']])

    def test_plasma_is_not_an_unknown_cosmetic_liquid(self):
        alone = self.risk(['coated in plasma'])
        self.assertEqual(alone['unknown_effects'], [])
        self.assertEqual(alone['priority'], 3)
        for effects in [['coated in plasma', 'burning'], ['coated in plasma', 'frozen']]:
            self.assertEqual(self.risk(effects)['priority'], 4)

    def test_context_promotes_confusion_mobility_and_defense_loss(self):
        for name in ['confused', 'blind', 'hobbled', 'cleaved', 'psionically cleaved']:
            with self.subTest(name=name):
                self.assertLess(self.risk([name])['priority'], self.risk([name], enemies=True)['priority'])
        self.assertEqual(self.risk(['stunned by gas'], enemies=True)['priority'], 4)
        self.assertEqual(self.risk(['terrified'])['priority'], 3)

    def test_disease_onsets_are_known_and_need_a_plan(self):
        for name in ['sore throat', 'stiff legs', 'itchy skin', 'mutating']:
            with self.subTest(name=name):
                risk = self.risk([name])
                self.assertEqual(risk['unknown_effects'], [])
                self.assertEqual(risk['priority'], 3)

    def test_dynamic_sitting_and_enclosure_names_retain_their_constraints(self):
        for name in ['sitting on a torture chair', 'enclosed in an iron maiden']:
            risk = self.risk([name], enemies=True)
            self.assertEqual(risk['unknown_effects'], [])
            self.assertEqual(risk['priority'], 4)

    def test_rare_liquids_and_wax_do_not_share_the_lava_rule(self):
        for name in ['entropic', 'magma-covered']:
            self.assertGreaterEqual(self.risk([name])['priority'], 3)
        self.assertLess(self.risk(['waxy'])['priority'], 3)
        self.assertEqual(self.risk(['waxy'])['unknown_effects'], [])
        self.assertLess(self.risk(['warm static-stained'])['priority'], 3)
        self.assertEqual(self.risk([], liquids=[dict(x=10, y=10, name='pool of neutron flux')])['priority'], 4)

    def test_equipment_effects_do_not_become_bodily_damage(self):
        obs = state()['observation']
        obs['kit'][0]['slot'] = 'body'
        obs['item_details'][0]['effect_details'] = [dict(name='rusted', description='Cannot be equipped.')]
        risk = assess_hazards(obs)
        self.assertGreaterEqual(risk['priority'], 3)
        self.assertNotIn('low_hp_damage', [m['id'] for m in risk['matches']])

    def test_carried_tonic_warns_about_allergy_without_inventing_exposure(self):
        obs = state()['observation']
        obs['kit'][0]['name'] = '{{C|salve injector}}'
        obs['character'] = dict(genotype='Mutated Human', mutations=[dict(name='Tonic Allergy (D)')])
        risk = assess_hazards(obs)
        self.assertEqual(risk['priority'], 0)
        self.assertEqual(risk['unknown_effects'], [])
        caution = risk['consumable_cautions'][0]
        self.assertEqual(caution['item_id'], obs['kit'][0]['id'])
        self.assertTrue(caution['tonic_allergy'])
        self.assertIn('adverse', caution['note'])
        obs['kit'][0]['name'] = 'small milky tube'
        self.assertEqual(assess_hazards(obs)['consumable_cautions'], [])

    def test_nectar_is_not_given_the_generic_adverse_reaction_warning(self):
        obs = state()['observation']
        obs['kit'][0]['name'] = "Eaters' nectar injector"
        caution = assess_hazards(obs)['consumable_cautions'][0]
        self.assertIn('exempt', caution['combination'])
        self.assertNotIn('Mutants can react adversely', caution['combination'])

    def test_unknown_liquid_component_is_retained_in_terrain(self):
        risk = self.risk([], liquids=[dict(x=11, y=10, name='pool of slimy alien-liquid')])
        self.assertIn('terrain: pool of slimy alien-liquid', risk['unknown_effects'])
        for name in ['pool of fresh water', 'pool of 500 drams of salty water', 'puddle of 1 dram of blood',
                     'puddle of 1 dram of dilute salt']:
            self.assertEqual(self.risk([], liquids=[dict(x=11, y=10, name=name)])['unknown_effects'], [])
