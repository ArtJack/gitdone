"""`ci` and `mcp`: the gate in a pull request, and read-only tools for an agent."""
import ast
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import unittest
from unittest import mock

from helpers import ENGINE, ProjectCase, clean_env, git, needs_sh
from gitdone import ci, gate, mcp, table as tables


class Annotations(ProjectCase):
    def lines(self, strict=False):
        plan = self.plan()
        return ci.annotations(plan, tables.load(plan), gate.report(plan, strict=strict, offline=True), cwd=str(self.project))

    def test_a_contradiction_lands_on_its_rows_line(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        number = tables.load_clean(self.plan()).rows[1].line + 1
        found = [line for line in self.lines() if line.startswith("::error")]
        self.assertTrue(found[0].startswith(f"::error file=status-table.md,line={number},title=gitdone::row 1"))

    def test_missing_evidence_is_a_warning_and_an_error_in_strict(self):
        self.assertTrue(any(line.startswith("::warning") and "names no commit" in line for line in self.lines()))
        self.assertTrue(any(line.startswith("::error") and "names no commit" in line for line in self.lines(strict=True)))

    def test_newlines_and_percent_cannot_break_a_command(self):
        self.assertEqual(ci._escape_data("a%b\nc"), "a%25b%0Ac")
        self.assertEqual(ci._escape_property("a:b,c"), "a%3Ab%2Cc")


class Action(ProjectCase):
    """`ci` as GitHub runs it: an event file, the summary and output files, and `gh` on PATH."""

    def setUp(self):
        super().setUp()
        self.change_plan(release=None, repo="../app")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.base = git(self.project, "rev-parse", "HEAD")
        git(self.project, "checkout", "-q", "-b", "feature")
        self.summary = self.tmp / "summary"
        self.output = self.tmp / "output"
        self.bin = self.tmp / "gh-bin"
        self.bin.mkdir()
        self.calls = self.tmp / "calls"
        self.bodies = self.tmp / "bodies"

    def gh(self, existing="", fail=False):
        needs_sh(self)
        script = f'#!/bin/sh\necho "$@" >> "{self.calls}"\n'
        if fail:
            script += 'echo "HTTP 403: Resource not accessible" >&2\nexit 1\n'
        else:
            script += f'case "$*" in *--paginate*) echo "{existing}" ;; *--input*) cat >> "{self.bodies}" ;; *) echo "[]" ;; esac\n'
        path = self.bin / "gh"
        path.write_text(script)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def run_ci(self, *args, pull_request=True, number=7):
        event = self.tmp / "event.json"
        payload = {"pull_request": {"number": number, "base": {"sha": self.base, "ref": "main"}}} if pull_request else {}
        event.write_text(json.dumps(payload))
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "GITHUB_EVENT_PATH": str(event), "GITHUB_STEP_SUMMARY": str(self.summary),
               "GITHUB_OUTPUT": str(self.output), "GITHUB_REPOSITORY": "someone/kiosk"}
        with mock.patch.dict(os.environ, env):
            return self.cli("ci", *args)

    def outputs(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def touch_tracker(self):
        self.set_row(11, "Partial", "the form exists")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "move a row")

    def test_a_pull_request_that_does_not_touch_the_tracker_is_left_alone(self):
        self.gh()
        (self.project / "note.txt").write_text("x\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "other")
        code, out, _ = self.run_ci()
        self.assertEqual(code, 0)
        self.assertIn("does not touch the tracker", out)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.outputs()["result"], "not touched")

    def test_always_judges_it_anyway(self):
        self.gh()
        (self.project / "note.txt").write_text("x\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", "other")
        code, out, _ = self.run_ci("--always")
        self.assertIn("result:", out)

    def test_a_pull_request_that_touches_it_is_judged_and_commented_on(self):
        self.gh()
        self.touch_tracker()
        code, out, _ = self.run_ci()
        self.assertEqual(code, 0, out)
        self.assertIn("-X POST repos/someone/kiosk/issues/7/comments", self.calls.read_text())
        body = json.loads(self.bodies.read_text())["body"]
        self.assertTrue(body.startswith(ci.MARKER))
        self.assertIn("Moved: 11 Not built→Partial", body)
        self.assertEqual(self.outputs()["result"], "warnings")
        self.assertEqual(self.outputs()["strict"], "25%")
        self.assertIn("gitdone", self.summary.read_text())

    def test_the_comment_is_updated_not_repeated(self):
        self.gh(existing="555")
        self.touch_tracker()
        self.run_ci()
        self.assertIn("-X PATCH repos/someone/kiosk/issues/comments/555", self.calls.read_text())
        self.assertNotIn("-X POST", self.calls.read_text())

    def test_no_comment_when_asked(self):
        self.gh()
        self.touch_tracker()
        self.run_ci("--no-comment")
        calls = self.calls.read_text() if self.calls.exists() else ""
        self.assertNotIn("comments", calls)

    def test_a_token_that_cannot_write_is_a_warning_and_the_gate_still_decides(self):
        self.gh(fail=True)
        self.touch_tracker()
        code, out, _ = self.run_ci()
        self.assertIn("::warning title=gitdone::could not comment", out)
        self.assertIn(code, (0, 1))
        self.assertNotEqual(code, 2)

    def test_a_contradiction_fails_the_job_with_an_annotation(self):
        self.gh()
        self.set_row(11, "Live", f"`{self.sha_stray[:7]}`")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "lie")
        code, out, _ = self.run_ci()
        self.assertEqual(code, 1)
        self.assertIn("::error file=", out)
        self.assertEqual(self.outputs()["result"], "fail")
        self.assertIn("FAIL", json.loads(self.bodies.read_text())["body"])

    def test_a_pull_request_that_changes_the_rules_is_said_out_loud(self):
        self.gh()
        data = json.loads(self.plan_path.read_text())
        data["evidence_pattern"] = "TICKET-[0-9]+"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "let a ticket count as a release")
        _, out, _ = self.run_ci()
        self.assertIn("::warning title=gitdone::this changes the gate's own rules: evidence_pattern", out)
        self.assertIn("changes the gate's own rules", json.loads(self.bodies.read_text())["body"])

    def test_strict_is_passed_through(self):
        self.gh()
        self.touch_tracker()
        code, _, _ = self.run_ci("--strict")
        self.assertEqual(code, 3)

    def test_a_repository_that_cannot_be_used_says_so(self):
        self.gh()
        self.touch_tracker()
        self.change_plan(default_branch="nope")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "x")
        code, out, _ = self.run_ci()
        self.assertEqual(code, 2)
        self.assertIn("::error title=gitdone::", out)

    def test_a_table_new_against_the_base_says_so(self):
        self.gh()
        self.assertIn("is new against", self.fresh_table_summary())

    def fresh_table_summary(self):
        plan = self.plan()
        empty = git(self.project, "hash-object", "-t", "tree", "/dev/null")
        return ci.summary(plan, tables.load(plan), gate.report(plan, offline=True), base=empty, branch="main")


