"""Remember only observed spatial facts; paths are advice, never a hidden-world oracle."""
from collections import deque

DIRECTIONS = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy]
WALKABLE = '.<>'


def neighbors(cell):
    x, y = cell
    return [(x+dx, y+dy) for dx, dy in DIRECTIONS if 0 <= x+dx < 80 and 0 <= y+dy < 25]


def distances(start, walkable):
    if start not in walkable:
        return {}
    result = {start: 0}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for nxt in neighbors(cell):
            if nxt in walkable and nxt not in result:
                result[nxt] = result[cell] + 1
                queue.append(nxt)
    return result


def current_terrain(obs, x, y):
    spatial = obs.get('spatial')
    return spatial['terrain'][y][x] if spatial else None


class SpatialMemory:
    def __init__(self):
        self.zones = {}
        self.last_position = None

    def observe(self, obs):
        v = obs['vitals']
        name = v['zone']
        if name not in self.zones:
            if len(self.zones) >= 32:
                del self.zones[next(iter(self.zones))]
            self.zones[name] = {'terrain': [['?'] * 80 for _ in range(25)],
                                'visits': {}, 'failures': []}
        zone = self.zones[name]
        spatial = obs.get('spatial')
        if spatial:
            for y, row in enumerate(spatial['visibility']):
                for x, visibility in enumerate(row):
                    if visibility == 'v':
                        zone['terrain'][y][x] = spatial['terrain'][y][x]
        position = (name, v['x'], v['y'])
        if self.last_position != position:
            cell = position[1:]
            zone['visits'][cell] = zone['visits'].get(cell, 0) + 1
            self.last_position = position
        return zone

    def record(self, before, action, result, after):
        zone = self.observe(before)
        if (action.get('action') in ('move', 'goto', 'explore')
                and (result.get('executed') is False or result.get('reason') in ('STUCK', 'ENGINE_STOP'))):
            zone['failures'].append({'position': {k: before['vitals'][k] for k in ('x', 'y')},
                                     'action': action.copy(), 'reason': result.get('reason'),
                                     'turn': before['vitals']['turn']})
            zone['failures'] = zone['failures'][-32:]
        self.observe(after)

    def evidence(self, obs, target=None, excluded=()):
        zone = self.observe(obs)
        if 'spatial' not in obs:
            return {'available': False}
        grid, visits = zone['terrain'], zone['visits']
        here = (obs['vitals']['x'], obs['vitals']['y'])
        blocked = {(c['x'], c['y']) for c in excluded}
        walkable = {(x, y) for y, row in enumerate(grid) for x, kind in enumerate(row)
                    if kind in WALKABLE and (x, y) not in blocked}
        # The current occupied cell may be an overlay or excluded damage endpoint.
        walkable.add(here)
        reachable = distances(here, walkable)
        frontiers = [cell for cell in reachable
                     if any(grid[y][x] == '?' for x, y in neighbors(cell))]
        frontiers.sort(key=lambda c: (reachable[c] + visits.get(c, 0) * 3, reachable[c], c))
        target_distances = distances((target['x'], target['y']), walkable) if target else {}
        dead_ends = [c for c in reachable if c not in frontiers
                    and len([n for n in neighbors(c) if n in walkable]) <= 1]
        return {'available': 'spatial' in obs, 'zone': obs['vitals']['zone'],
                'terrain': [''.join(row) for row in grid],
                'visits': [''.join(str(min(9, visits.get((x, y), 0))) for x in range(80)) for y in range(25)],
                'frontiers': [{'x': x, 'y': y, 'path_distance': reachable[(x, y)],
                               'visits': visits.get((x, y), 0)} for x, y in frontiers[:12]],
                'frontier_count': len(frontiers),
                'dead_ends': [{'x': x, 'y': y} for x, y in sorted(dead_ends)[:32]],
                'failed_routes': list(zone['failures']),
                'target_path_distance': target_distances.get(here),
                'neighbor_paths': [{'x': x, 'y': y, 'target_distance': target_distances.get((x, y)),
                                    'visits': visits.get((x, y), 0)} for x, y in neighbors(here)],
                'meaning': 'Terrain: ? unknown, . no visible static obstruction, # visible solid, + door, ~ liquid, < up, > down. Stored terrain may be stale outside current visibility; it is not guaranteed passability. Visits count observed arrivals, not intermediate macro steps. Frontiers border unknown terrain; dead ends use known eight-neighbor connectivity. Paths exclude known solids, doors, liquids and policy exclusions; they do not prove safety.'}
