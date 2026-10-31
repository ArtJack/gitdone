"""The local gate end to end: a real `git commit` in the repository that holds the table, with a real hook."""
import json
import os
import pathlib
import re
import subprocess
import unittest

from helpers import IDENTITY, ProjectCase, clean_env, git, needs_sh


class Gate(ProjectCase):
    def setUp(self):
        super().setUp()
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")  # the example's pull request cannot be proven with no remote
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "init", "-q", "-b", "main")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "--no-verify", "-m", "first")
        code, out, err = self.cli("install-hook")
        self.assertEqual(code, 0, err)
        self.hook = self.project / ".git" / "hooks" / "pre-commit"

    def run_git(self, *args, cwd=None):
        return subprocess.run(["git", *IDENTITY, *args], cwd=str(cwd or self.project), env=clean_env(),
                              capture_output=True, text=True)

    def try_commit(self, *paths):
        for path in paths:
            git(self.project, "add", path)
        return self.run_git("commit", "-q", "-m", "change")


class Commits(Gate):
    def test_a_good_commit_to_the_table_passes(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_commit_to_the_plan_alone_is_judged(self):
        data = json.loads(self.plan_path.read_text())
        data["title"] = "Another title"
        self.plan_path.write_text(json.dumps(data))
        done = self.try_commit("plan.json")
        self.assertNotEqual(done.returncode, 0, "the staged view no longer matches the staged plan")
        self.assertIn("differs from a fresh render", done.stderr)

    def test_a_sha_off_the_default_branch_stops_the_commit(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"commit {self.sha_stray[:7]} is not on main", done.stderr)

    def test_a_sha_on_main_of_the_named_repository_passes_inside_a_hook(self):
        # Under a commit's GIT_DIR and GIT_INDEX_FILE, `git -C app` must still look at app.
        self.set_row(10, "Live", f"`{self.sha_old[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_commit_that_passes_says_little(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertEqual(done.returncode, 0, done.stderr)
        said = done.stdout + done.stderr
        self.assertNotIn("view:", said)
        self.assertRegex(said, r"result: PASS")

    def test_a_refused_commit_says_all_of_it(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("view:", done.stderr)
        self.assertIn("FAIL row 10", done.stderr)

    def test_a_live_row_with_nothing_behind_it_stops_the_commit(self):
        self.set_row(10, "Live", "no release named")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("row 10 names no commit, pull request or tag", done.stderr)

    def test_a_pull_request_nothing_could_ever_confirm_stops_the_commit(self):
        self.set_row(10, "Live", "PR #999")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("has no remote, so nothing could confirm it", done.stderr)

    def test_a_lenient_hook_only_warns_about_it(self):
        code, _, err = self.cli("install-hook", "--lenient")
        self.assertEqual(code, 0, err)
        self.assertNotIn("--strict", self.hook.read_text())
        self.set_row(10, "Live", "no release named")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("row 10 names no commit", done.stdout + done.stderr)

    def test_the_hook_is_strict_unless_told_otherwise(self):
        self.assertIn("--if-staged --strict", self.hook.read_text())


class WhatIsJudged(Gate):
    """The gate judges what the commit will contain, not what happens to be on disk."""

    def test_a_table_staged_without_its_view_stops_the_commit(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.try_commit("status-table.md")
        self.assertNotEqual(done.returncode, 0, "a clone of this commit would fail check")
        self.assertIn("it is right on disk and not staged: git add STATUS.md", done.stderr)

    def test_a_view_wrong_on_disk_too_says_to_regenerate(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`", view=False)
        done = self.try_commit("status-table.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("run `gitdone render --write`, and stage the plan, the table and STATUS.md together", done.stderr)

    def test_a_bad_row_staged_and_fixed_on_disk_stops_the_commit(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.run_git("commit", "-q", "-m", "change")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"commit {self.sha_stray[:7]} is not on main", done.stderr)

    def test_a_good_commit_passes_with_a_bad_edit_on_disk(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        done = self.run_git("commit", "-q", "-m", "change")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_plan_broken_on_disk_does_not_stop_a_good_commit(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        self.plan_path.write_text("{ half an edit")
        done = self.run_git("commit", "-q", "-m", "change")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_broken_plan_in_the_commit_stops_it(self):
        self.plan_path.write_text("{ half an edit")
        done = self.try_commit("plan.json")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not valid JSON", done.stderr)

    def test_a_view_left_out_of_the_repository_stops_the_commit(self):
        git(self.project, "rm", "-q", "--cached", "STATUS.md")
        done = self.run_git("commit", "-q", "-m", "drop the view")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("STATUS.md is not in this commit", done.stderr)

    def test_commit_with_a_path_uses_the_commits_own_index(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        done = self.run_git("commit", "-q", "-m", "x", "status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)

    def test_commit_a_uses_the_commits_own_index(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        done = self.run_git("commit", "-q", "-a", "-m", "x")
        self.assertNotEqual(done.returncode, 0)


class OtherCommits(Gate):
    def note(self):
        (self.project / "note.txt").write_text("x\n")
        return "note.txt"

    def test_a_commit_that_does_not_touch_the_tracker_is_left_alone(self):
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`", view=False)  # broken, and not this commit's business
        done = self.try_commit(self.note())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout + done.stderr, "")

    def test_a_plan_deleted_from_disk_does_not_stop_it(self):
        self.plan_path.unlink()
        done = self.try_commit(self.note())
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_table_that_cannot_be_read_does_not_stop_it(self):
        self.table_path.write_bytes(b"\xff\xfe")
        done = self.try_commit(self.note())
        self.assertEqual(done.returncode, 0, done.stderr)


class WorktreesAndMerges(Gate):
    def test_a_linked_worktree_judges_its_own_commit(self):
        worktree = self.tmp / "wt"
        git(self.project, "worktree", "add", "-q", "-b", "side", str(worktree))
        table = worktree / "status-table.md"
        text = table.read_text().replace("| 10 | Staff override | Partial |", f"| 10 | Staff override | Live | `{self.sha_stray[:7]}` |")
        table.write_text(text)
        git(worktree, "add", "status-table.md")
        done = self.run_git("commit", "-q", "-m", "x", cwd=worktree)
        self.assertNotEqual(done.returncode, 0, "the hook is shared, and must not judge the main checkout's plan")
        self.assertIn("is not on main", done.stderr)

    def test_a_clean_merge_that_breaks_the_table_is_stopped(self):
        git(self.project, "checkout", "-q", "-b", "side")
        self.set_row(10, "Live", f"`{self.sha_stray[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        git(self.project, "commit", "-q", "--no-verify", "-m", "bad row")
        git(self.project, "checkout", "-q", "main")
        (self.project / "note.txt").write_text("x\n")
        git(self.project, "add", "note.txt")
        git(self.project, "commit", "-q", "-m", "so the merge is not a fast-forward")
        done = self.run_git("merge", "-q", "--no-ff", "-m", "merge", "side")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is not on main", done.stderr)

    def test_a_clean_merge_with_a_true_table_goes_through(self):
        git(self.project, "checkout", "-q", "-b", "side")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        git(self.project, "add", "status-table.md", "STATUS.md")
        git(self.project, "commit", "-q", "-m", "good row")
        git(self.project, "checkout", "-q", "main")
        (self.project / "note.txt").write_text("x\n")
        git(self.project, "add", "note.txt")
        git(self.project, "commit", "-q", "-m", "so the merge is not a fast-forward")
        done = self.run_git("merge", "-q", "--no-ff", "-m", "merge", "side")
        self.assertEqual(done.returncode, 0, done.stderr)


class Installing(Gate):
    def test_both_hooks_are_written(self):
        for name in ("pre-commit", "pre-merge-commit"):
            self.assertIn("gitdone gate", (self.project / ".git" / "hooks" / name).read_text())

    def test_a_hook_someone_else_wrote_is_not_replaced(self):
        self.hook.write_text("#!/bin/sh\nexit 0\n")
        code, _, err = self.cli("install-hook")
        self.assertEqual(code, 2)
        self.assertIn("is not this gate", err)
        self.assertEqual(self.hook.read_text(), "#!/bin/sh\nexit 0\n")

    def test_reinstalling_replaces_our_own(self):
        code, out, err = self.cli("install-hook")
        self.assertEqual(code, 0, err)
        self.assertIn("installed", out)

    def test_a_hooks_path_inside_the_work_tree_is_refused(self):
        git(self.project, "config", "core.hooksPath", ".githooks")
        code, _, err = self.cli("install-hook")
        self.assertEqual(code, 2)
        self.assertIn("core.hooksPath points inside the work tree", err)
        self.assertFalse((self.project / ".githooks").exists())

    def test_the_hook_is_not_a_tracked_file(self):
        self.assertNotIn("pre-commit", git(self.project, "ls-files"))

    def test_a_table_outside_git_has_nowhere_for_a_hook(self):
        data = json.loads(self.plan_path.read_text())
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "t.md").write_text(self.table_path.read_text())
        data["status_doc"] = str(outside / "t.md")
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("install-hook")
        self.assertEqual(code, 2)
        self.assertIn("is not in a git repository", err)


class FindingTheEngine(Gate):
    """The hook outlives whatever installed it: a plugin update, a moved checkout, a replaced Python."""

    def setUp(self):
        needs_sh(self)
        super().setUp()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "tools"
        self.bin.mkdir()
        self.gone()

    def gone(self):
        text = self.hook.read_text()
        text = re.sub(r"^home=.*$", "home=/gone", text, flags=re.M)
        self.hook.write_text(text)

    def path(self):
        """PATH with no engine on it, whatever this machine has installed."""
        keep = [d for d in os.environ["PATH"].split(os.pathsep) if not (pathlib.Path(d) / "gitdone").exists()
                and not (pathlib.Path(d) / "uvx").exists()]
        return os.pathsep.join([str(self.bin)] + keep)

    def commit_with(self, *paths):
        for path in paths:
            git(self.project, "add", path)
        return subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", "change"], cwd=str(self.project),
                              env={**clean_env(), "HOME": str(self.home), "PATH": self.path()},
                              capture_output=True, text=True)

    def tool(self, directory, name, script):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(script)
        path.chmod(0o755)
        return path

    def test_a_commit_that_does_not_touch_the_tracker_goes_through(self):
        (self.project / "note.txt").write_text("x\n")
        done = self.commit_with("note.txt")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_commit_that_touches_the_tracker_cannot_be_judged_and_is_stopped(self):
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.commit_with("status-table.md", "STATUS.md")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("engine not found", done.stderr)

    def test_the_command_on_path_is_used(self):
        self.tool(self.bin, "gitdone", '#!/bin/sh\necho "from PATH: $*" >&2\nexit 7\n')
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.commit_with("status-table.md", "STATUS.md")
        self.assertIn("from PATH: check --plan", done.stderr)
        self.assertIn("--if-staged", done.stderr)

    def test_the_plugins_newest_copy_is_used(self):
        cache = self.home / ".claude" / "plugins" / "cache" / "some-market" / "gitdone"
        self.tool(cache / "1.0.0" / "bin", "gitdone", '#!/bin/sh\necho old >&2\nexit 7\n')
        self.tool(cache / "1.1.0" / "bin", "gitdone", '#!/bin/sh\necho "from plugin: $*" >&2\nexit 7\n')
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.commit_with("status-table.md", "STATUS.md")
        self.assertIn("from plugin: check --plan", done.stderr)

    def test_uvx_is_the_last_resort_and_only_for_a_commit_that_touches_the_tracker(self):
        self.tool(self.bin, "uvx", '#!/bin/sh\necho "from uvx: $*" >&2\nexit 7\n')
        (self.project / "note.txt").write_text("x\n")
        self.assertEqual(self.commit_with("note.txt").returncode, 0)
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.commit_with("status-table.md", "STATUS.md")
        self.assertIn("from uvx: gitdone check --plan", done.stderr)


class TheInstalledHook(Gate):
    def test_a_replaced_python_falls_back_to_the_one_on_path(self):
        self.hook.write_text(re.sub(r"^python=.*$", "python=/gone/python3", self.hook.read_text(), flags=re.M))
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        done = self.try_commit("status-table.md", "STATUS.md")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_it_names_no_folder_a_stranger_would_not_have(self):
        self.assertNotIn("Projects/gitdone/gitdone", self.hook.read_text())


if __name__ == "__main__":
    unittest.main()
