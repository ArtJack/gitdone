"""What the documents say must stay true: real output, real commands, links that go somewhere."""
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest

from helpers import EXAMPLE, ROOT
from gitdone import chart, cli, render, table as tables
from gitdone.plan import Plan

README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md"))]
PUBLIC = DOCS
COMMANDS = cli._parser()._subparsers._group_actions[0].choices


def demo():
    spec = importlib.util.spec_from_file_location("record", ROOT / "docs" / "demo" / "record.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TheDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name == "nt":
            raise unittest.SkipTest("the README shows a session on a shell with forward slashes")
        with tempfile.TemporaryDirectory() as folder:
            cls.lines = demo().transcript(folder)

    def test_every_line_it_printed_is_in_the_readme(self):
        for kind, text in self.lines:
            if kind == "out":
                self.assertIn(text, README)

    def test_the_readme_block_is_exactly_the_session(self):
        block = README[README.index("<!-- demo:start -->"):README.index("<!-- demo:end -->")]
        self.assertIn(demo().console_block(self.lines), block)

    def test_the_readme_shows_the_view_that_session_wrote(self):
        block = README[README.index("<!-- view:start -->"):README.index("<!-- view:end -->")]
        self.assertIn(demo().view_block(self.lines.view), block)
        self.assertIn("What is left", block)
        self.assertIn("Sign-in", block)
        self.assertIn("Live 2026-03-04", block)  # the session's own day, whatever day it is run: a stamp is in the id of every commit after it

    def test_the_recording_says_the_same(self):
        svg = (ROOT / "docs" / "img" / "demo.svg").read_text(encoding="utf-8")
        for kind, text in self.lines:
            if kind == "out":
                self.assertIn(text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), svg)

    def test_the_gate_refuses_what_the_demo_says_it_refuses(self):
        words = " ".join(t for k, t in self.lines if k == "out")
        for expected in ("refused, nothing changed", "is on main", "is not on main", "was reverted on main by"):
            self.assertIn(expected, words)


