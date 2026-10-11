"""Public evidence and concrete candidates; no game access or model calls."""

import copy
import hashlib
import json
import math
import re

from harness import wire
from harness.hybrid_autonomy import excluded_cells, spatially_blocked
from harness.hybrid_mapping import SpatialMemory, current_terrain
from harness.hybrid_navigation import navigation_status
from harness.hybrid_hazards import assess_hazards, plain
from harness.hybrid_strategy import character_summary, effective_tactics, safe_to_review

OFFSETS = dict(zip(wire.ATTACK_DIRS, [(0, -1), (1, -1), (1, 0), (1, 1),
                                   (0, 1), (-1, 1), (-1, 0), (-1, -1)]))
CONTRACT = {
    "moves": "Eight compass directions are single steps; an occupied hostile cell may cause melee. Terrain/passability is not guaranteed by a glyph. U/D use native stairs or world-map transitions.",
    "macros": "derived.navigation exposes native goto/explore availability and blocking reasons, even when unavailable actions are absent from candidates. Prefer offered goto for a known destination and explore for open exploration. Native goto/explore/rest are unavailable on the world map or with visible hostiles; goto requires a known target. Native macros stop on danger; budget is game turns, not wall time. Exclusions cannot be passed to native macros. A move candidate with navigation starts a guarded route: the harness reobserves and checks mission permission before every ordinary step, for at most 12 steps. It stops for enemies, damage, failed steps, changed policy or an unsafe next cell. Unavailable capabilities are not executable candidates.",
    "items": "Use only current item IDs and listed native actions. open opens a carried container; apply does not. dispatched means the handler returned, not that the desired effect happened. Storage and trading are unsupported.",
    "knowledge": "Descriptions preserve unidentified names and confusion. Missing information stays unknown. Abilities and ranged-fire commands are not supported by this executor; do not plan to invoke them.",
    "history": "Past observations are not current facts. An unseen enemy may remain nearby. executed:false may still spend time/energy. Re-evaluate failures rather than blindly retrying.",
    "hazards": "derived.hazards is an ordinal review priority, not damage or death probability. Use actual effects, their details, and combinations with hostiles/HP/open liquid terrain. Unknown is not harmless. Body/equipment coating, dried stains, terrain liquid and carried containers differ. Wait uses native firefighting when aflame or warms the player when frozen; inspect the actual outcome. Cleaning and active abilities are not supported actions.",
    "map": "25 rows, 80 columns, x right and y down. Every character, including legacy control glyphs, occupies one cell; do not count visually rendered columns. derived.map_markers gives stair coordinates from observed terrain when available, otherwise displayed glyphs. Remembered stairs may be stale. Overlays such as @ can hide them; absence does not prove no stairs. Spaces may be unexplored; glyphs are display evidence, not a pathfinding oracle. Creature coordinates override glyphs.",
    "mapping": "spatial.visibility: v currently visible, m explored but unseen, u unexplored. spatial.terrain: ? unknown, . no visible static obstruction, # visible solid, + door, ~ open liquid, < up stairs, > down stairs. No hidden objects are inspected; clear is not a guarantee of passability or safety. derived.mapping is shared zone memory, including prior observed terrain, arrivals, failed routes, frontier cells beside unknown terrain, and known path distances. Prefer path distance over straight-line distance around walls. High visit counts help detect loops, but backtracking for safety or return remains valid. Native goto/explore uses the game engine and stops on danger.",
    "conversation": "An option labelled ... continues the NPC's speech. Cancel closes the conversation without advancing its branch. When seeking a quest, continue listening and accept the offered work before ending. Submitted modal responses document what was sent; their acknowledgements and subsequent observations establish what happened. Candidate IDs are scoped to this request, never reuse an ID from a past plan.",
}


