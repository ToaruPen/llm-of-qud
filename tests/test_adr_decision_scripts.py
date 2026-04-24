from __future__ import annotations

import sys
from contextlib import redirect_stderr
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import cast
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str, relative_path: str) -> ModuleType:
    script_path = ROOT / relative_path
    spec = spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec for {relative_path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configure_adr_module(module: ModuleType, tmp_root: Path) -> None:
    adr_dir = tmp_root / "docs" / "adr"
    module.ROOT = tmp_root
    module.ADR_DIR = adr_dir
    module.DECISION_LOG = adr_dir / "decision-log.md"
    module.DECISIONS_DIR = adr_dir / "decisions"


def decision_text(
    *,
    change: str = "Test change",
    rationale: str = "Test rationale",
    adr_required: str = "false",
    files: list[str] | None = None,
    adr_paths: list[str] | None = None,
) -> str:
    lines = [
        "# ADR Decision Record",
        "",
        "timestamp: 2026-03-29T00:00:00Z",
        f"change: {change}",
        f"adr_required: {adr_required}",
        f"rationale: {rationale}",
    ]
    if files:
        lines.append("files:")
        lines.extend(f"  - {path}" for path in files)
    else:
        lines.append("files: []")
    if adr_paths:
        lines.append("adr_paths:")
        lines.extend(f"  - {path}" for path in adr_paths)
    else:
        lines.append("adr_paths: []")
    lines.append("")
    return "\n".join(lines)


def write_decision_fixture(
    tmp_root: Path,
    *,
    decision_filename: str = "2026-03-29-test-change.md",
    change: str = "Test change",
    rationale: str = "Test rationale",
    adr_required: str = "false",
    files: list[str] | None = None,
    adr_paths: list[str] | None = None,
) -> None:
    decisions_dir = tmp_root / "docs" / "adr" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / decision_filename).write_text(
        decision_text(
            change=change,
            rationale=rationale,
            adr_required=adr_required,
            files=files,
            adr_paths=adr_paths,
        ),
        encoding="utf-8",
    )
    (tmp_root / "docs" / "adr" / "decision-log.md").write_text(
        "# ADR Decision Log\n\n"
        f"- 2026-03-29T00:00:00Z | adr_required={adr_required} | {change} | "
        f"[details](decisions/{decision_filename})\n",
        encoding="utf-8",
    )


def run_main(module: ModuleType, argv: list[str]) -> tuple[str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with patch.object(sys, "argv", argv), patch("sys.stdout", stdout), redirect_stderr(stderr):
        module.main()
    return stdout.getvalue(), stderr.getvalue()


def run_and_capture_system_exit(module: ModuleType, argv: list[str]) -> tuple[int, str]:
    stderr = StringIO()
    with patch.object(sys, "argv", argv), redirect_stderr(stderr):
        with pytest.raises(SystemExit) as exc_info:
            module.main()
    return cast(int, exc_info.value.code), stderr.getvalue()


def test_create_adr_decision_uses_staged_default_and_filters_decision_artifacts() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("create_adr_decision", "scripts/create_adr_decision.py")
        configure_adr_module(module, tmp_root)

        with patch.object(
            module,
            "changed_files",
            return_value=[
                "scripts/create_adr_decision.py",
                "docs/adr/decision-log.md",
                "docs/adr/decisions/existing.md",
                "scripts/create_adr_decision.py",
            ],
        ):
            stdout, _ = run_main(
                module,
                [
                    "create_adr_decision.py",
                    "--required",
                    "false",
                    "--change",
                    "Split ADR index",
                    "--rationale",
                    "Keep conflict scope small",
                ],
            )

        decision_files = sorted((tmp_root / "docs" / "adr" / "decisions").glob("*.md"))
        assert len(decision_files) == 1
        contents = decision_files[0].read_text(encoding="utf-8")
        assert "scripts/create_adr_decision.py" in contents
        assert "docs/adr/decision-log.md" not in contents
        assert "docs/adr/decisions/existing.md" not in contents
        assert contents.count("scripts/create_adr_decision.py") == 1
        assert "Created ADR decision file" in stdout


def test_create_adr_decision_adds_numeric_suffix_for_collisions() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("create_adr_decision_collision", "scripts/create_adr_decision.py")
        configure_adr_module(module, tmp_root)
        fixed_dt = datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC)

        with patch.object(
            module,
            "datetime",
            type("dt", (), {"now": staticmethod(lambda _tz: fixed_dt)}),
        ):
            first = module.create_entry(
                required=False,
                change="Same change text",
                rationale="First entry",
                files=["scripts/create_adr_decision.py"],
                adr_paths=[],
            )
            second = module.create_entry(
                required=False,
                change="Same change text",
                rationale="Second entry",
                files=["scripts/check_adr_decision.py"],
                adr_paths=[],
            )

        assert first.name.endswith("same-change-text.md")
        assert second.name.endswith("same-change-text-2.md")


