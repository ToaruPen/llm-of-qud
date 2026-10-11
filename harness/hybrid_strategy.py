"""Observed build changes and the boundary between planning and tactical choice."""

import copy
from collections import Counter
import hashlib
import json
import re

from harness.hybrid_hazards import assess_hazards, hazard_key


def hostile_distance(obs, threat, position=None):
    v = position or obs["vitals"]
    return max(abs(threat["x"] - v["x"]), abs(threat["y"] - v["y"]))


def effective_tactics(obs, plan):
    tactics = copy.deepcopy(plan.get("tactics", {}))
    enemies = [t for t in obs["threats"] if t["hostile"]]
    response = tactics.get("hostile_response", "replan")
    close = any(hostile_distance(obs, t) <= tactics.get("danger_distance", 6) for t in enemies)
    fraction = obs["vitals"]["hp"] / max(1, obs["vitals"]["max_hp"])
    if enemies:
        if fraction <= tactics.get("retreat_hp_fraction", 0) or response == "retreat":
            tactics["mode"] = "retreat"
        elif response == "avoid":
            tactics["mode"] = "avoid"
        elif response == "replan":
            tactics["mode"] = "replan"
        elif close:
            tactics["mode"] = "combat"
    return tactics


def character_summary(obs):
    character = obs.get("character")
    if character is None:
        return None
    return {key: character[key] for key in ("level", "skill_points", "attribute_points", "attributes", "owned_skills",
            "genotype", "subtype", "mutation_points", "mutations", "mutations_truncated") if key in character}


def safe_to_review(obs):
    if any(t["hostile"] for t in obs["threats"]):
        return False
    risk = assess_hazards(obs)
    return risk["priority"] < 2 and not risk["unknown_effects"]



def _gear_context(obs):
    details = {d["id"]: d for d in obs.get("item_details", [])}
    equipped, options = [], set()
    for item in obs.get("kit", []):
        detail = details.get(item["id"], {})
        # Quantity, carried weight and transient handles do not make a new build.
        name = detail.get("comparison_name", re.sub(r" \[\d+\]$", "", item["name"]))
        # A sip changes quantity, not equipment capability; retain the liquid's identity.
        name = re.sub(r"\[\d+ drams? of ([^\]]+)\]", r"[\1]", name)
        # Native torch ignition is a light-state change, not a different build.
        if name in ("torch (unburnt)", "lit torch (blazing)"):
            name = "torch"
        description = "\n".join(line for line in detail.get("description", "").splitlines()
                                if "Weight:" not in line)
        identity = json.dumps([name, description], ensure_ascii=False)
        if item.get("slot") is not None:
            equipped.append([item["slot"], identity])
        elif "equip" in detail.get("actions", []) and "eat" not in detail.get("actions", []):
            # Qud can equip ordinary food as an improvised held object. It remains
            # available to the planner, but harvesting alone is not a gear event.
            options.add(identity)
    return {"equipped": sorted(equipped), "options": sorted(options)}


