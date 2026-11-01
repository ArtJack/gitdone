"""The date stays off every screen until a plan or a person asks for it, and the scale is there from the first command."""
import datetime
import json
import unittest

from helpers import ProjectCase, git

from gitdone import chart, ci, doctor, gate, portfolio, render, scaffold, table as tables


class Moving(ProjectCase):
    """The sample project in its own repository, with rows moving over the last two weeks: enough for a line."""

    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        self.commit_on(self.day(20), "first")
        for offset, row in zip((12, 8, 4), (8, 11, 16)):
            self.set_row(row, "Partial", "started")
            self.commit_on(self.day(offset), f"row {row}")

    def day(self, offset):
        return (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()

    def commit_on(self, day, message):
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", message, env={"GIT_AUTHOR_DATE": f"{day}T12:00:00", "GIT_COMMITTER_DATE": f"{day}T12:00:00"})

    def plain(self, **keys):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None, release_sha=None, repo=None, **keys)

    def said_on_a_pull_request(self, base):
        plan = self.plan()
        return ci.summary(plan, tables.load_clean(plan), gate.report(plan, offline=True), base=base, branch="main")


class NobodyAsked(Moving):
    def test_opening_the_project_says_no_date(self):
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        self.assertNotIn("likely", out.lower())

    def test_the_session_opener_says_no_date(self):
        code, out, err = self.cli("opener", "--hook")
        self.assertEqual(code, 0, err)
        self.assertNotIn("likely", out.lower())

    def test_as_data_there_is_no_date(self):
        code, out, err = self.cli("opener", "--json")
        self.assertEqual(code, 0, err)
        self.assertFalse(any("likely" in line.lower() for line in json.loads(out)["time"]))

    def test_changing_the_scope_says_no_date(self):
        self.plain()
        for args in (("add", "A new thing", "--domain", "1"), ("remove", "16")):
            code, out, err = self.cli(*args)
            self.assertEqual(code, 0, err)
            self.assertNotIn("likely", out.lower())

    def test_a_deadline_alone_does_not_turn_it_on(self):
        self.change_plan(deadline="2030-01-01")
        self.write_view()
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        self.assertNotIn("likely", out.lower())
        self.assertIn("**Deadline.** 2030-01-01", self.view_path.read_text())

    def test_doctor_has_no_date(self):
        items, _ = doctor.run(self.plan_path, offline=True)
        self.assertNotIn("date", [item["name"] for item in items])

    def test_the_pull_request_hears_of_the_scope_and_no_date(self):
        base = git(self.project, "rev-parse", "HEAD")
        self.plain()
        code, _, err = self.cli("add", "A new thing", "--domain", "1")
        self.assertEqual(code, 0, err)
        said = self.said_on_a_pull_request(base)
        self.assertIn("**Scope:** this adds rows", said)
        self.assertNotIn("**When:**", said)
        self.assertNotIn("likely", said.lower())

    def test_the_action_publishes_the_scale_and_no_burndown(self):
        plan = self.plan()
        files = ci.badge_files(plan, tables.load_clean(plan))
        self.assertIn("scale.svg", files)
        self.assertNotIn("burndown.svg", files)

    def test_portfolio_has_no_date_column(self):
        page = portfolio.markdown(portfolio.scan([self.tmp]) or [self.entry()])
        self.assertNotIn("Likely done", page)

    def entry(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        return portfolio.scan([self.tmp])[0]

    def test_a_portfolio_row_keeps_its_columns(self):
        page = portfolio.markdown([self.entry(), {"project": "broken", "error": "words"}])
        counts = {line.count("|") for line in page.split("\n") if line.startswith("|")}
        self.assertEqual(len(counts), 1, page)

    def test_the_rules_an_agent_gets_ask_for_no_date(self):
        self.assertNotIn("date", scaffold.AGENTS_SNIPPET.lower().replace("up to date", ""))


class AskedForOnce(Moving):
    def test_eta_answers_and_says_how_to_keep_it_on(self):
        code, out, err = self.cli("eta")
        self.assertEqual(code, 0, err)
        self.assertIn("not a promise", out)
        self.assertIn('"dates": true', out)

    def test_eta_as_data_is_only_the_data(self):
        code, out, err = self.cli("eta", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["state"], "dated")

    def test_the_burndown_draws(self):
        target = self.tmp / "burndown.svg"
        code, _, err = self.cli("chart", "--burndown", "--out", str(target))
        self.assertEqual(code, 0, err)
        self.assertIn("not a promise", target.read_text())

    def test_the_mcp_tool_says_it_is_experimental(self):
        from gitdone import mcp
        tool = next(t for t in mcp.TOOLS if t["name"] == "eta")
        self.assertIn("Experimental", tool["description"])


class ThePlanAsksForIt(Moving):
    def test_it_is_back_where_it_was(self):
        self.change_plan(dates=True)
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        self.assertIn("likely done", out.lower())
        items, _ = doctor.run(self.plan_path, offline=True)
        self.assertIn("date", [item["name"] for item in items])
        plan = self.plan()
        self.assertIn("burndown.svg", ci.badge_files(plan, tables.load_clean(plan)))
        self.assertIn("**When:**", self.said_on_a_pull_request(git(self.project, "rev-parse", "HEAD~1")))

    def test_eta_does_not_repeat_how_to_turn_it_on(self):
        self.change_plan(dates=True)
        code, out, err = self.cli("eta")
        self.assertEqual(code, 0, err)
        self.assertNotIn('"dates": true', out)

    def test_changing_the_scope_says_what_it_did(self):
        self.plain(dates=True)
        code, out, err = self.cli("add", "A new thing", "--domain", "1")
        self.assertEqual(code, 0, err)
        self.assertIn("That moves the likely date", out)

    def test_portfolio_has_the_column(self):
        self.change_plan(dates=True)
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        page = portfolio.markdown(portfolio.scan([self.tmp]))
        self.assertIn("Likely done", page)
        counts = {line.count("|") for line in page.split("\n") if line.startswith("|")}
        self.assertEqual(len(counts), 1, page)

    def test_false_is_the_same_as_saying_nothing(self):
        self.change_plan(dates=False)
        self.assertFalse(self.plan().dates)
        self.assertEqual(self.plan().signal_problems, [])


class AMistakeInTheKey(ProjectCase):
    def test_a_wrong_value_is_said_and_stops_nothing(self):
        for value in ("yes", 1, [], {}):
            self.change_plan(dates=value)
            plan = self.plan()
            self.assertFalse(plan.dates)
            self.assertTrue(any("dates: expected true or false" in words for words in plan.signal_problems), value)
            code, _, err = self.cli("check", "--offline")
            self.assertEqual(code, 0, err)

    def test_null_is_off_and_says_nothing(self):
        self.change_plan(dates=None)
        data = json.loads(self.plan_path.read_text())
        data["dates"] = None
        self.plan_path.write_text(json.dumps(data))
        plan = self.plan()
        self.assertFalse(plan.dates)
        self.assertEqual(plan.signal_problems, [])

    def test_a_misspelling_is_said_and_stops_nothing(self):
        data = json.loads(self.plan_path.read_text())
        data["Dates"] = True
        self.plan_path.write_text(json.dumps(data))
        plan = self.plan()
        self.assertFalse(plan.dates)
        self.assertTrue(any("Did you mean 'dates'" in words for words in plan.signal_problems), plan.signal_problems)

    def test_the_schema_knows_the_key(self):
        from helpers import ROOT
        schema = json.loads((ROOT / "schema" / "plan.schema.json").read_text())
        self.assertEqual(schema["properties"]["dates"]["type"], "boolean")


class TheScaleAtATerminal(ProjectCase):
    def test_opening_the_project_draws_it_under_the_first_line(self):
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("Launch: strict"))
        self.assertRegex(lines[1], r"^  Launch  strict [█░]{16}  36%  weighted [█░]{16}  63%$")
        self.assertRegex(lines[2], r"^  Later   strict [█░]{16}   0%  weighted [█░]{16} +\d+%$")

    def test_one_group_is_one_line(self):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, release=None, release_sha=None)
        code, out, err = self.cli("opener")
        self.assertEqual(code, 0, err)
        self.assertRegex(out.splitlines()[1], r"^  All  strict [█░]{16}  25%  weighted [█░]{16}  46%$")

    def test_a_session_and_a_script_are_spared_it(self):
        for args in (("opener", "--hook"), ("opener", "--json")):
            code, out, err = self.cli(*args)
            self.assertEqual(code, 0, err)
            self.assertNotIn("░", out, args)

    def test_a_long_label_keeps_the_bars_in_line(self):
        data = json.loads(self.plan_path.read_text())
        data["groups"][0]["label"] = "A very long name for a group of domains"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        plan = self.plan()
        lines = render.scale_lines(plan, tables.load_clean(plan))
        self.assertEqual(len({line.index("strict") for line in lines}), 1)
        self.assertLess(len(lines[0]), 90)


