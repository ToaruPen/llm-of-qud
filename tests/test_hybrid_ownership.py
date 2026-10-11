import copy
import json
from pathlib import Path
import unittest

from harness.hybrid import select_operation
from harness.hybrid_models import validate_plan
from harness.hybrid_policy import History, candidates, evidence_state
from harness.hybrid_routing import action_ownership, navigation_options
from harness.hybrid_strategy import BuildReview, tactical_evidence
from tests.test_hybrid_routing import navigation


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    def test_post_combat_guidance_is_preserved_when_no_hostile_is_visible(self):
        s, plan, review = navigation()
        plan['tactics']['mode'] = 'combat'
        plan['guidance'] = 'After the fight, rest and then explore west.'
        data = tactical_evidence(evidence_state(s, plan, History(), review))
        self.assertEqual(data['claude_plan'].get('guidance'), plan['guidance'])
        self.assertEqual(data['claude_plan']['target'], plan['target'])

    def test_recorded_baboon_bypass_keeps_goal_and_does_not_relax_sideways_choice(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/jev_opus_distant_baboons.json').read_text())
        s = {'seq': 81, 'observation': fixture['observation']}
        plan = fixture['plan']
        review = BuildReview()
        review.accept(fixture['initial_observation'], plan['strategy'])
        review.accept(s['observation'], plan['strategy'])
        data = tactical_evidence(evidence_state(s, plan, History(), review))
        self.assertEqual(data['claude_plan']['target'], {'x': 40, 'y': 0})
        self.assertEqual(data['derived']['effective_tactics']['mode'], 'travel')
        options = candidates(s, plan)
        west = next(c for c in options if c['args'] == {'action': 'move', 'dir': 'W'})
        self.assertEqual(action_ownership(s, plan, History(), west, review)['owner'], 'claude')
        plan['tactics']['allowed_directions'] = ['N', 'NE', 'NW']
        self.assertNotIn(west, navigation_options(s, plan, options))
        north = next(c for c in options if c['args'] == {'action': 'move', 'dir': 'N'})
        self.assertEqual(action_ownership(s, plan, History(), north, review)['owner'], 'jev')

    async def choose(self, state, plan, review, action, probability=.2, history=None):
        requests = []

        async def jev(request):
            options = request['questions']['action']['criteria']
            chosen = next(k for k, c in options.items() if c['args'] == action)
            p = max(probability, 1 / len(options))
            return {'answers': {'action': {'type': 'choice', 'choice': chosen,
                    'confidence': .1, 'probabilities': {
                        k: p if k == chosen else (1-p)/(len(options)-1) for k in options}}}}

        async def claude(request):
            requests.append(request)
            return plan | {'selection': None}

        chosen, _, audit = await select_operation(state, plan, history or History(), jev, claude, review=review)
        return chosen, audit, requests

    def test_distant_fight_policy_preserves_navigation_input_and_candidate_distances(self):
        s, plan, review = navigation()
        plan['tactics']['danger_distance'] = 6
        s['observation']['threats'] = [{'id': 'e1', 'name': 'baboon', 'x': 60, 'y': 12, 'hostile': True}]
        data = tactical_evidence(evidence_state(s, plan, History(), review))
        self.assertEqual(data['claude_plan'].get('guidance'), 'Travel to the known stairs')
        self.assertEqual(data['claude_plan']['target'], {'x': 50, 'y': 12})
        self.assertEqual(data['derived']['effective_tactics']['mode'], 'travel')
        east = next(c for c in candidates(s, plan) if c['args'] == {'action': 'move', 'dir': 'E'})
        self.assertEqual(east.get('distance_to_plan_target'), 9)
        s['observation']['threats'][0]['x'] = 41
        near = tactical_evidence(evidence_state(s, plan, History(), review))
        self.assertEqual(near['derived']['effective_tactics']['mode'], 'combat')
        self.assertNotIn('guidance', near['claude_plan'])

    async def test_low_probability_routine_movement_does_not_call_upper_model(self):
        s, plan, review = navigation()
        plan['automatic_goto'] = False
        chosen, audit, calls = await self.choose(s, plan, review, {'action': 'move', 'dir': 'E'}, .15)
        self.assertEqual(calls, [])
        self.assertEqual(audit['actor'], 'jev')
        self.assertEqual(chosen['args'], {'action': 'move', 'dir': 'E'})

    async def test_known_distant_moving_enemy_does_not_revoke_approved_bypass(self):
        s, plan, review = navigation()
        plan['automatic_goto'] = False
        plan['tactics'].update(hostile_response='avoid', danger_distance=6, allowed_directions=['N', 'E', 'NE'])
        s['observation']['threats'] = [{'id': 'e1', 'name': 'croc', 'x': 20, 'y': 12, 'hostile': True}]
        review.accept(s['observation'], plan['strategy'])
        s['observation']['threats'][0]['x'] = 21
        chosen, audit, calls = await self.choose(s, plan, review, {'action': 'move', 'dir': 'E'})
        self.assertEqual(calls, [])
        self.assertEqual(audit['actor'], 'jev')
        offered = audit['jev_request']['questions']['action']['criteria'].values()
        self.assertFalse(any(c['args'] == {'action': 'move', 'dir': 'W'} for c in offered))
        self.assertEqual(chosen['args'], {'action': 'move', 'dir': 'E'})

    async def test_new_close_enemy_and_deterioration_override_high_probability(self):
        for case in ('new_enemy', 'nearer', 'damage', 'unknown', 'low_hp'):
            s, plan, review = navigation()
            plan['automatic_goto'] = False
            plan['tactics'].update(hostile_response='avoid', danger_distance=6)
            s['observation']['threats'] = [{'id': 'e1', 'name': 'croc', 'x': 20, 'y': 12, 'hostile': True}]
            review.accept(s['observation'], plan['strategy'])
            if case == 'new_enemy':
                s['observation']['threats'][0]['name'] = 'unknown hunter'
            elif case == 'nearer':
                s['observation']['threats'][0]['x'] = 35
            elif case == 'damage':
                s['observation']['vitals']['hp'] -= 1
            elif case == 'low_hp':
                s['observation']['vitals']['hp'] = 3
                review.accept(s['observation'], plan['strategy'])
            else:
                s['observation']['status'] = {'effects': ['unclassified curse']}
            with self.subTest(case=case):
                _, audit, calls = await self.choose(s, plan, review, {'action': 'move', 'dir': 'E'}, .99)
                self.assertEqual(audit['actor'], 'claude')
                self.assertEqual(len(calls), 1)

    async def test_acknowledged_single_melee_is_local_but_surrounding_enemies_are_not(self):
        for count, owner in ((1, 'jev'), (2, 'claude')):
            s, plan, review = navigation()
            plan['automatic_goto'] = False
            plan['tactics']['mode'] = 'combat'
            s['observation']['threats'] = [
                {'id': 'e1', 'name': 'snapjaw', 'x': 41, 'y': 12, 'hostile': True},
                {'id': 'e2', 'name': 'snapjaw', 'x': 39, 'y': 12, 'hostile': True}][:count]
            review.accept(s['observation'], plan['strategy'])
            with self.subTest(count=count):
                _, audit, _ = await self.choose(s, plan, review, {'action': 'attack', 'dir': 'E'}, .99 if count == 2 else .2)
                self.assertEqual(audit['actor'], owner)

    async def test_approaching_review_boundary_requires_upper_even_with_high_probability(self):
        s, plan, review = navigation()
        plan['automatic_goto'] = False
        s['observation']['threats'] = [{'id': 'e1', 'name': 'croc', 'x': 47, 'y': 12, 'hostile': True}]
        review.accept(s['observation'], plan['strategy'])
        _, audit, calls = await self.choose(s, plan, review, {'action': 'move', 'dir': 'E'}, .99)
        self.assertEqual(audit['actor'], 'claude')
        self.assertEqual(len(calls), 1)

    def test_restricted_corridor_cannot_be_bypassed_by_an_opaque_macro(self):
        s, plan, _ = navigation()
        plan['tactics']['allowed_directions'] = ['N', 'E']
        self.assertFalse(any(c['args'].get('action') in ('goto', 'explore') for c in candidates(s, plan)))

    async def test_unknown_consumable_never_becomes_local_due_to_high_probability(self):
        s, plan, review = navigation()
        plan['automatic_goto'] = False
        s['observation']['kit'][0]['name'] = 'strange flesh'
        s['observation']['item_details'][0]['description'] = 'Unknown effects.'
        _, audit, calls = await self.choose(s, plan, review, {'action': 'eat', 'item': 'i1'}, .99)
        self.assertEqual(audit['actor'], 'claude')
        self.assertEqual(len(calls), 1)

    async def test_listening_is_local_but_dialogue_branch_is_reasoned(self):
        for label, owner in (('...', 'jev'), ('Take my water.', 'claude')):
            s, plan, review = navigation()
            s['modal'] = {'token': 't', 'type': 'conversation', 'text': 'An offer.', 'choices': [
                {'id': 'option:0', 'label': label}, {'id': 'button:1', 'label': '[Esc] Cancel'}]}
            with self.subTest(label=label):
                _, audit, _ = await self.choose(s, plan, review, {'response': {'choice': 'option:0'}}, .5)
                self.assertEqual(audit['actor'], owner)

    def test_structured_navigation_limits_are_additive_and_validated(self):
        _, plan, _ = navigation()
        self.assertEqual(validate_plan(copy.deepcopy(plan)), plan)
        plan['tactics'].update(danger_distance=6, allowed_directions=['N', 'E'])
        self.assertEqual(validate_plan(copy.deepcopy(plan)), plan)
        for key, bad in (('danger_distance', 0), ('danger_distance', True),
                         ('allowed_directions', ['U']), ('allowed_directions', ['N', 'N'])):
            invalid = copy.deepcopy(plan)
            invalid['tactics'][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                validate_plan(invalid)
