"""`matrix` and the requirement files behind it: every requirement, the row that holds it, its evidence and the tests on record."""
import json
import os
import pathlib
import tempfile
import unittest

from helpers import git, needs_sh

from gitdone import gate, requirements, table as tables, trace
from gitdone.plan import Plan, PlanError


class Parsing(unittest.TestCase):
    def items(self, text):
        return [(i.ident, i.words, i.line) for i in requirements.parse(text, "spec.md")]

    def test_the_shapes_a_spec_is_written_in(self):
        text = "\n".join(["# Spec", "", "- REQ-1: one", "- **REQ-2**: two", "1. REQ-3 three", "### FR-4 four", "| US-5 | five | high |", "**AC-6.** six", "`NFR-7` seven",
                          "- [ ] REQ-8 eight", "- [x] REQ-9.1: nine"])
        self.assertEqual([i[0] for i in self.items(text)], ["REQ-1", "REQ-2", "REQ-3", "FR-4", "US-5", "AC-6", "NFR-7", "REQ-8", "REQ-9.1"])
        self.assertEqual([i[1] for i in self.items(text)], ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])

    def test_a_checklist_item_needs_no_id(self):
        self.assertEqual(self.items("- [ ] Export to CSV\n- [x] Sign-in"), [(None, "Export to CSV", 1), (None, "Sign-in", 2)])

    def test_prose_is_not_a_requirement(self):
        self.assertEqual(self.items("We use UTF-8 and ISO-8601 here.\n\nSee REQ-1 for more.\n- a plain bullet\n"), [])

    def test_a_code_fence_is_not_a_requirement(self):
        self.assertEqual(self.items("```\n- REQ-1: no\n- [ ] no\n```\n\n<!-- - REQ-2: no -->\n- REQ-3: yes\n"), [("REQ-3", "yes", 7)])


class RequirementCase(unittest.TestCase):
    spec = "- REQ-1: Sign-in with a magic link\n- REQ-2: Search\n- REQ-3: Export to PDF\n- [ ] Weekly digest email\n"
    rows = [("Sign-in (REQ-1)", "Not built", ""), ("Search", "Partial", "REQ-2 is half of it"), ("Weekly digest email", "Not built", ""), ("Dark mode", "Not built", "")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name).resolve() / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.plan_path = self.repo / ".gitdone.json"
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "spec.md").write_text(self.spec)
        self.write_plan(requirements=["docs/spec.md"])
        self.write_table(self.rows)

    def write_plan(self, **keys):
        self.plan_path.write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "default_branch": "main", **keys}))

    def write_table(self, rows):
        lines = ["# P", "", f"### 1. All ({len(rows)})", "", "| # | Capability | Status | Note |", "|---|---|---|---|"]
        lines += [f"| {n} | {name} | {kind} | {note} |" for n, (name, kind, note) in enumerate(rows, start=1)]
        (self.repo / "status-table.md").write_text("\n".join(lines) + "\n")

    def plan(self):
        return Plan(self.plan_path)

    def commit(self, message, files=None):
        for name, text in (files or {}).items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def coverage(self):
        plan = self.plan()
        return requirements.coverage(plan, tables.load_clean(plan))