class TheScaleAsAPicture(ProjectCase):
    def drawn(self):
        plan = self.plan()
        return chart.scale(plan, tables.load_clean(plan))

    def test_each_group_and_each_domain_has_a_bar(self):
        text = self.drawn()
        for words in ("Launch", "Later", "1. Catalogue search", "5. Accessibility", "36%", "63%"):
            self.assertIn(words, text)

    def test_the_same_table_gives_the_same_bytes(self):
        self.assertEqual(self.drawn(), self.drawn())

    def test_a_group_with_one_domain_has_no_second_bar(self):
        plan = self.plan()
        table = tables.load_clean(plan)
        rows = chart.scale_rows(plan, table)
        self.assertEqual([r["part"] for r in rows], [False, True, True, True, False, True, True])
        data = json.loads(self.plan_path.read_text())
        data["groups"] = [{"id": "launch", "label": "Launch", "domains": "1"}, {"id": "later", "label": "Later", "domains": "2-5"}]
        del data["rows_total"]
        self.plan_path.write_text(json.dumps(data))
        plan = self.plan()
        self.assertEqual([r["label"] for r in chart.scale_rows(plan, table)][:2], ["Launch", "Later"])

    def test_nothing_done_draws_no_bar_and_a_little_done_shows(self):
        plan = self.plan()
        table = tables.load_clean(plan)
        self.assertEqual(chart._scale_bar(50, 8, 0, "strict"), [])
        self.assertIn('width="8.0"', chart._scale_bar(50, 8, 0.001, "strict")[0])
        self.assertTrue(chart.scale(plan, table).startswith("<svg"))

    def test_words_from_a_plan_cannot_become_markup(self):
        data = json.loads(self.plan_path.read_text())
        data["title"] = "<script>alert(1)</script>"
        data["groups"][0]["label"] = "<b>Launch</b>"
        self.plan_path.write_text(json.dumps(data))
        text = self.drawn()
        self.assertNotIn("<script>", text)
        self.assertNotIn("<b>", text)
        self.assertIn("&lt;b&gt;Launch", text)

    def test_a_long_name_is_cut_and_many_parts_stop(self):
        lines = ["# P", ""]
        for n in range(1, 41):
            lines += [f"### {n}. A domain with a very long name that goes on and on past the bar {n} (1)", "", "| # | Name | Status | Note |", "|---|---|---|---|", f"| {n} | Row {n} | Not built |  |", ""]
        self.table_path.write_text("\n".join(lines))
        data = json.loads(self.plan_path.read_text())
        for key in ("groups", "rows_total", "sections", "products", "workstreams", "order"):
            data.pop(key, None)
        self.plan_path.write_text(json.dumps(data))
        plan = self.plan()
        text = chart.scale(plan, tables.parse(self.table_path.read_text(), plan.kinds))
        self.assertIn("…", text)
        self.assertIn("and 11 more", text)


