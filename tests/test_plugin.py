"""The plugin stays thin: a shim over the engine it bundles. No agent, and nothing that decides a status."""
import json
import os
import re
import subprocess
import tempfile
import unittest

from helpers import ENGINE, ROOT, ProjectCase
from gitdone import __version__, cli, install

PLUGIN = ROOT
SHIM = PLUGIN / "bin" / "gitdone"


def frontmatter(path):
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    return dict(line.split(": ", 1) for line in match.group(1).split("\n")), match.group(2)


class Manifests(unittest.TestCase):
    def test_the_manifests_agree(self):
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual(plugin["name"], "gitdone")
        self.assertEqual(market["plugins"][0]["name"], plugin["name"])
        self.assertEqual(market["plugins"][0]["source"], "./")

    def test_the_version_is_the_engines(self):
        plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        done = subprocess.run(["python3", str(ENGINE), "--version"], capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), plugin["version"])

    @unittest.skipUnless((ROOT / "gitdone").is_file(), "only until the adopters that call it have moved")
    def test_the_script_at_the_root_still_runs_for_the_adopters_that_call_it(self):
        done = subprocess.run(["python3", str(ROOT / "gitdone"), "--version"], capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), __version__)

    def test_the_session_start_hook_calls_the_engine(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(list(hooks), ["SessionStart"])
        command = hooks["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("bin/gitdone", command)
        self.assertIn("opener --hook", command)


class Thin(unittest.TestCase):
    def test_no_agents(self):
        self.assertFalse((PLUGIN / "agents").exists())

    def test_the_command_skill_is_one_only_a_person_can_start(self):
        meta, _ = frontmatter(PLUGIN / "skills" / "status" / "SKILL.md")
        self.assertEqual(meta["name"], "status")
        self.assertEqual(meta["disable-model-invocation"], "true")

    def test_the_two_skills_are_the_command_and_the_method(self):
        self.assertEqual({p.name for p in (PLUGIN / "skills").iterdir()}, {"status", "gitdone"})

    def test_the_method_skill_forbids_routing_around_the_gate(self):
        _, body = frontmatter(PLUGIN / "skills" / "gitdone" / "SKILL.md")
        for words in ("Never choose\na status from your own reading of the code", "--no-verify", "report the refusal", "A change of scope is the person's decision"):
            self.assertIn(words, body)

    def test_the_method_skill_names_only_real_commands(self):
        _, body = frontmatter(PLUGIN / "skills" / "gitdone" / "SKILL.md")
        for name in re.findall(r"`gitdone ([a-z-]+)", body):
            self.assertIn(name, cli._parser()._subparsers._group_actions[0].choices)

    def test_the_skill_forbids_deciding_a_status_from_code(self):
        _, body = frontmatter(PLUGIN / "skills" / "status" / "SKILL.md")
        self.assertIn("never look in the code", body)
        self.assertIn("no reading of code", body)

    def test_the_skill_names_only_engine_commands(self):
        _, body = frontmatter(PLUGIN / "skills" / "status" / "SKILL.md")
        table = body[body.index("| `$ARGUMENTS`"):body.index("Rules:")]
        for code in re.findall(r"`(gitdone[^`]*)`", table):
            self.assertRegex(code, r"^gitdone (opener|shipped|mark|rows|week|check|doctor)\b")

    def test_the_shim_is_all_the_plugin_adds_to_the_path(self):
        self.assertEqual([p.name for p in (PLUGIN / "bin").iterdir()], ["gitdone"])


class Shim(unittest.TestCase):
    def run_shim(self, *args, **env):
        base = {k: v for k, v in os.environ.items() if k not in ("GITDONE_HOME", "CLAUDE_PLUGIN_ROOT", "PYTHONPATH")}
        return subprocess.run(["sh", str(SHIM), *args], env={**base, **env}, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())

    def test_it_runs_the_bundled_engine_from_anywhere(self):
        done = self.run_shim("--version")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), __version__)

    def test_it_needs_no_environment_and_no_home_folder_convention(self):
        done = self.run_shim("--version", HOME="/nowhere")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_plugin_root_is_where_claude_code_says(self):
        done = self.run_shim("--version", CLAUDE_PLUGIN_ROOT=str(ROOT))
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_missing_engine_is_an_error_for_a_command(self):
        done = self.run_shim("opener", GITDONE_HOME="/nowhere")
        self.assertEqual(done.returncode, 2)
        self.assertIn("/nowhere/gitdone", done.stderr)

    def test_a_missing_engine_never_stops_a_session(self):
        done = self.run_shim("opener", "--hook", GITDONE_HOME="/nowhere")
        self.assertEqual(done.returncode, 0)
        self.assertIn("/nowhere/gitdone", done.stdout)


class ProjectSkill(ProjectCase):
    def skill(self):
        return self.project / ".claude" / "skills" / install.SKILL_NAME / "SKILL.md"

    def install(self):
        return self.cli("install-skill", "--into", str(self.project), plan=False)

    def test_it_takes_its_words_from_the_plugin(self):
        code, _, err = self.install()
        self.assertEqual(code, 0, err)
        meta, body = frontmatter(self.skill())
        self.assertEqual(meta["name"], install.SKILL_NAME)
        self.assertEqual(meta["disable-model-invocation"], "true")
        self.assertEqual(meta["allowed-tools"], "Bash(gitdone:*)")
        _, plugin_body = frontmatter(PLUGIN / "skills" / "status" / "SKILL.md")
        self.assertIn("gitdone project skill", body.split("\n")[0])
        self.assertIn("never look in the code", body)
        self.assertEqual(body.strip().split("\n")[-1], plugin_body.strip().split("\n")[-1])

    def test_it_names_the_engine_where_no_plugin_root_exists(self):
        self.install()
        _, body = frontmatter(self.skill())
        self.assertNotIn("CLAUDE_PLUGIN_ROOT", body)
        self.assertIn("uvx gitdone", body)
        self.assertNotIn(str(ROOT), body, "this file is likely to be committed, so it names no folder of this machine")

    def test_it_can_be_written_again(self):
        self.install()
        code, _, err = self.install()
        self.assertEqual(code, 0, err)

    def test_someone_elses_skill_is_left_alone(self):
        self.skill().parent.mkdir(parents=True)
        self.skill().write_text("mine\n")
        code, _, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("is not this skill", err)
        self.assertEqual(self.skill().read_text(), "mine\n")

    def test_the_project_root_comes_from_the_pointer(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        done = subprocess.run(["python3", str(ENGINE), "install-skill"], cwd=str(self.project), capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.tmp / "home")})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(self.skill().exists())

    def test_no_pointer_and_no_folder_is_a_clear_error(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        done = subprocess.run(["python3", str(ENGINE), "install-skill"], cwd=str(elsewhere), capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.tmp / "home")})
        self.assertEqual(done.returncode, 2)
        self.assertIn("pass --into", done.stderr)


if __name__ == "__main__":
    unittest.main()
