"""Auditable routing heuristics; choice probabilities are never safety probabilities."""

import copy
import re

from harness.hybrid_hazards import assess_hazards, plain
from harness.hybrid_continuation import continuation_allows
from harness.hybrid_autonomy import autonomous_action
from harness.hybrid_strategy import effective_tactics, hostile_distance, safe_to_review


def strategic_dialogue(state):
    modal = state.get("modal", {})
    if modal.get("title", "").strip().lower() == "choose an artifact to give.":
        return True
    return modal.get("type") == "conversation" and any(
        tag in choice["label"].lower() for choice in modal.get("choices", [])
        for tag in ("[accept quest]", "[complete quest]", "[give artifact]"))


def route_event(state, history, review):
    if "modal" in state:
        return None
    obs = state["observation"]
    if review:
        reason = review.reason(obs)
        if reason:
            return reason
        if review.reviewed_observation == obs:
            return None
        previous = review.reviewed_observation
        if previous and assess_hazards(previous)["navigation_constraints"] != assess_hazards(obs)["navigation_constraints"]:
            return "navigation_constraints_changed"
    last = history.records[-1] if history.records else None
    if not last or last["seq"] + 1 != state["seq"]:
        return None
    if "goals" in last["changes"]:
        return "quest_progress_changed"
    if last["after"]["hp"] < last["before"]["hp"] and not last["combat_attempt"]:
        return "recent_damage"
    if last["before"]["hp"] - last["after"]["hp"] >= obs["vitals"]["max_hp"] * .2:
        return "large_damage"
    if last["action"].get("action") == "goto":
        if not safe_to_review(obs):
            return "navigation_danger"
        result = last["result"]
        if result.get("executed") is not True or result.get("reason") not in ("BUDGET", "ARRIVED"):
            return "navigation_interrupted"
        if result.get("reason") == "ARRIVED":
            return "target_reached"
        if last["before"]["position"] == last["after"]["position"]:
            return "navigation_no_progress"
    return None


def authorized_goto(state, plan, history, review, options):
    obs = state["observation"]
    tactics = plan.get("tactics", {})
    v = obs["vitals"]
    target = plan.get("target")
    reached = (target and history.arrived_targets.get((v["zone"], target["x"], target["y"]), -1)
               >= plan.get("issued_seq", 0))
    if ("modal" in state or plan.get("automatic_goto") is not True or plan.get("stop")
            or reached
            or tactics.get("mode") != "travel" or plan.get("zone") != v["zone"]
            or not review or review.pending_reason(obs) or history.problem()
            or not safe_to_review(obs)
            or v["hp"] / max(1, v["max_hp"]) < max(.6, tactics.get("heal_hp_fraction", .6))):
        return None
    return next((c for c in options if c["args"].get("action") == "goto"), None)


def routing_threshold(state, plan, history, selected, base):
    obs = state["observation"]
    risk = assess_hazards(obs)
    v = obs["vitals"]
    factors = []
    hostile = any(t["hostile"] for t in obs["threats"])
    fraction = v["hp"] / max(1, v["max_hp"])
    if hostile:
        factors.append({"reason": "visible_hostile", "weight": .1})
    if risk["priority"] >= 2 or risk["unknown_effects"]:
        factors.append({"reason": "hazard_or_unknown", "weight": .1})
    if fraction < max(.6, plan.get("tactics", {}).get("heal_hp_fraction", .6)):
        factors.append({"reason": "reduced_hp", "weight": .1})
    target = plan.get("target")
    args = selected["args"]
    last_failed = history.records and history.records[-1]["result"].get("executed") is not True
    clear_step = (args.get("action") == "move" and args.get("dir") not in ("U", "D")
                  and selected.get("glyph") in (".", ",", "'", "`") and not selected.get("occupants"))
    destination = selected.get("destination")
    if (hostile and clear_step and destination and not last_failed and not history.problem()
            and plan.get("zone") == v["zone"] and plan.get("tactics", {}).get("hostile_response") == "avoid"
            and risk["priority"] < 2 and not risk["unknown_effects"]
            and fraction >= max(.6, plan.get("tactics", {}).get("heal_hp_fraction", .6))):
        distances = [(max(abs(t["x"]-v["x"]), abs(t["y"]-v["y"])),
                      max(abs(t["x"]-destination["x"]), abs(t["y"]-destination["y"])))
                     for t in obs["threats"] if t["hostile"]]
        if all(after >= before for before, after in distances) and min(a for _, a in distances) > min(b for b, _ in distances):
            factors.append({"reason": "avoidance_increases_separation", "weight": -.1})
    if (not factors and not last_failed and not history.problem() and target
            and plan.get("zone") == v["zone"] and plan.get("tactics", {}).get("mode") in ("travel", "explore")
            and clear_step
            and selected.get("distance_to_plan_target", 999) < max(abs(target["x"]-v["x"]), abs(target["y"]-v["y"]))):
        factors.append({"reason": "clear_goal_directed_step", "weight": -.15})
    return {"policy_version": 2, "base_threshold": base, "factors": factors,
            "threshold": min(.95, max(.35, round(base + sum(f["weight"] for f in factors), 4)))}


