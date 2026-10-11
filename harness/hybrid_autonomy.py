"""Conditional mission permissions, independent of model confidence and transport."""
import math
import re

from harness.hybrid_hazards import assess_hazards, hazard_key, plain
from harness.hybrid_strategy import (character_summary, effective_tactics, hostile_distance, low_hp_acknowledged,
                                     safe_to_review)


SOFT_EVENTS = {
    'plan_expired', 'continuation_expired', 'continuation_new_threat',
    'continuation_threat_approaching', 'continuation_action_outside_contract',
    'continuation_resource_changed', 'navigation_constraints_changed',
    'navigation_interrupted', 'navigation_danger', 'hostile_requires_replan',
    'avoidance_context_changed', 'threat_context_changed', 'recent_damage', 'large_damage',
    'no_progress', 'repeated_cycle',
}


def at_recovery_site(obs, plan):
    target = plan.get('target')
    return target is None or target == {k: obs['vitals'][k] for k in ('x', 'y')}


def recovery_pending(obs, plan):
    v = obs['vitals']
    target = min(plan.get('tactics', {}).get('recovery_hp_target') or v['max_hp'], v['max_hp'])
    return (plan.get('tactics', {}).get('mode') == 'recover' and v['hp'] < target
            and at_recovery_site(obs, plan)
            and not obs.get('place', {}).get('world_map') and safe_to_review(obs))


def excluded_cells(obs, plan, history):
    policy = plan.get('autonomy')
    if not policy or plan.get('zone') != obs['vitals']['zone']:
        return []
    cells = list(policy['avoid_cells'])
    if history:
        cells.extend(r['position'] for r in history.route_risks(obs) if r['damage_events'] >= 2)
    return cells


def spatially_blocked(obs, plan, history, candidate):
    cells = excluded_cells(obs, plan, history)
    action = candidate['args'].get('action')
    return bool(cells and (action in ('goto', 'explore')
                          or action == 'move' and candidate.get('destination') in cells))


def _healing_actions(obs, previous, policy):
    def identity(observation, detail):
        item = next((i for i in observation.get('kit', []) if i['id'] == detail['id']), {})
        return (detail.get('comparison_name', item.get('name')), detail.get('description'))
    approved = {identity(previous, d) for d in previous.get('item_details', [])
                if d['id'] in policy['healing_items']
                and re.search(r'\bheals\b|\brestores?\b.*\b(?:hp|hit points)\b', plain(d.get('description', '')))}
    return [{'action': action, 'item': d['id']} for d in obs.get('item_details', [])
            if identity(obs, d) in approved for action in d.get('actions', []) if action in ('eat', 'drink')]


