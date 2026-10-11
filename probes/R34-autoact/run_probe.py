"""Run one isolated live probe; focus switching was explicitly authorized.

No keyboard, mouse, or in-game responses are sent by this runner.
Requires an already loaded character and the authenticated local OBS endpoint.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time
import shutil

from obs_probe import Obs


GAME = "/Users/sankenbisha/Games/CavesOfQud-probe-2.0.211.56-build25520692/CoQ.app"


def activate(app):
    # Values come only from constants, never from log text or the command file.
    subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'], check=True)


def records(path, run_id):
    rows = []
    for line in path.read_text().splitlines():
        if "[R34] " in line:
            try:
                row = json.loads(line.split("[R34] ", 1)[1])
            except json.JSONDecodeError:
                continue  # The final log line may still be in flight.
            if row.get("id") == run_id:
                rows.append(row)
    return rows


class LogTail:
    def __init__(self, path):
        self.path = path
        stat = path.stat()
        self.identity = stat.st_dev, stat.st_ino
        self.position = stat.st_size
        self.pending = b""

    def poll(self):
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.position:
            raise RuntimeError("Player.log was replaced or truncated")
        with self.path.open("rb") as stream:
            stream.seek(self.position)
            data = stream.read()
            self.position = stream.tell()
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()
        return [json.loads(line.split(b"[R34] ", 1)[1]) for line in lines if b"[R34] " in line]


async def run(args):
    output = Path(__file__).parent / "results" / args.id
    output.mkdir(exist_ok=False)
    control = args.profile / "r34-command.json"
    if control.exists() or records(args.log, args.id):
        raise RuntimeError("Pending control file or duplicate run ID")
    receipt = {"id": args.id, "playerLog": str(args.log.resolve()),
               "mode": args.mode, "seconds": args.seconds, "focus": args.focus,
               "dropFirstPickerPush": args.drop_first_picker_push,
               "backgroundApp": args.background_app,
               "runnerGameInputs": [], "externalHumanInputsVerified": False,
               "sourceHashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (Path(__file__).parent / "mod").glob("*") if p.is_file()}}
    for p in (Path(__file__).parent / "mod").glob("*"):
        if p.is_file():
            (output / p.name).write_bytes(p.read_bytes())
    events = (output / "runner.jsonl").open("w")

    def event(kind, **fields):
        events.write(json.dumps({"kind": kind, "monotonic": time.monotonic(), **fields}) + "\n")
        events.flush()

    async with Obs() as obs:
        if (await obs.request("GetRecordStatus"))["outputActive"]:
            raise RuntimeError("Another OBS recording is active")
        windows = await obs.request("GetInputPropertiesListPropertyItems",
                                    inputName="Qud probe window", propertyName="window")
        exact = [r for r in windows["propertyItems"] if r["itemName"] == "[CavesOfQud] CavesOfQud"]
        if len(exact) != 1:
            raise RuntimeError("Expected exactly one live game window")
        await obs.request("SetInputSettings", inputName="Qud probe window", overlay=True,
                          inputSettings={"type": 1, "window": exact[0]["itemValue"], "show_cursor": False})
        receipt["captureWindow"] = exact[0]
        activate(GAME)
        event("focus", app=GAME)
        await asyncio.sleep(1)
        await obs.request("StartRecord")
        event("record_started")
        try:
            tail = LogTail(args.log)
            request = {"id": args.id, "mode": args.mode, "seconds": args.seconds,
                       "turns": 500, "focus": args.focus,
                       "dropFirstPickerPush": args.drop_first_picker_push}
            pending = control.with_suffix(".tmp")
            pending.write_text(json.dumps(request))
            pending.replace(control)
            event("control", request=request)
            deadline = time.monotonic() + (args.seconds + 20 if args.mode in {"r3", "hover"} else 180)
            background = False
            last_toggle = last_stats = 0
            started = False
            result = None
            last_progress = 0
            while time.monotonic() < deadline:
                for row in tail.poll():
                    if row.get("id") != args.id:
                        continue
                    if row["kind"] == "begin":
                        started = True
                    elif row["kind"] == "result":
                        result = row
                    elif row["kind"] == "heartbeat" and row["elapsedMs"] - last_progress >= 45000:
                        print(json.dumps(row), flush=True)
                        last_progress = row["elapsedMs"]
                if started and args.focus == "unfocused" and not background:
                    activate(args.background_app)
                    event("focus", app=args.background_app)
                    background = True
                if started and args.mode == "picker" and time.monotonic() - last_toggle >= 0.4:
                    background = not background
                    app = "Finder" if background else GAME
                    activate(app)
                    event("focus", app=app)
                    last_toggle = time.monotonic()
                if time.monotonic() - last_stats >= 1:
                    event("obs_stats", stats=await obs.request("GetStats"))
                    last_stats = time.monotonic()
                    if shutil.disk_usage(output).free < 10 * 1024**3:
                        raise RuntimeError("Less than 10 GiB free; stopping this recording")
                if result:
                    receipt["result"] = result
                    print(json.dumps(result), flush=True)
                    break
                await asyncio.sleep(0.02)
            else:
                control.write_text(json.dumps({"mode": "stop"}))
                receipt["timeout"] = True
                raise TimeoutError("Probe did not complete before its wall deadline")
        except BaseException as exc:
            control.write_text(json.dumps({"mode": "stop"}))
            receipt["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            stop_error = None
            try:
                receipt["recording"] = await obs.request("StopRecord")
                event("record_stopped", **receipt["recording"])
            except Exception as exc:
                stop_error = exc
                receipt["recordingStopError"] = f"{type(exc).__name__}: {exc}"
                event("record_stop_unconfirmed", error=receipt["recordingStopError"])
            finally:
                (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                events.close()
                print(str(output / "receipt.json"), flush=True)
            if stop_error is not None:
                raise RuntimeError("OBS recording stop is unconfirmed; inspect OBS before recovery") from stop_error


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--mode", choices=["r3", "r4", "picker", "hover"], required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--focus", choices=["focused", "unfocused", "mixed"], default="focused")
    parser.add_argument("--drop-first-picker-push", action="store_true",
                        help="Picker-only simulated loss before the first PushKey of each picker")
    parser.add_argument("--background-app", choices=["Finder", "OBS"], default="Finder",
                        help="App to activate after an unfocused run starts; prepare and verify any covering window separately")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=Path.home() / "Library/Application Support/Freehold Games/CavesOfQud-r34")
    args = parser.parse_args()
    if not args.id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.id):
        parser.error("id must be a simple filesystem-safe name")
    if args.drop_first_picker_push and args.mode != "picker":
        parser.error("--drop-first-picker-push requires --mode picker")
    if args.mode == "hover" and not 10 <= args.seconds <= 60:
        parser.error("hover requires --seconds between 10 and 60")
    asyncio.run(run(args))
