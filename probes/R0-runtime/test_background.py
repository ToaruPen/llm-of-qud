"""Offline evidence acceptance must fail closed without changing its inputs."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_background.py")
RUN = "69863fa7-3cb3-4db5-9efe-fdd6856b61c9"
PREVIOUS_RUN = "caff0ee2-a367-45ea-8b6e-d37ce73a39a9"
GAME = "4ebacdc3-96dd-4bb7-aa92-37b5a115ba28"


class BackgroundEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.paths = {name: self.root / filename for name, filename in {
            "start": "start.json", "launch-report": "launch-report.json",
            "desktop-observation": "desktop-observation.json",
            "player-log": "Player.log", "saved-game": "Primary.sav.gz",
        }.items()}
        launch_dir = self.root / "launch" / "20260927T065654.409439Z-38407-steam"
        launch_dir.mkdir(parents=True)
        for name in ("launch-report", "player-log"):
            self.paths[name] = launch_dir / self.paths[name].name
        self.start = {"run_id": RUN, "game_id": GAME, "save_turn": 9,
                      "save_sha256": hashlib.sha256(b"initial save").hexdigest()}
        self.saved_hash = hashlib.sha256(b"saved after play").hexdigest()
        profile = self.root / "profile"
        self.launch = {
            "preflight": {"ok": True}, "run_dir": str(launch_dir),
            "command": ["/game/CoQ.app/Contents/MacOS/CoQ", "-savepath", str(profile),
                        "-sharedpath", str(profile / "Local"), "-syncedpath", str(profile / "Synced"),
                        "-logFile", str(self.paths["player-log"]), "-batchmode"],
            "environment": {"SteamAppId": "333640", "SteamGameId": "333640"},
            "steam_mode": "steam", "launch_mode": "batchmode", "pid": 38408, "exit_code": 0,
        }
        self.desktop = {"pid": 38408, "samples": 1257, "exit_observed": True,
                        "activation_events": 0, "active_samples": 0,
                        "max_onscreen_windows": 0, "window_query_failures": 0}
        self.events = [
            {"kind": "background_loaded", "run_id": RUN, "game_id": GAME, "loaded_turn": 9},
            {"kind": "background_saved", "run_id": RUN, "game_id": GAME,
             "seq": 7, "turn": 15, "save_sha256": self.saved_hash},
            {"kind": "background_quit", "run_id": RUN, "seq": 7},
        ]
        self.paths["saved-game"].write_bytes(b"saved after play")

    def write_log(self, path, events):
        path.write_text("Ordinary Unity log line\n" + "".join(
            "INFO - [LLM] " + json.dumps(event) + "\n" for event in events))

    def write_evidence(self):
        for name, data in (("start", self.start), ("launch-report", self.launch),
                           ("desktop-observation", self.desktop)):
            self.paths[name].write_text(json.dumps(data))
        self.write_log(self.paths["player-log"], self.events)

    def run_verifier(self, *, write=True, previous=None):
        if write:
            self.write_evidence()
        args = [sys.executable, str(SCRIPT)]
        for name, path in self.paths.items():
            args.extend(["--" + name, str(path)])
        if previous:
            args.extend(["--previous-player-log", str(previous)])
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def assert_accepts(self, *, previous=None):
        result = self.run_verifier(previous=previous)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertIs(report["ok"], True)
        self.assertEqual(report["run_id"], RUN)
        self.assertEqual(report["saved_sha256"], self.saved_hash)
        return report

    def assert_refuses(self, *, write=True, previous=None):
        result = self.run_verifier(write=write, previous=previous)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout, result.stderr)
        report = json.loads(result.stdout)
        self.assertIs(report["ok"], False)
        self.assertTrue(report["error"])

    def test_accepts_changed_turn_save_without_equating_actions_and_turns(self):
        self.events.insert(1, {"kind": "request", "run_id": RUN, "seq": 1, "turn": 10})
        report = self.assert_accepts()
        self.assertEqual(report["loaded_turn"], 9)
        self.assertEqual(report["saved_turn"], 15)

    def test_accepts_same_turn_changed_hash_and_does_not_modify_inputs(self):
        self.events[1]["turn"] = 9
        self.write_evidence()
        before = {path: path.read_bytes() for path in self.paths.values()}
        result = self.run_verifier(write=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in self.paths.values()})

    def test_accepts_launch_report_and_log_after_archive_directory_rename(self):
        self.write_evidence()
        archive = self.root / "renamed-archive"
        self.paths["player-log"].parent.rename(archive)
        for name in ("launch-report", "player-log"):
            self.paths[name] = archive / self.paths[name].name
        result = self.run_verifier(write=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIs(json.loads(result.stdout)["ok"], True)

    def test_refuses_launch_report_and_log_selected_across_run_directories(self):
        other = self.root / "another-run"
        other.mkdir()
        original = self.paths.copy()
        for name in ("launch-report", "player-log"):
            with self.subTest(moved=name):
                self.paths = original.copy()
                self.paths[name] = other / original[name].name
                self.assert_refuses()

    def test_refuses_missing_duplicate_or_malformed_logfile_argument(self):
        original = copy.deepcopy(self.launch)
        command = original["command"]
        index = command.index("-logFile")
        invalid_commands = [command[:index] + command[index + 2:],
                            command + ["-logFile", str(self.paths["player-log"])],
                            command[:index] + ["-batchmode", "-logFile"]]
        for value in (None, 1, "", "Player.log", "-batchmode", "/", "/other/Player.log",
                      str(self.paths["player-log"].with_name("different.log"))):
            invalid_commands.append(command[:index + 1] + [value] + command[index + 2:])
        for invalid in invalid_commands:
            with self.subTest(command=invalid):
                self.launch = {**original, "command": invalid}
                self.assert_refuses()

    def test_refuses_missing_or_malformed_historical_run_directory(self):
        original = copy.deepcopy(self.launch)
        for value in (None, 1, "", "relative/run", "/other/run"):
            with self.subTest(run_dir=value):
                self.launch = {**original, "run_dir": value}
                self.assert_refuses()
        self.launch = original.copy()
        del self.launch["run_dir"]
        self.assert_refuses()

    def previous_log(self, *, loaded_turn=3):
        events = copy.deepcopy(self.events)
        for event in events:
            event["run_id"] = PREVIOUS_RUN
        events[0]["loaded_turn"] = loaded_turn
        events[1].update(turn=9, save_sha256=self.start["save_sha256"])
        path = self.root / "previous-Player.log"
        self.write_log(path, events)
        return path, events

    def test_accepts_reload_after_changed_turn_and_same_turn_prior_saves(self):
        for prior_turn in (3, 9):
            with self.subTest(prior_turn=prior_turn):
                path, _ = self.previous_log(loaded_turn=prior_turn)
                report = self.assert_accepts(previous=path)
                self.assertEqual(report["previous_run_id"], PREVIOUS_RUN)

    def test_uses_last_completed_prior_lifecycle(self):
        path, last = self.previous_log()
        older = copy.deepcopy(last)
        for event in older:
            event["run_id"] = "11111111-2222-3333-4444-555555555555"
        older[1].update(turn=4, save_sha256="a" * 64)
        self.write_log(path, older + last)
        self.assert_accepts(previous=path)

    def test_refuses_mismatched_previous_identity_turn_hash_or_run(self):
        for field, value in (("game_id", PREVIOUS_RUN), ("turn", 8),
                             ("save_sha256", "b" * 64), ("run_id", RUN)):
            with self.subTest(field=field):
                path, events = self.previous_log()
                if field in ("run_id", "game_id"):
                    for event in events:
                        if field in event:
                            event[field] = value
                else:
                    events[1][field] = value
                self.write_log(path, events)
                self.assert_refuses(previous=path)

    def test_refuses_incomplete_or_unordered_previous_lifecycle(self):
        path, events = self.previous_log()
        for invalid in (events[:-1], events[1:], list(reversed(events)),
                        events + [events[0]], events + [events[1], events[2]]):
            with self.subTest(events=invalid):
                self.write_log(path, invalid)
                self.assert_refuses(previous=path)

    def test_refuses_missing_duplicate_unordered_or_foreign_lifecycle(self):
        original = copy.deepcopy(self.events)
        foreign = copy.deepcopy(original)
        for event in foreign:
            event["run_id"] = PREVIOUS_RUN
        for invalid in (original[:-1], original[1:], list(reversed(original)),
                        original + [original[1]], original + foreign):
            with self.subTest(events=invalid):
                self.events = invalid
                self.assert_refuses()

    def test_refuses_lifecycle_identity_and_sequence_mismatches(self):
        original = copy.deepcopy(self.events)
        mutations = ((0, "run_id", PREVIOUS_RUN), (0, "game_id", PREVIOUS_RUN),
                     (0, "loaded_turn", 10), (0, "loaded_turn", True),
                     (1, "run_id", PREVIOUS_RUN), (1, "game_id", PREVIOUS_RUN),
                     (1, "turn", None), (1, "seq", True), (2, "run_id", PREVIOUS_RUN),
                     (2, "seq", 8), (2, "seq", None), (2, "game_id", PREVIOUS_RUN))
        for index, field, value in mutations:
            with self.subTest(index=index, field=field, value=value):
                self.events = copy.deepcopy(original)
                self.events[index][field] = value
                self.assert_refuses()

    def test_refuses_background_errors_and_game_faults_anywhere(self):
        original = copy.deepcopy(self.events)
        for kind in ("background_error", "game_fault"):
            with self.subTest(kind=kind):
                self.events = original + [{"kind": kind, "error": "failed"}]
                self.assert_refuses()

    def test_refuses_missing_or_invalid_start_fields(self):
        original = self.start.copy()
        mutations = (("run_id", "not-a-uuid"), ("game_id", None),
                     ("save_turn", True), ("save_turn", -1), ("save_turn", 9.0),
                     ("save_sha256", "x" * 64), ("save_sha256", "A" * 64))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self.start = {**original, field: value}
                self.assert_refuses()
        for field in original:
            with self.subTest(missing=field):
                self.start = original.copy()
                del self.start[field]
                self.assert_refuses()

    def test_refuses_non_batch_launch_invalid_pid_and_nonzero_exit(self):
        original = self.launch.copy()
        command = original["command"]
        for field, value in (("launch_mode", "windowed"),
                             ("command", [arg for arg in command if arg != "-batchmode"]),
                             ("command", command + ["-batchmode"]),
                             ("command", "CoQ -batchmode"), ("pid", 0), ("pid", True),
                             ("exit_code", 1), ("exit_code", False), ("exit_code", None)):
            with self.subTest(field=field, value=value):
                self.launch = {**original, field: value}
                self.assert_refuses()

    def test_refuses_missing_null_boolean_or_nonzero_observation_counters(self):
        original = self.desktop.copy()
        for field in ("activation_events", "active_samples", "max_onscreen_windows",
                      "window_query_failures"):
            for value in (None, False, 0.0, 1, -1, "0"):
                with self.subTest(field=field, value=value):
                    self.desktop = {**original, field: value}
                    self.assert_refuses()
            with self.subTest(missing=field):
                self.desktop = original.copy()
                del self.desktop[field]
                self.assert_refuses()

    def test_refuses_missing_observation_exit_samples_and_matching_pid(self):
        original = self.desktop.copy()
        for field, value in (("samples", 0), ("samples", True), ("samples", None),
                             ("pid", 38409), ("pid", None),
                             ("exit_observed", False), ("exit_observed", 1)):
            with self.subTest(field=field, value=value):
                self.desktop = {**original, field: value}
                self.assert_refuses()

    def test_refuses_save_hash_mismatch_unchanged_save_and_missing_file(self):
        self.paths["saved-game"].write_bytes(b"wrong save")
        self.assert_refuses()
        self.paths["saved-game"].write_bytes(b"saved after play")
        self.start["save_sha256"] = self.saved_hash
        self.assert_refuses()
        self.paths["saved-game"].unlink()
        self.assert_refuses()

    def test_refuses_malformed_json_documents_and_event_records(self):
        for name in ("start", "launch-report", "desktop-observation"):
            for raw in ("{", "[]", "null", '{"pid": 1, "pid": 2}'):
                with self.subTest(name=name, raw=raw):
                    self.write_evidence()
                    self.paths[name].write_text(raw)
                    self.assert_refuses(write=False)
        for raw in ("{", "[]", "null", '{}', '{"kind":"unrelated","x":NaN}',
                    '{"kind":"background_error","kind":"unrelated"}'):
            with self.subTest(event=raw):
                self.write_evidence()
                with self.paths["player-log"].open("a") as stream:
                    stream.write("INFO - [LLM] " + raw + "\n")
                self.assert_refuses(write=False)


if __name__ == "__main__":
    unittest.main()
