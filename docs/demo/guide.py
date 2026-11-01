#!/usr/bin/env python3
"""The README's instruction, run for real in a throwaway repository: every step a new project takes, and what each one prints. A test runs this and compares.

    python3 docs/demo/guide.py            print the block
    python3 docs/demo/guide.py --write    rewrite the README's block
"""
import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
START, END = "<!-- guide:start -->", "<!-- guide:end -->"


def _recorder():
    spec = importlib.util.spec_from_file_location("record", ROOT / "docs" / "demo" / "record.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session(folder):
    """[(kind, text)], as `record.transcript` gives them."""
    s = _recorder().Session(folder)
    s.shell("git init -q -b main")
    s.date = "2026-03-02"
    out = []

    def say(text):
        out.append(("say", text))

    def run(command, keep=None):
        out.append(("cmd", command))
        out.extend(("out", line) for line in s.shell(command) if keep is None or keep(line))
        out.append(("gap", ""))

    say("# Say what must exist, and commit it. The hook guards the next commit on.")
    run('gitdone init --rows "Sign-in, Search, Export, Reports" --hook', keep=lambda line: line.startswith(("wrote", "All:")))
    run("git add -A && git commit -q -m 'Track the scope'", keep=lambda line: line.startswith("result"))
    say("# Open the project: where it stands, and what comes next.")
    run("gitdone")
    say("# Work, and name the row in the commit message.")
    s.date = "2026-03-03"
    s.shell("echo code > signin.py && git add signin.py")
    run("git commit -q -m 'row 1: sign-in'")
    landed = s.shell("git rev-parse --short HEAD")[0]
    s.shell("git switch -q -c search && echo code > search.py && git add search.py && git commit -q -m 'row 2: search by title' && git switch -q main")
    say("# It is on main, so the row can say so. Git is asked, and it agrees.")
    run(f"gitdone shipped 1 {landed}")
    say("# Work short of main counts too, in the weighted number only.")
    run("gitdone mark 2 built --branch search")
    run('gitdone mark 3 partial "CSV works, PDF does not yet"')
    say("# A change of scope is a decision, and the percent says what it cost.")
    run('gitdone add "Password reset"')
    run("gitdone remove 4")
    say("# Commit what moved. The gate runs here.")
    run("git add status-table.md STATUS.md && git commit -q -m 'Sign-in is live; scope: password reset in, reports out'", keep=lambda line: line.startswith(("result", "FAIL")))
    say("# The scale now, and what moved since the start.")
    run("gitdone")
    run('gitdone week "1 month"', keep=lambda line: bool(line.strip()))
    return out


def block(lines):
    return "```console\n" + _recorder().console_block(lines).rstrip() + "\n```"


def produce(folder):
    return block(session(folder))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory() as folder:
        text = produce(folder)
    if "--write" not in args:
        print(text)
        return 0
    readme = ROOT / "README.md"
    head, _, rest = readme.read_text(encoding="utf-8").partition(START)
    _, _, tail = rest.partition(END)
    readme.write_text(f"{head}{START}\n{text}\n{END}{tail}", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
