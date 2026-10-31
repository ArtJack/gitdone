"""A fictional project on disk: the Bramble example, beside a real git repository of its kiosk code."""
import atexit
import contextlib
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "bramble"
ENGINE = ROOT / "tests" / "engine.py"
sys.path.insert(0, str(ROOT))

from gitdone import cli, render, table as tables  # noqa: E402
from gitdone.plan import Plan  # noqa: E402

IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]


# A stranger's global git config (a hooks path, signed tags) must not reach the suite, or the suite reach it.
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
ISOLATED = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in ISOLATED}


def git(repo, *args, env=None):
    done = subprocess.run(["git", *IDENTITY, "-C", str(repo), *args], env={**clean_env(), **(env or {})},
                          capture_output=True, text=True)
    if done.returncode:
        raise AssertionError(f"git {args}: {done.stderr}")
    return done.stdout.strip()


def commit(repo, name, text, message="change", env=None):
    (pathlib.Path(repo) / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message, env=env)
    return git(repo, "rev-parse", "HEAD")


def needs_sh(case):
    """A stub is a shell script. Windows finds a program by its extension, so these tests are for the other two systems."""
    if os.name == "nt":
        case.skipTest("the stubs are shell scripts")


_app_template = None


def app_template():
    """(path, oldest sha, main sha, stray sha) of the kiosk repository. Built once a run; each test copies it."""
    global _app_template
    if _app_template is None:
        holder = tempfile.TemporaryDirectory()
        atexit.register(holder.cleanup)
        app = pathlib.Path(holder.name).resolve() / "app"
        app.mkdir()
        git(app, "init", "-q", "-b", "main")
        old = commit(app, "a.txt", "1\n")
        main = commit(app, "a.txt", "2\n")
        for branch in ("reading-lists", "renewals"):
            git(app, "checkout", "-q", "-b", branch)
            commit(app, f"{branch}.txt", "x\n")
            git(app, "checkout", "-q", "main")
        git(app, "checkout", "-q", "-b", "stray")
        stray = commit(app, "stray.txt", "x\n")
        git(app, "checkout", "-q", "main")
        _app_template = (app, old, main, stray)
    return _app_template


class ProjectCase(unittest.TestCase):
    """setUp builds tmp/app (a repository: main, two feature branches, one stray commit) and tmp/project (the example)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.app = self.tmp / "app"
        template, self.sha_old, self.sha_main, self.sha_stray = app_template()
        shutil.copytree(template, self.app)
        self.project = self.tmp / "project"
        shutil.copytree(EXAMPLE, self.project)
        self.plan_path = self.project / "plan.json"
        self.table_path = self.project / "status-table.md"
        self.view_path = self.project / "STATUS.md"
        text = self.table_path.read_text().replace("1a2b3c4", self.sha_old[:7]).replace("5d6e7f8", self.sha_main[:7])
        self.table_path.write_text(text)
        data = json.loads(self.plan_path.read_text())
        data["repo"] = "../app"
        data["release"] = data["release"].replace("5d6e7f8", self.sha_main[:7])
        self.plan_path.write_text(json.dumps(data))
        self.write_view()

    def plan(self):
        return Plan(self.plan_path)

    def write_view(self):
        plan = self.plan()
        self.view_path.write_text(render.status_md(plan, tables.load_clean(plan)))

    def change_plan(self, **changes):
        data = json.loads(self.plan_path.read_text())
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        self.plan_path.write_text(json.dumps(data))
        self.write_view()

    def set_row(self, number, status, note, view=True):
        """Rewrite one row of the status table, keep the embedded counts true, and by default regenerate the view."""
        lines = self.table_path.read_text().split("\n")
        for i, line in enumerate(lines):
            if line.startswith(f"| {number} | ") and line.count("|") >= 4 and "### " not in line:
                name = line.split("|")[2].strip()
                if not name.replace(" ", "").isdigit():
                    lines[i] = f"| {number} | {name} | {status} | {note} |"
        text = "\n".join(lines)
        plan = self.plan()
        self.table_path.write_text(render.splice_counts(text, render.counts_table(plan, tables.parse(text, plan.kinds))))
        if view:
            self.write_view()

    def cli(self, *args, plan=True):
        """Run a command in this process: (exit code, stdout, stderr)."""
        argv = list(args) + (["--plan", str(self.plan_path)] if plan else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def fake_gh(self, prs=None, fail=None):
        """A `gh` on PATH that answers from a list, or fails; it records that it was called."""
        needs_sh(self)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        self.gh_calls = self.tmp / "gh-calls"
        answer = self.tmp / "gh-answer.json"
        # A forge names the commit that landed a merged pull request. A stub that says nothing about it is testing another path.
        merged = [{**pr, "mergeCommit": {"oid": self.sha_main}} if pr.get("state") == "MERGED" and "mergeCommit" not in pr else pr for pr in prs or []]
        answer.write_text(json.dumps(merged))
        body = f'#!/bin/sh\necho "$@" >> "{self.gh_calls}"\n'
        body += f'echo "{fail}" >&2\nexit 1\n' if fail else f'cat "{answer}"\n'
        gh = bin_dir / "gh"
        gh.write_text(body)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def add_remote(self, url="https://example.invalid/someone/kiosk.git", name="origin"):
        """A remote as a clone has one: named, and holding every branch as it stands."""
        git(self.app, "remote", "add", name, url)
        self.push(name)

    def push(self, name="origin"):
        """What a push leaves behind in the clone. Nothing in these tests needs the far end."""
        for ref in git(self.app, "for-each-ref", "--format=%(refname:short)", "refs/heads").split():
            git(self.app, "update-ref", f"refs/remotes/{name}/{ref}", ref)
