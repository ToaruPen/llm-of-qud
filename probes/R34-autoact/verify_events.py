"""Offline checks for staged R34 hover and simulated picker-loss events."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path


class Refused(ValueError):
    pass


def one(rows: list[dict], kind: str) -> tuple[int, dict]:
    found = [(index, row) for index, row in enumerate(rows) if row.get("kind") == kind]
    if len(found) != 1:
        raise Refused(f"requires exactly one {kind}; found {len(found)}")
    return found[0]


def checked_run(rows: list[dict], mode: str) -> tuple[int, int]:
    begin_index, begin = one(rows, "begin")
    result_index, result = one(rows, "result")
    if begin_index >= result_index or result_index != len(rows) - 1:
        raise Refused("incomplete or reordered run")
    if begin.get("mode") != mode or result.get("mode") != mode:
        raise Refused("wrong run mode")
    if result.get("reason") != "COMPLETE" or result.get("pass") is not True:
        raise Refused("run did not complete successfully")
    if result.get("playerTurnEntries") != 0 or result.get("endPlayerTurns") != 0:
        raise Refused("PlayerTurn/EndPlayerTurn leakage")
    if any(row.get("kind") in {"game_error", "ui_error", "hover_error", "hover_close_error",
                                "hover_status_unknown", "hover_page_mismatch", "control_error",
                                "player_turn_entered"} for row in rows):
        raise Refused("run contains an error")
    return begin_index, result_index


def string_list(value: object, name: str) -> list[str | None]:
    if not isinstance(value, list) or any(item is not None and not isinstance(item, str) for item in value):
        raise Refused(f"invalid queue snapshot: {name}")
    return value


def verify_hover(rows: list[dict], expected_focus: str) -> dict:
    if expected_focus not in {"focused", "unfocused"}:
        raise Refused("expected focus must be focused or unfocused")
    begin_index, result_index = checked_run(rows, "hover")
    if rows[begin_index].get("focus") != expected_focus:
        raise Refused("hover focus label differs from expected")
    status_index, status = one(rows, "hover_status_open")
    target_index, target = one(rows, "hover_target")
    before_index, before = one(rows, "hover_before_exit")
    exit_index, exit_event = one(rows, "hover_pointer_exit_event")
    after_index, after = one(rows, "hover_after_exit")
    evidence_index, evidence = one(rows, "hover_evidence")
    if not begin_index < status_index < target_index < before_index < exit_index < after_index < evidence_index < result_index:
        raise Refused("hover event order does not show a tooltip followed by an actual pointer exit")
    if status.get("pending") is not True or not target.get("name"):
        raise Refused("pending owned status or visible item name is missing")
    object_hash = target.get("objectHash")
    expected = target.get("expectedTaskId")
    if type(object_hash) is not int or expected != f"LookedAt{object_hash}":
        raise Refused("expected LookedAt task ID does not match target")
    for name in ("clientX", "clientYTop"):
        value = target.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise Refused(f"invalid {name}")
    width, height = target.get("screenWidth"), target.get("screenHeight")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise Refused("invalid Unity screen dimensions")
    unity_x, unity_y = target.get("unityX"), target.get("unityY")
    if (type(unity_x) not in (int, float) or type(unity_y) not in (int, float) or
            not math.isfinite(unity_x) or not math.isfinite(unity_y)):
        raise Refused("invalid Unity pixel coordinates")
    if (abs(target["clientX"] - unity_x / width) > 0.001 or
            abs(target["clientYTop"] - (1 - unity_y / height)) > 0.001):
        raise Refused("normalized client coordinates do not match Unity pixels")
    if before.get("tooltipShown") is not True or before.get("pointerInside") is not True:
        raise Refused("tooltip was not observed with pointer inside")
    if after.get("pointerExitEvent") is not True or after.get("pointerInside") is not False:
        raise Refused("actual pointer exit was not observed")
    for event in (before, exit_event, after):
        if event.get("actualFocused") is not (expected_focus == "focused"):
            raise Refused("actual focus differed during hover transition")
    if before.get("expectedTaskId") != expected or after.get("expectedTaskId") != expected:
        raise Refused("queue snapshots target different items")
    queue_before = string_list(before.get("queueTaskIds"), "before")
    queue_after = string_list(after.get("queueTaskIds"), "after")
    if expected in queue_before or expected not in queue_after:
        raise Refused("LookedAt task was not newly queued by tooltip exit")
    if (after.get("taskNewlyQueued") is not True or evidence.get("taskNewlyQueued") is not True or
            evidence.get("tooltipShown") is not True or evidence.get("pointerExitObserved") is not True or
            evidence.get("pass") is not True or evidence.get("queueBefore") != queue_before or
            evidence.get("queueAfter") != queue_after):
        raise Refused("hover evidence disagrees with queue snapshots")
    return {"ok": True, "mode": "hover", "focus": expected_focus,
            "expected_task_id": expected, "queued_during_block": True,
            "task_execution_verified": False, "scope": "tooltip_exit_and_pending_gameQueue_only"}


def verify_picker_retry(rows: list[dict]) -> dict:
    begin_index, result_index = checked_run(rows, "picker")
    if rows[begin_index].get("dropFirstPickerPush") is not True:
        raise Refused("picker simulated-loss switch was not enabled")
    results = [(i, row) for i, row in enumerate(rows) if row.get("kind") == "picker_result"]
    if len(results) != 10 or [row.get("seq") for _, row in results] != list(range(1, 11)):
        raise Refused("requires ten ordered picker results")
    if any(row.get("seq") not in range(1, 11) for row in rows
           if row.get("kind") in {"picker_drop_simulated", "picker_push"}):
        raise Refused("unpaired picker loss or push outside the ten requested pickers")
    for seq, (result_i, result) in enumerate(results, 1):
        drops = [(i, row) for i, row in enumerate(rows) if row.get("kind") == "picker_drop_simulated" and row.get("seq") == seq]
        pushes = [(i, row) for i, row in enumerate(rows) if row.get("kind") == "picker_push" and row.get("seq") == seq]
        if len(drops) != 1 or len(pushes) < 1:
            raise Refused(f"picker {seq} lacks simulated loss or actual retry")
        drop_i, drop = drops[0]
        if not begin_index < drop_i < pushes[0][0] < result_i < result_index:
            raise Refused(f"picker {seq} event order is wrong")
        if drop.get("attempt") != 1 or drop.get("beforeEnqueue") is not True:
            raise Refused(f"picker {seq} first attempt was not explicitly discarded before enqueue")
        if any(i >= result_i or row.get("key") != "Keypad6" or row.get("simulatedLoss") is not True
               for i, row in pushes):
            raise Refused(f"picker {seq} actual retry record is invalid")
        if [row.get("attempt") for _, row in pushes] != list(range(2, len(pushes) + 2)):
            raise Refused(f"picker {seq} retry attempts are not contiguous")
        if (result.get("actual") != "E" or result.get("pass") is not True or
                result.get("simulatedLoss") is not True or result.get("simulatedDrops") != 1 or
                result.get("pushes") != len(pushes) or result.get("attempts") != len(pushes) + 1 or
                type(result.get("focusChanges")) is not int or result["focusChanges"] < 2):
            raise Refused(f"picker {seq} did not prove a correct retry across focus transitions")
    return {"ok": True, "mode": "picker", "correct_pickers": 10,
            "simulated_drops": 10, "actual_retries": sum(row.get("kind") == "picker_push" for row in rows),
            "scope": "simulated_pre_enqueuing_loss;not_real_transport_loss"}


def selected_events(path: Path, run_id: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    events: list[tuple[int, dict]] = []
    for line_no, line in enumerate(lines):
        if "[R34] " not in line:
            continue
        try:
            row = json.loads(line.split("[R34] ", 1)[1])
        except json.JSONDecodeError as exc:
            raise Refused(f"malformed R34 event at line {line_no + 1}: {exc}") from exc
        if not isinstance(row, dict):
            raise Refused(f"non-object R34 event at line {line_no + 1}")
        events.append((line_no, row))
    selected = [(line_no, row) for line_no, row in events if row.get("id") == run_id]
    if not selected:
        raise Refused(f"run ID not found: {run_id}")
    begin_at = [line_no for line_no, row in selected if row.get("kind") == "begin"]
    result_at = [line_no for line_no, row in selected if row.get("kind") == "result"]
    if len(begin_at) != 1 or len(result_at) != 1:
        raise Refused("selected run lacks unique begin/result")
    for line_no, row in events:
        if begin_at[0] <= line_no <= result_at[0] and row.get("kind") in {"ui_error", "control_error"}:
            raise Refused(f"unscoped probe error at line {line_no + 1}")
    for line in lines[begin_at[0]:result_at[0] + 1]:
        if "[R34] " not in line and ("ERROR -" in line or re.search(r"\b\w*Exception:\s", line)):
            raise Refused("runtime error during selected run")
    return [row for _, row in selected]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-log", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("hover", "picker-retry"), required=True)
    parser.add_argument("--expected-focus", choices=("focused", "unfocused"))
    args = parser.parse_args()
    try:
        rows = selected_events(args.player_log, args.run_id)
        if args.mode == "hover":
            if args.expected_focus is None:
                raise Refused("hover requires --expected-focus")
            metrics = verify_hover(rows, args.expected_focus)
        else:
            metrics = verify_picker_retry(rows)
        metrics["run_id"] = args.run_id
    except (Refused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
