import json
import os
import stat
import subprocess
import sys
import unittest

from helpers import ENGINE, ProjectCase
from gitdone import verdict


def state(**last_run):
    run = {"git_sha": "abc1234def", "model": "opus", "sha_range": "abc1234def..abc1234def"}
    run.update(last_run)
    return {"run_number": 17, "verdict": "pass with risks", "last_run": run}


class Annotation(ProjectCase):
    def name_state(self, data, release=None):
        path = self.tmp / "state.json"
        path.write_text(json.dumps(data))
        self.change_plan(verdict_state=str(path), release=release or "kiosk main abc1234")
        return path

    def test_no_state_file_named_is_no_annotation(self):
        self.assertIsNone(verdict.annotate(self.plan()))

    def test_it_says_run_verdict_gated_sha_and_model(self):
        self.name_state(state())
        note = verdict.annotate(self.plan())
        self.assertEqual(note.line, "Verdict: run 17, pass with risks, gated abc1234, model opus")
        self.assertIsNone(note.flag)

    def test_a_local_model_is_named_as_such(self):
        self.name_state(state(model="local:some-alias"))
        self.assertIn("model local:some-alias", verdict.annotate(self.plan()).line)

    def test_a_range_is_shown_when_it_is_one(self):
        self.name_state(state(sha_range="1111111aaa..abc1234def"))
        self.assertIn("range 1111111..abc1234", verdict.annotate(self.plan()).line)

    def test_a_release_that_is_not_the_gated_sha_is_flagged(self):
        self.name_state(state(), release="kiosk main 9f9f9f9")
        note = verdict.annotate(self.plan())
        self.assertEqual(note.flag, "the plan's release (9f9f9f9) is not the gated commit (abc1234)")

    def test_any_release_sha_may_be_the_gated_one(self):
        self.name_state(state(), release="site main 9f9f9f9; kiosk main abc1234")
        self.assertIsNone(verdict.annotate(self.plan()).flag)

    def test_release_sha_says_which_one_counts(self):
        self.name_state(state(), release="site main abc1234; kiosk main 9f9f9f9")
        self.change_plan(release_sha="9f9f9f9")
        self.assertIn("(9f9f9f9)", verdict.annotate(self.plan()).flag)

    def test_a_release_with_no_sha_is_not_flagged(self):
        self.name_state(state(), release="the spring release")
        self.assertIsNone(verdict.annotate(self.plan()).flag)

    def test_a_missing_state_file_is_said_not_raised(self):
        self.change_plan(verdict_state=str(self.tmp / "gone.json"))
        self.assertIn("state unreadable", verdict.annotate(self.plan()).line)

    def test_a_broken_state_file_is_said_not_raised(self):
        path = self.tmp / "state.json"
        path.write_text("{")
        self.change_plan(verdict_state=str(path))
        self.assertIn("state unreadable", verdict.annotate(self.plan()).line)

    def test_a_tilde_is_the_home_directory(self):
        self.change_plan(verdict_state="~/x/state.json")
        self.assertEqual(str(self.plan().verdict_state), os.path.expanduser("~/x/state.json"))

    def test_the_state_file_is_only_read(self):
        path = self.name_state(state())
        path.chmod(stat.S_IRUSR)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        for command in (("render",), ("render", "--write"), ("opener",), ("check", "--offline"), ("counts",)):
            self.cli(*command)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_the_view_never_holds_the_annotation(self):
        self.name_state(state())
        _, out, err = self.cli("render")
        self.assertNotIn("Verdict:", out)
        self.assertIn("Verdict: run 17", err)

    def test_a_new_qa_run_does_not_make_the_view_stale(self):
        path = self.name_state(state())
        self.write_view()
        path.write_text(json.dumps(dict(state(), run_number=18)))
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("Verdict: run 18", out)

    def test_the_view_on_a_pipe_is_exactly_the_view(self):
        self.name_state(state())
        self.write_view()
        done = subprocess.run([sys.executable, str(ENGINE), "render", "--plan", str(self.plan_path)],
                              capture_output=True, text=True)
        self.assertEqual(done.stdout.split("\n", 1)[1], self.view_path.read_text().split("\n", 1)[1])
        self.assertIn("Verdict: run 17", done.stderr)


class InTheCommands(ProjectCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "state.json"
        self.path.write_text(json.dumps(state()))

    def test_the_opener_shows_it_beside_the_release(self):
        self.change_plan(verdict_state=str(self.path), release="kiosk main abc1234")
        _, out, _ = self.cli("opener")
        self.assertIn("Release: kiosk main abc1234. Verdict: run 17, pass with risks, gated abc1234, model opus.", out)

    def test_the_opener_flags_a_release_that_was_not_gated(self):
        self.change_plan(verdict_state=str(self.path), release="kiosk main 9f9f9f9")
        _, out, _ = self.cli("opener")
        self.assertIn("⚠ the plan's release (9f9f9f9) is not the gated commit (abc1234)", out)

    def test_check_warns_by_default_and_strict_fails(self):
        self.set_row(9, "Live", f"`{self.sha_main[:7]}`")
        self.change_plan(verdict_state=str(self.path), release="kiosk main 9f9f9f9")
        code, out, _ = self.cli("check", "--offline")
        self.assertEqual(code, 0, out)
        self.assertIn("WARN the plan's release (9f9f9f9) is not the gated commit (abc1234)", out)
        code, out, _ = self.cli("check", "--offline", "--strict")
        self.assertEqual(code, 3, out)


if __name__ == "__main__":
    unittest.main()
