#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"
DECISION_LOG = ADR_DIR / "decision-log.md"
DECISIONS_DIR = ADR_DIR / "decisions"
INDEX_LINK_PATTERN = re.compile(r"\[[^]]+\]\((decisions/[^)]+\.md)\)\s*$")
ADR_FILE_PATTERN = re.compile(r"docs/adr/\d{4}-[a-z0-9-]+\.md$")
TRIGGER_PREFIXES = ("config/", "harness/", "docs/adr/", "scripts/")
TRIGGER_FILES = {"pyproject.toml", "package.json"}


@dataclass(frozen=True)
class DecisionEntry:
    required: bool
    rationale: str
    files: list[str]
    adr_paths: list[str]


def git_lines(*args: str) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"BLOCKED: git command failed: git {' '.join(args)}", file=sys.stderr)
        raise SystemExit(1) from e
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def staged_files() -> list[str]:
    return git_lines("diff", "--cached", "--name-only", "--diff-filter=ACMR")


def push_files() -> list[str]:
    zero = "0" * 40
    raw = sys.stdin.read().strip().splitlines()
    if len(raw) > 1:
        print(
            "BLOCKED: multi-ref push is not supported by ADR gate; push one ref at a time",
            file=sys.stderr,
        )
        raise SystemExit(1)
    changed: set[str] = set()
    for line in raw:
        parts = line.split()
        if len(parts) != 4:
            print(
                f"BLOCKED: malformed pre-push input line: {line!r}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == zero:
            continue
        if remote_sha == zero:
            # New remote ref: collect changed files across all unpublished commits
            diff = git_lines(
                "log",
                "--name-only",
                "--pretty=format:",
                "--diff-filter=ACMR",
                local_sha,
                "--not",
                "--remotes",
            )
        else:
            diff = git_lines(
                "diff",
                "--name-only",
                f"{remote_sha}..{local_sha}",
                "--diff-filter=ACMR",
            )
        changed.update(diff)
    return sorted(changed)


def is_decision_artifact(path: str) -> bool:
    return path == "docs/adr/decision-log.md" or path.startswith("docs/adr/decisions/")


def is_trigger(path: str) -> bool:
    if is_decision_artifact(path):
        return False
    if path in TRIGGER_FILES:
        return True
    return path.startswith(TRIGGER_PREFIXES)


def actual_adr_changes(changed: list[str]) -> list[str]:
    return sorted(path for path in changed if ADR_FILE_PATTERN.fullmatch(path))


def parse_decision_file(path: Path) -> DecisionEntry | None:
    if not path.exists():
        return None

    required: bool | None = None
    rationale = ""
    files: list[str] = []
    adr_paths: list[str] = []
    saw_files = False
    saw_adr_paths = False
    current_list: list[str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("adr_required:"):
            value = line.split(":", 1)[1].strip().lower()
            if value not in {"true", "false"}:
                return None
            required = value == "true"
            current_list = None
        elif line.startswith("rationale:"):
            rationale = line.split(":", 1)[1].strip()
            current_list = None
        elif line == "files:":
            saw_files = True
            current_list = files
        elif line == "files: []":
            saw_files = True
            current_list = None
        elif line == "adr_paths:":
            saw_adr_paths = True
            current_list = adr_paths
        elif line == "adr_paths: []":
            saw_adr_paths = True
            current_list = None
        elif line.startswith("  - ") and current_list is not None:
            current_list.append(line[4:].strip())
        else:
            current_list = None

    if required is None or not saw_files or not saw_adr_paths:
        return None
    return DecisionEntry(
        required=required, rationale=rationale, files=files, adr_paths=adr_paths
    )


def latest_decision_path() -> Path | None:
    if not DECISION_LOG.exists():
        return None

    lines = DECISION_LOG.read_text(encoding="utf-8").splitlines()
    last_line: str | None = None
    for raw_line in reversed(lines):
        stripped = raw_line.strip()
        if stripped:
            last_line = stripped
            break

    if last_line is None or not last_line.startswith("- "):
        return None

    match = INDEX_LINK_PATTERN.search(last_line)
    if match is None:
        print(
            "BLOCKED: latest index line is malformed (no valid decision link)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return ADR_DIR / match.group(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["staged", "push"], default="staged")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    changed = staged_files() if args.mode == "staged" else push_files()
    triggered = sorted(path for path in changed if is_trigger(path))
    if not triggered:
        return

    if "docs/adr/decision-log.md" not in changed:
        print(
            "BLOCKED: ADR-triggering change requires docs/adr/decision-log.md update",
            file=sys.stderr,
        )
        raise SystemExit(1)

    decision_artifacts = sorted(
        path for path in changed if path.startswith("docs/adr/decisions/")
    )
    if not decision_artifacts:
        print(
            "BLOCKED: ADR-triggering change requires a docs/adr/decisions/*.md record",
            file=sys.stderr,
        )
        raise SystemExit(1)

    decision_path = latest_decision_path()
    if decision_path is None:
        print(
            "BLOCKED: no ADR decision entry found in docs/adr/decision-log.md",
            file=sys.stderr,
        )
        raise SystemExit(1)

    decision_relative_path = decision_path.relative_to(ROOT).as_posix()
    if decision_relative_path not in decision_artifacts:
        print(
            "BLOCKED: latest ADR decision index entry must point to a changed decision record",
            file=sys.stderr,
        )
        raise SystemExit(1)

    decision = parse_decision_file(decision_path)
    if decision is None:
        print(
            f"BLOCKED: ADR decision file is missing or malformed: {decision_path.relative_to(ROOT)}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    missing = [path for path in triggered if path not in decision.files]
    if missing:
        print(
            f"BLOCKED: latest ADR decision entry does not cover changed files: {', '.join(missing)}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not decision.rationale:
        print("BLOCKED: ADR decision entry requires a rationale", file=sys.stderr)
        raise SystemExit(1)

    if decision.required:
        adr_changes = actual_adr_changes(changed)
        if not adr_changes:
            print(
                "BLOCKED: adr_required=true but no ADR file changes detected",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if sorted(decision.adr_paths) != adr_changes:
            print(
                "BLOCKED: adr_required=true but latest decision entry adr_paths do not match changed ADR files",
                file=sys.stderr,
            )
            raise SystemExit(1)

    print("ADR decision gate passed")


if __name__ == "__main__":
    main()
