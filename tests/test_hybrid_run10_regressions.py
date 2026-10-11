"""Recorded run10 recovery and pursuit must honor semantic permissions."""
import copy
import json
from pathlib import Path
import unittest

from harness.hybrid import select_operation
from harness.hybrid_autonomy import autonomous_action
from harness.hybrid_continuation import continuation_status
from harness.hybrid_models import validate_plan
from harness.hybrid_policy import History, candidates
from harness.hybrid_strategy import BuildReview
from harness.jev_transport import JevError


def recorded(name):
    data = json.loads((Path(__file__).parent/'fixtures/jev_run10_recovery_pursuit.json').read_text())[name]
    review = BuildReview()
    safe = copy.deepcopy(data['reviewed_observation'])
    safe['threats'] = []
    review.accept(safe, data['plan']['strategy'])
    review.accept(data['reviewed_observation'], data['plan']['strategy'])
    history = History(events=data['events'])
    history.records = data['records']
    return data['state'], data['plan'], review, history


class Run10Regressions(unittest.IsolatedAsyncioTestCase):
    async def test_upper_selection_must_not_contradict_its_own_recovery_condition(self):
        state, plan, review, history = recorded('recovery')
        plan['tactics']['recovery_hp_target'] = 14
        async def forbidden(request):
            self.fail('An explicit review is pending')
        async def claude(request):
            north = next(c for c in request['candidates'] if c['args'] == {'action': 'move', 'dir': 'N'})
            return plan | {'selection': north['id']}
        choice, _, audit = await select_operation(state, plan, history, forbidden, claude,
                                                  force_reason='initial_build_review', review=review)
        self.assertIsNone(choice)
        self.assertEqual(audit.get('action_rejected'), 'recovery_incomplete')

    async def test_nonretryable_jev_failure_stops_without_costly_upper_consultation(self):
        state, plan, review, history = recorded('recovery')
        plan['tactics']['mode'] = 'explore'
        async def jev(request):
            raise JevError('Jev HTTP 401', retryable=False)
        async def claude(request):
            self.fail('An upper game planner cannot repair API credentials')
        with self.assertRaisesRegex(JevError, '401'):
            await select_operation(state, plan, history, jev, claude, review=review)

    async def test_exhausted_transient_failure_only_reviews_local_decision(self):
        state, plan, review, history = recorded('recovery')
        plan['tactics']['mode'] = 'explore'
        async def jev(request):
            raise JevError('Jev HTTP 503', retryable=True)
        calls = []
        async def claude(request):
            calls.append((request['reason'], request['decision_scope']))
            return plan | {'selection': None}
        await select_operation(state, plan, history, jev, claude, review=review)
        self.assertEqual(calls, [('jev_unavailable', 'local')])

    async def test_recovery_at_current_target_rests_without_consulting_or_departing(self):
        for target in (None, {'x': 54, 'y': 8}):
            state, plan, review, history = recorded('recovery')
            plan['target'] = target
            async def forbidden(request):
                self.fail('An already approved, safe recovery chunk requires no new model decision')
            with self.subTest(target=target):
                choice, _, _ = await select_operation(state, plan, history, forbidden, forbidden, review=review)
                self.assertEqual(choice['args'], {'action': 'rest', 'until': 'healed', 'budget': 12})

    def test_recovery_permission_rejects_departure_even_when_target_is_null(self):
        state, plan, review, history = recorded('recovery')
        north = next(c for c in candidates(state, plan) if c['args'] == {'action': 'move', 'dir': 'N'})
        self.assertIsNone(autonomous_action(state, plan, history, review, north))

    async def test_existing_recovery_plan_can_reach_its_rest_site_before_resting(self):
        state, plan, review, history = recorded('recovery')
        plan['target'] = {'x': 54, 'y': 10}
        from tests.test_hybrid_autonomy import answer
        async def jev(request):
            return answer(request, {'action': 'move', 'dir': 'S'})
        async def forbidden(request):
            self.fail('An old recovery plan still authorizes travel to its rest site')
        choice, _, _ = await select_operation(state, plan, history, jev, forbidden, review=review)
        self.assertEqual(choice['args'], {'action': 'move', 'dir': 'S'})

    async def test_slow_successful_healing_chunks_are_not_navigation_stalls(self):
        state, plan, review, history = recorded('recovery')
        history.records = []
        for _ in range(3):
            before = copy.deepcopy(state)
            state['seq'] += 1
            state['observation']['vitals']['turn'] += 12
            history.record(before, {'action': 'rest', 'until': 'healed', 'budget': 12},
                           {'executed': True, 'reason': 'BUDGET', 'turns_elapsed': 12}, state)
        async def forbidden(request):
            self.fail('Slow public Albino regeneration is not a failed movement loop')
        choice, _, _ = await select_operation(state, plan, history, forbidden, forbidden,
                                              force_reason=history.problem(), review=review)
        self.assertEqual(choice['args']['action'], 'rest')

    async def test_recovery_does_not_automatically_rest_when_enemy_or_hazard_appears(self):
        for case in ('enemy', 'poison'):
            state, plan, review, history = recorded('recovery')
            if case == 'enemy':
                state['observation']['threats'].append({'id': 'new', 'name': 'croc', 'x': 55, 'y': 8, 'hostile': True})
            else:
                state['observation']['status'] = {'effects': ['poisoned']}
            async def forbidden(request):
                self.fail('A changed danger needs upper judgment')
            async def claude(request, plan=plan):
                return plan | {'selection': None}
            with self.subTest(case=case):
                choice, _, audit = await select_operation(state, plan, history, forbidden, claude, review=review)
                self.assertIsNone(choice)
                self.assertEqual(audit['actor'], 'claude')

    async def test_structured_recovery_goal_ends_at_14_hp_instead_of_coordinate_arrival(self):
        state, plan, review, history = recorded('recovery')
        plan['tactics']['recovery_hp_target'] = 14
        validate_plan(plan)
        state['observation']['vitals']['hp'] = 14
        calls = []
        async def forbidden(request):
            self.fail('Completion should ask for the next objective, not start another rest')
        async def claude(request):
            calls.append(request['reason'])
            return plan | {'selection': None}
        await select_operation(state, plan, history, forbidden, claude, review=review)
        self.assertEqual(calls, ['recovery_complete'])

    def test_pursuer_at_constant_relative_distance_does_not_revoke_route(self):
        state, plan, review, history = recorded('pursuit')
        self.assertTrue(continuation_status(state, plan, history, review)['active'])

    def test_ambiguous_same_name_group_keeps_conservative_approach_review(self):
        state, plan, review, history = recorded('pursuit')
        for obs in (state['observation'], review.reviewed_observation):
            obs['threats'].append({'id': 'far', 'name': 'croc', 'x': 50, 'y': 20, 'hostile': True})
        self.assertFalse(continuation_status(state, plan, history, review)['active'])

    def test_new_adjacency_is_reviewed_even_when_enemy_did_not_move(self):
        state, plan, review, history = recorded('pursuit')
        # The player's approved step approached a stationary enemy: 2 -> 1 cells.
        review.reviewed_observation['threats'][0].update(x=5, y=22)
        state['observation']['threats'][0].update(x=5, y=22)
        self.assertFalse(continuation_status(state, plan, history, review)['active'])

    def test_pursuit_still_stops_for_actual_closing_new_enemy_or_failed_step(self):
        for case in ('closing', 'new_enemy', 'blocked', 'damage'):
            state, plan, review, history = recorded('pursuit')
            if case == 'closing':
                state['observation']['threats'][0].update(x=3, y=22)
            elif case == 'new_enemy':
                state['observation']['threats'].append({'id': 'new', 'name': 'snapjaw', 'x': 5, 'y': 22, 'hostile': True})
            elif case == 'blocked':
                history.records[-1]['result']['executed'] = False
            else:
                state['observation']['vitals']['hp'] = 3
            with self.subTest(case=case):
                self.assertFalse(continuation_status(state, plan, history, review)['active'])
