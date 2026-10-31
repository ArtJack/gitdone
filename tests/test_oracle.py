"""Random histories where the truth can be read off: every commit adds files of its own, so a commit's bytes at the tip say whether its content is there.

A commit none of whose bytes are at the tip must not be verified, and one all of whose bytes are there must not be refused. The histories are random and the seeds are not.
A revert is set aside: a later revert of the commit it undid takes its files away without naming it, which docs/gate.md states as a limit.
"""
import itertools
import json
import os
import pathlib
import random
import tempfile
import unittest

from helpers import git as plain_git
from gitdone import cli  # noqa: F401
from gitdone import report
from gitdone.plan import Plan

# A few here. Before a release, GITDONE_ORACLE_SEEDS=400, and read what it lists: contrived chains of reverts of one commit can be refused.
SEEDS = range(int(os.environ.get("GITDONE_ORACLE_SEEDS", 6)))
CLOCK = itertools.count(1700000000, 60)


def git(repo, *args):
    """git with a clock of its own, so that a seed means one history."""
    stamp = f"{next(CLOCK)} +0000"
    return plain_git(repo, *args, env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
OPERATIONS = ("main", "main", "side-real", "side-real", "side-ours", "side-squash", "revert", "revert", "revert-side", "revert-side-ours",
              "revert-merge", "reapply", "two-step-ours", "ours-touch")


def attempt(repo, *args):
    try:
        git(repo, *args)
        return True
    except AssertionError:
        return False


def work(repo, rnd, tag):
    for i in range(rnd.choice([1, 1, 2, 2, 3, 3, 4])):
        (repo / f"u{tag}_{i}.txt").write_text(rnd.choice(["", "same\n", f"{tag}.{i}\n"]))
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"work {tag}")


def side_branch(repo, rnd, seq, op):
    heads = git(repo, "log", "--first-parent", "--format=%H", "main").split()
    git(repo, "checkout", "-q", "-b", f"s{seq}", rnd.choice(heads[:3]))
    for i in range(rnd.randint(1, 2)):
        work(repo, rnd, f"{seq}x{i}")
    git(repo, "checkout", "-q", "main")
    if op == "two-step-ours":
        git(repo, "checkout", "-q", "-b", f"d{seq}", "main")
        work(repo, rnd, f"{seq}d")
        attempt(repo, "merge", "-q", "-s", "ours", "--no-ff", "-m", f"ours {seq}", f"s{seq}")
        git(repo, "checkout", "-q", "main")
        return attempt(repo, "merge", "-q", "--no-ff", "-m", f"merge d{seq}", f"d{seq}")
    if op == "ours-touch":
        attempt(repo, "merge", "-q", "-s", "ours", "--no-ff", "--no-commit", f"s{seq}")
        (repo / f"note{seq}.txt").write_text("n\n")
        git(repo, "add", ".")
        return attempt(repo, "commit", "-q", "-m", f"merge touching {seq}")
    if op == "side-squash":
        return attempt(repo, "merge", "-q", "--squash", f"s{seq}") and attempt(repo, "commit", "-q", "-m", f"squash {seq}")
    flags = ["--no-ff"] if op == "side-real" else ["-s", "ours", "--no-ff"]
    return attempt(repo, "merge", "-q", *flags, "-m", f"merge {seq}", f"s{seq}")


def revert_something(repo, rnd, seq, op):
    if op == "revert-merge":
        pick, extra = git(repo, "log", "--merges", "--first-parent", "--format=%H", "main").split(), ["-m", "1"]
    elif op == "reapply":
        pick, extra = git(repo, "log", "--grep=This reverts", "--format=%H", "main").split(), []
    else:
        pick, extra = git(repo, "log", "--no-merges", "--format=%H", "main").split()[:-1], []
    if not pick:
        return True
    if op.startswith("revert-side"):
        git(repo, "checkout", "-q", "-b", f"r{seq}", "main")
    if not attempt(repo, "revert", "--no-edit", *extra, rnd.choice(pick)):
        attempt(repo, "revert", "--abort")
        return False
    if op.startswith("revert-side"):
        git(repo, "checkout", "-q", "main")
        flags = ["--no-ff"] if op == "revert-side" else ["-s", "ours", "--no-ff"]
        return attempt(repo, "merge", "-q", *flags, "-m", f"merge r{seq}", f"r{seq}")
    return True


def history(repo, rnd):
    git(repo, "init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    for seq in range(1, rnd.randint(4, 12) + 1):
        op = rnd.choice(OPERATIONS)
        if op == "main":
            work(repo, rnd, seq)
        elif op in ("side-real", "side-ours", "side-squash", "two-step-ours", "ours-touch"):
            if not side_branch(repo, rnd, seq, op):
                attempt(repo, "merge", "--abort")
                attempt(repo, "reset", "-q", "--hard")
        elif not revert_something(repo, rnd, seq, op):
            attempt(repo, "reset", "-q", "--hard")
            attempt(repo, "checkout", "-q", "main")


def share_at_the_tip(repo, sha):
    """How much of what this commit changed is at the tip as it left it: a fraction, or None if it changed nothing."""
    files = [f for f in git(repo, "-c", "log.showroot=true", "log", "-1", "-m", "--first-parent", "--format=", "--name-only", sha).split("\n") if f]
    if not files:
        return None
    same = 0
    for name in files:
        here = attempt(repo, "rev-parse", "--verify", "-q", f"{sha}:{name}") and git(repo, "rev-parse", "--verify", "-q", f"{sha}:{name}")
        tip = attempt(repo, "rev-parse", "--verify", "-q", f"main:{name}") and git(repo, "rev-parse", "--verify", "-q", f"main:{name}")
        same += here == tip
    return same / len(files)


class TheTruthAtTheTip(unittest.TestCase):
    def test_random_histories(self):
        wrong = []
        for seed in SEEDS:
            rnd = random.Random(seed)
            with tempfile.TemporaryDirectory() as folder:
                repo = pathlib.Path(folder).resolve() / "app"
                repo.mkdir()
                history(repo, rnd)
                shas = git(repo, "log", "--format=%H", "main").split()
                (repo / "status-table.md").write_text(
                    f"### 1. D ({len(shas)})\n\n| # | Name | Status | Note |\n|---|---|---|---|\n" + "".join(f"| {i} | r | Live | `{s}` |\n" for i, s in enumerate(shas, 1)))
                (repo / ".gitdone.json").write_text(json.dumps({"status_doc": "status-table.md", "repo": ".", "title": "T"}))
                (repo / ".git" / "info" / "exclude").write_text("status-table.md\n.gitdone.json\nSTATUS.md\n")
                rows = {r["claims"][0]["value"]: r["claims"][0] for r in report.rows_data(Plan(repo / ".gitdone.json"), offline=True) if r["claims"]}
                for sha in shas:
                    share = share_at_the_tip(repo, sha)
                    if share is None:
                        continue
                    state = rows[sha]["state"]
                    subject = git(repo, "log", "-1", "--format=%s", sha)
                    if subject.startswith(("Revert", "Reapply")):
                        continue
                    if state == "verified" and share == 0:
                        wrong.append(f"seed {seed}: {sha[:8]} {subject!r}: verified, and none of its bytes are at the tip")
                    elif state != "verified" and share == 1 and not subject.startswith(("merge", "ours")):
                        wrong.append(f"seed {seed}: {sha[:8]} {subject!r}: {rows[sha]['detail']}, and all its bytes are at the tip")
        self.assertEqual(wrong, [], "\n".join(wrong))


if __name__ == "__main__":
    unittest.main()
