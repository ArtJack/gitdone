"""`add`, `mark` and `rows`: the changes that need no release, without hand-editing the table's shape."""
import json
import unittest

from helpers import ProjectCase
from gitdone import table as tables
from gitdone.edit import resolve_kind
from gitdone.shipped import Refused


class Add(ProjectCase):
    def setUp(self):
        super().setUp()
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None)
        self.write_view()

    def rows(self):
        return tables.load_clean(self.plan()).rows

    def test_a_row_goes_at_the_end_of_the_last_domain_by_default(self):
        before = max(self.rows())
        code, out, err = self.cli("add", "Large-print receipts")
        self.assertEqual(code, 0, err)
        self.assertIn(f"added row {before + 1}", out)
        row = self.rows()[before + 1]
        self.assertEqual((row.name, row.kind), ("Large-print receipts", "Not built"))

    def test_the_header_count_and_the_view_stay_true(self):
        self.cli("add", "Another", "--domain", "1")
        code, out, _ = self.cli("check")
        self.assertEqual(code, 0, out)
        self.assertIn("### 1. Catalogue search (5)", self.table_path.read_text())

    def test_the_domain_can_be_named(self):
        code, _, err = self.cli("add", "Another", "--domain", "lending")
        self.assertEqual(code, 0, err)
        self.assertIn("### 2. Lending (5)", self.table_path.read_text())

    def test_an_unknown_domain_is_refused_and_lists_them(self):
        code, _, err = self.cli("add", "Another", "--domain", "Nope")
        self.assertEqual(code, 1)
        self.assertIn("1. Catalogue search", err)

    def test_a_new_domain_can_start_with_this_row(self):
        code, _, err = self.cli("add", "Mobile app", "--new-domain", "Apps")
        self.assertEqual(code, 0, err)
        self.assertIn("### 6. Apps (1)", self.table_path.read_text())
        self.assertEqual(self.cli("check")[0], 0)

    def test_the_kind_can_be_given(self):
        code, _, err = self.cli("add", "Half done", "--kind", "partial", "--note", "the form exists")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows()[max(self.rows())].kind, "Partial")

    def test_a_kind_that_needs_a_note_is_refused_without_one(self):
        code, _, err = self.cli("add", "Half done", "--kind", "partial")
        self.assertEqual(code, 1)
        self.assertIn("needs a note", err)

    def test_the_strict_kind_cannot_be_added_directly(self):
        code, _, err = self.cli("add", "Done already", "--kind", "live")
        self.assertEqual(code, 1)
        self.assertIn("shipped", err)

    def test_a_pipe_in_the_name_stays_one_cell(self):
        self.cli("add", "a|b")
        self.assertEqual(self.rows()[max(self.rows())].name, "a\\|b")

    def test_a_name_the_table_already_has_is_refused(self):
        self.cli("add", "Large-print receipts")
        before = self.table_path.read_text()
        code, _, err = self.cli("add", "large-print RECEIPTS")
        self.assertEqual(code, 1)
        self.assertIn("already has that name", err)
        self.assertEqual(self.table_path.read_text(), before)


class Remove(ProjectCase):
    def setUp(self):
        super().setUp()
        self.change_plan(rows_total=None, groups=None, sections=None, products=None, workstreams=None, order=None, release=None)

    def rows(self):
        return tables.load_clean(self.plan()).rows

    def test_a_row_goes_and_the_counts_and_the_view_stay_true(self):
        code, out, err = self.cli("remove", "4")
        self.assertEqual(code, 0, err)
        self.assertIn("is out of the scope", out)
        self.assertNotIn(4, self.rows())
        self.assertIn("### 1. Catalogue search (3)", self.table_path.read_text())
        self.assertEqual(self.cli("check", "--offline")[0], 0)

    def test_the_last_row_of_a_domain_leaves_a_domain_that_can_be_added_to(self):
        for number in (15, 16):
            code, _, err = self.cli("remove", str(number))
            self.assertEqual(code, 0, err)
        self.assertIn("### 5. Accessibility (0)", self.table_path.read_text())
        self.assertEqual(self.cli("check", "--offline")[0], 0)
        code, _, err = self.cli("add", "Screen reader", "--domain", "5")
        self.assertEqual(code, 0, err)
        self.assertIn("### 5. Accessibility (1)", self.table_path.read_text())

    def test_a_number_is_not_reused_while_a_higher_one_stands(self):
        self.cli("remove", "4")
        self.cli("add", "Another")
        self.assertNotIn(4, self.rows())

    def test_a_row_that_is_not_there_is_refused(self):
        code, _, err = self.cli("remove", "99")
        self.assertEqual(code, 1)
        self.assertIn("row 99 is not in", err)

    def test_a_row_in_a_prose_domain_is_refused(self):
        code, _, err = self.cli("remove", "12")
        self.assertEqual(code, 1)
        self.assertIn("prose", err)


class RemoveWithAFixedScope(ProjectCase):
    def test_a_plan_that_fixes_its_row_count_refuses_quietly_shrinking_it(self):
        before = self.table_path.read_text()
        code, _, err = self.cli("remove", "4")
        self.assertEqual(code, 2)
        self.assertIn("the plan says", err)
        self.assertEqual(self.table_path.read_text(), before)


class AddWithAFixedScope(ProjectCase):
    def test_a_plan_that_fixes_its_row_count_refuses_quietly_growing_it(self):
        before = self.table_path.read_text()
        code, _, err = self.cli("add", "Scope creep", "--domain", "1")
        self.assertEqual(code, 2)
        self.assertIn("the plan says", err)
        self.assertEqual(self.table_path.read_text(), before)

    def test_a_domain_of_prose_is_refused(self):
        self.change_plan(rows_total=None, groups=None, sections=None, products=None)
        code, _, err = self.cli("add", "Another", "--domain", "4")
        self.assertEqual(code, 1, err)
        self.assertIn("prose", err)


