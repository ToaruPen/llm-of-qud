"""Game <-> harness wire contract: strict parsing, validation and decision serialization.

Shared by the broker (which enforces the contract on live frames) and the verifier
(which re-checks the same shapes in the ledger). Standard library only.
"""

import hashlib
import json
import uuid

MAX_FRAME_BYTES = 1 << 20

ITEM_ACTIONS = ("eat", "drink", "apply", "get", "equip", "open")
GROWTH_ACTIONS = ("learn_skill", "raise_attribute")
ATTRIBUTES = ("Strength", "Agility", "Toughness", "Intelligence", "Willpower", "Ego")
ACTIONS = ("move", "attack", "wait", "explore", "goto", "rest", "talk") + ITEM_ACTIONS + GROWTH_ACTIONS
MACRO_ACTIONS = ("explore", "goto", "rest")
ATTACK_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
MOVE_DIRS = ATTACK_DIRS + ("U", "D")
EXPLORE_BUDGET_MIN = 1
EXPLORE_BUDGET_MAX = 40
MAP_ROWS = 25
MAP_COLS = 80
DIGEST_MAX = 12

REQUEST_KEYS = frozenset({"kind", "run_id", "seq", "observation", "telemetry"})
RESULT_KEYS = frozenset({
    "kind", "run_id", "seq", "action", "executed", "reason", "observation", "telemetry",
    "energy_before", "energy_after", "turns_elapsed", "steps",
})
HEARTBEAT_KEYS = frozenset({"kind", "run_id", "seq"})
OBSERVATION_KEYS = frozenset({"vitals", "threats", "digest", "map", "map_frame"})
# Optional, additive player-visible keys (inventory/equipment, own status, place).
# Absent in M1 ledgers, which therefore remain valid.
OPTIONAL_OBSERVATION_KEYS = frozenset({"kit", "status", "place", "ground", "goals", "item_details", "character", "spatial"})
GOALS_TEXT_MAX = 16384
KIT_MAX = 64
GROUND_MAX = 64
GROUND_ITEM_KEYS = frozenset({"id", "name", "x", "y"})
KIT_ITEM_KEYS = frozenset({"id", "name", "slot"})
STATUS_KEYS = frozenset({"effects", "food_water"})
STATUS_EFFECTS_MAX = 32
PLACE_KEYS = frozenset({"name", "world_map", "lost"})
VITALS_INT_KEYS = ("hp", "max_hp", "x", "y", "turn", "energy")
VITALS_KEYS = frozenset(VITALS_INT_KEYS + ("zone",))
THREAT_KEYS = frozenset({"id", "name", "wound", "x", "y", "hostile"})
TELEMETRY_COUNTERS = ("cta", "end_player_turns", "player_turn_entries", "ui_tasks", "unknown_tasks")
QUEUE_ENTRY_KEYS = frozenset({"task_id", "type", "method", "classification"})
RESULT_FIELD_KEYS = ("action", "executed", "reason", "energy_before", "energy_after",
                     "turns_elapsed", "steps")
# Lifecycle frames. A recovery reports that the game reloaded a save/checkpoint while
# request ``seq`` was current; a game_fault reports that the game cannot continue.
RECOVERY_FIELD_KEYS = ("recovery_id", "reason", "game_id", "save_file", "save_sha256",
                       "turn_before", "loaded_turn", "lost_turns")
RECOVERY_KEYS = frozenset({"kind", "run_id", "seq", *RECOVERY_FIELD_KEYS})
RECOVERY_SAVE_FILES = {"checkpoint_reload": "Checkpoint", "save_reload": "Primary"}
GAME_ID_MAX = 128
GAME_FAULT_KEYS = frozenset({"kind", "run_id", "seq", "reason"})
GAME_FAULT_REASON_MAX = 1024
# A suspension reports that the controlled game stopped running (e.g. it exited to the
# main menu) while request ``seq`` was open. Not terminal: only a verified reload
# (recovery of the same seq) or a game_fault may follow for that seq.
SUSPENDED_KEYS = frozenset({"kind", "run_id", "seq", "reason"})
SUSPENDED_REASONS = ("game_not_running",)
_HEX = frozenset("0123456789abcdef")


