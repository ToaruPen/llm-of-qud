"""Shared fixtures that imitate the C# bridge's wire frames.

The frames are serialized the way a non-Python peer would (key order as written,
non-ASCII glyphs kept verbatim, spaces after separators) so byte-exact replay
checks cannot accidentally pass because both sides use Python's compact form.
"""

import json
import uuid

RUN_ID = "3f2b8c1e-9d4a-4e6b-8a71-0c5d2e9f1a47"
OTHER_RUN_ID = "b7e1d3a0-2c4f-4a8e-9b6d-5f1e0a3c7d92"


def make_map(px=40, py=12):
    rows = []
    for y in range(25):
        if y in (0, 24):
            row = "#" * 80
        else:
            row = "#" + "." * 78 + "#"
        if y == 5:
            row = row[:10] + "░░▒▓" + row[14:]
        if y == py:
            row = row[:px] + "@" + row[px + 1:]
        if y == py and px + 3 < 79:
            row = row[:px + 3] + "s" + row[px + 4:]
        rows.append(row)
    return rows


def make_observation(turn=1, px=40, py=12, energy=1000, hp=14, frame=1):
    return {
        "vitals": {
            "hp": hp,
            "max_hp": 14,
            "x": px,
            "y": py,
            "zone": "JoppaWorld.11.22.1.1.10",
            "turn": turn,
            "energy": energy,
        },
        "threats": [
            {
                "id": "e1",
                "name": "snapjaw scavenger",
                "wound": "Fine",
                "x": px + 3,
                "y": py,
                "hostile": True,
            }
        ],
        "digest": [f"&yMessage {i}: the watervine rustles. — ░" for i in range(12)],
        "map": make_map(px, py),
        "map_frame": frame,
    }


def make_telemetry(cta=1, end_player_turns=0, player_turn_entries=0):
    return {
        "cta": cta,
        "end_player_turns": end_player_turns,
        "player_turn_entries": player_turn_entries,
        "game_queue": [
            {
                "task_id": None,
                "type": "XRL.Core.XRLCore",
                "method": "<RenderBase>b__0",
                "classification": "engine_task",
            }
        ],
        "ui_tasks": 0,
        "unknown_tasks": 0,
    }


def _dump(message):
    return json.dumps(message, ensure_ascii=False, separators=(", ", ": "))


def request_frame(seq, run_id=RUN_ID, observation=None, telemetry=None, **obs_kw):
    return _dump({
        "kind": "request",
        "run_id": run_id,
        "seq": seq,
        "observation": observation if observation is not None else make_observation(**obs_kw),
        "telemetry": telemetry if telemetry is not None else make_telemetry(cta=seq),
    })


def result_frame(seq, action, run_id=RUN_ID, executed=True, reason="ok", observation=None,
                 telemetry=None, energy_before=1000, energy_after=0, turns_elapsed=1, steps=1,
                 **obs_kw):
    return _dump({
        "kind": "result",
        "run_id": run_id,
        "seq": seq,
        "action": action,
        "executed": executed,
        "reason": reason,
        "observation": observation if observation is not None else make_observation(**obs_kw),
        "telemetry": telemetry if telemetry is not None else make_telemetry(cta=seq + 1),
        "energy_before": energy_before,
        "energy_after": energy_after,
        "turns_elapsed": turns_elapsed,
        "steps": steps,
    })


def heartbeat_frame(seq, run_id=RUN_ID):
    return _dump({"kind": "heartbeat", "run_id": run_id, "seq": seq})


RECOVERY_ID = "6a0c9e2d-4b7f-4d1a-9e3c-8f2b5d7a1c04"
OTHER_RECOVERY_ID = "d91f4b2e-7c3a-4e8b-a5d6-1f0e9c8b7a63"
SAVE_SHA256 = "0123456789abcdef" * 4
SAVE_FILES = {"checkpoint_reload": "Checkpoint", "save_reload": "Primary"}


def recovery_frame(seq, recovery_id=RECOVERY_ID, run_id=RUN_ID, reason="checkpoint_reload",
                   save_file=None, game_id="Roleplay-7f3a", save_sha256=SAVE_SHA256,
                   turn_before=120, loaded_turn=100, lost_turns=None, **extra):
    """A save/checkpoint reload that interrupted request ``seq`` (C#-style spacing)."""
    message = {
        "kind": "recovery",
        "run_id": run_id,
        "seq": seq,
        "recovery_id": recovery_id,
        "reason": reason,
        "game_id": game_id,
        "save_file": save_file if save_file is not None else SAVE_FILES.get(reason, "Checkpoint"),
        "save_sha256": save_sha256,
        "turn_before": turn_before,
        "loaded_turn": loaded_turn,
        "lost_turns": (lost_turns if lost_turns is not None
                       else max(0, turn_before - loaded_turn)),
    }
    message.update(extra)
    return _dump(message)


def game_fault_frame(seq, reason="player died with no checkpoint to reload", run_id=RUN_ID):
    return _dump({"kind": "game_fault", "run_id": run_id, "seq": seq, "reason": reason})


def suspended_frame(seq, reason="game_not_running", run_id=RUN_ID, **extra):
    """The controlled game stopped running while request ``seq`` was open (C#-style spacing)."""
    message = {"kind": "suspended", "run_id": run_id, "seq": seq, "reason": reason}
    message.update(extra)
    return _dump(message)


def contains_key(value, key):
    """Recursively report whether a JSON-like value contains a dict key."""
    if isinstance(value, dict):
        return key in value or any(contains_key(v, key) for v in value.values())
    if isinstance(value, list):
        return any(contains_key(v, key) for v in value)
    return False


def new_uuid():
    return str(uuid.uuid4())
