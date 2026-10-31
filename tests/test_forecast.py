"""`eta`: a line through the table's history. A date moves with the scope, and a test here can fail for each thing the words promise."""
import datetime
import json
import math
import pathlib
import random
import shutil
import unittest

from helpers import ProjectCase, git

from gitdone import chart, forecast
from gitdone.plan import Plan, PlanError

TODAY = datetime.date(2026, 3, 1)


def table_text(rows):
    lines = ["# Project", "", f"### 1. All ({len(rows)})", "", "| # | Capability | Status | Note |", "|---|---|---|---|"]
    for num, (name, kind) in sorted(rows.items()):
        note = "started" if kind == "Partial" else ""
        lines.append(f"| {num} | {name} | {kind} | {note} |")
    return "\n".join(lines) + "\n"


class HistoryCase(unittest.TestCase):
    """A repository whose table is written commit by commit, on dates a test chooses."""

    plan_keys = {}

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name).resolve() / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.rows = {n: (f"Thing {n}", "Not built") for n in range(1, 11)}
        self.plan_path = self.repo / ".gitdone.json"
        self.write_plan(**self.plan_keys)

    def write_plan(self, **keys):
        data = {"status_doc": "status-table.md", "repo": ".", "default_branch": "main", **keys}
        self.plan_path.write_text(json.dumps(data))

    def plan(self):
        return Plan(self.plan_path)

    def commit(self, day, message="change"):
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        git(self.repo, "add", "-A")
        stamp = f"{day}T12:00:00"
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message, env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        return git(self.repo, "rev-parse", "HEAD")

    def move(self, num, kind, day):
        self.rows[num] = (self.rows[num][0], kind)
        return self.commit(day)

    def steady(self, count=4):
        """A table born on Feb 1, with a row reaching Partial every few days."""
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20", "2026-02-25")[:count], start=1):
            self.move(i, "Partial", day)

    def data(self, **kwargs):
        return forecast.data(self.plan(), today=TODAY, **kwargs)