class WireError(ValueError):
    """A frame or ledger body does not match the wire contract."""


def _reject_constant(name):
    raise WireError(f"non-finite JSON number {name} is not allowed")


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise WireError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def loads_strict(text):
    """Parse JSON rejecting NaN/Infinity and duplicate object keys."""
    try:
        return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except WireError:
        raise
    except (ValueError, RecursionError) as exc:
        raise WireError(f"invalid JSON: {exc}") from None


def _require(condition, message):
    if not condition:
        raise WireError(message)


def _int(value, name, minimum=None):
    _require(type(value) is int, f"{name} must be an integer")
    if minimum is not None:
        _require(value >= minimum, f"{name} must be >= {minimum}")
    return value


def _str(value, name):
    _require(type(value) is str, f"{name} must be a string")
    return value


def _exact_keys(obj, keys, name):
    _require(isinstance(obj, dict), f"{name} must be an object")
    missing = sorted(keys - obj.keys())
    extra = sorted(obj.keys() - keys)
    _require(not missing and not extra, f"{name} keys mismatch (missing={missing}, extra={extra})")


def _uuid(value, name):
    _str(value, name)
    _require(0 < len(value) <= 64, f"{name} length out of range")
    try:
        return uuid.UUID(value)
    except ValueError:
        raise WireError(f"{name} must be a UUID string") from None


def _run_id(value):
    _uuid(value, "run_id")
    return value


def canonical_uuid(value, name="recovery_id"):
    """Canonical spelling used to index IDs (uuid.UUID accepts braces, urn: and no hyphens)."""
    return str(_uuid(value, name))


def sha256_hex(value, name):
    """Exactly 64 lowercase hex digits (int(x, 16) would also take '_' and uppercase)."""
    _require(type(value) is str and len(value) == 64 and set(value) <= _HEX,
             f"{name} must be 64 lowercase hex digits")
    return value


def _bounded_nonempty(value, name, limit):
    _str(value, name)
    _require(0 < len(value) <= limit, f"{name} must be 1..{limit} characters")
    return value


