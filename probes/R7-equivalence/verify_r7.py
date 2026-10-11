"""R7 direct-vs-UI equivalence verifier (local, deterministic).

Reads ``[R7] {json}`` lines from one or more Player.log files and compares the
``branch_result`` records of the direct and UI branches of each case.
Random outcomes (hits, damage, target HP, throw messages) are never compared;
a record that carries such fields is rejected instead of silently ignored.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PREFIX = "[R7] "

# case -> (direct path, ui path or None if the UI branch is unsupported, compared keys)
DETERMINISTIC = ("energy", "stats", "inventory", "equipment", "skills", "position", "turns",
                 "messages", "popups", "journal")
NON_RANDOM_THROW = ("energy", "stats", "inventory", "equipment", "skills", "position", "turns")
# Look: the InventoryAction route shows the Description popup (Description.cs:335-367) while the Looker
# shows a tooltip (Look.cs:331-401); 06-recommendation.md:304 defines the case as "same journal change".
# Popups are still recorded, just not compared. Messages stay compared.
LOOK_KEYS = tuple(k for k in DETERMINISTIC if k != "popups")
CASES = {
    "BuyStat": ("StatusScreen.BuyStat", "CharacterStatusScreen.HandleSelectPrimaryAttribute", DETERMINISTIC),
    "SelectNode": ("SkillsAndPowersScreen.SelectNode", "SkillsAndPowersLine.Accept", DETERMINISTIC),
    "EquipObject": ("GameObject.EquipObject+CheckStacks", "InventoryAndEquipmentStatusScreen.HandleDragDrop", DETERMINISTIC),
    "Drink": ("InventoryAction.Process:Drink", "InventoryAndEquipmentStatusScreen.HandleQuickDrink", DETERMINISTIC),
    "Eat": ("InventoryAction.Process:Eat", "InventoryAndEquipmentStatusScreen.HandleQuickEat", DETERMINISTIC),
    "Apply": ("InventoryAction.Process:Apply", "InventoryAndEquipmentStatusScreen.HandleQuickApply", DETERMINISTIC),
    "CommandGet": ("FireEvent:CommandGet+TargetCell", "Keyboard.PushCommand:CmdGet", DETERMINISTIC),
    "ThrowWeapon": ("Combat.ThrowWeapon+TargetCell", "Keyboard.PushCommand:CmdThrow+FireMissileWeapon", NON_RANDOM_THROW),
    "CmdWait": ("Shim:CmdWait(XRLCore.cs:1517-1540)", "Keyboard.PushCommand:CmdWait", DETERMINISTIC),
    "Look": ("InventoryAction.Process:Look", "Keyboard.PushCommand:CmdLook+Looker", LOOK_KEYS),
}
# Cases whose UI branch is not implemented. Empty since all 10 routes exist; the None-path handling
# and explicit status:"unsupported" records (e.g. UI_UNAVAILABLE on a classic-UI profile) still apply.
UNSUPPORTED_UI = {}
# A pair of no-ops is not evidence: these cases must change this fingerprint key in both branches.
REQUIRED_EFFECT = {"SelectNode": "skills", "EquipObject": "equipment", "Look": "journal"}
SCREEN_CASES = ("BuyStat", "Drink", "Eat", "Apply", "SelectNode", "EquipObject")
FINGERPRINT_KEYS = {"energy", "stats", "inventory", "equipment", "skills", "position", "turns",
                    "journal", "askForOneItem", "confirmDangerousLiquid"}
RANDOM_KEYS = {"damage", "hit", "hits", "penetrations", "targetHp", "targetHitpoints", "roll", "rolls"}
LOAD_KEYS = ("gameId", "zoneId", "turns", "randomSeed", "nextRandomSeed")
_SCREEN_STEPS = ("completion_signal ", "StatusScreensScreen.Exit", "ShowPopup returned")
# Exact step markers the mod writes (R7Probe.cs). (substring, exact count) per UI case.
UI_MARKERS = {
    "CmdWait": (("Keyboard.PushCommand(CmdWait)", 1), ("consumed_by_PlayerTurn", 1)),
    "CommandGet": (("Keyboard.PushCommand(CmdGet)", 1), ("consumed_by_PlayerTurn", 1)),
    "ThrowWeapon": (("Keyboard.PushCommand(CmdThrow)", 1), ("FireMissileWeapon PointerOver(", 2),
                    ("FireMissileWeapon CmdFire", 1), ("consumed_by_PlayerTurn", 1)),
}
UI_MARKERS["Look"] = (("Keyboard.PushCommand(CmdLook)", 1), ("Looker LeftClick(", 1), ("Looker target tooltip shown", 1),
                      ("Looker Escape", 1), ("consumed_by_PlayerTurn", 1))
UI_MARKERS["SelectNode"] = (("SkillsAndPowersLine active=True", 1),)
for _case in SCREEN_CASES:
    UI_MARKERS[_case] = UI_MARKERS.get(_case, ()) + ((CASES[_case][1] + " invoked on UI thread", 1),) + tuple((m, 1) for m in _SCREEN_STEPS)
FORBIDDEN_UI_STEPS = ("direct_call ", "actions=", "deadline")
SOURCE_LITERALS = ("Keyboard.PushCommand(", "consumed_by_PlayerTurn", "\"FireMissileWeapon \"", "PointerOver(", "\"CmdFire\"",
                   " invoked on UI thread", "completion_signal ", "StatusScreensScreen.Exit", "ShowPopup returned",
                   "direct_call ", "deadline Escape", "\"Looker LeftClick(\"", "\"Looker target tooltip shown\"",
                   "\"Looker Escape\"", "SkillsAndPowersLine active=", "CheckStacks=")


def read_records(paths):
    records = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            at = line.find(PREFIX)
            if at < 0:
                continue
            try:
                value = json.loads(line[at + len(PREFIX):])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def _delta(before, after, key):
    b, a = before.get(key), after.get(key)
    if key in ("energy", "turns"):
        return (a - b) if isinstance(a, int) and isinstance(b, int) else None
    if isinstance(b, list) and isinstance(a, list):
        cb, ca = Counter(map(str, b)), Counter(map(str, a))
        return {"added": sorted((ca - cb).elements()), "removed": sorted((cb - ca).elements())}
    if isinstance(b, dict) and isinstance(a, dict):
        return {k: [b.get(k), a.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}
    return [b, a] if a != b else None


def _record_errors(rec, case, branch):
    errors = []
    direct_path, ui_path, _ = CASES[case]
    for part in ("before", "after"):
        fp = rec.get(part)
        if not isinstance(fp, dict):
            errors.append(f"{branch}:MISSING_{part.upper()}")
            continue
        for key in sorted(FINGERPRINT_KEYS - fp.keys()):
            errors.append(f"{branch}:MISSING_FIELD:{part}.{key}")
        for key in fp:
            if key in RANDOM_KEYS:
                errors.append(f"{branch}:RANDOM_FIELD:{part}.{key}")
            elif key not in FINGERPRINT_KEYS:
                errors.append(f"{branch}:UNEXPECTED_FIELD:{part}.{key}")
    for key in rec:
        if key in RANDOM_KEYS:
            errors.append(f"{branch}:RANDOM_FIELD:{key}")
    if rec.get("errors"):
        errors.append(f"{branch}:ERRORS:{rec['errors']}")
    receipt = rec.get("uiReceipt")
    if branch == "direct":
        if receipt is not None:
            errors.append("direct:HAS_UI_RECEIPT")
        if rec.get("path") != direct_path:
            errors.append(f"direct:PATH:{rec.get('path')}")
        if not any(str(x).startswith("direct_call ") for x in rec.get("directSteps") or []):
            errors.append("direct:NO_DIRECT_CALL_STEP")
    else:
        if not isinstance(receipt, dict):
            errors.append("ui:NO_UI_RECEIPT")
        else:
            if receipt.get("path") != ui_path or rec.get("path") != ui_path:
                errors.append(f"ui:PATH:{receipt.get('path')}")
            if receipt.get("completed") is not True:
                errors.append("ui:RECEIPT_NOT_COMPLETED")
            steps = [str(x) for x in receipt.get("engineSteps") or []]
            for marker, count in UI_MARKERS[case]:
                seen = sum(marker in x for x in steps)
                if seen != count:
                    errors.append(f"ui:MARKER:{marker}:{seen}!={count}")
            for bad in FORBIDDEN_UI_STEPS:
                if any(bad in x for x in steps):
                    errors.append(f"ui:FORBIDDEN_STEP:{bad}")
            if case in SCREEN_CASES and receipt.get("handlerInvoked") is not True:
                errors.append("ui:HANDLER_NOT_INVOKED")
            if receipt.get("directCall") is not False:
                errors.append("ui:DIRECT_CALL_NOT_EXCLUDED")
    before, after = rec.get("before"), rec.get("after")
    effect_key = REQUIRED_EFFECT.get(case)
    if effect_key and isinstance(before, dict) and isinstance(after, dict):
        delta = _delta(before, after, effect_key)
        added = delta.get("added") if isinstance(delta, dict) else None
        if not added:
            errors.append(f"{branch}:NO_EFFECT:{effect_key}")
        elif case == "Look":
            note = (rec.get("args") or {}).get("noteId")
            if not note or not any(str(x).split(":", 1)[-1] == note for x in added):
                errors.append(f"{branch}:NOTE_NOT_REVEALED:{note}")
    return errors


def compare_case(case, direct, ui):
    """Return (status, errors, compared) for one case."""
    if CASES[case][1] is None:
        return "UNSUPPORTED", [UNSUPPORTED_UI.get(case, "UI_UNSUPPORTED")], {}
    if direct is None or ui is None:
        return "MISSING", [f"MISSING_BRANCH:{'direct' if direct is None else 'ui'}"], {}
    unsupported = [r for r in (direct, ui) if r.get("status") == "unsupported"]
    if unsupported:
        return "UNSUPPORTED", [r.get("reason") for r in unsupported], {}
    errors = []
    for rec, branch in ((direct, "direct"), (ui, "ui")):
        if rec.get("status") != "executed":
            errors.append(f"{branch}:STATUS:{rec.get('status')}:{rec.get('reason')}")
        errors += _record_errors(rec, case, branch)
    sha_d, sha_u = direct.get("saveSha256"), ui.get("saveSha256")
    if not isinstance(sha_d, str) or not re.fullmatch(r"[0-9a-f]{64}", sha_d) or sha_d != sha_u:
        errors.append("BASELINE:SAVE_SHA256")
    if direct.get("fixture") != ui.get("fixture") or not direct.get("fixture"):
        errors.append("BASELINE:FIXTURE")
    load_d, load_u = direct.get("load") or {}, ui.get("load") or {}
    for key in LOAD_KEYS:
        if key not in load_d or load_d.get(key) != load_u.get(key):
            errors.append(f"BASELINE:LOAD:{key}")
    if direct.get("args") != ui.get("args"):
        errors.append("BASELINE:ARGS")
    if direct.get("before") != ui.get("before"):
        errors.append("BASELINE:FINGERPRINT")
    compared = {}
    if not errors:
        for key in CASES[case][2]:
            if key in ("messages", "popups"):
                d, u = direct.get(key), ui.get(key)
            else:
                d, u = _delta(direct["before"], direct["after"], key), _delta(ui["before"], ui["after"], key)
            compared[key] = d == u
            if d != u:
                errors.append(f"DIFF:{key}:direct={d!r}:ui={u!r}")
    return ("EQUIVALENT" if not errors else "NOT_EQUIVALENT"), errors, compared


def verify(records, required=None, run_prefix=None):
    required = list(required or CASES)
    results = {}
    by_key = {}
    for rec in records:
        if rec.get("kind") != "branch_result":
            continue
        if run_prefix and not str(rec.get("run", "")).startswith(run_prefix):
            continue
        key = (rec.get("case"), rec.get("branch"))
        by_key.setdefault(key, []).append(rec)
    for case in required:
        if case not in CASES:
            results[case] = {"status": "UNKNOWN_CASE", "errors": [case]}
            continue
        dup = [b for b in ("direct", "ui") if len(by_key.get((case, b), [])) > 1]
        if dup:
            results[case] = {"status": "NOT_EQUIVALENT", "errors": [f"DUPLICATE_BRANCH:{b}" for b in dup]}
            continue
        direct = (by_key.get((case, "direct")) or [None])[0]
        ui = (by_key.get((case, "ui")) or [None])[0]
        status, errors, compared = compare_case(case, direct, ui)
        results[case] = {"status": status, "errors": errors, "compared": compared}
    statuses = {r["status"] for r in results.values()}
    overall = "PASS" if statuses == {"EQUIVALENT"} else (
        "FAIL" if statuses & {"NOT_EQUIVALENT", "UNKNOWN_CASE"} else "INCOMPLETE")
    return {"overall": overall, "cases": results,
            "subset": sorted(required) != sorted(CASES),
            "note": "a PASS on a --case subset is not an R7 pass; runtime equivalence only for EQUIVALENT cases from parent live runs; save SHA-256 is parent-attested"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-log", action="append", required=True)
    parser.add_argument("--case", action="append", help="required case (default: all 10)")
    parser.add_argument("--run-prefix")
    args = parser.parse_args(argv)
    report = verify(read_records(args.player_log), args.case, args.run_prefix)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