class Coverage(RequirementCase):
    def test_a_requirement_finds_its_row_by_id_in_the_name_or_the_note(self):
        found = dict((i.ident or i.words, [r.num for r in rows]) for i, rows in self.coverage()["items"])
        self.assertEqual(found["REQ-1"], [1])
        self.assertEqual(found["REQ-2"], [2])

    def test_an_id_is_a_whole_id(self):
        self.write_table([("Sign-in (REQ-11)", "Not built", ""), ("Search", "Partial", "PREQ-1, REQ-1.5, REQ-1-b")])
        found = dict((i.ident, [r.num for r in rows]) for i, rows in self.coverage()["items"] if i.ident)
        self.assertEqual(found["REQ-1"], [])

    def test_a_checklist_item_finds_its_row_by_its_words(self):
        found = dict((i.ident or i.words, [r.num for r in rows]) for i, rows in self.coverage()["items"])
        self.assertEqual(found["Weekly digest email"], [3])

    def test_one_shared_word_is_not_the_same_work(self):
        (self.repo / "docs" / "spec.md").write_text("- [ ] Email the weekly numbers to everyone who asked\n")
        self.write_table([("Weekly digest email", "Not built", "")])
        self.assertEqual(len(self.coverage()["without"]), 1)

    def test_it_says_what_has_no_row_and_what_nobody_asked_for(self):
        found = self.coverage()
        self.assertEqual([i.ident for i in found["without"]], ["REQ-3"])
        self.assertEqual([r.num for r in found["unasked"]], [4])

    def test_the_same_requirement_in_two_files_counts_once(self):
        (self.repo / "docs" / "roadmap.md").write_text("- REQ-1: Sign-in again\n")
        self.write_plan(requirements=["docs/spec.md", "docs/roadmap.md"])
        self.assertEqual(sum(1 for i, _ in self.coverage()["items"] if i.ident == "REQ-1"), 1)

    def test_a_file_with_nothing_to_read_says_how_to_write_one(self):
        (self.repo / "docs" / "spec.md").write_text("Just words.\n")
        self.assertIn("names no requirement", self.coverage()["problems"][0])

    def test_a_missing_file_says_so(self):
        self.write_plan(requirements=["docs/gone.md"])
        self.assertIn("gone.md", self.coverage()["problems"][0])

    def test_a_file_outside_the_project_is_not_read(self):
        outside = self.repo.parent / "secret.md"
        outside.write_text("- REQ-1: a secret\n")
        for name in (str(outside), "../secret.md"):
            self.write_plan(requirements=[name])
            found = self.coverage()
            self.assertEqual(found["items"], [])
            self.assertIn("outside this project", found["problems"][0])

    def test_a_link_out_of_the_project_is_not_read(self):
        needs_sh(self)
        outside = self.repo.parent / "secret.md"
        outside.write_text("- REQ-1: a secret\n")
        os.symlink(outside, self.repo / "docs" / "link.md")
        self.write_plan(requirements=["docs/link.md"])
        self.assertEqual(self.coverage()["items"], [])

    def test_the_plan_must_name_files(self):
        self.write_plan(requirements=[5])
        with self.assertRaises(PlanError):
            self.plan()
        self.write_plan(requirements="docs/spec.md")
        with self.assertRaises(PlanError):
            self.plan()


class Gate(RequirementCase):
    def setUp(self):
        super().setUp()
        plan = self.plan()
        from gitdone import render
        (self.repo / "STATUS.md").write_text(render.status_md(plan, tables.load_clean(plan)))
        self.commit("first")

    def test_a_requirement_with_no_row_is_a_note_and_stops_nothing(self):
        report = gate.report(self.plan(), offline=True)
        self.assertEqual(report.code, gate.OK)
        self.assertTrue(any("REQ-3" in f.text for f in report.notes))

    def test_strict_is_not_about_this(self):
        self.assertEqual(gate.report(self.plan(), offline=True, strict=True).code, gate.OK)

    def test_a_plan_without_requirements_says_nothing_about_them(self):
        self.write_plan()
        self.assertFalse(any("requirement" in f.text for f in gate.report(self.plan(), offline=True).notes))

    def test_many_are_cut_to_a_few(self):
        (self.repo / "docs" / "spec.md").write_text("".join(f"- REQ-{n}: thing\n" for n in range(100, 140)))
        notes = [f.text for f in gate.report(self.plan(), offline=True).notes if "requirement" in f.text]
        self.assertLessEqual(len(notes), gate.MOST_REQUIREMENTS_SAID + 1)
        self.assertIn("more requirements have no row", notes[-1])

    def test_the_opener_warns(self):
        self.assertIn("REQ-3", requirements.opener_line(self.plan(), tables.load_clean(self.plan())))

    def test_a_deadline_that_moves_is_said(self):
        self.write_plan(requirements=["docs/spec.md"], deadline="2027-01-01")
        old = json.loads(git(self.repo, "show", "HEAD:.gitdone.json"))
        words = gate.rule_changes(self.plan(), old)
        self.assertIn("the deadline moved: it was not set, now 2027-01-01", words)