def navigation_options(state, plan, options):
    """Apply the upper planner's current local movement envelope without renumbering IDs."""
    if "modal" in state or plan.get("zone") != state["observation"]["vitals"]["zone"]:
        return options
    tactics = effective_tactics(state["observation"], plan)
    allowed = tactics.get("allowed_directions", [])
    if not allowed or tactics.get("mode") not in ("travel", "explore", "avoid"):
        return options
    return [c for c in options if c["args"].get("action") != "move"
            or c["args"].get("dir") in ("U", "D", *allowed)]


def action_ownership(state, plan, history, selected, review):
    """Classify consequence and observed context separately from Jev's probability."""
    def decision(owner, category, reason):
        return {"owner": owner, "category": category, "reason": reason}

    args = selected["args"]
    if "modal" in state:
        if args.get("response", {}).get("cancel") or selected.get("dialog_effect"):
            return decision("jev", "routine_dialogue", "Listen or dismiss without selecting a branch")
        return decision("claude", "dialogue_branch", "dialogue_requires_reasoning")
    obs = state["observation"]
    risk = assess_hazards(obs)
    tactics = effective_tactics(obs, plan)
    action = args["action"]
    category = autonomous_action(state, plan, history, review, selected)
    if category:
        return decision("jev", category, "Within current mission and resource permissions")
    if plan.get("autonomy"):
        return decision("claude", "mission_boundary", "autonomy_action_requires_review")
    if continuation_allows(state, plan, history, review, selected):
        return decision("jev", "reviewed_continuation", "Within the explicit encounter limits")
    if plan.get("continuation"):
        return decision("claude", "continuation_boundary", "continuation_action_outside_contract")
    if (action == "move" and any(r["position"] == selected.get("destination") and r["damage_events"] >= 2
                                for r in history.route_risks(obs))):
        return decision("claude", "repeated_exposure", "repeated_exposure_requires_review")
    enemies = [t for t in obs["threats"] if t["hostile"]]
    healthy = obs["vitals"]["hp"] / max(1, obs["vitals"]["max_hp"]) >= max(.6, tactics.get("heal_hp_fraction", .6))
    if risk["priority"] >= 2 or risk["unknown_effects"]:
        return decision("claude", "danger", "dangerous_context")
    if not healthy and not (not enemies and action in ("rest", "wait") and tactics.get("mode") == "recover"):
        return decision("claude", "danger", "low_hp_requires_review")
    if history.problem() or history.records and history.records[-1]["result"].get("executed") is not True:
        return decision("conditional", "failed_operation", "Inspect the failed result before relaxing probability")
    if action in ("equip", "learn_skill", "raise_attribute", "apply", "open", "get"):
        return decision("claude", "resource_or_build", "action_requires_reasoning")
    if action in ("eat", "drink"):
        item = next((i for i in obs.get("kit", []) if i["id"] == args.get("item")), {})
        detail = next((d for d in obs.get("item_details", []) if d["id"] == args.get("item")), {})
        name = plain(detail.get("comparison_name", item.get("name", "")))
        needs = plain(obs.get("status", {}).get("food_water", ""))
        food = action == "eat" and re.fullmatch(r"(?:bear )?jerky(?: \[[^\]]*servings?\])?", name) and any(
            word in needs for word in ("hungry", "starving"))
        water = action == "drink" and re.fullmatch(r"waterskin \[\d+ drams? of fresh water\]", name) and any(
            word in needs for word in ("thirsty", "dehydrated"))
        if not enemies and not detail.get("effect_details") and (food or water):
            return decision("jev", "routine_consumption", "Known staple or pure water for a current need")
        return decision("claude", "consumable", "consumable_requires_reasoning")
    authorized = (review is not None and not review.pending_reason(obs)
                  and plan.get("zone") == obs["vitals"]["zone"]
                  and not review.avoidance_changed(obs, tactics.get("danger_distance", 6), check_damage=False))
    if not authorized:
        return decision("conditional", "unreviewed_context", "No current upper-level authorization")
    if action == "move" and args.get("dir") not in ("U", "D"):
        destination = selected.get("destination")
        clear = selected.get("glyph") in (".", ",", "'", "`") and not selected.get("occupants")
        distant = destination and all(hostile_distance(obs, t, destination) > tactics.get("danger_distance", 6) for t in enemies)
        target = plan.get("target")
        if target and history.arrived_targets.get((obs["vitals"]["zone"], target["x"], target["y"]), -1) >= plan.get("issued_seq", 0):
            target = None
        progress = (not target or args.get("dir") in tactics.get("allowed_directions", [])
                    or selected.get("distance_to_plan_target", 999) < max(
                        abs(target["x"]-obs["vitals"]["x"]), abs(target["y"]-obs["vitals"]["y"])))
        directed = target or tactics.get("allowed_directions") or tactics.get("mode") == "explore"
        if clear and distant and progress and directed and tactics.get("mode") in ("travel", "explore", "avoid"):
            return decision("jev", "routine_navigation", "Clear step within the reviewed navigation policy")
        if clear and tactics.get("mode") in ("travel", "explore", "avoid") and not progress:
            return decision("claude", "navigation_conflict", "navigation_policy_conflict")
        if enemies and not distant:
            return decision("claude", "close_contact", "contact_requires_review")
    if (action == "attack" and tactics.get("mode") == "combat" and tactics.get("hostile_response") == "fight"
            and len([t for t in enemies if hostile_distance(obs, t) <= tactics.get("danger_distance", 6)]) == 1
            and len(selected.get("occupants", [])) == 1 and selected["occupants"][0]["hostile"]):
        return decision("jev", "routine_combat", "Reviewed single melee target with sufficient HP")
    if action == "attack":
        return decision("claude", "combat", "combat_requires_review")
    if not enemies:
        if action in ("goto", "explore") and tactics.get("mode") in ("travel", "explore"):
            return decision("jev", "bounded_navigation", "Native bounded macro with interruption checks")
        if action in ("rest", "wait") and tactics.get("mode") == "recover":
            return decision("jev", "routine_recovery", "No observed enemy or progressive hazard")
    return decision("conditional", "context_dependent", "Use probability and current tactical policy")


