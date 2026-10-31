import json
import os
import subprocess
import sys
import unittest

from helpers import ENGINE, ProjectCase, git


class ViewAndCounts(ProjectCase):
    def test_the_example_passes_with_warnings_and_fails_strict(self):
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("view: STATUS.md matches a fresh render, date line aside", out)
        self.assertIn("counts: Launch 11, Later 5, all 16", out)
        self.assertIn("WARN row 9 names no commit, pull request or tag; run `gitdone shipped 9 <commit>`", out)
        self.assertIn("result: PASS with warnings; --strict would fail", out)
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("FAIL row 9 names no commit, pull request or tag", out)

    def test_a_different_date_is_not_a_stale_view(self):
        text = self.view_path.read_text().split("\n")
        text[0] = "# Bramble Kiosk tracker (generated 1999-01-01)"
        self.view_path.write_text("\n".join(text))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)

    def test_a_stale_view_fails(self):
        self.set_row(9, "Partial", "card and PIN", view=False)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL view: STATUS.md differs from a fresh render at line", out)

    def test_a_hand_edit_of_the_view_fails(self):
        self.view_path.write_text(self.view_path.read_text() + "a note\n")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)

    def test_a_missing_view_fails(self):
        self.view_path.unlink()
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL view: STATUS.md does not exist", out)

    def test_counts_that_do_not_sum_fail(self):
        data = json.loads(self.plan_path.read_text())
        data["groups"][0]["total"] = 12
        self.plan_path.write_text(json.dumps(data))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL group Launch: its domains hold 11 rows, the plan says 12", out)

    def test_a_counts_table_that_disagrees_with_its_rows_fails(self):
        text = self.table_path.read_text()
        self.table_path.write_text(text.replace("| 1 | Catalogue search | 4 | 2 | 1 |  | 1 | 0 |", "| 1 | Catalogue search | 4 | 3 | 1 |  | 0 | 0 |"))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("disagrees with its rows", out)

    def test_a_table_with_a_broken_shape_fails_without_a_traceback(self):
        self.set_row(9, "Almost", "soon", view=False)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL row 9: unknown status 'Almost'", out)
        self.assertIn("view: not compared", out)

    def test_a_workstream_outside_the_order_is_noted(self):
        data = json.loads(self.plan_path.read_text())
        data["workstreams"].append({"id": "S4", "name": "New", "rows": [16]})
        self.change_plan(workstreams=data["workstreams"])
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE workstream S4 is in the plan and not in its order", out)


