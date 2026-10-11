"""Expose native navigation limits and bounded, observed alternatives to opaque macros."""
import copy
from collections import deque

from harness.hybrid_autonomy import excluded_cells
from harness.hybrid_hazards import assess_hazards
from harness.hybrid_mapping import WALKABLE, current_terrain, neighbors
from harness.hybrid_strategy import safe_to_review

OFFSETS = {'N': (0, -1), 'NE': (1, -1), 'E': (1, 0), 'SE': (1, 1),
           'S': (0, 1), 'SW': (-1, 1), 'W': (-1, 0), 'NW': (-1, -1)}


def _route(obs, grid, target, excluded, directions):
    start = (obs['vitals']['x'], obs['vitals']['y'])
    goal = (target['x'], target['y'])
    blocked = {(c['x'], c['y']) for c in excluded}
    blocked.update((t['x'], t['y']) for t in obs['threats'])
    offsets = {OFFSETS[d] for d in directions} if directions else set(OFFSETS.values())
    previous = {start: None}
    queue = deque([start])
    while queue and goal not in previous:
        here = queue.popleft()
        for x, y in neighbors(here):
            cell = (x, y)
            if (cell in previous or cell in blocked or grid[y][x] not in WALKABLE
                    or (x-here[0], y-here[1]) not in offsets):
                continue
            previous[cell] = here
            queue.append(cell)
    if goal not in previous:
        return []
    path = []
    while goal != start:
        path.append({'x': goal[0], 'y': goal[1]})
        goal = previous[goal]
    return list(reversed(path))


def navigation_status(state, plan, history):
    obs = state['observation']
    v = obs['vitals']
    tactics = plan.get('tactics', {})
    target = plan.get('target') if plan.get('zone') in (None, v['zone']) else None
    excluded = excluded_cells(obs, plan, history)
    risk = assess_hazards(obs)
    reasons = []
    for condition, reason in (("modal" in state, 'modal'),
                              (obs.get('place', {}).get('world_map'), 'world_map'),
                              (any(t['hostile'] for t in obs['threats']), 'visible_hostile'),
                              (v['hp'] * 4 <= v['max_hp'], 'low_hp'),
                              (risk['priority'] >= 2, 'hazard'),
                              (risk['unknown_effects'], 'unknown_effect')):
        if condition:
            reasons.append(reason)
    native_reasons = reasons + (['direction_limits'] if tactics.get('allowed_directions') else [])
    if excluded:
        native_reasons.append('spatial_exclusions')
    goto_reasons = list(native_reasons)
    if target is None:
        goto_reasons.append('no_target')
    elif (v['x'], v['y']) == (target['x'], target['y']):
        goto_reasons.append('target_reached')
    elif not (0 <= target['x'] < 80 and 0 <= target['y'] < 25) or obs['map'][target['y']][target['x']] == ' ':
        goto_reasons.append('target_not_known')
    result = {'explore': {'available': not native_reasons, 'reasons': native_reasons},
              'goto': {'available': not goto_reasons, 'reasons': goto_reasons},
              'guarded_route': {'available': False, 'reasons': []}, 'preferred': None,
              'meaning': 'Availability is not permission. Only candidate IDs are executable. Native macros cannot honor excluded cells. Guarded routes use ordinary moves, observe every step, and require active mission permission.'}
    if tactics.get('mode') not in ('travel', 'explore'):
        result['guarded_route']['reasons'] = ['not_navigation_mode']
        return result
    if result['goto']['available'] and target:
        result['preferred'] = 'goto'
    elif result['explore']['available']:
        result['preferred'] = 'explore'
    blocked = list(reasons)
    if not plan.get('autonomy') or plan.get('zone') != v['zone'] or plan.get('stop'):
        blocked.append('no_mission_permission')
    if not history or 'spatial' not in obs:
        blocked.append('no_spatial_memory')
    if not excluded and not tactics.get('allowed_directions'):
        blocked.append('no_route_constraints')
    if blocked:
        result['guarded_route']['reasons'] = blocked
        return result
    mapping = history.mapping.evidence(obs, target, excluded)
    goals = [target] if target else [{'x': f['x'], 'y': f['y']} for f in mapping['frontiers']
                                   if (f['x'], f['y']) != (v['x'], v['y'])]
    for goal in goals:
        path = _route(obs, mapping['terrain'], goal, excluded, tactics.get('allowed_directions', []))
        if not path:
            continue
        first = path[0]
        if any(OFFSETS.get(action.get('dir')) == (first['x']-v['x'], first['y']-v['y'])
               for action in history.blocked_moves(obs)):
            result['guarded_route']['reasons'] = ['previous_step_blocked']
            return result
        if (current_terrain(obs, **first) not in ('.', '<', '>')
                or obs['spatial']['visibility'][first['y']][first['x']] != 'v'):
            result['guarded_route']['reasons'] = ['next_step_not_visible']
            return result
        result['guarded_route'] = {'available': True, 'reasons': [], 'purpose': 'goto' if target else 'explore',
                                   'target': goal, 'path': path[:12], 'path_distance': len(path), 'max_steps': 12}
        result['preferred'] = 'guarded_route'
        return result
    reason = 'target_unreachable' if target else 'no_reachable_frontier'
    if target and (target['x'], target['y']) == (v['x'], v['y']):
        reason = 'target_reached'
    result['guarded_route']['reasons'] = [reason]
    return result


def remember_navigation(history, state, plan, choice):
    route = choice.get('navigation')
    history.navigation = None
    if route and len(route['path']) > 1:
        history.navigation = {'seq': state['seq'] + 1, 'expected': choice['destination'],
                              'zone': state['observation']['vitals']['zone'],
                              'hp': state['observation']['vitals']['hp'], 'plan': copy.deepcopy(plan),
                              'route': copy.deepcopy(route) | {'path': route['path'][1:]}}


def guarded_step(state, plan, history, options):
    saved = history.navigation
    history.navigation = None
    if not saved or 'modal' in state:
        return None
    obs = state['observation']
    v = obs['vitals']
    last = history.records[-1] if history.records else None
    if (state['seq'] != saved['seq'] or plan != saved['plan'] or v['zone'] != saved['zone']
            or {k: v[k] for k in ('x', 'y')} != saved['expected'] or v['hp'] < saved['hp']
            or obs.get('place', {}).get('world_map') or not safe_to_review(obs) or history.problem()
            or not last or last['seq'] != state['seq'] - 1 or last['result'].get('executed') is not True):
        return None
    position = saved['route']['path'][0]
    if (current_terrain(obs, **position) not in ('.', '<', '>')
            or obs['spatial']['visibility'][position['y']][position['x']] != 'v'):
        return None
    choice = next((c for c in options if c['args'].get('action') == 'move' and c.get('destination') == position
                   and not c.get('occupants')), None)
    if choice is None:
        return None
    goal = saved['route']['target']
    return choice | {'navigation': saved['route'],
                     'label': f"Continue guarded {saved['route']['purpose']} route to ({goal['x']}, {goal['y']})"}
