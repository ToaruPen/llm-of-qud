"""The launcher must reject changed game content and unapproved profile state."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring


SCRIPT = Path(__file__).with_name("runtime.py")
EXPECTED_OPTIONS = {
    "OptionAutoexploreChests": "No",
    "OptionAbilityCooldownWarningAsMessage": "Yes",
    "OptionShowScavengeItemAsMessage": "Yes",
    "OptionPopupJournalNote": "No",
    "OptionDisplayHPWarning": "No Warning",
    "OptionDisableTextAnimationEffects": "Yes",
    "OptionMusicBackground": "Yes",
    "OptionAllowCSMods": "Yes",
    "OptionModernUI": "Yes",
    "OptionSessionBackups": "None",
    "OptionAutosaveInterval": "5",
    "OptionEnableMods": "Yes",
}


class RuntimeCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.game = root / "CoQ.app"
        self.profile = root / "profile"
        self.workshop = root / "workshop"
        self.workshop.mkdir()
        managed = self.game / "Contents/Resources/Data/Managed"
        base = self.game / "Contents/Resources/Data/StreamingAssets/Base"
        managed.mkdir(parents=True)
        base.mkdir(parents=True)
        executable = self.game / "Contents/MacOS/CoQ"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fake launcher")
        (managed / "Assembly-CSharp.dll").write_bytes(b"pinned assembly")
        (managed / "Newtonsoft.Json.dll").write_bytes(b"pinned newtonsoft")
        options = Element("options")
        for key, value in EXPECTED_OPTIONS.items():
            SubElement(options, "option", ID=key, Default=value)
        (base / "Options.xml").write_bytes(tostring(options))
        (base / "World.xml").write_bytes(b"<world/>")
        self.baseline = root / "baseline.json"
        files = {}
        for directory in (managed, base):
            for item in directory.rglob("*"):
                if item.is_file():
                    files[item.relative_to(self.game).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
        self.baseline.write_text(json.dumps({
            "game_path": str(self.game),
            "assembly_version_expected": "2.0.211.56",
            "steam_buildid": "25520692",
            "files": files,
        }))
        local = self.profile / "Local"
        local.mkdir(parents=True)
        (self.profile / "Synced").mkdir()
        mod = self.profile / "Mods" / "ProbeR0"
        mod.mkdir(parents=True)
        (mod / "manifest.json").write_text('{"ID":"ProbeR0"}')
        (local / "ModSettings.json").write_text(json.dumps({"ProbeR0": {"Enabled": True}}))
        (local / "PlayerOptions.json").write_text("{}")
        self.player_log = root / "Player.log"
        self.build_log = root / "build_log.txt"

    def write_runtime_logs(self, *, mod_ids=None, options=None, compile_success=True):
        mod_ids = mod_ids or ["ProbeR0"]
        options = options or EXPECTED_OPTIONS
        init = {"kind": "init", "assemblyVersion": "2.0.211.56",
                "activeModIds": mod_ids, "options": options,
                "optionsMatch": options == EXPECTED_OPTIONS}
        self.player_log.write_text("INFO - [R0] " + json.dumps(init) + "\n")
        compile_line = "Success :)" if compile_success else "Errors compiling"
        self.build_log.write_text(
            "[time] BuildLogger initialized...\n"
            "[time] === PROBER0 ===\n"
            "[time] Compiling 1 file...\n"
            f"[time] {compile_line}\n"
            "[time] Defined symbol: MOD_PROBER0\n"
            "[time] ==== FINAL LOAD ORDER ====\n" +
            "".join(f"[time] {i}: {mod_id}\n" for i, mod_id in enumerate(mod_ids, 1)))

    def verify(self):
        return subprocess.run([
            sys.executable, str(SCRIPT), "verify", "--player-log", str(self.player_log),
            "--build-log", str(self.build_log), "--allow-mod", "ProbeR0",
        ], text=True, capture_output=True, check=False)

    def check(self):
        return subprocess.run([
            sys.executable, str(SCRIPT), "check", "--game", str(self.game),
            "--profile", str(self.profile), "--baseline", str(self.baseline),
            "--expected-buildid", "25520692", "--allow-mod", "ProbeR0",
            "--workshop-dir", str(self.workshop),
        ], text=True, capture_output=True, check=False)

    def test_valid_pinned_runtime_passes(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["active_mod_ids"], ["ProbeR0"])
        self.assertEqual(report["assembly_version"], "2.0.211.56")

    def test_changed_managed_dll_is_rejected(self):
        (self.game / "Contents/Resources/Data/Managed/Assembly-CSharp.dll").write_bytes(b"modified")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)

    def test_missing_managed_dll_is_rejected(self):
        (self.game / "Contents/Resources/Data/Managed/Newtonsoft.Json.dll").unlink()
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing protected file", result.stderr)

    def test_extra_base_file_is_rejected(self):
        path = self.game / "Contents/Resources/Data/StreamingAssets/Base/Injected.xml"
        path.write_text("<injected/>")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extra protected file", result.stderr)

    def test_unapproved_enabled_local_mod_is_rejected(self):
        mod = self.profile / "Local/Mods/Unexpected"
        mod.mkdir(parents=True)
        (mod / "manifest.json").write_text('{"ID":"Unexpected"}')
        settings = self.profile / "Local/ModSettings.json"
        settings.write_text(json.dumps({"ProbeR0": {"Enabled": True},
                                        "Unexpected": {"Enabled": True}}))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unapproved enabled mod", result.stderr)

    def test_new_workshop_mod_defaults_to_enabled_and_is_rejected(self):
        (self.workshop / "999999").mkdir()
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unapproved enabled mod", result.stderr)

    def test_unexpected_option_is_rejected(self):
        (self.profile / "Local/PlayerOptions.json").write_text(
            json.dumps({"OptionMusicBackground": "No"}))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("option mismatch", result.stderr)

    def test_unpinned_build_id_is_rejected(self):
        self.baseline.write_text(self.baseline.read_text().replace("25520692", "99999999"))
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build ID mismatch", result.stderr)

    def test_caller_cannot_redefine_the_pinned_build_id(self):
        self.baseline.write_text(self.baseline.read_text().replace("25520692", "99999999"))
        result = subprocess.run([
            sys.executable, str(SCRIPT), "check", "--game", str(self.game),
            "--profile", str(self.profile), "--baseline", str(self.baseline),
            "--expected-buildid", "99999999", "--allow-mod", "ProbeR0",
            "--workshop-dir", str(self.workshop),
        ], text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pinned build", result.stderr)

    def test_launch_plan_keeps_steam_modes_distinct_without_starting_game(self):
        common = [sys.executable, str(SCRIPT), "launch", "--game", str(self.game),
                  "--profile", str(self.profile), "--baseline", str(self.baseline),
                  "--expected-buildid", "25520692", "--allow-mod", "ProbeR0",
                  "--workshop-dir", str(self.workshop), "--log-dir", str(Path(self.temp.name) / "logs"),
                  "--dry-run"]
        no_steam = subprocess.run(common + ["--steam-mode", "no-steam"],
                                  text=True, capture_output=True, check=False)
        steam = subprocess.run(common + ["--steam-mode", "steam"],
                               text=True, capture_output=True, check=False)
        self.assertEqual(no_steam.returncode, 0, no_steam.stderr)
        self.assertEqual(steam.returncode, 0, steam.stderr)
        no_steam_plan = json.loads(no_steam.stdout)
        steam_plan = json.loads(steam.stdout)
        self.assertIn("STEAM:NO", no_steam_plan["command"])
        self.assertNotIn("SteamAppId", no_steam_plan["environment"])
        self.assertNotIn("STEAM:NO", steam_plan["command"])
        self.assertEqual(steam_plan["environment"]["SteamAppId"], "333640")
        self.assertEqual(no_steam_plan["launch_mode"], "windowed")
        self.assertEqual(steam_plan["launch_mode"], "windowed")
        self.assertNotIn("-batchmode", no_steam_plan["command"])
        self.assertNotIn("-batchmode", steam_plan["command"])
        self.assertFalse((Path(self.temp.name) / "logs").exists())

    def test_batchmode_launch_plan_preserves_existing_modes_without_starting_game(self):
        common = [sys.executable, str(SCRIPT), "launch", "--game", str(self.game),
                  "--profile", str(self.profile), "--baseline", str(self.baseline),
                  "--expected-buildid", "25520692", "--allow-mod", "ProbeR0",
                  "--workshop-dir", str(self.workshop), "--log-dir", str(Path(self.temp.name) / "logs"),
                  "--dry-run", "--batchmode"]
        for steam_mode in ("steam", "no-steam"):
            with self.subTest(steam_mode=steam_mode):
                result = subprocess.run(common + ["--steam-mode", steam_mode],
                                        text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertEqual(plan["launch_mode"], "batchmode")
                self.assertEqual(plan["command"].count("-batchmode"), 1)
                self.assertNotIn("-nographics", plan["command"])
                self.assertEqual(plan["command"][0], str((self.game / "Contents/MacOS/CoQ").resolve()))
                self.assertIn("-logFile", plan["command"])
                if steam_mode == "steam":
                    self.assertEqual(plan["environment"]["SteamAppId"], "333640")
                    self.assertEqual(plan["environment"]["SteamGameId"], "333640")
                    self.assertNotIn("STEAM:NO", plan["command"])
                else:
                    self.assertEqual(plan["environment"], {})
                    self.assertIn("STEAM:NO", plan["command"])
        self.assertFalse((Path(self.temp.name) / "logs").exists())

    def test_batchmode_launch_keeps_process_report_and_sanitizes_no_steam_environment(self):
        executable = self.game / "Contents/MacOS/CoQ"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({'argv': sys.argv, 'SteamAppId': os.environ.get('SteamAppId'), "
            "'SteamGameId': os.environ.get('SteamGameId')}))\n"
            "sys.exit(7)\n")
        executable.chmod(0o755)
        log_dir = Path(self.temp.name) / "logs"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "launch", "--game", str(self.game),
            "--profile", str(self.profile), "--baseline", str(self.baseline),
            "--expected-buildid", "25520692", "--allow-mod", "ProbeR0",
            "--workshop-dir", str(self.workshop), "--log-dir", str(log_dir),
            "--steam-mode", "no-steam", "--batchmode",
        ], text=True, capture_output=True, check=False,
            env={**os.environ, "SteamAppId": "inherited", "SteamGameId": "inherited"})
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["launch_mode"], "batchmode")
        self.assertGreater(plan["pid"], 0)
        self.assertEqual(plan["exit_code"], 7)
        self.assertEqual(json.loads((Path(plan["run_dir"]) / "launch-report.json").read_text()), plan)
        child = json.loads((Path(plan["run_dir"]) / "launcher.log").read_text())
        self.assertIn("-batchmode", child["argv"])
        self.assertIn("STEAM:NO", child["argv"])
        self.assertIsNone(child["SteamAppId"])
        self.assertIsNone(child["SteamGameId"])

    def test_background_entry_always_launches_without_display_in_both_steam_modes(self):
        executable = self.game / "Contents/MacOS/CoQ"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "print(json.dumps(sys.argv))\n")
        executable.chmod(0o755)
        log_dir = Path(self.temp.name) / "logs"
        for mode in ("steam", "no-steam"):
            with self.subTest(mode=mode):
                result = subprocess.run([
                    sys.executable, str(SCRIPT), "launch-background",
                    "--game", str(self.game), "--profile", str(self.profile),
                    "--baseline", str(self.baseline), "--expected-buildid", "25520692",
                    "--allow-mod", "ProbeR0", "--workshop-dir", str(self.workshop),
                    "--log-dir", str(log_dir), "--steam-mode", mode,
                ], text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertEqual(plan["launch_mode"], "batchmode")
                self.assertEqual(plan["exit_code"], 0)
                child = json.loads((Path(plan["run_dir"]) / "launcher.log").read_text())
                self.assertEqual(child.count("-batchmode"), 1)
                self.assertNotIn("-nographics", child)
                self.assertEqual("STEAM:NO" in child, mode == "no-steam")

    def test_background_dry_run_does_not_create_files_or_bypass_preflight(self):
        log_dir = Path(self.temp.name) / "logs"
        command = [
            sys.executable, str(SCRIPT), "launch-background", "--dry-run",
            "--game", str(self.game), "--profile", str(self.profile),
            "--baseline", str(self.baseline), "--expected-buildid", "25520692",
            "--allow-mod", "ProbeR0", "--workshop-dir", str(self.workshop),
            "--log-dir", str(log_dir), "--steam-mode", "no-steam",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["launch_mode"], "batchmode")
        self.assertFalse(log_dir.exists())
        (self.game / "Contents/Resources/Data/Managed/Assembly-CSharp.dll").write_bytes(b"changed")
        refused = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("hash mismatch", refused.stderr)
        self.assertFalse(log_dir.exists())

    def test_runtime_logs_prove_compile_load_and_options(self):
        self.write_runtime_logs()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_runtime_logs_reject_unapproved_loaded_mod(self):
        self.write_runtime_logs(mod_ids=["ProbeR0", "Unexpected"])
        init = {"kind": "init", "assemblyVersion": "2.0.211.56",
                "activeModIds": ["ProbeR0"], "options": EXPECTED_OPTIONS,
                "optionsMatch": True}
        self.player_log.write_text("INFO - [R0] " + json.dumps(init) + "\n")
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("load order", result.stderr)

    def test_runtime_logs_reject_failed_compile(self):
        self.write_runtime_logs(compile_success=False)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compile", result.stderr)

    def test_runtime_logs_reject_options_mismatch(self):
        self.write_runtime_logs(options={**EXPECTED_OPTIONS, "OptionMusicBackground": "No"})
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("option", result.stderr)


if __name__ == "__main__":
    unittest.main()