class LiveRows(ProjectCase):
    def settle_row_two(self):
        """The example's pull request is not these tests' question."""
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")

    """A Live row names a release, and git has the last word on a commit."""

    def assert_one_live_problem(self, words):
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn(words, out)
        self.assertIn("result: FAIL", out)
        code_strict, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code_strict, 1, "a contradiction outranks missing evidence")

    def test_a_sha_on_the_default_branch_passes(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        self.set_row(9, "Live", f"Card and PIN; `{self.sha_main[:7]}`.")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertIn("6 verified", out)
        self.assertEqual(code, 0, out)

    def test_strict_means_every_claim_was_checked(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("FAIL row 2: PR #12: offline", out)
        self.assertEqual(self.cli("check", "--offline")[0], 0, "plain check says it is unverified, and passes")

    def test_a_sha_that_is_not_on_the_default_branch_fails(self):
        self.set_row(9, "Live", f"Card and PIN; `{self.sha_stray[:7]}`.")
        self.assert_one_live_problem(f"FAIL row 9 (Live): commit {self.sha_stray[:7]} is not on main")

    def test_a_sha_the_repository_does_not_have_fails(self):
        self.set_row(9, "Live", "Card and PIN; `abcdef1`.")
        self.assert_one_live_problem("FAIL row 9 (Live): commit abcdef1 is not in the repository app")

    def test_a_full_sha_works(self):
        self.set_row(9, "Live", f"released in {self.sha_main}")
        code, out, _ = self.cli("check", "--offline")
        self.assertNotIn("names no commit", out)
        self.assertEqual(code, 0, out)

    def test_a_commit_beside_the_release_is_said_and_does_not_fail_the_default_mode(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`; a later fix waits on `{self.sha_stray[:7]}`.")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn(f"WARN row 9 (Live): commit {self.sha_stray[:7]} is not on main", out)
        self.assertIn("1 verified" if False else "result: PASS with warnings", out)
        code, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3)

    def test_a_disproved_commit_is_never_hidden_by_a_pull_request_nobody_can_check(self):
        self.set_row(9, "Live", "`abcdef1` and PR #12")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 9 (Live): commit abcdef1 is not in the repository app", out)
        self.assertIn("NOTE row 9: PR #12: offline", out)
        code, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3)

    def test_a_row_with_only_contradictions_fails(self):
        self.set_row(9, "Live", f"`abcdef1` and `{self.sha_stray[:7]}`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)

    def test_a_commit_a_remote_may_have_is_a_warning_until_fetched(self):
        self.add_remote()
        self.set_row(9, "Live", "`abcdef1`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 9 (Live): commit abcdef1 is not in app's clone; fetch, or correct it", out)
        self.assertIn("evidence:", out)
        code, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3)

    def test_a_commit_url_is_a_commit(self):
        self.settle_row_two()
        self.add_remote("https://example.invalid/o/r.git")
        self.set_row(9, "Live", f"https://example.invalid/o/r/commit/{self.sha_main}")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_the_named_repository_is_looked_at_whatever_git_dir_the_caller_has(self):
        git(self.project, "init", "-q", "-b", "main")
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        env = {**os.environ, "GIT_DIR": str(self.project / ".git"), "GIT_INDEX_FILE": str(self.project / ".git" / "index")}
        done = subprocess.run([sys.executable, str(ENGINE), "check", "--offline", "--plan", str(self.plan_path)],
                              env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_being_on_any_remote_counts(self):
        self.add_remote(name="upstream")
        git(self.app, "update-ref", "refs/remotes/upstream/main", self.sha_stray)
        self.set_row(9, "Live", f"`{self.sha_stray[:7]}`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)

    def test_being_on_origin_only_counts(self):
        self.add_remote()
        git(self.app, "update-ref", "refs/remotes/origin/main", self.sha_stray)
        self.set_row(9, "Live", f"`{self.sha_stray[:7]}`")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)

    def test_another_default_branch(self):
        git(self.app, "branch", "-m", "main", "trunk")
        self.change_plan(default_branch="trunk")
        self.set_row(9, "Live", f"`{self.sha_stray[:7]}`")
        self.assert_one_live_problem(f"commit {self.sha_stray[:7]} is not on trunk")

    def test_numbers_and_words_are_not_commits(self):
        self.set_row(9, "Live", "2026103 cards were defaced and 12345678 replaced, 1999-01-01.")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("row 9 names no commit", out)

    def test_a_path_with_a_hash_in_it_is_not_a_commit(self):
        self.set_row(9, "Live", "see notes/abc1234/ and run-abc1234")
        code, out, _ = self.cli("check", "--offline")
        self.assertIn("row 9 names no commit", out)
        self.assertEqual(code, 0, out)

    def test_without_a_repo_nothing_can_be_proven_so_strict_fails(self):
        self.change_plan(repo=None)
        self.set_row(9, "Live", "`abcdef1`")
        code, out, _ = self.cli("check", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("FAIL row 9 (Live): commit abcdef1: the plan names no repo", out)
        self.assertEqual(self.cli("check")[0], 0, "the default mode warns")

    def test_a_plan_whose_repo_is_not_a_repository_cannot_run(self):
        self.change_plan(repo="../not-there")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 2, out)
        self.assertIn("is not a git repository", out)

    def test_a_plan_whose_repo_lacks_the_default_branch_cannot_run(self):
        self.change_plan(default_branch="trunk")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 2, out)
        self.assertIn("has no branch trunk", out)


class PullRequests(ProjectCase):
    PRS = [{"number": 12, "state": "MERGED", "baseRefName": "main"},
           {"number": 13, "state": "OPEN", "baseRefName": "main"},
           {"number": 14, "state": "CLOSED", "baseRefName": "main"},
           {"number": 15, "state": "MERGED", "baseRefName": "stack"}]

    def setUp(self):
        super().setUp()
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")

    def test_merged_passes(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("6 verified, 0 unverified", out)  # four Live rows, two Built

    def test_open_fails(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", "PR #13")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL row 2 (Live): PR #13 is open, not merged", out)

    def test_closed_fails(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", "pull request 14")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1, out)
        self.assertIn("PR #14 is closed, not merged", out)

    def test_one_that_does_not_exist_fails(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", "PR #99")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 1, out)
        self.assertIn("PR #99 does not exist on app's remote", out)

    def test_merged_elsewhere_is_not_proven(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", "PR #15")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 2 (Live): PR #15 merged into stack, not main", out)
        self.assertEqual(self.cli("check", "--strict")[0], 3, "merged elsewhere is not on the default branch")

    def test_gh_failing_is_unverified_not_a_contradiction(self):
        self.add_remote()
        self.fake_gh(fail="HTTP 503")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 2: PR #12: gh could not answer: HTTP 503", out)

    def test_no_remote_is_not_proven_and_gh_is_not_asked(self):
        self.fake_gh(self.PRS)
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 2 (Live): PR #12: app has no remote, so nothing could confirm it", out)
        self.assertEqual(self.cli("check", "--strict")[0], 3, "a pull request in a repository with no remote proves nothing")
        self.assertFalse(self.gh_calls.exists())

    def test_offline_is_unverified_and_gh_is_not_asked(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 2: PR #12: offline", out)
        self.assertFalse(self.gh_calls.exists())

    def test_gh_is_asked_once_however_many_rows_name_a_pull_request(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(1, "Live", "PR #12")
        self.cli("check")
        self.assertEqual(len(self.gh_calls.read_text().strip().split("\n")), 1)

    def test_a_pull_request_that_does_not_exist_beside_a_good_commit_is_said(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", f"`{self.sha_main[:7]}` and PR #99")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 2 (Live): PR #99 does not exist", out)
        code, _, _ = self.cli("check", "--strict")
        self.assertEqual(code, 3)

    def test_a_bare_number_sign_is_not_a_pull_request(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        self.set_row(2, "Live", "works; discussed in issue #7, and see #12 in the backlog")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("row 2 names no commit", out)
        code, _, _ = self.cli("check", "--strict")
        self.assertEqual(code, 3)

    def test_every_way_of_writing_a_pull_request(self):
        self.add_remote()
        self.fake_gh(self.PRS)
        for words in ("PR #12", "PR 12", "PRs #12", "pull request 12", "pull request #12", "https://example.invalid/someone/kiosk/pull/12"):
            self.set_row(2, "Live", words)
            code, out, _ = self.cli("check", "--strict")
            self.assertEqual(code, 0, f"{words}: {out}")

    def test_an_unverified_pull_request_fails_strict(self):
        self.add_remote()
        self.fake_gh(fail="offline")
        code, out, _ = self.cli("check", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("gh could not answer: offline", out)


class EvidencePattern(ProjectCase):
    def setUp(self):
        super().setUp()
        self.set_row(1, "Live", f"`{self.sha_main[:7]}`")
        self.set_row(2, "Live", f"`{self.sha_main[:7]}`")

    def test_a_named_ref_is_verified_like_a_commit(self):
        git(self.app, "tag", "v1.2.0", self.sha_main)
        self.change_plan(evidence_pattern=r"\b(?P<ref>v\d+\.\d+\.\d+)\b")
        self.set_row(9, "Live", "in v1.2.0")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_a_ref_off_the_default_branch_fails(self):
        git(self.app, "tag", "v9.9.9", self.sha_stray)
        self.change_plan(evidence_pattern=r"\b(?P<ref>v\d+\.\d+\.\d+)\b")
        self.set_row(9, "Live", "in v9.9.9")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("v9.9.9 is not on main", out)

    def test_a_plain_match_counts_as_named_and_unverified(self):
        self.change_plan(evidence_pattern=r"release note \d+")
        self.set_row(9, "Live", "see release note 7")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 9: 'release note 7' matches the plan's evidence pattern", out)
        self.assertEqual(self.cli("check", "--offline", "--strict")[0], 3, "nothing checked it, so strict does not count it")

    def test_a_bad_pattern_cannot_run(self):
        data = json.loads(self.plan_path.read_text())
        data["evidence_pattern"] = "("
        self.plan_path.write_text(json.dumps(data))
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2)
        self.assertIn("evidence_pattern is not a regular expression", err)


class BuiltRows(ProjectCase):
    def setUp(self):
        super().setUp()
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")  # the example's pull request is not this class's question
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")

    def test_a_branch_that_exists_passes(self):
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_a_branch_that_does_not_exist_fails(self):
        self.set_row(3, "Built, not live (no-such-branch)", "reviewed")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL row 3 (Built, not live): branch no-such-branch does not exist in app", out)

    def test_a_branch_only_on_origin_counts(self):
        self.add_remote()
        git(self.app, "update-ref", "refs/remotes/origin/far-away", self.sha_stray)
        self.set_row(3, "Built, not live (far-away)", "reviewed")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_aliases_stand_for_branches(self):
        self.change_plan(branch_aliases={"R": "reading-lists", "N": "renewals"})
        self.set_row(3, "Built, not live (R, N)", "reviewed")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_each_branch_named_must_exist(self):
        self.set_row(3, "Built, not live (reading-lists, gone)", "reviewed")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("branch gone does not exist", out)

    def test_and_inside_a_branch_name_is_not_a_separator(self):
        git(self.app, "branch", "add-search-and-filter", self.sha_stray)
        self.set_row(3, "Built, not live (add-search-and-filter)", "reviewed")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_words_between_branches_are_separators(self):
        self.set_row(3, "Built, not live (reading-lists and renewals)", "reviewed")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_a_branch_named_in_the_note_beats_words_in_the_status(self):
        self.set_row(3, "Built, not live (reviewed)", "on branch `renewals`")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_a_branch_below_another_of_that_name_does_not_count(self):
        git(self.app, "branch", "topic/deep", self.sha_stray)
        self.set_row(3, "Built, not live (topic)", "reviewed")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("branch topic does not exist", out)

    def test_a_branch_on_any_remote_counts(self):
        self.add_remote(name="upstream")
        git(self.app, "update-ref", "refs/remotes/upstream/far-away", self.sha_stray)
        self.set_row(3, "Built, not live (far-away)", "reviewed")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_a_branch_named_in_the_note(self):
        self.set_row(3, "Built, not live", "reviewed on branch `renewals`")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_no_branch_is_missing_evidence(self):
        self.set_row(3, "Built, not live", "reviewed somewhere")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 3 names no branch; run `gitdone mark <row> <kind> --branch NAME`", out)
        code, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3)

    def test_a_branch_already_merged_is_noted(self):
        git(self.app, "branch", "merged-one", self.sha_main)
        self.set_row(3, "Built, not live (merged-one)", "reviewed")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE row 3: branch merged-one is already on main; is the row Live?", out)

    def test_without_a_repo_a_branch_is_not_proven(self):
        self.change_plan(repo=None)
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 3 (Built, not live): branch reading-lists: the plan names no repo", out)


class CannotRun(ProjectCase):
    """Exit 1 means a proven contradiction, so nothing else may exit 1."""

    def assert_cannot_run(self, words=None):
        code, _, err = self.cli("check", "--offline")
        self.assertEqual(code, 2, err)
        if words:
            self.assertIn(words, err)

    def test_a_table_that_is_not_utf8(self):
        self.table_path.write_bytes(b"\xff\xfe")
        self.assert_cannot_run("is not UTF-8")

    def test_an_order_that_is_not_a_list(self):
        data = json.loads(self.plan_path.read_text())
        data["order"] = 5
        self.plan_path.write_text(json.dumps(data))
        self.assert_cannot_run("order: expected a list")

    def test_a_group_that_is_not_an_object(self):
        data = json.loads(self.plan_path.read_text())
        data["groups"] = ["x"]
        self.plan_path.write_text(json.dumps(data))
        self.assert_cannot_run("groups: each group needs")

    def test_a_view_that_would_overwrite_the_table(self):
        data = json.loads(self.plan_path.read_text())
        data["status_out"] = "status-table.md"
        self.plan_path.write_text(json.dumps(data))
        before = self.table_path.read_bytes()
        code, _, err = self.cli("render", "--write")
        self.assertEqual(code, 2, err)
        self.assertIn("three different files", err)
        self.assertEqual(self.table_path.read_bytes(), before)

    def test_an_unexpected_failure_is_not_a_contradiction(self):
        data = json.loads(self.plan_path.read_text())
        data["workstreams"][0]["rows"] = {"not": "numbers"}
        self.plan_path.write_text(json.dumps(data))
        code, _, _ = self.cli("check", "--offline")
        self.assertEqual(code, 2)


class PartialRows(ProjectCase):
    def setUp(self):
        super().setUp()
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")  # the example's pull request is not this class's question
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")

    def test_a_note_is_enough(self):
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_no_note_is_missing_evidence(self):
        self.set_row(4, "Partial", "")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN row 4 has no note saying what exists", out)
        code, _, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3)

    def test_not_built_and_custom_kinds_ask_for_nothing(self):
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)
        self.set_row(6, "Demo only", "")
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
