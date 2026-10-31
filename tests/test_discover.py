import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import ENGINE, ProjectCase
from gitdone.discover import POINTER, find_plan
from gitdone.plan import PlanError


class Find(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = pathlib.Path(self._tmp.name).resolve()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.packs = self.home / "packs"
        self.packs.mkdir()
        self.project = self.home / "Projects" / "thing"
        self.deep = self.project / "src" / "deep"
        self.deep.mkdir(parents=True)
        self.plan = self.project / "tracker" / "plan.json"
        self.plan.parent.mkdir()
        self.plan.write_text("{}")

    def find(self, start=None):
        return find_plan(start or self.deep, packs=self.packs)

    def point(self, directory, plan="tracker/plan.json"):
        (directory / POINTER).write_text(json.dumps({"plan": plan}))

    def test_nothing_anywhere(self):
        self.assertIsNone(self.find())

    def test_a_pointer_at_the_project_root_is_found_from_below(self):
        self.point(self.project)
        self.assertEqual(self.find(), self.plan)

    def test_the_nearest_pointer_wins(self):
        self.point(self.project)
        other = self.deep / "plan.json"
        other.write_text("{}")
        self.point(self.deep, "plan.json")
        self.assertEqual(self.find(), other)

    def test_a_pointer_may_be_absolute_or_home_relative(self):
        self.point(self.project, str(self.plan))
        self.assertEqual(self.find(), self.plan)
        self.point(self.project, "~/Projects/thing/tracker/plan.json")
        self.assertEqual(self.find(), self.plan)

    def test_a_pointer_in_the_home_directory_is_not_a_project(self):
        self.point(self.home, "Projects/thing/tracker/plan.json")
        self.assertIsNone(self.find())

    def test_a_broken_pointer_says_so(self):
        (self.project / POINTER).write_text("{")
        with self.assertRaisesRegex(PlanError, "is unreadable"):
            self.find()

    def test_the_file_may_be_the_plan_itself(self):
        (self.project / POINTER).write_text(json.dumps({"status_doc": "status-table.md"}))
        self.assertEqual(self.find(), self.project / POINTER)

    def test_a_pointer_to_a_missing_plan_says_so(self):
        self.point(self.project, "gone.json")
        with self.assertRaisesRegex(PlanError, "which does not exist"):
            self.find()

    def test_a_pack_that_names_a_tracker(self):
        (self.packs / "thing.md").write_text("# thing\n\n<!-- gitdone: tracker/plan.json -->\n\n## 5. Queue\n")
        self.assertEqual(self.find(), self.plan)

    def test_the_marker_may_be_a_plain_line(self):
        (self.packs / "thing.md").write_text("gitdone: ~/Projects/thing/tracker/plan.json\n")
        self.assertEqual(self.find(), self.plan)

    def test_a_pack_that_names_none(self):
        (self.packs / "thing.md").write_text("# thing\n\nThe gitdone: is not used here, it says so in prose.\n")
        self.assertIsNone(self.find())

    def test_a_pointer_beats_a_pack(self):
        other = self.project / "other.json"
        other.write_text("{}")
        (self.packs / "thing.md").write_text("gitdone: other.json\n")
        self.point(self.project)
        self.assertEqual(self.find(), self.plan)

    def test_the_packs_folder_comes_from_the_environment(self):
        (self.packs / "thing.md").write_text("gitdone: tracker/plan.json\n")
        with mock.patch.dict(os.environ, {"GITDONE_PACKS": str(self.packs)}):
            self.assertEqual(find_plan(self.deep), self.plan)

    def test_without_the_environment_no_pack_is_read(self):
        """A stranger's machine has no packs folder; the rule must not look for one in a default place."""
        (self.packs / "thing.md").write_text("gitdone: tracker/plan.json\n")
        with mock.patch.dict(os.environ):
            os.environ.pop("GITDONE_PACKS", None)
            self.assertIsNone(find_plan(self.deep))


class Hook(ProjectCase):
    """What the SessionStart hook does, run as a process the way Claude Code runs it."""

    def hook(self, cwd, payload=None, env=None):
        stdin = json.dumps(payload) if payload is not None else ""
        base = {**os.environ, "HOME": str(self.tmp / "home"), "GITDONE_PACKS": str(self.tmp / "no-packs")}
        return subprocess.run([sys.executable, str(ENGINE), "opener", "--hook"], cwd=str(cwd), input=stdin,
                              env={**base, **(env or {})}, capture_output=True, text=True)

    def test_silent_in_a_project_with_no_tracker(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        done = self.hook(elsewhere)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_the_opener_in_a_tracked_project(self):
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))
        done = self.hook(self.project)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Launch: strict 36% (4/11), weighted 63%", done.stdout)

    def test_the_directory_comes_from_the_payload(self):
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        done = self.hook(elsewhere, payload={"cwd": str(self.project)})
        self.assertIn("Launch: strict", done.stdout)

    def test_a_broken_plan_is_one_line_and_never_stops_the_session(self):
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))
        self.plan_path.write_text("{")
        done = self.hook(self.project)
        self.assertEqual(done.returncode, 0)
        self.assertIn("gitdone: the plan", done.stdout)
        self.assertEqual(done.stderr, "")

    def test_a_stale_view_is_said(self):
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))
        self.view_path.write_text("# old\n")
        self.assertIn("⚠ STATUS.md is out of date", self.hook(self.project).stdout)


class Commands(ProjectCase):
    def test_commands_find_the_plan_from_the_directory(self):
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))
        done = subprocess.run([sys.executable, str(ENGINE), "where"], cwd=str(self.project),
                              env={**os.environ, "HOME": str(self.tmp / "home")}, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(str(self.plan_path), done.stdout)

    def test_no_plan_is_a_clear_error(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        done = subprocess.run([sys.executable, str(ENGINE), "opener"], cwd=str(elsewhere),
                              env={**os.environ, "HOME": str(self.tmp / "home"), "GITDONE_PACKS": str(self.tmp / "no")},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn(POINTER, done.stderr)


if __name__ == "__main__":
    unittest.main()
