"""Bounded execution of an upper planner's explicitly reviewed encounter steps."""

from collections import Counter
import math

from harness.hybrid_hazards import assess_hazards, hazard_key, liquid_hazard_cells
from harness.hybrid_strategy import character_summary, hostile_distance, low_hp_acknowledged


def continuation_status(state, plan, history, review):
    contract = plan.get("continuation")
    if not contract or "modal" in state:
        return {"active": False, "reason": "no_continuation"}

    def revoked(reason):
        return {"active": False, "reason": reason}

    obs = state["observation"]
    v = obs["vitals"]
    previous = review.reviewed_observation if review else None
    issued = plan.get("issued_seq")
    if previous is None or plan.get("zone") != v["zone"] or type(issued) is not int:
        return revoked("continuation_unreviewed")
    steps = state["seq"] - issued
    if not 0 <= steps < min(contract["max_steps"], plan["horizon"]):
        return revoked("continuation_expired")
    risk = assess_hazards(obs)
    reviewed_risk = assess_hazards(previous)
    if (risk["priority"] >= 4 or risk["unknown_effects"]
            or hazard_key(risk) != hazard_key(reviewed_risk)):
        return revoked("continuation_hazard_changed")
    if character_summary(obs) != character_summary(previous) or obs.get("goals") != previous.get("goals"):
        return revoked("continuation_context_changed")
    if (v["hp"] <= contract["min_hp"]
            or v["hp"] <= math.ceil(v["max_hp"] * .4) and not low_hp_acknowledged(obs, previous, plan)):
        return revoked("continuation_hp_floor")
    records = [r for r in history.records if r["seq"] >= issued]
    damage = sum(max(0, r["before"]["hp"] - r["after"]["hp"]) for r in records)
    damage = max(damage, previous["vitals"]["hp"] - v["hp"])
    if damage > min(contract["max_damage"], math.floor(v["max_hp"] * .25)):
        return revoked("continuation_damage_budget")
    for record in records:
        if record["before"]["hp"] - record["after"]["hp"] >= v["max_hp"] * .2:
            return revoked("large_damage")
        if (record["result"].get("executed") is not True
                or record["action"].get("action") == "move"
                and record["before"]["position"] == record["after"]["position"]):
            return revoked("continuation_operation_failed")
        if record["action"].get("action") not in ("move", "wait", "attack"):
            return revoked("continuation_resource_changed")
    old_enemies = [t for t in previous["threats"] if t["hostile"]]
    enemies = [t for t in obs["threats"] if t["hostile"]]
    if Counter(t["name"] for t in enemies) - Counter(t["name"] for t in old_enemies):
        return revoked("continuation_new_threat")
    # Compare relative distances at the two observations, not the old enemy
    # position from the new player position (which flags any following movement).
    # Ambiguous same-name groups remain conservative; handles are observation-local.
    for enemy in enemies:
        same = [t for t in old_enemies if t["name"] == enemy["name"]]
        old_distance = min(hostile_distance(previous, t) for t in same)
        if hostile_distance(obs, enemy) <= 1 < old_distance:
            return revoked("continuation_threat_approaching")
        if not any((t["x"], t["y"]) == (enemy["x"], enemy["y"]) for t in same):
            unique = len(same) == 1 and sum(t['name'] == enemy['name'] for t in enemies) == 1
            anchor = previous if unique else obs
            if hostile_distance(obs, enemy) < min(hostile_distance(anchor, t) for t in same):
                return revoked("continuation_threat_approaching")
    origin = {k: previous["vitals"][k] for k in ("x", "y")}
    route = [origin, *contract["route"]]
    if any(max(abs(a["x"]-b["x"]), abs(a["y"]-b["y"])) != 1 for a, b in zip(route, route[1:])):
        return revoked("continuation_invalid_route")
    position = {k: v[k] for k in ("x", "y")}
    if position not in route:
        return revoked("continuation_route_deviation")
    index = route.index(position)
    ahead = {(c["x"], c["y"]) for c in route[index+1:]}
    if any((x, y) in ahead for x, y, _ in liquid_hazard_cells(risk) - liquid_hazard_cells(reviewed_risk)):
        return revoked("continuation_route_hazard")
    return {"active": True, "reason": "reviewed_continuation", "steps_used": steps,
            "damage_used": damage, "next_position": route[index+1] if index+1 < len(route) else None}


def continuation_allows(state, plan, history, review, candidate):
    status = continuation_status(state, plan, history, review)
    if not status["active"]:
        return False
    contract = plan["continuation"]
    obs = state["observation"]
    args = candidate["args"]
    if args.get("action") == "move":
        target = candidate.get("destination")
        return (target is not None and target == status["next_position"] and not candidate.get("occupants")
                and candidate.get("glyph") not in (None, " ")
                and not any(r["position"] == target and r["damage_events"] >= 2 for r in history.route_risks(obs)))
    if args.get("action") == "wait":
        return contract["hold_position"] == {k: obs["vitals"][k] for k in ("x", "y")}
    if args.get("action") == "attack":
        occupants = candidate.get("occupants", [])
        return (len(occupants) == 1 and occupants[0]["hostile"]
                and contract["attack_target"] == {k: occupants[0][k] for k in ("x", "y")}
                and sum(t["hostile"] and hostile_distance(obs, t) <= 1 for t in obs["threats"]) == 1)
    return False