class Publishing(ProjectCase):
    def setUp(self):
        super().setUp()
        self.change_plan(release=None, repo=".")
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], env=clean_env(), check=True)
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "remote", "add", "origin", str(self.remote))
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")

    def branch_file(self, name):
        return subprocess.run(["git", "--git-dir", str(self.remote), "show", f"badges:{name}"], capture_output=True, text=True, env=clean_env())

    def test_the_files_reach_the_branch_and_the_work_tree_is_untouched(self):
        before = git(self.project, "status", "--porcelain")
        words = ci.publish(self.project, "badges", {"badge.svg": "<svg/>\n"}, "status: x")
        self.assertEqual(words, "published to badges")
        self.assertEqual(self.branch_file("badge.svg").stdout, "<svg/>\n")
        self.assertEqual(git(self.project, "status", "--porcelain"), before)

    def test_a_second_run_with_the_same_files_makes_no_commit(self):
        ci.publish(self.project, "badges", {"badge.svg": "<svg/>\n"}, "one")
        self.assertIn("already holds", ci.publish(self.project, "badges", {"badge.svg": "<svg/>\n"}, "two"))

    def test_a_change_adds_a_commit_on_the_old_one(self):
        ci.publish(self.project, "badges", {"badge.svg": "one\n"}, "one")
        ci.publish(self.project, "badges", {"badge.svg": "two\n"}, "two")
        log = subprocess.run(["git", "--git-dir", str(self.remote), "log", "--format=%s", "badges"], capture_output=True, text=True, env=clean_env())
        self.assertEqual(log.stdout.split(), ["two", "one"])

    def test_a_push_event_publishes_the_badge_and_the_chart(self):
        event = self.tmp / "event.json"
        event.write_text("{}")
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event)}):
            code, out, err = self.cli("ci", "--publish", "badges", "--no-comment")
        self.assertIn("published to badges", out, err)
        self.assertTrue(self.branch_file("burnup.svg").stdout.startswith("<svg"))
        self.assertIn("schemaVersion", self.branch_file("badge.json").stdout)
        self.assertIn("date,scope", self.branch_file("burnup.csv").stdout)

    def test_a_pull_request_does_not_publish(self):
        event = self.tmp / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 1, "base": {"sha": "HEAD", "ref": "main"}}}))
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event)}):
            code, out, _ = self.cli("ci", "--publish", "badges", "--no-comment", "--always")
        self.assertNotIn("published", out)


