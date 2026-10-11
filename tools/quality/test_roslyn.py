"""Prove real SDK analyzers execute, and failures cannot become clean scans."""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("quality_roslyn", Path(__file__).with_name("roslyn.py"))
roslyn = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(roslyn)


class RoslynTests(unittest.TestCase):
    def test_real_analyzers_detect_rethrow_unused_result_and_clean_counterpart(self):
        references = roslyn.framework_references(roslyn.sdk_paths())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample with spaces.cs"
            bad = '''using System;
public static class Sample {
  public static string F(string text) {
    try { text.Trim(); return text; }
    catch (Exception error) { throw error; }
  }
}'''
            source.write_text(bad)
            code, diagnostics = roslyn.compile_sources([source], references)
            self.assertEqual(code, 1, diagnostics)
            self.assertTrue({"CA1806", "CA2200"}.issubset({d["ruleId"] for d in diagnostics}), diagnostics)
            self.assertEqual(source.read_text(), bad)
            source.write_text('public static class Sample { public static string F(string text) { return text.Trim(); } }')
            code, diagnostics = roslyn.compile_sources([source], references)
            self.assertEqual(code, 0, diagnostics)
            self.assertEqual(diagnostics, [])

            # Same spelling, different resolved method: this is not string.Trim().
            source.write_text('''public sealed class Worker { public void Trim() {} }
public static class Sample { public static void F(Worker worker) { worker.Trim(); } }''')
            code, diagnostics = roslyn.compile_sources([source], references)
            self.assertEqual(code, 0, diagnostics)
            self.assertEqual(diagnostics, [])

    def test_compile_failure_is_not_a_candidate_only_result(self):
        references = roslyn.framework_references(roslyn.sdk_paths())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.cs"
            source.write_text("class Sample { MissingType field; }")
            code, diagnostics = roslyn.compile_sources([source], references)
            self.assertEqual(code, 2)
            self.assertIn("CS0246", {d["ruleId"] for d in diagnostics})

    def test_defines_select_conditional_source(self):
        references = roslyn.framework_references(roslyn.sdk_paths())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "conditional.cs"
            source.write_text("#if !QUALITY_TEST\nclass Sample { MissingType field; }\n#endif\n")
            code, diagnostics = roslyn.compile_sources([source], references)
            self.assertEqual(code, 2)
            self.assertIn("CS0246", {d["ruleId"] for d in diagnostics})
            code, diagnostics = roslyn.compile_sources([source], references, defines=["QUALITY_TEST"])
            self.assertEqual((code, diagnostics), (0, []))
            with self.assertRaises(ValueError):
                roslyn.compile_sources([source], references, defines=["A;B"])

    def test_surface_tests_unit_compiles_with_its_define(self):
        # run() must forward the unit's defines; without them SurfaceCheck.cs needs game types (exit 2).
        output = io.StringIO()
        with redirect_stdout(output):
            code = roslyn.run([roslyn.ROOT / "mod/surface-tests/Program.cs"])
        self.assertLess(code, 2, output.getvalue())

    def test_scope_expands_unit_with_dependencies_and_unknown_sources_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("mod/LlmOfQud/Policy.cs", "mod/LlmOfQud/CallbackRegistration.cs", "mod/tests/Program.cs"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            units = roslyn.select_units(root, [root / "mod/tests/Program.cs"])
            self.assertEqual(len(units), 1)
            self.assertEqual(len(units[0]["files"]), 3)
            unknown = root / "unknown.cs"
            unknown.touch()
            with self.assertRaises(ValueError):
                roslyn.select_units(root, [unknown])

    def test_missing_managed_configuration_fails_and_explicit_path_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(roslyn.os.environ, {}, clear=True), patch.object(roslyn, "SETTINGS", root / "missing.json"):
                with self.assertRaisesRegex(ValueError, "quality-setup-csharp"):
                    roslyn.managed_directory()
                with self.assertRaisesRegex(ValueError, "Managed directory"):
                    roslyn.managed_directory(root)
                for name in ("Assembly-CSharp.dll", "mscorlib.dll", "Newtonsoft.Json.dll"):
                    (root / name).touch()
                self.assertEqual(roslyn.managed_directory(root), root.resolve())


if __name__ == "__main__":
    unittest.main()
