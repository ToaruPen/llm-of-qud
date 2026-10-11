"""Regression tests for read-only source selection and detector orchestration."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("quality_check", Path(__file__).with_name("check.py"))
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


class SelectionTests(unittest.TestCase):
    def test_sources_include_untracked_files_but_exclude_evidence_and_generated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = [
                "harness/new.py", "mod/New.cs", "probes/new helper.swift", "tools/tool.py",
                "archives/old.py", ".runtime/run.py", ".staging/copy.cs", ".venv/lib.py",
                "mod/tests/obj/Generated.cs", "mod/tests/bin/Generated.cs",
                "probes/R34/results/copied.cs", "tools/quality/fixtures/bad.py",
            ]
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            selected = check.select_sources(root, [root])
            self.assertEqual(
                {path.relative_to(root).as_posix() for paths in selected.values() for path in paths},
                set(paths[:4]),
            )
            self.assertEqual(check.select_sources(root, [root / paths[-1]])["python"], [])

    def test_explicit_scope_deduplicates_and_rejects_missing_or_external_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.py"
            source.touch()
            self.assertEqual(check.select_sources(root, [root, source])["python"], [source])
            with self.assertRaises(ValueError):
                check.select_sources(root, [root / "missing.py"])
            with self.assertRaises(ValueError):
                check.select_sources(root, [root.parent])

    def test_symlink_sources_are_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "real.py").touch()
            (root / "link.py").symlink_to(root / "real.py")
            self.assertEqual(check.select_sources(root, [root])["python"], [root / "real.py"])
            with self.assertRaises(ValueError):
                check.select_sources(root, [root / "link.py"])


class ExecutionTests(unittest.TestCase):
    def test_all_languages_run_after_findings_and_paths_remain_single_arguments(self):
        sources = {language: [Path(f"/tmp/file with spaces{extension}")]
                   for extension, language in check.LANGUAGES.items()}
        with patch.object(check.shutil, "which", side_effect=lambda name: f"/bin/{name}"), \
                patch.object(check.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 1),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, stdout="[]", stderr=""),
                ]) as run:
            self.assertEqual(check.run_checks(sources), 1)
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            self.assertTrue(str(call.args[0][-1]).startswith("/tmp/file with spaces"))
            self.assertNotIn("--fix", call.args[0])
            self.assertNotIn("--autocorrect", call.args[0])

    def test_missing_tool_is_an_error_but_other_checks_still_run(self):
        sources = {"python": [Path("/tmp/a.py")], "csharp": [Path("/tmp/a.cs")], "swift": []}
        with patch.object(check.shutil, "which", side_effect=[None, "/bin/python3"]), \
                patch.object(check.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(check.run_checks(sources), 2)
        self.assertEqual(run.call_count, 1)

    def test_empty_language_skips_tool_and_process_error_is_not_a_finding(self):
        with patch.object(check.shutil, "which", return_value="/bin/ruff"), \
                patch.object(check.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)):
            self.assertEqual(check.run_checks({"python": [Path("/tmp/a.py")]}), 2)
        with patch.object(check.subprocess, "run") as run:
            self.assertEqual(check.run_checks({"python": []}), 0)
        run.assert_not_called()

    def test_swift_violation_exit_is_normalized_but_malformed_output_fails(self):
        finding = '[{"file":"a.swift","line":1,"character":1,"rule_id":"duplicate_imports","reason":"Duplicate"}]'
        with patch.object(check.shutil, "which", return_value="/bin/swiftlint"), \
                patch.object(check.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 2, stdout=finding, stderr="")):
            self.assertEqual(check.run_checks({"swift": [Path("/tmp/a.swift")]}), 1)
        with patch.object(check.shutil, "which", return_value="/bin/swiftlint"), \
                patch.object(check.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 2, stdout="", stderr="configuration error")):
            self.assertEqual(check.run_checks({"swift": [Path("/tmp/a.swift")]}), 2)


if __name__ == "__main__":
    unittest.main()