def tactical_scope(reason, state, plan, history, review):
    if reason == "navigation_interrupted":
        last = history.records[-1] if history.records else None
        if not last or last["result"].get("reason") != "ENGINE_STOP" or last["after"]["hp"] < last["before"]["hp"]:
            return False
    return (not plan.get("autonomy") and reason in ("low_probability", "plan_expired", "navigation_interrupted", "target_reached", "navigation_constraints_changed") and "modal" not in state
            and plan.get("zone") == state["observation"]["vitals"]["zone"]
            and plan.get("tactics", {}).get("mode") in ("travel", "explore") and "strategy" in plan
            and not plan.get("tactics", {}).get("allowed_directions")
            and "memory" in plan and bool(review) and not review.pending_reason(state["observation"])
            and safe_to_review(state["observation"]) and not history.problem())


def local_scope(reason, state, plan, review):
    """Update encounter/navigation policy without rewriting an unchanged build."""
    reasons = {"zone_changed", "plan_expired", "continuation_expired", "continuation_new_threat",
               "continuation_threat_approaching", "continuation_action_outside_contract",
               "continuation_hazard_changed", "continuation_hp_floor", "continuation_damage_budget",
               "continuation_operation_failed", "navigation_danger", "navigation_interrupted",
               "navigation_constraints_changed", "navigation_target_unreachable", "target_reached", "recovery_complete", "hazard_changed", "recent_damage",
               "large_damage", "hostile_requires_replan", "avoidance_context_changed", "threat_context_changed",
               "dangerous_context", "low_hp_requires_review", "contact_requires_review", "unsafe_upper_action",
               "jev_unavailable"}
    return ((reason in reasons or reason.startswith("autonomy_")) and "modal" not in state and bool(review)
            and not review.pending_reason(state["observation"])
            and "strategy" in plan and "memory" in plan)


def renew_navigation(state, plan, history, review):
    """Release an expired encounter route only for an unchanged, healthy destination."""
    obs = state["observation"]
    v = obs["vitals"]
    previous = review.reviewed_observation if review else None
    target = plan.get("target")
    issued = plan.get("issued_seq")
    if ("modal" in state or not previous or type(issued) is not int or not target
            or plan.get("stop") or plan.get("zone") != v["zone"] or not safe_to_review(obs)
            or review.pending_reason(obs) or v["hp"] != v["max_hp"]
            or v["hp"] < previous["vitals"]["hp"] or obs.get("goals") != previous.get("goals")
            or plan.get("tactics", {}).get("mode") not in ("travel", "explore")
            or plan.get("tactics", {}).get("allowed_directions") or history.problem()
            or (v["x"], v["y"]) == (target["x"], target["y"])
            or obs["map"][target["y"]][target["x"]] == " "
            or history.arrived_targets.get((v["zone"], target["x"], target["y"]), -1) >= issued):
        return None
    if any(r["seq"] >= issued and (r["result"].get("executed") is not True
                                  or r["after"]["hp"] < r["before"]["hp"])
           for r in history.records):
        return None
    if any(e["kind"] == "risk_outcome" and e["source"]["seq"] > issued
           and e["observed_hp_loss"] > 0 for e in history.events):
        return None
    renewed = copy.deepcopy(plan)
    renewed.update(continuation=None, automatic_goto=True, horizon=12, selection=None)
    renewed["tactics"]["mode"] = "travel"
    return renewed
