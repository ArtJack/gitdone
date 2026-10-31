"""`init`: from nothing to a tracker the gate accepts, in a real repository."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from helpers import ENGINE, commit, git, needs_sh
from gitdone import scaffold
from gitdone.discover import POINTER, find_plan
from gitdone.plan import Plan


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.dir = self.tmp / "kiosk"
        self.dir.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()

    def run_engine(self, *args, cwd=None, **env):
        return subprocess.run([sys.executable, str(ENGINE), *args], cwd=str(cwd or self.dir), capture_output=True,
                              text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
                              env={**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), **env})

    def repo(self, branch="main"):
        git(self.dir, "init", "-q", "-b", branch)
        return commit(self.dir, "a.txt", "1\n")


class Writing(Case):
    def test_it_writes_three_files_that_the_gate_accepts(self):
        self.repo()
        done = self.run_engine("init", "--rows", "Sign-in, Search, Export")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.dir / POINTER).exists())
        self.assertTrue((self.dir / "status-table.md").exists())
        self.assertTrue((self.dir / "STATUS.md").exists())
        check = self.run_engine("check", "--strict")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("result: PASS", check.stdout)

    def test_the_commands_find_it_from_below(self):
        self.repo()
        self.run_engine("init", "--rows", "A")
        deep = self.dir / "src" / "deep"
        deep.mkdir(parents=True)
        done = self.run_engine("opener", cwd=deep)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("strict 0% (0/1)", done.stdout)

    def test_the_plan_file_is_the_discovered_file(self):
        self.run_engine("init", "--rows", "A")
        self.assertEqual(find_plan(self.dir), self.dir / POINTER)

    def test_the_title_defaults_to_the_folder(self):
        self.run_engine("init", "--rows", "A")
        self.assertEqual(json.loads((self.dir / POINTER).read_text())["title"], "kiosk")

    def test_a_title_can_be_given(self):
        self.run_engine("init", "--rows", "A", "--title", "The Kiosk")
        self.assertTrue((self.dir / "STATUS.md").read_text().startswith("# The Kiosk (generated"))

    def test_several_strings_are_taken_whole(self):
        self.run_engine("init", "--rows", "Sign-in, with cards", "Search")
        plan = Plan(self.dir / POINTER)
        from gitdone import table
        rows = table.load_clean(plan).rows
        self.assertEqual([rows[1].name, rows[2].name], ["Sign-in, with cards", "Search"])

    def test_no_rows_means_placeholders_and_it_says_so(self):
        done = self.run_engine("init")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("First capability", (self.dir / "status-table.md").read_text())
        self.assertIn("replace the placeholder rows", done.stdout)

    def test_a_pipe_in_a_row_name_does_not_break_the_table(self):
        self.run_engine("init", "--rows", "a|b")
        plan = Plan(self.dir / POINTER)
        from gitdone import table
        self.assertEqual(table.load_clean(plan).rows[1].name, "a\\|b")

    def test_at_a_terminal_it_asks(self):
        answers = iter(["Sign-in", "Search", ""])
        with open(os.devnull, "w") as quiet:
            names = scaffold.ask_for_rows(ask=lambda prompt: next(answers), stream=quiet)
        self.assertEqual(names, ["Sign-in", "Search"])


class Refusing(Case):
    def test_an_existing_tracker_is_left_alone(self):
        self.run_engine("init", "--rows", "A")
        before = (self.dir / POINTER).read_text()
        done = self.run_engine("init", "--rows", "B")
        self.assertEqual(done.returncode, 2)
        self.assertIn("already has a tracker", done.stderr)
        self.assertEqual((self.dir / POINTER).read_text(), before)

    def test_someone_elses_status_file_is_left_alone(self):
        (self.dir / "STATUS.md").write_text("mine\n")
        done = self.run_engine("init", "--rows", "A")
        self.assertEqual(done.returncode, 2)
        self.assertIn("--view", done.stderr)
        self.assertEqual((self.dir / "STATUS.md").read_text(), "mine\n")
        self.assertFalse((self.dir / POINTER).exists())

    def test_another_view_name_can_be_chosen(self):
        (self.dir / "STATUS.md").write_text("mine\n")
        done = self.run_engine("init", "--rows", "A", "--view", "PROGRESS.md")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.dir / "PROGRESS.md").exists())
        self.assertEqual((self.dir / "STATUS.md").read_text(), "mine\n")
        self.assertEqual(self.run_engine("check").returncode, 0)

    def test_a_missing_folder_is_a_clear_error(self):
        done = self.run_engine("init", "--rows", "A", "--dir", str(self.tmp / "gone"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("is not a folder", done.stderr)


class TheRepository(Case):
    def test_the_default_branch_is_read_from_the_repository(self):
        self.repo("master")
        self.run_engine("init", "--rows", "A")
        self.assertEqual(json.loads((self.dir / POINTER).read_text())["default_branch"], "master")
        self.assertEqual(self.run_engine("check").returncode, 0)

    def test_a_folder_outside_git_has_no_repo_and_still_works(self):
        done = self.run_engine("init", "--rows", "A")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads((self.dir / POINTER).read_text())["repo"], ".")
        self.assertIn("git init", done.stdout)
        self.assertEqual(self.run_engine("check").returncode, 0)

    def test_a_repository_with_no_commit_yet_can_commit_its_tracker_through_the_gate(self):
        git(self.dir, "init", "-q", "-b", "main")
        done = self.run_engine("init", "--rows", "A", "--hook")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.run_engine("check").returncode, 0)
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "first", env={"HOME": str(self.home)})
        self.assertEqual(git(self.dir, "log", "--format=%s"), "first")

    def test_the_hook_flag_installs_the_gate(self):
        self.repo()
        self.run_engine("init", "--rows", "A", "--hook")
        self.assertIn("gitdone gate", (self.dir / ".git" / "hooks" / "pre-commit").read_text())


class FromAChecklist(Case):
    def write(self, text):
        path = self.dir / "TODO.md"
        path.write_text(text)
        return path.name

    def test_each_heading_is_a_domain_and_each_item_a_row(self):
        sections = scaffold.sections_from_checklist(
            "# Project\n\nintro\n\n## Launch\n- [x] Sign-in\n- [ ] Search\n\nprose\n\n## Later\n* [ ] Export\n1. [X] Numbered\n")
        self.assertEqual([s.name for s in sections], ["Launch", "Later"])
        self.assertEqual([r[0] for r in sections[0].rows], ["Sign-in", "Search"])
        self.assertEqual(sections[0].rows[0][1], "Partial", "checked, and it names no commit")
        self.assertEqual(sections[0].rows[1][1], "Not built")
        self.assertEqual(sections[1].rows[1][1], "Partial")

    def test_items_before_any_heading_go_in_one_domain(self):
        self.assertEqual([s.name for s in scaffold.sections_from_checklist("- [ ] A\n- [ ] B\n")], ["Scope"])

    def test_items_in_a_code_fence_are_not_rows(self):
        sections = scaffold.sections_from_checklist("- [ ] Real\n```\n- [ ] Example\n```\n")
        self.assertEqual([r[0] for s in sections for r in s.rows], ["Real"])

    def test_a_heading_with_no_items_is_not_a_domain(self):
        self.assertEqual([s.name for s in scaffold.sections_from_checklist("## Empty\n\n## Full\n- [ ] A\n")], ["Full"])

    def test_a_checked_item_with_no_evidence_is_not_counted_as_done(self):
        self.repo()
        done = self.run_engine("init", "--from-checklist", self.write("- [x] Sign-in\n- [ ] Search\n"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("strict 0% (0/2)", done.stdout, "the first number printed must already be true")
        self.assertIn("1 checked item names no commit, so it starts as Partial: row 1.", done.stdout)
        self.assertEqual(self.run_engine("check", "--strict").returncode, 0)

    def test_naming_the_commit_then_moves_it(self):
        sha = self.repo()
        self.run_engine("init", "--from-checklist", self.write("- [x] Sign-in\n"))
        done = self.run_engine("shipped", "1", sha[:7])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("strict 100% (1/1)", done.stdout)
        table = (self.dir / "status-table.md").read_text()
        self.assertNotIn("no commit named yet", table)

    def test_the_commit_moves_out_of_a_rows_name(self):
        sha = self.repo()
        self.run_engine("init", "--from-checklist", self.write(f"- [x] Sign-in (`{sha[:7]}`)\n- [x] Search (PR #4)\n"))
        table = (self.dir / "status-table.md").read_text()
        self.assertIn(f"| 1 | Sign-in | Live | `{sha[:7]}` |", table)
        self.assertIn("| 2 | Search | Partial | PR #4 *(Partial: checked off; PR #4:", table, "a pull request nothing can look up starts as Partial")

    def test_a_first_commit_goes_through_a_strict_gate(self):
        self.repo()
        self.run_engine("init", "--from-checklist", self.write("- [x] Sign-in\n- [ ] Search\n"), "--hook")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "track it", env={"HOME": str(self.home)})
        self.assertIn("track it", git(self.dir, "log", "--format=%s"))

    def test_a_checked_item_that_names_its_commit_starts_out_verified(self):
        sha = self.repo()
        self.run_engine("init", "--from-checklist", self.write(f"- [x] Sign-in (`{sha[:7]}`)\n"))
        check = self.run_engine("check", "--strict")
        self.assertEqual(check.returncode, 0, check.stdout)
        self.assertIn("1 verified", check.stdout)

    def test_a_checked_item_naming_a_stray_commit_starts_as_partial_and_says_why(self):
        self.repo()
        git(self.dir, "checkout", "-q", "-b", "side")
        stray = commit(self.dir, "b.txt", "x\n")
        git(self.dir, "checkout", "-q", "main")
        done = self.run_engine("init", "--from-checklist", self.write(f"- [x] Sign-in `{stray[:7]}`\n"))
        self.assertIn(f"row 1 starts as Partial: commit {stray[:7]} is not on main", done.stdout)
        self.assertIn("strict 0%", done.stdout, "so the first number printed is already true")
        self.assertEqual(self.run_engine("check", "--strict").returncode, 0)

    def test_the_first_commit_after_init_is_not_refused_for_what_init_accepted(self):
        self.repo()
        self.run_engine("init", "--from-checklist", self.write("- [x] Export, done in PR #7\n- [ ] Search\n"), "--hook")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "track it", env={"HOME": str(self.home)})
        self.assertIn("track it", git(self.dir, "log", "--format=%s"))

    def test_a_file_with_no_items_is_a_clear_error(self):
        done = self.run_engine("init", "--from-checklist", self.write("# Nothing\n"))
        self.assertEqual(done.returncode, 2)
        self.assertIn("holds no", done.stderr)
        self.assertFalse((self.dir / POINTER).exists())

    def test_a_missing_file_is_a_clear_error(self):
        done = self.run_engine("init", "--from-checklist", "gone.md")
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot read", done.stderr)


class FromIssues(Case):
    def fake_gh(self, issues=None, fail=None):
        needs_sh(self)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        answer = self.tmp / "answer.json"
        answer.write_text(json.dumps(issues or []))
        calls = self.tmp / "calls"
        script = f'#!/bin/sh\necho "$@" >> "{calls}"\n'
        script += f'echo "{fail}" >&2\nexit 1\n' if fail else f'cat "{answer}"\n'
        gh = bin_dir / "gh"
        gh.write_text(script)
        gh.chmod(0o755)
        self.calls = calls
        return {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}

    ISSUES = [
        {"number": 3, "title": "Export", "state": "OPEN", "stateReason": "", "milestone": {"title": "Later"}},
        {"number": 1, "title": "Sign-in", "state": "CLOSED", "stateReason": "COMPLETED", "milestone": {"title": "Launch"},
         "closedByPullRequestsReferences": [{"number": 9}]},
        {"number": 2, "title": "Search", "state": "CLOSED", "stateReason": "COMPLETED", "milestone": {"title": "Launch"}},
        {"number": 4, "title": "Fax support", "state": "CLOSED", "stateReason": "NOT_PLANNED", "milestone": None},
    ]

    def test_a_domain_per_milestone_and_a_row_per_issue(self):
        sections = scaffold.sections_from_issues(self.ISSUES)
        self.assertEqual([s.name for s in sections], ["Launch", "Later"])
        self.assertEqual(sections[0].rows[0], ("Sign-in", "Live", "issue #1, PR #9"))
        self.assertEqual(sections[0].rows[1], ("Search", "Partial", "issue #2 *(Partial: closed; no commit named yet)*"))
        self.assertEqual(sections[1].rows[0], ("Export", "Not built", "issue #3"))

    def test_closed_as_not_planned_is_out_of_scope(self):
        names = [r[0] for s in scaffold.sections_from_issues(self.ISSUES) for r in s.rows]
        self.assertNotIn("Fax support", names)

    def test_the_command_passes_the_label_and_writes_the_table(self):
        self.repo()
        env = self.fake_gh(self.ISSUES)
        done = self.run_engine("init", "--from-issues", "v1", **env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--label v1", self.calls.read_text())
        self.assertIn("| 1 | Sign-in | Partial | issue #1, PR #9 *(Partial: checked off; PR #9:", (self.dir / "status-table.md").read_text())

    def test_gh_failing_is_a_clear_error_and_writes_nothing(self):
        env = self.fake_gh(fail="not logged in")
        done = self.run_engine("init", "--from-issues", **env)
        self.assertEqual(done.returncode, 2)
        self.assertIn("gh could not answer", done.stderr)
        self.assertFalse((self.dir / POINTER).exists())


class TellingAgents(Case):
    def test_it_creates_agents_md(self):
        written = scaffold.install_agents(self.dir)
        self.assertEqual([p.name for p in written], ["AGENTS.md"])
        self.assertIn("gitdone shipped", (self.dir / "AGENTS.md").read_text())

    def test_it_keeps_what_is_there(self):
        (self.dir / "AGENTS.md").write_text("# Ours\n\nRules.\n")
        scaffold.install_agents(self.dir)
        text = (self.dir / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("# Ours\n\nRules.\n\n<!-- gitdone:start -->"))

    def test_a_second_run_changes_nothing(self):
        scaffold.install_agents(self.dir)
        before = (self.dir / "AGENTS.md").read_text()
        self.assertEqual(scaffold.install_agents(self.dir), [])
        self.assertEqual((self.dir / "AGENTS.md").read_text(), before)

    def test_an_old_section_is_replaced_in_place(self):
        (self.dir / "AGENTS.md").write_text("a\n<!-- gitdone:start -->\nold\n<!-- gitdone:end -->\nb\n")
        scaffold.install_agents(self.dir)
        text = (self.dir / "AGENTS.md").read_text()
        self.assertNotIn("old", text)
        self.assertTrue(text.startswith("a\n<!-- gitdone:start -->"))
        self.assertTrue(text.endswith("<!-- gitdone:end -->\nb\n"))

    def test_claude_md_is_written_only_if_the_project_has_one(self):
        (self.dir / "CLAUDE.md").write_text("# Claude\n")
        written = scaffold.install_agents(self.dir)
        self.assertEqual(sorted(p.name for p in written), ["AGENTS.md", "CLAUDE.md"])

    def test_the_flag_and_the_command_both_reach_it(self):
        self.run_engine("init", "--rows", "A", "--agents")
        self.assertTrue((self.dir / "AGENTS.md").exists())
        (self.dir / "AGENTS.md").unlink()
        done = self.run_engine("install-agents")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.dir / "AGENTS.md").exists())


class TheBareCommand(Case):
    def test_it_prints_where_the_project_stands(self):
        self.repo()
        self.run_engine("init", "--rows", "A, B")
        done = self.run_engine()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("strict 0% (0/2)", done.stdout)

    def test_with_no_tracker_it_says_how_to_start(self):
        done = self.run_engine()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("gitdone init", done.stdout)

    def test_status_is_another_word_for_opener(self):
        self.repo()
        self.run_engine("init", "--rows", "A")
        self.assertEqual(self.run_engine("status").stdout, self.run_engine("opener").stdout)


if __name__ == "__main__":
    unittest.main()