class TheLine(HistoryCase):
    def test_a_new_table_has_no_date_and_says_how_much_it_needs(self):
        self.commit("2026-02-28", "first")
        found = self.data()
        self.assertEqual(found["state"], "too_little")
        self.assertIsNone(found["likely"])
        self.assertIn("a line needs 3", forecast.headline(found))

    def test_a_table_with_no_commit_has_no_date_either(self):
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        found = self.data()
        self.assertEqual(found["state"], "too_little")
        self.assertIsNone(found["last_change"])

    def test_two_days_of_movement_are_not_enough(self):
        self.steady(2)
        self.assertEqual(self.data()["state"], "too_little")

    def test_three_days_of_movement_draw_a_line(self):
        self.steady(3)
        found = self.data()
        self.assertEqual(found["state"], "dated")
        self.assertEqual(found["moving_days"], 3)

    def test_the_date_is_what_is_left_over_the_pace(self):
        self.steady(4)
        found = self.data()
        # 28 days, in which 4 rows gained 0.4 each.
        self.assertEqual(found["window_days"], 28)
        self.assertEqual(found["left"], 8.4)
        self.assertAlmostEqual(found["pace_per_day"], round(1.6 / 28, 3))
        expected = TODAY + datetime.timedelta(days=math.ceil(8.4 / (1.6 / 28)))
        self.assertEqual(found["likely"], expected.isoformat())
        self.assertGreater(found["sure"], found["likely"])

    def test_the_words_call_it_a_line(self):
        self.steady(4)
        words = forecast.headline(self.data())
        self.assertIn("not a promise", words)
        self.assertIn("85% sure", words)

    def test_the_same_history_gives_the_same_answer(self):
        self.steady(4)
        self.assertEqual(self.data(), self.data())

    def test_a_row_at_done_counts_its_whole_weight(self):
        self.steady(3)
        self.move(9, "Live", "2026-02-26")
        found = self.data()
        self.assertAlmostEqual(found["left"], 10 - 3 * 0.4 - 1)

    def test_every_row_done_needs_no_date(self):
        self.rows = {1: ("One", "Live")}
        self.commit("2026-02-01")
        found = self.data()
        self.assertEqual(found["state"], "done")
        self.assertIsNone(found["likely"])
        self.assertIn("Nothing left", forecast.headline(found))

    def test_nothing_moved_in_the_window_is_stalled_and_says_when_it_last_did(self):
        self.commit("2025-06-01", "first")
        self.move(1, "Partial", "2025-06-02")
        found = self.data()
        self.assertEqual(found["state"], "stalled")
        self.assertEqual(found["last_change"], "2025-06-02")
        self.assertIn("nothing moved a row in the last 28 days", forecast.headline(found))

    def test_a_table_that_went_backwards_as_fast_as_forwards_has_no_date(self):
        self.commit("2026-02-01", "first")
        for day, kind in (("2026-02-05", "Partial"), ("2026-02-10", "Not built"), ("2026-02-15", "Partial"), ("2026-02-20", "Not built")):
            self.move(1, kind, day)
        self.assertEqual(self.data()["state"], "stalled")

    def test_a_far_date_is_said_as_far_and_gives_no_day(self):
        self.rows = {n: (f"Thing {n}", "Not built") for n in range(1, 100000)}
        self.commit("2026-02-01", "first")
        for i, day in enumerate(("2026-02-05", "2026-02-10", "2026-02-15"), start=1):
            self.move(i, "Partial", day)
        found = self.data()
        self.assertTrue(found["too_far"])
        self.assertIsNone(found["likely"])
        self.assertIn("more than ten years", forecast.headline(found))

    def test_a_day_with_most_of_the_movement_is_said(self):
        self.commit("2026-02-01", "first")
        self.move(1, "Partial", "2026-02-05")
        self.move(2, "Partial", "2026-02-10")
        for n in range(3, 11):
            self.rows[n] = (self.rows[n][0], "Partial")
        self.commit("2026-02-15")
        found = self.data()
        self.assertGreater(found["largest_day_share"], 0.5)
        self.assertIn("read the date loosely", forecast.text(found))

    def test_a_commit_dated_tomorrow_counts_today(self):
        self.commit("2026-02-01", "first")
        self.move(1, "Partial", "2026-02-05")
        self.move(2, "Partial", "2026-02-10")
        self.move(3, "Partial", "2026-03-09")
        self.assertEqual(self.data()["moving_days"], 3)

    def test_a_window_too_small_is_refused(self):
        self.commit("2026-02-01")
        with self.assertRaises(PlanError):
            self.data(days=0)

    def test_a_status_the_plan_no_longer_has_is_not_progress(self):
        """A kind renamed in the plan must not read as every row jumping forward on the day of the rename."""
        self.rows = {n: (f"Thing {n}", "Started") for n in range(1, 6)}
        self.write_plan(kinds=[{"name": "Live", "weight": 1, "evidence": "release"}, {"name": "Started", "weight": 0.4, "evidence": None}, {"name": "Not built", "weight": 0}])
        self.commit("2026-02-01", "first")
        self.write_plan(kinds=[{"name": "Live", "weight": 1, "evidence": "release"}, {"name": "Begun", "weight": 0.4, "evidence": None}, {"name": "Not built", "weight": 0}])
        self.rows = {n: (f"Thing {n}", "Begun") for n in range(1, 6)}
        self.commit("2026-02-10")
        self.assertEqual(self.data()["moving_days"], 0)

    def test_a_table_outside_any_repository_cannot_run_rather_than_answering(self):
        shutil.rmtree(self.repo / ".git")
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        with self.assertRaises(PlanError):
            self.data()