def fingerprint(state):
    value = {k: state.get(k) for k in ("run_id", "seq", "observation", "modal")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def progress(obs):
    v = obs.get("vitals", {})
    return {"position": [v.get(k) for k in ("zone", "x", "y")], "hp": v.get("hp"),
            "character": character_summary(obs), **{k: obs.get(k) for k in ("kit", "goals", "status", "threats", "map", "spatial")}}


def movement_context(obs):
    # Ignore transport sequence and rolling messages, but expire a block after
    # any public spatial/physical change, including elapsed game time.
    value = progress(obs) | {"vitals": obs["vitals"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def candidates(state, plan, *, strategic=False, history=None):
    result = []

    def add(label, args, **facts):
        result.append({"id": f"c{len(result)}", "label": label, "args": args, **facts})

    if "modal" in state:
        modal = state["modal"]
        for choice in modal.get("choices", []):
            if choice.get("enabled", True):
                facts = {}
                if modal.get("type") == "conversation":
                    if choice["id"].startswith("button:") and choice["label"].strip() in ("[Esc] Cancel", "Cancel"):
                        facts["dialog_effect"] = "Close this conversation without selecting a dialogue branch"
                    elif choice["label"].strip() in ("...", "…"):
                        facts["dialog_effect"] = "Continue listening to this conversation"
                add(choice["label"], {"response": {"choice": choice["id"]}}, **facts)
        if modal.get("type") == "pick_item" or modal.get("input_kind") in ("direction", "cell", "field"):
            add("Cancel this dialog", {"response": {"cancel": True}})
        return result
    obs = state["observation"]
    v = obs["vitals"]
    world = obs.get("place", {}).get("world_map", False)
    enemies = [t for t in obs["threats"] if t["hostile"]]
    target = plan.get("target") if plan.get("zone") in (None, v["zone"]) else None
    if enemies and effective_tactics(obs, plan).get("mode") in ("combat", "replan"):
        target = None
    mapping = history.mapping.evidence(obs, target, excluded_cells(obs, plan, history)) if history and "spatial" in obs else None
    for direction, (dx, dy) in OFFSETS.items():
        x, y = v["x"] + dx, v["y"] + dy
        if not (0 <= x < 80 and 0 <= y < 25):
            # Native local movement can cross zone edges; world limits are unknown.
            add(f"Move {direction} across zone edge", {"action": "move", "dir": direction})
            continue
        terrain = current_terrain(obs, x, y)
        if terrain == '#':
            continue
        occupants = [t for t in obs["threats"] if (t["x"], t["y"]) == (x, y)]
        facts = {"destination": {"x": x, "y": y}, "glyph": obs["map"][y][x],
                 "occupants": occupants,
                 "nearest_visible_hostile_after_step": min((max(abs(t["x"]-x), abs(t["y"]-y)) for t in enemies), default=None)}
        if terrain is not None:
            facts['terrain'] = terrain
            facts['visibility'] = obs['spatial']['visibility'][y][x]
            facts['terrain_names'] = next((c['names'] for c in obs['spatial']['nearby'] if (c['x'], c['y']) == (x, y)), [])
        if mapping:
            path = next(c for c in mapping['neighbor_paths'] if (c['x'], c['y']) == (x, y))
            facts['known_path_distance_to_target'] = path['target_distance']
            facts['visit_count'] = path['visits']
        if target:
            facts["distance_to_plan_target"] = max(abs(target["x"]-x), abs(target["y"]-y))
        label = f"Move {direction}"
        if any(t["hostile"] for t in occupants):
            label += " using movement rules (may bump-attack; does not guarantee relocation)"
        add(label, {"action": "move", "dir": direction}, **facts)
        if any(t["hostile"] for t in occupants):
            add(f"Melee hostile {direction}", {"action": "attack", "dir": direction}, occupants=occupants)
        if any(not t["hostile"] for t in occupants):
            add(f"Try talking {direction}", {"action": "talk", "dir": direction}, occupants=occupants)
    glyph = obs["map"][v["y"]][v["x"]]
    # The player glyph can hide stairs; explicit U/D attempts retain reachability.
    add("Ascend stairs here, or enter world map from surface if permitted", {"action": "move", "dir": "U"}, current_glyph=glyph)
    add("Descend stairs here, or enter local zone from world map", {"action": "move", "dir": "D"}, current_glyph=glyph)
    risk = assess_hazards(obs)
    navigation = navigation_status(state, plan, history)
    if navigation['explore']['available']:
        add("Explore this local zone, stopping on danger", {"action": "explore", "budget": 12})
    if navigation['goto']['available']:
        add(f"Travel to ({target['x']}, {target['y']}) from the current plan",
            {"action": "goto", "target": target, "budget": 12})
    if not world and not enemies and risk["priority"] < 2 and not risk["unknown_effects"]:
        if v["hp"] < v["max_hp"]:
            add("Rest briefly to heal; stop on danger", {"action": "rest", "until": "healed", "budget": 12})
    add("Wait one turn", {"action": "wait"})
    details = {d["id"]: d for d in obs.get("item_details", [])}
    for item in obs.get("kit", []):
        detail = details.get(item["id"], {})
        for action in detail.get("actions", []):
            if action == "equip":
                continue
            add(f"{action} {item['name']}", {"action": action, "item": item["id"]},
                description=detail.get("description", ""), slot=item["slot"])
    for item in obs.get("ground", []):
        add(f"Pick up {item['name']}", {"action": "get", "item": item["id"]},
            position={"x": item["x"], "y": item["y"]})
    character = obs.get("character")
    # Upper-level options are appended so escalation preserves Jev's candidate IDs.
    if strategic and safe_to_review(obs):
        for item in obs.get("kit", []):
            detail = details.get(item["id"], {})
            if "equip" in detail.get("actions", []):
                add(f"equip {item['name']}", {"action": "equip", "item": item["id"]},
                    description=detail.get("description", ""), slot=item["slot"])
    if strategic and character and safe_to_review(obs):
        for entry in character["skill_catalog"]:
            if entry["eligible"] and not entry["owned"] and 0 <= entry["cost"] <= character["skill_points"]:
                add(f"Learn {entry['name']} ({entry['cost']} SP)",
                    {"action": "learn_skill", "skill": entry["id"]}, description=entry["description"],
                    requirements=entry["requirements"])
        if character["attribute_points"] > 0:
            for name, values in character["attributes"].items():
                if values["base"] < 100:
                    add(f"Raise {name} by one base point (1 AP)",
                        {"action": "raise_attribute", "attribute": name}, current=values)
    blocked = history.blocked_moves(state["observation"]) if history else []
    result = [c for c in result if c["args"] not in blocked
              and not spatially_blocked(obs, plan, history, c)]
    route = navigation['guarded_route']
    if route['available']:
        for candidate in result:
            if candidate['args'].get('action') == 'move' and candidate.get('destination') == route['path'][0]:
                candidate['navigation'] = {k: route[k] for k in ('purpose', 'target', 'path', 'max_steps')}
                candidate['label'] += f"; start guarded {route['purpose']} route to ({route['target']['x']}, {route['target']['y']})"
    return result


def decision_gate(answer, ids, threshold):
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return "invalid_jev_response"
    probs = answer.get("probabilities")
    confidence = answer.get("confidence")
    chosen = answer.get("choice")
    if not isinstance(probs, dict) or set(probs) != set(ids) or chosen not in ids:
        return "invalid_jev_response"
    if any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()):
        return "invalid_jev_response"
    if (not math.isclose(sum(probs.values()), 1, abs_tol=.02)
            or probs[chosen] < max(probs.values()) and not math.isclose(
                probs[chosen], max(probs.values()), rel_tol=0, abs_tol=1e-12)
            or type(confidence) not in (int, float) or not math.isfinite(confidence)
            or not 0 <= confidence <= 1):
        return "invalid_jev_response"
    return "low_probability" if probs[chosen] < threshold else None


def evidence_state(state, plan, history, review=None):
    obs = state["observation"]
    v = obs["vitals"]
    creatures = [t | {"distance": max(abs(t["x"]-v["x"]), abs(t["y"]-v["y"]))} for t in obs["threats"]]
    markers = [{"glyph": glyph, "x": x, "y": y,
                "distance": max(abs(x-v["x"]), abs(y-v["y"]))}
               for y, row in enumerate(obs["map"]) for x, glyph in enumerate(row) if glyph in "<>"]
    if 'spatial' in obs:
        markers = [{'glyph': kind, 'x': x, 'y': y, 'distance': max(abs(x-v['x']), abs(y-v['y']))}
                   for y, row in enumerate(history.mapping.observe(obs)['terrain']) for x, kind in enumerate(row) if kind in '<>']
    loss = max((max(0, r["before"]["hp"] - r["after"]["hp"]) for r in history.records
                if r["after"]["position"][0] == v["zone"]), default=0)
    healing = [{"action": action, "item": d["id"]}
               for d in obs.get("item_details", [])
               if re.search(r"\bheals\b|\brestores?\b.*\b(?:hp|hit points)\b", plain(d.get("description", "")))
               for action in d.get("actions", []) if action in ("eat", "drink", "apply")]
    return {"identity": {"run_id": state.get("run_id"), "seq": state["seq"], "sha256": fingerprint(state)},
            "current_observation": obs, "modal": state.get("modal"),
            "claude_plan": plan, "recent_outcomes": history.records,
            "strategic_context": review.evidence(obs) if review else None,
            "verified_session": {"completed_actions": history.completed_actions,
                                 "action_counts": history.action_counts,
                                 "macro_stop_counts": history.macro_stop_counts,
                                 "hostile_stops_without_following_visible_enemy": history.hostile_stops_without_following_visible_enemy,
                                 "scope": "Counts of completed executor operations, not kills or successful objectives. Rolling messages are not unique event IDs."},
            "submitted_modal_responses": history.modal_records,
            "verified_events": copy.deepcopy(history.events),
            "deferred_reviews": copy.deepcopy(history.notifications),
            "executor_contract": CONTRACT,
            "unknowns": ["unseen enemies", "unidentified item identities", "hidden terrain", "ability execution unavailable"],
            "derived": {"hp_fraction": v["hp"] / max(1, v["max_hp"]), "creatures": creatures,
                        "navigation": navigation_status(state, plan, history),
                        "map_markers": markers,
                        "mapping": history.mapping.evidence(obs, plan.get("target") if plan.get("zone") in (None, v["zone"]) else None, excluded_cells(obs, plan, history)),
                        "history_problem": history.problem(),
                        "hazards": assess_hazards(obs),
                        "survival": {"largest_recent_hp_loss": loss,
                                     "observed_loss_can_be_lethal": loss > 0 and v["hp"] <= loss,
                                     "healing_actions": healing,
                                     "meaning": "Observed net HP loss per operation, not a damage ceiling. Healing descriptions are candidate evidence, not approval; inspect side effects and current hazards."},
                        "route_risks": history.route_risks(obs),
                        "observed_blocked_moves": history.blocked_moves(obs)}}


class History:
    def __init__(self, *, events=None):
        self.mapping = SpatialMemory()
        self.navigation = None
        self.events = copy.deepcopy(events or [])
        self.notifications = {}
        self.records = []
        self.modal_records = []
        self.completed_actions = 0
        self.action_counts = {}
        self.macro_stop_counts = {}
        self.hostile_stops_without_following_visible_enemy = 0
        self.arrived_targets = {}
        self.modal_responses = 0
        self.modal_review_after = 0

    def remember(self, kind, state, **facts):
        # Historical observations are evidence, not assertions about the current world.
        self.events.append({"kind": kind, "source": {"run_id": state.get("run_id"),
                            "seq": state["seq"], "sha256": fingerprint(state)}, **copy.deepcopy(facts)})
        self.events = self.events[-128:]

    def record_modal(self, state, candidate, dispatch):
        self.modal_responses += 1
        modal = state["modal"]
        self.modal_records.append({"seq": state["seq"], "token": modal["token"],
            "dialog_type": modal.get("type"), "dialog_text": modal.get("text"),
            "offered_choices": [dict(choice) for choice in modal.get("choices", [])],
            "selected_label": candidate["label"], "response": candidate["args"]["response"],
            "acknowledgement": dispatch})
        self.modal_records = self.modal_records[-8:]
        if any(tag in choice["label"].lower() for choice in modal.get("choices", [])
               for tag in ("[accept quest]", "[complete quest]", "[give artifact]")) or (
                   modal.get("title", "").strip().lower() == "choose an artifact to give."):
            self.remember("quest_dialogue", state, **self.modal_records[-1],
                          meaning="Observed options and submitted response; acknowledgement alone is not quest completion.")

    def modal_problem(self, state):
        modal = state.get("modal", {})
        if modal.get("type") != "conversation" or self.modal_responses - self.modal_review_after < 4:
            return None
        recent = self.modal_records[-4:]
        if (len(recent) != 4 or any(r["seq"] != state["seq"] or r["dialog_type"] != "conversation"
                                   or r["acknowledgement"].get("accepted") is not True for r in recent)):
            return None
        pairs = [(r["dialog_text"], r["selected_label"]) for r in recent]
        if pairs[:2] == pairs[2:] and modal.get("text") in (pairs[0][0], pairs[1][0]):
            return "repeated_dialogue"
        return None

    def record(self, before, action, result, after):
        self.completed_actions += 1
        kind = action.get("action", "unknown")
        self.action_counts[kind] = self.action_counts.get(kind, 0) + 1
        old = before["observation"]
        new = after["observation"]
        self.mapping.record(old, action, result, new)
        loss = max(0, old["vitals"]["hp"] - new["vitals"]["hp"])
        if loss or kind in ("eat", "drink", "apply"):
            item = next((i for i in old.get("kit", []) if i["id"] == action.get("item")), None)
            self.remember("risk_outcome", after,
                          zone=new["vitals"]["zone"], position={k: new["vitals"][k] for k in ("x", "y")},
                          observed_hp_loss=loss, action=action, consumed_item=item,
                          visible_hostiles=[{k: t[k] for k in ("name", "x", "y")} for t in new["threats"] if t["hostile"]],
                          meaning="HP difference after one operation; healing can mask damage. Endpoint is not an attributed hit tile. Visible enemies do not establish the attacker or maximum range.")
        if old.get("goals") != new.get("goals"):
            self.remember("quest_log_changed", after, before=old.get("goals"), after=new.get("goals"),
                          meaning="Public quest-log change; disappearance alone does not prove completion.")
        if old["vitals"]["zone"] != new["vitals"]["zone"]:
            self.remember("zone_entered", after, place=new.get("place"),
                          position={k: new["vitals"][k] for k in ("zone", "x", "y")})
        target = action.get("target")
        if (kind == "goto" and target and result.get("reason") == "ARRIVED"
                and old["vitals"]["zone"] == new["vitals"]["zone"]
                and (new["vitals"]["x"], new["vitals"]["y"]) == (target["x"], target["y"])):
            self.arrived_targets[(new["vitals"]["zone"], target["x"], target["y"])] = before["seq"]
            self.remember("target_reached", after, target=target, zone=new["vitals"]["zone"])
        if kind in wire.MACRO_ACTIONS:
            reason = result.get("reason", "unknown")
            self.macro_stop_counts[reason] = self.macro_stop_counts.get(reason, 0) + 1
            if reason == "NEW_HOSTILE" and not any(t["hostile"] for t in new["threats"]):
                self.hostile_stops_without_following_visible_enemy += 1
        dx, dy = OFFSETS.get(action.get("dir"), (0, 0))
        v = old["vitals"]
        combat_attempt = (result.get("executed") is True and kind in ("attack", "move")
                          and any(t["hostile"] and (t["x"], t["y"]) == (v["x"]+dx, v["y"]+dy)
                                  for t in old["threats"]))
        previous, current = progress(old), progress(new)
        def compact(value):
            return {"position": value["position"], "hp": value["hp"],
                    "state_sha256": hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()}
        self.records.append({"seq": before["seq"], "source_sha256": fingerprint(before),
                             "action": action, "result": {k: result.get(k) for k in wire.RESULT_FIELD_KEYS},
                             "before": compact(previous), "after": compact(current),
                             "changes": {k: {"before": old.get(k), "after": new.get(k)}
                                         for k in ("kit", "goals", "status") if old.get(k) != new.get(k)},
                             "character_change": {"before": previous["character"], "after": current["character"]}
                                                 if previous["character"] != current["character"] else None,
                             # A rolling digest is a snapshot, not an event stream:
                             # membership subtraction would erase repeated hits/messages.
                             "messages": new.get("digest", []),
                             "combat_attempt": combat_attempt,
                             "movement_context": movement_context(old),
                             "changed": previous != current})
        self.records = self.records[-8:]

    def problem(self):
        last = self.records[-3:]
        if len(last) == 3 and all(r["result"].get("executed") is False for r in last):
            return "repeated_failure"
        if len(last) == 3 and all(not r["changed"] and not r["combat_attempt"] for r in last):
            return "no_progress"
        last = self.records[-6:]
        if (len(last) == 6 and not any(r["combat_attempt"] for r in last)
                and len({json.dumps(r["after"], sort_keys=True) for r in last}) <= 2):
            return "repeated_cycle"
        return None

    def route_risks(self, obs):
        sites = {}
        for event in self.events:
            if event["kind"] != "risk_outcome" or event["zone"] != obs["vitals"]["zone"]:
                continue
            position = event["position"]
            site = sites.setdefault((position["x"], position["y"]),
                                    {"position": position, "damage_events": 0, "observed_hp_loss": 0,
                                     "consumable_actions": 0, "last_source": event["source"]})
            site["damage_events"] += event["observed_hp_loss"] > 0
            site["observed_hp_loss"] += event["observed_hp_loss"]
            site["consumable_actions"] += event["action"].get("action") in ("eat", "drink", "apply")
            site["last_source"] = event["source"]
        return list(sites.values())

    def blocked_moves(self, obs):
        context = movement_context(obs)
        return [r["action"] for r in self.records
                if r["action"].get("action") == "move" and r["movement_context"] == context
                and r["result"].get("executed") is False and r["result"].get("reason") == "blocked"
                and r["result"].get("turns_elapsed") == 0]

    def reset(self):
        self.mapping = SpatialMemory()
        self.navigation = None
        self.events = []
        self.notifications = {}
        self.records = []
        self.modal_records = []
        self.completed_actions = 0
        self.action_counts = {}
        self.macro_stop_counts = {}
        self.hostile_stops_without_following_visible_enemy = 0
        self.arrived_targets = {}
        self.modal_responses = 0
        self.modal_review_after = 0
