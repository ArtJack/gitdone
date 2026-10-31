"""A plan that names a badge keeps it with the view: written together, and held to the table by the gate and the hook."""
import json
import subprocess
import unittest

from helpers import IDENTITY, ProjectCase, clean_env, git
from gitdone import scaffold


class Synced(ProjectCase):
    def setUp(self):
        super().setUp()
        data = json.loads(self.plan_path.read_text())
        data["badge"] = "img/badge.svg"
        self.plan_path.write_text(json.dumps(data))
        self.badge = self.project / "img" / "badge.svg"
        self.cli("render", "--write")

    def test_render_writes_it(self):
        self.assertIn("25% strict", self.badge.read_text())

    def test_shipped_keeps_it_true(self):
        code, _, err = self.cli("shipped", "11", f"`{self.sha_main[:7]}`", "--offline")
        self.assertEqual(code, 0, err)
        self.assertIn("31% strict", self.badge.read_text())
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_mark_keeps_it_true(self):
        self.cli("mark", "11", "partial", "the", "form", "exists")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_a_stale_badge_fails_the_gate(self):
        self.badge.write_text("<svg/>")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("badge: badge.svg says something else than the table", out)

    def test_a_missing_badge_fails_the_gate(self):
        self.badge.unlink()
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("badge: badge.svg does not exist", out)

    def test_it_cannot_be_the_view(self):
        data = json.loads(self.plan_path.read_text())
        data["badge"] = "STATUS.md"
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("render")
        self.assertEqual(code, 2)
        self.assertIn("cannot be the same file", err)


class TheHook(ProjectCase):
    def setUp(self):
        super().setUp()
        data = json.loads(self.plan_path.read_text())
        data["badge"] = "badge.svg"
        self.plan_path.write_text(json.dumps(data))
        self.cli("render", "--write")
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        self.cli("render", "--write")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook")

    def commit(self, *paths):
        git(self.project, "add", *paths)
        return subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "x"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)

    def test_a_table_staged_without_its_badge_is_refused(self):
        self.cli("mark", "11", "partial", "words")
        done = self.commit("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("says something else than the table", done.stderr)

    def test_all_of_it_together_passes(self):
        self.cli("mark", "11", "partial", "words")
        done = self.commit("status-table.md", "STATUS.md", "badge.svg")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_commit_touching_only_the_badge_is_judged(self):
        (self.project / "badge.svg").write_text("<svg/>")
        done = self.commit("badge.svg")
        self.assertNotEqual(done.returncode, 0)


class Footer(ProjectCase):
    def test_a_plan_with_no_footer_renders_as_before(self):
        self.assertNotIn("---\n\nTracked", self.view_path.read_text())

    def test_a_footer_ends_the_view(self):
        self.change_plan(footer="Words at the end.")
        self.assertTrue(self.view_path.read_text().endswith("---\n\nWords at the end.\n"))

    def test_a_new_tracker_gets_one_it_can_delete(self):
        data = scaffold.plan_data("x", True, "main")
        self.assertIn("github.com/ArtJack/gitdone", data["footer"])


class CheapAtAnySize(ProjectCase):
    """Settling a table's claims costs a few git processes, not a few per row."""

    def count_git(self, rows):
        from unittest import mock
        from gitdone import gitio
        for number in rows:
            self.set_row(number, "Live", f"`{self.sha_main[:7]}`")
        real, calls = gitio._run, []

        def counting(args, **kwargs):
            calls.append(args)
            return real(args, **kwargs)
        with mock.patch.object(gitio, "_run", counting):
            self.assertEqual(self.cli("check", "--offline")[0], 0)
        return len(calls)

    def test_ten_more_claims_start_no_more_processes(self):
        small = self.count_git([])
        large = self.count_git([3, 4, 6, 7, 9, 10, 11, 15, 16])
        self.assertLessEqual(large, small)
        self.assertLess(large, 12)


if __name__ == "__main__":
    unittest.main()