class TheFormula(unittest.TestCase):
    def test_no_spread_is_plain_division(self):
        self.assertAlmostEqual(forecast.days_for(10, [1.0, 1.0, 1.0]), 10.0)

    def test_it_never_arrives_at_no_pace(self):
        self.assertIsNone(forecast.days_for(10, [0.0, 0.0]))
        self.assertIsNone(forecast.days_for(10, [1.0, -2.0]))

    def test_the_sure_date_is_later_the_lumpier_the_pace(self):
        steady = forecast.days_for(10, [1.0, 1.0, 1.0, 1.0], forecast.SURE)
        lumpy = forecast.days_for(10, [4.0, 0.0, 0.0, 0.0], forecast.SURE)
        self.assertLess(steady, lumpy)

    def test_it_agrees_with_resampling_the_days(self):
        """The closed form takes a sum of days as normal. Drawing the same days at random, many times, must land close to it."""
        series = [0.0, 0.8, 0.0, 0.0, 0.4, 1.0, 0.0, 0.0, 0.4, 0.0, 0.8, 0.0, 0.0, 1.0]
        left = 25.0
        rng = random.Random(7)
        runs = []
        for _ in range(4000):
            remaining, days = left, 0
            while remaining > 0:
                remaining -= rng.choice(series)
                days += 1
            runs.append(days)
        runs.sort()
        self.assertAlmostEqual(forecast.days_for(left, series) / runs[len(runs) // 2], 1.0, delta=0.05)
        self.assertAlmostEqual(forecast.days_for(left, series, forecast.SURE) / runs[int(len(runs) * 0.85)], 1.0, delta=0.05)


class Scope(HistoryCase):
    def test_a_row_added_moves_the_date_out(self):
        self.steady(4)
        before = self.data()["likely"]
        self.rows[11] = ("New", "Not built")
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        self.assertGreater(self.data()["likely"], before)

    def test_a_row_dropped_moves_the_date_in(self):
        self.steady(4)
        before = self.data()["likely"]
        del self.rows[10]
        (self.repo / "status-table.md").write_text(table_text(self.rows))
        self.assertLess(self.data()["likely"], before)

    def test_a_row_added_is_not_pace(self):
        self.commit("2026-02-01", "first")
        for n, day in zip(range(11, 15), ("2026-02-05", "2026-02-10", "2026-02-15", "2026-02-20")):
            self.rows[n] = (f"Thing {n}", "Partial")
            self.commit(day)
        found = self.data()
        self.assertEqual(found["moving_days"], 0)
        self.assertEqual(found["scope"]["added"], 4)

    def test_a_row_taken_out_is_not_pace(self):
        self.commit("2026-02-01", "first")
        for n, day in zip((10, 9, 8), ("2026-02-05", "2026-02-10", "2026-02-15")):
            del self.rows[n]
            self.commit(day)
        found = self.data()
        self.assertEqual(found["moving_days"], 0)
        self.assertEqual(found["scope"]["removed"], 3)

    def test_scope_growing_as_fast_as_the_work_is_said_to_never_catch_up(self):
        self.steady(4)
        for n, day in zip(range(11, 15), ("2026-02-06", "2026-02-11", "2026-02-16", "2026-02-21")):
            self.rows[n] = (f"Thing {n}", "Not built")
            self.commit(day)
        found = self.data()
        self.assertTrue(found["scope"]["never_catches_up"])
        self.assertIn("never catches up", forecast.text(found))

    def test_scope_growing_slowly_gives_a_later_date(self):
        self.steady(5)
        for n in range(1, 6):
            self.rows[n] = (self.rows[n][0], "Live")
        self.commit("2026-02-26")
        for n, day in zip((11, 12), ("2026-02-07", "2026-02-27")):
            self.rows[n] = (f"Thing {n}", "Not built")
        self.commit("2026-02-27")
        self.rows[13] = ("Thing 13", "Not built")
        self.commit("2026-02-28")
        found = self.data()
        grown = found["scope"]["if_it_goes_on"]
        self.assertIsNotNone(grown)
        self.assertGreater(grown["likely"], found["likely"])

    def test_scope_that_grew_once_is_an_event_and_is_not_extrapolated(self):
        self.steady(4)
        for n in range(11, 41):
            self.rows[n] = (f"Thing {n}", "Not built")
        self.commit("2026-02-26")
        found = self.data()
        self.assertEqual(found["scope"]["added"], 30)
        self.assertIsNone(found["scope"]["if_it_goes_on"])
        self.assertFalse(found["scope"]["never_catches_up"])


class Deadline(HistoryCase):
    plan_keys = {"deadline": "2026-04-01"}

    def test_it_says_how_late_at_the_likely_date(self):
        self.steady(4)
        found = self.data()
        late = (datetime.date.fromisoformat(found["likely"]) - datetime.date(2026, 4, 1)).days
        self.assertEqual(found["deadline"]["late_by"], late)
        self.assertIn(f"likely {late} days late", forecast.text(found))

    def test_it_says_what_pace_it_needs(self):
        self.steady(4)
        found = self.data()
        self.assertEqual(found["deadline"]["days_left"], 31)
        self.assertEqual(found["deadline"]["needs_per_day"], round(8.4 / 31, 3))
        self.assertIn("It needs 0.27 rows a day from here; the pace is", forecast.text(found))

    def test_with_no_date_yet_it_still_says_the_days_and_the_pace_it_needs(self):
        self.commit("2026-02-28", "first")
        self.assertIn("Deadline Apr 1: 31 days left. It needs 0.32 rows a day from here.", forecast.text(self.data()))

    def test_a_deadline_gone_by_says_so(self):
        self.write_plan(deadline="2026-02-01")
        self.steady(4)
        self.assertIn("passed 28 days ago", forecast.text(self.data()))

    def test_it_burns_work_against_time(self):
        self.steady(4)
        words = forecast.text(self.data())
        self.assertIn("  Work ", words)
        self.assertIn("  Time ", words)
        self.assertEqual(self.data()["deadline"]["start"], "2026-02-01")
        self.assertAlmostEqual(self.data()["deadline"]["time_used"], 28 / 59)

    def test_the_plan_may_name_when_it_started(self):
        self.write_plan(deadline="2026-04-01", start="2026-01-01")
        self.steady(4)
        self.assertEqual(self.data()["deadline"]["start"], "2026-01-01")

    def test_a_malformed_deadline_is_refused_by_the_plan(self):
        for bad in ("next week", "2026-13-01", "20261201", 5):
            self.write_plan(deadline=bad)
            with self.assertRaises(PlanError):
                self.plan()

    def test_a_misspelled_deadline_is_refused(self):
        self.write_plan(deadlin="2026-04-01")
        with self.assertRaisesRegex(PlanError, "deadline"):
            self.plan()


class Workstreams(HistoryCase):
    plan_keys = {"workstreams": [{"id": "P1", "name": "Core", "rows": "1-5"}, {"id": "P2", "name": "Launch", "rows": "6-9"}], "order": ["P1", "P2"]}

    def test_they_finish_in_the_plans_order(self):
        self.steady(4)
        found = self.data()
        first, second, rest = found["workstreams"]
        self.assertEqual((first["id"], second["id"], rest["id"]), ("P1", "P2", None))
        self.assertLess(first["dates"]["likely"], second["dates"]["likely"])
        self.assertLess(second["dates"]["likely"], rest["dates"]["likely"])
        self.assertEqual(rest["dates"]["likely"], found["likely"])

    def test_a_finished_one_says_done(self):
        for n in range(1, 6):
            self.rows[n] = (self.rows[n][0], "Live")
        self.commit("2026-02-01", "first")
        words = forecast.text(self.data())
        self.assertRegex(words, r"P1 Core\s+done")


class Group(HistoryCase):
    plan_keys = {"groups": [{"label": "All", "domains": [1]}]}

    def test_a_group_can_be_asked_about(self):
        self.steady(3)
        self.assertEqual(self.data(group="All")["rows"], 10)

    def test_an_unknown_group_cannot_run(self):
        self.steady(3)
        with self.assertRaises(PlanError):
            self.data(group="Nope")


class Commands(ProjectCase):
    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        days = ("2026-01-01",)
        git(self.project, "commit", "-q", "-m", "first", env={"GIT_AUTHOR_DATE": f"{days[0]}T12:00:00", "GIT_COMMITTER_DATE": f"{days[0]}T12:00:00"})

    def plain_plan(self):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None, release_sha=None)

    def recent(self, offset):
        return (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()

    def commit_on(self, day, message):
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", message, env={"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{day}T12:00:00"})

    def moving(self):
        for offset, row in zip((12, 8, 4), (8, 11, 16)):
            self.set_row(row, "Partial", "started")
            self.commit_on(self.recent(offset), f"row {row}")

    def test_eta_prints_words_and_json(self):
        self.moving()
        code, out, err = self.cli("eta")
        self.assertEqual(code, 0, err)
        self.assertIn("not a promise", out)
        code, out, err = self.cli("eta", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"], "dated")

    def test_eta_with_a_table_outside_git_cannot_run_and_exits_two(self):
        shutil.rmtree(self.project / ".git")
        code, _, err = self.cli("eta")
        self.assertEqual(code, 2)
        self.assertIn("not in a git repository", err)

    def test_add_says_what_it_did_to_the_date(self):
        self.moving()
        self.plain_plan()
        code, out, err = self.cli("add", "A new thing", "--domain", "1")
        self.assertEqual(code, 0, err)
        self.assertIn("That moves the likely date from", out)

    def test_remove_says_what_it_did_to_the_date(self):
        self.moving()
        self.plain_plan()
        code, out, err = self.cli("remove", "16")
        self.assertEqual(code, 0, err)
        self.assertIn("That moves the likely date from", out)

    def test_add_with_no_date_yet_says_nothing_about_one(self):
        self.plain_plan()
        code, out, err = self.cli("add", "A new thing", "--domain", "1")
        self.assertEqual(code, 0, err)
        self.assertNotIn("likely date", out)

    def test_the_opener_says_the_date(self):
        self.moving()
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        self.assertIn("Likely done", out)

    def test_the_opener_as_data_keeps_the_date_apart_from_the_warnings(self):
        self.moving()
        code, out, err = self.cli("opener", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(any(line.startswith("Likely done") for line in data["time"]))
        self.assertFalse(any("Likely done" in line for line in data["warnings"]))

    def test_the_view_does_not_change_with_the_day(self):
        """The gate compares the view byte for byte, so nothing that moves with the calendar goes in it."""
        self.moving()
        text = self.view_path.read_text()
        self.assertNotIn("Likely", text)

    def test_a_deadline_is_a_plans_word_and_the_view_says_it(self):
        data = json.loads(self.plan_path.read_text())
        data["deadline"] = "2027-01-15"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        self.assertIn("**Deadline.** 2027-01-15", self.view_path.read_text())
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 0, err)

    def test_the_burndown_is_the_same_bytes_for_the_same_history(self):
        self.moving()
        plan = self.plan()
        found = forecast.data(plan, today=datetime.date.today())
        items = chart.points(plan)
        one = chart.burndown(items, plan.title, found, forecast.headline(found))
        self.assertEqual(one, chart.burndown(items, plan.title, found, forecast.headline(found)))
        self.assertIn("burn-down", one)
        self.assertIn("not a promise", one)
        self.assertIn("likely", one)

    def test_the_burndown_writes_a_file(self):
        self.moving()
        target = self.tmp / "burndown.svg"
        code, _, err = self.cli("chart", "--burndown", "--out", str(target))
        self.assertEqual(code, 0, err)
        self.assertTrue(target.read_text().startswith("<svg"))

    def test_the_burnup_still_makes_no_forecast(self):
        self.moving()
        target = self.tmp / "burnup.svg"
        code, _, err = self.cli("chart", "--out", str(target))
        self.assertEqual(code, 0, err)
        self.assertIn("No forecast", target.read_text())


class Burndown(unittest.TestCase):
    """The drawing, from numbers."""

    items = [{"date": "2026-02-01", "scope": 10, "strict": 0, "weighted": 0.0}, {"date": "2026-02-10", "scope": 12, "strict": 1, "weighted": 2.0},
             {"date": "2026-02-20", "scope": 12, "strict": 2, "weighted": 4.0}]

    def found(self, **keys):
        base = {"as_of": "2026-03-01", "left": 8.0, "likely": "2026-04-01", "sure": "2026-04-20", "window_days": 28, "deadline": None}
        return {**base, **keys}

    def test_scope_changes_are_marked(self):
        drawn = chart.burndown(self.items, "P", self.found(), "words")
        self.assertIn(">+2<", drawn)

    def test_a_deadline_is_drawn_with_what_it_needs(self):
        found = self.found(deadline={"date": "2026-03-20"})
        drawn = chart.burndown(self.items, "P", found, "words")
        self.assertIn("deadline", drawn)
        self.assertIn("Dotted: what the deadline needs", drawn)

    def test_no_date_says_why_and_draws_no_line(self):
        drawn = chart.burndown(self.items, "P", self.found(likely=None, sure=None), "No date yet: rows moved on 1 day")
        self.assertIn("No date yet", drawn)
        self.assertNotIn("stroke-dasharray=\"6 5\"", drawn)

    def test_a_far_date_does_not_flatten_the_record(self):
        drawn = chart.burndown(self.items, "P", self.found(likely="2036-01-01", sure="2040-01-01"), "words")
        self.assertIn("Jan 1, 2036", drawn)
        self.assertLess(drawn.count("2036"), 3)

    def test_a_title_cannot_write_markup(self):
        drawn = chart.burndown(self.items, "<script>", self.found(), "<b>")
        self.assertNotIn("<script>", drawn)
        self.assertNotIn("<b>", drawn)

    def test_no_history_cannot_be_drawn(self):
        with self.assertRaises(PlanError):
            chart.burndown([], "P", self.found(), "words")


if __name__ == "__main__":
    unittest.main()
