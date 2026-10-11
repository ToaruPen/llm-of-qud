"""Exercise the secretlint home-path rule with positive and negative fixtures."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Path segments are joined at runtime so `just secretlint` does not flag this file.
USERS, HOME = "Users", "home"
FLAGGED = [
    f"macOS /{USERS}/alice/notes.md",
    f"Linux /{HOME}/bob/.config",
    f"Windows C:\\{USERS}\\carol\\save.sav",
    f"escaped C:\\\\{USERS}\\\\dave\\\\save.sav",
    f"encoded /tmp/claude/-{USERS}-erin-Dev-project/scratch",
]
CLEAN = [
    "outside ~/Dev/coq-decompiled_stable",
    "placeholder /Users/<name>/Library",
    "relative ../../.runtime/run1/metrics.json",
    "msbuild $(HOME)/Games/CoQ.app",
    "sentinel /Users/someone/private/save.sav",
    "url https://example.com/home/page",
    "prose Power-Users-Guide-notes",
]


def secretlint(*paths):
    command = ["npx", "--no-install", "secretlint", "--no-glob", "--no-gitignore", "--format", "json",
               *map(str, paths)]
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


class SecretlintRuleTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT / "node_modules/.bin/secretlint").exists():
            self.fail("secretlint is not installed; run: npm ci")

    def test_home_paths_are_flagged_and_placeholders_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".hidden").mkdir()
            bad, dotted, good = root / "bad.txt", root / ".hidden/notes.md", root / "good.txt"
            bad.write_text("\n".join(FLAGGED) + "\n")
            dotted.write_text(FLAGGED[0] + "\n")
            good.write_text("\n".join(CLEAN) + "\n")
            result = secretlint(bad, dotted, good)
            self.assertEqual(result.returncode, 1, result.stderr)
            found = {Path(item["filePath"]).name: item["messages"] for item in json.loads(result.stdout)}
            self.assertEqual([m["loc"]["start"]["line"] for m in found["bad.txt"]], [1, 2, 3, 4, 5])
            self.assertEqual(len(found["notes.md"]), 1)
            self.assertEqual(found["good.txt"], [])

    def test_recipe_fails_without_installed_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("justfile", ".secretlintrc.json"):
                shutil.copyfile(ROOT / name, root / name)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            result = subprocess.run(["just", "secretlint"], cwd=root, text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("npm ci", result.stderr)


if __name__ == "__main__":
    unittest.main()