class Matrix(RequirementCase):
    def live(self):
        sha = self.commit("Sign-in", {"src/auth.py": "1\n", "tests/test_auth.py": "1\n"})
        self.write_table([("Sign-in (REQ-1)", "Live", f"`{sha[:7]}`"), ("Search", "Partial", "REQ-2 is half of it. `tests/test_search.py`"), ("Weekly digest email", "Not built", ""), ("Dark mode", "Live", f"`{sha[:7]}`")])
        return sha

    def test_it_ties_a_requirement_to_its_row_evidence_and_tests(self):
        sha = self.live()
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn(f"| REQ-1 Sign-in with a magic link | docs/spec.md:1 | 1 | Live | `{sha[:7]}` | `tests/test_auth.py` |", words)

    def test_a_requirement_with_no_row_stands_out(self):
        self.live()
        self.assertIn("| REQ-3 Export to PDF | docs/spec.md:3 | **no row** |", trace.markdown(self.plan(), offline=True))

    def test_a_row_nobody_asked_for_stands_out(self):
        self.live()
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn("## Rows no requirement asks for", words)
        self.assertIn("| 4 | Dark mode |", words)

    def test_the_headline_counts_the_gaps(self):
        self.live()
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn("**3 of 4 requirements have a row, and 1 of them are all Live (25%).**", words)
        self.assertIn("1 of 4 rows answer to no requirement.", words)
        self.assertIn("2 of 2 Live rows have a test on record.", words)

    def test_a_commit_that_names_a_row_brings_its_tests(self):
        self.commit("row 3: the digest", {"src/digest.py": "1\n", "tests/test_digest.py": "1\n"})
        rows = {r["row"]: r for r in trace.rows_data(self.plan(), offline=True)}
        self.assertEqual(rows[3]["tests"], ["tests/test_digest.py"])
        self.assertEqual(len(rows[3]["named_by"]), 1)

    def test_a_test_a_note_names_counts_if_it_exists(self):
        self.commit("first", {"tests/test_search.py": "1\n"})
        self.write_table([("Sign-in (REQ-1)", "Not built", ""), ("Search", "Partial", "REQ-2. `tests/test_search.py` `tests/test_gone.py`")])
        rows = {r["row"]: r for r in trace.rows_data(self.plan(), offline=True)}
        self.assertEqual(rows[2]["tests"], ["tests/test_search.py"])

    def test_a_test_since_deleted_is_not_on_record(self):
        self.commit("row 1: a", {"tests/test_a.py": "1\n"})
        (self.repo / "tests" / "test_a.py").unlink()
        self.commit("Remove it")
        rows = {r["row"]: r for r in trace.rows_data(self.plan(), offline=True)}
        self.assertEqual(rows[1]["tests"], [])

    def test_a_live_row_with_no_test_is_counted(self):
        sha = self.commit("Sign-in", {"src/auth.py": "1\n"})
        self.write_table([("Sign-in (REQ-1)", "Live", f"`{sha[:7]}`")])
        summary = trace.data(self.plan(), offline=True)["summary"]
        self.assertEqual(summary["live_without_a_test"], [1])

    def test_a_merged_pull_request_brings_what_it_landed(self):
        needs_sh(self)
        sha = self.commit("Sign-in", {"src/auth.py": "1\n", "tests/test_auth.py": "1\n"})
        git(self.repo, "remote", "add", "origin", "https://example.invalid/a/b.git")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        answer = self.repo.parent / "answer.json"
        answer.write_text(json.dumps([{"number": 7, "state": "MERGED", "baseRefName": "main", "title": "Sign-in", "mergedAt": "2026-01-01T00:00:00Z", "mergeCommit": {"oid": sha}, "url": "u"}]))
        bin_dir = self.repo.parent / "bin"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text(f'#!/bin/sh\ncat "{answer}"\n')
        (bin_dir / "gh").chmod(0o755)
        from unittest import mock
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}):
            self.write_table([("Sign-in (REQ-1)", "Live", "PR #7")])
            rows = {r["row"]: r for r in trace.rows_data(self.plan())}
        self.assertEqual(rows[1]["tests"], ["tests/test_auth.py"])

    def test_with_no_requirement_files_it_is_a_matrix_of_rows(self):
        self.write_plan()
        self.live()
        words = trace.markdown(self.plan(), offline=True)
        self.assertNotIn("Requirement |", words)
        self.assertIn("| 1 | Sign-in (REQ-1) | Live |", words)

    def test_pipes_in_a_name_do_not_break_the_table(self):
        (self.repo / "docs" / "spec.md").write_text("- REQ-1: a \\| b\n")
        self.write_plan(requirements=["docs/spec.md"])
        self.assertIn("REQ-1 a \\| b |", trace.markdown(self.plan(), offline=True))

    def test_a_file_that_could_not_be_read_is_said(self):
        self.write_plan(requirements=["docs/gone.md"])
        self.assertIn("## Could not be read", trace.markdown(self.plan(), offline=True))

    def test_with_no_repository_the_rows_still_stand(self):
        import shutil
        shutil.rmtree(self.repo / ".git")
        self.write_plan(requirements=["docs/spec.md"])
        words = trace.markdown(self.plan(), offline=True)
        self.assertIn("**no row**", words)

    def test_as_data(self):
        self.live()
        data = trace.data(self.plan(), offline=True)
        self.assertEqual(data["summary"]["requirements"], 4)
        self.assertEqual(data["requirements"][0]["id"], "REQ-1")
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