def _validate_optional(obs):
    if "item_details" in obs:
        details = obs["item_details"]
        _require(isinstance(details, list) and len(details) <= KIT_MAX, "invalid item_details")
        ids = {item.get("id") for item in obs.get("kit", []) if isinstance(item, dict)}
        seen = set()
        for item in details:
            _exact_keys(item, {"id", "description", "actions"} | (item.keys() & {"effect_details", "comparison_name"}), "item_details entry")
            if "comparison_name" in item:
                _bounded_nonempty(item["comparison_name"], "comparison_name", 8192)
            if "effect_details" in item:
                _validate_effect_details(item["effect_details"])
            _str(item["id"], "item_details.id")
            _require(item["id"] in ids and item["id"] not in seen, "unknown or duplicate item_details.id")
            seen.add(item["id"])
            _str(item["description"], "item_details.description")
            _require(len(item["description"]) <= 8192, "item_details.description too long")
            actions = item["actions"]
            _require(isinstance(actions, list) and len(actions) <= 5, "invalid item_details.actions")
            _require(all(type(a) is str and a in ITEM_ACTIONS and a != "get" for a in actions),
                     "unsupported item_details action")
            _require(len(set(actions)) == len(actions), "duplicate item_details action")
    if "goals" in obs:
        goals = obs["goals"]
        _exact_keys(goals, {"text", "truncated"}, "observation.goals")
        _str(goals["text"], "goals.text")
        _require(len(goals["text"]) <= GOALS_TEXT_MAX, "goals.text too long")
        _require(type(goals["truncated"]) is bool, "goals.truncated must be a boolean")
    if "ground" in obs:
        ground = obs["ground"]
        _require(isinstance(ground, list) and len(ground) <= GROUND_MAX,
                 f"observation.ground must be a list of at most {GROUND_MAX}")
        seen = set()
        for item in ground:
            _exact_keys(item, GROUND_ITEM_KEYS, "ground item")
            _require(item["id"] in tuple(f"p{n}" for n in range(1, GROUND_MAX + 1)), "invalid ground id")
            _require(item["id"] not in seen, "duplicate ground id")
            seen.add(item["id"])
            _str(item["name"], "ground name")
            _int(item["x"], "ground x", 0)
            _int(item["y"], "ground y", 0)
            _require(item["x"] < MAP_COLS and item["y"] < MAP_ROWS, "ground item outside map")
    if "kit" in obs:
        kit = obs["kit"]
        _require(isinstance(kit, list), "observation.kit must be a list")
        _require(len(kit) <= KIT_MAX, f"observation.kit has more than {KIT_MAX} items")
        seen = set()
        for i, item in enumerate(kit):
            name = f"observation.kit[{i}]"
            _exact_keys(item, KIT_ITEM_KEYS, name)
            _str(item["id"], f"{name}.id")
            _require(item["id"][:1] == "i" and item["id"][1:].isdigit(), f"{name}.id must look like i<N>")
            _require(item["id"] not in seen, f"{name}.id is duplicated")
            seen.add(item["id"])
            _str(item["name"], f"{name}.name")
            _require(item["slot"] is None or type(item["slot"]) is str, f"{name}.slot must be a string or null")
    if "status" in obs:
        status = obs["status"]
        _exact_keys(status, STATUS_KEYS | (status.keys() & {"effect_details", "on_fire", "frozen", "nearby_liquids"}), "observation.status")
        if "effect_details" in status:
            _validate_effect_details(status["effect_details"])
        for key in ("on_fire", "frozen"):
            if key in status:
                _require(type(status[key]) is bool, "status." + key + " must be boolean")
        if "nearby_liquids" in status:
            liquids = status["nearby_liquids"]
            _require(isinstance(liquids, list) and len(liquids) <= 9, "invalid nearby_liquids")
            for liquid in liquids:
                _exact_keys(liquid, {"x", "y", "name"}, "nearby liquid")
                _int(liquid["x"], "liquid x", 0)
                _int(liquid["y"], "liquid y", 0)
                _require(liquid["x"] < MAP_COLS and liquid["y"] < MAP_ROWS, "liquid outside map")
                _bounded_nonempty(liquid["name"], "liquid name", 512)
        effects = status["effects"]
        _require(isinstance(effects, list) and len(effects) <= STATUS_EFFECTS_MAX,
                 f"observation.status.effects must be a list of at most {STATUS_EFFECTS_MAX}")
        for i, effect in enumerate(effects):
            _str(effect, f"observation.status.effects[{i}]")
        _str(status["food_water"], "observation.status.food_water")
    if "place" in obs:
        place = obs["place"]
        _exact_keys(place, PLACE_KEYS, "observation.place")
        _str(place["name"], "observation.place.name")
        for key in ("world_map", "lost"):
            _require(type(place[key]) is bool, f"observation.place.{key} must be a boolean")


