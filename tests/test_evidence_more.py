"""Evidence beyond a commit and a pull request: tags, GitLab merge requests, and a claim that held until it was reverted."""
import json
import os
import stat
import unittest
from unittest import mock

from helpers import IDENTITY, ProjectCase, commit, git, needs_sh
from gitdone import evidence


class Words(unittest.TestCase):
    def test_tags_need_the_word_tag_or_a_version_after_release(self):
        self.assertEqual(evidence.find_tags("tag v1.2.0"), ["v1.2.0"])
        self.assertEqual(evidence.find_tags("tag `prod-2026`"), ["prod-2026"])
        self.assertEqual(evidence.find_tags("in release v1.2.0."), ["v1.2.0"])
        self.assertEqual(evidence.find_tags("release 2.0"), ["2.0"])

    def test_prose_about_releases_is_not_a_tag(self):
        for text in ("release notes", "the next release", "released it", "tag along", "needs v2.0 of the API", "tag the commit"):
            self.assertEqual(evidence.find_tags(text), [], text)

    def test_merge_requests(self):
        self.assertEqual(evidence.find_mrs("MR !12"), [12])
        self.assertEqual(evidence.find_mrs("merge request 12"), [12])
        self.assertEqual(evidence.find_mrs("https://gitlab.example/x/-/merge_requests/12"), [12])
        self.assertEqual(evidence.find_mrs("!12"), [])


class Tags(ProjectCase):
    def tag(self, name, sha):
        git(self.app, "tag", name, sha)

    def test_a_tag_on_the_default_branch_is_verified(self):
        self.tag("v1.0.0", self.sha_main)
        self.set_row(9, "Live", "tag v1.0.0")
        code, out, _ = self.cli("check", "--strict", "--offline")
        self.assertIn("is on main", self.cli("shipped", "10", "tag v1.0.0", "--offline")[1])
        self.assertNotIn("row 9", out)

    def test_a_tag_off_the_default_branch_is_a_contradiction(self):
        self.tag("v9", self.sha_stray)
        self.set_row(9, "Live", "tag `v9`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("tag v9 is not on main", out)

    def test_a_tag_that_does_not_exist_is_a_contradiction_with_no_remote(self):
        self.set_row(9, "Live", "tag v7.7.7")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("tag v7.7.7 is not in", out)

    def test_shipped_refuses_a_missing_tag(self):
        code, _, err = self.cli("shipped", "10", "tag v7.7.7")
        self.assertEqual(code, 1)
        self.assertIn("is not in", err)


class Reverts(ProjectCase):
    def setUp(self):
        super().setUp()
        self.feature = commit(self.app, "feature.txt", "x\n", "Add the feature")

    def revert(self, sha):
        git(self.app, "revert", "--no-edit", sha)
        return git(self.app, "rev-parse", "HEAD")

    def test_a_reverted_commit_contradicts_its_row(self):
        self.set_row(9, "Live", f"`{self.feature[:7]}`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)
        undoing = self.revert(self.feature)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1)
        self.assertIn(f"commit {self.feature[:7]} was reverted on main by {undoing[:7]}", out)

    def test_a_revert_of_the_revert_puts_it_back(self):
        self.set_row(9, "Live", f"`{self.feature[:7]}`")
        undoing = self.revert(self.feature)
        self.revert(undoing)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)

    def test_a_third_revert_takes_it_out_again(self):
        self.set_row(9, "Live", f"`{self.feature[:7]}`")
        undoing = self.revert(self.feature)
        back = self.revert(undoing)
        self.revert(back)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn(f"commit {self.feature[:7]} was reverted on main by {undoing[:7]}", out)

    def test_a_row_that_names_the_second_landing_stands_on_it(self):
        self.revert(self.feature)
        again = commit(self.app, "feature.txt", "x\ny\n", "Land the feature again")
        self.set_row(9, "Live", f"`{self.feature[:7]}`, then `{again[:7]}`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("was reverted", out, "what does not hold beside what does is still said")

    def test_shipped_refuses_a_reverted_commit(self):
        self.revert(self.feature)
        code, _, err = self.cli("shipped", "10", self.feature[:7])
        self.assertEqual(code, 1)
        self.assertIn("was reverted", err)

    def test_a_revert_on_another_branch_does_not_count(self):
        git(self.app, "checkout", "-q", "-b", "side")
        self.revert(self.feature)
        git(self.app, "checkout", "-q", "main")
        self.set_row(9, "Live", f"`{self.feature[:7]}`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_words_that_only_mention_a_revert_are_not_one(self):
        commit(self.app, "note.txt", "x\n", f"Decide not to revert {self.feature[:7]}: This reverts nothing")
        self.set_row(9, "Live", f"`{self.feature[:7]}`")
        self.assertEqual(self.cli("check", "--offline")[0], 0)


class RevertsThatCannotBeRead(ProjectCase):
    def test_it_stops_rather_than_read_as_no_reverts(self):
        from gitdone import gitio
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        real = gitio.git

        def failing_log(repo, *args, **kwargs):
            if args and args[0] == "log" and "--extended-regexp" in args:
                return gitio.Done(124, "", "git did not answer in 30s")
            return real(repo, *args, **kwargs)
        with mock.patch.object(gitio, "git", failing_log):
            code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2, "git failing is not an answer, either way")
        self.assertIn("git could not answer which commits were reverted on main in app: git did not answer in 30s", err)


class RevertedPullRequests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.add_remote()
        self.feature = commit(self.app, "feature.txt", "x\n", "Add the feature (#30)")
        self.push()
        self.fake_gh(prs=[{"number": 12, "state": "MERGED", "baseRefName": "main"},
                          {"number": 30, "state": "MERGED", "baseRefName": "main", "mergeCommit": {"oid": self.feature}}])

    def test_a_merged_pull_request_is_verified(self):
        self.set_row(9, "Live", "PR #30")
        code, out, _ = self.cli("check")
        self.assertNotIn("FAIL", out)

    def test_git_revert_of_its_merge_commit_contradicts_it(self):
        self.set_row(9, "Live", "PR #30")
        git(self.app, "revert", "--no-edit", self.feature)
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1)
        self.assertIn("PR #30 was reverted on main by", out)

    def test_the_github_revert_button_contradicts_it(self):
        self.set_row(9, "Live", "PR #30")
        (self.app / "feature.txt").unlink()
        git(self.app, "add", "-A")
        git(self.app, "commit", "-q", "-m", 'Revert "Add the feature" (#31)\n\nReverts someone/kiosk#30')
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1)
        self.assertIn("PR #30 was reverted on main by", out)

    def test_a_reverted_revert_of_a_pull_request_puts_it_back(self):
        self.set_row(9, "Live", "PR #30")
        git(self.app, "commit", "-q", "--allow-empty", "-m", 'Revert "Add the feature" (#31)\n\nReverts someone/kiosk#30')
        undoing = git(self.app, "rev-parse", "HEAD")
        git(self.app, "commit", "-q", "--allow-empty", "-m", f"Reapply the feature\n\nThis reverts commit {undoing}.")
        code, out, _ = self.cli("check")
        self.assertNotIn("PR #30", out)


