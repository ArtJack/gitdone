"""What an independent review of the gate reproduced. Each test failed before its fix, on a repository built the way the review built it."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from helpers import ENGINE, ROOT, clean_env, commit, git, needs_sh, not_on_windows
from gitdone import cli, gitio
from gitdone.plan import Plan, PlanError
from gitdone.table import parse
from gitdone.plan import _kind, DEFAULT_KINDS

KINDS = [_kind(k) for k in DEFAULT_KINDS]
HEAD = "| # | Name | Status | Note |\n|---|---|---|---|\n"


class Small(unittest.TestCase):
    """A small repository on main, with a tracker at its root when a test writes one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.repo = self.tmp / "app"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.plan_path = self.repo / ".gitdone.json"

    def c(self, name, message=None):
        return commit(self.repo, f"{name}.txt", f"{name}\n", message or f"add {name}")

    def empty(self, message="empty"):
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def origin(self, name="origin", push=True):
        bare = self.tmp / f"{name}.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(bare))
        git(self.repo, "remote", "add", name, str(bare))
        if push:
            git(self.repo, "push", "-q", name, "main")

    def write_plan(self, **more):
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "title": "T", **more}))

    def table(self, *rows, plan=None, count=None):
        """Rows as `| n | name | status | note |` lines; writes the plan and the view."""
        count = len(rows) if count is None else count
        (self.repo / "status-table.md").write_text(f"### 1. D ({count})\n\n{HEAD}" + "\n".join(rows) + "\n")
        self.write_plan(**(plan or {}))
        self.render()

    def raw_table(self, text, **plan):
        (self.repo / "status-table.md").write_text(text)
        self.write_plan(**plan)
        return self.render()

    def render(self):
        return self.run_cli("render", "--write", "--plan", str(self.plan_path))[0]

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(args))
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue() + err.getvalue()

    def judge(self, *more):
        return self.run_cli("check", "--strict", "--plan", str(self.plan_path), *more)

    def plain(self):
        return self.run_cli("check", "--plan", str(self.plan_path))

    def stub(self, name, answer):
        needs_sh(self)
        folder = self.tmp / "bin"
        folder.mkdir(exist_ok=True)
        data = self.tmp / f"{name}.json"
        data.write_text(json.dumps(answer))
        script = folder / name
        script.write_text(f'#!/bin/sh\ncat "{data}"\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def in_repo(self, *args, **kwargs):
        """The engine as a hook would run it: from the repository, in its own process."""
        env = {**clean_env(), "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
               **kwargs.pop("env", {})}
        return subprocess.run(args, cwd=str(self.repo), env=env, capture_output=True, text=True, **kwargs)

    def commit_all(self, message="change", no_verify=False):
        self.in_repo("git", "add", "-A")
        return self.in_repo("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, *(["--no-verify"] if no_verify else []))

    def install_hook(self):
        done = self.run_cli("install-hook", "--plan", str(self.plan_path))
        self.assertEqual(done[0], 0, done[1])


def merged(number, oid, base="main"):
    return {"number": number, "state": "MERGED", "baseRefName": base, "mergeCommit": {"oid": oid} if oid else None}


class ThePlanStaysOutOfGitsOwnFolder(Small):
    def test_a_view_cannot_replace_a_hook(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan()
        self.render()
        self.install_hook()
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        before = hook.read_text()
        self.write_plan(status_out=".git/hooks/pre-commit", regenerate="'; touch ran; exit 0; #")
        code, out = self.run_cli("render", "--write", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertIn("inside a .git folder", out)
        self.assertEqual(hook.read_text(), before)

    def test_no_way_of_naming_it_gets_there(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        config = (self.repo / ".git" / "config").read_text()
        for name in (".git/config", "sub/../.git/config", ".GIT/config"):
            self.write_plan(status_out=name)
            self.assertEqual(self.render(), 2, name)
            self.assertEqual((self.repo / ".git" / "config").read_text(), config, name)
        for key in ("status_doc", "badge"):
            self.write_plan(**{key: ".git/config"})
            self.assertEqual(self.render(), 2, key)

    def test_a_git_folder_under_another_name_is_refused_too(self):
        repo = self.tmp / "split"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main", f"--separate-git-dir={repo / 'meta'}")
        (repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        plan = repo / ".gitdone.json"
        plan.write_text(json.dumps({"status_doc": "status-table.md", "status_out": "meta/config", "repo": ".", "title": "T"}))
        config = (repo / "meta" / "config").read_text()
        code, out = self.run_cli("render", "--write", "--plan", str(plan))
        self.assertEqual(code, 2, out)
        self.assertIn("git's own folder", out)
        self.assertEqual((repo / "meta" / "config").read_text(), config)


class PullRequestsAnswerToTheCommitRules(Small):
    def setUp(self):
        super().setUp()
        self.origin(push=False)
        self.c("a")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")

    def test_a_pull_request_that_only_edits_the_table_is_no_evidence(self):
        with (self.repo / "status-table.md").open("a") as handle:
            handle.write("\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "only the table (#12)")
        only_table = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "push", "-q", "origin", "main")
        self.stub("gh", [merged(12, only_table)])
        self.stub("glab", {"state": "merged", "target_branch": "main", "merge_commit_sha": only_table})
        self.table("| 1 | x | Live | PR #12 |", "| 2 | y | Live | MR !21 |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn(f"PR #12's commit {only_table[:7]} only changes the tracker itself; if the work is in another commit of it, cite that commit instead of the pull request", out)
        self.assertIn(f"MR !21's commit {only_table[:7]} only changes the tracker itself", out)

    def test_an_empty_one_and_one_with_no_commit_named(self):
        nothing = self.empty("nothing (#13)")
        git(self.repo, "push", "-q", "origin", "main")
        self.stub("gh", [merged(13, nothing), merged(15, None)])
        self.table("| 1 | x | Live | PR #13 |", "| 2 | y | Live | PR #15 |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn(f"PR #13's commit {nothing[:7]} changes no file", out)
        self.assertIn("PR #15 is merged, and the forge names no commit for it", out)

    def test_one_whose_commit_arrived_through_ours_is_no_evidence(self):
        git(self.repo, "checkout", "-qb", "side")
        taken = self.c("feature")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "side", "-m", "take nothing")
        git(self.repo, "push", "-q", "origin", "main")
        self.stub("gh", [merged(14, taken)])
        self.table("| 1 | x | Live | PR #14 |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("a merge that took none of its changes", out)

    def test_a_real_one_still_holds(self):
        landed = self.c("feature", "Add the feature (#16)")
        git(self.repo, "push", "-q", "origin", "main")
        self.stub("gh", [merged(16, landed)])
        self.table("| 1 | x | Live | PR #16 |")
        code, out = self.judge()
        self.assertEqual(code, 0, out)


class AMergeIsACommitToo(Small):
    def test_a_merge_that_changes_nothing_or_only_the_table_is_no_evidence(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "side")
        self.c("b")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "side", "-m", "take nothing")
        ours = git(self.repo, "rev-parse", "HEAD")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        git(self.repo, "checkout", "-qb", "t")
        with (self.repo / "status-table.md").open("a") as handle:
            handle.write("\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "only the table")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "t", "-m", "merge the table edit")
        table_only = git(self.repo, "rev-parse", "HEAD")
        self.table(f"| 1 | x | Live | `{ours}` |", f"| 2 | y | Live | `{table_only}` |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn(f"commit {ours} changes no file", out)
        self.assertIn(f"commit {table_only} only changes the tracker itself", out)

    def test_a_real_merge_holds(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "side")
        self.c("b")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
        merge = git(self.repo, "rev-parse", "HEAD")
        self.table(f"| 1 | x | Live | `{merge}` |")
        self.assertEqual(self.judge()[0], 0)


class NothingHasShippedUntilItIsPushed(Small):
    def test_a_remote_with_nothing_on_it_yet(self):
        self.origin(push=False)
        local = self.c("a", "only on this machine")
        self.table(f"| 1 | x | Live | `{local}` |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("origin/main does not exist here; push it, or fetch", out)
        code, out = self.run_cli("shipped", "1", local, "--plan", str(self.plan_path))
        self.assertEqual(code, 1, out)
        self.assertIn("push it", out)
        git(self.repo, "push", "-q", "origin", "main")
        self.assertEqual(self.judge()[0], 0, "once it is pushed, it counts")

    def test_a_lone_remote_counts_whatever_it_is_called(self):
        self.c("a")
        self.origin("github")
        unpushed = self.c("b", "not pushed")
        pushed = git(self.repo, "rev-parse", "HEAD~1")
        self.table(f"| 1 | x | Live | `{unpushed}` |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("is on your local main and not on github/main; push it", out)
        self.table(f"| 1 | x | Live | `{pushed}` |")
        self.assertEqual(self.judge()[0], 0)

    def test_another_remote_beside_origin_is_still_somebody_elses(self):
        self.c("a")
        self.origin()
        self.origin("fork", push=False)
        extra = self.c("b", "only on the fork")
        git(self.repo, "push", "-q", "fork", "main")
        self.table(f"| 1 | x | Live | `{extra}` |")
        self.assertEqual(self.judge()[0], 3)

    def test_a_built_row_on_a_branch_only_here(self):
        self.c("a")
        self.origin()
        git(self.repo, "branch", "spike")
        self.table("| 1 | x | Not built | |")
        code, out = self.run_cli("mark", "1", "built", "--branch", "spike", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, "it is true here, so it is recorded: " + out)
        self.assertIn("branch spike is only on this machine; push it", out)
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("branch spike is only on this machine; push it", out)
        self.assertEqual(self.plain()[0], 0, "and a lenient hook lets it through")
        git(self.repo, "push", "-q", "origin", "spike")
        self.assertEqual(self.judge()[0], 0)

    def test_a_branch_a_clone_cannot_find_says_to_push_it(self):
        self.c("a")
        self.table("| 1 | x | Built, not live (spike) | |")
        code, out = self.plain()
        self.assertEqual(code, 1, out)
        self.assertIn("not pushed yet? Push it.", out)

    def test_with_no_remote_a_local_branch_and_commit_are_all_there_is(self):
        good = self.c("a")
        git(self.repo, "branch", "spike")
        self.table(f"| 1 | x | Live | `{good}` |", "| 2 | y | Built, not live (spike) | |")
        self.assertEqual(self.judge()[0], 0)


class StrictMeansEveryClaim(Small):
    def test_a_claim_in_name_only_beside_a_good_one_fails(self):
        good = self.c("a")
        nothing = self.empty()
        self.table(f"| 1 | x | Live | `{good}` and `{nothing}` |", f"| 2 | y | Live | `{good}` and PR #999 |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn(f"commit {nothing} changes no file", out)
        self.assertIn("PR #999", out)
        self.assertEqual(self.plain()[0], 0, "a plain check stands on the strongest claim")

    def test_a_plans_own_pattern_beside_a_good_commit_is_only_said(self):
        good = self.c("a")
        self.table(f"| 1 | x | Live | `{good}` TICKET-12 |", plan={"evidence_pattern": "TICKET-\\d+"})
        code, out = self.judge()
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 1: 'TICKET-12' matches", out)

    def test_the_plans_release_is_held_like_a_row(self):
        self.c("a")
        nothing = self.empty()
        self.table("| 1 | x | Not built | |", plan={"release": f"Release `{nothing[:7]}`, tag v9.9, PR #404"})
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn(f"the plan's release: commit {nothing[:7]} changes no file", out)
        self.assertIn("the plan's release: tag v9.9", out)
        self.assertIn("the plan's release: PR #404", out)


class RevertsAreReadTheWayGitWritesThem(Small):
    def gone(self, sha):
        self.table(f"| 1 | x | Live | `{sha}` |")
        code, out = self.judge()
        self.assertEqual(code, 1, out)
        self.assertIn("was reverted on main by", out)
        self.assertIn("what is true now? gitdone mark 1", out, "the failure names the next step")

    def test_git_revert_reference(self):
        feature = self.c("a", "add feature A")
        self.c("b")
        git(self.repo, "revert", "--no-edit", feature)
        short = feature[:7]
        git(self.repo, "commit", "-q", "--amend", "-m", f"Back out feature A\n\nThis reverts commit {short} (add feature A, 2026-10-31).\n")
        self.gone(feature)

    def test_one_line_naming_nothing_does_not_cancel_a_real_revert(self):
        feature = self.c("a", "add feature A")
        self.c("b")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "commit", "-q", "--amend", "-m", f"Drop feature A\n\nThis reverts commit {feature}.\nThis reverts commit {'0123456789abcdef' * 2}01234567.\n")
        self.gone(feature)

    def test_a_squash_that_really_removes_it_and_quotes_a_local_experiment(self):
        feature = self.c("a", "add feature A")
        self.c("b")
        git(self.repo, "checkout", "-qb", "wip")
        experiment = self.c("x", "local experiment")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "commit", "-q", "--amend", "-m", f'Drop feature A and the experiment (#7)\n\n* Revert "add feature A"\n\n    This reverts commit {feature}.\n\n'
                                                        f'* Revert "local experiment"\n\n    This reverts commit {experiment}.\n')
        self.gone(feature)

    def test_a_squash_that_quotes_a_revert_and_its_reapply_and_changes_something_else(self):
        feature = self.c("a", "add feature A")
        lost_id = "0123456789abcdef" * 2 + "01234567"
        self.c("b", f'Other work (#8)\n\n* Revert "add feature A"\n\n    This reverts commit {feature}.\n\n* Reapply\n\n    This reverts commit {lost_id}.\n')
        self.table(f"| 1 | x | Live | `{feature}` |")
        self.assertEqual(self.judge()[0], 0, "the squash left the feature's files alone")

    def test_no_date_can_hide_a_revert_that_stands(self):
        def at(minute):
            stamp = f"2026-01-01T00:{minute:02d}:00Z"
            return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base", env=at(1))
        (self.repo / "a.txt").write_text("feature\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-qm", "add feature A", env=at(2))
        feature = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-qb", "side")
        git(self.repo, "revert", "--no-edit", feature, env=at(3))
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "c.txt").write_text("c\n")
        git(self.repo, "add", "c.txt")
        git(self.repo, "commit", "-qm", "other", env=at(4))
        git(self.repo, "revert", "--no-edit", feature, env=at(5))
        first = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "revert", "--no-edit", first, env=at(6))
        git(self.repo, "merge", "-q", "--no-ff", "side", "-m", "merge side", env=at(7))
        self.assertFalse((self.repo / "a.txt").exists())
        self.gone(feature)

    def test_a_revert_a_merge_threw_away_reverts_nothing(self):
        feature = self.c("a", "add feature A")
        git(self.repo, "checkout", "-qb", "maint")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "maint", "-m", "record maint, keep feature A")
        self.table(f"| 1 | x | Live | `{feature}` |")
        self.assertEqual(self.judge()[0], 0)

    def test_gits_reapply_wording_is_followed_through_a_rebase(self):
        feature = self.c("a", "add feature A")
        git(self.repo, "checkout", "-qb", "work")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "revert", "--no-edit", "HEAD")
        git(self.repo, "commit", "-q", "--amend", "-m", 'Reapply "add feature A"\n\nThis reverts commit ' + git(self.repo, "rev-parse", "HEAD~1") + ".\n")
        git(self.repo, "checkout", "-q", "main")
        self.c("c", "other")
        git(self.repo, "rebase", "-q", "main", "work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--ff-only", "work")
        git(self.repo, "branch", "-qD", "work")
        git(self.repo, "reflog", "expire", "--expire=now", "--all")
        git(self.repo, "gc", "-q", "--prune=now")
        self.table(f"| 1 | x | Live | `{feature}` |")
        code, out = self.judge()
        self.assertEqual(code, 0, out)

    def test_a_tag_named_like_a_short_id_does_not_steer_a_revert(self):
        feature = self.c("a", "add A")
        other = self.c("z", "add Z")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "commit", "-q", "--amend", "-m", f'Revert "add A"\n\nThis reverts commit {feature[:7]}.\n')
        git(self.repo, "tag", feature[:7], other)
        self.table(f"| 1 | x | Live | `{feature}` |", f"| 2 | y | Live | `{other}` |")
        code, out = self.judge()
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {feature} was reverted", out)
        self.assertNotIn(f"commit {other} was reverted", out)

    def test_a_form_feed_in_a_subject_does_not_hide_a_landing_commit(self):
        self.origin(push=False)
        self.c("a")
        landed = self.c("f", "feature\fmore (#30)")
        self.c("o")
        git(self.repo, "rm", "-q", "f.txt")
        git(self.repo, "commit", "-qm", 'Revert "feature" (#31)\n\nReverts me/app#30\n')
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.gone(landed)

    def test_githubs_button_finds_a_rebase_merged_commit_by_its_subject(self):
        self.origin(push=False)
        self.c("a")
        landed = self.c("f", "add the feature")
        self.c("o")
        git(self.repo, "rm", "-q", "f.txt")
        git(self.repo, "commit", "-qm", 'Revert "add the feature" (#31)\n\nReverts me/app#30\n')
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.gone(landed)

    def test_another_projects_merge_request_is_not_ours(self):
        self.origin(push=False)
        feature = self.c("a", "feature")
        self.c("b", "unrelated work\n\nThis reverts merge request other/project!12.\n")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "git@gitlab.com:me/app.git")
        self.stub("glab", {"state": "merged", "target_branch": "main", "merge_commit_sha": feature})
        self.table("| 1 | x | Live | MR !12 |")
        self.assertEqual(self.judge()[0], 0)

    def test_the_same_project_named_in_full_is(self):
        self.origin(push=False)
        feature = self.c("a", "feature")
        self.c("b", "take it out\n\nThis reverts merge request me/app!12.\n")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "git@gitlab.com:me/app.git")
        self.stub("glab", {"state": "merged", "target_branch": "main", "merge_commit_sha": feature})
        self.table("| 1 | x | Live | MR !12 |")
        self.assertEqual(self.judge()[0], 1)

    def test_a_sha256_repository(self):
        repo = self.tmp / "long"
        repo.mkdir()
        try:
            git(repo, "init", "-q", "-b", "main", "--object-format=sha256")
        except AssertionError:
            self.skipTest("this git has no SHA-256")
        self.repo, self.plan_path = repo, repo / ".gitdone.json"
        feature = self.c("a", "add A")
        self.table(f"| 1 | x | Live | `{feature}` |")
        self.assertEqual(self.judge()[0], 0, "a 64-digit id is read as a commit")
        git(repo, "revert", "--no-edit", feature)
        self.gone(feature[:7])


class ItsContentArrived(Small):
    def hollow(self, sha):
        self.table(f"| 1 | x | Live | `{sha}` |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("a merge that took none of its changes", out)

    def feature_branch(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "feature")
        taken = self.c("feature", "the feature")
        git(self.repo, "checkout", "-q", "main")
        return taken

    def test_ours_on_a_side_branch_and_then_a_real_merge(self):
        base = None
        self.c("a")
        base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-qb", "feature")
        taken = self.c("feature", "the feature")
        git(self.repo, "checkout", "-qb", "dev", base)
        self.c("dev")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "feature", "-m", "dev: record feature, take nothing")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "dev", "-m", "merge dev")
        self.assertFalse((self.repo / "feature.txt").exists())
        self.hollow(taken)

    def test_ours_with_one_more_file_touched(self):
        taken = self.feature_branch()
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "--no-commit", "feature")
        (self.repo / "notes.txt").write_text("merged\n")
        git(self.repo, "add", "notes.txt")
        git(self.repo, "commit", "-qm", "merge feature, take nothing of it")
        self.hollow(taken)

    def test_ours_on_upstream_with_origin_behind_it(self):
        self.c("a")
        self.origin()
        self.origin("upstream")
        git(self.repo, "checkout", "-qb", "feature")
        taken = self.c("feature", "the feature")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "feature", "-m", "take nothing")
        git(self.repo, "push", "-q", "upstream", "main")
        self.hollow(taken)

    def test_a_hotfix_cherry_picked_and_merged_back_arrived(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "release")
        fix = self.c("fix", "the fix")
        git(self.repo, "checkout", "-q", "main")
        self.c("y", "main moves on")
        git(self.repo, "cherry-pick", fix)
        git(self.repo, "merge", "-q", "--no-ff", "release", "-m", "merge release back")
        self.table(f"| 1 | x | Live | `{fix}` |")
        code, out = self.judge()
        self.assertEqual(code, 0, out)

    def test_a_commit_in_a_real_merge_arrived(self):
        taken = self.feature_branch()
        self.c("m")
        git(self.repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
        self.table(f"| 1 | x | Live | `{taken}` |")
        self.assertEqual(self.judge()[0], 0)

    def test_side_claims_cost_a_few_processes_however_many(self):
        self.c("a")
        shas = []
        git(self.repo, "checkout", "-qb", "feature")
        for n in range(12):
            shas.append(self.c(f"f{n}"))
        git(self.repo, "checkout", "-q", "main")
        self.c("m")
        git(self.repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")

        def count(rows):
            self.table(*rows)
            calls = []
            real = gitio.git

            def counting(*args, **kwargs):
                calls.append(args)
                return real(*args, **kwargs)
            with mock.patch.object(gitio, "git", counting):
                self.assertEqual(self.judge()[0], 0)
            return len(calls)
        few = count([f"| 1 | x | Live | `{shas[0]}` |"])
        many = count([f"| {n + 1} | x{n} | Live | `{sha}` |" for n, sha in enumerate(shas)])
        self.assertLessEqual(many, few + 1)


class CommitsThatAreTheTracker(Small):
    def test_a_commit_that_only_changes_the_pointer(self):
        self.c("a")
        (self.repo / "plans").mkdir()
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        real = self.repo / "plans" / "a.json"
        real.write_text(json.dumps({"status_doc": "../status-table.md", "status_out": "../STATUS.md", "repo": "..", "title": "T"}))
        self.plan_path.write_text('{"plan": "plans/a.json"}')
        self.run_cli("render", "--write", "--plan", str(real))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        self.plan_path.write_text('{"plan": "./plans/a.json"}')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "only the pointer")
        pointer_only = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n| 1 | x | Live | `{pointer_only}` |\n")
        self.run_cli("render", "--write", "--plan", str(real))
        code, out = self.run_cli("check", "--strict", "--plan", str(real))
        self.assertEqual(code, 3, out)
        self.assertIn("only changes the tracker itself", out)

    def test_from_a_linked_worktree_with_an_absolute_repo(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        with (self.repo / "status-table.md").open("a") as handle:
            handle.write("\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "only the table")
        only_table = git(self.repo, "rev-parse", "HEAD")
        other = self.tmp / "wt"
        git(self.repo, "worktree", "add", "-q", "-b", "wt", str(other))
        (other / "status-table.md").write_text(f"### 1. D (1)\n\n| 1 | x | Live | `{only_table}` |\n")
        plan = other / ".gitdone.json"
        plan.write_text(json.dumps({"status_doc": "status-table.md", "repo": str(self.repo), "title": "T"}))
        self.run_cli("render", "--write", "--plan", str(plan))
        code, out = self.run_cli("check", "--strict", "--plan", str(plan))
        self.assertEqual(code, 3, out)
        self.assertIn("only changes the tracker itself", out)


class RowsAreWhatAReaderSees(unittest.TestCase):
    def read(self, text):
        return parse(text, KINDS)

    def seen(self, text):
        table = self.read(text)
        return bool(table.strays or table.problems)

    def test_inline_code_at_the_start_of_a_line_opens_no_fence(self):
        table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n```inline``` words\n\n| 2 | b | Not built | |\n\n### 2. E (1)\n\n{HEAD}| 3 | c | Not built | |\n")
        self.assertIn(3, table.rows)
        self.assertIn(2, table.rows)

    def test_an_indented_comment_opener_is_a_code_block(self):
        table = self.read(f"### 1. D (2)\n\n{HEAD}| 1 | a | Live | x |\n\n    <!-- example\n\n{HEAD}| 2 | b | Not built | |\n")
        self.assertIn(2, table.rows)

    def test_lines_that_look_like_rows_are_said(self):
        for line in ("| 2x | b | Not built yet | |", "| 2 | b |", "| x | b | live | |", "2 | b | Live | x"):
            table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n{line}\n")
            self.assertTrue(table.strays, line)

    def test_a_row_under_a_heading_that_lost_its_count_is_said(self):
        table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n### 2. Lost\n\n{HEAD}| 4 | d | Not built (soon) | |\n")
        self.assertTrue(table.strays)

    def test_a_table_of_your_own_is_yours(self):
        for text in ("## Statuses\n\n| Status | Meaning |\n|---|---|\n| Live | On the default branch |\n| Partial | Some of it exists |\n",
                     "| Area | Live | Partial |\n|---|---|---|\n| Web | 3 | 2 |\n",
                     "Each row is one of Live | Partial\n",
                     "| # | Step |\n|---|---|\n| 1 | Install |\n"):
            for doc in (f"{text}\n### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n", f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n## Notes\n\n{text}"):
                table = self.read(doc)
                self.assertEqual((table.strays, table.problems), ([], []), doc)

    def test_a_comment_opened_mid_line_hides_its_paragraph(self):
        table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\nwords <!-- hidden\n| 2 | b | Live | x |\n-->\n")
        self.assertEqual(list(table.rows), [1])

    def test_a_comment_mid_line_that_never_closes_in_its_paragraph_is_only_words(self):
        table = self.read(f"### 1. D (2)\n\n{HEAD}| 1 | a | Live | x |\n\nwords <!-- not a comment\n\n{HEAD}| 2 | b | Not built | |\n")
        self.assertEqual(list(table.rows), [1, 2])

    def test_a_fence_closes_only_the_way_markdown_closes_one(self):
        for inner in ("````\n```\n| 2 | b | Live | x |\n````\n", "```\n``` text\n| 2 | b | Live | x |\n```\n", "~~~\n```\n| 2 | b | Live | x |\n~~~\n"):
            table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n{inner}")
            self.assertEqual(list(table.rows), [1], inner)
            self.assertEqual(table.problems, [])

    def test_a_fence_or_comment_that_never_closes_is_a_problem(self):
        self.assertIn("code fence that never closes", self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n~~~\n| 2 | b | Live | x |\n").problems[0])
        self.assertIn("HTML comment that never closes", self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n\n<!--\n| 2 | b | Live | x |\n").problems[0])

    def test_a_merge_conflict_says_so_first(self):
        table = self.read(f"### 1. D (1)\n\n{HEAD}<<<<<<< HEAD\n| 1 | a | Live | x |\n=======\n| 1 | a | Partial | y |\n>>>>>>> side\n")
        self.assertIn("merge conflict marker", table.problems[0])

    def test_a_number_too_long_to_be_one_is_no_row(self):
        table = self.read(f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n| {'9' * 5000} | b | Not built | |\n")
        self.assertEqual(list(table.rows), [1])
        self.assertTrue(table.strays)

    def test_a_line_of_spaces_costs_nothing(self):
        started = time.perf_counter()
        self.read("### 1. D (0)\n\n| a | b | c |\n" + " " * 20000 + "x\n")
        self.assertLess(time.perf_counter() - started, 1)


class Counts(Small):
    def body(self, sha):
        return f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | `{sha}` |\n"

    def test_a_counts_table_in_a_fence_is_an_example(self):
        sha = self.c("a")
        self.raw_table("# T\n\n```\n| # | Domain | All | Live |\n|---|---|---|---|\n| 1 | Example | 9 | 9 |\n```\n\n" + self.body(sha))
        self.assertEqual(self.judge()[0], 0)

    def test_a_right_one_in_a_comment_does_not_hide_a_stale_one_in_sight(self):
        sha = self.c("a")
        self.raw_table(self.body(sha))
        counts = self.run_cli("counts", "--plan", str(self.plan_path))[1].strip()
        (self.repo / "status-table.md").write_text(f"<!--\n{counts}\n-->\n\n" + counts.replace("| 1 | D | 1 | 1 |", "| 1 | D | 7 | 7 |") + "\n\n" + self.body(sha))
        self.render()
        code, out = self.judge()
        self.assertEqual(code, 1, out)
        self.assertIn("disagrees with its rows", out)


class LinksIntoOtherRepositories(Small):
    def setUp(self):
        super().setUp()
        self.origin(push=False)
        self.sha = self.c("a", "init")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.stub("gh", [merged(12, self.sha), {"number": 999, "state": "OPEN", "baseRefName": "main"}])

    def names_nothing(self, words):
        self.table(f"| 1 | x | Live | {words} |")
        code, out = self.judge()
        self.assertEqual(code, 3, words + "\n" + out)
        self.assertIn("names no commit", out, words)

    def test_no_way_of_writing_one_is_evidence_here(self):
        for words in ("[PR #12](https://github.com/vendor/lib/pull/12)", "github.com/vendor/lib/pull/12", "HTTPS://github.com/vendor/lib/pull/12",
                      "https://evil.example/me/app/pull/12", f"www.github.com/vendor/lib/commit/{self.sha[:7]}",
                      f"https://github.com/vendor/lib/pull/999/commits/{self.sha[:7]}", "https://github.com/vendor/lib/pull/12",
                      f"https://github.com/vendor/lib/commit/{self.sha[:7]}", '<a href="https://github.com/vendor/lib/pull/12">PR #12</a>'):
            self.names_nothing(words)

    def test_our_own_links_are_evidence(self):
        for words in ("[PR #12](https://github.com/me/app/pull/12)", "https://github.com/me/app/pull/12", "github.com/ME/App/pull/12", f"https://www.github.com/me/app/commit/{self.sha}"):
            self.table(f"| 1 | x | Live | {words} |")
            code, out = self.judge()
            self.assertEqual(code, 0, words + "\n" + out)

    def test_every_form_a_remote_can_take_is_read(self):
        for url in ("github.com:me/app.git", "git@github.com:me/app.git", "ssh://git@github.com/me/app.git", "ssh://git@ssh.github.com:443/me/app.git", "https://x:y@github.com/me/app"):
            git(self.repo, "remote", "set-url", "origin", url)
            self.table("| 1 | x | Live | https://github.com/me/app/pull/12 |")
            self.assertEqual(self.judge()[0], 0, url)
            self.table("| 1 | x | Live | https://github.com/vendor/lib/pull/12 |")
            self.assertEqual(self.judge()[0], 3, url)

    def test_a_name_from_an_ssh_config_says_nothing_about_the_host(self):
        git(self.repo, "remote", "set-url", "origin", "git@github-work:me/app.git")
        self.table("| 1 | x | Live | https://github.com/me/app/pull/12 |")
        self.assertEqual(self.judge()[0], 0)

    def test_a_remote_with_no_owner_does_not_make_every_repository_of_that_name_ours(self):
        git(self.repo, "remote", "set-url", "origin", "https://example.invalid/app.git")
        self.names_nothing("https://github.com/attacker/app/pull/12")

    def test_a_subgroup_is_compared_whole(self):
        git(self.repo, "remote", "set-url", "origin", "git@gitlab.com:group/sub/app.git")
        self.names_nothing("https://gitlab.com/evil/sub/app/-/merge_requests/3")

    def test_a_remote_that_is_a_local_path_vouches_for_no_link(self):
        git(self.repo, "remote", "set-url", "origin", str(self.tmp / "origin.git"))
        self.names_nothing("https://github.com/me/app/pull/12")

    def test_thousands_of_links_cost_nothing(self):
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | x | Live | `{self.sha}` {'https://x/' * 20000} |\n")
        self.write_plan()
        started = time.perf_counter()
        self.run_cli("check", "--offline", "--plan", str(self.plan_path))
        self.assertLess(time.perf_counter() - started, 5)


class TheHookSeesWhatLeaves(Small):
    def tracker(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        self.install_hook()

    def test_moving_the_table_away_stops_the_commit(self):
        self.tracker()
        git(self.repo, "mv", "status-table.md", "somewhere-else.md")
        done = self.in_repo("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "move the table away")
        self.assertNotEqual(done.returncode, 0, done.stderr)
        self.assertIn("cannot read the status table", done.stderr)

    def test_moving_the_table_with_the_plan_is_fine(self):
        self.tracker()
        git(self.repo, "mv", "status-table.md", "somewhere-else.md")
        self.write_plan(status_doc="somewhere-else.md")
        self.render()
        done = self.commit_all("move the table")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_pointer_naming_nothing_stops_the_commit(self):
        self.c("a")
        (self.repo / "plans").mkdir()
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        real = self.repo / "plans" / "a.json"
        real.write_text(json.dumps({"status_doc": "../status-table.md", "status_out": "../STATUS.md", "repo": "..", "title": "T"}))
        self.plan_path.write_text('{"plan": "plans/a.json"}')
        self.run_cli("render", "--write", "--plan", str(real))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        self.run_cli("install-hook", "--plan", str(real))
        self.plan_path.write_text('{"plan": "plans/nothing.json"}')
        done = self.commit_all("point at nothing")
        self.assertNotEqual(done.returncode, 0, done.stderr)

    def test_moving_the_rules_to_a_new_file_is_said(self):
        self.c("a")
        (self.repo / "plans").mkdir()
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        first = self.repo / "plans" / "a.json"
        first.write_text(json.dumps({"status_doc": "../status-table.md", "status_out": "../STATUS.md", "repo": "..", "title": "T"}))
        self.plan_path.write_text('{"plan": "plans/a.json"}')
        self.run_cli("render", "--write", "--plan", str(first))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        base = git(self.repo, "rev-parse", "HEAD")
        lax = {"status_doc": "../status-table.md", "status_out": "../STATUS.md", "repo": "..", "title": "T",
               "kinds": [{"name": "Live", "weight": 1, "evidence": "release"}, {"name": "Not built", "weight": 1}]}
        second = self.repo / "plans" / "b.json"
        second.write_text(json.dumps(lax))
        self.plan_path.write_text('{"plan": "plans/b.json"}')
        self.run_cli("render", "--write", "--plan", str(second))
        git(self.repo, "add", "-A")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--strict")
        self.assertIn("the plan moved here from plans/a.json", done.stdout)
        self.assertIn("Not built: weight 0.0 to 1", done.stdout)
        git(self.repo, "commit", "-qm", "a new plan")
        from gitdone import ci
        self.assertTrue(any("moved here" in line for line in ci.rule_changes(Plan(second), base)))

    def test_the_action_judges_a_table_moved_away(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        base = git(self.repo, "rev-parse", "HEAD")
        plan = Plan(self.plan_path)
        git(self.repo, "mv", "status-table.md", "somewhere-else.md")
        git(self.repo, "commit", "-qm", "move")
        from gitdone import ci
        self.assertTrue(ci.touched(plan, base))

    def test_a_plan_broken_any_way_stays_out_of_an_unrelated_commit(self):
        self.tracker()
        self.plan_path.write_text('{"status_doc":"status-table.md","repo":5,"title":"T"}')
        self.commit_all("a plan with a number for its repo", no_verify=True)
        (self.repo / "a.txt").write_text("2\n")
        git(self.repo, "add", "a.txt")
        done = self.in_repo("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "unrelated work")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("not checked", done.stdout + done.stderr)

    def test_a_real_replacement_character_is_read_as_itself(self):
        self.c("a")
        self.table("| 1 | x | Partial | a replacement character: � |")
        git(self.repo, "add", "-A")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--strict")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_bytes_that_are_not_utf8_are_still_refused(self):
        self.c("a")
        self.table("| 1 | x | Partial | words |")
        with (self.repo / "status-table.md").open("ab") as handle:
            handle.write(b"\xff\xfe\n")
        git(self.repo, "add", "-A")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--strict")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)


class Branches(Small):
    def test_head_is_no_branch(self):
        self.c("a")
        self.origin()
        git(self.repo, "remote", "set-head", "origin", "main")
        self.table("| 1 | x | Built, not live (HEAD) | |")
        self.assertEqual(self.judge()[0], 1)


class GitFailingIsNoAnswer(Small):
    def fails_on(self, *wanted):
        real = gitio.git

        def failing(repo, *args, **kwargs):
            if args and args[0] in wanted:
                return gitio.Done(128, "", "fatal: simulated failure")
            return real(repo, *args, **kwargs)
        return mock.patch.object(gitio, "git", failing)

    def test_a_reverted_merge_whose_commits_cannot_be_read(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "side")
        inside = self.c("x", "side work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
        git(self.repo, "revert", "--no-edit", "-m", "1", "HEAD")
        self.table(f"| 1 | x | Live | `{inside}` |")
        real = gitio.git

        def failing(repo, *args, **kwargs):
            if args and args[0] == "rev-list" and "--stdin" not in args:
                return gitio.Done(128, "", "fatal: simulated failure")
            return real(repo, *args, **kwargs)
        with mock.patch.object(gitio, "git", failing):
            code, out = self.judge()
        self.assertEqual(code, 2, out)
        self.assertIn("simulated failure", out)

    def test_what_a_merge_took_cannot_be_read(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "side")
        inside = self.c("x", "side work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "side", "-m", "take nothing")
        self.table(f"| 1 | x | Live | `{inside}` |")
        real = gitio.git

        def failing(repo, *args, **kwargs):
            if args and args[0] == "cat-file" and any(":" in line for line in (kwargs.get("stdin_text") or "").split("\n")):
                return gitio.Done(128, "", "fatal: simulated failure")
            return real(repo, *args, **kwargs)
        with mock.patch.object(gitio, "git", failing):
            code, out = self.judge()
        self.assertEqual(code, 2, out)


class RealFilesInTheProject(Small):
    def test_a_link_as_the_plan_is_refused_and_writes_nothing_beside_it(self):
        victim = self.tmp / "victim"
        victim.mkdir()
        git(victim, "init", "-q", "-b", "main")
        (victim / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        (victim / "STATUS.md").write_text("the victim's own words\n")
        (victim / ".gitdone.json").write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "title": "T"}))
        os.symlink(victim / ".gitdone.json", self.plan_path)
        code, out = self.run_cli("render", "--write", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertEqual((victim / "STATUS.md").read_text(), "the victim's own words\n")
        before = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, before)
        code, out = self.run_cli("render", "--write")
        self.assertEqual(code, 2, out)
        self.assertIn("symbolic link", out)
        self.assertEqual((victim / "STATUS.md").read_text(), "the victim's own words\n")

    def test_a_table_through_a_link_by_an_absolute_path(self):
        (self.repo / "real.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        os.symlink("real.md", self.repo / "link.md")
        self.write_plan(status_doc=str(self.repo / "link.md"))
        code, out = self.judge()
        self.assertEqual(code, 2, out)

    def test_a_pointer_through_a_link_is_refused(self):
        (self.repo / "real").mkdir()
        (self.repo / "real" / "a.json").write_text(json.dumps({"status_doc": "t.md", "title": "T"}))
        os.symlink("real", self.repo / "plans")
        self.plan_path.write_text('{"plan": "plans/a.json"}')
        before = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, before)
        code, out = self.run_cli("where")
        self.assertEqual(code, 2, out)
        self.assertIn("symbolic link", out)

    def test_two_names_for_one_file_do_not_overwrite_the_table(self):
        self.c("a")
        names = [f"{self.repo}/sub/../status-table.md"]
        if (self.repo / "A.TXT").exists():  # this disk ignores case
            names.append("STATUS-TABLE.md")
        (self.repo / "sub").mkdir()
        text = "### 1. D (1)\n\n| 1 | x | Not built | |\n"
        (self.repo / "status-table.md").write_text(text)
        for name in names:
            self.write_plan(status_out=name)
            self.assertEqual(self.render(), 2, name)
            self.assertEqual((self.repo / "status-table.md").read_text(), text, name)

    def test_a_device_or_a_pipe_is_not_read(self):
        if os.name == "nt":
            self.skipTest("no such files")
        self.write_plan(status_doc="/dev/zero")
        code, out = self.plain()
        self.assertEqual(code, 2, out)
        self.assertIn("not a regular file", out)
        os.mkfifo(self.repo / "pipe")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(status_out="pipe")
        code, out = self.plain()
        self.assertEqual(code, 2, out)
        self.write_plan(verdict_state="pipe")
        code, out = self.plain()
        self.assertEqual(code, 2, out)


class ThePlanIsReadStrictly(Small):
    def test_a_misspelled_rule_is_refused_and_its_own_keys_are_not(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        for key in ("default_brnach", "evidence_patern", "statusdoc", "kind", "rows-total"):
            self.write_plan(**{key: "x"})
            code, out = self.plain()
            self.assertEqual(code, 2, key + out)
            self.assertIn("Did you mean", out, key)
        self.write_plan(status_out="STATUS.md", decisions=[], asks=[], candidates=[], owner="x", notes="y")
        self.assertEqual(self.render(), 0)

    def test_every_path_is_text(self):
        for key, value in (("repo", 5), ("status_out", 5), ("badge", []), ("verdict_state", True), ("default_branch", 5), ("release", 5), ("evidence_pattern", 5)):
            self.write_plan(**{key: value})
            with self.assertRaises(PlanError, msg=key):
                Plan(self.plan_path)

    def test_a_range_too_long_to_mean_anything(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        for domains in ("1-99999999999", "9" * 5000, "1-9000000"):
            self.write_plan(groups=[{"label": "A", "domains": domains}])
            self.assertEqual(self.plain()[0], 2, domains)


class SmallerRules(Small):
    def test_a_note_no_reader_sees_is_no_note(self):
        self.c("a")
        self.table("| 1 | x | Partial | <!-- --> |", "| 2 | y | Partial | &nbsp; |", "| 3 | z | Partial | ​ |", "| 4 | w | Partial | real words |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("rows 1, 2, 3 have no note", out)

    def test_a_short_id_two_commits_share_settles_on_the_one_on_the_branch(self):
        not_on_windows(self, "the search for a shared short id makes file names that cannot exist there")
        self.c("base")
        parent = git(self.repo, "rev-parse", "HEAD")
        blob = subprocess.run(["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"], input="x\n", capture_output=True, text=True, env=clean_env()).stdout.strip()
        tree = git(self.repo, "rev-parse", "HEAD^{tree}")
        listing = git(self.repo, "ls-tree", tree)
        made = {}
        trees = []
        for name in ("f1.txt", "f2.txt"):
            trees.append(subprocess.run(["git", "-C", str(self.repo), "mktree"], input=f"{listing}\n100644 blob {blob}\t{name}\n", capture_output=True, text=True, env=clean_env()).stdout.strip())
        pair = None
        for n in range(200000):
            which = trees[n % 2]
            body = f"tree {which}\nparent {parent}\nauthor T <t@example.com> 1800000000 +0000\ncommitter T <t@example.com> 1800000000 +0000\n\nchange {n}\n".encode()
            short = hashlib.sha1(b"commit %d\0" % len(body) + body).hexdigest()[:7]
            if short in made and made[short][0] != which:
                pair = (made[short], (which, body))
                break
            made[short] = (which, body)
        self.assertIsNotNone(pair)
        ids = [subprocess.run(["git", "-C", str(self.repo), "hash-object", "-t", "commit", "-w", "--stdin"], input=body, capture_output=True, env=clean_env()).stdout.decode().strip() for _, body in pair]
        git(self.repo, "merge", "-q", "--ff-only", ids[0])
        git(self.repo, "branch", "side", ids[1])
        self.table("| 1 | x | Not built | |")
        code, out = self.run_cli("shipped", "1", ids[0][:7], "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        code, out = self.judge()
        self.assertEqual(code, 0, out)

    def test_a_ref_groups_unfetched_tag_only_warns_as_a_tag_does(self):
        self.c("a")
        self.origin()
        self.table("| 1 | x | Live | ref v9.9 |", plan={"evidence_pattern": "ref (?P<ref>v\\d+\\.\\d+)"})
        code, out = self.plain()
        self.assertEqual(code, 0, out)
        self.assertIn("v9.9 is not in app's clone; fetch --tags", out)

    def test_a_personal_diff_relative_changes_no_answer(self):
        sha = self.c("a")
        folder = self.repo / "pkg"
        folder.mkdir()
        self.repo_was, self.repo = self.repo, folder
        self.plan_path = folder / ".gitdone.json"
        self.table(f"| 1 | x | Live | `{sha}` |")
        config = self.tmp / "gitconfig"
        config.write_text("[diff]\n\trelative = true\n")
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            code, out = self.judge()
        self.assertEqual(code, 0, out)

    def test_an_odd_verdict_state_stops_nothing(self):
        self.c("a")
        for state in ('{"last_run":"x"}', '{"last_run":{"git_sha":5}}', "[]"):
            (self.repo / "state.json").write_text(state)
            self.table("| 1 | x | Not built | |", plan={"verdict_state": "state.json"})
            code, out = self.judge()
            self.assertEqual(code, 0, state + out)
            self.assertIn("state unreadable", out, state)

    def test_report_stops_where_the_gate_stops(self):
        self.c("a")
        self.c("b")
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "1", f"file://{self.repo}", str(clone))
        self.repo, self.plan_path = clone, clone / ".gitdone.json"
        sha = git(clone, "rev-parse", "HEAD")
        self.table(f"| 1 | x | Live | `{sha}` |")
        code, out = self.run_cli("report", "--json", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertIn("shallow", out)

    def test_report_names_the_commit_not_a_tag_named_like_it(self):
        real = self.c("a", "the real commit")
        other = self.c("z", "another commit entirely")
        git(self.repo, "tag", real[:7], other)
        self.table(f"| 1 | x | Live | `{real[:7]}` |")
        code, out = self.run_cli("report", "--json", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)[0]["claims"][0]["found"]["subject"], "the real commit")

    def test_a_byte_order_mark_does_not_break_add_or_remove(self):
        self.c("a")
        self.raw_table(f"﻿### 1. D (1)\n\n{HEAD}| 1 | a | Not built | |\n")
        code, out = self.run_cli("add", "another row", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        code, out = self.run_cli("remove", "1", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        self.assertNotIn("a | Not built", (self.repo / "status-table.md").read_text())
        self.assertEqual(self.judge()[0], 0)

    def test_a_number_too_long_to_be_one_is_no_pull_request(self):
        self.c("a")
        self.table(f"| 1 | x | Live | PR #{'9' * 5000} |")
        code, out = self.judge()
        self.assertEqual(code, 3, out)
        self.assertIn("names no commit", out)

    def test_a_status_cell_full_of_openers_costs_nothing(self):
        self.c("a")
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | x | Built, not live {'(' * 50000} | |\n")
        self.write_plan()
        started = time.perf_counter()
        self.run_cli("check", "--offline", "--plan", str(self.plan_path))
        self.assertLess(time.perf_counter() - started, 3)

    def test_a_revert_message_of_blank_lines_costs_nothing(self):
        not_on_windows(self, "a command line that long is refused there")
        sha = self.c("a")
        self.c("b", "x" + "\n" * 60000 + "This reverts commit 0123456.")
        self.table(f"| 1 | x | Live | `{sha}` |")
        started = time.perf_counter()
        self.judge()
        self.assertLess(time.perf_counter() - started, 3)


class AStrangersWordsAtYourTerminal(Small):
    def test_an_escape_sequence_is_shown_and_not_obeyed(self):
        self.c("a")
        self.table("| 1 | x | Built, not live (x\x1b[1A\x1b[2Kresult: PASS) | |")
        code, out = self.plain()
        self.assertEqual(code, 1)
        self.assertNotIn("\x1b", out)
        self.assertIn("x\\x1b[1A", out)

    def test_a_carriage_return_cannot_start_a_workflow_command(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(regenerate="x\r::error title=forged::the gate passed")
        code, out = self.plain()
        self.assertEqual(code, 1, out)
        self.assertNotIn("\r", out)

    def test_a_terminal_gets_every_command_escaped_and_a_pipe_gets_the_bytes(self):
        stream = io.StringIO()
        cli._Terminal(stream).write("safe\n\x1b[2Kline\tend\n")
        self.assertEqual(stream.getvalue(), "safe\n\\x1b[2Kline\tend\n")
        self.c("a")
        self.table("| 1 | x\x1b[2K | Not built | |")
        self.assertIn("\x1b", self.run_cli("render", "--plan", str(self.plan_path))[1], "a pipe gets what the table holds")


class TheCommandLine(Small):
    def test_json_goes_before_or_after_the_command(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        before = self.run_cli("--json", "check", "--plan", str(self.plan_path))[1]
        after = self.run_cli("check", "--json", "--plan", str(self.plan_path))[1]
        self.assertEqual(json.loads(before), json.loads(after))
        self.assertIn("rows", self.run_cli("--json", "status", "--plan", str(self.plan_path))[1])

    def test_json_on_a_command_with_no_json_is_refused_and_not_ignored(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        code, out = self.run_cli("--json", "render", "--plan", str(self.plan_path))
        self.assertEqual(code, 2)
        self.assertIn("--json does not go with render", out)

    def test_a_row_given_by_name_gets_a_way_forward(self):
        code, out = self.run_cli("shipped", "Search", "abc1234")
        self.assertEqual(code, 2)
        self.assertIn("'Search' is not a row number; `gitdone rows` lists them", out)

    def test_the_headline_names_the_one_thing_that_does_not_hold(self):
        feature = self.c("a", "add A")
        self.table(f"| 1 | x | Live | `{feature}` |")
        git(self.repo, "revert", "--no-edit", feature)
        code, out = self.run_cli("status", "--plan", str(self.plan_path))
        self.assertIn("the gate fails: row 1 (Live): commit", out)
        self.assertIn("was reverted on main", out)

    def test_doctor_names_the_row(self):
        self.c("a")
        self.table("| 1 | x | Built, not live (spike) | |")
        code, out = self.run_cli("doctor", "--plan", str(self.plan_path))
        self.assertIn("row 1 (Built, not live): branch spike does not exist", out)

    def test_a_row_past_the_gate_with_no_verify_names_the_new_id(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "wip")
        stray = self.c("b")
        git(self.repo, "checkout", "-q", "main")
        self.table(f"| 1 | x | Live | `{stray}` |")
        code, out = self.plain()
        self.assertEqual(code, 1, out)
        self.assertIn("amended or rebased? Name the new id", out)
        data = json.loads(self.run_cli("check", "--json", "--plan", str(self.plan_path))[1])
        self.assertIn("amended or rebased", data["failures"][0]["next"])


class VouchingForAClaim(Small):
    def test_no_repository_at_all(self):
        (self.repo / ".git").rename(self.tmp / "gone")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan()
        self.render()
        code, out = self.run_cli("shipped", "1", "abc1234", "--plan", str(self.plan_path))
        self.assertEqual(code, 1, out)
        self.assertIn("not a git repository yet", out)
        self.assertIn("--allow-unverified", out)
        code, out = self.run_cli("shipped", "1", "abc1234", "--allow-unverified", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        self.assertIn("unverified", (self.repo / "status-table.md").read_text())

    def test_a_claim_that_holds_in_name_only_cannot_be_vouched_for(self):
        self.c("a")
        nothing = self.empty()
        self.table("| 1 | x | Not built | |")
        code, out = self.run_cli("shipped", "1", nothing, "--allow-unverified", "--plan", str(self.plan_path))
        self.assertEqual(code, 1, out)
        self.assertIn("changes no file", out)

    def test_a_claim_git_disproves_cannot_be_vouched_for(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "wip")
        stray = self.c("b")
        git(self.repo, "checkout", "-q", "main")
        self.table("| 1 | x | Not built | |")
        self.assertEqual(self.run_cli("shipped", "1", stray, "--allow-unverified", "--plan", str(self.plan_path))[0], 1)


class TheAction(Small):
    def test_install_ci_writes_the_workflow_for_this_branch(self):
        self.c("a")
        git(self.repo, "branch", "-m", "main", "trunk")
        self.table("| 1 | x | Not built | |", plan={"default_branch": "trunk"})
        code, out = self.run_cli("install-ci", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        text = (self.repo / ".github" / "workflows" / "status.yml").read_text()
        self.assertIn("branches: [trunk]", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("uses: ArtJack/gitdone@v0", text)
        self.assertNotIn("working-directory", text)

    def test_it_leaves_a_workflow_it_did_not_write_alone(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        path = self.repo / ".github" / "workflows" / "status.yml"
        path.parent.mkdir(parents=True)
        path.write_text("mine\n")
        code, out = self.run_cli("install-ci", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertIn("left alone", out)
        self.assertEqual(path.read_text(), "mine\n")

    def test_a_tracker_in_a_subfolder_names_its_folder(self):
        self.c("a")
        folder = self.repo / "pkg" / "web"
        folder.mkdir(parents=True)
        self.repo_was, self.repo = self.repo, folder
        self.plan_path = folder / ".gitdone.json"
        self.table("| 1 | x | Not built | |", plan={"repo": "../.."})
        code, out = self.run_cli("install-ci", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        self.assertIn('working-directory: "pkg/web"', (self.repo_was / ".github" / "workflows" / "status.yml").read_text())

    def test_a_tracker_measuring_another_repository_cannot_use_it(self):
        self.c("a")
        other = self.tmp / "other"
        other.mkdir()
        git(other, "init", "-q", "-b", "main")
        commit(other, "a.txt", "1\n")
        self.table("| 1 | x | Not built | |", plan={"repo": "../other"})
        code, out = self.run_cli("install-ci", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)

    def test_the_docs_show_what_it_writes(self):
        from gitdone import scaffold
        self.assertIn(scaffold.WORKFLOW.format(branch="main"), (ROOT / "docs" / "ci.md").read_text())


class InitHoldsCheckedItemsToGit(Small):
    def init(self, *args):
        before = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, before)
        return self.run_cli("init", *args)

    def test_a_checked_item_starts_live_only_if_what_it_names_holds(self):
        good = self.c("a")
        nothing = self.empty()
        (self.tmp / "TODO.md").write_text(f"- [x] One `{good[:7]}`\n- [x] Two `{nothing[:7]}`\n- [x] Three, done in PR #7\n- [x] Four\n- [ ] Five\n")
        code, out = self.init("--from-checklist", str(self.tmp / "TODO.md"))
        self.assertEqual(code, 0, out)
        table = (self.repo / "status-table.md").read_text()
        rows = parse(table, KINDS).rows
        self.assertEqual([rows[n].kind for n in (1, 2, 3, 4, 5)], ["Live", "Partial", "Partial", "Partial", "Not built"])
        self.assertIn("row 2 starts as Partial", out)
        self.assertIn("row 3 starts as Partial: PR #7", out)
        self.assertIn("strict 20%", out)
        self.assertEqual(self.judge()[0], 0, "nothing init accepted is refused at the first commit")

    def test_init_with_a_hook_it_cannot_install_still_says_what_it_did(self):
        self.c("a")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\necho mine\n")
        code, out = self.init("--rows", "A, B", "--hook")
        self.assertEqual(code, 2, out)
        self.assertIn("wrote .gitdone.json", out)
        self.assertIn("Next:", out, "the summary is still there")

    def test_init_with_ci(self):
        self.c("a")
        code, out = self.init("--rows", "A, B", "--ci")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.repo / ".github" / "workflows" / "status.yml").exists())
        self.assertNotIn("install-ci", out, "no need to suggest what was just done")
        self.assertIn(".github", [line for line in out.splitlines() if "git add" in line][0])  # or the first commit leaves the gate behind


class WhatChangedInTheRulesIsShort(unittest.TestCase):
    def changes(self, old, new):
        from gitdone import gate
        plan = mock.Mock()
        plan.data = new
        return gate.rule_changes(plan, old)

    def test_only_what_moved_is_said(self):
        kinds = [{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "Partial", "weight": 0.4}]
        more = [{"name": "Live", "weight": 1.0, "evidence": "release"}, {"name": "Partial", "weight": 0.9}, {"name": "Parked", "weight": 0.1}]
        self.assertEqual(self.changes({"kinds": kinds}, {"kinds": more}), ["this changes the gate's own rules: kinds: Parked added; Partial: weight 0.4 to 0.9"])
        self.assertEqual(self.changes({"default_branch": "main"}, {"default_branch": "stray"}), ['this changes the gate\'s own rules: default_branch was "main", now "stray"'])
        self.assertEqual(self.changes({"groups": [{"label": "A"}]}, {"groups": []}), ["this changes the gate's own rules: groups changed"])


if __name__ == "__main__":
    unittest.main()


class TheSecondPass(Small):
    """What a second reading found in the first round of fixes."""

    def judged(self, *rows, **kwargs):
        self.table(*rows, **kwargs)
        return self.judge()

    def two_files(self, one="f1.txt", two="f2.txt", message="the feature, two files"):
        (self.repo / one).write_text("1\n")
        (self.repo / two).write_text("2\n")
        git(self.repo, "add", one, two)
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")

    def test_ours_of_a_commit_with_several_files(self):
        self.c("base")
        git(self.repo, "checkout", "-qb", "feature")
        taken = self.two_files()
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "feature", "-m", "take nothing")
        code, out = self.judged(f"| 1 | x | Live | `{taken}` |")
        self.assertEqual(code, 3, out)
        self.assertIn("a merge that took none of its changes", out)

    def test_a_real_merge_of_a_commit_with_several_files(self):
        (self.repo / "setup.py").write_text("s0\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "checkout", "-qb", "feature")
        (self.repo / "pkg" / "sub").mkdir(parents=True)
        (self.repo / "pkg" / "__init__.py").write_text("")
        (self.repo / "pkg" / "sub" / "__init__.py").write_text("")
        (self.repo / "setup.py").write_text("s1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add the package")
        taken = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "feature", "-m", "merge the package")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{taken}` |")[0], 0)

    def test_a_revert_of_several_files_on_a_merged_branch_stands(self):
        feature = self.two_files(message="add feature A")
        git(self.repo, "checkout", "-qb", "undo")
        git(self.repo, "revert", "--no-edit", feature)
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "undo", "-m", "Merge pull request #31 from me/undo")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{feature}` |")[0], 1)

    def test_a_merge_with_everything_it_brought_in_reverted_has_nothing_left(self):
        self.c("a")
        self.origin()
        git(self.repo, "checkout", "-qb", "pr")
        inside = self.c("feature", "the feature")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "pr", "-m", "Merge pull request #12 from me/pr")
        merge = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "revert", "--no-edit", inside)
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.stub("gh", [merged(12, merge)])
        code, out = self.judged(f"| 1 | x | Live | `{merge}` |", "| 2 | y | Live | PR #12 |")
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {merge} was reverted", out)
        self.assertIn("PR #12 was reverted", out)

    def test_a_merge_with_only_some_of_it_reverted_still_stands(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "pr")
        one = self.c("one")
        self.c("two")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "pr", "-m", "merge")
        merge = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "revert", "--no-edit", one)
        self.assertEqual(self.judged(f"| 1 | x | Live | `{merge}` |")[0], 0)

    def test_a_squash_reverting_a_merge_reverts_what_it_brought_in(self):
        self.c("a")
        git(self.repo, "checkout", "-qb", "side")
        inside = self.c("x", "side work")
        self.c("y", "more side work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
        merge = git(self.repo, "rev-parse", "HEAD")
        parent = git(self.repo, "rev-parse", "HEAD^1")
        other = self.c("z", "other")
        git(self.repo, "rm", "-q", "x.txt", "y.txt", "z.txt")
        git(self.repo, "commit", "-qm", f"Back out side and other\n\nThis reverts commit {merge}, reversing\nchanges made to {parent}.\n\nThis reverts commit {other}.\n")
        code, out = self.judged(f"| 1 | x | Live | `{merge}` |", f"| 2 | y | Live | `{inside}` |", f"| 3 | z | Live | `{other}` |")
        self.assertEqual(code, 1, out)
        for sha in (merge, inside, other):
            self.assertIn(f"commit {sha} was reverted", out)

    def test_a_squash_of_a_revert_a_reapply_and_more_work_on_the_same_file(self):
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-qm", "add a")
        (self.repo / "a.txt").write_text("one\ntwo\n")
        git(self.repo, "add", "a.txt")
        git(self.repo, "commit", "-qm", "the feature")
        feature = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "a.txt").write_text("one\ntwo\nthree\n")
        git(self.repo, "add", "a.txt")
        lost = "0123456789abcdef" * 2 + "01234567"
        git(self.repo, "commit", "-qm", f'More of the feature (#9)\n\n* Revert "the feature"\n\n    This reverts commit {feature}.\n\n* Reapply "the feature"\n\n    This reverts commit {lost}.\n')
        self.assertEqual(self.judged(f"| 1 | x | Live | `{feature}` |")[0], 0)

    def test_reverting_a_pull_request_leaves_an_older_commit_of_that_subject_alone(self):
        self.origin(push=False)
        older = self.c("readme", "Update README")
        self.c("notes", "Update README (#30)")
        self.c("more")
        git(self.repo, "rm", "-q", "notes.txt")
        git(self.repo, "commit", "-qm", 'Revert "Update README" (#31)\n\nReverts me/app#30\n')
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{older}` |")[0], 0)

    def test_a_reapply_only_on_this_machine_puts_nothing_back(self):
        self.origin(push=False)
        feature = self.c("a", "add A")
        git(self.repo, "revert", "--no-edit", feature)
        revert = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "revert", "--no-edit", revert)
        code, out = self.judged(f"| 1 | x | Live | `{feature}` |")
        self.assertEqual(code, 1, out)
        git(self.repo, "push", "-q", "origin", "main")
        self.assertEqual(self.judge()[0], 0, "pushed, it counts")

    def test_a_revert_only_on_this_machine_counts_against_a_claim(self):
        self.origin(push=False)
        feature = self.c("a", "add A")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "revert", "--no-edit", feature)
        self.assertEqual(self.judged(f"| 1 | x | Live | `{feature}` |")[0], 1)

    def test_a_checksum_is_no_commit_in_an_ordinary_repository(self):
        sha = self.c("a")
        digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        self.assertEqual(self.judged(f"| 1 | x | Live | `{sha}`, artifact sha256 `{digest}` |")[0], 0)

    def test_several_remotes_answer_to_the_one_git_tracks(self):
        self.c("a")
        self.origin("company")
        self.origin("alice")
        git(self.repo, "branch", "-q", "--set-upstream-to=company/main", "main")
        git(self.repo, "checkout", "-qb", "a2", "main")
        theirs = self.c("fork", "a commit only on a colleague's fork")
        git(self.repo, "push", "-q", "alice", "a2:main")
        git(self.repo, "fetch", "-q", "alice")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "branch", "-qD", "a2")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{theirs}` |")[0], 1)
        good = git(self.repo, "rev-parse", "main")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{good}` |")[0], 0)

    def test_several_remotes_and_nothing_to_say_which(self):
        good = self.c("a")
        self.origin("one")
        self.origin("two")
        code, out = self.judged(f"| 1 | x | Live | `{good}` |")
        self.assertEqual(code, 3, out)
        self.assertIn("nothing says which of one, two holds it", out)
        git(self.repo, "config", "remote.pushDefault", "one")
        self.assertEqual(self.judge()[0], 0)

    def test_a_remote_with_a_slash_in_its_name(self):
        good = self.c("a")
        bare = self.tmp / "team.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(bare))
        git(self.repo, "remote", "add", "team/x", str(bare))
        git(self.repo, "push", "-q", "team/x", "main")
        self.assertEqual(self.judged(f"| 1 | x | Live | `{good}` |")[0], 0)

    def test_git_failing_to_name_its_remotes_or_its_folder_is_no_answer(self):
        self.c("a")
        self.origin()
        unpushed = self.c("b", "only here")
        self.table(f"| 1 | x | Live | `{unpushed}` |")
        real = gitio.git

        for verb in ("remote", "--git-common-dir"):
            def failing(repo, *args, verb=verb, **kwargs):
                if verb in args:
                    return gitio.Done(128, "", "fatal: simulated failure")
                return real(repo, *args, **kwargs)
            with mock.patch.object(gitio, "git", failing):
                code, out = self.judge()
            if verb == "remote":
                self.assertEqual(code, 2, out)
        git(self.repo, "push", "-q", "origin", "main")
        with mock.patch.object(gitio, "git", failing):
            code, out = self.judge()
        self.assertEqual(code, 2, out)

    def test_the_commit_the_forge_names_is_named_when_it_is_judged(self):
        self.origin(push=False)
        self.c("a")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        self.c("work", "the real work")
        with (self.repo / "status-table.md").open("a") as handle:
            handle.write("\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "update the table")
        last = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "push", "-q", "origin", "main")
        self.stub("gh", [merged(12, last)])
        code, out = self.judged("| 1 | x | Live | PR #12 |")
        self.assertEqual(code, 3, out)
        self.assertIn(f"PR #12's commit {last[:7]} only changes the tracker itself; if the work is in another commit of it, cite that commit instead of the pull request", out)

    def test_a_tracker_named_in_another_case_on_a_disk_that_ignores_it(self):
        self.c("a")
        if not (self.repo / "A.TXT").exists():
            self.skipTest("this disk minds case")
        self.table("| 1 | x | Not built | |")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        with (self.repo / "status-table.md").open("a") as handle:
            handle.write("\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "only the table")
        only_table = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n| 1 | x | Live | `{only_table}` |\n")
        self.write_plan(status_doc="Status-Table.md")
        self.render()
        code, out = self.judge()
        self.assertEqual(code, 3, out)

    def test_a_note_that_only_looks_like_one(self):
        self.c("a")
        code, out = self.judged(f"| 1 | x | Partial | <!-- {'x' * 600} --> |", "| 2 | y | Partial | &#8203; |", "| 3 | z | Partial | <br> |", "| 4 | w | Partial | <b>real</b> |")
        self.assertEqual(code, 3, out)
        self.assertIn("rows 1, 2, 3 have no note", out)

    def test_a_flood_of_comment_openers_in_a_note_costs_nothing(self):
        self.c("a")
        self.table(f"| 1 | x | Partial | {'<!--' * 50000} |")
        started = time.perf_counter()
        self.judge()
        self.assertLess(time.perf_counter() - started, 3)

    def test_vouching_for_part_of_a_claim_leaves_its_mark(self):
        self.c("a")
        self.origin()
        good = git(self.repo, "rev-parse", "HEAD")
        self.table("| 1 | x | Not built | |")
        code, out = self.run_cli("shipped", "1", f"`{good}` and PR #12", "--offline", "--allow-unverified", "--plan", str(self.plan_path))
        self.assertEqual(code, 0, out)
        self.assertIn("PR #12, unverified", (self.repo / "status-table.md").read_text())

    def test_a_plans_words_cannot_reach_a_workflow_through_an_error(self):
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(kinds=[{"name": "x\r::error title=forged::the gate passed", "weight": 1, "oops": 1}, {"name": "y", "weight": 0}])
        code, out = self.plain()
        self.assertEqual(code, 2)
        self.assertNotIn("\r", out)
        self.assertIn("\\x0d", out)

    def test_closed_streams_never_read_as_a_contradiction(self):
        good = self.c("a")
        self.table(f"| 1 | x | Live | `{good}` |")
        for closed in ("stdout", "stderr"):
            done = subprocess.run([sys.executable, "-c", f"import os,sys; os.close({1 if closed == 'stdout' else 2}); os.execv(sys.executable, [sys.executable, {str(ENGINE)!r}, 'check', '--strict', '--plan', {str(self.plan_path)!r}])"],
                                  capture_output=True, text=True, env=clean_env())
            self.assertEqual(done.returncode, 0, closed + done.stderr)

    def test_a_branch_a_plan_writes_cannot_shape_the_workflow(self):
        self.c("a")
        self.table("| 1 | x | Not built | |")
        self.write_plan(default_branch='main]\n  workflow_dispatch:\n  x: [y')
        code, out = self.run_cli("install-ci", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertFalse((self.repo / ".github").exists())

    def test_an_ignored_file_a_plan_names_as_its_view_is_left_alone(self):
        self.c("a")
        (self.repo / ".gitignore").write_text(".env\n")
        (self.repo / ".env").write_text("SECRET=only-copy\n")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(status_out=".env")
        code, out = self.run_cli("render", "--write", "--plan", str(self.plan_path))
        self.assertEqual(code, 2, out)
        self.assertIn("refusing to overwrite", out)
        self.assertEqual((self.repo / ".env").read_text(), "SECRET=only-copy\n")

    def test_a_view_git_holds_or_one_of_ours_can_be_replaced(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan()
        self.assertEqual(self.render(), 0)
        self.assertEqual(self.render(), 0, "a view replaces a view")
        (self.repo / "STATUS.md").write_text("edited by hand\n")
        self.assertEqual(self.render(), 2, "not one of ours, and git does not hold it")
        (self.repo / "STATUS.md").write_text("edited by hand\n")
        git(self.repo, "add", "STATUS.md")
        git(self.repo, "commit", "-qm", "hold it")
        self.assertEqual(self.render(), 0, "git holds it as it stands, so git can bring it back")
        git(self.repo, "checkout", "-q", "--", "STATUS.md")
        (self.repo / "STATUS.md").write_text("uncommitted work\n")
        self.assertEqual(self.render(), 2, "uncommitted work is not what git holds")
        self.assertEqual((self.repo / "STATUS.md").read_text(), "uncommitted work\n")

    def test_a_worktree_kept_under_git_can_use_the_tracker(self):
        self.c("a")
        place = self.repo / ".git" / "wt" / "feature"
        git(self.repo, "worktree", "add", "-q", str(place), "-b", "feature")
        (place / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        plan = place / ".gitdone.json"
        plan.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "title": "T"}))
        code, out = self.run_cli("render", "--write", "--plan", str(plan))
        self.assertEqual(code, 0, out)
        plan.write_text(json.dumps({"status_doc": "status-table.md", "status_out": "../../config", "repo": ".", "title": "T"}))
        self.assertEqual(self.run_cli("render", "--write", "--plan", str(plan))[0], 2, "but not what is git's")

    def test_the_hook_refuses_a_link_as_the_plan(self):
        self.c("a")
        (self.repo / "plans").mkdir()
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        real = self.repo / "plans" / "real.json"
        real.write_text(json.dumps({"status_doc": "../status-table.md", "status_out": "../STATUS.md", "repo": "..", "title": "T"}))
        self.run_cli("render", "--write", "--plan", str(real))
        os.symlink("plans/real.json", self.plan_path)
        git(self.repo, "add", "-A")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--strict")
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("symbolic link", done.stdout + done.stderr)

    def test_a_shallow_clone_starts_every_checked_row_as_partial_and_says_why(self):
        self.c("a")
        good = git(self.repo, "rev-parse", "HEAD")
        self.c("b")
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "1", f"file://{self.repo}", str(clone))
        (clone / "TODO.md").write_text(f"- [x] Sign-in ({good})\n")
        before = os.getcwd()
        os.chdir(clone)
        self.addCleanup(os.chdir, before)
        code, out = self.run_cli("init", "--from-checklist", "TODO.md")
        self.assertIn("strict 0%", out)
        self.assertIn("shallow clone", out)


class TheSecondPassOnTables(unittest.TestCase):
    def read(self, text):
        return parse(text, KINDS)

    def body(self, extra):
        return f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n{extra}"

    def test_rows_whose_status_is_not_in_the_third_cell_are_said(self):
        for line in ("| Hidden work | Not built | |", "| 2x | Not built | |", "| 2x | b | Sam | Not built |"):
            self.assertTrue(self.read(self.body(line + "\n")).strays, line)
        self.assertTrue(self.read(self.body("\n### 2. Lost\n\n| Hidden work | Not built | |\n")).strays)

    def test_a_table_of_your_own_goes_under_a_heading_of_its_own(self):
        for doc in (self.body("\n## The phases\n\n| Phase | Weeks |\n|---|---|\n| 1 | three |\n| 2 | five |\n"),
                    f"# T\n\n| Service | Version | Live |\n|---|---|---|\n| web | 1.2 | Live since May |\n\n{self.body('')}",
                    f"## Environments\n\n| Service | Owner | Status |\n|---|---|---|\n| API | me | Live |\n\n{self.body('')}"):
            table = self.read(doc)
            self.assertEqual((table.strays, table.problems), ([], []), doc)
        inside = self.read(self.body("\nThe phases:\n\n| Phase | Weeks |\n|---|---|\n| 1 | three |\n| 2 | five |\n"))
        self.assertTrue(inside.strays, "inside a domain, every table line is a row or is said")

    def test_a_table_of_your_own_shaped_like_a_row_is_still_said(self):
        self.assertTrue(self.read(self.body("\n## Notes\n\n| No | Name | State |\n|---|---|---|\n| 5 | x | Not built |\n")).strays)
        self.assertTrue(self.read(self.body("\n## Notes\n\n| # | Name | State | Note |\n|---|---|---|---|\n| 5 | x | Not built | |\n")).strays)

    def test_a_table_in_a_domain_that_is_not_the_status_table_is_no_prose(self):
        for doc in ("### 1. Payments (2)\n\n| Feature | Status | Note |\n|---|---|---|\n| Stripe | Live | shipped, trust me |\n| Refunds | Not started | |\n",
                    "### 1. Payments (2)\n\n| No | Status | Name |\n|---|---|---|\n| 1 | Live | Stripe |\n| 2 | Not started | Refunds |\n",
                    "### 1. Payments (1)\n\n| Item | Name | State | Note |\n|---|---|---|---|\n| a | Stripe | Live | shipped |\n",
                    "### 1. Payments (1)\n\n| Area | # | Name | Status | Note |\n|---|---|---|---|---|\n| Pay | 1 | Stripe | Live | shipped |\n"):
            self.assertTrue(self.read(doc).problems, doc)

    def test_a_second_table_in_a_domain_is_said(self):
        table = self.read(self.body("\n| Item | Name | State | Note |\n|---|---|---|---|\n| a2 | B | Live | no commit anywhere |\n"))
        self.assertTrue(table.problems or table.strays)

    def test_a_row_above_a_rule_or_a_divider_is_still_a_row(self):
        for after in ("---\n\nMore words.\n", "|---|---|---|---|\n", "| - | - | - | - |\n"):
            table = self.read(f"### 1. D (2)\n\n{HEAD}| 1 | a | Live | x |\n| 2 | b | Not built | |\n{after}")
            self.assertEqual(list(table.rows), [1, 2], after)
            self.assertEqual(table.problems, [], after)

    def test_a_heading_shaped_like_a_domain_that_lost_its_count_is_said(self):
        for heading in ("### 2. Lost", "### 2. Hard (4 rows)", "### 2. Payments (x)", "### 2 Later (1)", "### 2: Later (1)"):
            self.assertTrue(self.read(self.body(f"\n{heading}\n\n| Feature | Status | Note |\n|---|---|---|\n| a | Live | b |\n")).strays, heading)
        self.assertEqual(self.read(self.body("\n## 2. Notes\n\nWords.\n")).strays, [], "another level of heading is yours")
        self.assertEqual(self.read(self.body("\n### 2.1 What is left\n\nWords.\n")).strays, [], "a numbered section is not a domain")
        self.assertEqual(self.read(self.body("\n## Notes\n\n### 1. How we count\n\nWords.\n")).strays, [], "under another heading, it is your own")

    def test_a_sentence_with_pipes_is_a_sentence(self):
        for line in ("Statuses here: Live | Built, not live | Partial | Not built", "Run `a | b | live` to see it."):
            for doc in (f"{line}\n\n{self.body('')}", self.body(f"\n{line}\n")):
                self.assertEqual(self.read(doc).strays, [], doc)

    def test_the_tools_own_counts_table_with_a_domain_named_like_a_status(self):
        doc = f"| # | Domain | All | Live | Built, not live | Partial | Not built |\n|---|---|---|---|---|---|---|\n| 1 | Live | 1 | 1 |  |  | 0 |\n| | **All** | **1** | **1** |  |  |  |\n\n### 1. Live (1)\n\n{HEAD}| 1 | a | Live | x |\n"
        self.assertEqual(self.read(doc).strays, [])

    def test_a_table_inside_a_list_item_is_said(self):
        self.assertTrue(self.read(self.body("\n1. And also:\n\n    | # | Name | Status | Note |\n    |---|---|---|---|\n    | 2 | B | Not started | |\n")).strays)

    def test_a_comment_mid_line_hiding_a_domain_or_rows_is_said(self):
        hidden = self.read(self.body(f"\nLater work <!-- see below\n{HEAD}| 2 | b | Not built | |\n| 3 | c | Not built | -->\n"))
        self.assertEqual(list(hidden.rows), [1])
        self.assertTrue(hidden.strays)
        heading = self.read(f"{self.body('')}\n## Next <!-- not counted yet\n### 2. E (1)\n{HEAD}| 2 | b | Not built | |\n<!-- end -->\n")
        self.assertEqual(list(heading.rows), [1, 2], "a heading is one line, and closes what opens in it")

    def test_a_row_in_a_block_indented_with_spaces_and_a_tab(self):
        self.assertEqual(list(self.read(self.body("\n  \t| 2 | in a code block | Live | x |\n")).rows), [1])

    def test_a_conflict_marker_in_a_fence_is_an_example(self):
        table = self.read("# T\n\n```\n<<<<<<< HEAD\n| 1 | a | Live | x |\n=======\n| 1 | a | Partial | y |\n>>>>>>> branch\n```\n\n" + self.body(""))
        self.assertEqual(table.problems, [])

    def test_a_flood_of_comment_openers_costs_nothing(self):
        started = time.perf_counter()
        self.read("### 1. D (0)\n\n" + "words <!-- open\n" * 40000)
        self.assertLess(time.perf_counter() - started, 2)

    def test_the_prose_rows_of_all_domains_together_have_a_limit(self):
        started = time.perf_counter()
        table = self.read("".join(f"### {n}. D (100000)\n" for n in range(1, 41)))
        self.assertLess(time.perf_counter() - started, 2)
        self.assertTrue(any("the most is" in p for p in table.problems))


class TheSecondPassOnKeysAndCounts(Small):
    def test_a_key_a_section_reads_is_yours_and_capitals_do_not_hide_a_rule(self):
        self.c("a")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(repos=[{"name": "a"}], sections=[{"type": "table", "title": "Repositories", "from": "repos", "columns": [{"head": "Name", "key": "name"}]}])
        self.assertEqual(self.render(), 0)
        for key in ("DEFAULT_BRANCH", "STATUS_OUT", "RowsTotal", "Evidence-Pattern"):
            self.write_plan(**{key: "x"})
            code, out = self.plain()
            self.assertEqual(code, 2, key + out)
            self.assertIn("Did you mean", out)

    def test_a_byte_order_mark_does_not_hide_a_stale_counts_table(self):
        sha = self.c("a")
        body = f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | `{sha}` |\n"
        (self.repo / "status-table.md").write_text(body)
        self.write_plan()
        self.render()
        counts = self.run_cli("counts", "--plan", str(self.plan_path))[1].strip()
        (self.repo / "status-table.md").write_text("﻿" + counts.replace("| 1 | D | 1 | 1 |", "| 1 | D | 7 | 7 |") + "\n\n" + body)
        self.render()
        self.assertEqual(self.judge()[0], 1)
        (self.repo / "status-table.md").write_text("﻿" + counts + "\n\n" + body)
        self.render()
        self.assertEqual(self.judge()[0], 0, "a true one passes with the mark")

    def test_several_ranges_together_have_a_limit(self):
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(groups=[{"label": "g", "domains": ",".join(["1-1000000"] * 8)}])
        started = time.perf_counter()
        self.assertEqual(self.plain()[0], 2)
        self.assertLess(time.perf_counter() - started, 3)


class TheSecondPassOnLinks(Small):
    def setUp(self):
        super().setUp()
        self.origin(push=False)
        self.sha = self.c("a", "init")
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.stub("gh", [merged(12, self.sha)])

    def names_nothing(self, words, after=""):
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | x | Live | {words} |\n\n{after}\n")
        self.write_plan()
        self.render()
        code, out = self.judge()
        self.assertEqual(code, 3, words + "\n" + out)
        self.assertIn("names no commit", out, words)

    def test_no_way_of_writing_a_link_elsewhere_is_a_claim_here(self):
        for words, after in (("[PR #12][lib]", "[lib]: https://github.com/vendor/lib/pull/12"),
                             ("[PR #12]", "[pr #12]: https://github.com/vendor/lib/pull/12"),
                             ("[PR #12]( https://github.com/vendor/lib/pull/12 )", ""),
                             ("[[PR #12]](https://github.com/vendor/lib/pull/12)", ""),
                             ("[PR #12](https://codeberg.org/vendor/lib/pulls/12)", ""),
                             ("[PR #12](https://bitbucket.org/vendor/lib/pull-requests/12)", ""),
                             ("[PR #12](https://github.com/vendor/lib/issues/12)", ""),
                             ("PR #12 (https://github.com/vendor/lib/pull/12)", ""),
                             ("vendor/lib/pull/12", ""),
                             ("//github.com/vendor/lib/pull/12", ""),
                             ("localhost:3000/vendor/lib/pull/12", "")):
            self.names_nothing(words, after)

    def test_a_link_in_this_repository_keeps_its_words(self):
        for words, after in (("[PR #12][ours]", "[ours]: https://github.com/me/app/pull/12"),
                             ("[PR #12](https://github.com/me/app/issues/12)", ""),
                             ("me/app/pull/12", ""),
                             (f"[the fix](https://github.com/me/app/commit/{self.sha}) `{self.sha}`", ""),
                             ("[PR #12](./notes.md)", "")):
            (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | x | Live | {words} |\n\n{after}\n")
            self.write_plan()
            self.render()
            code, out = self.judge()
            self.assertEqual(code, 0, words + "\n" + out)


class LongHistoriesCostLittle(Small):
    def test_many_reverts_by_id_cost_a_few_processes(self):
        ids = [self.c(f"f{n}", f"work {n}") for n in range(6)]
        for sha in ids[:5]:
            git(self.repo, "revert", "--no-edit", sha)
        self.table(f"| 1 | x | Live | `{ids[5]}` |")
        real, calls = gitio._run, []

        def counting(args, **kwargs):
            calls.append(args)
            return real(args, **kwargs)
        with mock.patch.object(gitio, "_run", counting):
            self.assertEqual(self.judge()[0], 0)
        self.assertLess(len([c for c in calls if "merge-base" in c]), 2, "a revert's target is looked up, not asked about")

    def processes_for(self, reverts):
        self.repo = self.tmp / f"app{reverts}"
        self.repo.mkdir()
        self.plan_path = self.repo / ".gitdone.json"
        git(self.repo, "init", "-q", "-b", "main")
        bare = self.tmp / f"origin{reverts}.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(bare))
        git(self.repo, "remote", "add", "origin", str(bare))
        keep = self.c("keep")
        for n in range(1, reverts + 1):
            self.c(f"f{n}", f"work {n} (#{n})")
        for n in range(1, reverts + 1):
            git(self.repo, "rm", "-q", f"f{n}.txt")
            git(self.repo, "commit", "-qm", f'Revert "work {n}" (#{n + 10})\n\nReverts me/app#{n}\n')
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
        self.table(f"| 1 | x | Live | `{keep}` |")
        real, calls = gitio._run, []

        def counting(args, **kwargs):
            calls.append(args)
            return real(args, **kwargs)
        with mock.patch.object(gitio, "_run", counting):
            self.assertEqual(self.judge()[0], 0)
        return len(calls)

    def test_many_reverts_by_pull_request_read_the_subjects_once(self):
        self.assertEqual(self.processes_for(8), self.processes_for(1))


class TheThirdPass(Small):
    """What a third reading found in the second round of fixes."""

    def judged(self, *rows, **kwargs):
        self.table(*rows, **kwargs)
        return self.judge()

    def hub(self):
        self.origin(push=False)
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")

    def test_a_link_to_a_site_a_run_or_a_ticket_keeps_its_words(self):
        sha = self.c("work")
        git(self.repo, "tag", "v1.0")
        self.hub()
        self.stub("gh", [merged(12, sha)])
        for words in ("[tag v1.0](https://myapp.example.com/changelog)", f"[`{sha}`](https://ci.example.com/runs/5)", "[PR #12](https://linear.app/me/issue/ABC-12)",
                      "[PR #12](../../pull/12)", f"[`{sha}`](../../commit/{sha})"):
            code, out = self.judged(f"| 1 | x | Live | {words} |")
            self.assertEqual(code, 0, words + "\n" + out)

    def test_an_issue_number_under_ten_hides_no_commit(self):
        for n in range(40):
            sha = self.c(f"work{n}")
            if sha[0].isdigit() and sha[0] != "0":
                break
        self.hub()
        code, out = self.judged(f"| 1 | x | Live | `{sha}`, works around https://github.com/vendor/lib/issues/{sha[0]} |")
        self.assertEqual(code, 0, out)

    def test_a_vendor_kept_as_a_remote_is_not_this_repository(self):
        sha = self.c("work")
        self.hub()
        git(self.repo, "remote", "add", "vendor", "https://github.com/vendor/lib.git")
        self.stub("gh", [merged(12, sha)])
        code, out = self.judged("| 1 | x | Live | waits on [PR #12](https://github.com/vendor/lib/pull/12) |")
        self.assertEqual(code, 3, out)
        self.assertIn("names no commit", out)

    def test_a_merge_whose_branch_took_something_back_has_nothing_left(self):
        self.c("base")
        git(self.repo, "checkout", "-qb", "s")
        real = self.c("real")
        tried = self.c("tried")
        git(self.repo, "revert", "--no-edit", tried)
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge s", "s")
        merge = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "revert", "--no-edit", real)
        code, out = self.judged(f"| 1 | x | Live | `{merge}` |")
        self.assertEqual(code, 1, out)

    def test_a_merge_with_a_commit_thrown_away_inside_has_nothing_left(self):
        self.c("base")
        git(self.repo, "checkout", "-qb", "s")
        self.c("thrown")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "checkout", "-qb", "d")
        real = self.c("real")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "-m", "ours", "s")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge d", "d")
        merge = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "revert", "--no-edit", real)
        self.assertEqual(self.judged(f"| 1 | x | Live | `{merge}` |")[0], 1)

    def test_a_squash_is_not_excused_by_a_line_somebody_else_wrote(self):
        (self.repo / "code.py").write_text("base\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        (self.repo / "code.py").write_text("base\ndef f():\n    return 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add f")
        first = git(self.repo, "rev-parse", "HEAD")
        other = self.c("other")
        (self.repo / "code.py").write_text("base\ndef f():\n    return 1\ndef g():\n    return 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add g")
        (self.repo / "code.py").write_text("base\ndef g():\n    return 1\n")
        git(self.repo, "rm", "-q", "other.txt")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", f'Undo f and other (#9)\n\n* Revert "add f"\n\nThis reverts commit {first}.\n\n* Revert "add other"\n\nThis reverts commit {other}.')
        code, out = self.judged(f"| 1 | f | Live | `{first}` |", f"| 2 | other | Live | `{other}` |")
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {first} was reverted", out)

    def test_a_squash_of_empty_or_oddly_named_files_stops_nothing(self):
        not_on_windows(self, "no file there can have those characters in its name")
        for name in ("__init__.py", 'we"ird.txt'):
            with self.subTest(name):
                repo = self.tmp / f"r{abs(hash(name))}"
                repo.mkdir()
                git(repo, "init", "-q", "-b", "main")
                self.repo, self.plan_path = repo, repo / ".gitdone.json"
                self.c("base")
                (repo / name).write_text("")
                git(repo, "add", ".")
                git(repo, "commit", "-qm", "add it")
                first = git(repo, "rev-parse", "HEAD")
                other = self.c("other")
                git(repo, "rm", "-q", name, "other.txt")
                git(repo, "commit", "-qm", f"Undo them (#9)\n\nThis reverts commit {first}.\n\nThis reverts commit {other}.")
                later = self.c("later")
                code, out = self.judged(f"| 1 | later | Live | `{later}` |")
                self.assertEqual(code, 0, out)

    def test_ours_of_a_commit_with_an_oddly_named_file(self):
        not_on_windows(self, "no file there can have those characters in its name")
        self.c("base")
        git(self.repo, "checkout", "-qb", "side")
        (self.repo / 'we"ird.txt').write_text("feature\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "feature")
        taken = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        self.c("other")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "-m", "merge side", "side")
        code, out = self.judged(f"| 1 | x | Live | `{taken}` |")
        self.assertEqual(code, 3, out)

    def test_a_view_leaves_a_secret_under_skip_worktree_alone(self):
        (self.repo / "settings.env").write_text("TOKEN=template\n")
        git(self.repo, "add", "settings.env")
        git(self.repo, "commit", "-qm", "m")
        git(self.repo, "update-index", "--skip-worktree", "settings.env")
        (self.repo / "settings.env").write_text("TOKEN=my-real-secret\n")
        (self.repo / "status-table.md").write_text("### 1. D (1)\n\n| 1 | x | Not built | |\n")
        self.write_plan(status_out="settings.env")
        self.assertEqual(self.render(), 2)
        self.assertEqual((self.repo / "settings.env").read_text(), "TOKEN=my-real-secret\n")

    def test_a_plan_named_by_hand_beside_another_plans_pointer_has_not_moved(self):
        self.c("work")
        (self.repo / "sub").mkdir()
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | A | Partial | x |\n")
        self.write_plan()
        (self.repo / "sub" / "table.md").write_text(f"### 1. E (1)\n\n{HEAD}| 1 | B | Partial | y |\n")
        second = self.repo / "sub" / "plan.json"
        second.write_text(json.dumps({"status_doc": "table.md", "status_out": "VIEW.md", "repo": "..", "title": "Sub", "evidence_pattern": "RELEASE-[0-9]+"}))
        self.render()
        self.run_cli("render", "--write", "--plan", str(second))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        second.write_text(json.dumps({"status_doc": "table.md", "status_out": "VIEW.md", "repo": "..", "title": "Sub"}))
        self.run_cli("render", "--write", "--plan", str(second))
        git(self.repo, "add", "-A")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--plan", "sub/plan.json")
        self.assertIn('evidence_pattern was "RELEASE-[0-9]+", now null', done.stdout)
        self.assertNotIn("moved", done.stdout)

    def test_a_link_as_the_named_plan_stays_out_of_an_unrelated_commit(self):
        self.c("work")
        (self.repo / "conf").mkdir()
        (self.repo / "src").mkdir()
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | A | Partial | x |\n")
        (self.repo / "conf" / "real.json").write_text(json.dumps({"status_doc": "../status-table.md", "repo": "..", "title": "T"}))
        os.symlink("real.json", self.repo / "conf" / "plan.json")
        self.plan_path.write_text('{"plan":"conf/plan.json"}')
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        (self.repo / "src" / "x.py").write_text("x\n")
        git(self.repo, "add", "src/x.py")
        done = self.in_repo(sys.executable, str(ENGINE), "check", "--if-staged", "--strict")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_an_autolink_is_a_note(self):
        self.c("work")
        self.assertEqual(self.judged("| 1 | A | Partial | <https://example.com/issue/5> |")[0], 0)

    def test_a_key_called_status_is_yours_and_a_bad_from_gets_the_plans_words(self):
        self.c("work")
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | A | Partial | x |\n")
        self.write_plan(status="active")
        self.assertEqual(self.render(), 0)
        self.write_plan(sections=[{"from": ["x"]}])
        code, out = self.plain()
        self.assertEqual(code, 2)
        self.assertNotIn("TypeError", out)

    def test_nine_bytes_of_plan_ask_for_little(self):
        self.write_plan(groups=[{"label": "g", "domains": "1-1000000"}])
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | A | Partial | x |\n")
        self.assertEqual(self.plain()[0], 2)

    def test_many_rows_citing_merges_cost_a_few_processes(self):
        self.c("base")
        merges = []
        for n in range(5):
            git(self.repo, "checkout", "-qb", f"s{n}")
            self.c(f"s{n}")
            git(self.repo, "checkout", "-q", "main")
            git(self.repo, "merge", "-q", "--no-ff", "-m", f"merge {n}", f"s{n}")
            merges.append(git(self.repo, "rev-parse", "HEAD"))
        unrelated = self.c("unrelated")
        git(self.repo, "revert", "--no-edit", unrelated)

        def count(rows):
            self.table(*rows)
            real, calls = gitio._run, []

            def counting(args, **kwargs):
                calls.append(args)
                return real(args, **kwargs)
            with mock.patch.object(gitio, "_run", counting):
                self.assertEqual(self.judge()[0], 0)
            return len(calls)
        self.assertLessEqual(count([f"| {i + 1} | x{i} | Live | `{m}` |" for i, m in enumerate(merges)]), count([f"| 1 | x | Live | `{merges[0]}` |"]))


class TheFourthPass(Small):
    """What a fourth reading found in the third round of fixes."""

    def judged(self, *rows, **kwargs):
        self.table(*rows, **kwargs)
        return self.judge()

    def read(self, text):
        return parse(text, KINDS)

    def body(self, extra=""):
        return f"### 1. D (1)\n\n{HEAD}| 1 | a | Live | x |\n{extra}"

    def test_a_table_line_with_no_leading_pipe_is_a_table_line(self):
        for extra in ("x | B | Live | no commit anywhere\n", "​| 2 | B | Live | no commit anywhere |\n", "[x]: y | B | Live | no commit anywhere\n"):
            self.assertTrue(self.read(self.body(extra)).strays, extra)

    def test_a_table_with_no_leading_pipes_is_a_table(self):
        for doc in ("### 1. Payments (1)\n\nItem | Name | Status | Note\n--- | --- | --- | ---\na | Stripe | Live | shipped\n",
                    "### 1. Payments (2)\n\nFeature | Status | Note\n--- | --- | ---\nStripe | Live | shipped\nRefunds | Not built |\n"):
            table = self.read(doc)
            self.assertTrue(table.strays and table.problems, doc)

    def test_a_sentence_with_pipes_away_from_any_table_stays_free(self):
        self.assertEqual(self.read(self.body("\nStatuses here: Live | Built, not live | Partial | Not built\n")).strays, [])
        self.assertEqual(self.read(self.body("\nRun `a | b | live` to see it.\n")).strays, [])

    def test_a_merge_with_only_a_table_edit_or_an_empty_commit_left_has_nothing_left(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                self.setUp()
                self.origin(push=False)
                self.c("a")
                self.table("| 1 | x | Not built | |")
                git(self.repo, "add", "-A")
                git(self.repo, "commit", "-qm", "tracker")
                git(self.repo, "checkout", "-qb", "pr")
                code = self.c("feature", "the feature")
                if empty:
                    self.empty("ci: retrigger")
                else:
                    with (self.repo / "status-table.md").open("a") as handle:
                        handle.write("\n")
                    git(self.repo, "add", "-A")
                    git(self.repo, "commit", "-qm", "update the table")
                git(self.repo, "checkout", "-q", "main")
                git(self.repo, "merge", "-q", "--no-ff", "pr", "-m", "Merge pull request #12 from me/pr")
                merge = git(self.repo, "rev-parse", "HEAD")
                git(self.repo, "revert", "--no-edit", code)
                git(self.repo, "push", "-q", "origin", "main")
                git(self.repo, "remote", "set-url", "origin", "https://github.com/me/app.git")
                self.stub("gh", [merged(12, merge)])
                out_code, out = self.judged(f"| 1 | the merge | Live | `{merge}` |", "| 2 | the pull request | Live | PR #12 |")
                self.assertEqual(out_code, 1, out)
                self.assertIn("PR #12 was reverted", out)

    def test_a_merge_whose_branch_reverted_something_older_stands(self):
        older = self.c("older", "add older")
        git(self.repo, "checkout", "-qb", "s")
        git(self.repo, "revert", "--no-edit", older)
        self.c("real")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "s", "-m", "merge s")
        merge = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(self.judged(f"| 1 | the merge | Live | `{merge}` |")[0], 0)

    def test_a_squash_taking_what_was_left_of_a_commit_reverts_it(self):
        (self.repo / "code.py").write_text("base\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        (self.repo / "code.py").write_text("base\na = 1\nc = 3\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add a and c")
        first = git(self.repo, "rev-parse", "HEAD")
        other = self.c("other")
        (self.repo / "code.py").write_text("base\na = 2\nc = 3\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "change a")
        (self.repo / "code.py").write_text("base\na = 2\n")
        git(self.repo, "rm", "-q", "other.txt")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", f'Undo them (#9)\n\n* Revert "add a and c"\n\nThis reverts commit {first}.\n\n* Revert "add other"\n\nThis reverts commit {other}.')
        code, out = self.judged(f"| 1 | a and c | Live | `{first}` |", f"| 2 | other | Live | `{other}` |")
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {first} was reverted", out)

    def test_a_squash_of_a_submodule_bump_or_an_odd_name_stops_nothing(self):
        self.c("base")
        (self.repo / "o\xe9.txt").write_text("x\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "add it")
        first = git(self.repo, "rev-parse", "HEAD")
        gitlink = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-index", "--add", "--cacheinfo", f"160000,{gitlink},sub")
        git(self.repo, "commit", "-qm", "bump the submodule")
        bump = git(self.repo, "rev-parse", "HEAD")
        other = self.c("other")
        git(self.repo, "update-index", "--force-remove", "sub")
        git(self.repo, "rm", "-q", "other.txt")
        git(self.repo, "commit", "-qm", f"Undo them (#9)\n\nThis reverts commit {bump}.\n\nThis reverts commit {other}.\n\nThis reverts commit {first[:8]}0.")
        later = self.c("later")
        code, out = self.judged(f"| 1 | later | Live | `{later}` |")
        self.assertEqual(code, 0, out)

    def test_what_a_comment_or_a_list_item_hides_in_a_domain_is_said(self):
        for extra in ("\nWords <!-- not a comment once a table interrupts them\n| Item | Name | Status | Note |\n| x | B | Live | no commit --> |\n",
                      "\n1. And also:\n\n    | Feature | Name | Status | Note |\n    |---|---|---|---|\n    | x | B | Live | no commit anywhere |\n",
                      "\n1. And also:\n\n   These are the rest of it.\n\n    | # | Name | Status | Note |\n    |---|---|---|---|\n    | 2 | B | Live | no commit anywhere |\n"):
            self.assertTrue(self.read(self.body(extra)).strays, extra)

    def test_an_empty_heading_or_a_counts_table_ends_no_domain(self):
        for extra in ("\n###### \n\n| Item | Name | Status | Note |\n|---|---|---|---|\n| x | B | Live | no commit |\n",
                      "\n#### &nbsp;\n\n| Item | Name | Status | Note |\n|---|---|---|---|\n| x | B | Live | no commit |\n",
                      "\n| # | Domain | All | Live |\n|---|---|---|---|\n| 1 | D | 1 | 0 |\n\n| Item | Name | Status | Note |\n|---|---|---|---|\n| x | B | Live | no commit |\n"):
            table = self.read(self.body(extra))
            self.assertTrue(table.strays or table.problems, extra)

    def test_a_rule_ends_nothing(self):
        for doc in (f"### 1. Payments (2)\n---\n\n{HEAD}| 1 | a | Live | x |\n| 2 | b | Not built | |\n",
                    f"### 1. Payments (2)\n\n{HEAD}| 1 | a | Live | x |\n\n<!-- note -->\n---\n\n| 2 | b | Not built | |\n"):
            table = self.read(doc)
            self.assertEqual(list(table.rows), [1, 2], doc)
            self.assertEqual((table.strays, table.problems), ([], []), doc)

    def test_a_table_under_an_underlined_heading_is_told_to_take_a_heading(self):
        self.assertTrue(self.read(self.body("\nThe phases\n-----\n\n| Phase | Weeks |\n|---|---|\n| 1 | three |\n")).strays)

    def test_a_row_with_a_leading_space_under_the_counts_table_is_read(self):
        table = self.read(f"### 1. D (2)\n\n{HEAD}| 1 | a | Live | x |\n\n| # | Domain | All | Live |\n|---|---|---|---|\n| 1 | D | 2 | 1 |\n | 2 | b | Not built | |\n")
        self.assertEqual(list(table.rows), [1, 2])

    def test_a_file_name_with_a_newline_shifts_no_answer(self):
        not_on_windows(self, "no file there can have a newline in its name")
        self.c("base")
        git(self.repo, "checkout", "-qb", "side")
        (self.repo / "a\nb.txt").write_text("x\n")
        (self.repo / "plain.txt").write_text("y\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "odd")
        odd = git(self.repo, "rev-parse", "HEAD")
        taken = self.c("taken")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "-s", "ours", "--no-ff", "side", "-m", "take nothing")
        code, out = self.judged(f"| 1 | x | Live | `{taken}` |", f"| 2 | y | Live | `{odd}` |")
        self.assertEqual(code, 3, out)
        self.assertIn(f"commit {taken} reached main through", out)

    def test_a_pull_request_that_deletes_the_pointer_and_brings_a_new_plan_is_said(self):
        self.c("a")
        (self.repo / "status-table.md").write_text(f"### 1. D (1)\n\n{HEAD}| 1 | A | Partial | x |\n")
        self.write_plan()
        self.render()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracker")
        base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "rm", "-q", ".gitdone.json")
        new = self.repo / "plan.json"
        new.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "title": "T", "kinds": [{"name": "Live", "weight": 1, "evidence": "release"}, {"name": "Not built", "weight": 1}]}))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "a new plan")
        from gitdone import ci
        self.assertTrue(any("moved here" in line for line in ci.rule_changes(Plan(new), base)))