def validate_character(character):
    mutation_keys = {"genotype", "subtype", "mutation_points", "mutations", "mutations_truncated"}
    _exact_keys(character, {"level", "xp", "next_level_xp", "skill_points", "attribute_points",
                            "attributes", "owned_skills", "skill_catalog", "catalog_truncated"}
                | (mutation_keys if character.keys() & mutation_keys else set()), "character")
    if "mutations" in character:
        for key in ("genotype", "subtype"):
            _bounded_nonempty(character[key], "character." + key, 512)
        _int(character["mutation_points"], "mutation_points", 0)
        _require(type(character["mutations_truncated"]) is bool, "invalid mutations_truncated")
        mutations = character["mutations"]
        _require(isinstance(mutations, list) and len(mutations) <= 128, "invalid mutations")
        for mutation in mutations:
            _exact_keys(mutation, {"name", "level", "description", "level_text", "defect"}, "mutation")
            _bounded_nonempty(mutation["name"], "mutation.name", 512)
            _int(mutation["level"], "mutation.level", 0)
            _require(type(mutation["defect"]) is bool, "invalid mutation.defect")
            for key in ("description", "level_text"):
                _str(mutation[key], "mutation." + key)
                _require(len(mutation[key]) <= 4096, "mutation text too long")
    for key in ("level", "xp", "next_level_xp", "skill_points", "attribute_points"):
        _int(character[key], "character." + key, 1 if key == "level" else 0)
    _exact_keys(character["attributes"], set(ATTRIBUTES), "character.attributes")
    for name, stats in character["attributes"].items():
        _exact_keys(stats, {"base", "value"}, "character.attributes." + name)
        for value in stats.values():
            _int(value, "attribute value")
    owned = character["owned_skills"]
    _require(isinstance(owned, list) and len(owned) <= 512, "invalid owned_skills")
    for name in owned:
        _bounded_nonempty(name, "owned skill", 200)
    _require(len(set(owned)) == len(owned), "duplicate owned skill")
    _require(type(character["catalog_truncated"]) is bool, "invalid catalog_truncated")
    catalogue = character["skill_catalog"]
    _require(isinstance(catalogue, list) and len(catalogue) <= 512, "invalid skill_catalog")
    ids = set()
    for entry in catalogue:
        _exact_keys(entry, {"id", "name", "kind", "parent_id", "cost", "description", "requirements",
                            "owned", "eligible"}, "skill_catalog entry")
        for key, limit in (("id", 200), ("name", 512)):
            _bounded_nonempty(entry[key], "skill " + key, limit)
        _require(entry["id"] not in ids, "duplicate skill id")
        ids.add(entry["id"])
        _require(entry["kind"] in ("skill", "power"), "invalid skill kind")
        if entry["parent_id"] is not None:
            _bounded_nonempty(entry["parent_id"], "skill parent_id", 200)
        _int(entry["cost"], "skill cost")
        _str(entry["description"], "skill description")
        _require(len(entry["description"]) <= 4096, "skill description too long")
        requirements = entry["requirements"]
        _require(isinstance(requirements, list) and len(requirements) <= 32, "invalid skill requirements")
        for requirement in requirements:
            _str(requirement, "skill requirement")
            _require(len(requirement) <= 1024, "skill requirement too long")
        _require(type(entry["owned"]) is bool and type(entry["eligible"]) is bool, "invalid skill eligibility")


def _validate_effect_details(details):
    _require(isinstance(details, list) and len(details) <= STATUS_EFFECTS_MAX, "invalid effect_details")
    for detail in details:
        _exact_keys(detail, {"name", "description"}, "effect detail")
        _bounded_nonempty(detail["name"], "effect name", 512)
        _str(detail["description"], "effect description")
        _require(len(detail["description"]) <= 4096, "effect description too long")


