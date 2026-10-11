"""Shared terrain must remove invalid moves without inventing hidden knowledge."""
import copy
import unittest

from harness import wire
from harness.hybrid import select_operation
from harness.hybrid_policy import History, candidates, evidence_state
from harness.hybrid_strategy import tactical_evidence
from tests.test_hybrid_autonomy import delegated, answer
from tests.support import make_observation


def spatial(obs, cells):
    terrain = [['?'] * 80 for _ in range(25)]
    visibility = [['u'] * 80 for _ in range(25)]
    for (x, y), kind in cells.items():
        terrain[y][x] = kind
        visibility[y][x] = 'v'
    obs['spatial'] = {'terrain': [''.join(r) for r in terrain],
                      'visibility': [''.join(r) for r in visibility], 'nearby': []}


class MappingTests(unittest.IsolatedAsyncioTestCase):
    def test_optional_wire_field_retains_old_ledgers_and_rejects_hidden_terrain(self):
        obs = make_observation()
        wire.validate_observation(obs)
        spatial(obs, {(40, 12): '.', (41, 12): '#'})
        self.assertEqual(wire.validate_observation(obs)['spatial']['terrain'][12][41], '#')
        for mutate in ('hidden', 'width', 'symbol', 'nearby'):
            bad = copy.deepcopy(obs)
            s = bad['spatial']
            if mutate == 'hidden':
                s['visibility'][12] = 'u' * 80
            elif mutate == 'width':
                s['terrain'][0] = '?' * 79
            elif mutate == 'symbol':
                s['terrain'][0] = 'x' * 80
            else:
                s['nearby'] = [{'x': 79, 'y': 24, 'names': ['secret wall']}]
            with self.subTest(mutate=mutate), self.assertRaises(wire.WireError):
                wire.validate_observation(bad)

    def test_visible_wall_is_not_offered_but_door_and_zone_edge_remain(self):
        state, plan, _ = delegated()
        spatial(state['observation'], {(41, 12): '#', (39, 12): '+'})
        options = candidates(state, plan)
        self.assertFalse(any(c['args'] == {'action': 'move', 'dir': 'E'} for c in options))
        self.assertTrue(any(c['args'] == {'action': 'move', 'dir': 'W'} for c in options))
        state['observation']['vitals']['x'] = 0
        self.assertTrue(any(c['args'] == {'action': 'move', 'dir': 'W'} for c in candidates(state, plan)))

    async def test_current_clear_terrain_overrides_ambiguous_display_without_upper_call(self):
        state, plan, review = delegated()
        obs = state['observation']
        obs['map'][11] = obs['map'][11][:40] + '±' + obs['map'][11][41:]
        spatial(obs, {(40, 12): '.', (40, 11): '.'})
        async def jev(request):
            return answer(request, {'action': 'move', 'dir': 'N'})
        async def claude(request):
            self.fail('A visible clear cell must not escalate for its display glyph')
        _, _, audit = await select_operation(state, plan, History(), jev, claude, review=review)
        self.assertEqual(audit['actor'], 'jev')

    def test_mapping_retains_visits_and_known_terrain_across_zones_and_eight_record_window(self):
        state, plan, review = delegated()
        obs = state['observation']
        spatial(obs, {(40, 12): '.', (41, 12): '.', (42, 12): '#'})
        history = History()
        first = evidence_state(state, plan, history, review)
        self.assertIn('mapping', first['derived'])
        state['seq'] += 1
        obs['vitals']['x'] = 41
        evidence_state(state, plan, history, review)
        state['seq'] += 20
        obs['vitals']['zone'] = 'another-zone'
        spatial(obs, {(41, 12): '.'})
        evidence_state(state, plan, history, review)
        state['seq'] += 1
        obs['vitals']['zone'] = plan['zone']
        obs['vitals']['x'] = 40
        spatial(obs, {(40, 12): '.'})
        evidence = evidence_state(state, plan, history, review)
        mapping = evidence['derived']['mapping']
        self.assertEqual(mapping['terrain'][12][42], '#')
        self.assertEqual(mapping['visits'][12][40:42], '21')
        self.assertEqual(mapping, tactical_evidence(evidence)['derived']['mapping'])
        self.assertEqual(evidence_state(state, plan, history, review)['derived']['mapping']['visits'], mapping['visits'])
        history.reset()
        self.assertEqual(evidence_state(state, plan, history, review)['derived']['mapping']['terrain'][12][42], '?')

    def test_known_route_distance_respects_wall_detour_and_shares_frontiers(self):
        state, plan, review = delegated()
        obs = state['observation']
        cells = {(x,y): '#' for x in range(39,44) for y in range(10,15)}
        cells.update({(40,12):'.', (40,13):'.', (41,14):'.', (42,13):'.', (42,12):'.'})
        spatial(obs, cells)
        plan['target'] = {'x': 42, 'y': 12}
        history = History()
        mapping = evidence_state(state, plan, history, review)['derived'].get('mapping')
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping['target_path_distance'], 4)
        self.assertTrue(mapping['frontiers'])
        south = next(c for c in candidates(state, plan, history=history) if c['args'] == {'action':'move','dir':'S'})
        self.assertEqual(south['known_path_distance_to_target'], 3)

    def test_current_terrain_reopens_a_blocked_move_and_retains_failure_evidence(self):
        state, plan, review = delegated()
        obs = state['observation']
        spatial(obs, {(40,12):'.', (41,12):'#'})
        history = History()
        evidence_state(state, plan, history, review)
        after = copy.deepcopy(state)
        after['seq'] += 1
        history.record(state, {'action':'move','dir':'E'},
                       {'executed':False,'reason':'blocked','turns_elapsed':0}, after)
        spatial(after['observation'], {(40,12):'.', (41,12):'.'})
        mapping = evidence_state(after, plan, history, review)['derived']['mapping']
        self.assertEqual(mapping['terrain'][12][41], '.')
        self.assertEqual(mapping['failed_routes'][0]['reason'], 'blocked')
        self.assertTrue(any(c['args'] == {'action':'move','dir':'E'} for c in candidates(after, plan, history=history)))

    async def test_liquid_or_unknown_is_not_delegated_just_because_display_is_floor(self):
        for kind in ('~', '?', '+'):
            state, plan, review = delegated()
            spatial(state['observation'], {(40,12):'.', (40,11):kind})
            calls = []
            async def jev(request):
                return answer(request, {'action':'move','dir':'N'})
            async def claude(request, calls=calls, plan=plan):
                calls.append(request)
                return plan | {'selection':None}
            await select_operation(state, plan, History(), jev, claude, review=review)
            with self.subTest(kind=kind):
                self.assertEqual(len(calls), 1)

    async def test_combat_position_arrival_does_not_end_approved_melee(self):
        state, plan, review = delegated()
        plan['target'] = {'x':40, 'y':12}
        plan['autonomy']['combat_names'] = ['snapjaw']
        state['observation']['threats'] = [{'id':'e1','name':'snapjaw','x':41,'y':12,'hostile':True}]
        async def jev(request):
            return answer(request, {'action':'attack','dir':'E'})
        async def claude(request):
            self.fail('Standing at an approved combat position is not objective completion')
        _,_,audit = await select_operation(state, plan, History(), jev, claude, review=review)
        self.assertEqual(audit['actor'], 'jev')