class Mark(ProjectCase):
    def test_it_says_what_the_commit_should_hold(self):
        _, out, _ = self.cli("mark", "11", "partial", "words")
        self.assertIn("to commit: git add", out)

    def row(self, n):
        return tables.load_clean(self.plan()).rows[n]

    def test_a_row_moves_with_a_note_and_says_what_it_was(self):
        code, out, err = self.cli("mark", "11", "partial", "the", "form", "exists")
        self.assertEqual(code, 0, err)
        self.assertIn("row 11: Not built → Partial", out)
        row = self.row(11)
        self.assertEqual(row.kind, "Partial")
        self.assertIn("the form exists", row.note)
        self.assertIn("was Not built", row.note)

    def test_the_view_stays_true(self):
        self.cli("mark", "11", "partial", "the", "form", "exists")
        self.assertEqual(self.cli("check")[0], 0)

    def test_the_strict_kind_is_refused_and_points_at_shipped(self):
        before = self.table_path.read_text()
        code, _, err = self.cli("mark", "11", "live")
        self.assertEqual(code, 1)
        self.assertIn("gitdone shipped 11", err)
        self.assertEqual(self.table_path.read_text(), before)

    def test_a_partial_row_needs_words_or_a_note_already_there(self):
        code, _, err = self.cli("mark", "11", "partial")
        self.assertEqual(code, 1)
        self.assertIn("needs a note", err)

    def test_a_built_row_needs_a_branch(self):
        code, _, err = self.cli("mark", "11", "built")
        self.assertEqual(code, 1)
        self.assertIn("--branch", err)

    def test_a_branch_that_does_not_exist_is_refused(self):
        self.change_plan()
        code, _, err = self.cli("mark", "11", "built", "--branch", "nowhere")
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_a_branch_that_exists_is_recorded_where_the_gate_reads_it(self):
        code, _, err = self.cli("mark", "11", "built", "--branch", "renewals")
        self.assertEqual(code, 0, err)
        self.assertIn("branch `renewals`", self.row(11).note)
        out = self.cli("check")
        self.assertEqual(out[0], 0, out[1])

    def test_a_live_row_can_be_taken_back(self):
        code, _, err = self.cli("mark", "1", "partial", "reverted", "on", "Tuesday")
        self.assertEqual(code, 0, err)
        self.assertIn("was Live", self.row(1).note)

    def test_a_kind_with_no_rule_needs_nothing(self):
        code, _, err = self.cli("mark", "11", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.row(11).kind, "Demo only")

    def test_the_same_kind_with_no_words_changes_nothing(self):
        before = self.table_path.read_text()
        code, out, _ = self.cli("mark", "11", "not built")
        self.assertEqual(code, 0)
        self.assertIn("nothing changed", out)
        self.assertEqual(self.table_path.read_text(), before)

    def test_a_row_that_is_not_there_is_refused(self):
        code, _, err = self.cli("mark", "99", "partial", "x")
        self.assertEqual(code, 1)
        self.assertIn("row 99 is not in", err)


class Kinds(ProjectCase):
    def test_a_name_a_short_name_or_a_unique_prefix(self):
        plan = self.plan()
        self.assertEqual(resolve_kind(plan, "LIVE").name, "Live")
        self.assertEqual(resolve_kind(plan, "built").name, "Built, not live")
        self.assertEqual(resolve_kind(plan, "dem").name, "Demo only")

    def test_an_unknown_word_lists_the_kinds(self):
        with self.assertRaisesRegex(Refused, "Demo only"):
            resolve_kind(self.plan(), "shipped")

    def test_an_ambiguous_prefix_is_refused(self):
        data = json.loads(self.plan_path.read_text())
        data["kinds"] = [{"name": "Partial", "weight": 0.5}, {"name": "Parked", "weight": 0}]
        self.plan_path.write_text(json.dumps(data))
        with self.assertRaises(Refused):
            resolve_kind(self.plan(), "par")


class Rows(ProjectCase):
    def test_every_row_by_default(self):
        code, out, _ = self.cli("rows")
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().split("\n")), 16)

    def test_by_kind(self):
        _, out, _ = self.cli("rows", "--kind", "live")
        self.assertEqual(len(out.strip().split("\n")), 4)

    def test_open_leaves_out_the_strict_kind(self):
        _, out, _ = self.cli("rows", "--open")
        self.assertEqual(len(out.strip().split("\n")), 12)

    def test_by_domain(self):
        _, out, _ = self.cli("rows", "--domain", "1")
        self.assertEqual(len(out.strip().split("\n")), 4)

    def test_a_domains_name_in_any_case(self):
        _, out, _ = self.cli("rows", "--domain", "LENDING")
        self.assertEqual(len(out.strip().split("\n")), 4)

    def test_an_unknown_domain_is_a_clear_error_not_silence(self):
        code, _, err = self.cli("rows", "--domain", "nope")
        self.assertEqual(code, 2)
        self.assertIn("1. Catalogue search", err)

    def test_as_data(self):
        _, out, _ = self.cli("rows", "--json", "--kind", "live")
        data = json.loads(out)
        self.assertEqual({r["kind"] for r in data}, {"Live"})
        self.assertEqual(set(data[0]), {"row", "name", "kind", "status", "note", "domain", "domain_name"})

    def test_an_unknown_kind_is_a_clear_error(self):
        code, _, err = self.cli("rows", "--kind", "nope")
        self.assertEqual(code, 2)
        self.assertIn("is not one kind", err)


if __name__ == "__main__":
    unittest.main()