def validate_spatial(obs):
    spatial = obs['spatial']
    _exact_keys(spatial, {'terrain', 'visibility', 'nearby'}, 'spatial')
    for key, symbols in (('terrain', '?#.+~<>'), ('visibility', 'umv')):
        rows = spatial[key]
        _require(isinstance(rows, list) and len(rows) == MAP_ROWS, 'invalid spatial rows')
        for row in rows:
            _require(type(row) is str and len(row) == MAP_COLS and set(row) <= set(symbols),
                     'invalid spatial row')
    for y, row in enumerate(spatial['visibility']):
        for x, visibility in enumerate(row):
            _require(visibility == 'v' or spatial['terrain'][y][x] == '?', 'unseen terrain must be unknown')
    nearby = spatial['nearby']
    _require(isinstance(nearby, list) and len(nearby) <= 9, 'invalid spatial nearby')
    seen = set()
    for cell in nearby:
        _exact_keys(cell, {'x', 'y', 'names'}, 'spatial nearby cell')
        x, y = cell['x'], cell['y']
        _int(x, 'spatial.x', 0)
        _int(y, 'spatial.y', 0)
        _require(x < MAP_COLS and y < MAP_ROWS and (x, y) not in seen, 'invalid spatial coordinates')
        seen.add((x, y))
        _require(spatial['visibility'][y][x] == 'v' and
                 max(abs(x-obs['vitals']['x']), abs(y-obs['vitals']['y'])) <= 1, 'nearby must be visible and adjacent')
        _require(isinstance(cell['names'], list) and len(cell['names']) <= 4, 'invalid terrain names')
        for name in cell['names']:
            _bounded_nonempty(name, 'terrain name', 256)


def validate_observation(obs):
    _require(isinstance(obs, dict), "observation must be an object")
    optional = obs.keys() & OPTIONAL_OBSERVATION_KEYS
    _exact_keys(obs, OBSERVATION_KEYS | optional, "observation")
    _validate_optional(obs)
    vitals = obs["vitals"]
    _exact_keys(vitals, VITALS_KEYS, "observation.vitals")
    for key in VITALS_INT_KEYS:
        _int(vitals[key], f"observation.vitals.{key}")
    _str(vitals["zone"], "observation.vitals.zone")

    _require(isinstance(obs["threats"], list), "observation.threats must be a list")
    for i, threat in enumerate(obs["threats"]):
        name = f"observation.threats[{i}]"
        _exact_keys(threat, THREAT_KEYS, name)
        for key in ("id", "name", "wound"):
            _str(threat[key], f"{name}.{key}")
        _int(threat["x"], f"{name}.x")
        _int(threat["y"], f"{name}.y")
        _require(type(threat["hostile"]) is bool, f"{name}.hostile must be a boolean")

    digest = obs["digest"]
    _require(isinstance(digest, list), "observation.digest must be a list")
    _require(len(digest) <= DIGEST_MAX, f"observation.digest has more than {DIGEST_MAX} lines")
    for i, line in enumerate(digest):
        _str(line, f"observation.digest[{i}]")

    grid = obs["map"]
    _require(isinstance(grid, list) and len(grid) == MAP_ROWS,
             f"observation.map must be a list of {MAP_ROWS} rows")
    for i, row in enumerate(grid):
        _require(type(row) is str and len(row) == MAP_COLS,
                 f"observation.map[{i}] must be a string of {MAP_COLS} characters")
    _int(obs["map_frame"], "observation.map_frame", 0)
    if "spatial" in obs:
        validate_spatial(obs)
    if "character" in obs:
        validate_character(obs["character"])
    return obs


def validate_telemetry(tel):
    """Telemetry must carry the listed counters; extra keys are retained, never exposed."""
    _require(isinstance(tel, dict), "telemetry must be an object")
    if "stray_keys" in tel:
        _int(tel["stray_keys"], "telemetry.stray_keys", 0)
    for key in TELEMETRY_COUNTERS:
        _require(key in tel, f"telemetry.{key} is missing")
        _int(tel[key], f"telemetry.{key}", 0)
    queue = tel.get("game_queue")
    _require(isinstance(queue, list), "telemetry.game_queue must be a list")
    for i, entry in enumerate(queue):
        name = f"telemetry.game_queue[{i}]"
        _exact_keys(entry, QUEUE_ENTRY_KEYS, name)
        _require(entry["task_id"] is None or type(entry["task_id"]) is str,
                 f"{name}.task_id must be a string or null")
        for key in ("type", "method", "classification"):
            _str(entry[key], f"{name}.{key}")
    return tel


