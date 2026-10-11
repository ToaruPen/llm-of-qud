"""Jev needs current facts and bounded outcome evidence, not repeated full character snapshots."""
import copy
import json
from pathlib import Path
import unittest

from harness.hybrid_policy import History, evidence_state
from harness.hybrid_strategy import tactical_evidence
from tests.test_hybrid_autonomy import delegated
from tests.test_hybrid_mapping import spatial


class JevContextTests(unittest.TestCase):
    def test_growth_history_is_compact_without_losing_current_maps_or_danger(self):
        state, plan, review = delegated()
        spatial(state['observation'], {(40,12):'.', (41,12):'#'})
        evidence = evidence_state(state, plan, History(), review)
        evidence['recent_outcomes'] = [{'seq': i, 'action': {'action':'attack','dir':'E'},
            'result': {'executed':True}, 'before':{'hp':15-i}, 'after':{'hp':14-i},
            'character_change': {'before':{'description':'old build '*1000}, 'after':{'level':2}},
            'messages':['repeated text '*100], 'changes':{}, 'changed':True, 'combat_attempt':True}
            for i in range(8)]
        evidence['verified_events'] = [{'kind':'quest_dialogue', 'source':{'seq':i},
                                       'dialog_text':'old dialogue '*1000} for i in range(128)]
        original = copy.deepcopy(evidence)
        projected = tactical_evidence(evidence)
        self.assertLess(len(json.dumps(projected)), 30000)
        self.assertEqual(projected['current_observation'], original['current_observation'] | {
            'character':{k:v for k,v in original['current_observation']['character'].items() if k!='skill_catalog'}})
        self.assertEqual(projected['derived'], original['derived'] | {'effective_tactics':projected['derived']['effective_tactics']})
        self.assertEqual([(r['before']['hp'],r['after']['hp']) for r in projected['recent_outcomes']],
                         [(r['before']['hp'],r['after']['hp']) for r in original['recent_outcomes']])
        self.assertTrue(projected['recent_outcomes'][-1]['character_changed'])
        self.assertEqual(evidence, original)

    def test_actual_levelup_error_input_is_reduced_without_removing_current_terrain(self):
        path=Path(__file__).parent/'fixtures/jev_growth_context.json'
        original=json.loads(path.read_text())
        projected=tactical_evidence(original)
        self.assertLess(len(json.dumps(projected,ensure_ascii=False).encode()), 45000)
        self.assertEqual(projected['current_observation']['spatial'], original['current_observation']['spatial'])
        self.assertEqual(projected['derived']['mapping'], original['derived']['mapping'])
        self.assertEqual(projected['derived']['route_risks'], original['derived']['route_risks'])
        self.assertEqual(projected['derived']['survival'], original['derived']['survival'])