def test_create_adr_decision_rejects_required_true_without_adr() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("create_required", "scripts/create_adr_decision.py")
        configure_adr_module(module, tmp_root)

        with patch.object(module, "changed_files", return_value=["config/settings.yaml"]):
            code, stderr = run_and_capture_system_exit(
                module,
                [
                    "create_adr_decision.py",
                    "--required",
                    "true",
                    "--change",
                    "Document trigger",
                    "--rationale",
                    "ADR should be mandatory",
                ],
            )

        assert code == 1
        assert "--adr is required" in stderr


def test_check_adr_decision_uses_template_trigger_configuration() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_triggers", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)

        assert module.TRIGGER_PREFIXES == ("config/", "harness/", "docs/adr/", "scripts/")
        assert module.TRIGGER_FILES == {"pyproject.toml", "package.json"}
        assert module.is_trigger("config/settings.yaml")
        assert module.is_trigger("harness/manifest.yaml")
        assert module.is_trigger("scripts/create_adr_decision.py")
        assert module.is_trigger("pyproject.toml")
        assert module.is_trigger("package.json")
        assert not module.is_trigger("docs/adr/decision-log.md")
        assert not module.is_trigger("docs/adr/decisions/example.md")
        assert not module.is_trigger("README.md")


def test_check_adr_decision_accepts_latest_changed_decision_record() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_accepts", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)
        write_decision_fixture(
            tmp_root,
            decision_filename="2026-03-29-split-log.md",
            change="Split ADR index",
            rationale="Keep conflict scope small",
            files=["scripts/create_adr_decision.py"],
        )

        with patch.object(
            module,
            "staged_files",
            return_value=[
                "scripts/create_adr_decision.py",
                "docs/adr/decision-log.md",
                "docs/adr/decisions/2026-03-29-split-log.md",
            ],
        ):
            stdout, _ = run_main(module, ["check_adr_decision.py"])

        assert "ADR decision gate passed" in stdout


def test_check_blocks_when_decision_log_not_in_staged() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_no_log", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)
        write_decision_fixture(tmp_root, files=["scripts/check_adr_decision.py"])

        with patch.object(
            module,
            "staged_files",
            return_value=[
                "scripts/check_adr_decision.py",
                "docs/adr/decisions/2026-03-29-test-change.md",
            ],
        ):
            code, stderr = run_and_capture_system_exit(module, ["check_adr_decision.py"])

        assert code == 1
        assert "decision-log.md" in stderr


def test_check_blocks_when_trigger_files_not_covered() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_uncovered", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)
        write_decision_fixture(tmp_root, files=["scripts/other.py"])

        with patch.object(
            module,
            "staged_files",
            return_value=[
                "scripts/check_adr_decision.py",
                "docs/adr/decision-log.md",
                "docs/adr/decisions/2026-03-29-test-change.md",
            ],
        ):
            code, stderr = run_and_capture_system_exit(module, ["check_adr_decision.py"])

        assert code == 1
        assert "does not cover" in stderr


def test_check_blocks_when_adr_paths_mismatch() -> None:
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_adr_mismatch", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)
        write_decision_fixture(
            tmp_root,
            decision_filename="2026-03-29-adr-mismatch.md",
            change="ADR mismatch test",
            rationale="Testing adr_paths validation",
            adr_required="true",
            files=["config/settings.yaml", "docs/adr/0099-real-adr.md"],
            adr_paths=["docs/adr/9999-wrong.md"],
        )

        with patch.object(
            module,
            "staged_files",
            return_value=[
                "config/settings.yaml",
                "docs/adr/decision-log.md",
                "docs/adr/decisions/2026-03-29-adr-mismatch.md",
                "docs/adr/0099-real-adr.md",
            ],
        ):
            code, stderr = run_and_capture_system_exit(module, ["check_adr_decision.py"])

        assert code == 1
        assert "adr_paths" in stderr


def test_check_accepts_push_mode_for_new_branch() -> None:
    """Regression: --mode push with remote_sha=000... (new branch) must aggregate all commits."""
    with TemporaryDirectory() as temp_dir:
        tmp_root = Path(temp_dir)
        module = load_script_module("check_push_new", "scripts/check_adr_decision.py")
        configure_adr_module(module, tmp_root)
        write_decision_fixture(
            tmp_root,
            decision_filename="2026-03-29-push-test.md",
            change="Push test",
            rationale="Validate new-branch push path",
            files=["scripts/create_adr_decision.py"],
        )

        zero = "0" * 40
        fake_local_sha = "a" * 40
        stdin_line = f"refs/heads/feat/test {fake_local_sha} refs/heads/feat/test {zero}\n"

        def fake_push_files() -> list[str]:
            return [
                "scripts/create_adr_decision.py",
                "docs/adr/decision-log.md",
                "docs/adr/decisions/2026-03-29-push-test.md",
            ]

        with patch.object(module, "push_files", side_effect=fake_push_files):
            stdout, _ = run_main(module, ["check_adr_decision.py", "--mode", "push"])

        assert "ADR decision gate passed" in stdout


def test_git_hooks_use_generic_adr_gate_messages() -> None:
    pre_commit = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    pre_push = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")

    assert "adr gate" in pre_commit
    assert "adr gate" in pre_push
    assert "wooly-fluffy" not in pre_commit
    assert "wooly-fluffy" not in pre_push
    assert "uv run python scripts/smoke_test.py" not in pre_push
