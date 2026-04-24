#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / "docs" / "adr"
DECISION_LOG = ADR_DIR / "decision-log.md"
DECISIONS_DIR = ADR_DIR / "decisions"
INDEX_HEADER = """# ADR Decision Log

This index lists ADR decision records in append order. Each line points to an
individual decision artifact under `docs/adr/decisions/`.

"""


@dataclass(frozen=True)
class DecisionEntry:
    timestamp: str
    change: str
    required: bool
    rationale: str
    files: list[str]
    adr_paths: list[str]


def run_git_lines(*args: str) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--required", choices=["true", "false"], required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--adr", action="append", dest="adr_paths", default=[])
    parser.add_argument("--mode", choices=["staged", "worktree"], default="staged")
    return parser.parse_args()


def changed_files(mode: str) -> list[str]:
    if mode == "staged":
        return run_git_lines("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return run_git_lines("diff", "--name-only", "--diff-filter=ACMR")


def is_decision_artifact(path: str) -> bool:
    return path == "docs/adr/decision-log.md" or path.startswith("docs/adr/decisions/")


def unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "decision"


def next_decision_path(timestamp: str, change: str) -> Path:
    date_prefix = timestamp[:10]
    base_name = f"{date_prefix}-{slugify(change)}"
    candidate = DECISIONS_DIR / f"{base_name}.md"
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = DECISIONS_DIR / f"{base_name}-{suffix}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def format_decision_file(entry: DecisionEntry) -> str:
    lines = [
        "# ADR Decision Record",
        "",
        f"timestamp: {entry.timestamp}",
        f"change: {entry.change}",
        f"adr_required: {'true' if entry.required else 'false'}",
        f"rationale: {entry.rationale}",
    ]
    if entry.files:
        lines.append("files:")
        lines.extend(f"  - {path}" for path in entry.files)
    else:
        lines.append("files: []")
    if entry.adr_paths:
        lines.append("adr_paths:")
        lines.extend(f"  - {path}" for path in entry.adr_paths)
    else:
        lines.append("adr_paths: []")
    lines.append("")
    return "\n".join(lines)


def append_index_entry(*, timestamp: str, change: str, required: bool, decision_path: Path) -> None:
    relative_path = decision_path.relative_to(ADR_DIR).as_posix()
    line = (
        f"- {timestamp} | adr_required={'true' if required else 'false'} | {change} | "
        f"[details]({relative_path})"
    )
    if not DECISION_LOG.exists():
        DECISION_LOG.write_text(INDEX_HEADER + line + "\n", encoding="utf-8")
        return

    existing = DECISION_LOG.read_text(encoding="utf-8")
    prefix = existing if existing.endswith("\n") else existing + "\n"
    DECISION_LOG.write_text(prefix + line + "\n", encoding="utf-8")


def create_entry(
    *,
    required: bool,
    change: str,
    rationale: str,
    files: list[str],
    adr_paths: list[str],
) -> Path:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    entry = DecisionEntry(
        timestamp=timestamp,
        change=change,
        required=required,
        rationale=rationale,
        files=files,
        adr_paths=adr_paths,
    )
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    decision_path = next_decision_path(timestamp, change)
    decision_path.write_text(format_decision_file(entry), encoding="utf-8")
    append_index_entry(
        timestamp=entry.timestamp,
        change=entry.change,
        required=entry.required,
        decision_path=decision_path,
    )
    return decision_path


def require_single_line(*, field: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        print(f"--{field} must be a single line", file=sys.stderr)
        raise SystemExit(1)
    normalized = value.strip()
    if not normalized:
        print(f"--{field} must not be empty", file=sys.stderr)
        raise SystemExit(1)
    return normalized


def main() -> None:
    args = parse_args()
    required = args.required == "true"
    change = require_single_line(field="change", value=args.change)
    rationale = require_single_line(field="rationale", value=args.rationale)
    files = unique_paths(
        [path for path in changed_files(args.mode) if not is_decision_artifact(path)]
    )
    adr_paths = unique_paths(
        [require_single_line(field="adr", value=path) for path in args.adr_paths]
    )
    if required and not adr_paths:
        print("--adr is required when --required=true", file=sys.stderr)
        raise SystemExit(1)

    decision_path = create_entry(
        required=required,
        change=change,
        rationale=rationale,
        files=files,
        adr_paths=adr_paths,
    )
    print(f"Created ADR decision file {decision_path.relative_to(ROOT)}")
    print(f"Updated ADR decision index {DECISION_LOG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
