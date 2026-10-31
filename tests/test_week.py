import datetime
import json
import unittest

from helpers import ProjectCase, git


class Week(ProjectCase):
    def commit_table(self, message, date=None):
        env = {"GIT_COMMITTER_DATE": f"{date}T12:00:00", "GIT_AUTHOR_DATE": f"{date}T12:00:00"} if date else None
        git(self.project, "add", "-A")
        git(self.project, "commit", "-q", "-m", message, env=env)
        return git(self.project, "rev-parse", "HEAD")

    def setUp(self):
        super().setUp()
        git(self.project, "init", "-q", "-b", "main")
        self.first = self.commit_table("first", "2026-01-01")
        self.set_row(10, "Live", f"`{self.sha_main[:7]}`")
        self.set_row(4, "Built, not live (reading-lists)", "reviewed")
        self.second = self.commit_table("second", "2026-02-01")
        self.set_row(11, "Partial", "started")
        self.third = self.commit_table("third", "2026-03-01")

    def line(self, *args):
        code, out, err = self.cli("week", *args)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("\n"), 1, "one line")
        return out

    def test_since_a_date(self):
        line = self.line("2026-02-15")
        self.assertTrue(line.startswith(f"Since 2026-02-15 ({self.second[:7]}, 2026-02-01): "))
        self.assertIn("Moved: 11 Not built→Partial.", line)
        self.assertIn("Launch strict 5→5 of 11 (45%→45%), weighted 72%→75%", line)
        self.assertIn("Later strict 0→0 of 5", line)

    def test_a_date_with_no_earlier_commit_starts_at_the_first(self):
        line = self.line("2025-06-01")
        self.assertTrue(line.startswith(f"No commit of the table before 2025-06-01; since its first commit ({self.first[:7]}, 2026-01-01): "))
        self.assertIn("4 Partial→Built, not live", line)
        self.assertIn("10 Partial→Live", line)

    def test_since_a_commit(self):
        self.assertIn("Moved: 11 Not built→Partial.", self.line(self.second[:7]))

    def recent_history(self):
        """Commits 20, 10 and 1 days old, each moving one row, so the baseline decides what the line says."""
        today = datetime.date.today()
        for days, row in ((20, 16), (10, 8), (1, 6)):
            self.set_row(row, "Partial", "moved")
            self.commit_table(f"row {row}", (today - datetime.timedelta(days=days)).isoformat())

    def test_a_span_sets_the_baseline(self):
        self.recent_history()
        line = self.line("2 weeks")
        self.assertTrue(line.startswith("Since 2 weeks ago ("))
        self.assertIn("Moved: 6 Demo only→Partial; 8 Not built→Partial.", line)

    def test_a_short_span_means_the_same(self):
        self.recent_history()
        self.assertTrue(self.line("14d").startswith("Since 14 days ago ("))
        self.assertTrue(self.line("2w").startswith("Since 2 weeks ago ("))

    def test_the_default_is_a_week_ago(self):
        self.recent_history()
        self.assertIn("Moved: 6 Demo only→Partial.", self.line())

    def test_a_rewritten_history_keeps_its_baseline(self):
        # A rebase changes committer dates and keeps author dates.
        env = {"GIT_COMMITTER_DATE": "2026-10-29T12:00:00"}
        git(self.project, "-c", "rebase.autosquash=false", "rebase", "-q", "--force-rebase", "--root", env=env)
        line = self.line("2026-02-15")
        self.assertTrue(line.startswith("Since 2026-02-15 ("))
        self.assertIn("Moved: 11 Not built→Partial.", line)

    def test_a_removed_row_is_said(self):
        text = self.table_path.read_text()
        kept = [line for line in text.split("\n") if not line.startswith("| 9 |")]
        text = "\n".join(kept).replace("### 3. Accounts (3)", "### 3. Accounts (2)")
        self.table_path.write_text(text)
        data = json.loads(self.plan_path.read_text())
        data["groups"][0]["total"] = 10
        data["rows_total"] = 15
        data["workstreams"][2]["rows"] = [10, 11]
        self.plan_path.write_text(json.dumps(data))
        line = self.line(self.third[:7])
        self.assertIn("Removed: 9 (was Live).", line)

    def test_nothing_moved(self):
        self.assertIn("Moved: nothing.", self.line(self.third[:7]))

    def test_workstreams_that_moved_and_those_that_did_not(self):
        line = self.line("2026-01-15")
        self.assertIn("Workstreams moved: S3; not moved: S1, S2.", line)

    def test_uncommitted_changes_are_counted_and_said(self):
        self.set_row(16, "Partial", "started")
        line = self.line(self.third[:7])
        self.assertIn("16 Not built→Partial", line)
        self.assertIn("The table has uncommitted changes, counted here.", line)

    def test_a_status_the_plan_no_longer_knows_is_named_as_it_was(self):
        text = self.table_path.read_text()
        self.table_path.write_text(text.replace("| 15 | Screen-reader mode | Partial |", "| 15 | Screen-reader mode | Trial |"))
        self.commit_table("old word", "2026-03-02")
        self.table_path.write_text(text)
        line = self.line("HEAD")
        self.assertIn("15 Trial→Partial", line)

    def test_nonsense_cannot_run(self):
        code, _, err = self.cli("week", "whenever")
        self.assertEqual(code, 2)
        self.assertIn("is not a date", err)

    def test_it_writes_nothing(self):
        before = (self.table_path.read_bytes(), self.view_path.read_bytes())
        self.line("2026-02-15")
        self.assertEqual((self.table_path.read_bytes(), self.view_path.read_bytes()), before)


class NoHistory(ProjectCase):
    def test_a_table_outside_git_cannot_run(self):
        code, _, err = self.cli("week")
        self.assertEqual(code, 2)
        self.assertIn("is not in a git repository", err)

    def test_a_table_with_no_commit_cannot_run(self):
        git(self.project, "init", "-q", "-b", "main")
        code, _, err = self.cli("week")
        self.assertEqual(code, 2)
        self.assertIn("has no commit yet", err)


if __name__ == "__main__":
    unittest.main()
