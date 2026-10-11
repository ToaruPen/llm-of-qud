"""Mission permissions must reduce reviews without erasing safety boundaries."""
import copy
import tempfile
from pathlib import Path
import unittest

from harness.hybrid import play, select_operation
from harness.hybrid_models import validate_plan
from harness.hybrid_policy import History, candidates, decision_gate
from tests.test_hybrid_routing import navigation


def delegated():
    state, plan, review = navigation()
    plan.update(issued_seq=state['seq'], automatic_goto=False, continuation=None,
                autonomy={'max_steps': 64, 'min_hp': 6, 'max_damage': 3,
                          'combat_names': [], 'healing_items': [], 'avoid_cells': []})
    return state, plan, review


def answer(request, action):
    options = request['questions']['action']['criteria']
    chosen = next(k for k, c in options.items() if c['args'] == action)
    p = max(.2, 1 / len(options))
    return {'answers': {'action': {'type': 'choice', 'choice': chosen, 'confidence': .2,
            'probabilities': {k: p if k == chosen else (1-p)/(len(options)-1) for k in options}}}}


class AutonomyTests(unittest.IsolatedAsyncioTestCase):
    async def select(self, state, plan, review, action, *, history=None, reason=None):
        calls = []
        async def jev(request):
            return answer(request, action)
        async def claude(request):
            calls.append(request)
            return plan | {'selection': None}
        choice, _, audit = await select_operation(state, plan, history or History(), jev, claude,
                                                 force_reason=reason, review=review)
        return choice, audit, calls

    async def test_distant_new_enemy_and_expired_horizon_are_notifications(self):
        state, plan, review = delegated()
        state['seq'] += 25
        state['observation']['threats'] = [{'id': 'e2', 'name': 'baboon', 'x': 60, 'y': 12, 'hostile': True}]
        choice, audit, calls = await self.select(state, plan, review, {'action': 'move', 'dir': 'N'}, reason='plan_expired')
        self.assertEqual(calls, [])
        self.assertEqual(choice['args'], {'action': 'move', 'dir': 'N'})
        self.assertTrue(audit.get('notifications'))
        self.assertEqual(audit['actor'], 'jev')

    async def test_approved_enemy_kind_can_move_without_invalidating_single_melee(self):
        state, plan, review = delegated()
        plan['autonomy']['combat_names'] = ['snapjaw']
        state['observation']['threats'] = [{'id': 'e2', 'name': 'snapjaw', 'x': 41, 'y': 12, 'hostile': True}]
        choice, _, calls = await self.select(state, plan, review, {'action': 'attack', 'dir': 'E'})
        self.assertEqual(calls, [])
        self.assertEqual(choice['args']['action'], 'attack')

    async def test_bypass_can_get_closer_to_a_far_enemy_without_entering_its_review_band(self):
        state, plan, review = delegated()
        plan['tactics'].update(hostile_response='avoid', danger_distance=8)
        state['observation']['vitals'].update(x=40, y=23)
        state['observation']['threats'] = [{'id': 'e2', 'name': 'croc', 'x': 49, 'y': 6, 'hostile': True}]
        review.accept(state['observation'], plan['strategy'])
        choice, _, calls = await self.select(state, plan, review, {'action': 'move', 'dir': 'NW'})
        self.assertEqual(calls, [])
        self.assertEqual(choice['args'], {'action': 'move', 'dir': 'NW'})

    async def test_close_approved_enemy_still_requires_nonapproaching_avoidance(self):
        state, plan, review = delegated()
        plan['tactics'].update(hostile_response='avoid', danger_distance=8)
        plan['autonomy']['combat_names'] = ['croc']
        state['observation']['threats'] = [{'id': 'e2', 'name': 'croc', 'x': 45, 'y': 12, 'hostile': True}]
        review.accept(state['observation'], plan['strategy'])
        _, audit, calls = await self.select(state, plan, review, {'action': 'move', 'dir': 'E'})
        self.assertEqual(len(calls), 1)
        self.assertEqual(audit['actor'], 'claude')

    async def test_hard_boundaries_still_block_high_confidence_local_actions(self):
        for change in ('enemy', 'surrounded', 'hp', 'damage', 'unknown', 'growth', 'quest', 'zone', 'budget'):
            state, plan, review = delegated()
            history = History()
            obs = state['observation']
            if change in ('enemy', 'surrounded'):
                obs['threats'] = [{'id': 'e1', 'name': 'snapjaw', 'x': 41, 'y': 12, 'hostile': True}]
                if change == 'surrounded':
                    plan['autonomy']['combat_names'] = ['snapjaw']
                    obs['threats'].append({'id': 'e2', 'name': 'snapjaw', 'x': 39, 'y': 12, 'hostile': True})
            elif change == 'hp':
                obs['vitals']['hp'] = 3
            elif change == 'damage':
                history.events = [{'kind': 'risk_outcome', 'source': {'seq': state['seq']+1},
                    'zone': obs['vitals']['zone'], 'position': {'x': 40, 'y': 12},
                    'observed_hp_loss': 4, 'action': {'action': 'move', 'dir': 'E'}}]
                state['seq'] += 12  # Damage survives the eight-record rolling window and healing.
            elif change == 'unknown':
                obs.setdefault('status', {})['effects'] = ['unclassified curse']
            elif change == 'growth':
                obs['character']['skill_points'] += 100
            elif change == 'quest':
                obs['goals'] = {'text': 'Quest completed', 'truncated': False}
            elif change == 'zone':
                obs['vitals']['zone'] += '.new'
            else:
                state['seq'] += 64
            with self.subTest(change=change):
                _, audit, calls = await self.select(state, plan, review, {'action': 'move', 'dir': 'N'}, history=history)
                self.assertEqual(len(calls), 1)
                self.assertEqual(audit['actor'], 'claude')

    async def test_rest_does_not_require_a_new_recovery_mode_or_resource_review(self):
        state, plan, review = delegated()
        state['observation']['vitals']['hp'] -= 1
        choice, _, calls = await self.select(state, plan, review, {'action': 'rest', 'until': 'healed', 'budget': 12})
        self.assertEqual(calls, [])
        self.assertEqual(choice['args']['action'], 'rest')

    async def test_high_probability_cannot_step_into_unapproved_contact_band(self):
        state, plan, review = delegated()
        state['observation']['threats'] = [{'id': 'e2', 'name': 'unknown hunter', 'x': 47, 'y': 12, 'hostile': True}]
        calls = []
        async def jev(request):
            result = answer(request, {'action': 'move', 'dir': 'E'})
            value = result['answers']['action']
            value['probabilities'] = {k: float(k == value['choice']) for k in value['probabilities']}
            return result
        async def claude(request):
            calls.append(request)
            return plan | {'selection': None}
        choice, _, audit = await select_operation(state, plan, History(), jev, claude, review=review)
        self.assertIsNone(choice)
        self.assertEqual(audit['actor'], 'claude')
        self.assertEqual(len(calls), 1)

    async def test_heal_outcome_requires_review_before_second_consumption(self):
        state, plan, review = delegated()
        obs = state['observation']
        obs['kit'][0]['name'] = 'witchwood bark'
        obs['item_details'][0].update(description='Heals 1d6 HP.', actions=['eat'])
        plan['autonomy']['healing_items'] = ['i1']
        review.accept(obs, plan['strategy'])
        before = copy.deepcopy(state)
        before['observation']['vitals']['hp'] = 3
        state['seq'] += 1
        obs['vitals']['hp'] = 4
        history = History()
        history.record(before, {'action': 'eat', 'item': 'i1'}, {'executed': True}, state)
        _, audit, calls = await self.select(state, plan, review, {'action': 'eat', 'item': 'i1'}, history=history)
        self.assertEqual(len(calls), 1)
        self.assertEqual(audit['escalation'], 'autonomy_consumption_review')

    async def test_damage_above_heal_threshold_consults_before_offering_unpermitted_heal(self):
        state, plan, review = delegated()
        obs = state['observation']
        obs['vitals'].update(hp=15, max_hp=15)
        obs['kit'][0]['name'] = 'witchwood bark'
        obs['item_details'][0].update(description='Heals and confuses when eaten.', actions=['eat'])
        plan['autonomy']['healing_items'] = ['i1']
        plan['tactics']['heal_hp_fraction'] = .4
        review.accept(obs, plan['strategy'])
        before = copy.deepcopy(state)
        state['seq'] += 1
        obs['vitals']['hp'] = 7  # Observed live: emergency loss, but outside the 40% permission.
        history = History()
        history.record(before, {'action': 'attack', 'dir': 'E'}, {'executed': True}, state)
        async def jev(request):
            self.fail('Do not offer a heal that the execution gate cannot authorize')
        async def claude(request):
            self.assertEqual(request['reason'], 'autonomy_damage_limit')
            self.assertIsNone(request['jev_answer'])
            return plan | {'selection': None}
        _, _, audit = await select_operation(state, plan, history, jev, claude, review=review)
        self.assertEqual(audit['actor'], 'claude')

    async def test_healing_permission_matches_description_not_recycled_item_handle(self):
        for changed in (False, True):
            state, plan, review = delegated()
            obs = state['observation']
            obs['kit'][0]['name'] = 'witchwood bark'
            obs['item_details'][0].update(description='Heals 1d6 HP; may cause confusion.', actions=['eat'])
            plan['autonomy']['healing_items'] = ['i1']
            review.accept(obs, plan['strategy'])
            obs['vitals']['hp'] = 3
            obs['kit'][0]['id'] = 'i7'
            obs['item_details'][0]['id'] = 'i7'
            if changed:
                obs['item_details'][0]['description'] = 'Poisons the eater.'
            with self.subTest(changed=changed):
                choice, _, calls = await self.select(state, plan, review, {'action': 'eat', 'item': 'i7'})
                self.assertEqual(len(calls), int(changed))
                if not changed:
                    self.assertEqual(choice['args'], {'action': 'eat', 'item': 'i7'})

    def test_spatial_exclusions_disable_opaque_macros_and_block_steps_for_both_models(self):
        state, plan, _ = delegated()
        plan['autonomy']['avoid_cells'] = [{'x': 41, 'y': 12}]
        for strategic in (False, True):
            offered = candidates(state, plan, strategic=strategic)
            self.assertFalse(any(c['args'].get('action') in ('goto', 'explore') for c in offered))
            self.assertFalse(any(c.get('destination') == {'x': 41, 'y': 12} for c in offered))
        plan['autonomy']['avoid_cells'] = []
        history = History(events=[{'kind': 'risk_outcome', 'source': {'seq': i},
            'zone': state['observation']['vitals']['zone'], 'position': {'x': 41, 'y': 12},
            'observed_hp_loss': 2, 'action': {'action': 'move', 'dir': 'E'}} for i in (1, 2)])
        self.assertFalse(any(c['args'].get('action') in ('goto', 'explore') for c in candidates(state, plan, history=history)))

    def test_probability_roundoff_tie_is_valid_but_nonmaximal_choice_is_not(self):
        value = {'type': 'choice', 'choice': 'a', 'confidence': .19,
                 'probabilities': {'a': .22999999999999998, 'b': .23, 'c': .18, 'd': .18, 'e': .18}}
        self.assertIsNone(decision_gate(value, list(value['probabilities']), 0))
        value['probabilities'].update(a=.22, b=.24)
        self.assertEqual(decision_gate(value, list(value['probabilities']), 0), 'invalid_jev_response')

    def test_invalid_permissions_and_dual_contracts_are_rejected(self):
        _, plan, _ = delegated()
        for key, value in (('max_steps', 0), ('max_steps', True), ('min_hp', -1), ('max_damage', -1),
                           ('combat_names', [17]), ('healing_items', ['i1', 'i1']),
                           ('avoid_cells', [{'x': 80, 'y': 0}])):
            changed = copy.deepcopy(plan)
            changed['autonomy'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_plan(changed)
        plan['continuation'] = {'route': [], 'hold_position': None, 'attack_target': None,
                                'min_hp': 1, 'max_damage': 0, 'max_steps': 1}
        with self.assertRaises(ValueError):
            validate_plan(plan)

    async def test_play_keeps_permission_past_horizon_without_resetting_review_anchor(self):
        state, plan, _ = delegated()
        plan['horizon'] = 1
        requests = []
        class Models:
            claude_calls = 0
            jev_calls = 0
            async def claude(self, request):
                requests.append(request)
                self.claude_calls += 1
                return copy.deepcopy(plan)
            async def jev(self, request):
                self.jev_calls += 1
                return answer(request, {'action': 'move', 'dir': 'N'})
        async def call(name, **args):
            if name == 'get_state':
                return copy.deepcopy(state)
            if name == 'act':
                state['seq'] += 1
                state['observation']['vitals']['y'] -= 1
                return {'ok': True}
            if name == 'wait_for_turn':
                return {'completed': True, 'result': {'executed': True, 'reason': 'ok'}}
            raise AssertionError(name)
        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, Models(), Path(directory), max_actions=4, duration=2)
        self.assertEqual(report['accepted_actions'], 4)
        self.assertEqual(len(requests), 1)
        self.assertEqual(report['plan']['issued_seq'], state['seq']-4)
