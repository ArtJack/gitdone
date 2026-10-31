import unittest

from helpers import EXAMPLE
from gitdone.plan import DEFAULT_KINDS, Plan, PlanError, _kind, numbers
from gitdone.table import match_kind, parse, split_cells

KINDS = [_kind(k) for k in DEFAULT_KINDS]


class TableShape(unittest.TestCase):
    def test_the_example_has_its_domains_and_rows(self):
        plan = Plan(EXAMPLE / "plan.json")
        table = parse(plan.doc.read_text(), plan.kinds)
        self.assertEqual([d.n for d in table.domains], [1, 2, 3, 4, 5])
        self.assertEqual(len(table.rows), 16)
        self.assertEqual(table.problems, [])

    def test_a_domain_with_no_rows_is_prose_and_counts_as_the_last_kind(self):
        plan = Plan(EXAMPLE / "plan.json")
        table = parse(plan.doc.read_text(), plan.kinds)
        prose = [table.rows[n] for n in (12, 13, 14)]
        self.assertTrue(all(r.prose and r.kind == "Not built" for r in prose))

    def test_an_unknown_status_is_a_problem(self):
        table = parse("### 1. A (1)\n\n| 1 | a | Shipping soon | x |\n", KINDS)
        self.assertIn("row 1: unknown status 'Shipping soon'", table.problems)

    def test_a_count_that_does_not_match_its_header_is_a_problem(self):
        table = parse("### 1. A (2)\n\n| 1 | a | Live | x |\n", KINDS)
        self.assertIn("domain 1 (A) has 1 rows, its header says 2; correct the number in its heading, or use `add` and `remove`", table.problems)

    def test_a_row_number_used_twice_is_a_problem(self):
        table = parse("### 1. A (2)\n\n| 1 | a | Live | x |\n| 1 | b | Live | y |\n", KINDS)
        self.assertIn("row 1 appears twice", table.problems)

    def test_rows_with_no_space_after_the_pipe_are_rows(self):
        table = parse("### 1. A (1)\n\n|1|a|Live|x|\n", KINDS)
        self.assertEqual(table.problems, [])
        self.assertEqual(table.rows[1].kind, "Live")
        self.assertFalse(table.rows[1].prose)

    def test_a_table_nothing_can_be_read_from_is_not_prose(self):
        table = parse("### 1. A (2)\n\n| # | Name | Status | Note |\n|---|---|---|---|\n| one | a | Live | x |\n| two | b | Live | y |\n", KINDS)
        self.assertIn("domain 1 (A) has a table, and none of its rows could be read", table.problems)

    def test_a_table_under_another_heading_is_not_rows(self):
        table = parse("### 1. A (1)\n\n| 1 | a | Live | x |\n\n## Appendix\n\n| 9 | not a row | Whatever | |\n", KINDS)
        self.assertEqual(table.problems, [])
        self.assertEqual(list(table.rows), [1])

    def test_a_table_above_the_first_domain_is_not_rows(self):
        table = parse("| 1 | Search | 4 | 2 |\n\n### 1. A (1)\n\n| 1 | a | Live | x |\n", KINDS)
        self.assertEqual(table.rows[1].name, "a")

    def test_an_escaped_pipe_stays_in_the_note(self):
        self.assertEqual(split_cells(r"| 1 | a | Live | x \| y |"), ["1", "a", "Live", r"x \| y"])

    def test_an_empty_note_is_empty(self):
        self.assertEqual(split_cells("| 1 | a | Live | |"), ["1", "a", "Live", ""])


class Kinds(unittest.TestCase):
    NAMES = ["Live", "Built, not live", "Not built"]

    def test_a_status_may_say_more_after_its_kind(self):
        self.assertEqual(match_kind("Live after a grant", self.NAMES), "Live")
        self.assertEqual(match_kind("Built, not live (some-branch)", self.NAMES), "Built, not live")

    def test_the_longest_name_wins(self):
        self.assertEqual(match_kind("Live, partly", ["Live", "Live, partly"]), "Live, partly")

    def test_a_kind_must_end_on_a_word_boundary(self):
        self.assertIsNone(match_kind("Liveness probe", self.NAMES))


class Numbers(unittest.TestCase):
    def test_every_spelling(self):
        self.assertEqual(numbers("1-3,7", "x"), [1, 2, 3, 7])
        self.assertEqual(numbers([4, 2], "x"), [4, 2])
        self.assertEqual(numbers(5, "x"), [5])

    def test_nonsense_stops(self):
        for bad in ("a-b", "1-", ["1"], True, 1.5):
            with self.assertRaises(PlanError):
                numbers(bad, "x")


if __name__ == "__main__":
    unittest.main()
