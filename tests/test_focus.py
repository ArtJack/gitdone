"""`focus` and `next`: where the commits went, and what comes next. A signal that never stops anything, with a reason for every answer."""
import datetime
import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from helpers import ENGINE, ROOT, clean_env, git

from gitdone import focus
from gitdone.plan import Plan, PlanError

TODAY = datetime.date(2026, 3, 1)


class FocusCase(unittest.TestCase):
    plan_keys = {}
    rows = {1: ("Sign-in with a magic link", "Not built"), 2: ("Search across projects", "Partial"), 3: ("Export", "Not built"), 4: ("Billing page", "Live")}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name).resolve() / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.rows = dict(type(self).rows)
        self.plan_path = self.repo / ".gitdone.json"
        self.write_plan(**self.plan_keys)
        self.notes = {2: "index built", 4: "shipped"}
        self.write_table()
        self.commit("the tracker", "2026-01-01")

    def write_plan(self, **keys):
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main", **keys}))

    def write_table(self):
        lines = ["# P", "", f"### 1. All ({len(self.rows)})", "", "| # | Capability | Status | Note |", "|---|---|---|---|"]
        lines += [f"| {n} | {name} | {kind} | {self.notes.get(n, '')} |" for n, (name, kind) in sorted(self.rows.items())]
        (self.repo / "status-table.md").write_text("\n".join(lines) + "\n")

    def plan(self):
        return Plan(self.plan_path)

    def commit(self, message, day="2026-02-25", files=None):
        for name, text in (files or {}).items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(self.repo, "add", "-A")
        stamp = f"{day}T12:00:00"
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message, env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        return git(self.repo, "rev-parse", "HEAD")

    def data(self, **kwargs):
        return focus.data(self.plan(), today=TODAY, **kwargs)

    def judged(self, message, files=None, day="2026-02-25"):
        sha = self.commit(message, day, files or {"src/thing.py": f"{message}\n"})
        found = {c["commit"]: c for c in self.data()["list"]}
        return found[sha[:7]]