def validate_result_fields(fields):
    _require(fields.get("action") in ACTIONS, f"result action must be one of {ACTIONS}")
    _require(type(fields.get("executed")) is bool, "result executed must be a boolean")
    _str(fields.get("reason"), "result reason")
    _int(fields.get("energy_before"), "result energy_before")
    _int(fields.get("energy_after"), "result energy_after")
    _int(fields.get("turns_elapsed"), "result turns_elapsed", 0)
    _int(fields.get("steps"), "result steps", 0)


def validate_recovery_fields(fields):
    """Recovery fields shared by the wire frame and the ledger body."""
    canonical_uuid(fields.get("recovery_id"), "recovery_id")
    reason = fields.get("reason")
    _require(type(reason) is str and reason in RECOVERY_SAVE_FILES,
             f"recovery reason must be one of {tuple(RECOVERY_SAVE_FILES)}")
    _require(fields.get("save_file") == RECOVERY_SAVE_FILES[reason],
             f"recovery reason {reason} requires save_file {RECOVERY_SAVE_FILES[reason]}")
    _bounded_nonempty(fields.get("game_id"), "recovery game_id", GAME_ID_MAX)
    sha256_hex(fields.get("save_sha256"), "recovery save_sha256")
    before = _int(fields.get("turn_before"), "recovery turn_before", 0)
    loaded = _int(fields.get("loaded_turn"), "recovery loaded_turn", 0)
    _int(fields.get("lost_turns"), "recovery lost_turns", 0)
    _require(fields["lost_turns"] == max(0, before - loaded),
             "recovery lost_turns must equal max(0, turn_before - loaded_turn)")


def validate_game_fault_reason(reason):
    return _bounded_nonempty(reason, "game_fault reason", GAME_FAULT_REASON_MAX)


def validate_suspended_reason(reason):
    _require(type(reason) is str and reason in SUSPENDED_REASONS,
             f"suspended reason must be one of {SUSPENDED_REASONS}")
    return reason


def parse_game_frame(frame):
    """Parse one text frame from the game. Raises WireError on any contract violation."""
    _require(isinstance(frame, str), "game frames must be text")
    _require(len(frame.encode("utf-8")) <= MAX_FRAME_BYTES, "frame exceeds size limit")
    message = loads_strict(frame)
    _require(isinstance(message, dict), "frame must be a JSON object")
    kind = message.get("kind")
    if kind == "recovery":
        _exact_keys(message, RECOVERY_KEYS, "recovery")
        _int(message["seq"], "recovery seq", 1)
        validate_recovery_fields(message)
    elif kind == "game_fault":
        _exact_keys(message, GAME_FAULT_KEYS, "game_fault")
        _int(message["seq"], "game_fault seq", 1)
        validate_game_fault_reason(message["reason"])
    elif kind == "suspended":
        _exact_keys(message, SUSPENDED_KEYS, "suspended")
        _int(message["seq"], "suspended seq", 1)
        validate_suspended_reason(message["reason"])
    elif kind == "request":
        _exact_keys(message, REQUEST_KEYS, "request")
        _int(message["seq"], "request seq", 1)
        validate_observation(message["observation"])
        validate_telemetry(message["telemetry"])
    elif kind == "result":
        _exact_keys(message, RESULT_KEYS, "result")
        _int(message["seq"], "result seq", 1)
        validate_result_fields(message)
        validate_observation(message["observation"])
        validate_telemetry(message["telemetry"])
    elif kind == "heartbeat":
        _exact_keys(message, HEARTBEAT_KEYS, "heartbeat")
        _int(message["seq"], "heartbeat seq", 0)
    else:
        raise WireError(f"unknown frame kind {kind!r}")
    _run_id(message["run_id"])
    return message


