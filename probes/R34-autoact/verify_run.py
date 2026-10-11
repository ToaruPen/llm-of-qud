"""Verify one R3 or R4 run from recorded [R34] Player.log events."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path


MARKER = "[R34] "
MAX_HEARTBEAT_GAP_MS = 2000
MAX_MOVE_STALL_MS = 5000
DURATION_TOLERANCE_MS = 250


class Refused(ValueError):
    """The selected log does not establish the requested result."""


def number(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise Refused(f"invalid {label}: {value!r}")
    return value


def read_log(path: Path) -> tuple[list[str], list[tuple[int, dict]]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise Refused(f"cannot read Player.log: {exc}") from exc
    events = []
    for line_no, line in enumerate(lines):
        if MARKER not in line:
            continue
        try:
            value = json.loads(line.split(MARKER, 1)[1])
        except json.JSONDecodeError as exc:
            raise Refused(f"malformed R34 JSON at line {line_no + 1}: {exc}") from exc
        if not isinstance(value, dict):
            raise Refused(f"R34 record is not an object at line {line_no + 1}")
        events.append((line_no, value))
    return lines, events


def exactly_one(events: list[tuple[int, dict]], kind: str) -> tuple[int, dict]:
    matches = [(line_no, row) for line_no, row in events if row.get("kind") == kind]
    if len(matches) != 1:
        raise Refused(f"selected run requires exactly one {kind} record; found {len(matches)}")
    return matches[0]


def check_leak(row: dict, label: str) -> None:
    if (number(row.get("playerTurnEntries"), f"{label}.playerTurnEntries") != 0 or
            number(row.get("endPlayerTurns"), f"{label}.endPlayerTurns") != 0):
        raise Refused(f"PlayerTurn/EndPlayerTurn leakage in {label}")


def pair_macros(rows: list[dict], result: dict, mode: str) -> dict:
    decisions = []
    outcomes = []
    pending = None
    covered_through = number(result.get("turnStart"), "result.turnStart")
    for row in rows:
        kind = row.get("kind")
        if kind == "decision":
            seq = number(row.get("seq"), "decision.seq", minimum=1)
            if pending is not None or seq != len(decisions) + 1:
                raise Refused("decision/macro_result pair sequence is incomplete or overlapping")
            if row.get("action") not in {"explore", "goto", "rest"}:
                raise Refused(f"unknown decision action: {row.get('action')!r}")
            if number(row.get("turn"), "decision.turn") != covered_through:
                raise Refused("macro turn coverage has a gap or overlap")
            pending = row
            decisions.append(row)
        elif kind == "macro_result":
            if pending is None or row.get("seq") != pending["seq"] or row.get("action") != pending["action"]:
                raise Refused("decision/macro_result pair is missing or mismatched")
            if not isinstance(row.get("reason"), str) or not row["reason"].strip():
                raise Refused("macro_result lacks reason")
            start = number(row.get("turnStart"), "macro_result.turnStart")
            end = number(row.get("turnEnd"), "macro_result.turnEnd")
            turns = number(row.get("turns"), "macro_result.turns")
            if start != pending["turn"] or end - start != turns:
                raise Refused("macro_result turns do not match decision and turn span")
            if end > number(result.get("turnEnd"), "result.turnEnd"):
                raise Refused("macro_result ends after run result")
            number(row.get("moves"), "macro_result.moves")
            outcomes.append(row)
            covered_through = end
            pending = None
    if pending is not None or len(decisions) != len(outcomes):
        raise Refused("decision/macro_result pair is incomplete")
    if len(decisions) != number(result.get("decisions"), "result.decisions"):
        raise Refused("decision count differs from result")
    if covered_through != number(result.get("turnEnd"), "result.turnEnd"):
        raise Refused("macro turn coverage does not reach run end")
    if mode == "r4" and {row["action"] for row in decisions} != {"explore", "goto", "rest"}:
        raise Refused("R4 requires explore, goto, and rest decisions")
    turns = [row["turns"] for row in outcomes]
    count = Counter(row["action"] for row in decisions)
    reasons = Counter(row["reason"] for row in outcomes)
    return {
        "decisions": len(decisions),
        "action_counts": dict(sorted(count.items())),
        "macro_reason_counts": dict(sorted(reasons.items())),
        "turns_per_decision": turns,
        "turn_distribution": {
            "min": min(turns) if turns else None,
            "median": statistics.median(turns) if turns else None,
            "p95": sorted(turns)[math.ceil(len(turns) * 0.95) - 1] if turns else None,
            "max": max(turns) if turns else None,
            "histogram": dict(sorted(Counter(turns).items())),
        },
        "macros": [{"seq": row["seq"], "action": row["action"], "reason": row["reason"],
                    "turns": row["turns"], "moves": row["moves"]} for row in outcomes],
    }


def check_heartbeats(rows: list[dict], result: dict, expected_focus: str) -> dict:
    beats = [row for row in rows if row.get("kind") == "heartbeat"]
    if not beats:
        raise Refused("R3 has no heartbeat evidence")
    elapsed = number(result.get("elapsedMs"), "result.elapsedMs")
    previous_ms = 0
    previous_frame = None
    previous_moves = 0
    last_move_ms = 0
    move_stalls = []
    gaps = []
    for beat in beats:
        check_leak(beat, "heartbeat")
        actual = beat.get("actualFocused")
        if type(actual) is not bool or actual != (expected_focus == "focused"):
            raise Refused("heartbeat actual focus differs from expected focus")
        frame = number(beat.get("frame"), "heartbeat.frame")
        if number(beat.get("frameDelta"), "heartbeat.frameDelta", minimum=1) <= 0:
            raise Refused("heartbeat frame did not advance")
        if previous_frame is not None and frame <= previous_frame:
            raise Refused("heartbeat frame did not advance")
        previous_frame = frame
        beat_ms = number(beat.get("elapsedMs"), "heartbeat.elapsedMs", minimum=1)
        if beat_ms <= previous_ms or beat_ms > elapsed:
            raise Refused("heartbeat elapsed time is non-monotonic or beyond result")
        gap = beat_ms - previous_ms
        reported_gap = beat.get("heartbeatMs")
        if (type(reported_gap) not in (int, float) or not math.isfinite(reported_gap) or
                reported_gap <= 0):
            raise Refused("invalid heartbeat gap measurement")
        if gap > MAX_HEARTBEAT_GAP_MS or reported_gap > MAX_HEARTBEAT_GAP_MS:
            raise Refused(f"heartbeat gap exceeds {MAX_HEARTBEAT_GAP_MS} ms")
        moves = number(beat.get("moves"), "heartbeat.moves")
        if moves < previous_moves:
            raise Refused("heartbeat move count decreased")
        if moves > previous_moves:
            move_stalls.append(beat_ms - last_move_ms)
            last_move_ms = beat_ms
        elif beat_ms - last_move_ms > MAX_MOVE_STALL_MS:
            raise Refused(f"R3 move stall exceeds {MAX_MOVE_STALL_MS} ms")
        previous_moves = moves
        gaps.append(gap)
        previous_ms = beat_ms
    final_gap = elapsed - previous_ms
    if final_gap > MAX_HEARTBEAT_GAP_MS:
        raise Refused(f"heartbeat gap before result exceeds {MAX_HEARTBEAT_GAP_MS} ms")
    result_moves = number(result.get("moves"), "result.moves")
    if result_moves < previous_moves:
        raise Refused("result move count decreased")
    if result_moves > previous_moves:
        move_stalls.append(elapsed - last_move_ms)
        last_move_ms = elapsed
    elif elapsed - last_move_ms > MAX_MOVE_STALL_MS:
        raise Refused(f"R3 move stall exceeds {MAX_MOVE_STALL_MS} ms")
    gaps.append(final_gap)
    movement_windows = []
    window_start_ms = window_start_moves = 0
    # Use actual heartbeat endpoints, avoiding invented sub-second interpolation.
    for point in beats + [result]:
        end_ms, end_moves = point["elapsedMs"], point["moves"]
        duration = end_ms - window_start_ms
        if duration > 0 and (duration >= 60000 or point is result):
            movement_windows.append({"start_ms": window_start_ms, "duration_ms": duration,
                                     "moves": end_moves - window_start_moves,
                                     "move_rate_per_second": (end_moves - window_start_moves) * 1000 / duration})
            window_start_ms, window_start_moves = end_ms, end_moves
    return {"heartbeat_count": len(beats), "max_heartbeat_gap_ms": max(gaps),
            "min_frame_delta": min(beat["frameDelta"] for beat in beats),
            "max_move_stall_ms": max(move_stalls) if move_stalls else elapsed,
            "movement_windows": movement_windows}


def verify_run(lines: list[str], events: list[tuple[int, dict]], run_id: str,
               expected_focus: str | None) -> dict:
    selected = [(line_no, row) for line_no, row in events if row.get("id") == run_id]
    if not selected:
        raise Refused(f"run ID not found: {run_id}")
    armed_at, armed = exactly_one(selected, "armed")
    begin_at, begin = exactly_one(selected, "begin")
    result_at, result = exactly_one(selected, "result")
    if not armed_at < begin_at < result_at or any(line_no > result_at for line_no, _ in selected):
        raise Refused("selected run has incomplete or ambiguous record order")
    if any(row.get("kind") in {"game_error", "control_error", "ui_error", "player_turn_entered"}
           for _, row in selected):
        raise Refused("selected run contains error or PlayerTurn event")
    for line_no, row in events:
        if armed_at <= line_no <= result_at and row.get("kind") in {"ui_error", "control_error"}:
            raise Refused(f"unscoped R34 error during selected run at line {line_no + 1}")
    for line in lines[armed_at:result_at + 1]:
        if MARKER not in line and ("ERROR -" in line or re.search(r"\b\w*Exception:\s", line)):
            raise Refused("runtime error during selected run")
    mode = begin.get("mode")
    if mode not in {"r3", "r4"} or armed.get("mode") != mode or result.get("mode") != mode:
        raise Refused("run mode missing or inconsistent")
    focus = begin.get("focus")
    if focus not in {"focused", "unfocused"} or armed.get("focus") != focus or result.get("focus") != focus:
        raise Refused("run focus label missing or inconsistent")
    if expected_focus is not None and focus != expected_focus:
        raise Refused("run focus label differs from expected focus")
    if result.get("reason") != "COMPLETE" or result.get("pass") is not True:
        raise Refused("run did not COMPLETE successfully")
    check_leak(result, "result")
    start = number(result.get("turnStart"), "result.turnStart")
    end = number(result.get("turnEnd"), "result.turnEnd")
    turns = number(result.get("turns"), "result.turns")
    if start != number(begin.get("turn"), "begin.turn") or end - start != turns:
        raise Refused("result turns do not match turn span")
    moves = number(result.get("moves"), "result.moves")
    elapsed = number(result.get("elapsedMs"), "result.elapsedMs", minimum=1)
    body = [row for line_no, row in selected if begin_at < line_no < result_at]
    for row in body:
        if row.get("kind") == "heartbeat":
            check_leak(row, "heartbeat")
    metrics = {"ok": True, "run_id": run_id, "mode": mode, "focus": focus,
               "reason": "COMPLETE", "elapsed_ms": elapsed, "turns": turns,
               "moves": moves, "move_rate_per_second": moves * 1000.0 / elapsed,
               "player_turn_entries": 0, "end_player_turns": 0}
    metrics.update(pair_macros(body, result, mode))
    if mode == "r4":
        target = number(begin.get("targetTurns"), "begin.targetTurns")
        if target < 500 or number(armed.get("turns"), "armed.turns") != target:
            raise Refused("R4 must request at least 500 turns consistently")
        if turns < target:
            raise Refused("R4 actual turns are below requested target")
        metrics["requested_turns"] = target
        metrics["scope"] = "runtime_log_only"
        metrics["external_input_unverified"] = True
    else:
        if expected_focus is None:
            raise Refused("R3 requires --expected-focus")
        seconds = number(begin.get("seconds"), "begin.seconds", minimum=1)
        if number(armed.get("seconds"), "armed.seconds") != seconds:
            raise Refused("R3 requested seconds are inconsistent")
        if elapsed < seconds * 1000 - DURATION_TOLERANCE_MS:
            raise Refused("R3 duration shorter than requested")
        metrics["requested_seconds"] = seconds
        metrics.update(check_heartbeats(body, result, expected_focus))
        metrics["scope"] = "runtime_log_only; OBS, picker, hover and window coverage unverified"
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-log", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-focus", choices=("focused", "unfocused"))
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--baseline-log", type=Path)
    args = parser.parse_args(argv)
    try:
        lines, events = read_log(args.player_log)
        metrics = verify_run(lines, events, args.run_id, args.expected_focus)
        if args.baseline_run_id:
            if args.baseline_run_id == args.run_id:
                raise Refused("baseline run ID must differ from selected run ID")
            if metrics["mode"] != "r3" or metrics["focus"] != "unfocused":
                raise Refused("move-rate baseline is only for an unfocused R3 run")
            baseline_lines, baseline_events = (read_log(args.baseline_log) if args.baseline_log
                                               else (lines, events))
            baseline = verify_run(baseline_lines, baseline_events, args.baseline_run_id, "focused")
            if baseline["mode"] != "r3" or baseline["move_rate_per_second"] <= 0:
                raise Refused("focused R3 baseline is missing movement")
            ratio = metrics["move_rate_per_second"] / baseline["move_rate_per_second"]
            if ratio < 0.8 - 1e-9:
                raise Refused(f"unfocused move rate is below 80% of focused baseline: {ratio:.3f}")
            metrics["baseline_run_id"] = args.baseline_run_id
            metrics["baseline_move_rate_per_second"] = baseline["move_rate_per_second"]
            metrics["move_rate_ratio"] = ratio
            for window in metrics["movement_windows"]:
                window["baseline_ratio"] = window["move_rate_per_second"] / baseline["move_rate_per_second"]
                window["checked"] = window["duration_ms"] >= 10000
                if window["checked"] and window["baseline_ratio"] < 0.8 - 1e-9:
                    raise Refused(f"movement window at {window['start_ms']} ms is below 80% "
                                  f"of focused baseline: {window['baseline_ratio']:.3f}")
        elif args.baseline_log:
            raise Refused("--baseline-log requires --baseline-run-id")
    except Refused as exc:
        print(f"R34 REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
