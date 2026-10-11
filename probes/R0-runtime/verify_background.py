"""Check background lifecycle and desktop observations; evidence is not authenticated."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from uuid import UUID


LIFECYCLE = ("background_loaded", "background_saved", "background_quit")
SCOPE = "offline_background_lifecycle_and_desktop_observation"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON field: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def object_record(raw, source):
    value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    require(isinstance(value, dict), f"{source}: expected a JSON object")
    return value


def read_record(path):
    return object_record(path.read_text(encoding="utf-8"), path)


def integer(record, key, minimum=0):
    value = record.get(key)
    require(type(value) is int and value >= minimum,
            f"{key}: expected integer >= {minimum}, got {value!r}")
    return value


def uuid_field(record, key):
    value = record.get(key)
    require(isinstance(value, str), f"{key}: expected UUID string")
    UUID(value)
    return value


def hash_field(record, key):
    value = record.get(key)
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{key}: expected lowercase SHA-256")
    return value


def lifecycle_events(path):
    events = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if "[LLM]" not in line:
                continue
            event = object_record(line.split("[LLM]", 1)[1].strip(), f"{path}:{number}")
            kind = event.get("kind")
            require(isinstance(kind, str) and kind, f"{path}:{number}: missing event kind")
            require(kind not in ("background_error", "game_fault"),
                    f"{path}:{number}: {kind}")
            if kind in LIFECYCLE:
                events.append(event)
    return events


def check_lifecycle(events):
    require(tuple(event["kind"] for event in events) == LIFECYCLE,
            "expected unique ordered background_loaded -> background_saved -> background_quit")
    loaded, saved, quit_event = events
    run_id = uuid_field(loaded, "run_id")
    game_id = uuid_field(loaded, "game_id")
    integer(loaded, "loaded_turn")
    integer(saved, "turn")
    hash_field(saved, "save_sha256")
    require(saved.get("run_id") == quit_event.get("run_id") == run_id,
            "lifecycle run_id mismatch")
    require(saved.get("game_id") == game_id, "lifecycle game_id mismatch")
    if "game_id" in quit_event:
        require(quit_event["game_id"] == game_id, "quit game_id mismatch")
    require(integer(saved, "seq", 1) == integer(quit_event, "seq", 1),
            "saved/quit seq mismatch")
    return loaded, saved


def check_previous(path, start):
    events = lifecycle_events(path)
    require(events and len(events) % 3 == 0, "previous lifecycle is incomplete")
    seen = set()
    for index in range(0, len(events), 3):
        loaded, saved = check_lifecycle(events[index:index + 3])
        require(loaded["run_id"] not in seen, "duplicate previous run_id")
        seen.add(loaded["run_id"])
    require(saved["run_id"] != start["run_id"], "previous run_id must differ")
    require(saved["game_id"] == start["game_id"], "previous game_id mismatch")
    require(saved["turn"] == start["save_turn"], "previous saved turn mismatch")
    require(saved["save_sha256"] == start["save_sha256"], "previous saved hash mismatch")
    return saved["run_id"]


def check_log_linkage(launch, command, report_path, log_path):
    # Preserve relocation while rejecting accidental selection from another run directory.
    require(report_path.resolve().parent == log_path.resolve().parent,
            "launch-report and player-log must be siblings")
    require(command.count("-logFile") == 1, "command must contain exactly one -logFile")
    index = command.index("-logFile") + 1
    require(index < len(command), "-logFile must have a path value")
    configured_log = Path(command[index])
    run_dir = launch.get("run_dir")
    require(isinstance(run_dir, str) and run_dir and Path(run_dir).is_absolute(),
            "run_dir must be an absolute path string")
    require(configured_log.is_absolute() and configured_log.parent == Path(run_dir),
            "historical -logFile parent must equal launch run_dir")
    require(configured_log.name == log_path.name, "player-log basename does not match -logFile")


def verify(args):
    start = read_record(args.start)
    run_id = uuid_field(start, "run_id")
    game_id = uuid_field(start, "game_id")
    initial_turn = integer(start, "save_turn")
    initial_hash = hash_field(start, "save_sha256")

    launch = read_record(args.launch_report)
    require(launch.get("launch_mode") == "batchmode", "launch_mode must be batchmode")
    command = launch.get("command")
    require(isinstance(command, list) and command and
            all(isinstance(arg, str) and arg for arg in command) and
            command.count("-batchmode") == 1, "command must contain exactly one -batchmode")
    check_log_linkage(launch, command, args.launch_report, args.player_log)
    pid = integer(launch, "pid", 1)
    require(integer(launch, "exit_code") == 0, "launch exit_code must be zero")

    observation = read_record(args.desktop_observation)
    require(integer(observation, "pid", 1) == pid, "observation/launch PID mismatch")
    samples = integer(observation, "samples", 1)
    require(observation.get("exit_observed") is True, "process exit was not observed")
    for key in ("activation_events", "active_samples", "max_onscreen_windows", "window_query_failures"):
        require(integer(observation, key) == 0, f"{key} must be zero")

    loaded, saved = check_lifecycle(lifecycle_events(args.player_log))
    require(loaded["run_id"] == run_id, "start/lifecycle run_id mismatch")
    require(loaded["game_id"] == game_id, "start/lifecycle game_id mismatch")
    require(loaded["loaded_turn"] == initial_turn, "loaded_turn does not match requested save_turn")
    with args.saved_game.open("rb") as stream:
        saved_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    require(saved_hash == saved["save_sha256"], "saved-game SHA-256 mismatch")
    require(saved_hash != initial_hash, "saved-game hash did not change")
    previous = check_previous(args.previous_player_log, start) if args.previous_player_log else None
    return {"ok": True, "acceptance": SCOPE, "run_id": run_id, "game_id": game_id,
            "pid": pid, "samples": samples, "loaded_turn": initial_turn,
            "saved_turn": saved["turn"], "saved_sha256": saved_hash,
            "previous_run_id": previous,
            "not_proven": ["M2", "autonomous_llm_play", "runtime_build", "ledger", "evidence_authenticity"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("start", "launch-report", "player-log", "desktop-observation", "saved-game"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--previous-player-log", type=Path)
    args = parser.parse_args()
    try:
        report = verify(args)
    except (OSError, ValueError) as error:
        report = {"ok": False, "acceptance": SCOPE, "error": str(error)}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
