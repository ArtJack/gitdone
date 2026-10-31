"""`--json`: a program reads the same findings a person reads, and the exit codes do not change."""
import json
import os
import re
import subprocess
import sys
import unittest

from helpers import ENGINE, ProjectCase, git


class Check(ProjectCase):
    def data(self, *args):
        code, out, err = self.cli("check", "--json", *args)
        return code, json.loads(out)

    def test_a_clean_table(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        code, data = self.data("--offline")
        self.assertEqual(code, 0)
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["view"], "fresh")
        self.assertIn(data["result"], ("pass", "warnings"))
        self.assertEqual(data["failures"], [])
        self.assertEqual(set(data["evidence"]), {"verified", "unverified", "missing", "contradicted"})

    def test_a_contradiction_names_its_row_and_exits_the_same(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        code, data = self.data("--offline")
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "fail")
        self.assertEqual(data["failures"][0]["rows"], [1])
        self.assertIn("is not on main", data["failures"][0]["text"])

    def test_missing_evidence_lists_the_rows(self):
        code, data = self.data("--offline")
        self.assertEqual(code, 0)
        self.assertEqual(data["result"], "warnings")
        self.assertEqual(data["warnings"][0]["rows"], [9])

    def test_strict_changes_the_exit_code_and_the_result(self):
        code, data = self.data("--offline", "--strict")
        self.assertEqual(code, 3)
        self.assertEqual(data["result"], "fail")
        self.assertTrue(data["strict"])

    def test_a_stale_view(self):
        self.view_path.write_text("# old\n")
        code, data = self.data("--offline")
        self.assertEqual(code, 1)
        self.assertEqual(data["view"], "stale")

    def test_a_repository_that_cannot_be_used(self):
        self.change_plan(default_branch="nope")
        code, data = self.data("--offline")
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "cannot run")
        self.assertIn("has no branch nope", data["error"])

    def test_a_broken_plan_is_still_json(self):
        self.plan_path.write_text("{")
        code, out, _ = self.cli("check", "--json")
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", json.loads(out)["error"])

    def test_it_does_not_go_with_if_staged(self):
        code, out, _ = self.cli("check", "--json", "--if-staged")
        self.assertEqual(code, 2)
        self.assertIn("do not go together", json.loads(out)["error"])

    def test_the_lines_and_the_data_agree(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        _, data = self.data("--offline")
        _, text, _ = self.cli("check", "--offline")
        for failure in data["failures"]:
            self.assertIn(failure["text"], text)


class Opener(ProjectCase):
    def test_it_holds_the_groups_and_the_next_workstream(self):
        code, out, _ = self.cli("opener", "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["groups"][0]["label"], "Launch")
        self.assertEqual(data["groups"][0]["strict_rows"], 4)
        self.assertEqual(data["groups"][0]["rows"], 11)
        self.assertAlmostEqual(data["groups"][0]["strict"], 4 / 11)
        self.assertEqual(data["next"]["id"], "S1")
        self.assertFalse(data["all_workstreams_done"])
        self.assertTrue(data["line"].startswith("Launch: strict 36%"))

    def test_with_no_workstreams_the_next_row_is_the_tables_own(self):
        self.change_plan(workstreams=None, order=None, sections=None, products=None, groups=None, rows_total=None)
        _, out, _ = self.cli("opener", "--json")
        data = json.loads(out)
        self.assertEqual(data["next"]["id"], "row 3")
        self.assertIn("next: row 3 (Reading-list import)", data["line"])

    def test_a_failing_gate_is_a_warning(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        _, out, _ = self.cli("opener", "--json")
        self.assertIn("the gate fails", json.loads(out)["warnings"][0])

    def test_the_bare_command_has_it_too(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        done = subprocess.run([sys.executable, str(ENGINE), "--json"], cwd=str(self.project), capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "HOME": str(self.tmp / "home"), "USERPROFILE": str(self.tmp / "home")})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["next"]["id"], "S1")

    def test_a_stale_view_is_a_warning(self):
        self.view_path.write_text("# old\n")
        _, out, _ = self.cli("opener", "--json")
        self.assertIn("STATUS.md is out of date", json.loads(out)["warnings"][0])

    def test_the_line_is_the_plain_commands_first_line(self):
        _, plain, _ = self.cli("opener")
        _, out, _ = self.cli("opener", "--json")
        self.assertEqual(plain.split("\n")[0], json.loads(out)["line"])


class Where(ProjectCase):
    def test_the_paths(self):
        _, out, _ = self.cli("where", "--json")
        data = json.loads(out)
        self.assertEqual(data["plan"], str(self.plan_path))
        self.assertEqual(data["default_branch"], "main")
        self.assertIsNone(data["verdict"])


class Week(ProjectCase):
    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "first")
        self.base = git(self.project, "rev-parse", "HEAD")

    def test_what_moved(self):
        self.set_row(11, "Partial", "the form exists")
        code, out, err = self.cli("week", "--json", self.base)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["moved"], [{"row": 11, "from": "Not built", "to": "Partial"}])
        self.assertEqual(data["base"], self.base[:7])
        self.assertTrue(data["older_commit_found"])
        self.assertTrue(data["uncommitted_changes"])
        self.assertIn("S3", data["workstreams_moved"])
        self.assertIn("S1", data["workstreams_not_moved"])
        self.assertEqual(data["groups"][0]["label"], "Launch")

    def test_the_words_come_from_the_data(self):
        self.set_row(11, "Partial", "the form exists")
        _, text, _ = self.cli("week", self.base)
        self.assertIn("Moved: 11 Not built→Partial.", text)
        self.assertIn("Workstreams moved: S3", text)


