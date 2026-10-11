"""Public-effect priorities backed by the reviewed wiki catalogue.

Priorities are review urgency, not probabilities. Unknowns remain explicit.
See docs/jev-hazard-policy.md and docs/jev-status-catalog.md for coverage limits.
"""

import json
from pathlib import Path
import re

WIKI = 'https://wiki.cavesofqud.com/wiki/'
CATALOG = json.loads(Path(__file__).with_name('hybrid_effects.json').read_text())
EFFECTS = CATALOG['effects']
LIQUIDS = CATALOG['liquids']
LIQUID_WORDS = {word for liquid in LIQUIDS for alias in liquid['aliases']
                for word in re.findall(r'[a-z]+', alias)}


def plain(text):
    while '{{' in text:
        changed = re.sub(r'\{\{[^{}|]+\|([^{}]*)\}\}', r'\1', text)
        if changed == text:
            break
        text = changed
    return re.sub(r'\s+', ' ', text).strip().lower()


def has(text, pattern):
    return re.search(r'\b(?:' + pattern + r')\b', text) is not None


def effect_entry(name):
    for prefix, canonical in (('sitting on ', 'sitting'), ('enclosed in ', 'enclosed')):
        if name.startswith(prefix):
            return EFFECTS[canonical]
    return EFFECTS.get(name)


def liquid_entries(text):
    return [liquid for liquid in LIQUIDS
            if any(has(text, re.escape(alias)) for alias in liquid['aliases'])]


def is_coating(name, description):
    return ('covered in ' in description or 'stained with ' in description or 'stained by ' in description
            or bool(liquid_entries(name)) or has(name, 'covered|coated|stained'))


def tonic_cautions(obs):
    """Known inventory facts inform a choice; carrying a tonic is not exposure."""
    character = obs.get('character', {})
    allergy = any(plain(m['name']) in ('tonic allergy', 'tonic allergy (d)')
                  for m in character.get('mutations', []))
    cautions = []
    for item in obs.get('kit', []):
        name = plain(item['name'])
        for tonic in CATALOG['tonics']:
            if not has(name, re.escape(tonic['name'])):
                continue
            cautions.append({'item_id': item['id'], 'name': tonic['name'], 'note': tonic['note'],
                             'genotype': character.get('genotype'), 'tonic_allergy': allergy,
                             'combination': ('This tonic is exempt from overdose according to its wiki entry.'
                                             if tonic['name'] == "eaters' nectar injector" else
                                             'Before use, check active tonic effects and Juicer. Mutants can react adversely even to a single tonic; unknown active counts are not zero.'),
                             'sources': tonic['sources'] + ([WIKI + 'Tonic_Allergy'] if allergy else [])})
    return cautions


