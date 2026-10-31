"""One version line. The engine says it, the plugin says it, and the changelog has a section for it."""
import json
import pathlib
import re
import subprocess
import sys
import unittest

from helpers import ROOT
from gitdone import __version__


def plugin_version(root):
    return json.loads((pathlib.Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


class Versions(unittest.TestCase):
    def test_the_engine_and_the_plugin_carry_one_version(self):
        self.assertEqual(__version__, plugin_version(ROOT))

    def test_the_registry_entry_carries_it_too(self):
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(server["version"], __version__)
        self.assertEqual(server["packages"][0]["version"], __version__)

    def test_the_registry_name_is_in_the_package_readme(self):
        server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
        self.assertIn(f"mcp-name: {server['name']}", (ROOT / "README-pypi.md").read_text(encoding="utf-8"))

    def test_the_version_is_a_release_number(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_the_changelog_has_a_section_for_it(self):
        done = subprocess.run([sys.executable, str(ROOT / ".github" / "release_notes.py"), __version__],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(done.stdout.strip())

    def test_notes_for_a_version_that_has_none_are_refused(self):
        done = subprocess.run([sys.executable, str(ROOT / ".github" / "release_notes.py"), "99.0.0"],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 1)
        self.assertIn("no section for 99.0.0", done.stderr)

    def test_the_project_takes_its_version_from_the_engine(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertRegex(text, r'dynamic = \["version"\]')
        self.assertIsNone(re.search(r'^version = ', text, re.M))


if __name__ == "__main__":
    unittest.main()