class Judging(FocusCase):
    def test_a_commit_that_names_an_open_row_is_on_plan(self):
        for message in ("row 1: first cut", "Add the thing (row 1)", "Row: 1", "ROW #1", "rows 1, 2", "rows 1 and 2", "work on rows 1-2"):
            with self.subTest(message):
                judged = self.judged(message)
                self.assertEqual(judged["class"], focus.ON)
                self.assertIn(1, judged["rows"])
                self.assertEqual(judged["because"], "named in the message")

    def test_a_row_named_in_the_body_counts(self):
        self.assertEqual(self.judged("Do a thing\n\nThis is for row 3.")["rows"], [3])

    def test_a_row_the_table_does_not_have_ties_nothing(self):
        self.assertEqual(self.judged("row 99: the thing")["class"], focus.OFF)

    def test_a_range_that_is_absurd_costs_nothing(self):
        self.assertEqual(self.judged("rows 1-999999999")["rows"], [1, 2, 3, 4])

    def test_rows_of_a_database_do_not_read_as_a_row_without_a_number(self):
        self.assertEqual(self.judged("Lock the rows while writing")["class"], focus.OFF)

    def test_a_commit_a_row_cites_is_on_plan(self):
        sha = self.commit("Build it", files={"src/a.py": "1\n"})
        self.notes[3] = f"`{sha[:7]}`"
        self.rows[3] = ("Export", "Live")
        self.write_table()
        self.commit("Export is live", files={})
        found = {c["commit"]: c for c in self.data()["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.ON)
        self.assertEqual(found[sha[:7]]["because"], "cited as evidence")

    def test_a_pull_request_a_row_cites_ties_its_squash(self):
        self.notes[1] = "PR #41"
        self.write_table()
        judged = self.judged("Magic links arrive (#41)")
        self.assertEqual(judged["rows"], [1])
        self.assertIn("pull request", judged["because"])

    def test_a_commit_that_moved_a_row_is_on_plan(self):
        self.rows[1] = ("Sign-in with a magic link", "Partial")
        self.notes[1] = "started"
        self.write_table()
        judged = self.judged("Some early work", files={"src/z.py": "1\n"})
        self.assertEqual(judged["class"], focus.ON)
        self.assertEqual(judged["rows"], [1])
        self.assertEqual(judged["because"], "it moved the row in the table")

    def test_a_commit_that_adds_its_own_row_is_on_plan(self):
        self.rows[5] = ("Dark mode", "Not built")
        self.write_table()
        judged = self.judged("Dark mode, first cut", files={"src/dark.py": "1\n"})
        self.assertEqual(judged["class"], focus.ON)
        self.assertEqual(judged["rows"], [5])

    def test_only_the_trackers_files_count_for_nothing(self):
        self.rows[3] = ("Export", "Partial")
        self.notes[3] = "x"
        self.write_table()
        sha = self.commit("Move a row", files={"STATUS.md": "x\n"})
        found = self.data()
        self.assertEqual(found["tracker_only"], 1)
        self.assertNotIn(sha[:7], [c["commit"] for c in found["list"] if c["class"] != focus.TRACKER])

    def test_tests_docs_and_project_files_are_upkeep(self):
        for name in ("tests/test_a.py", "src/foo.test.js", "docs/a.md", "README.md", ".github/workflows/ci.yml", "uv.lock", "package-lock.json"):
            with self.subTest(name):
                judged = self.judged(f"Touch {name}", files={name: f"{name}\n"})
                self.assertEqual(judged["class"], focus.UPKEEP)

    def test_a_subject_that_says_upkeep_is_upkeep(self):
        for message in ("fix: a crash", "chore(deps): bump x", "ci: cache", "build: flags", "Revert \"a thing\"", "Bump lodash from 1 to 2"):
            with self.subTest(message):
                self.assertEqual(self.judged(message)["class"], focus.UPKEEP)

    def test_a_refactor_says_nothing_about_upkeep(self):
        self.assertEqual(self.judged("refactor: the logger")["class"], focus.OFF)

    def test_a_new_feature_with_no_row_is_off_plan(self):
        judged = self.judged("feat: dark mode")
        self.assertEqual(judged["class"], focus.OFF)
        self.assertEqual(judged["because"], "it names no row and matches none")

    def test_a_subject_with_a_rows_words_is_unclear_and_says_what_it_looks_like(self):
        judged = self.judged("Search results across all projects")
        self.assertEqual(judged["class"], focus.UNCLEAR)
        self.assertEqual(judged["rows"], [2])
        self.assertEqual(judged["because"], "it looks like row 2, by its words")

    def test_one_shared_word_is_enough_only_when_the_row_has_one(self):
        self.assertEqual(self.judged("Tidy the search box")["class"], focus.OFF)
        self.assertEqual(self.judged("Export to a file")["rows"], [3])

    def test_a_fix_with_an_open_rows_words_is_unclear(self):
        self.assertEqual(self.judged("fix: search across projects misses one")["class"], focus.UNCLEAR)

    def test_the_words_of_a_finished_row_are_polish(self):
        """Billing went Live before this window. A commit on billing now is not advancing anything."""
        self.assertEqual(self.judged("Billing page gets a nicer button")["class"], focus.OFF)

    def test_the_words_of_a_row_that_finished_later_still_count(self):
        sha = self.commit("Export the report", "2026-02-20", {"src/e.py": "1\n"})
        self.rows[3] = ("Export", "Live")
        self.notes[3] = f"`{sha[:7]}`"
        self.write_table()
        self.commit("Export is live", "2026-02-22")
        before = self.commit("Export the numbers too", "2026-02-21", {"src/f.py": "1\n"})
        after = self.commit("Export it faster", "2026-02-25", {"src/g.py": "1\n"})
        found = {c["commit"]: c for c in self.data()["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.ON)
        self.assertEqual(found[before[:7]]["class"], focus.UNCLEAR)  # written while the row was open, and landed a little later
        self.assertEqual(found[after[:7]]["class"], focus.OFF)

    def test_a_mixed_commit_is_judged_by_its_work(self):
        judged = self.judged("Tidy up", files={"src/z.py": "1\n", "tests/test_z.py": "1\n"})
        self.assertEqual(judged["class"], focus.OFF)
        self.assertEqual(judged["area"], "src/z.py")

    def test_where_it_happened(self):
        self.assertEqual(self.judged("Change it", files={"src/logging/a/b.py": "1\n"})["area"], "src/logging")
        self.assertEqual(self.judged("Change it again", files={"tools/x/y.py": "1\n"})["area"], "tools")
        self.assertEqual(self.judged("Change a file", files={"setup.py": "1\n"})["area"], "setup.py")


class Plans(FocusCase):
    plan_keys = {"focus": {"paths": {"3": ["src/export/"], "P1": ["src/auth/*.py"]}, "upkeep": ["ops/*"], "not_upkeep": ["docs/*"]},
                 "workstreams": [{"id": "P1", "name": "Core", "rows": "1-2"}], "order": ["P1"]}

    def test_the_plan_can_tie_files_to_a_row(self):
        judged = self.judged("Change the writer", files={"src/export/w.py": "1\n"})
        self.assertEqual(judged["rows"], [3])
        self.assertEqual(judged["because"], "the plan ties its files to the row")

    def test_the_plan_can_tie_files_to_a_workstream(self):
        self.assertEqual(self.judged("Change the login", files={"src/auth/a.py": "1\n"})["rows"], [1, 2])

    def test_files_tied_to_a_row_count_by_the_lines_that_changed(self):
        judged = self.judged("Mostly elsewhere", files={"src/export/w.py": "1\n", "src/other/a.py": "1\n2\n3\n4\n"})
        self.assertEqual(judged["class"], focus.OFF)

    def test_the_plans_upkeep_adds_to_the_list_and_keeps_the_rest(self):
        self.assertEqual(self.judged("Touch ops", files={"ops/a.py": "1\n"})["class"], focus.UPKEEP)
        self.assertEqual(self.judged("More tests", files={"tests/test_a.py": "1\n"})["class"], focus.UPKEEP)

    def test_a_project_whose_product_is_its_docs_can_say_so(self):
        self.assertEqual(self.judged("Change the docs site", files={"docs/a.html": "1\n"})["class"], focus.OFF)

    def test_a_misspelled_focus_key_is_refused(self):
        self.write_plan(focus={"upkep": ["x"]})
        with self.assertRaisesRegex(PlanError, "upkep"):
            self.plan()

    def test_nonsense_in_the_plan_says_so(self):
        for bad in ({"paths": "x"}, {"paths": {"3": "src"}}, {"upkeep": "docs"}, {"paths": {"not a row": ["x"]}}):
            with self.subTest(bad):
                self.write_plan(focus=bad)
                with self.assertRaises(PlanError):
                    self.data()


class Merges(FocusCase):
    def branch(self, name, *messages):
        git(self.repo, "checkout", "-q", "-b", name)
        for i, message in enumerate(messages):
            self.commit(message, files={f"src/{name}{i}.py": "1\n"})
        git(self.repo, "checkout", "-q", "main")

    def merge(self, name, message):
        stamp = "2026-02-26T12:00:00"
        git(self.repo, "merge", "-q", "--no-ff", "-m", message, name, env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})

    def test_a_merge_tied_to_a_row_brings_its_branch(self):
        self.branch("feature", "Some work", "More work")
        self.merge("feature", "Merge the thing, row 3")
        found = self.data()
        self.assertEqual(found["on_plan"], 2)
        self.assertEqual({tuple(c["rows"]) for c in found["list"] if c["class"] == focus.ON}, {(3,)})

    def test_a_merge_for_a_row_that_had_finished_does_not_make_new_work_on_plan(self):
        self.branch("row-4-polish", "A large rewrite")
        self.merge("row-4-polish", "Merge branch 'row-4-polish'")
        found = self.data()
        self.assertEqual(found["on_plan"], 0)
        self.assertEqual(found["unclear"], 1)

    def test_a_branch_named_for_a_row_ties_it(self):
        self.branch("row-3-export", "Some work")
        self.merge("row-3-export", "Merge branch 'row-3-export'")
        self.assertEqual(self.data()["on_plan"], 1)

    def test_a_merge_is_not_counted_as_a_commit_of_its_own(self):
        self.branch("feature", "Some work")
        self.merge("feature", "Merge the thing")
        self.assertEqual(self.data()["commits"], 1)


class Summing(FocusCase):
    def filled(self):
        self.commit("row 1: a", files={"src/a.py": "1\n"})
        self.commit("row 1: b", files={"src/b.py": "1\n"})
        self.commit("docs: c", files={"docs/c.md": "1\n"})
        self.commit("Refactor the logger", files={"src/logging/d.py": "1\n"})
        self.commit("Try a new build", files={"tools/e.py": "1\n"})
        self.commit("Refactor it again", files={"src/logging/f.py": "1\n"})

    def test_it_counts_and_says_where_the_rest_went(self):
        self.filled()
        found = self.data()
        self.assertEqual((found["commits"], found["on_plan"], found["upkeep"], found["off_plan"]), (6, 2, 1, 3))
        self.assertEqual(found["rows"], [{"row": 1, "commits": 2}])
        self.assertEqual(found["areas"][0], {"area": "src/logging", "lines": 2})

    def test_the_window_is_days(self):
        self.commit("Old thing", "2026-02-01", {"src/old.py": "1\n"})
        self.assertEqual(self.data()["commits"], 0)
        self.assertEqual(self.data(days=60)["commits"], 1)

    def test_a_range_of_revisions_can_be_asked_about(self):
        base = git(self.repo, "rev-parse", "HEAD")
        self.filled()
        found = self.data(revisions=f"{base}..HEAD")
        self.assertEqual(found["commits"], 6)
        self.assertIsNone(found["days"])

    def test_the_words_list_the_commits_that_were_off_plan_and_what_is_next(self):
        self.filled()
        words = focus.text(self.data())
        self.assertRegex(words, r"Off plan\s+3\s+50%")
        self.assertIn("Refactor the logger (1 line, src/logging)", words)
        self.assertIn("Next on the plan: row 1", words)
        self.assertIn("gitdone add", words)

    def test_all_says_why_for_every_commit(self):
        self.filled()
        words = focus.text(self.data(), show_all=True)
        self.assertIn("[on plan: named in the message]", words)
        self.assertIn("[upkeep: tests, docs or project files]", words)

    def test_nothing_off_plan_gives_no_sermon(self):
        self.commit("row 1: a", files={"src/a.py": "1\n"})
        self.assertNotIn("gitdone add", focus.text(self.data()))

    def test_no_commits_says_so(self):
        self.assertIn("no commits", focus.text(self.data()))

    def test_a_long_list_is_cut_and_says_how_to_see_it(self):
        for i in range(12):
            self.commit(f"Unplanned {i}", files={f"tools/{i}.py": "1\n"})
        for i in range(12, 14):
            self.commit(f"Unplanned {i}", files={f"tools/{i}.py": "1\n"})
        self.assertIn("and 2 more: gitdone focus --all", focus.text(self.data()))

    def test_an_empty_repository_has_no_commits(self):
        fresh = self.repo.parent / "fresh"
        fresh.mkdir()
        git(fresh, "init", "-q", "-b", "main")
        (fresh / "status-table.md").write_text((self.repo / "status-table.md").read_text())
        (fresh / ".gitdone.json").write_text(self.plan_path.read_text())
        self.assertEqual(focus.data(Plan(fresh / ".gitdone.json"), today=TODAY)["commits"], 0)

    def test_a_folder_that_is_no_repository_says_so_rather_than_no_commits(self):
        self.write_plan(repo="not-here")
        with self.assertRaisesRegex(PlanError, "not a git repository"):
            self.data()

    def test_the_opener_stays_quiet_until_there_is_something_to_say(self):
        self.commit("row 1: a", day=datetime.date.today().isoformat(), files={"src/a.py": "1\n"})
        self.assertIsNone(focus.opener_line(self.plan()))

    def test_the_opener_says_the_numbers(self):
        today = datetime.date.today().isoformat()
        for i, message in enumerate(("row 1: a", "Refactor", "docs: c")):
            self.commit(message, day=today, files={f"src/x{i}.py" if i < 2 else "docs/c.md": "1\n"})
        self.assertEqual(focus.opener_line(self.plan()), "Focus, last 14 days: 1 of 3 commits on plan, 1 off plan (src/x1.py).")


class Next(FocusCase):
    def test_with_no_workstreams_it_is_the_tables_next_rows(self):
        found = focus.next_data(self.plan())
        self.assertEqual([r["row"] for r in found["rows"]], [1, 2, 3])
        self.assertIsNone(found["workstream"])

    def test_with_workstreams_it_is_the_next_ones_open_rows(self):
        self.write_plan(workstreams=[{"id": "P1", "name": "Later", "rows": "4"}, {"id": "P2", "name": "Core", "rows": "2-3", "needs": "a key"}], order=["P1", "P2"])
        found = focus.next_data(self.plan())
        self.assertEqual(found["workstream"]["id"], "P2")
        self.assertEqual([r["row"] for r in found["rows"]], [2, 3])
        words = focus.next_text(found)
        self.assertIn("Next: P2 (Core). It needs a key.", words)
        self.assertIn("Work on no row is a change of scope", words)

    def test_nothing_open_says_so(self):
        self.rows = {4: ("Billing page", "Live")}
        self.write_table()
        self.assertIn("Nothing is open", focus.next_text(focus.next_data(self.plan())))

    def test_many_open_rows_are_cut_to_a_few(self):
        self.rows = {n: (f"Thing {n}", "Not built") for n in range(1, 30)}
        self.write_table()
        found = focus.next_data(self.plan())
        self.assertEqual(len(found["rows"]), focus.NEXT_ROWS)
        self.assertEqual(found["open_rows"], 29)


class TheHook(FocusCase):
    def run_engine(self, *args):
        return subprocess.run([os.environ.get("PYTHON", "python3"), str(ENGINE), *args], cwd=self.repo, env=clean_env(), capture_output=True, text=True)

    def setUp(self):
        super().setUp()
        done = self.run_engine("render", "--write")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.commit("the view", "2026-01-02")
        done = self.run_engine("install-hook")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("post-commit", done.stdout)

    def commit_for_real(self, message, name="src/hooked.py"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message + "\n")
        git(self.repo, "add", "-A")
        return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-m", message],
                              env=clean_env(), capture_output=True, text=True)

    def test_a_commit_off_plan_is_told_and_goes_through(self):
        done = self.commit_for_real("Rewrite the logger")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("is off plan", done.stdout + done.stderr)
        self.assertIn("Next on the plan: row 1", done.stdout + done.stderr)

    def test_a_commit_on_plan_is_told_nothing(self):
        done = self.commit_for_real("row 1: the link")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("off plan", done.stdout + done.stderr)

    def test_upkeep_is_told_nothing(self):
        done = self.commit_for_real("Words", "docs/a.md")
        self.assertNotIn("off plan", done.stdout + done.stderr)

    def test_a_broken_plan_says_nothing_after_a_commit(self):
        self.plan_path.write_text("{ not json")
        done = self.run_engine("focus", "--last")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_a_folder_with_no_plan_says_nothing_after_a_commit(self):
        self.plan_path.unlink()
        done = self.run_engine("focus", "--last")
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_someones_own_post_commit_keeps_its_place(self):
        hook = self.repo / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\necho mine\n")
        done = self.run_engine("install-hook")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("installed " + str(hook), done.stdout)
        self.assertIn("will not be said", done.stdout)
        self.assertEqual(hook.read_text(), "#!/bin/sh\necho mine\n")

    def test_it_can_be_left_out(self):
        hook = self.repo / ".git" / "hooks" / "post-commit"
        hook.unlink()
        done = self.run_engine("install-hook", "--no-focus")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(hook.exists())

    def test_the_engine_comes_from_no_file_of_the_repository(self):
        """A commit in a stranger's clone must not run the clone's code: the hook starts Python with -I, like the gate's."""
        (self.repo / "gitdone").mkdir()
        (self.repo / "gitdone" / "__init__.py").write_text("raise SystemExit('planted')\n")
        done = self.commit_for_real("Rewrite the logger", "src/third.py")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn("planted", done.stdout + done.stderr)
        self.assertIn("off plan", done.stdout + done.stderr)


class Hostile(FocusCase):
    def test_a_subject_with_escape_sequences_is_data(self):
        self.commit("\x1b[2Jgone", files={"src/a.py": "1\n"})
        done = subprocess.run(["python3", str(ENGINE), "focus", "--json"], cwd=self.repo, env=clean_env(), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_file_name_with_odd_characters_is_read(self):
        name = "src/with space\tand tab.py"
        judged = self.judged("Odd", files={name: "1\n"})
        self.assertEqual(judged["area"], name)

    def test_a_message_with_the_readers_own_separators_is_not_a_crash(self):
        path = self.repo / "a.py"
        path.write_text("1\n")
        git(self.repo, "add", "-A")
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-q", "-F", "-"],
                       input=b"sep \x01 and \x02 here\n", env=clean_env(), check=True)
        self.assertIsInstance(self.data(days=4000)["commits"], int)

    def test_the_word_row_in_many_shapes_costs_nothing(self):
        self.assertEqual(focus.named_rows("row " + "1," * 50000 + "2", {1, 2}), {1, 2})


class Layout(unittest.TestCase):
    def test_the_module_stays_out_of_the_commit_hook(self):
        """The gate's hook runs on every commit, so it must not pay for this."""
        code = (ROOT / "gitdone" / "gate.py").read_text()
        head = code[:code.index("def ")]
        self.assertNotIn("focus", head)
        self.assertNotIn("forecast", head)
        self.assertNotIn("requirements", head)


if __name__ == "__main__":
    unittest.main()
