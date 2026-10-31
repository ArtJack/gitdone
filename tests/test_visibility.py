"""`chart`, `badge`, `report` and `portfolio`: the tracker showing itself."""
import json
import unittest
import xml.dom.minidom

from helpers import ProjectCase, delete_tree, git
from gitdone import badge, chart, portfolio, report, scaffold, table as tables
from gitdone.discover import POINTER


class History(ProjectCase):
    """The project folder as a repository, with the table committed on three dates."""

    def setUp(self):
        super().setUp()
        self.change_plan(release=None)
        git(self.project, "init", "-q", "-b", "main")
        self.commit_at("2026-03-01")
        self.set_row(11, "Partial", "the form exists")
        self.commit_at("2026-03-05")
        self.set_row(11, "Live", f"`{self.sha_main[:7]}`")
        self.commit_at("2026-03-09")

    def commit_at(self, date, message="change"):
        stamp = f"{date}T12:00:00"
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", message, env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


class Points(History):
    def points(self, **kwargs):
        return chart.points(self.plan(), **kwargs)

    def test_a_point_per_date_with_the_numbers_of_that_commit(self):
        items = self.points()
        self.assertEqual([p["date"] for p in items], ["2026-03-01", "2026-03-05", "2026-03-09"])
        self.assertEqual([p["scope"] for p in items], [16, 16, 16])
        self.assertEqual([p["strict"] for p in items], [4, 4, 5])
        self.assertLess(items[0]["weighted"], items[1]["weighted"])

    def test_two_commits_in_a_day_count_as_the_days_last_state(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.commit_at("2026-03-09")
        items = self.points()
        self.assertEqual(len(items), 3)
        self.assertEqual(items[-1]["strict"], 6)

    def test_uncommitted_changes_are_a_point_for_today(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        items = self.points(today="2026-04-01")
        self.assertEqual(items[-1]["date"], "2026-04-01")
        self.assertEqual(items[-1]["strict"], 6)

    def test_a_group_counts_only_its_rows(self):
        self.assertEqual(self.points(group="later")[0]["scope"], 5)

    def test_a_renamed_table_keeps_its_history(self):
        git(self.project, "mv", "status-table.md", "table.md")
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = "table.md"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        self.commit_at("2026-03-12")
        items = self.points()
        self.assertEqual([p["date"] for p in items], ["2026-03-01", "2026-03-05", "2026-03-09", "2026-03-12"])

    def test_the_main_line_decides_not_a_side_branch(self):
        git(self.project, "checkout", "-q", "-b", "side")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.commit_at("2026-03-10", "on the side")
        git(self.project, "checkout", "-q", "main")
        self.commit_at_note("2026-03-11")
        stamp = "2026-03-12T12:00:00"
        git(self.project, "merge", "-q", "--no-ff", "--no-verify", "-m", "merge", "side", env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        items = self.points()
        self.assertNotIn("2026-03-10", [p["date"] for p in items])
        self.assertEqual((items[-1]["date"], items[-1]["strict"]), ("2026-03-12", 6))

    def commit_at_note(self, date):
        (self.project / "note.txt").write_text("x\n")
        self.commit_at(date)


class TheFile(History):
    def svg(self):
        return chart.svg(chart.points(self.plan()), "Bramble <Kiosk>")

    def test_it_is_well_formed_and_escapes_the_title(self):
        text = self.svg()
        xml.dom.minidom.parseString(text)
        self.assertIn("Bramble &lt;Kiosk&gt;", text)

    def test_the_same_history_gives_the_same_bytes(self):
        self.assertEqual(self.svg(), self.svg())

    def test_it_says_the_last_numbers_in_words(self):
        text = self.svg()
        self.assertIn("As of 2026-03-09: scope 16 rows", text)
        self.assertIn("strict 31%", text)

    def test_it_has_no_scripts_and_no_outside_references(self):
        text = self.svg()
        self.assertNotIn("<script", text)
        self.assertNotIn("href", text)

    def test_it_makes_no_forecast(self):
        self.assertIn("No forecast", self.svg())

    def test_one_date_is_still_a_chart(self):
        text = chart.svg([{"date": "2026-03-01", "scope": 4, "strict": 1, "weighted": 1.4}], "One")
        xml.dom.minidom.parseString(text)
        self.assertIn("Mar 1, 2026", text)

    def test_an_empty_scope_is_still_a_chart(self):
        xml.dom.minidom.parseString(chart.svg([{"date": "2026-03-01", "scope": 0, "strict": 0, "weighted": 0}], "Empty"))

    def test_lines_that_end_together_get_labels_apart(self):
        placed = chart._spread([100.0, 100.0, 100.0], 0, 300)
        self.assertGreaterEqual(min(abs(placed[i] - placed[j]) for i in range(3) for j in range(3) if i != j), chart.LABEL_GAP)

    def test_labels_stay_inside_the_plot(self):
        placed = chart._spread([300.0, 300.0, 300.0], 0, 300)
        self.assertLessEqual(max(placed), 300)


class TheCommand(History):
    def test_csv(self):
        code, out, _ = self.cli("chart", "--csv")
        self.assertEqual(code, 0)
        self.assertEqual(out.split("\n")[0], "date,scope,strict,weighted")
        self.assertTrue(out.split("\n")[1].startswith("2026-03-01,16,4,"))

    def test_json(self):
        _, out, _ = self.cli("chart", "--json")
        self.assertEqual(json.loads(out)[-1]["strict"], 5)

    def test_it_writes_a_file(self):
        target = self.tmp / "out" / "burnup.svg"
        code, out, _ = self.cli("chart", "--out", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.read_text().startswith("<svg"))

    def test_a_table_outside_git_is_a_clear_error(self):
        delete_tree(self.project / ".git")
        code, _, err = self.cli("chart")
        self.assertEqual(code, 2)
        self.assertIn("no history to chart", err)


class TheWeekFollowsARename(History):
    def test_a_renamed_table_is_compared_with_its_old_self(self):
        base = git(self.project, "rev-parse", "HEAD~1")
        git(self.project, "mv", "status-table.md", "table.md")
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = "table.md"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        self.commit_at("2026-03-12")
        code, out, err = self.cli("week", base)
        self.assertEqual(code, 0, err)
        self.assertIn("Moved: 11 Partial→Live", out)
        code, out, err = self.cli("week", "2026-03-06")
        self.assertEqual(code, 0, err)
        self.assertIn("Moved: 11 Partial→Live", out)


class Badge(ProjectCase):
    def load(self):
        plan = self.plan()
        return plan, tables.load_clean(plan)

    def test_the_words(self):
        plan, table = self.load()
        self.assertEqual(badge.message(plan, table), "25% strict · 46% weighted")

    def test_a_group(self):
        plan, table = self.load()
        self.assertEqual(badge.message(plan, table, group="launch"), "36% strict · 63% weighted")

    def test_the_endpoint_is_what_shields_reads(self):
        code, out, _ = self.cli("badge")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["label"], "done")
        self.assertIn("strict", data["message"])

    def test_the_svg_is_well_formed_and_says_it_in_text(self):
        target = self.tmp / "badge.svg"
        self.cli("badge", "--svg", str(target), "--label", "a<b")
        text = target.read_text()
        xml.dom.minidom.parseString(text)
        self.assertIn('aria-label="a&lt;b: 25% strict · 46% weighted"', text)

    def test_the_color_only_turns_green_at_the_whole_scope(self):
        plan, table = self.load()
        self.assertEqual(badge.color(plan, table), badge.BLUE)
        for row in table.rows.values():
            row.kind = plan.strict_kind.name
        self.assertEqual(badge.color(plan, table), badge.GREEN)

    def test_keep_names_it_in_the_plan_and_writes_it(self):
        code, out, err = self.cli("badge", "--keep")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.plan_path.read_text())["badge"], "status-badge.svg")
        self.assertIn("25% strict", (self.project / "status-badge.svg").read_text())
        self.assertIn("[![status](status-badge.svg)]", out)
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_keep_touches_one_line_of_a_laid_out_plan(self):
        lines = ['{', '  "title": "x",', '  "status_doc": "status-table.md",', '  "kinds": [', '    {"name": "Live", "weight": 1.0, "evidence": "release"},',
                 '    {"name": "Not built", "weight": 0}', '  ]', '}', '']
        path = self.tmp / "laid-out.json"
        path.write_text("\n".join(lines))
        scaffold.keep_badge(path, "b.svg")
        text = path.read_text().split("\n")
        self.assertEqual(text[3], '  "badge": "b.svg",')
        self.assertEqual(text[:3] + text[4:], lines)

    def test_keep_does_not_change_a_badge_already_named(self):
        self.change_plan(badge="mine.svg")
        self.cli("render", "--write")
        self.cli("badge", "--keep")
        self.assertEqual(json.loads(self.plan_path.read_text())["badge"], "mine.svg")

    def test_files_can_be_written_together(self):
        svg, endpoint = self.tmp / "b.svg", self.tmp / "b.json"
        code, _, err = self.cli("badge", "--svg", str(svg), "--endpoint", str(endpoint))
        self.assertEqual(code, 0, err)
        self.assertTrue(svg.exists() and endpoint.exists())


