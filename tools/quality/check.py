"""Run candidate detectors without changing source or game state."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LANGUAGES = {".py": "python", ".cs": "csharp", ".swift": "swift"}
CONFIG = Path(__file__).resolve().parent
ROOT = CONFIG.parent.parent
EXCLUDED = {"archives", "results", "bin", "obj", "__pycache__", "node_modules"}
FIXTURES = Path("tools/quality/fixtures")


def select_sources(root: Path, paths: list[Path]) -> dict[str, list[Path]]:
    """Include new/untracked source; never traverse evidence, caches or symlinks."""
    root = root.resolve()
    selected = {language: set() for language in LANGUAGES.values()}

    def excluded(path: Path) -> bool:
        relative = path.relative_to(root)
        return (
            path.is_symlink()
            or any(part.startswith(".") or part in EXCLUDED for part in relative.parts)
            or relative == FIXTURES or FIXTURES in relative.parents
        )

    def add(path: Path) -> None:
        if not excluded(path) and path.suffix in LANGUAGES:
            selected[LANGUAGES[path.suffix]].add(path)

    for requested in paths:
        if requested.is_symlink() or not requested.exists():
            raise ValueError(f"Missing or symlink scope: {requested}")
        path = requested.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Scope must be inside {root}: {requested}")
        if excluded(path):
            continue
        if path.is_file():
            add(path)
            continue
        for directory, directories, filenames in os.walk(path, followlinks=False):
            base = Path(directory)
            directories[:] = [name for name in directories if not excluded(base / name)]
            for filename in filenames:
                add(base / filename)
    return {language: sorted(files) for language, files in selected.items()}


def run_checks(sources: dict[str, list[Path]], *, structural=False, managed=None) -> int:
    commands = {
        "python": ["ruff", "check", "--config", str(CONFIG / "ruff.toml"),
                   "--no-cache", "--no-fix"],
        "csharp": [sys.executable, "-B", str(CONFIG / "roslyn.py")],
        "swift": ["swiftlint", "lint", "--config", str(CONFIG / "swiftlint.yml"),
                  "--strict", "--no-cache", "--quiet", "--reporter", "json"],
    }
    if structural:
        commands["csharp"] = ["ast-grep", "scan", "--config", str(CONFIG / "sgconfig.yml"),
                              "--error", "--report-style", "short"]
    elif managed is not None:
        commands["csharp"] += ["--managed", str(managed)]
    exit_code = 0
    for language, files in sources.items():
        if not files:
            print(f"{language}: no source files in scope", flush=True)
            continue
        command = commands[language]
        if shutil.which(command[0]) is None:
            print(f"{language}: missing {command[0]}; see tools/quality/README.md", file=sys.stderr)
            exit_code = 2
            continue
        print(f"{language}: checking {len(files)} files", flush=True)
        try:
            result = subprocess.run([*command, *map(str, files)], cwd=ROOT, check=False,
                                    capture_output=language == "swift", text=True)
        except OSError as error:
            print(f"{language}: could not run detector: {error}", file=sys.stderr)
            exit_code = 2
            continue
        code = result.returncode
        if language == "swift":
            # SwiftLint uses 2 for strict violations as well as some tool errors.
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="")
            try:
                findings = json.loads(result.stdout)
                if not isinstance(findings, list):
                    raise ValueError("expected a JSON array")
                for item in findings:
                    print(f"{item['file']}:{item['line']}:{item.get('character') or 1}: "
                          f"{item['rule_id']}: {item['reason']}")
                code = 1 if code in (0, 2) and findings else (0 if code == 0 else 2)
            except (ValueError, TypeError, KeyError) as error:
                print(f"swift: invalid detector output: {error}", file=sys.stderr)
                code = 2
        exit_code = max(exit_code, code if code in (0, 1) else 2)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=list(LANGUAGES.values()))
    parser.add_argument("--managed", type=Path, help="Fixed-game Managed directory for Roslyn")
    parser.add_argument("--structural", action="store_true", help="Optional C# AST hints, not semantic analysis")
    parser.add_argument("paths", nargs="*", type=Path, help="Repository files/directories; default: all")
    args = parser.parse_args()
    if args.structural and args.language != "csharp":
        parser.error("--structural requires --language csharp")
    try:
        sources = select_sources(ROOT, args.paths or [ROOT])
    except ValueError as error:
        parser.error(str(error))
    if args.language:
        sources = {args.language: sources[args.language]}
    if not any(sources.values()):
        print("No supported source files selected; check paths and exclusions.", file=sys.stderr)
        return 2
    return run_checks(sources, structural=args.structural, managed=args.managed)


if __name__ == "__main__":
    sys.exit(main())