def autonomy_status(state, plan, history, review):
    policy = plan.get('autonomy')
    def blocked(reason):
        return {'active': False, 'reason': reason}
    if not policy or 'modal' in state:
        return blocked('no_autonomy')
    obs = state['observation']
    v = obs['vitals']
    previous = review.reviewed_observation if review else None
    issued = plan.get('issued_seq')
    if previous is None or type(issued) is not int or plan.get('zone') != v['zone'] or plan.get('stop'):
        return blocked('autonomy_context_changed')
    if review.pending_reason(obs) or character_summary(obs) != character_summary(previous):
        return blocked('autonomy_build_changed')
    if obs.get('goals') != previous.get('goals'):
        return blocked('quest_progress_changed')
    if not 0 <= state['seq'] - issued < policy['max_steps']:
        return blocked('autonomy_review_due')
    risk = assess_hazards(obs)
    if (risk['priority'] >= 4 or risk['unknown_effects']
            or risk['priority'] >= 2 and hazard_key(risk) != hazard_key(assess_hazards(previous))):
        return blocked('autonomy_hazard_changed')
    recovering = plan.get('tactics', {}).get('mode') == 'recover'
    recovery_safe = (recovering and at_recovery_site(obs, plan) and not any(t['hostile'] for t in obs['threats'])
                     and risk['priority'] < 2 and not obs.get('place', {}).get('world_map'))
    recovery_target = min(plan.get('tactics', {}).get('recovery_hp_target') or v['max_hp'], v['max_hp'])
    if recovery_safe and v['hp'] >= recovery_target:
        return blocked('recovery_complete')
    problem = history.problem()
    resting = (recovery_safe and len(history.records) >= 3
               and all(r['action'].get('action') == 'rest' and r['result'].get('executed') is True
                       and (r['result'].get('turns_elapsed') or 0) > 0
                       and r['after']['hp'] >= r['before']['hp'] for r in history.records[-3:]))
    if problem and not (resting and problem in ('no_progress', 'repeated_cycle')):
        return blocked(problem)
    records = [r for r in history.records if r['seq'] >= issued]
    last = records[-1] if records else None
    if last and last['result'].get('executed') is not True:
        # A zero-turn blocked step can be locally detoured; other failures need review.
        if not (last['action'].get('action') == 'move' and last['result'].get('reason') == 'blocked'
                and last['result'].get('turns_elapsed') == 0):
            return blocked('autonomy_operation_failed')
    events = [e for e in history.events if e['kind'] == 'risk_outcome' and e['source']['seq'] > issued]
    if any(e['action'].get('action') in ('eat', 'drink', 'apply') for e in events):
        return blocked('autonomy_consumption_review')
    damage = max(sum(e['observed_hp_loss'] for e in events),
                 sum(max(0, r['before']['hp'] - r['after']['hp']) for r in records),
                 previous['vitals']['hp'] - v['hp'])
    largest = max([e['observed_hp_loss'] for e in events]
                  + [max(0, r['before']['hp'] - r['after']['hp']) for r in records], default=0)
    dangerous_loss = (damage > min(policy['max_damage'], math.floor(v['max_hp'] * .25))
                      or largest >= v['max_hp'] * .2 or largest > 0 and v['hp'] <= largest)
    low_hp = (v['hp'] <= policy['min_hp']
              or v['hp'] <= math.ceil(v['max_hp'] * .4) and not low_hp_acknowledged(obs, previous, plan))
    healing = _healing_actions(obs, previous, policy)
    if dangerous_loss or low_hp:
        if healing and v['hp'] / max(1, v['max_hp']) <= plan['tactics']['heal_hp_fraction']:
            return {'active': True, 'reason': 'autonomy_emergency_healing', 'healing_only': True,
                    'healing_actions': healing, 'damage_used': damage}
        return blocked('autonomy_damage_limit' if dangerous_loss else 'autonomy_hp_floor')
    close = [t for t in obs['threats'] if t['hostile']
             and hostile_distance(obs, t) <= plan.get('tactics', {}).get('danger_distance', 6)]
    if len(close) > 1 or any(plain(t['name']) not in {plain(n) for n in policy['combat_names']} for t in close):
        return blocked('autonomy_unreviewed_contact')
    if close and plan.get('tactics', {}).get('hostile_response') == 'replan':
        return blocked('hostile_requires_replan')
    if recovery_safe:
        return {'active': True, 'reason': 'mission_recovery', 'recovery_only': True,
                'recovery_hp_target': recovery_target, 'healing_actions': healing, 'healing_only': False}
    target = plan.get('target')
    fighting = close and effective_tactics(obs, plan).get('mode') == 'combat' and plan['tactics']['hostile_response'] == 'fight'
    if target and (v['x'], v['y']) == (target['x'], target['y']) and not fighting:
        return blocked('target_reached')
    return {'active': True, 'reason': 'mission_permission', 'steps_used': state['seq']-issued,
            'damage_used': damage, 'healing_actions': healing, 'healing_only': False}


def autonomous_action(state, plan, history, review, candidate):
    """Return a delegated category, or None to preserve ordinary upper ownership."""
    status = autonomy_status(state, plan, history, review)
    if not status['active']:
        return None
    obs = state['observation']
    args = candidate['args']
    if (args in status['healing_actions'] and obs['vitals']['hp'] / max(1, obs['vitals']['max_hp'])
            <= plan['tactics']['heal_hp_fraction']):
        return 'authorized_healing'
    if status['healing_only'] or spatially_blocked(obs, plan, history, candidate):
        return None
    if status.get('recovery_only'):
        return 'autonomous_recovery' if args.get('action') == 'rest' else None
    action = args.get('action')
    enemies = [t for t in obs['threats'] if t['hostile']]
    tactics = effective_tactics(obs, plan)
    if action == 'move' and args.get('dir') not in ('U', 'D'):
        position = candidate.get('destination')
        clear = (candidate['terrain'] in ('.', '<', '>') if 'terrain' in candidate
                 else candidate.get('glyph') in ('.', ',', "'", '`', '<', '>'))
        if not position or candidate.get('occupants') or not clear:
            return None
        # An unknown distant enemy may be bypassed, never approached into its review band.
        for enemy in enemies:
            distance = hostile_distance(obs, enemy, position)
            if plain(enemy['name']) not in {plain(n) for n in plan['autonomy']['combat_names']}:
                if distance <= tactics.get('danger_distance', 6):
                    return None
            separating = (tactics.get('mode') == 'retreat'
                          or tactics.get('mode') == 'avoid' and distance <= tactics.get('danger_distance', 6))
            if separating and distance < hostile_distance(obs, enemy):
                return None
        return 'autonomous_navigation'
    if (action == 'attack' and tactics.get('mode') == 'combat' and tactics.get('hostile_response') == 'fight'
            and len(candidate.get('occupants', [])) == 1 and candidate['occupants'][0]['hostile']
            and plain(candidate['occupants'][0]['name']) in {plain(n) for n in plan['autonomy']['combat_names']}):
        return 'autonomous_combat'
    if not enemies:
        if action in ('rest', 'wait'):
            return 'autonomous_recovery'
        if action in ('goto', 'explore') and tactics.get('mode') in ('travel', 'explore'):
            return 'autonomous_navigation'
    return None