class BuildReview:
    def __init__(self):
        self.reviewed = None
        self.policy = {}
        self.revision = 0
        self.reviewed_hazard = None
        self.reviewed_threats = None
        self.reviewed_observation = None

    @staticmethod
    def _threat_context(obs):
        return sorted((t["name"], t["x"], t["y"]) for t in obs["threats"] if t["hostile"])

    def avoidance_changed(self, obs, danger_distance=6, *, check_damage=True):
        if self.reviewed_threats is None:
            return True
        v = obs["vitals"]
        zone, hp, _ = self.reviewed_threats
        if v["zone"] != zone or (check_damage and v["hp"] < hp):
            return True
        previous = self.reviewed_observation
        # Handles are transient. Compare observed kinds/counts and proximity bands,
        # not exact coordinates. Losing sight never proves a kill.
        for distance in (None, danger_distance, 1):
            old = Counter(t["name"] for t in previous["threats"] if t["hostile"]
                          and (distance is None or hostile_distance(previous, t) <= distance))
            new = Counter(t["name"] for t in obs["threats"] if t["hostile"]
                          and (distance is None or hostile_distance(obs, t) <= distance))
            if new - old:
                return True
        return False

    def pending_reason(self, obs):
        if "character" not in obs:
            return None
        if self.reviewed is None:
            return "initial_build_review"
        if character_summary(obs) != self.reviewed["character"]:
            return "character_changed"
        gear = _gear_context(obs)
        if gear["equipped"] != self.reviewed["gear"]["equipped"]:
            return "equipment_changed"
        if set(gear["options"]) - set(self.reviewed["gear"]["options"]):
            return "new_equipment_option"
        return None

    def reason(self, obs):
        risk = assess_hazards(obs)
        if (risk["priority"] >= 3 or risk["unknown_effects"]) and hazard_key(risk) != self.reviewed_hazard:
            return "hazard_changed"
        if risk["priority"] < 3 and not risk["unknown_effects"]:
            self.reviewed_hazard = None
        return self.pending_reason(obs) if safe_to_review(obs) else None

    def accept(self, obs, policy):
        self.reviewed_observation = copy.deepcopy(obs)
        self.policy = copy.deepcopy(policy)
        self.reviewed_hazard = hazard_key(assess_hazards(obs))
        self.reviewed_threats = (obs["vitals"]["zone"], obs["vitals"]["hp"], self._threat_context(obs))
        if safe_to_review(obs):
            self.reviewed = {"character": copy.deepcopy(character_summary(obs)), "gear": _gear_context(obs)}
            self.revision += 1

    def evidence(self, obs):
        return {"revision": self.revision, "policy": self.policy,
                "pending_review": self.pending_reason(obs), "safe_to_review": safe_to_review(obs),
                "reviewed_context_sha256": hashlib.sha256(json.dumps(self.reviewed, sort_keys=True).encode()).hexdigest()}


def tactical_evidence(evidence):
    """Keep current facts; suppress obsolete navigation prose during combat."""
    result = copy.deepcopy(evidence)
    obs = result["current_observation"]
    if "character" in obs:
        obs["character"].pop("skill_catalog", None)
    plan = result["claude_plan"]
    for key in ("memory", "selection", "stop"):
        plan.pop(key, None)
    tactics = effective_tactics(obs, plan)
    if (not plan.get("continuation") and any(t["hostile"] for t in obs["threats"])
            and tactics.get("mode") in ("combat", "replan", "retreat")):
        plan.pop("guidance", None)
        plan["target"] = None
    result["derived"]["effective_tactics"] = tactics
    # Current character state is authoritative; repeating full before/after builds
    # and old quest dialogue exhausted Jev's context after the first level-up.
    recent = result.get('recent_outcomes', [])[-8:]
    compact = []
    for index, record in enumerate(recent):
        entry = {k: record[k] for k in ('seq', 'action', 'result', 'before', 'after', 'changed', 'combat_attempt')
                 if k in record}
        entry['character_changed'] = record.get('character_changed', bool(record.get('character_change')))
        if index == len(recent) - 1:
            entry['changes'] = record.get('changes', {})
            entry['messages'] = record.get('messages', [])
        compact.append(entry)
    result['recent_outcomes'] = compact
    result['submitted_modal_responses'] = result.get('submitted_modal_responses', [])[-2:]
    result['verified_events'] = [{k: event[k] for k in ('kind', 'source', 'zone', 'position',
        'observed_hp_loss', 'action', 'consumed_item', 'visible_hostiles') if k in event}
        for event in result.get('verified_events', []) if event['kind'] in ('risk_outcome', 'zone_entered')][-16:]
    result['context_projection'] = 'Current observations, shared mapping, permission limits and derived risks are complete. Recent outcomes retain eight operation results and HP changes; only the latest keeps messages and detailed changes. Full historical builds and old quest dialogue are omitted; use the current build, quest log and modal. Missing historical text is not evidence that an event never occurred.'
    return result
