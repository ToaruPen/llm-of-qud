import copy
import json
import unittest
import tempfile
from pathlib import Path

from harness.hybrid import play
from harness.hybrid_models import validate_plan
from harness.hybrid_policy import History, evidence_state
from harness.hybrid_strategy import tactical_evidence
from tests import test_hybrid_ownership as ownership
from tests.test_hybrid_routing import navigation


def encounter():
    state, plan, review = navigation()
    obs = state['observation']
    obs['threats'] = [{'id': 'e1', 'name': 'seed-spitting vine', 'x': 44, 'y': 12, 'hostile': True}]
    obs['status'] = {'effects': ['confused']}
    plan.update(automatic_goto=False, issued_seq=state['seq'], target={'x': 38, 'y': 12},
                guidance='Withdraw west to the reviewed endpoint.',
                continuation={'route': [{'x': 39, 'y': 12}, {'x': 38, 'y': 12}],
                              'hold_position': None, 'attack_target': None,
                              'min_hp': 10, 'max_damage': 2, 'max_steps': 4})
    plan['tactics'].update(mode='retreat', hostile_response='retreat')
    review.accept(obs, plan['strategy'])
    return state, plan, review


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    choose = ownership.OwnershipTests.choose

    async def test_recorded_routine_bypass_survives_hazard_acknowledgement_reset(self):
        from harness.hybrid_strategy import BuildReview
        data = json.loads((Path(__file__).parent / 'fixtures/jev_reviewed_croc_continuation.json').read_text())
        state = {'seq': data['seq'], 'observation': data['observation']}
        plan = data['plan']
        review = BuildReview()
        review.accept(state['observation'], plan['strategy'])
        self.assertIsNone(review.reason(state['observation']))
        _, audit, calls = await self.choose(state, plan, review, {'action': 'move', 'dir': 'NW'})
        self.assertFalse(calls)
        self.assertEqual(audit['actor'], 'jev')

    async def test_play_loop_honors_bounded_wait_until_contract_expires(self):
        state, plan, _ = encounter()
        plan['continuation'].update(route=[], hold_position={'x': 40, 'y': 12})
        plan['tactics'].update(mode='recover', hostile_response='avoid')

        class Models:
            claude_calls = 0
            jev_calls = 0

            async def claude(self, request):
                self.claude_calls += 1
                candidate = next(c for c in request['candidates'] if c['args'] == {'action': 'wait'})
                return copy.deepcopy(plan) | {'selection': candidate['id']}

            async def jev(self, request):
                self.jev_calls += 1
                options = request['questions']['action']['criteria']
                chosen = next(k for k, c in options.items() if c['args'] == {'action': 'wait'})
                return {'answers': {'action': {'type': 'choice', 'choice': chosen, 'confidence': 1,
                        'probabilities': {k: int(k == chosen) for k in options}}}}

        async def call(name, **args):
            if name == 'get_state':
                return copy.deepcopy(state)
            if name == 'act':
                state['seq'] += 1
                return {'ok': True}
            if name == 'wait_for_turn':
                return {'completed': True, 'result': {'executed': True}}
            raise AssertionError(name)

        models = Models()
        with tempfile.TemporaryDirectory() as directory:
            report = await play(call, models, Path(directory), max_actions=5)
        self.assertEqual(report['accepted_actions'], 5)
        self.assertEqual(models.claude_calls, 2)
        self.assertEqual(models.jev_calls, 3)

    async def test_healing_does_not_refund_damage_budget(self):
        state, plan, review = encounter()
        plan['continuation'].update(route=[], hold_position={'x': 40, 'y': 12})
        history = History()
        for hp in (12, 14, 12):
            before = copy.deepcopy(state)
            state['seq'] += 1
            state['observation']['vitals']['hp'] = hp
            history.record(before, {'action': 'wait'}, {'executed': True}, state)
        _, audit, calls = await self.choose(state, plan, review, {'action': 'wait'}, .99, history)
        self.assertTrue(calls)
        self.assertEqual(audit['escalation'], 'continuation_damage_budget')

    async def test_reviewed_confusion_retreat_keeps_route_and_runs_locally(self):
        state, plan, review = encounter()
        data = tactical_evidence(evidence_state(state, plan, History(), review))
        self.assertEqual(data['claude_plan'].get('guidance'), plan['guidance'])
        chosen, audit, calls = await self.choose(state, plan, review, {'action': 'move', 'dir': 'W'})
        self.assertFalse(calls)
        self.assertEqual(audit['actor'], 'jev')
        self.assertEqual(chosen['args'], {'action': 'move', 'dir': 'W'})

    async def test_acknowledged_hazard_wait_does_not_reconsult_each_turn(self):
        state, plan, review = encounter()
        plan['continuation'].update(route=[], hold_position={'x': 40, 'y': 12})
        plan['tactics'].update(mode='recover', hostile_response='avoid')
        _, audit, calls = await self.choose(state, plan, review, {'action': 'wait'})
        self.assertFalse(calls)
        self.assertEqual(audit['actor'], 'jev')

    async def test_expected_small_damage_does_not_interrupt_approved_escape(self):
        state, plan, review = encounter()
        before = copy.deepcopy(state)
        state['seq'] += 1
        state['observation']['vitals'].update(x=39, hp=13)
        history = History()
        history.record(before, {'action': 'move', 'dir': 'W'}, {'executed': True}, state)
        _, audit, calls = await self.choose(state, plan, review, {'action': 'move', 'dir': 'W'}, history=history)
        self.assertFalse(calls)
        self.assertEqual(audit['actor'], 'jev')

    async def test_changes_and_unapproved_actions_revoke_delegation(self):
        for case in ('new_enemy', 'unknown', 'critical_hp', 'expired', 'wrong_direction', 'blocked', 'large_damage'):
            state, plan, review = encounter()
            history = History()
            action = {'action': 'move', 'dir': 'W'}
            if case == 'new_enemy':
                state['observation']['threats'].append({'id': 'e2', 'name': 'snapjaw', 'x': 39, 'y': 13, 'hostile': True})
            elif case == 'unknown':
                state['observation']['status']['effects'].append('unknown curse')
            elif case == 'critical_hp':
                state['observation']['vitals']['hp'] = 3
            elif case == 'expired':
                state['seq'] += 4
            elif case == 'wrong_direction':
                action['dir'] = 'E'
            else:
                before = copy.deepcopy(state)
                state['seq'] += 1
                if case == 'large_damage':
                    state['observation']['vitals']['hp'] -= 5
                history.record(before, action, {'executed': case != 'blocked'}, state)
            with self.subTest(case=case):
                _, audit, calls = await self.choose(state, plan, review, action, .99, history)
                self.assertTrue(calls)
                self.assertEqual(audit['actor'], 'claude')

    async def test_adjacent_approved_target_can_be_attacked_during_known_hazard(self):
        state, plan, review = encounter()
        state['observation']['threats'][0].update(x=41)
        review.accept(state['observation'], plan['strategy'])
        plan['continuation'].update(route=[], attack_target={'x': 41, 'y': 12})
        plan['tactics'].update(mode='combat', hostile_response='fight')
        _, audit, calls = await self.choose(state, plan, review, {'action': 'attack', 'dir': 'E'})
        self.assertFalse(calls)
        self.assertEqual(audit['actor'], 'jev')

    def test_observed_losses_survive_short_history_and_resume_without_claiming_attack_range(self):
        state, plan, review = encounter()
        history = History()
        for damage in (2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2):
            before = copy.deepcopy(state)
            state['seq'] += 1
            state['observation']['vitals']['hp'] -= damage
            history.record(before, {'action': 'wait'}, {'executed': True}, state)
        restored = History(events=history.events)
        risks = evidence_state(state, plan, restored, review)['derived'].get('route_risks', [])
        self.assertEqual(len(risks), 1)
        self.assertEqual(risks[0]['damage_events'], 2)
        self.assertEqual(risks[0]['observed_hp_loss'], 4)
        self.assertEqual(risks[0]['position'], {'x': 40, 'y': 12})
        self.assertNotIn('maximum_attack_range', risks[0])

    def test_invalid_continuations_are_rejected_but_old_plans_remain_valid(self):
        _, old, _ = navigation()
        self.assertEqual(validate_plan(copy.deepcopy(old)), old)
        _, plan, _ = encounter()
        self.assertEqual(validate_plan(copy.deepcopy(plan)), plan)
        for key, value in (('min_hp', True), ('max_damage', -1), ('max_steps', 9),
                           ('route', [{'x': 80, 'y': 12}]), ('attack_target', {'x': 1}),
                           ('route', [{'x': 39, 'y': 12}, {'x': 39, 'y': 12}])):
            invalid = copy.deepcopy(plan)
            invalid['continuation'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_plan(invalid)