def normalize_decision(action, dir, budget, target=None, until=None, item=None, skill=None, attribute=None):
    """Validate MCP act arguments and return the (action, dir, budget) sent on the wire.

    Macro actions keep their bounded budget; direct actions always carry budget 1.
    """
    _require(action in ACTIONS, f"action must be one of {ACTIONS}")
    _int(budget, "budget")
    if action in MACRO_ACTIONS:
        _require(EXPLORE_BUDGET_MIN <= budget <= EXPLORE_BUDGET_MAX,
                 f"{action} budget must be within {EXPLORE_BUDGET_MIN}..{EXPLORE_BUDGET_MAX}")
    else:
        budget = 1
    validate_wire_decision(action, dir, budget, target, "healed" if action == "rest" and until is None else until,
                           item, skill, attribute)
    return action, dir, budget


def validate_wire_decision(action, dir, budget, target=None, until=None, item=None, skill=None, attribute=None):
    _require(action in ACTIONS, f"action must be one of {ACTIONS}")
    if action == "move":
        _require(dir in MOVE_DIRS, f"move dir must be one of {MOVE_DIRS}")
    elif action in ("attack", "talk"):
        _require(dir in ATTACK_DIRS, f"{action} dir must be one of {ATTACK_DIRS}")
    else:
        _require(dir is None, f"{action} takes no dir")
    _int(budget, "budget")
    if action in MACRO_ACTIONS:
        _require(EXPLORE_BUDGET_MIN <= budget <= EXPLORE_BUDGET_MAX,
                 f"{action} budget must be within {EXPLORE_BUDGET_MIN}..{EXPLORE_BUDGET_MAX}")
    else:
        _require(budget == 1, f"{action} budget must be 1")
    if action == "goto":
        _exact_keys(target, frozenset({"x", "y"}), "goto target")
        _int(target["x"], "target.x", 0)
        _int(target["y"], "target.y", 0)
        _require(target["x"] < MAP_COLS and target["y"] < MAP_ROWS, "target is outside the map")
    else:
        _require(target is None, f"{action} takes no target")
    if action == "rest":
        _require(until in ("healed", "morning"), "rest until must be healed or morning")
    else:
        _require(until is None, f"{action} takes no until")
    if action in ITEM_ACTIONS:
        prefix, limit = ("p", GROUND_MAX) if action == "get" else ("i", KIT_MAX)
        _require(item in tuple(f"{prefix}{n}" for n in range(1, limit + 1)), "item must be a current observed id")
    else:
        _require(item is None, f"{action} takes no item")
    if action == "learn_skill":
        _bounded_nonempty(skill, "skill", 200)
    else:
        _require(skill is None, f"{action} takes no skill")
    if action == "raise_attribute":
        _require(attribute in ATTRIBUTES, "unknown attribute")
    else:
        _require(attribute is None, f"{action} takes no attribute")


def validate_observed_item(action, item, observation):
    if action in ITEM_ACTIONS:
        source = "ground" if action == "get" else "kit"
        _require(any(entry["id"] == item for entry in observation.get(source, [])),
                 "item is absent from the current observation")


def validate_observed_growth(action, skill, attribute, observation):
    if action not in GROWTH_ACTIONS:
        return
    character = observation.get("character")
    _require(character is not None, "character growth is not observed")
    if action == "learn_skill":
        entries = [entry for entry in character["skill_catalog"] if entry["id"] == skill]
        _require(len(entries) == 1 and entries[0]["eligible"] and not entries[0]["owned"]
                 and 0 <= entries[0]["cost"] <= character["skill_points"], "skill is not currently purchasable")
    else:
        _require(attribute in ATTRIBUTES and character["attribute_points"] >= 1
                 and character["attributes"][attribute]["base"] < 100, "attribute is not currently purchasable")


