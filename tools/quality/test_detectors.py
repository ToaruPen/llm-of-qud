"""Exercise installed detectors with positive and negative source fixtures."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parent


class DetectorTests(unittest.TestCase):
    def test_python_candidates_and_clean_code(self):
        command = ["ruff", "check", "--config", str(CONFIG / "ruff.toml"),
                   "--no-cache", "--no-fix", "--output-format", "json",
                   "--stdin-filename", "candidate.py", "-"]
        bad = "import os\n\ndef ready(value):\n    if value:\n        return True\n    else:\n        return False\n"
        result = subprocess.run(command, input=bad, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual({item["code"] for item in json.loads(result.stdout)}, {"F401", "SIM103"})
        good = "import os\n\ndef ready():\n    return bool(os.getenv('READY'))\n"
        result = subprocess.run(command, input=good, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_swift_candidates_clean_code_and_no_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture with spaces.swift"
            command = ["swiftlint", "lint", "--config", str(CONFIG / "swiftlint.yml"),
                       "--strict", "--no-cache", "--quiet", "--reporter", "json", str(source)]
            bad = "import Foundation\nimport Foundation\nlet optional: Int? = nil\nlet value = optional ?? nil\n"
            source.write_text(bad)
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual({item["rule_id"] for item in json.loads(result.stdout)},
                             {"duplicate_imports", "redundant_nil_coalescing"})
            self.assertEqual(source.read_text(), bad)
            source.write_text("import Foundation\nlet value = ProcessInfo.processInfo.processName\n")
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [])

    def test_just_scoped_all_languages_and_space_paths_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(CONFIG, root / "tools/quality")
            shutil.copyfile(CONFIG.parent.parent / "justfile", root / "justfile")
            scope = root / "sample with spaces"
            scope.mkdir()
            (root / "tools/quality/roslyn/units.json").write_text(json.dumps([
                {"name": "fixture", "sources": ["sample with spaces/*.cs"], "framework": "net10.0"}
            ]))
            examples = {
                "bad.py": "import os\n",
                "bad.cs": 'string text = "x"; text.Trim();\n',
                "bad.swift": "import Foundation\nimport Foundation\n",
            }
            for name, content in examples.items():
                (scope / name).write_text(content)
            result = subprocess.run(["just", "anti-slop", scope.name], cwd=root,
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1, result.stderr)
            for expected in ("F401", "CA1806", "duplicate_imports"):
                self.assertIn(expected, result.stdout)
            for name, content in examples.items():
                self.assertEqual((scope / name).read_text(), content)
            clean = scope / "clean file.py"
            clean.write_text("def ready(value):\n    return bool(value)\n")
            result = subprocess.run(["just", "anti-slop-python", str(clean)], cwd=root,
                                    text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("All checks passed", result.stdout)
            result = subprocess.run(["just", "anti-slop", "missing.py"], cwd=root,
                                    text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing or symlink scope", result.stderr)


if __name__ == "__main__":
    unittest.main()