class TheEngineNamesItsEncoding(unittest.TestCase):
    def test_every_file_it_opens(self):
        """A default encoding is whatever the machine says, and on Windows that cannot hold a progress bar."""
        for path in sorted((ROOT / "gitdone").glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if re.search(r"(?<![.\w])open\(|\.read_text\(|\.write_text\(", line):
                    self.assertIn("encoding=", line, f"{path.name}:{number}")


class Commands(unittest.TestCase):
    def test_every_command_is_in_the_readmes_table(self):
        table = README[README.index("## Commands"):README.index("## The method")]
        for name in COMMANDS:
            if name not in ("opener", "status"):
                self.assertIn(f"`{name}", table + " `" + " ".join(re.findall(r"`([a-z-]+)", table)), name)

    def test_every_command_a_document_names_exists(self):
        for path in PUBLIC:
            text = path.read_text(encoding="utf-8")
            for name in re.findall(r"`gitdone ([a-z][a-z-]+)", text):
                self.assertIn(name, COMMANDS, f"{path.name}: gitdone {name}")

    def test_every_flag_the_readmes_table_names_exists(self):
        table = README[README.index("## Commands"):README.index("## The method")]
        known = set()
        for sub in COMMANDS.values():
            known |= {option for action in sub._actions for option in action.option_strings}
        for flag in re.findall(r"`(--[a-z-]+)", table):
            self.assertIn(flag, known)


class Links(unittest.TestCase):
    def test_relative_links_and_images_resolve(self):
        pattern = re.compile(r"\]\((?!https?://|#|mailto:)([^)#\s]+)|<img src=\"(?!https?://)([^\"]+)\"")
        for path in PUBLIC:
            for groups in pattern.findall(path.read_text(encoding="utf-8")):
                target = groups[0] or groups[1]
                self.assertTrue((path.parent / target).exists(), f"{path.name}: {target}")

    def test_anchors_within_docs_exist(self):
        for path in PUBLIC:
            for target, anchor in re.findall(r"\]\(([^)#\s]*\.md)#([^)]+)\)", path.read_text(encoding="utf-8")):
                text = (path.parent / target).read_text(encoding="utf-8")
                slugs = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^#+ (.+)$", text, re.M)}
                self.assertIn(anchor, slugs, f"{path.name}: {target}#{anchor}")


class Samples(unittest.TestCase):
    def test_the_plan_file_document_names_every_key_of_the_schema(self):
        schema = json.loads((ROOT / "schema" / "plan.schema.json").read_text(encoding="utf-8"))
        text = (ROOT / "docs" / "plan-file.md").read_text(encoding="utf-8")
        for key in schema["properties"]:
            if key != "$schema":
                self.assertIn(f"`{key}`", text, key)

    def test_the_example_view_is_committed_fresh(self):
        plan = Plan(EXAMPLE / "plan.json")
        table = tables.load_clean(plan)
        self.assertEqual(render.normalize((EXAMPLE / "STATUS.md").read_text(encoding="utf-8")), render.normalize(render.status_md(plan, table)))

    def test_the_readme_badge_matches_the_example(self):
        svg = (ROOT / "docs" / "img" / "bramble-badge.svg").read_text(encoding="utf-8")
        self.assertIn("25% strict · 46% weighted", svg)

    def test_the_chart_in_the_readme_says_what_the_example_says(self):
        svg = (ROOT / "docs" / "img" / "bramble-burnup.svg").read_text(encoding="utf-8")
        self.assertIn("scope 16 rows, weighted 46%, strict 25%", svg)


class TheChartInTheReadme(unittest.TestCase):
    def test_it_is_what_the_command_draws_from_the_generated_history(self):
        spec = importlib.util.spec_from_file_location("make_history", ROOT / "docs" / "demo" / "make_history.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            repo = os.path.join(folder, "bramble")
            module.main([repo])
            plan = Plan(os.path.join(repo, "plan.json"))
            drawn = chart.svg(chart.points(plan), plan.title)
        self.assertEqual(drawn, (ROOT / "docs" / "img" / "bramble-burnup.svg").read_text(encoding="utf-8"))


class WhatTheReadmeShowsOfTheSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name == "nt":
            raise unittest.SkipTest("the sample's portfolio runs the README's session, on a shell with forward slashes")
        spec = importlib.util.spec_from_file_location("timeline", ROOT / "docs" / "demo" / "timeline.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        with tempfile.TemporaryDirectory() as folder:
            cls.shown = cls.module.produce(folder)

    def test_each_block_is_what_the_commands_print(self):
        for name, block in self.shown.blocks.items():
            start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
            found = README[README.index(start) + len(start):README.index(end)].strip()
            self.assertEqual(self.module.normalized(found), self.module.normalized(block), name)

    def test_each_picture_is_what_the_command_draws(self):
        for name, picture in self.shown.pictures.items():
            self.assertEqual((ROOT / "docs" / "img" / name).read_text(encoding="utf-8"), picture, name)

    def test_the_scale_tells_the_story_it_is_there_for(self):
        for words in ("strict ████", "weighted ███████", "Next, in order", "gate: **PASS**", "| Project |", "**fail**, 1 contradicted"):
            self.assertIn(words, "\n".join(self.shown.blocks.values()))

    def test_the_date_is_not_on_the_readmes_page(self):
        self.assertNotIn("Likely done", README)
        self.assertNotIn("likely date", README)
        self.assertNotIn("bramble-burndown", README)

    def test_the_documents_samples_are_what_the_commands_print(self):
        text = (ROOT / "docs" / "timeline.md").read_text(encoding="utf-8")
        for name, sample in self.shown.samples.items():
            shown = text[text.index(f"<!-- {name}:start -->") + len(f"<!-- {name}:start -->"):text.index(f"<!-- {name}:end -->")].strip()
            self.assertEqual(self.module.normalized(shown), self.module.normalized(sample))

    def test_the_date_says_what_it_is_where_it_is_shown(self):
        for words in ("not a promise", "85% sure", "Time "):
            self.assertIn(words, self.shown.samples["eta"])
        self.assertIn("That moves the likely date", self.shown.samples["add"])


class TheInstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name == "nt":
            raise unittest.SkipTest("the README shows a session on a shell with forward slashes")
        spec = importlib.util.spec_from_file_location("guide", ROOT / "docs" / "demo" / "guide.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        with tempfile.TemporaryDirectory() as folder:
            cls.steps = cls.module.produce(folder)

    def test_each_block_in_the_readme_is_that_session(self):
        for name, block in self.steps.items():
            start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
            self.assertEqual(README[README.index(start) + len(start):README.index(end)].strip(), block, name)

    def test_the_steps_are_in_the_order_they_ran(self):
        places = [README.index(f"<!-- {name}:start -->") for name in self.steps]
        self.assertEqual(places, sorted(places))

    def test_every_step_did_what_it_says(self):
        said = "\n".join(self.steps.values())
        for words in ("result: PASS", "is on main", "Built, not live", "Not built → Partial", "added row 5", "out of the scope", "strict ████░░░░░░░░░░░░  25%"):
            self.assertIn(words, said)
        self.assertNotIn("FAIL", said)
        self.assertNotIn("refused", said)


class ThePageOnPyPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("pypi_readme", ROOT / "docs" / "demo" / "pypi_readme.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        cls.text = (ROOT / "README-pypi.md").read_text(encoding="utf-8")

    def test_it_is_made_from_the_readme(self):
        self.assertEqual(self.text, self.module.made_from(README))

    def test_the_registry_can_tell_it_is_ours(self):
        self.assertIn("<!-- mcp-name: io.github.ArtJack/gitdone -->", self.text)

    def test_nothing_on_it_depends_on_being_in_the_repository(self):
        for groups in re.findall(r"\]\((?!https?://|mailto:)([^)\s]+)\)|<img src=\"(?!https?://)([^\"]+)\"", self.text):
            self.fail(f"a relative link on PyPI: {groups}")

    def test_every_page_it_links_to_is_in_the_repository(self):
        for name in re.findall(r"https://(?:github\.com/ArtJack/gitdone/(?:blob|tree)|raw\.githubusercontent\.com/ArtJack/gitdone)/v[\d.]+/([^)\"#\s]+)", self.text):
            self.assertTrue((ROOT / name).exists(), name)

    def test_it_says_how_to_install_and_shows_the_scale(self):
        for words in ("pipx install gitdone", "uv tool install gitdone", "pip install gitdone", "/plugin install gitdone@gitdone", "npx skills add", "strict ████", "bramble-scale.svg", "sponsors/ArtJack"):
            self.assertIn(words, self.text)


def shipped_files():
    """What a release holds: the tracked files, whatever else sits in a checkout. An unpacked archive has no git, so everything."""
    done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True)
    if done.returncode == 0:
        return [ROOT / name for name in done.stdout.split("\0") if name]
    return [path for path in ROOT.rglob("*") if path.is_file() and not {"__pycache__", ".ruff_cache", ".venv", "dist"} & set(path.parts)]


class NoPrivatePaths(unittest.TestCase):
    def test_nothing_shipped_names_a_private_folder(self):
        for path in shipped_files():
            if "tests" in path.relative_to(ROOT).parts or path.suffix in (".png", ".pyc") or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for word in ("/Users/", "engineering-docs", "~/Projects"):
                self.assertNotIn(word, text, str(path))


if __name__ == "__main__":
    unittest.main()