class Doctor(ProjectCase):
    def setUp(self):
        super().setUp()
        self.fake_gh()

    def data(self):
        code, out, err = self.cli("doctor", "--json")
        return code, {i["name"]: i for i in json.loads(out)["items"]}

    def test_a_healthy_tracker(self):
        code, items = self.data()
        self.assertEqual(code, 0)
        self.assertEqual(items["engine"]["state"], "ok")
        self.assertEqual(items["plan"]["state"], "ok")
        self.assertEqual(items["table"]["state"], "ok")
        self.assertEqual(items["repo"]["state"], "ok")
        self.assertEqual(items["view"]["state"], "ok")

    def test_offline_does_not_ask_gh(self):
        self.fake_gh(fail="not logged in")
        code, out, _ = self.cli("doctor", "--json", "--offline")
        self.assertFalse(self.gh_calls.exists())
        items = {i["name"]: i for i in json.loads(out)["items"]}
        self.assertEqual(items["gh"]["state"], "ok")

    def test_a_lenient_hook_is_said(self):
        git(self.project, "init", "-q", "-b", "main")
        self.cli("install-hook", "--lenient")
        _, items = self.data()
        self.assertEqual(items["hook"]["state"], "warn")
        self.assertIn("lenient", items["hook"]["detail"])

    def test_a_missing_hook_is_a_warning_not_a_failure(self):
        git(self.project, "init", "-q", "-b", "main")
        code, items = self.data()
        self.assertEqual(code, 0)
        self.assertEqual(items["hook"]["state"], "warn")
        self.assertIn("install-hook", items["hook"]["detail"])

    def test_an_installed_hook_is_seen(self):
        git(self.project, "init", "-q", "-b", "main")
        self.cli("install-hook")
        _, items = self.data()
        self.assertEqual(items["hook"]["state"], "ok")

    def test_a_hook_whose_engine_moved_is_seen(self):
        git(self.project, "init", "-q", "-b", "main")
        self.cli("install-hook")
        hook = self.project / ".git" / "hooks" / "pre-commit"
        hook.write_text(re.sub(r"^home=.*$", "home=/gone", hook.read_text(), flags=re.M))
        _, items = self.data()
        self.assertEqual(items["hook"]["state"], "warn")
        self.assertIn("moved", items["hook"]["detail"])

    def test_a_stale_view_is_a_failure(self):
        self.view_path.write_text("# old\n")
        code, items = self.data()
        self.assertEqual(code, 1)
        self.assertEqual(items["view"]["state"], "fail")

    def test_a_broken_table_stops_at_the_table(self):
        self.table_path.write_text(self.table_path.read_text().replace("(4)", "(9)", 1))
        code, items = self.data()
        self.assertEqual(code, 1)
        self.assertEqual(items["table"]["state"], "fail")

    def test_a_contradiction_is_a_failure(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        code, items = self.data()
        self.assertEqual(code, 1)
        self.assertEqual(items["evidence"]["state"], "fail")

    def test_gh_is_only_asked_about_when_a_row_names_a_pull_request(self):
        self.fake_gh(fail="not logged in")
        self.set_row(2, "Live", f"`{self.sha_main[:7]}`")
        _, items = self.data()
        self.assertEqual(items["gh"]["state"], "ok")
        self.assertFalse(self.gh_calls.exists())

    def test_a_pull_request_and_no_login_is_a_warning(self):
        self.fake_gh(fail="not logged in")
        _, items = self.data()
        self.assertEqual(items["gh"]["state"], "warn")
        self.assertIn("not logged in", items["gh"]["detail"])

    def test_it_reads_as_lines(self):
        code, out, _ = self.cli("doctor")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^ok   engine    ")


if __name__ == "__main__":
    unittest.main()
