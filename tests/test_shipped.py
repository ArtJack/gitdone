import os
import stat
import unittest
import unittest.mock

from helpers import ProjectCase, not_on_windows
from gitdone import render, shipped, table as tables


class Moves(ProjectCase):
    def row(self, number):
        plan = self.plan()
        return tables.load_clean(plan).rows[number]

    def test_a_row_moves_with_its_evidence_and_the_view_follows(self):
        before = self.table_path.read_text().split("\n")
        code, out, err = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0, err)
        self.assertIn("row 10: Partial → Live (verified: commit", out)
        row = self.row(10)
        self.assertEqual(row.kind, "Live")
        self.assertIn("Staff sign in; the override screen is not there yet. *(Live ", row.note)
        self.assertIn(f"`{self.sha_main[:7]}`; was Partial)*", row.note)
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        after = self.table_path.read_text().split("\n")
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(before), len(after))
        counts_span = render.embedded_counts(self.table_path.read_text())[0]
        outside = [i for i in changed if not counts_span[0] <= i < counts_span[1]]
        self.assertEqual(len(outside), 1, "one row changes, and the counts table")

    def test_the_counts_table_inside_the_table_stays_true(self):
        self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertIn("| 3 | Accounts | 3 | 2 |  |  |  | 1 |", self.table_path.read_text())

    def test_the_opener_is_printed_after_a_move(self):
        _, out, _ = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertIn("Launch: strict 45% (5/11)", out)

    def test_a_built_row_moves_and_keeps_what_its_status_said(self):
        code, _, err = self.cli("shipped", "3", "PR #12", "--offline", "--allow-unverified")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.row(3).status, "Live")
        self.assertIn("PR #12, unverified; was Built, not live (reading-lists))*", self.row(3).note)

    def test_a_status_qualifier_is_kept_in_the_note(self):
        self.set_row(10, "Partial (blocked on the fines policy)", "x")
        self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertIn("was Partial (blocked on the fines policy)", self.row(10).note)

    def test_a_live_row_keeps_its_status_cell_and_its_old_evidence(self):
        self.set_row(1, "Live (PR #12)", "x")
        code, _, err = self.cli("shipped", "1", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.row(1).status, "Live (PR #12)")

    def test_a_shorter_number_is_not_already_named(self):
        self.set_row(1, "Live", "PR #12")
        code, out, err = self.cli("shipped", "1", "PR #1", "--offline", "--allow-unverified")
        self.assertEqual(code, 0, err)
        self.assertNotIn("nothing changed", out)
        self.assertIn("PR #1, unverified)*", self.row(1).note)

    def test_a_table_with_windows_line_ends_keeps_them(self):
        text = self.table_path.read_text()
        self.table_path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        self.write_view()
        code, _, err = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0, err)
        raw = self.table_path.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertEqual(self.row(10).kind, "Live")

    def test_counts_write_keeps_windows_line_ends_too(self):
        self.table_path.write_bytes(self.table_path.read_text().replace("\n", "\r\n").encode("utf-8"))
        code, _, err = self.cli("counts", "--write")
        self.assertEqual(code, 0, err)
        raw = self.table_path.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_a_view_that_cannot_be_written_puts_the_table_back(self):
        before = self.table_path.read_bytes()
        real = shipped.write_atomically

        def failing(path, text, newline="\n"):
            if path == self.view_path:
                raise PermissionError(13, "Permission denied", str(path))
            real(path, text, newline)

        with unittest.mock.patch.object(shipped, "write_atomically", failing):
            code, _, err = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(code, 2, err)
        self.assertIn("the table was put back", err)
        self.assertEqual(self.table_path.read_bytes(), before)

    def test_a_new_view_gets_ordinary_permissions(self):
        self.view_path.unlink()
        self.cli("render", "--write")
        umask = os.umask(0)
        os.umask(umask)
        self.assertEqual(stat.S_IMODE(self.view_path.stat().st_mode), 0o666 & ~umask)

    def test_an_existing_file_keeps_its_permissions(self):
        not_on_windows(self, "a file there has no such mode to keep")
        self.table_path.chmod(0o640)
        self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(stat.S_IMODE(self.table_path.stat().st_mode), 0o640)

    def test_evidence_in_several_words(self):
        code, _, err = self.cli("shipped", "10", "released", "as", f"`{self.sha_main[:7]}`", "--offline")
        self.assertEqual(code, 0, err)
        self.assertIn(f"released as `{self.sha_main[:7]}`", self.row(10).note)

    def test_a_row_that_was_live_only_gains_evidence(self):
        self.set_row(2, "Live", f"`{self.sha_old[:7]}`")
        code, out, err = self.cli("shipped", "9", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0, err)
        self.assertIn("row 9 was already Live; evidence added", out)
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 0, out)

    def test_the_same_evidence_twice_changes_nothing(self):
        self.cli("shipped", "9", self.sha_main[:7], "--offline")
        before = self.table_path.read_text()
        code, out, _ = self.cli("shipped", "9", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0)
        self.assertIn("nothing changed", out)
        self.assertEqual(self.table_path.read_text(), before)

    def test_a_pipe_in_the_evidence_does_not_break_the_row(self):
        code, _, err = self.cli("shipped", "10", f"`{self.sha_main[:7]}` a|b", "--offline")
        self.assertEqual(code, 0, err)
        self.assertIn(r"a\|b", self.row(10).note)
        self.assertEqual(self.row(10).kind, "Live")

    def test_a_pull_request_with_no_remote_is_refused_unless_a_person_vouches_for_it(self):
        before = self.table_path.read_text()
        code, _, err = self.cli("shipped", "10", "PR #999")
        self.assertEqual(code, 1, err)
        self.assertIn("app has no remote, so nothing could confirm it", err)
        self.assertIn("--allow-unverified", err, "the refusal names the way out")
        self.assertEqual(self.table_path.read_text(), before)
        code, _, err = self.cli("shipped", "10", "PR #999", "--allow-unverified")
        self.assertEqual(code, 0, err)
        self.assertIn("PR #999, unverified", self.row(10).note, "the note says so")
        self.assertEqual(self.cli("check", "--strict")[0], 3, "and strict still fails on it")

    def test_a_pull_request_nothing_can_answer_for_is_refused(self):
        self.add_remote()
        self.fake_gh(fail="not logged in")
        before = self.table_path.read_text()
        code, _, err = self.cli("shipped", "10", "PR #12")
        self.assertEqual(code, 1, err)
        self.assertIn("nothing here can check it", err)
        self.assertIn("--allow-unverified", err)
        self.assertEqual(self.table_path.read_text(), before)

    def test_offline_cannot_vouch_for_a_pull_request(self):
        self.add_remote()
        code, _, err = self.cli("shipped", "10", "PR #12", "--offline")
        self.assertEqual(code, 1, err)

    def test_the_flag_takes_it_and_says_so(self):
        self.add_remote()
        self.fake_gh(fail="not logged in")
        code, out, err = self.cli("shipped", "10", "PR #12", "--allow-unverified")
        self.assertEqual(code, 0, err)
        self.assertIn("(unverified: PR #12: gh could not answer: not logged in)", out)

    def test_everything_named_must_be_checked_even_beside_a_commit_that_holds(self):
        self.add_remote()
        self.fake_gh(fail="not logged in")
        code, _, err = self.cli("shipped", "10", f"PR #12 and `{self.sha_main[:7]}`")
        self.assertEqual(code, 1, err)
        self.assertIn("nothing here can check it", err)

    def test_a_plans_own_evidence_pattern_is_not_checked_by_anything(self):
        self.change_plan(evidence_pattern="TICKET-\\d+")
        self.assertEqual(self.cli("shipped", "10", "TICKET-7")[0], 1)
        code, _, err = self.cli("shipped", "10", "TICKET-7", "--allow-unverified")
        self.assertEqual(code, 0, err)

    def test_it_says_what_the_commit_should_hold(self):
        code, out, _ = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertIn("to commit: git add", out)
        self.assertIn("status-table.md", out)
        self.assertIn("STATUS.md", out)

    def test_a_refusal_over_a_branch_says_how_to_record_it(self):
        code, _, err = self.cli("shipped", "10", self.sha_stray[:7], "--offline")
        self.assertEqual(code, 1)
        self.assertIn("gitdone mark 10 built --branch NAME", err)

    def test_only_the_latest_machine_note_stays(self):
        self.set_row(10, "Partial", "the form exists")
        self.cli("mark", "10", "built", "--branch", "renewals")
        self.assertIn("branch `renewals`", self.row(10).note)
        code, _, err = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(code, 0, err)
        note = self.row(10).note
        self.assertIn("the form exists", note, "a person's words stay")
        self.assertNotIn("branch `renewals`", note, "git keeps that step")
        self.assertIn(f"`{self.sha_main[:7]}`", note)
        self.assertIn("was Built, not live", note)

    def test_evidence_added_to_a_live_row_keeps_what_was_there(self):
        self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.cli("shipped", "10", self.sha_old[:7], "--offline")
        note = self.row(10).note
        self.assertIn(self.sha_main[:7], note)
        self.assertIn(self.sha_old[:7], note)

    def test_an_all_digit_commit_given_alone_is_read_as_a_commit(self):
        code, _, err = self.cli("shipped", "10", "1234567", "--offline")
        self.assertEqual(code, 1)
        self.assertIn("commit 1234567 is not in the repository app", err)


