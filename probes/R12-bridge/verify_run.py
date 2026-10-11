"""Recompute R1/R2 acceptance from both sides' raw logs; fail if evidence is missing."""

import argparse
import json
import math
from pathlib import Path


def verify(player_log, server_log, additional_player_logs=()):
    events = []
    for path in (player_log, *additional_player_logs):
        lines = path.read_text().splitlines()
        # Each process has its own startup baseline. Do not concatenate startup
        # exceptions from a later process into an earlier process's probe window.
        started = False
        for line in lines:
            event = json.loads(line.split("[R12] ", 1)[1]) if "[R12] " in line else None
            if event:
                events.append(event)
                started |= event["kind"] in ("r1_begin", "r2_begin")
                # The deliberate disconnect is recorded with its caught exception
                # type. Its successful recovery is checked against both peers below.
                if event["kind"] == "r2_reconnect":
                    continue
            if started:
                assert not any(marker in line for marker in ("Exception", "ERROR", "Error:")), \
                    f"Probe runtime exception in {path}: {line}"
    failures = [event for event in events if event["kind"].endswith("error")]
    assert not failures, failures
    runs = []
    samples = []
    for event in events:
        if event["kind"] == "r1_begin":
            samples = []
        elif event["kind"] == "r1_sample":
            samples.append(event)
        elif event["kind"] == "r1_result":
            runs.append((event, samples))
    # A failed OS focus transition invalidates that experimental condition. Keep
    # these attempts in the report, but require a full correctly focused rerun.
    invalid = [r for r, _ in runs if r["focusMismatches"] > 0]
    valid = [(r, s) for r, s in runs if r["focusMismatches"] == 0]
    results = [r for r, _ in valid]
    assert {(r["requestedSeconds"], r["focus"]) for r in results} == {
        (60, "focused"), (60, "unfocused"), (600, "focused"), (600, "unfocused")
    }, "missing R1 matrix cells"
    assert len(results) == 4, "expected one run per matrix cell"
    for result, samples in valid:
        assert result["pass"] and result["actions"] == 1 and result["endPlayerTurns"] == 0, result
        assert result["elapsedMs"] >= result["requestedSeconds"] * 1000, result
        assert result["turnEnd"] > result["turnStart"], result
        # UseEnergy can adjust PassTurn's nominal 1000 through game events.
        assert result["energyAfter"] < 1000 <= result["energyStart"], result
        assert len(samples) >= result["requestedSeconds"] - 1, result
        assert all(not e.get("uiTimeout") and e["uiMs"] < 1000 for e in samples), result
        # Nominally one pulse per second: allow scheduling jitter, but reject
        # blind intervals later hidden by a burst of catch-up samples.
        timestamps = [0, *(e["elapsedMs"] for e in samples), result["elapsedMs"]]
        assert all(0 < later - earlier < 2000
                   for earlier, later in zip(timestamps, timestamps[1:])), "R1 sample coverage"
        assert all(e["actualFocused"] == (result["focus"] == "focused")
                   for e in samples if e["elapsedMs"] >= 3000), result
    rounds = [event for event in events if event["kind"] == "r2_roundtrip"]
    assert [e["seq"] for e in rounds] == list(range(1, 1001)), "missing/duplicate/out-of-order roundtrips"
    p95 = sorted(e["rttMs"] for e in rounds)[math.ceil(len(rounds) * .95) - 1]
    assert p95 < 5, p95
    r2 = [event for event in events if event["kind"] == "r2_result"]
    assert len(r2) == 1 and r2[0]["pass"] and r2[0]["replayed501"], r2
    server = [json.loads(line) for line in server_log.read_text().splitlines()]
    observations = [e for e in server if e["kind"] == "observation"]
    assert [e["seq"] for e in observations] == list(range(1, 502)) + list(range(501, 1001))
    replay = [e for e in observations if e["seq"] == 501]
    assert replay[0]["sha256"] == replay[1]["sha256"], "replayed request changed"
    assert replay[0]["connection"] != replay[1]["connection"], "not a reconnection"
    assert any(e["kind"] == "server_result" and e["passed"] for e in server), "server did not complete"
    return {"r1": results, "invalid_focus_attempts": invalid, "r2": r2[0],
            "verified_p95_ms": p95, "pending_request_identical": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("player_log", type=Path)
    parser.add_argument("server_log", type=Path)
    parser.add_argument("--additional-player-log", action="append", type=Path, default=[])
    args = parser.parse_args()
    print(json.dumps(verify(args.player_log, args.server_log, args.additional_player_log),
                     ensure_ascii=False, indent=2))
