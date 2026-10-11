import copy
import unittest

from harness.hybrid_policy import History, candidates
from tests.test_hybrid import state


class TrialRegressionTests(unittest.TestCase):
    def test_coating_names_do_not_trigger_growth_review_but_numeric_upgrades_do(self):
        from harness.hybrid_strategy import BuildReview
        from tests.test_hybrid_strategy import growth_state
        obs = growth_state()['observation']
        obs['kit'][1]['slot'] = 'right hand'
        detail = obs['item_details'][1]
        detail['comparison_name'] = 'steel sword +1'
        review = BuildReview()
        review.accept(obs, {})
        obs['kit'][1]['name'] = '{{r|bloody}} steel sword +1'
        detail['effect_details'] = [dict(name='bloody', description='')]
        self.assertIsNone(review.reason(obs))
        detail['comparison_name'] = 'steel sword +2'
        self.assertEqual(review.reason(obs), 'equipment_changed')

    def test_successful_combat_attempts_are_not_navigation_stalls(self):
        for kind in ('attack', 'move'):
            s = state()
            v = s['observation']['vitals']
            s['observation']['threats'] = [dict(id='e1', name='snapjaw', wound='Perfect',
                                               x=v['x'] + 1, y=v['y'], hostile=True)]
            history = History()
            for _ in range(6):
                history.record(s, {'action': kind, 'dir': 'E'}, {'executed': True}, s)
            with self.subTest(kind=kind):
                self.assertIsNone(history.problem())

    def test_enemy_wound_change_and_exploration_are_observed_progress(self):
        for key, value in [('threats', [dict(id='e1', name='snapjaw', wound='Wounded', x=1, y=1, hostile=True)]),
                           ('map', ['.' * 80] * 25)]:
            s, after = state(), state()
            after['observation'][key] = value
            history = History()
            history.record(s, {'action': 'attack', 'dir': 'E'}, {'executed': True}, after)
            self.assertTrue(history.records[-1]['changed'])

    def test_exact_observed_block_is_excluded_until_conditions_change(self):
        s = state()
        action = {'action': 'move', 'dir': 'NE'}
        history = History()
        after = copy.deepcopy(s)
        after['seq'] += 1
        history.record(s, action, {'executed': False, 'reason': 'blocked', 'turns_elapsed': 0}, after)
        self.assertNotIn(action, [c['args'] for c in candidates(after, {}, history=history)])
        # Different actions retain their IDs when the failed option is removed.
        originals = {c['id']: c for c in candidates(after, {})}
        for c in candidates(after, {}, history=history):
            self.assertEqual(c, originals[c['id']])
        after['observation']['vitals']['turn'] += 1
        self.assertIn(action, [c['args'] for c in candidates(after, {}, history=history)])

    def test_failed_combat_still_reports_failure_and_stationary_navigation_stalls(self):
        s = state()
        for result, expected in [({'executed': False}, 'repeated_failure'),
                                  ({'executed': True}, 'no_progress')]:
            history = History()
            for _ in range(3):
                history.record(s, {'action': 'move', 'dir': 'E'}, result, s)
            self.assertEqual(history.problem(), expected)


