import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.hybrid import play, select_operation
from harness.hybrid_models import Models, claude_input
from harness.hybrid_policy import History
from harness.hybrid_strategy import BuildReview
from tests.test_hybrid_cache import expand_payload


def recorded(name):
    data = json.loads((Path(__file__).parent / 'fixtures/jev_run5_decision_boundaries.json').read_text())[name]
    state, plan = data['state'], data['plan']
    review = BuildReview()
    review.accept(data['reviewed_observation'], plan['strategy'])
    # Growth was reviewed earlier in the actual episode, before entering danger.
    if review.reviewed is None:
        safe = copy.deepcopy(data['reviewed_observation'])
        safe['threats'] = []
        safe['status'] = {'effects': []}
        review.accept(safe, plan['strategy'])
        review.accept(data['reviewed_observation'], plan['strategy'])
    history = History(events=data['events'])
    history.records = data['records']
    return state, plan, review, history, data['reason']


class LocalReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorded_expiry_resumes_known_route_without_model_or_history_reset(self):
        state, plan, review, history, reason = recorded('expired_travel')
        original = copy.deepcopy(plan)
        events = copy.deepcopy(history.events)
        async def forbidden(request):
            self.fail('An unchanged, healthy known route should resume through native goto')
        chosen, updated, audit = await select_operation(
            state, plan, history, forbidden, forbidden, force_reason=reason, review=review)
        self.assertEqual(chosen['args']['action'], 'goto')
        self.assertEqual(chosen['args']['target'], {'x': 79, 'y': 0})
        self.assertIsNone(updated['continuation'])
        self.assertEqual(updated['strategy'], original['strategy'])
        self.assertEqual(history.events, events)
        self.assertEqual(plan, original)
        self.assertIn('local_plan_update', audit)

    async def test_reached_target_new_zone_and_enemy_updates_use_local_scope(self):
        for name in ('expired_at_target', 'zone_change', 'distant_new_enemy', 'combat_finished'):
            state, plan, review, history, reason = recorded(name)
            async def forbidden(request):
                self.fail('This boundary still requires upper judgment')
            async def claude(request, plan=plan):
                self.assertEqual(request['decision_scope'], 'local')
                return plan | {'selection': None}
            with self.subTest(name=name):
                _, _, audit = await select_operation(
                    state, plan, history, forbidden, claude, force_reason=reason, review=review)
                self.assertEqual(audit['actor'], 'claude')

    async def test_renewal_does_not_hide_damage_growth_unknown_effect_or_changed_goal(self):
        for change in ('damage', 'growth', 'unknown', 'goal', 'failed'):
            state, plan, review, history, reason = recorded('expired_travel')
            obs = state['observation']
            if change == 'damage':
                obs['vitals']['hp'] -= 1
            elif change == 'growth':
                obs['character']['skill_points'] += 100
            elif change == 'unknown':
                obs['status']['effects'].append('unknown test curse')
            elif change == 'goal':
                obs['goals'] = {'text': 'A different quest', 'truncated': False}
            else:
                history.records[-1]['result']['executed'] = False
            async def forbidden(request):
                self.fail('Changed conditions must not renew navigation')
            async def claude(request, plan=plan):
                return plan | {'selection': None}
            with self.subTest(change=change):
                _, _, audit = await select_operation(
                    state, plan, history, forbidden, claude, force_reason=reason, review=review)
                self.assertEqual(audit['actor'], 'claude')
                self.assertNotIn('local_plan_update', audit)

    async def test_critical_retreat_exposes_lethal_loss_and_available_healing(self):
        state, plan, review, history, reason = recorded('critical_retreat')
        async def forbidden(request):
            self.fail('Critical damage must reach the upper planner')
        async def claude(request):
            survival = request['evidence']['derived'].get('survival', {})
            self.assertEqual(survival.get('largest_recent_hp_loss'), 6)
            self.assertTrue(survival.get('observed_loss_can_be_lethal'))
            self.assertIn({'action': 'eat', 'item': 'i9'}, survival.get('healing_actions', []))
            return plan | {'selection': None}
        _, _, audit = await select_operation(
            state, plan, history, forbidden, claude, force_reason=reason, review=review)
        self.assertEqual(audit['actor'], 'claude')

    async def test_upper_first_move_cannot_reenter_repeated_lethal_exposure(self):
        state, plan, review, history, reason = recorded('critical_retreat')
        # The western cell has two completed damage outcomes in this zone.
        for seq in (151, 152):
            history.events.append({'kind': 'risk_outcome', 'source': {'seq': seq},
                                   'zone': state['observation']['vitals']['zone'],
                                   'position': {'x': 32, 'y': 2}, 'observed_hp_loss': 2,
                                   'action': {'action': 'move', 'dir': 'W'}})
        async def forbidden(request):
            self.fail('A critical state requires the upper planner')
        async def claude(request):
            chosen = next(c for c in request['candidates'] if c['args'] == {'action': 'move', 'dir': 'W'})
            return plan | {'selection': chosen['id']}
        chosen, _, audit = await select_operation(
            state, plan, history, forbidden, claude, force_reason=reason, review=review)
        self.assertIsNone(chosen)
        self.assertEqual(audit.get('action_rejected'), 'lethal_repeated_exposure')

    async def test_play_loop_keeps_locally_renewed_plan_for_subsequent_macro(self):
        state, plan, _, _, _ = recorded('expired_travel')
        state['ok'] = True
        plan['horizon'] = 1
        x, y = (state['observation']['vitals'][k] for k in ('x', 'y'))
        plan['continuation']['route'] = [{'x': x+1, 'y': y}, {'x': x+2, 'y': y}]
        requests = []
        class Models:
            claude_calls = 0
            jev_calls = 0
            async def claude(self, request):
                requests.append(request)
                self.claude_calls += 1
                return plan | {'selection': None}
            async def jev(self, request):
                self.jev_calls += 1
                options = request['questions']['action']['criteria']
                chosen = next(k for k,c in options.items() if c['args'] == {'action':'move','dir':'E'})
                return {'answers': {'action': {'type':'choice','choice':chosen,'confidence':1,
                        'probabilities': {k:float(k==chosen) for k in options}}}}
        async def call(name, **args):
            if name == 'get_state':
                return copy.deepcopy(state)
            if name == 'act':
                state['seq'] += 1
                state['observation']['vitals']['x'] += 1
                return {'ok':True}
            if name == 'wait_for_turn':
                return {'completed':True, 'result':{'executed':True,'reason':'BUDGET'}}
            raise AssertionError(name)
        with tempfile.TemporaryDirectory() as directory:
            models = Models()
            report = await play(call, models, Path(directory), max_actions=3, duration=.3)
        self.assertEqual(report['accepted_actions'], 3)
        self.assertEqual(models.claude_calls, 1)
        self.assertIsNone(report['plan']['continuation'])

    async def test_local_patch_keeps_build_memory_and_uses_high_effort_for_danger(self):
        for name, effort in (('expired_at_target', 'medium'), ('critical_retreat', 'high')):
            state, plan, review, history, reason = recorded(name)
            captured = []
            async def capture(request, captured=captured, plan=plan):
                captured.append(request)
                return plan | {'selection': None}
            await select_operation(state, plan, history, capture, capture, force_reason=reason, review=review)
            request = captured[0] | {'decision_scope': 'local'}
            fields = ('goal', 'guidance', 'target', 'horizon', 'selection', 'stop', 'automatic_goto', 'tactics', 'continuation', 'autonomy')
            update = {k: copy.deepcopy(plan.get(k)) for k in fields}
            update['continuation'] = None
            update['tactics']['mode'] = 'recover'
            async def transport(command, payload, record, effort=effort, update=update):
                self.assertEqual(command[command.index('--effort')+1], effort)
                self.assertNotIn('strategy', json.loads(command[command.index('--json-schema')+1])['properties'])
                return {'structured_output': update}
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, patch('harness.hybrid_models.run_cli', transport):
                result = await Models(Path(directory), 'unused', 'claude', model='opus').claude(request)
                self.assertEqual(result['strategy'], plan['strategy'])
                self.assertEqual(result['memory'], plan['memory'])
                self.assertEqual(result['tactics']['mode'], 'recover')
            system, payload = claude_input(request)
            current = expand_payload(payload)['evidence']['current_observation']
            self.assertNotIn('skill_catalog', current['character'])
            self.assertEqual(current['character']['mutations'], state['observation']['character']['mutations'])
            self.assertEqual(json.loads(system.split('\nREFERENCE_DATA_JSON\n')[1])['skill_definitions'], [])