class BeyondTheListLimit(ProjectCase):
    def test_a_pull_request_past_the_limit_is_asked_about_on_its_own(self):
        needs_sh(self)
        self.add_remote()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        many = self.tmp / "many.json"
        many.write_text(json.dumps([{"number": n, "state": "MERGED", "baseRefName": "main"} for n in range(2000, 3000)]))
        gh = bin_dir / "gh"
        gh.write_text(f'#!/bin/sh\nif [ "$2" = "list" ]; then cat "{many}"; else echo \'{{"number": 12, "state": "MERGED", "baseRefName": "main", "mergeCommit": {{"oid": "{self.sha_main}"}}}}\'; fi\n')
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
            self.set_row(9, "Live", "PR #12")
            code, out, _ = self.cli("check")
        self.assertNotIn("row 9", out)


class MergeRequests(ProjectCase):
    def fake_glab(self, answer=None, fail=None):
        needs_sh(self)
        self.add_remote()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        path = self.tmp / "glab.json"
        path.write_text(json.dumps(answer or {}))
        glab = bin_dir / "glab"
        glab.write_text(f'#!/bin/sh\necho "{fail}" >&2\nexit 1\n' if fail else f'#!/bin/sh\ncat "{path}"\n')
        glab.chmod(glab.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def check_row(self, words):
        self.set_row(9, "Live", words)
        return self.cli("check")

    def test_a_merged_one_is_verified(self):
        self.fake_glab({"iid": 12, "state": "merged", "target_branch": "main", "merge_commit_sha": self.sha_main})
        code, out, _ = self.check_row("MR !12")
        self.assertNotIn("row 9", out)

    def test_an_open_one_is_a_contradiction(self):
        self.fake_glab({"iid": 12, "state": "opened", "target_branch": "main"})
        code, out, _ = self.check_row("MR !12")
        self.assertEqual(code, 1)
        self.assertIn("MR !12 is opened, not merged", out)

    def test_merged_elsewhere_is_not_proven(self):
        self.fake_glab({"iid": 12, "state": "merged", "target_branch": "develop"})
        code, out, _ = self.check_row("MR !12")
        self.assertIn("WARN row 9 (Live): MR !12 merged into develop, not main", out)

    def test_glab_failing_is_unverified_not_a_failure(self):
        self.fake_glab(fail="not logged in")
        code, out, _ = self.check_row("MR !12")
        self.assertIn("glab could not answer", out)
        self.assertNotIn("FAIL row 9", out)

    def test_a_reverted_merge_commit_contradicts_it(self):
        feature = commit(self.app, "f.txt", "x\n", "Add")
        self.fake_glab({"iid": 12, "state": "merged", "target_branch": "main", "merge_commit_sha": feature})
        git(self.app, *IDENTITY, "revert", "--no-edit", feature)
        code, out, _ = self.check_row("MR !12")
        self.assertEqual(code, 1)
        self.assertIn("was reverted", out)


class Shallow(ProjectCase):
    def test_a_shallow_clone_says_what_to_do(self):
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", "--depth", "1", "--branch", "stray", f"file://{self.app}", str(clone))
        data = json.loads(self.plan_path.read_text())
        data["repo"] = str(clone)
        self.plan_path.write_text(json.dumps(data))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("fetch-depth: 0", out)


if __name__ == "__main__":
    unittest.main()