def assess_hazards(obs):
    status = obs.get('status', {})
    details = {plain(d['name']): plain(d['description']) for d in status.get('effect_details', [])}
    # Repeated rendered labels are not independent damage sources.
    effects = list(dict.fromkeys(plain(e) for e in status.get('effects', [])))
    if status.get('on_fire') and 'burning' not in effects:
        effects.append('burning')
    if status.get('frozen') and 'frozen' not in effects:
        effects.append('frozen')
    matches, unknown, damage, restraint, fuels = [], [], [], [], []
    navigation, tags, coatings = [], set(), []
    hostile = any(t['hostile'] for t in obs['threats'])
    v = obs['vitals']

    def add(rule, priority, reason, evidence, *pages, sources=()):
        matches.append({'id': rule, 'priority': priority, 'reason': reason, 'evidence': evidence,
                        'sources': list(sources) + [WIKI + p for p in pages]})

    for name in effects:
        description = details.get(name, '')
        entry = effect_entry(name)
        if entry and 'coating' not in entry['tags']:
            effect_tags = entry['tags']
            tags.update(effect_tags)
            if 'no_fast_travel' in effect_tags:
                navigation.append('no_fast_travel')
            if 'damage' in effect_tags:
                damage.append(name)
            if 'restraint' in effect_tags:
                restraint.append(name)
            rule = ('ongoing_damage' if 'damage' in effect_tags else
                    'impaired_action' if 'restraint' in effect_tags else 'effect_' + entry['category'])
            add(rule, entry['priority'], entry['note'], [name, description], sources=entry['sources'])
            # Furniture descriptions disclose conditional damage. Do not assume every
            # enclosure/chair injures the player, or infer its hidden numeric level.
            if entry['category'] == 'action_limit' and ('ongoing damage' in description or
                                                       'periodic damage' in description):
                damage.append(name)
                add('furniture_damage', 3, 'Public furniture description warns of damage.', [name, description],
                    'Enclosed', 'Sitting')
        elif has(name, 'leaking|oozing|fluxing') and 'damage per turn' in description:
            damage.append(name)
            add('ongoing_damage', 3, 'Public description identifies ongoing loss.', [name, description], 'Bleeding')
        elif is_coating(name, description):
            coatings.append(('body', name, description))
        elif name in ('defensive stance', 'aggressive stance', 'dueling stance', 'wading', 'swimming',
                       'well fed', 'sated', 'quenched', 'recuperating', 'basking', 'meditating'):
            continue
        else:
            unknown.append(name)

    slots = {item['id']: item.get('slot') for item in obs.get('kit', [])}
    for item in obs.get('item_details', []):
        if slots.get(item['id']) is None:
            continue
        for effect in item.get('effect_details', []):
            name, description = plain(effect['name']), plain(effect['description'])
            scope = 'equipped:' + item['id']
            if name == 'burning':
                add('burning_equipment', 3, 'Equipped item is burning.', [scope, name], 'Burning')
            elif name == 'coated in plasma' or name in ('broken', 'rusted', 'pulsed'):
                entry = EFFECTS[name]
                add('equipment_condition', entry['priority'], entry['note'], [scope, name, description],
                    sources=entry['sources'])
            elif is_coating(name, description):
                coatings.append((scope, name, description))

    known_words = LIQUID_WORDS | {'covered', 'coated', 'stained', 'encrusted', 'in', 'with', 'by', 'liquid'}
    for scope, name, description in coatings:
        liquids = liquid_entries(name + ' ' + description)
        if not liquids or set(re.findall(r'[a-z]+', name)) - known_words:
            unknown.append(scope + ': ' + name)
        stained = 'stained' in name or 'stained with ' in description or 'stained by ' in description
        if stained:
            add('coating_context', 1, 'Dry staining is not current damaging liquid contact.',
                [scope, name, description], 'Stained_by_liquid')
            continue
        liquid_tags = {tag for liquid in liquids for tag in liquid['tags']}
        sources = sorted({source for liquid in liquids for source in liquid['sources']})
        if 'volatile' in liquid_tags or 'transforming' in liquid_tags or 'damage' in liquid_tags:
            priority = 4 if 'volatile' in liquid_tags else 3
            add('dangerous_contact', priority, ' '.join(liquid['note'] for liquid in liquids),
                [scope, name, description], sources=sources)
        elif 'fuel' in liquid_tags:
            fuels.append(scope + ': ' + name)
            add('flammable_coating', 1, 'Combustible coating is contextual; verify ignition separately.',
                [scope, name, description], sources=sources)
        else:
            add('coating_context', 1, ' '.join(liquid['note'] for liquid in liquids) or
                'Unidentified coating; its safety has not been established.', [scope, name, description], sources=sources)

    if fuels and ('burning' in effects or any(m['id'] == 'burning_equipment' for m in matches)):
        add('fire_and_fuel', 3, 'Burning and combustible coating coexist; no extra damage multiplier is assumed.',
            fuels, 'Burning', 'Oil', 'Asphalt')
    if damage and v['hp'] / max(1, v['max_hp']) <= .35:
        add('low_hp_damage', 4, 'Low HP overlaps ongoing damage; ordinary resting may not recover HP.', damage, 'Bleeding', 'Poisoned')
    if len(set(damage)) > 1:
        add('stacked_damage', 4, 'Multiple distinct visible damage effects can compound.', damage, 'Bleeding')
    if restraint and (hostile or damage):
        add('restraint_and_danger', 4, 'Impaired actions overlap visible hostiles or ongoing damage.', restraint, 'Stuck', 'Prone', 'Frozen')
    if hostile and tags.intersection(('perception', 'mobility', 'defense')):
        add('impairment_and_hostile', 3, 'Perception, escape or defenses are impaired while an enemy is visible.',
            [name for name in effects if effect_entry(name) and
             set(effect_entry(name)['tags']).intersection(('perception', 'mobility', 'defense'))], 'Confused', 'Hobbled', 'Cleaved')
    if 'plasma' in tags and ('burning' in effects or 'frozen' in effects):
        add('plasma_and_temperature', 4, 'Plasma vulnerability overlaps active burning/freezing; passive normalization is unavailable.',
            ['coated in plasma'], 'Coated_in_plasma')
    if 'recovery' in tags and 'recovery_block' in tags:
        add('recovery_suppressed', 3, 'A healing effect is active but poison/illness reduces recovery; inspect actual HP change.',
            [name for name in effects if effect_entry(name) and 'recovery_block' in effect_entry(name)['tags']], 'Ill', 'Poisoned')

    for liquid in status.get('nearby_liquids', []):
        name = plain(liquid['name'])
        here = (liquid['x'], liquid['y']) == (v['x'], v['y'])
        entries = liquid_entries(name)
        terrain_words = LIQUID_WORDS | {'pool', 'pools', 'puddle', 'puddles', 'of', 'and', 'liquid',
                                       'deep', 'shallow', 'fresh', 'a', 'patch', 'stream', 'river', 'dram', 'drams'}
        if not entries or set(re.findall(r'[a-z]+', name)) - terrain_words:
            unknown.append('terrain: ' + name)
        liquid_tags = {tag for entry in entries for tag in entry['tags']}
        sources = sorted({source for entry in entries for source in entry['sources']})
        if 'volatile' in liquid_tags:
            add('volatile_liquid_terrain', 4, 'Visible open neutron flux requires urgent avoidance; this is not a carried container.', [liquid], sources=sources)
        elif 'damage' in liquid_tags or 'transforming' in liquid_tags:
            add('liquid_terrain', 3 if here else 2, ' '.join(entry['note'] for entry in entries), [liquid], sources=sources)
            if here and 'plasma' in tags and any(entry['name'] == 'lava' for entry in entries):
                add('plasma_and_temperature', 4, 'Plasma vulnerability overlaps current lava contact.', [liquid], 'Coated_in_plasma', 'Lava')
        elif 'exposure' in liquid_tags:
            add('harmful_liquid_terrain', 2, 'Prone contact or ingestion may cause disease, poison or corrosion.', [liquid], sources=sources)
            if here and 'prone' in effects:
                add('prone_harmful_liquid', 4, 'Prone in harmful liquid permits additional exposure; verify the actual resulting effect.', [liquid], 'Prone')
        elif liquid_tags.intersection(('slippery', 'sticky')):
            add('movement_liquid', 2 if hostile else 1, 'Open liquid terrain can impair movement; depth and immunity remain contextual.', [liquid], sources=sources)
        elif 'cooling' in liquid_tags and here and 'frozen' in effects:
            add('cold_liquid_and_frozen', 4, 'Already frozen in cooling liquid; a healing benefit does not establish safety.', [liquid], sources=sources)
        elif 'spawning' in liquid_tags:
            add('reactive_liquid_terrain', 2, 'Mixed primordial soup may produce hostile sludge; mixture volume is not observed.', [liquid], sources=sources)
        elif entries:
            add('liquid_context', 1, ' '.join(entry['note'] for entry in entries), [liquid], sources=sources)
    return {'policy_version': 2, 'scale': '0 routine, 1 contextual, 2 caution, 3 urgent, 4 critical; heuristic, not a probability',
            'priority': max((m['priority'] for m in matches), default=0), 'matches': matches,
            'navigation_constraints': navigation, 'unknown_effects': unknown,
            'consumable_cautions': tonic_cautions(obs), 'coverage': CATALOG['coverage']}


def hazard_key(risk):
    """Acknowledge named conditions, not every changing dram, duration or message."""
    return sorted((m['id'], m['priority'], m['evidence'][0] if m['evidence'] and
                   isinstance(m['evidence'][0], str) else '')
                  for m in risk['matches'] if m['priority'] >= 2), sorted(risk['unknown_effects'])
