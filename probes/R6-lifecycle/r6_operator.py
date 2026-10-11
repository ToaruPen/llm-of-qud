"""Local R6 fixture control and an attested crash of an opted-in disposable game.

Never exposed through MCP. Does not launch the game, choose a save, or arm gameplay.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

import r6_evidence as ev

FIXTURES = {"status", "save", "autosave", "save_quit", "reload", "death"}


def utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def optin(profile):
    profile = Path(profile).resolve()
    config = ev.loads((profile / ev.OPTIN_FILE).read_text())
    if (config.get("v") != 1 or config.get("development") is not True
            or config.get("disposable") is not True or config.get("savepath") != str(profile)):
        raise ValueError("A disposable development opt-in for this exact profile is required")
    nonce = config.get("nonce", "")
    if not isinstance(nonce, str) or not 32 <= len(nonce) <= 64 or set(nonce) - set("0123456789abcdef-"):
        raise ValueError("Invalid profile nonce")
    return profile, config


def fixture(profile, kind):
    profile, config = optin(profile)
    if kind not in FIXTURES:
        raise ValueError("Unknown R6 fixture")
    payload = {"command": "probe_lifecycle", "nonce": config["nonce"],
               "fixture_id": str(uuid.uuid4()), "fixture": kind, "death_answer": "external"}
    target = profile / "llm-control.json"
    temporary = profile / (".r6-control-" + payload["fixture_id"])
    try:
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic publication without replacing another operator's pending command.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"kind": "fixture", "utc": utc(), **{k: v for k, v in payload.items() if k != "nonce"}}


def process_command(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                            capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def verify_process(profile, init):
    pid, argv = init.get("pid"), init.get("argv")
    if type(pid) is not int or pid <= 1 or not isinstance(argv, list):
        raise ValueError("Missing process identity")
    if argv.count("-savepath") != 1 or argv[argv.index("-savepath") + 1] != str(profile):
        raise ValueError("Process profile differs from opt-in")
    if process_command(pid) != " ".join(argv):
        raise ValueError("Live process argv differs from probe evidence")
    return pid


def check_heartbeat(record):
    age = (datetime.now(timezone.utc) - ev.parse_utc(record["utc"])).total_seconds()
    if not -2 <= age <= 5:
        raise ValueError("Probe heartbeat is not fresh")


def crash(profile, evidence, receipt_path):
    profile, config = optin(profile)
    evidence = Path(evidence).resolve()
    if evidence.parent != profile / ev.EVIDENCE_DIR:
        raise ValueError("Evidence must belong to the opted-in profile")
    session = ev.load_session(evidence)
    if session.init.get("optin_nonce") != config["nonce"]:
        raise ValueError("Evidence nonce differs from opt-in")
    heartbeat = next((r for r in reversed(session.records) if r["kind"] == "heartbeat"), None)
    if heartbeat is None:
        raise ValueError("No probe heartbeat")
    check_heartbeat(heartbeat)
    game = ev.last_game(session.records)
    if game is None:
        raise ValueError("No loaded game in evidence")
    game_id = str(uuid.UUID(game["game_id"]))
    saves = {}
    for name in ("Primary", "Checkpoint"):
        path = profile / "Synced/Saves" / game_id / (name + ".sav.gz")
        if path.exists():
            saves[name] = {"sha256": ev.sha256_file(path), "size": path.stat().st_size}
    if "Primary" not in saves:
        raise ValueError("No Primary save to recover")
    # Reserve the receipt before mutating the process; never overwrite prior evidence.
    with Path(receipt_path).open("x") as output:
        os.chmod(receipt_path, 0o600)
        pid = verify_process(profile, session.init)
        killed = utc()
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while process_command(pid) is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        gone = process_command(pid) is None
        final = ev.load_session(evidence)
        last = ev.last_game(final.records)
        receipt = {"kind": "crash", "session": session.session, "pid": pid,
                   "kill_utc": killed, "signal": "SIGKILL", "dry_run": False,
                   "verified": {"profile": True, "argv": True, "heartbeat": True},
                   "process_gone": gone, "last_probe_turn": last["turns"], "saves": saves}
        json.dump(receipt, output, indent=2)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    if not gone:
        raise RuntimeError("Process exit unconfirmed; inspect receipt")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    control = sub.add_parser("fixture")
    control.add_argument("kind", choices=sorted(FIXTURES))
    control.add_argument("--receipt", required=True, type=Path)
    kill = sub.add_parser("crash")
    kill.add_argument("--evidence", required=True, type=Path)
    kill.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "fixture":
        with args.receipt.open("x") as output:
            os.chmod(args.receipt, 0o600)
            result = fixture(args.profile, args.kind)
            json.dump(result, output, indent=2); output.write("\n")
    else:
        result = crash(args.profile, args.evidence, args.receipt)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