class Server(ProjectCase):
    def call(self, name, **arguments):
        answer = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {"project": str(self.plan_path), **arguments}}})
        return answer["result"]

    def data(self, name, **arguments):
        result = self.call(name, **arguments)
        self.assertNotIn("isError", result, result)
        return json.loads(result["content"][0]["text"])

    def test_initialize_answers_the_version_it_was_asked_for(self):
        answer = mcp.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(answer["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(answer["result"]["serverInfo"]["name"], "gitdone")

    def test_an_unknown_version_gets_the_newest(self):
        answer = mcp.handle({"id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(answer["result"]["protocolVersion"], mcp.SUPPORTED[0])

    def test_a_notification_gets_no_answer(self):
        self.assertIsNone(mcp.handle({"method": "notifications/initialized"}))

    def test_an_unknown_method_is_an_error(self):
        self.assertEqual(mcp.handle({"id": 2, "method": "nope"})["error"]["code"], -32601)

    def test_every_tool_is_listed_as_read_only(self):
        tools = mcp.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, set(mcp.HANDLERS))
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_nothing_the_server_reaches_can_write(self):
        """Walk the imports from the server: none of the modules that write a table, a hook or a skill is reachable."""
        package = pathlib.Path(mcp.__file__).parent
        seen, todo = set(), ["mcp"]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            tree = ast.parse((package / f"{name}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    todo += [node.module] if node.module else [a.name for a in node.names if (package / f"{a.name}.py").exists()]
        self.assertFalse(seen & {"shipped", "edit", "scaffold", "install", "ci", "cli"}, seen)

    def test_status(self):
        data = self.data("status")
        self.assertTrue(data["line"].startswith("Launch: strict 36%"))
        self.assertEqual(data["next"]["id"], "S1")

    def test_rows_and_open_rows(self):
        self.assertEqual(len(self.data("rows")), 16)
        self.assertEqual(len(self.data("rows", open=True)), 12)

    def test_evidence(self):
        rows = self.data("evidence", offline=True)
        self.assertEqual(rows[0]["claims"][0]["state"], "verified")

    def test_check(self):
        self.assertEqual(self.data("check", offline=True)["result"], "warnings")

    def test_week(self):
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.assertIn("moved", self.data("week"))

    def test_portfolio(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        answer = mcp.handle({"id": 1, "method": "tools/call", "params": {"name": "portfolio", "arguments": {"folder": str(self.tmp)}}})
        self.assertEqual(json.loads(answer["result"]["content"][0]["text"])[0]["project"], "project")

    def test_a_bad_project_is_a_tool_error_not_a_crash(self):
        answer = mcp.handle({"id": 1, "method": "tools/call", "params": {"name": "status", "arguments": {"project": str(self.tmp / "gone")}}})
        self.assertTrue(answer["result"]["isError"])

    def test_an_unknown_tool_is_a_tool_error(self):
        answer = mcp.handle({"id": 1, "method": "tools/call", "params": {"name": "nope"}})
        self.assertTrue(answer["result"]["isError"])

    def test_a_folder_finds_its_plan(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        answer = mcp.handle({"id": 1, "method": "tools/call", "params": {"name": "status", "arguments": {"project": str(self.project)}}})
        self.assertNotIn("isError", answer["result"])

    def test_the_stream_answers_line_by_line(self):
        stdin = io.StringIO('{"id":1,"method":"ping"}\n\nnot json\n{"method":"notifications/initialized"}\n[]\n')
        stdout = io.StringIO()
        mcp.serve(stdin, stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        self.assertEqual(lines[1]["error"]["code"], -32700)
        self.assertEqual(lines[2]["error"]["code"], -32600)
        self.assertEqual(len(lines), 3)

    def test_it_runs_as_a_process(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "status"}}]
        done = subprocess.run([sys.executable, str(ENGINE), "mcp"], cwd=str(self.project), input="\n".join(json.dumps(m) for m in messages) + "\n",
                              capture_output=True, text=True, encoding="utf-8", env={**os.environ, "HOME": str(self.tmp / "home")})
        self.assertEqual(done.returncode, 0, done.stderr)
        answers = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([a["id"] for a in answers], [1, 2])
        self.assertIn("Launch", answers[1]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
