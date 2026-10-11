"""Decode R34's on-screen frame counter from an OBS recording."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Iterable


# OBS scene: 1280x720; the 2560x1345 game capture is scaled to half size.
# Two magenta anchors occupy x=8..19; bit i is centered at x=23+6*i.
CROP_X = 8
CROP_Y = 50
CROP_WIDTH = 108
CROP_HEIGHT = 2  # YUV crop requires an even height; only the first RGB row is sampled.
ROW_BYTES = CROP_WIDTH * 3
FRAME_BYTES = ROW_BYTES * CROP_HEIGHT
ANCHOR_X = (11 - CROP_X, 17 - CROP_X)
BIT_X = tuple(23 + 6 * bit - CROP_X for bit in range(16))


class Refused(ValueError):
    """The recording cannot establish the requested capture metric."""


def rgb(row: bytes, x: int) -> tuple[int, int, int]:
    index = x * 3
    return row[index], row[index + 1], row[index + 2]


def is_magenta(color: tuple[int, int, int]) -> bool:
    red, green, blue = color
    return red >= 180 and blue >= 180 and green <= 90 and red - green >= 100 and blue - green >= 100


def decode_row(row: bytes) -> tuple[str, int | None]:
    if len(row) != ROW_BYTES:
        return "invalid", None
    anchors = [is_magenta(rgb(row, x)) for x in ANCHOR_X]
    if not any(anchors):
        return "absent", None
    if not all(anchors):
        return "invalid", None
    code = 0
    for bit, x in enumerate(BIT_X):
        color = rgb(row, x)
        if min(color) >= 180:
            code |= 1 << bit
        elif max(color) <= 75:
            continue
        else:
            return "invalid", None
    return "valid", code


def windows(statuses: list[tuple[str, int | None]], first: int, last: int,
            fps: float, seconds: int) -> list[dict]:
    frame_span = seconds * fps
    count = math.ceil((last - first + 1) / frame_span)
    result = []
    for bucket in range(count):
        start = first + math.ceil(bucket * frame_span)
        end = min(last + 1, first + math.ceil((bucket + 1) * frame_span))
        changes = repeats = valid = invalid = 0
        for index in range(start, end):
            state, code = statuses[index]
            if state == "valid":
                valid += 1
                if index > start and statuses[index - 1][0] == "valid":
                    if code != statuses[index - 1][1]:
                        changes += 1
                    else:
                        repeats += 1
            elif state == "invalid":
                invalid += 1
        duration = (end - start) / fps
        result.append({"start_seconds": bucket * seconds,
                       "duration_seconds": duration,
                       "output_frames": end - start,
                       "valid_marker_frames": valid,
                       "invalid_marker_frames": invalid,
                       "fresh_transitions": changes,
                       "repeat_frames": repeats,
                       "fresh_source_fps": changes / duration if duration else 0.0})
    return result


def analyze_rows(rows: Iterable[bytes], *, fps: float, min_active_seconds: float = 0,
                 baseline_fresh_source_fps: float | None = None, min_ratio: float = 0.8) -> dict:
    if not math.isfinite(fps) or fps <= 0:
        raise Refused("output fps must be positive")
    statuses = [decode_row(row) for row in rows]
    valid_indices = [index for index, (state, _) in enumerate(statuses) if state == "valid"]
    failures = []
    if not valid_indices:
        failures.append("no valid R34 frame marker found")
    first = valid_indices[0] if valid_indices else None
    last = valid_indices[-1] if valid_indices else None
    active_frames = last - first + 1 if first is not None else 0
    active_seconds = active_frames / fps
    invalid_total = sum(state == "invalid" for state, _ in statuses)
    if invalid_total:
        failures.append(f"{invalid_total} invalid marker frames (decoding failure)")
    gaps = []
    if first is not None:
        index = first
        while index <= last:
            state = statuses[index][0]
            if state == "valid":
                index += 1
                continue
            start = index
            while index <= last and statuses[index][0] == state:
                index += 1
            gaps.append({"start_frame": start, "end_frame": index - 1,
                         "frames": index - start, "seconds": (index - start) / fps,
                         "reason": state})
    if gaps:
        failures.append(f"{len(gaps)} internal marker gaps")
    if min_active_seconds and active_seconds < min_active_seconds:
        failures.append(f"active duration {active_seconds:.3f}s is below {min_active_seconds:.3f}s")

    transitions = repeats = segments = longest_same = same_run = 0
    for index in range(first or 0, (last + 1) if last is not None else 0):
        state, code = statuses[index]
        if state != "valid":
            same_run = 0
            continue
        previous = statuses[index - 1] if index > first else ("absent", None)
        if previous[0] == "valid" and previous[1] == code:
            repeats += 1
            same_run += 1
        else:
            segments += 1
            if previous[0] == "valid":
                transitions += 1
            same_run = 1
        longest_same = max(longest_same, same_run)
    fresh_source_fps = transitions / active_seconds if active_seconds else 0.0
    metrics = {
        "kind": "r34_capture",
        "ok": not failures,
        "failures": failures,
        "warnings": [],
        "output_fps": fps,
        "recorded_frames": len(statuses),
        "recorded_duration_seconds": len(statuses) / fps,
        "first_marker_frame": first,
        "last_marker_frame": last,
        "active_frames": active_frames,
        "active_duration_seconds": active_seconds,
        "valid_marker_frames": len(valid_indices),
        "outer_absent_frames": sum(state == "absent" for state, _ in statuses[:first or 0]) +
                               sum(state == "absent" for state, _ in statuses[(last + 1) if last is not None else 0:]),
        "invalid_marker_frames": invalid_total,
        "internal_gaps": gaps,
        "fresh_transitions": transitions,
        "consecutive_code_segments": segments,
        "repeat_frames": repeats,
        "fresh_source_fps": fresh_source_fps,
        "worst_repeat_frames": longest_same,
        "worst_freeze_seconds": max(0, longest_same - 1) / fps,
        "per_10_seconds": windows(statuses, first, last, fps, 10) if first is not None else [],
        "per_minute": windows(statuses, first, last, fps, 60) if first is not None else [],
        "sampling": {"crop": [CROP_X, CROP_Y, CROP_WIDTH, CROP_HEIGHT],
                     "anchor_x": [11, 17], "bit_x_first": 23, "bit_width": 6, "sample_y": 50},
        "scope": "observed_game_frame_updates_in_OBS_recording",
    }
    if baseline_fresh_source_fps is not None:
        if not math.isfinite(baseline_fresh_source_fps) or baseline_fresh_source_fps <= 0:
            raise Refused("baseline fresh source fps must be positive")
        if not math.isfinite(min_ratio) or min_ratio <= 0:
            raise Refused("minimum ratio must be positive")
        ratio = fresh_source_fps / baseline_fresh_source_fps
        metrics["baseline_fresh_source_fps"] = baseline_fresh_source_fps
        metrics["fresh_source_ratio"] = ratio
        metrics["minimum_ratio"] = min_ratio
        if ratio < min_ratio:
            failures.append(f"fresh source fps ratio {ratio:.3f} is below {min_ratio:.3f}")
        for output_key, window_key in (("window_ratio_checks", "per_10_seconds"),
                                       ("minute_ratio_checks", "per_minute")):
            checks = []
            for window in metrics[window_key]:
                window_ratio = window["fresh_source_fps"] / baseline_fresh_source_fps
                checked = window["duration_seconds"] >= 10 - 1e-9
                checks.append({"start_seconds": window["start_seconds"],
                               "duration_seconds": window["duration_seconds"],
                               "fresh_source_fps": window["fresh_source_fps"],
                               "ratio": window_ratio, "checked": checked,
                               "minimum_checked_seconds": 10})
                if checked and window_ratio < min_ratio:
                    failures.append(
                        f"{window_key} window at {window['start_seconds']}s has fresh source fps ratio "
                        f"{window_ratio:.3f} below {min_ratio:.3f}")
            metrics[output_key] = checks
    metrics["ok"] = not failures
    return metrics


def reconcile_frame_counts(metrics: dict, *, declared: int | None, decodable: int | None) -> None:
    metrics["container_declared_frames"] = declared
    metrics["ffprobe_decodable_frames"] = decodable
    if declared is not None and decodable is not None and declared != decodable:
        metrics["warnings"].append(
            f"container frame-count discrepancy: declared {declared}, decodable {decodable}")
    if decodable is None:
        metrics["failures"].append("ffprobe did not establish decodable frame count")
    elif metrics["recorded_frames"] != decodable:
        metrics["failures"].append(
            f"decoded frame count {metrics['recorded_frames']} differs from ffprobe decodable {decodable}")
    metrics["ok"] = not metrics["failures"]


def probe_video(path: Path, ffprobe: str) -> tuple[float, int | None, int | None]:
    command = [ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,avg_frame_rate,nb_frames,nb_read_frames", "-of", "json", str(path)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise Refused(f"ffprobe unavailable: {exc}") from exc
    if completed.returncode:
        raise Refused(f"ffprobe failed: {completed.stderr.strip()}")
    try:
        streams = json.loads(completed.stdout)["streams"]
        video = streams[0]
        if (video["width"], video["height"]) != (1280, 720):
            raise Refused("recording must use the confirmed 1280x720 OBS scene")
        fps = float(Fraction(video["avg_frame_rate"]))
        declared_frames = int(video["nb_frames"]) if video.get("nb_frames", "N/A") != "N/A" else None
        decodable_frames = int(video["nb_read_frames"]) if video.get("nb_read_frames", "N/A") != "N/A" else None
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise Refused(f"invalid ffprobe video metadata: {exc}") from exc
    if not math.isfinite(fps) or fps <= 0:
        raise Refused("invalid output fps")
    return fps, declared_frames, decodable_frames


def cropped_rows(path: Path, ffmpeg: str) -> Iterable[bytes]:
    command = [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
               "-vf", f"crop={CROP_WIDTH}:{CROP_HEIGHT}:{CROP_X}:{CROP_Y},format=rgb24",
               "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise Refused(f"ffmpeg unavailable: {exc}") from exc
    assert process.stdout is not None and process.stderr is not None
    try:
        while True:
            frame = process.stdout.read(FRAME_BYTES)
            if not frame:
                break
            if len(frame) != FRAME_BYTES:
                raise Refused("truncated raw RGB frame from ffmpeg")
            yield frame[:ROW_BYTES]
        error = process.stderr.read().decode("utf-8", errors="replace").strip()
        if process.wait() != 0:
            raise Refused(f"ffmpeg decoding failed: {error}")
        if error:
            raise Refused(f"ffmpeg decoder error output: {error}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clip", required=True, type=Path)
    parser.add_argument("--min-active-seconds", type=float, default=0)
    parser.add_argument("--baseline-json", type=Path)
    parser.add_argument("--min-ratio", type=float, default=0.8)
    parser.add_argument("--ffmpeg", default="/opt/homebrew/bin/ffmpeg")
    parser.add_argument("--ffprobe", default="/opt/homebrew/bin/ffprobe")
    args = parser.parse_args(argv)
    try:
        if not args.clip.is_file():
            raise Refused(f"clip not found: {args.clip}")
        if not math.isfinite(args.min_active_seconds) or args.min_active_seconds < 0:
            raise Refused("minimum active seconds must be nonnegative")
        if not math.isfinite(args.min_ratio) or args.min_ratio <= 0:
            raise Refused("minimum ratio must be positive")
        if not args.baseline_json and args.min_ratio != 0.8:
            raise Refused("--min-ratio requires --baseline-json")
        baseline_fps = None
        if args.baseline_json:
            try:
                baseline = json.loads(args.baseline_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise Refused(f"cannot read baseline JSON: {exc}") from exc
            if not isinstance(baseline, dict) or baseline.get("kind") != "r34_capture" or baseline.get("ok") is not True:
                raise Refused("baseline must be a passing R34 capture report")
            baseline_fps = baseline.get("fresh_source_fps")
            if type(baseline_fps) not in (int, float):
                raise Refused("baseline fresh source fps is missing")
        fps, declared_frames, decodable_frames = probe_video(args.clip, args.ffprobe)
        metrics = analyze_rows(cropped_rows(args.clip, args.ffmpeg), fps=fps,
                               min_active_seconds=args.min_active_seconds,
                               baseline_fresh_source_fps=baseline_fps, min_ratio=args.min_ratio)
        reconcile_frame_counts(metrics, declared=declared_frames, decodable=decodable_frames)
        metrics["clip"] = str(args.clip.resolve())
    except Refused as exc:
        print(json.dumps({"kind": "r34_capture", "ok": False, "failures": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if metrics["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