def serialize_decision(run_id, seq, action, dir, budget, target=None, until=None, item=None, skill=None, attribute=None):
    """Serialize a decision once; the returned text is cached and replayed verbatim."""
    return json.dumps(
        {"kind": "decision", "run_id": run_id, "seq": seq, "action": action, "dir": dir,
         "budget": budget, **decision_options(action, target, until, item, skill, attribute)},
        separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )


def frame_sha256(frame):
    return hashlib.sha256(frame.encode("utf-8")).hexdigest()


# Ledger bodies. The verifier checks these exact key sets.

REQUEST_BODY_KEYS = frozenset({"frame_sha256", "observation", "telemetry"})
DECISION_BODY_KEYS = frozenset({"request_hash", "action", "dir", "budget"})
RESULT_BODY_KEYS = frozenset({"decision_hash", "frame_sha256", "observation", "telemetry",
                              *RESULT_FIELD_KEYS})


def request_body(message, frame):
    return {
        "frame_sha256": frame_sha256(frame),
        "observation": message["observation"],
        "telemetry": message["telemetry"],
    }


def decision_options(action, target, until, item=None, skill=None, attribute=None):
    # Existing action frames and ledger bodies retain their exact historical shape.
    if action == "goto":
        return {"target": target}
    if action == "rest":
        return {"until": "healed" if until is None else until}
    if action in ITEM_ACTIONS:
        return {"item": item}
    if action == "learn_skill":
        return {"skill": skill}
    if action == "raise_attribute":
        return {"attribute": attribute}
    return {}


def validate_rationale(rationale):
    if rationale is not None:
        _bounded_nonempty(rationale, "rationale", 2000)
        _require(bool(rationale.strip()), "rationale must contain text")


def decision_body(request_hash, action, dir, budget, target=None, until=None, item=None, rationale=None,
                  skill=None, attribute=None):
    return {"request_hash": request_hash, "action": action, "dir": dir, "budget": budget,
            **decision_options(action, target, until, item, skill, attribute),
            **({"rationale": rationale} if rationale is not None else {})}


def result_body(message, frame, decision_hash):
    body = {key: message[key] for key in RESULT_FIELD_KEYS}
    body.update({
        "decision_hash": decision_hash,
        "frame_sha256": frame_sha256(frame),
        "observation": message["observation"],
        "telemetry": message["telemetry"],
    })
    return body


def public_result(message):
    """The part of a result shown to the model: no telemetry."""
    public = {key: message[key] for key in RESULT_FIELD_KEYS}
    public["observation"] = message["observation"]
    return public


# Lifecycle bodies carry the frame fields (without kind/run_id/seq, like modal bodies),
# the frame digest and links to the interrupted request and its decision (null when
# no decision was accepted for that seq).
LINK_KEYS = ("frame_sha256", "request_hash", "decision_hash")
RECOVERY_BODY_KEYS = frozenset({*RECOVERY_FIELD_KEYS, *LINK_KEYS})
GAME_FAULT_BODY_KEYS = frozenset({"reason", *LINK_KEYS})
SUSPENDED_BODY_KEYS = frozenset({"reason", *LINK_KEYS})


def recovery_body(message, frame, request_hash, decision_hash):
    body = {key: message[key] for key in RECOVERY_FIELD_KEYS}
    body.update({"frame_sha256": frame_sha256(frame), "request_hash": request_hash,
                 "decision_hash": decision_hash})
    return body


def game_fault_body(message, frame, request_hash, decision_hash):
    return {"reason": message["reason"], "frame_sha256": frame_sha256(frame),
            "request_hash": request_hash, "decision_hash": decision_hash}


def suspended_body(message, frame, request_hash, decision_hash):
    """Same shape as a game_fault body: the reason plus links to the open request/decision."""
    return game_fault_body(message, frame, request_hash, decision_hash)


def public_recovery(message):
    """Recovery metadata shown to the model (game_id and save digest stay in the ledger)."""
    return {key: message[key] for key in
            ("recovery_id", "reason", "save_file", "turn_before", "loaded_turn", "lost_turns")}