class Refusals(ProjectCase):
    def assert_refused(self, words, *args):
        table, view = self.table_path.read_bytes(), self.view_path.read_bytes()
        code, out, err = self.cli("shipped", *args, "--offline")
        self.assertEqual(code, 1, out)
        self.assertIn("refused, nothing changed", err)
        self.assertIn(words, err)
        self.assertEqual((self.table_path.read_bytes(), self.view_path.read_bytes()), (table, view))

    def test_no_evidence(self):
        self.assert_refused("no evidence given", "10")

    def test_words_that_name_no_release(self):
        self.assert_refused("the evidence names no release", "10", "trust me, it works")

    def test_a_commit_off_the_default_branch(self):
        self.assert_refused("is not on main", "10", self.sha_stray[:7])

    def test_a_commit_that_is_not_there(self):
        self.assert_refused("is not in the repository app", "10", "abcdef1")

    def test_a_row_that_is_not_there(self):
        self.assert_refused("row 99 is not in", "99", self.sha_main[:7])

    def test_a_row_in_a_prose_domain(self):
        self.assert_refused("sits in a prose domain", "12", self.sha_main[:7])

    def test_a_good_commit_beside_one_that_is_not_on_main(self):
        self.assert_refused("is not on main", "10", f"`{self.sha_main[:7]}` and `{self.sha_stray[:7]}`")

    def test_a_commit_the_clone_does_not_have_even_with_a_remote(self):
        self.add_remote()
        self.assert_refused("fetch, or correct it", "10", "abcdef1")

    def test_a_table_with_a_broken_shape_stops_the_move(self):
        self.set_row(9, "Almost", "soon", view=False)
        code, _, err = self.cli("shipped", "10", self.sha_main[:7], "--offline")
        self.assertEqual(code, 2)
        self.assertIn("unknown status", err)

    def test_a_good_commit_beside_a_pull_request_that_does_not_exist(self):
        self.add_remote()
        self.fake_gh([])
        table = self.table_path.read_bytes()
        code, _, err = self.cli("shipped", "10", f"`{self.sha_main[:7]}` and PR #99")
        self.assertEqual(code, 1)
        self.assertIn("PR #99 does not exist", err)
        self.assertEqual(self.table_path.read_bytes(), table)

    def test_a_merged_pull_request_is_needed_when_gh_can_say(self):
        self.add_remote()
        self.fake_gh([{"number": 13, "state": "OPEN", "baseRefName": "main"}])
        table = self.table_path.read_bytes()
        code, _, err = self.cli("shipped", "10", "PR #13")
        self.assertEqual(code, 1)
        self.assertIn("PR #13 is open, not merged", err)
        self.assertEqual(self.table_path.read_bytes(), table)


if __name__ == "__main__":
    unittest.main()