class TheChartCommandDrawsIt(ProjectCase):
    def test_out_writes_the_picture(self):
        target = self.tmp / "scale.svg"
        code, _, err = self.cli("chart", "--scale", "--out", str(target))
        self.assertEqual(code, 0, err)
        self.assertIn("how far along", target.read_text())

    def test_it_needs_no_history(self):
        """The sample's project folder is no repository: the scale is the table today."""
        code, out, err = self.cli("chart", "--scale")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("<svg"))

    def test_as_data_and_as_csv(self):
        code, out, err = self.cli("chart", "--scale", "--json")
        self.assertEqual(code, 0, err)
        first = json.loads(out)[0]
        self.assertEqual((first["label"], first["rows"], first["strict_rows"], first["part"]), ("Launch", 11, 4, False))
        code, out, err = self.cli("chart", "--scale", "--csv")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[0], "label,rows,strict_rows,strict,weighted")
        self.assertTrue(out.splitlines()[1].startswith("Launch,11,4,0.3636,"))

    def test_one_group(self):
        code, out, err = self.cli("chart", "--scale", "--json", "--group", "later")
        self.assertEqual(code, 0, err)
        self.assertEqual([r["label"] for r in json.loads(out)], ["Later", "4. Reporting", "5. Accessibility"])

    def test_a_comma_in_a_name_stays_one_cell(self):
        self.assertEqual(chart._csv_cell('a, "b"'), '"a, ""b"""')

    def test_two_pictures_at_once_is_refused(self):
        code, _, err = self.cli("chart", "--scale", "--burndown")
        self.assertEqual(code, 2)
        self.assertIn("ask for one", err)


class SmallWords(ProjectCase):
    def test_doctor_counts_one_domain(self):
        lines = ["# P", "", "### 1. All (1)", "", "| # | Name | Status | Note |", "|---|---|---|---|", "| 1 | Row | Not built |  |", ""]
        self.table_path.write_text("\n".join(lines))
        data = json.loads(self.plan_path.read_text())
        for key in ("groups", "rows_total", "sections", "products", "workstreams", "order"):
            data.pop(key, None)
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        items, _ = doctor.run(self.plan_path, offline=True)
        table = next(item for item in items if item["name"] == "table")
        self.assertIn("1 rows in 1 domain", table["detail"] if "detail" in table else str(table))


if __name__ == "__main__":
    unittest.main()