class HazardTests(unittest.TestCase):
    def test_native_additions_validate_without_rejecting_older_observations(self):
        from harness import wire
        obs = state()['observation']
        wire.validate_observation(obs)
        obs['status'] = dict(effects=[], food_water='', on_fire=True, frozen=False,
                             effect_details=[dict(name='bloody', description='Covered in blood.')],
                             nearby_liquids=[dict(x=1, y=1, name='slimy pool')])
        obs['item_details'][0]['effect_details'] = [dict(name='oily', description='')]
        wire.validate_observation(obs)
        obs['status']['on_fire'] = 'false'
        with self.assertRaises(wire.WireError):
            wire.validate_observation(obs)

    def test_player_fire_and_frozen_flags_are_not_lost_with_empty_effect_names(self):
        from harness.hybrid_hazards import assess_hazards
        obs = state()['observation']
        obs['status'] = dict(effects=[], food_water='', on_fire=True, frozen=True)
        self.assertEqual(assess_hazards(obs)['priority'], 4)

    def assess(self, effects, *, hp=20, enemies=False, liquids=(), details=()):
        from harness.hybrid_hazards import assess_hazards
        obs = state()['observation']
        obs['vitals'].update(hp=hp, max_hp=20, x=10, y=10)
        obs['status'] = {'effects': effects, 'food_water': 'Sated Quenched',
                         'effect_details': list(details), 'nearby_liquids': list(liquids)}
        if enemies:
            obs['threats'] = [dict(id='e1', name='snapjaw', wound='Perfect', x=11, y=10, hostile=True)]
        return assess_hazards(obs)

    def test_lost_is_a_constraint_without_hiding_other_unknown_effects(self):
        risk = self.assess(['lost', 'unfamiliar curse'])
        self.assertEqual(risk['unknown_effects'], ['unfamiliar curse'])
        self.assertEqual(risk.get('navigation_constraints'), ['no_fast_travel'])
        self.assertLess(risk['priority'], 2)

    def test_cosmetic_blood_and_slime_are_not_bleeding_or_slipping(self):
        risk = self.assess(['{{g|{{r|bloody}} {{slimy|slimy}}}}', '{{G|defensive stance}}'])
        self.assertLess(risk['priority'], 2)
        self.assertEqual(risk['unknown_effects'], [])

    def test_low_health_and_stacked_damage_promote_priority(self):
        normal = self.assess(['bleeding'])
        severe = self.assess(['bleeding', 'bleeding', 'poisoned'], hp=4)
        self.assertEqual(normal['priority'], 3)
        self.assertEqual(severe['priority'], 4)
        self.assertIn('stacked_damage', [r['id'] for r in severe['matches']])
        self.assertIn('low_hp_damage', [r['id'] for r in severe['matches']])

    def test_rest_is_not_offered_as_poison_recovery(self):
        s = state()
        s['observation']['status'] = {'effects': ['poisoned'], 'food_water': ''}
        self.assertFalse(any(c['args'].get('action') in ('rest', 'goto', 'explore') for c in candidates(s, {})))

    def test_immobility_with_hostile_is_critical(self):
        self.assertEqual(self.assess(['stuck'], enemies=True)['priority'], 4)
        self.assertLess(self.assess(['prone'])['priority'], self.assess(['prone'], enemies=True)['priority'])

    def test_liquid_contact_is_not_inferred_from_carried_container(self):
        from harness.hybrid_hazards import assess_hazards
        obs = state()['observation']
        obs['kit'][0]['name'] = 'lead-acid cell'
        self.assertEqual(assess_hazards(obs)['priority'], 0)
        self.assertGreaterEqual(self.assess(['acid-covered'])['priority'], 3)
        self.assertLess(self.assess(['acid-stained'])['priority'], 3)

    def test_fire_and_flammable_coating_combination(self):
        tar = self.assess(['tarry'])
        fire = self.assess(['burning', 'tarry'])
        self.assertLess(tar['priority'], 3)
        self.assertEqual(fire['priority'], 3)
        self.assertIn('fire_and_fuel', [r['id'] for r in fire['matches']])

    def test_prone_in_ooze_differs_from_ooze_in_nearby_cell(self):
        here = dict(x=10, y=10, name='pool of black ooze')
        next_cell = here | {'x': 11}
        current = self.assess(['prone'], liquids=[here])
        nearby = self.assess(['prone'], liquids=[next_cell])
        self.assertIn('prone_harmful_liquid', [r['id'] for r in current['matches']])
        self.assertNotIn('prone_harmful_liquid', [r['id'] for r in nearby['matches']])

    def test_unknown_is_visible_and_not_silently_safe(self):
        risk = self.assess(['unfamiliar curse'])
        self.assertEqual(risk['unknown_effects'], ['unfamiliar curse'])

    def test_hazard_escalates_once_until_actionable_context_changes(self):
        from harness.hybrid_strategy import BuildReview
        from tests.test_hybrid_strategy import growth_state
        obs = growth_state()['observation']
        review = BuildReview()
        review.accept(obs, {})
        obs['status'] = {'effects': ['bleeding'], 'food_water': ''}
        self.assertEqual(review.reason(obs), 'hazard_changed')
        review.accept(obs, {})
        self.assertIsNone(review.reason(obs))
        obs['vitals'].update(hp=1, max_hp=20)
        self.assertEqual(review.reason(obs), 'hazard_changed')

class UnknownLiquidRegressionTests(unittest.TestCase):
    def test_unclassified_component_is_not_hidden_by_known_slime(self):
        from harness.hybrid_hazards import assess_hazards
        obs = state()['observation']
        obs['status'] = dict(effects=['slimy alien-coated'], food_water='', effect_details=[
            dict(name='slimy alien-coated', description='Covered in 3 drams of an unknown mixture.')])
        self.assertIn('body: slimy alien-coated', assess_hazards(obs)['unknown_effects'])
