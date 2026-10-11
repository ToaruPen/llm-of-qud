"""R0 preflight and isolated CoQ launcher. The pinned manifest is read-only input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


EXPECTED_ASSEMBLY_VERSION = "2.0.211.56"
PINNED_BUILD_ID = "25520692"
APP_ID = "333640"
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
MANAGED = Path("Contents/Resources/Data/Managed")
BASE = Path("Contents/Resources/Data/StreamingAssets/Base")
EMBEDDED_MODS = Path("Contents/Resources/Data/StreamingAssets/Mods")
DLC = Path("Contents/Resources/Data/StreamingAssets/DLC")


class Refused(RuntimeError):
    """A preflight condition is not established."""


def read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Refused(f"cannot read JSON {path}: {exc}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_files(game: Path) -> dict[str, Path]:
    managed = game / MANAGED
    base = game / BASE
    if not managed.is_dir() or not base.is_dir():
        raise Refused("Managed or StreamingAssets/Base directory is missing")
    result: dict[str, Path] = {}
    for path in managed.iterdir():
        if path.suffix.lower() == ".dll":
            result[path.relative_to(game).as_posix()] = path
    for path in base.rglob("*"):
        if path.is_file() or path.is_symlink():
            result[path.relative_to(game).as_posix()] = path
    return result


def check_content(game: Path, manifest: dict) -> int:
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise Refused("baseline has no protected files")
    for relative, digest in expected.items():
        path = Path(relative)
        if (not isinstance(relative, str) or path.is_absolute() or ".." in path.parts
                or not isinstance(digest, str)
                or not (path == MANAGED / path.name and path.suffix.lower() == ".dll"
                        or BASE in path.parents)):
            raise Refused(f"invalid baseline protected path: {relative}")
    if (MANAGED / "Assembly-CSharp.dll").as_posix() not in expected:
        raise Refused("baseline lacks Assembly-CSharp.dll")
    actual = protected_files(game)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        raise Refused(f"missing protected file: {missing[0]}")
    if extra:
        raise Refused(f"extra protected file: {extra[0]}")
    for relative, path in sorted(actual.items()):
        if path.is_symlink() or not path.is_file():
            raise Refused(f"protected file is not a regular file: {relative}")
        if sha256(path) != expected[relative]:
            raise Refused(f"hash mismatch: {relative}")
    return len(actual)


def read_mod_id(directory: Path) -> str:
    if directory.is_symlink() and not directory.exists():
        raise Refused(f"broken mod symlink: {directory}")
    config = directory / "manifest.json"
    manifest = read_json(config) if config.exists() else {}
    if not isinstance(manifest, dict):
        raise Refused(f"mod manifest is not an object: {config}")
    raw_id = manifest.get("ID") or directory.name
    if not isinstance(raw_id, str):
        raise Refused(f"invalid mod ID in {config}")
    # ModInfo.ReadConfigurations applies this exact character filter.
    mod_id = re.sub(r"[^\w ]", "", raw_id)
    if not mod_id:
        raise Refused(f"empty mod ID in {directory}")
    return mod_id


def check_mods(game: Path, profile: Path, workshop: Path, allowed: set[str]) -> tuple[list[str], list[str]]:
    if not allowed:
        raise Refused("mod allowlist is empty")
    settings_path = profile / "Local/ModSettings.json"
    settings = read_json(settings_path)
    if not isinstance(settings, dict):
        raise Refused("ModSettings.json must be an object")
    if not workshop.is_dir():
        raise Refused(f"workshop directory unavailable; cannot discover enabled subscriptions: {workshop}")
    roots = [game / EMBEDDED_MODS, game / DLC,
             game / "Contents/CoQ_Data/StreamingAssets/DLC",
             profile / "Mods", profile / "Local/Mods", workshop]
    discovered: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        if not root.is_dir():
            raise Refused(f"mod source is not a directory: {root}")
        for child in sorted(root.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            mod_id = read_mod_id(child)
            if mod_id in discovered:
                raise Refused(f"duplicate discovered mod ID {mod_id}: {discovered[mod_id]} and {child}")
            discovered[mod_id] = child
    enabled: set[str] = set()
    for mod_id, directory in discovered.items():
        entry = settings.get(mod_id, {})
        if not isinstance(entry, dict) or type(entry.get("Enabled", True)) is not bool:
            raise Refused(f"invalid ModSettings entry for {mod_id}")
        if entry.get("Enabled", True):
            enabled.add(mod_id)
            if mod_id not in allowed:
                raise Refused(f"unapproved enabled mod {mod_id}: {directory}")
    for mod_id, entry in settings.items():
        if not isinstance(entry, dict) or type(entry.get("Enabled", True)) is not bool:
            raise Refused(f"invalid ModSettings entry for {mod_id}")
        if entry.get("Enabled", True) and mod_id not in allowed:
            raise Refused(f"unapproved enabled mod in settings: {mod_id}")
    missing_allowed = allowed - enabled
    if missing_allowed:
        raise Refused(f"allowlisted mod is missing or disabled: {', '.join(sorted(missing_allowed))}")
    return sorted(enabled), sorted(discovered)


def check_options(game: Path, profile: Path, expected: dict[str, str]) -> dict[str, str]:
    try:
        tree = ElementTree.parse(game / BASE / "Options.xml")
    except (OSError, ElementTree.ParseError) as exc:
        raise Refused(f"cannot read Base/Options.xml: {exc}") from exc
    defaults = {item.get("ID"): item.get("Default") for item in tree.iter("option")}
    saved = read_json(profile / "Local/PlayerOptions.json")
    if not isinstance(saved, dict):
        raise Refused("PlayerOptions.json must be an object")
    effective = {}
    for key, wanted in expected.items():
        if key not in defaults:
            raise Refused(f"option absent from pinned Base/Options.xml: {key}")
        value = saved.get(key, defaults[key])
        if value != wanted:
            raise Refused(f"option mismatch: {key} expected {wanted!r}, got {value!r}")
        effective[key] = value
    return effective


def appmanifest_buildid(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise Refused(f"cannot read Steam appmanifest: {exc}") from exc
    app_id = re.search(r'"appid"\s+"(\d+)"', content)
    build_id = re.search(r'"buildid"\s+"(\d+)"', content)
    if not app_id or app_id.group(1) != APP_ID or not build_id:
        raise Refused(f"invalid Steam appmanifest for app {APP_ID}: {path}")
    return build_id.group(1)


def check(args: argparse.Namespace) -> dict:
    game = args.game.expanduser().resolve()
    profile = args.profile.expanduser().resolve()
    baseline_path = args.baseline.expanduser().resolve()
    workshop = args.workshop_dir.expanduser().resolve()
    manifest = read_json(baseline_path)
    if not isinstance(manifest, dict):
        raise Refused("baseline is not an object")
    if game != Path(manifest.get("game_path", "")).expanduser().resolve():
        raise Refused("game path differs from pinned baseline")
    if manifest.get("assembly_version_expected") != EXPECTED_ASSEMBLY_VERSION:
        raise Refused("assembly version label differs from pinned version")
    if args.expected_buildid != PINNED_BUILD_ID:
        raise Refused("requested build ID differs from pinned build")
    if manifest.get("steam_buildid") != args.expected_buildid:
        raise Refused("build ID mismatch between baseline and required build")
    if not profile.is_dir() or not (profile / "Local").is_dir():
        raise Refused(f"isolated profile missing Local directory: {profile}")
    file_count = check_content(game, manifest)
    allowed = set(args.allow_mod)
    enabled, discovered = check_mods(game, profile, workshop, allowed)
    options = check_options(game, profile, EXPECTED_OPTIONS)
    if args.appmanifest:
        external_buildid = appmanifest_buildid(args.appmanifest.expanduser().resolve())
        if external_buildid != args.expected_buildid:
            raise Refused("build ID mismatch in external Steam appmanifest")
        buildid_provenance = "external Steam appmanifest; clone tied by protected-content hashes"
    else:
        buildid_provenance = "baseline label only; build ID is not embedded in the cloned app"
    executable = game / "Contents/MacOS/CoQ"
    if not executable.is_file():
        raise Refused(f"game executable missing: {executable}")
    return {
        "ok": True,
        "game": str(game),
        "profile": str(profile),
        "baseline_sha256": sha256(baseline_path),
        "assembly_version": EXPECTED_ASSEMBLY_VERSION,
        "assembly_version_provenance": "exact Assembly-CSharp.dll hash against pinned baseline; verify actual runtime version in [R0] init log",
        "steam_buildid": args.expected_buildid,
        "buildid_provenance": buildid_provenance,
        "protected_file_count": file_count,
        "active_mod_ids": enabled,
        "discovered_mod_ids": discovered,
        "effective_options": options,
    }


def launch(args: argparse.Namespace, report: dict) -> dict:
    game = args.game.expanduser().resolve()
    profile = args.profile.expanduser().resolve()
    log_dir = args.log_dir.expanduser().resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{os.getpid()}-{args.steam_mode}"
    run_dir = log_dir / run_id
    player_log = run_dir / "Player.log"
    command = [str(game / "Contents/MacOS/CoQ"), "-savepath", str(profile),
               "-sharedpath", str(profile / "Local"), "-syncedpath", str(profile / "Synced"),
               "-logFile", str(player_log)]
    if args.batchmode:
        command.append("-batchmode")
    environment = {}
    if args.steam_mode == "steam":
        environment["SteamAppId"] = APP_ID
        environment["SteamGameId"] = APP_ID
    else:
        command.append("STEAM:NO")
    plan = {"preflight": report, "run_dir": str(run_dir), "command": command,
            "environment": environment, "steam_mode": args.steam_mode,
            "launch_mode": "batchmode" if args.batchmode else "windowed"}
    if args.dry_run:
        return plan
    run_dir.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.pop("SteamAppId", None)
    env.pop("SteamGameId", None)
    env.update(environment)
    build_log = profile / "build_log.txt"
    previous_build_stat = build_log.stat() if build_log.is_file() else None
    with (run_dir / "launcher.log").open("wb") as output:
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT)
        plan["pid"] = process.pid
        (run_dir / "launch-report.json").write_text(json.dumps(plan, indent=2) + "\n")
        exit_code = process.wait()
    if build_log.is_file() and (previous_build_stat is None or
                                build_log.stat().st_mtime_ns != previous_build_stat.st_mtime_ns or
                                build_log.stat().st_size != previous_build_stat.st_size):
        shutil.copy2(build_log, run_dir / "build_log.txt")
    plan["exit_code"] = exit_code
    (run_dir / "launch-report.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def verify(args: argparse.Namespace) -> dict:
    try:
        player_text = args.player_log.read_text(encoding="utf-8", errors="replace")
        build_text = args.build_log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Refused(f"cannot read runtime log: {exc}") from exc
    allowed = set(args.allow_mod)
    r0_ids = [mod_id for mod_id in allowed if mod_id.lower().endswith("prober0")]
    if len(r0_ids) != 1:
        raise Refused("allowlist must contain exactly one R0 probe ID")
    marker = "[R0] "
    records = []
    for line in player_text.splitlines():
        if marker not in line:
            continue
        try:
            records.append(json.loads(line.split(marker, 1)[1]))
        except json.JSONDecodeError as exc:
            raise Refused(f"invalid R0 init JSON: {exc}") from exc
    if not records or any(not isinstance(record, dict) for record in records):
        raise Refused("no valid R0 init record in Player.log")
    if any(record.get("kind") == "init_error" for record in records):
        raise Refused("R0 init error in Player.log")
    inits = [record for record in records if record.get("kind") == "init"]
    if not inits:
        raise Refused("no R0 init record in Player.log")
    for record in inits:
        if record.get("assemblyVersion") != EXPECTED_ASSEMBLY_VERSION:
            raise Refused("runtime assembly version mismatch")
        mod_ids = record.get("activeModIds")
        if not isinstance(mod_ids, list) or len(mod_ids) != len(allowed) or set(mod_ids) != allowed:
            raise Refused("R0 init active mod IDs differ from allowlist")
        options = record.get("options")
        if not isinstance(options, dict) or any(options.get(key) != value
                                                 for key, value in EXPECTED_OPTIONS.items()):
            raise Refused("R0 init option mismatch")
        if record.get("optionsMatch") is not True:
            raise Refused("R0 init reports option mismatch")
    if "BuildLogger initialized" not in build_text:
        raise Refused("no build logger session")
    session = build_text.rsplit("BuildLogger initialized", 1)[1]
    headings = list(re.finditer(r"=== [^\n]* ===", session))
    probe_heading = next((heading for heading in headings
                          if re.search(r"R0\b", heading.group(), re.IGNORECASE)), None)
    if probe_heading is None:
        # The abbreviated fixture heading uses the ID rather than the title.
        probe_heading = next((heading for heading in headings
                              if r0_ids[0].upper() in heading.group().upper()), None)
    if probe_heading is None:
        raise Refused("R0 compile section missing from latest build session")
    next_heading = next((heading for heading in headings if heading.start() > probe_heading.start()), None)
    section = session[probe_heading.end():next_heading.start() if next_heading else len(session)]
    if ("Compiling 1 file..." not in section or "Success :)" not in section or
            f"Defined symbol: MOD_{r0_ids[0].upper()}" not in section):
        raise Refused("R0 one-file compile success missing from latest build session")
    if "==== FINAL LOAD ORDER ====" not in session:
        raise Refused("final load order missing from latest build session")
    load_section = session.rsplit("==== FINAL LOAD ORDER ====", 1)[1]
    load_ids = re.findall(r"(?m)^\[[^\]]+\]\s+\d+:\s+(\S+)\s*$", load_section)
    if len(load_ids) != len(allowed) or set(load_ids) != allowed:
        raise Refused(f"final load order differs from allowlist: {load_ids}")
    return {"ok": True, "r0_init_records": len(inits), "assembly_version": EXPECTED_ASSEMBLY_VERSION,
            "active_mod_ids": sorted(allowed), "r0_compiled_one_file": True,
            "effective_options": inits[-1]["options"], "player_log": str(args.player_log),
            "build_log": str(args.build_log)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "launch", "launch-background"):
        action = sub.add_parser(name)
        action.add_argument("--game", required=True, type=Path)
        action.add_argument("--profile", required=True, type=Path)
        action.add_argument("--baseline", required=True, type=Path)
        action.add_argument("--expected-buildid", required=True)
        action.add_argument("--allow-mod", action="append", required=True)
        action.add_argument("--workshop-dir", type=Path,
                            default=Path.home() / "Library/Application Support/Steam/steamapps/workshop/content/333640")
        action.add_argument("--appmanifest", type=Path)
        if name in ("launch", "launch-background"):
            action.add_argument("--steam-mode", choices=("steam", "no-steam"), required=True)
            action.add_argument("--log-dir", required=True, type=Path)
            action.add_argument("--dry-run", action="store_true")
            action.add_argument("--batchmode", action="store_true", default=name == "launch-background")
    verifier = sub.add_parser("verify")
    verifier.add_argument("--player-log", required=True, type=Path)
    verifier.add_argument("--build-log", required=True, type=Path)
    verifier.add_argument("--allow-mod", action="append", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "verify":
            result = verify(args)
        else:
            report = check(args)
            result = launch(args, report) if args.command in ("launch", "launch-background") else report
    except (Refused, OSError) as exc:
        print(f"R0 REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