class Report(ProjectCase):
    def text(self, *args):
        code, out, err = self.cli("report", "--offline", *args)
        self.assertEqual(code, 0, err)
        return out

    def test_each_kind_gets_a_section(self):
        text = self.text()
        self.assertIn("## Live: 4 of 16", text)
        self.assertIn("## Partial:", text)

    def test_a_live_row_shows_what_git_says(self):
        subject = git(self.app, "log", "-1", "--format=%s", self.sha_main)
        date = git(self.app, "log", "-1", "--format=%as", self.sha_main)
        text = self.text()
        self.assertIn(f"commit {self.sha_main[:7]} is on main ({date}, {subject})", text)

    def test_a_row_naming_nothing_is_said_in_bold(self):
        self.assertIn("**no evidence named**", self.text())

    def test_a_contradiction_is_shown_not_hidden(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        self.assertIn(f"commit {self.sha_stray[:7]} is not on main", self.text())

    def test_it_says_what_it_cannot_tell(self):
        self.assertIn("What this cannot tell", self.text())

    def test_pull_requests_show_their_title(self):
        self.add_remote()
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main", "title": "Add holds", "mergedAt": "2026-02-02T10:00:00Z"}])
        code, out, _ = self.cli("report")
        self.assertIn("PR #12 is merged into main (2026-02-02, Add holds)", out)

    def test_as_data(self):
        _, out, _ = self.cli("report", "--offline", "--json")
        data = json.loads(out)
        live = [r for r in data if r["kind"] == "Live"]
        self.assertEqual(len(live), 4)
        self.assertEqual(live[0]["claims"][0]["state"], "verified")
        self.assertIn("subject", live[0]["claims"][0]["found"])

    def test_it_writes_a_file(self):
        target = self.tmp / "EVIDENCE.md"
        self.cli("report", "--offline", "--out", str(target))
        self.assertTrue(target.read_text().startswith("# Bramble Kiosk tracker: evidence"))

    def test_the_data_function_names_every_row(self):
        self.assertEqual(len(report.rows_data(self.plan(), offline=True)), 16)


class Portfolio(ProjectCase):
    def setUp(self):
        super().setUp()
        (self.project / POINTER).write_text(json.dumps({"plan": "plan.json"}))

    def entries(self, *roots):
        return portfolio.scan(roots or [self.tmp])

    def test_a_tracked_child_is_found_and_an_untracked_one_is_not(self):
        found = self.entries()
        self.assertEqual([e["project"] for e in found], ["project"])

    def test_the_numbers_cover_the_whole_table(self):
        entry = self.entries()[0]
        self.assertEqual((entry["rows"], entry["strict_rows"]), (16, 4))
        self.assertEqual(entry["next"], "S1")
        self.assertEqual(entry["gate"], "warnings")

    def test_with_no_workstreams_next_is_the_tables_first_open_row(self):
        self.change_plan(workstreams=None, order=None, sections=None, products=None, groups=None, rows_total=None)
        self.assertEqual(self.entries()[0]["next"], "row 3")

    def test_a_project_folder_can_be_named_directly(self):
        self.assertEqual(len(self.entries(self.project)), 1)

    def test_a_broken_tracker_is_a_row_not_a_crash(self):
        self.plan_path.write_text("{")
        entry = self.entries()[0]
        self.assertIn("not valid JSON", entry["error"])
        self.assertIn("cannot run", portfolio.markdown([entry]))

    def test_the_page(self):
        code, out, err = self.cli("portfolio", str(self.tmp), plan=False)
        self.assertEqual(code, 0, err)
        self.assertIn("| project | 16 | 4 (25%) | 46% |", out)
        self.assertIn("S1 Reading lists and renewals", out)

    def test_as_data(self):
        _, out, _ = self.cli("portfolio", str(self.tmp), "--json", plan=False)
        self.assertEqual(json.loads(out)[0]["project"], "project")

    def test_nothing_found_says_so(self):
        empty = self.tmp / "nothing"
        empty.mkdir()
        _, out, _ = self.cli("portfolio", str(empty), plan=False)
        self.assertIn(f"no {POINTER} found", out)


if __name__ == "__main__":
    unittest.main()
