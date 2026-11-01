#!/usr/bin/env python3
"""The README's instruction, run for real in a throwaway repository: every step a new project takes, and what each one prints. A test runs this and compares.

    python3 docs/demo/guide.py            print the blocks
    python3 docs/demo/guide.py --write    rewrite the README's blocks
"""
import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _recorder():
    spec = importlib.util.spec_from_file_location("record", ROOT / "docs" / "demo" / "record.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def produce(folder):
    """{step: a console block}: one session, one repository, in the README's order."""
    s = _recorder().Session(folder)
    s.shell("git init -q -b main")
    s.date = "2026-03-02"
    steps, lines = {}, []

    def run(command, keep=None):
        lines.append(f"$ {command}")
        lines.extend(line for line in s.shell(command) if keep is None or keep(line))
        lines.append("")

    def close(name):
        steps[f"guide-{name}"] = "```console\n" + "\n".join(lines).rstrip() + "\n```"
        lines.clear()

    run('gitdone init --rows "Sign-in, Search, Export, Reports" --hook', keep=lambda line: line.startswith(("wrote", "All:")))
    run("git add .gitdone.json status-table.md STATUS.md && git commit -q -m 'Track the scope'", keep=lambda line: line.startswith("result"))
    close("begin")
    run("gitdone")
    close("open")
    s.date = "2026-03-03"
    s.shell("echo code > signin.py && echo code > search.py")
    run("git add signin.py && git commit -q -m 'row 1: sign-in'")
    landed = s.shell("git rev-parse --short HEAD")[0]
    run("git switch -q -c search && git add search.py && git commit -q -m 'row 2: search by title'")
    run("git switch -q main")
    close("work")
    run(f"gitdone shipped 1 {landed}")
    run("gitdone mark 2 built --branch search")
    run('gitdone mark 3 partial "CSV works, PDF does not yet"')
    close("move")
    run('gitdone add "Password reset"')
    run("gitdone remove 4")
    close("scope")
    run("git add status-table.md STATUS.md && git commit -q -m 'Sign-in is live'", keep=lambda line: line.startswith(("result", "FAIL")))
    close("commit")
    run("gitdone")
    run('gitdone week "1 month"', keep=lambda line: bool(line.strip()))
    close("read")
    return steps


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory() as folder:
        steps = produce(folder)
    if "--write" not in args:
        print("\n\n".join(steps.values()))
        return 0
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for name, block in steps.items():
        head, _, rest = text.partition(f"<!-- {name}:start -->")
        _, _, tail = rest.partition(f"<!-- {name}:end -->")
        text = f"{head}<!-- {name}:start -->\n{block}\n<!-- {name}:end -->{tail}"
    readme.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
