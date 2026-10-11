"""Navigation capabilities remain visible; guarded execution preserves exclusions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from harness.hybrid import play, select_operation
from harness.hybrid_policy import History, candidates, evidence_state
from harness.hybrid_strategy import BuildReview, tactical_evidence
from tests.test_hybrid_autonomy import delegated, answer
from tests.test_hybrid_mapping import spatial


def corridor(length=4):
    state, plan, review = delegated()
    cells = {(x, y): '#' for x in range(39, 57) for y in range(10, 15)}
    cells.update({(x, 12): '.' for x in range(40, 41 + length)})
    spatial(state['observation'], cells)
    plan['target'] = {'x': 40 + length, 'y': 12}
    plan['autonomy']['avoid_cells'] = [{'x': 40, 'y': 10}]
    review.accept(state['observation'], plan['strategy'])
    return state, plan, review


def recorded(seq):
    data = json.loads((Path(__file__).parent / 'fixtures/jev_run11_navigation.json').read_text())[str(seq)]
    state, plan = data['state'], data['plan']
    history = History(events=data['events'])
    history.records = data['records']
    m = data['mapping']
    history.mapping.zones[m['zone']] = {
        'terrain': [list(row) for row in m['terrain']],
        'visits': {(x, y): int(n) for y, row in enumerate(m['visits']) for x, n in enumerate(row) if n != '0'},
        'failures': m['failed_routes'],
    }
    review = BuildReview()
    review.accept(state['observation'], plan['strategy'])
    return state, plan, history, review


def advance(state, choice, history, *, executed=True):
    after = copy.deepcopy(state)
    after['seq'] += 1
    if executed:
        after['observation']['vitals'].update(choice['destination'])
        after['observation']['vitals']['turn'] += 1
    history.record(state, choice['args'], {'executed': executed, 'reason': 'executed' if executed else 'blocked',
                                         'turns_elapsed': int(executed)}, after)
    return after


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    def test_both_models_see_native_availability_and_exclusion_reason(self):
        state, plan, review = delegated()
        history = History()
        for excluded in (False, True):
            plan['autonomy']['avoid_cells'] = [{'x': 45, 'y': 12}] if excluded else []
            evidence = evidence_state(state, plan, history, review)
            nav = evidence['derived'].get('navigation')
            self.assertIsNotNone(nav, 'Auto-explore capability and blockers must be public evidence')
            self.assertEqual(nav['explore']['available'], not excluded)
            self.assertEqual(nav['explore']['reasons'], ['spatial_exclusions'] if excluded else [])
            self.assertEqual(tactical_evidence(evidence)['derived']['navigation'], nav)
            self.assertEqual(any(c['args']['action'] == 'explore' for c in candidates(state, plan, history=history)),
                             nav['explore']['available'])

    def test_native_blockers_are_explained_without_becoming_choices(self):
        for change, reason in (('world', 'world_map'), ('enemy', 'visible_hostile'),
                               ('hp', 'low_hp'), ('effect', 'unknown_effect'), ('directions', 'direction_limits')):
            state, plan, review = delegated()
            obs = state['observation']
            if change == 'world': obs['place']['world_map'] = True
            elif change == 'enemy': obs['threats'] = [{'id': 'e1', 'name': 'croc', 'x': 60, 'y': 12, 'hostile': True}]
            elif change == 'hp': obs['vitals']['hp'] = 1
            elif change == 'effect': obs.setdefault('status', {})['effects'] = ['unclassified curse']
            else: plan['tactics']['allowed_directions'] = ['N']
            with self.subTest(change=change):
                nav = evidence_state(state, plan, History(), review)['derived'].get('navigation')
                self.assertIsNotNone(nav)
                self.assertIn(reason, nav['explore']['reasons'])
                self.assertFalse(nav['explore']['available'])

    def test_recorded_exploration_offers_a_route_to_a_reachable_frontier(self):
        state, plan, history, review = recorded(194)
        options = candidates(state, plan, history=history)
        guarded = [c for c in options if c.get('navigation')]
        self.assertEqual(len(guarded), 1, 'The real run must have an alternative to unguided walking')
        route = guarded[0]['navigation']
        self.assertEqual(route['purpose'], 'explore')
        self.assertEqual(route['target'], {'x': 28, 'y': 11})
        self.assertFalse(any(p in plan['autonomy']['avoid_cells'] for p in route['path']))
        self.assertFalse(any(c['args']['action'] in ('explore', 'goto') for c in options))

    async def test_unreachable_recorded_target_is_reviewed_before_another_oscillation(self):
        state, plan, history, review = recorded(276)
        async def jev(request):
            self.fail('The recorded unreachable goal must not produce another arbitrary step')
        async def claude(request):
            self.assertEqual(request['reason'], 'navigation_target_unreachable')
            self.assertEqual(request['decision_scope'], 'local')
            return plan | {'selection': None}
        choice, _, audit = await select_operation(state, plan, history, jev, claude, review=review)
        self.assertIsNone(choice)
        self.assertEqual(audit['actor'], 'claude')

    async def test_jev_starts_route_and_executor_observes_each_step_with_a_finite_budget(self):
        state, plan, review = corridor(14)
        history, calls = History(), []
        async def jev(request):
            calls.append(request)
            chosen = next((c for c in request['questions']['action']['criteria'].values() if c.get('navigation')), None)
            self.assertIsNotNone(chosen)
            return answer(request, chosen['args'])
        async def claude(request):
            self.fail('Safe approved navigation must not need another upper review')
        for index in range(13):
            choice, _, audit = await select_operation(state, plan, history, jev, claude, review=review)
            self.assertEqual(choice['args'], {'action': 'move', 'dir': 'E'})
            self.assertEqual(audit['actor'], 'jev' if index in (0, 12) else 'plan_executor')
            state = advance(state, choice, history)
        self.assertEqual(len(calls), 2)

    async def test_play_records_individual_guarded_moves_without_native_macro_dispatch(self):
        state, plan, _ = corridor()
        class Models:
            claude_calls = 0
            jev_calls = 0
            async def claude(self, request):
                self.claude_calls += 1
                return copy.deepcopy(plan)
            async def jev(self, request):
                self.jev_calls += 1
                c = next(c for c in request['questions']['action']['criteria'].values() if c.get('navigation'))
                return answer(request, c['args'])
        async def call(name, **args):
            if name == 'get_state':
                return copy.deepcopy(state)
            if name == 'act':
                self.assertEqual(args, {'expect_seq': state['seq'], 'action': 'move', 'dir': 'E'})
                state['seq'] += 1
                state['observation']['vitals']['x'] += 1
                state['observation']['vitals']['turn'] += 1
                return {'ok': True}
            if name == 'wait_for_turn':
                return {'completed': True, 'result': {'executed': True, 'reason': 'executed', 'turns_elapsed': 1}}
            raise AssertionError(name)
        models = Models()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            report = await play(call, models, path, max_actions=3, duration=2)
            decisions = [json.loads(p.read_text()) for p in sorted(path.glob('decision-*.json'))]
            self.assertEqual([d['actor'] for d in decisions if d.get('dispatch', {}).get('ok')],
                             ['jev', 'plan_executor', 'plan_executor'])
        self.assertEqual(report['accepted_actions'], 3)
        self.assertIsNone(report['pending_seq'])
        self.assertEqual((models.claude_calls, models.jev_calls), (1, 1))

    async def test_route_cancels_on_new_danger_failed_step_or_policy_change(self):
        for change in ('enemy', 'hp', 'failed', 'exclusion', 'modal', 'stale', 'hazard', 'expiry', 'zone', 'unseen', 'occupied'):
            state, plan, review = corridor()
            history = History()
            async def first_jev(request):
                chosen = next((c for c in request['questions']['action']['criteria'].values() if c.get('navigation')), None)
                self.assertIsNotNone(chosen)
                return answer(request, chosen['args'])
            async def claude(request, plan=plan):
                return plan | {'selection': None}
            choice, _, _ = await select_operation(state, plan, history, first_jev, claude, review=review)
            after = advance(state, choice, history, executed=change != 'failed')
            if change == 'enemy': after['observation']['threats'] = [{'id': 'e1', 'name': 'croc', 'x': 42, 'y': 12, 'hostile': True}]
            elif change == 'hp': after['observation']['vitals']['hp'] = 1
            elif change == 'exclusion': plan['autonomy']['avoid_cells'].append({'x': 42, 'y': 12})
            elif change == 'modal': after['modal'] = {'type': 'popup', 'choices': [{'id': 'ok', 'label': 'OK'}]}
            elif change == 'stale': after['seq'] += 2
            elif change == 'hazard': after['observation'].setdefault('status', {})['effects'] = ['unclassified curse']
            elif change == 'expiry': plan['autonomy']['max_steps'] = 1
            elif change == 'zone': after['observation']['vitals']['zone'] += '.new'
            elif change == 'unseen':
                spatial(after['observation'], {(41, 12): '.'})
            elif change == 'occupied':
                after['observation']['threats'] = [{'id': 'e1', 'name': 'farmer', 'x': 42, 'y': 12, 'hostile': False}]
            async def next_jev(request, change=change):
                return answer(request, {'response': {'choice': 'ok'}} if change == 'modal' else {'action': 'wait'})
            with self.subTest(change=change):
                _, _, audit = await select_operation(after, plan, history, next_jev, claude, review=review)
                self.assertNotEqual(audit['actor'], 'plan_executor')

    def test_blocked_step_is_not_advertised_as_a_guarded_route(self):
        state, plan, review = corridor()
        history = History()
        after = advance(state, {'args': {'action': 'move', 'dir': 'E'}, 'destination': {'x': 41, 'y': 12}},
                        history, executed=False)
        nav = evidence_state(after, plan, history, review)['derived']['navigation']
        self.assertFalse(nav['guarded_route']['available'])
        self.assertIn('previous_step_blocked', nav['guarded_route']['reasons'])
        self.assertFalse(any(c.get('navigation') for c in candidates(after, plan, history=history)))

    def test_route_does_not_cross_exclusions_liquids_doors_or_unknown_cells(self):
        for kind in ('.', '~', '+', '?'):
            state, plan, review = corridor()
            cells = {(x, y): '#' for x in range(39, 46) for y in range(10, 15)}
            cells.update({(40, 12): '.', (41, 12): '.', (42, 12): kind, (43, 12): '.', (44, 12): '.',
                          (41, 13): '.', (42, 14): '.', (43, 13): '.'})
            spatial(state['observation'], cells)
            if kind == '.': plan['autonomy']['avoid_cells'] = [{'x': 42, 'y': 12}]
            options = candidates(state, plan, history=History())
            route = next((c.get('navigation') for c in options if c.get('navigation')), None)
            with self.subTest(kind=kind):
                self.assertIsNotNone(route)
                self.assertNotIn({'x': 42, 'y': 12}, route['path'])
