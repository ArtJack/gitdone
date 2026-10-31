"""The Action's own script, run the way a runner runs it, with the inputs arriving through the environment."""
import json
import os
import re
import subprocess
import unittest

from helpers import ROOT, ProjectCase, git

ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")


def script():
    lines = ACTION.split("\n")
    start = next(i for i, line in enumerate(lines) if line.strip() == "run: |") + 1
    indent = len(lines[start]) - len(lines[start].lstrip())
    return "\n".join(line[indent:] for line in lines[start:] if line.strip()) + "\n"


@unittest.skipIf(os.name == "nt", "the runner's bash is what is being imitated")
class Script(ProjectCase):
    def setUp(self):
        super().setUp()
        self.change_plan(release=None)
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")

    def run_action(self, **inputs):
        event = self.tmp / "event.json"
        event.write_text("{}")
        self.output = self.tmp / "output"
        env = {**os.environ, "HOME": str(self.tmp / "home"), "ST_HOME": str(ROOT), "GITHUB_EVENT_PATH": str(event), "GITHUB_OUTPUT": str(self.output),
               "ST_PLAN": "", "ST_STRICT": "true", "ST_COMMENT": "true", "ST_ALWAYS": "false", "ST_PUBLISH": "", **inputs}
        env.pop("PYTHONPATH", None)
        return subprocess.run(["bash", "-e", "-c", script()], cwd=str(self.project), env=env, capture_output=True, text=True, encoding="utf-8")

    def test_it_finds_the_plan_and_strict_is_the_default(self):
        done = self.run_action()
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("result: FAIL in --strict", done.stdout)

    def test_strict_can_be_turned_off(self):
        done = self.run_action(ST_STRICT="false")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_named_plan_is_used(self):
        (self.project / ".gitdone.json").unlink()
        done = self.run_action(ST_PLAN="plan.json", ST_STRICT="false")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_an_input_cannot_reach_the_shell_as_code(self):
        marker = self.tmp / "ran"
        self.run_action(ST_PLAN=f'x"; touch {marker}; "')
        self.assertFalse(marker.exists())

    def test_outputs_reach_the_runner(self):
        self.run_action(ST_STRICT="false")
        self.assertIn("strict=25%", self.output.read_text())


class Declared(unittest.TestCase):
    def test_every_input_reaches_the_script(self):
        block = ACTION[ACTION.index("inputs:"):ACTION.index("outputs:")]
        for name in re.findall(r"^  ([a-z-]+):$", block, re.M):
            if name != "working-directory":
                self.assertIn("inputs." + name, ACTION, name)

    def test_inputs_are_never_substituted_into_the_script(self):
        self.assertNotIn("${{", script())

    def test_the_readme_action_tag_is_a_major_version(self):
        self.assertIn("ArtJack/gitdone@v0", (ROOT / "docs" / "ci.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
