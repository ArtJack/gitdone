#!/usr/bin/env python3
"""Run the README's demo for real in a throwaway repository, and write what it printed as an animated SVG.

    python3 docs/demo/record.py docs/img/demo.svg --readme README.md
    python3 docs/demo/record.py /tmp/frame.svg --at 12    one still frame, to look at

Every line of output is what the engine printed. Dates and identities are fixed, so the commit ids are the same each run.
No recording software is needed, and the file is small, sharp at any size, and honest: run it again and it would say the same.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
COLUMNS, ROWS = 92, 27
CHAR, LINE, PAD, HEAD = 7.8, 19, 16, 34
WIDTH = round(COLUMNS * CHAR + 2 * PAD)
HEIGHT = ROWS * LINE + HEAD + PAD
TYPE_SECONDS, OUTPUT_SECONDS, AFTER_COMMAND, AFTER_BLOCK, HOLD = 0.035, 0.09, 0.45, 2.0, 6.0
POSTER = 4.0  # the whole session shows first: a reader who glances, or a viewer that does not animate, still sees the story

STYLE = """
.bg{fill:#14161a}.edge{fill:none;stroke:#2c3036}.dot{fill:#3a3f46}
text{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:13px;fill:#d7dae0;white-space:pre}
.say{fill:#8b93a1}.cmd{fill:#f0f2f5}.prompt{fill:#6cb6ff}.bad{fill:#ff7b72}.good{fill:#56d364}.title{fill:#8b93a1;font-size:12px}
.mark{fill:#14161a}
"""
# The engine stamps a row with today, the stamp goes in a commit, and so in the id of every commit after it. So the session has a calendar of its own.
CALENDAR = """import datetime, os, runpy


class Fixed(datetime.date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(os.environ["DEMO_TODAY"])


datetime.date = Fixed
runpy.run_module("gitdone", run_name="__main__", alter_sys=True)
"""


def identity(date):
    return {"GIT_AUTHOR_NAME": "Demo", "GIT_AUTHOR_EMAIL": "demo@example.com", "GIT_COMMITTER_NAME": "Demo", "GIT_COMMITTER_EMAIL": "demo@example.com",
            "GIT_AUTHOR_DATE": f"{date}T12:00:00+00:00", "GIT_COMMITTER_DATE": f"{date}T12:00:00+00:00"}


class Session:
    """A throwaway repository, and the engine on PATH as the bare command a reader would type."""

    def __init__(self, folder):
        self.repo = pathlib.Path(folder) / "kiosk"
        self.repo.mkdir()
        tools = pathlib.Path(folder) / "tools"
        tools.mkdir()
        calendar = tools / "calendar.py"
        calendar.write_text(CALENDAR, encoding="utf-8")
        shim = tools / "gitdone"
        shim.write_text(f'#!/bin/sh\nPYTHONPATH="{ROOT}" exec "{sys.executable}" "{calendar}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        self.env = {**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "HOME": str(folder)}
        self.env.pop("PYTHONPATH", None)
        self.date = "2026-03-01"

    def shell(self, command):
        env = {**self.env, **identity(self.date), "DEMO_TODAY": self.date}
        done = subprocess.run(["sh", "-c", command], cwd=str(self.repo), env=env, capture_output=True, text=True, encoding="utf-8")
        return (done.stdout + done.stderr).rstrip("\n").split("\n") if (done.stdout + done.stderr).strip() else []

    def land(self, name, message, date):
        self.date = date
        self.shell(f"echo code > {name} && git add {name} && git commit -q -m '{message}'")
        return self.shell("git rev-parse --short HEAD")[0]


class Session_lines(list):
    """The session's lines, and the view as it stood after the first real row moved."""
    view = ""


def transcript(folder):
    """[(kind, text)]: `say` for narration, `cmd` for what is typed, `out` for what came back."""
    s = Session(folder)
    s.shell("git init -q -b main")
    landed = s.land("signin.py", "Add sign-in", "2026-03-02")
    s.shell("git switch -q -c spike")
    spike = s.land("search.py", "Try a search idea", "2026-03-03")
    s.shell("git switch -q main")
    s.date = "2026-03-04"
    out = Session_lines()

    def say(text):
        out.append(("say", text))

    def run(command, keep=None, shown=None):
        lines = s.shell(command)
        out.append(("cmd", shown or command))
        for line in lines:
            if keep is None or keep(line):
                out.append(("out", line))
        out.append(("gap", ""))

    say("# Four things must exist for this to be done.")
    run('gitdone init --rows "Sign-in, Search, Export, Reports" --hook',
        keep=lambda line: line.startswith(("wrote", "All:")))
    s.shell("git add -A && git commit -q -m 'Track the scope'")
    say("# The agent says sign-in shipped, and names a commit from its spike branch.")
    run(f"gitdone shipped 1 {spike}", keep=lambda line: not line.startswith("Squashed"))
    say("# The commit that really landed:")
    run(f"gitdone shipped 1 {landed}")
    s.shell("git add -A && git commit -q -m 'Sign-in is live'")
    view = (s.repo / "STATUS.md").read_text(encoding="utf-8")
    say("# Someone types Live into the table by hand, with nothing behind it.")
    table = s.repo / "status-table.md"
    text = table.read_text(encoding="utf-8")
    table.write_text(text.replace("| 2 | Search | Not built |  |", "| 2 | Search | Live |  |"), encoding="utf-8")
    s.shell("gitdone render --write")
    run("git add -A && git commit -m 'Search is live'", keep=lambda line: line.startswith(("FAIL", "result")))
    s.shell("git reset -q --hard")
    say("# Later, sign-in is reverted on main. The claim stops holding.")
    s.date = "2026-03-09"
    s.shell(f"git revert --no-edit {landed}")
    run("gitdone check", keep=lambda line: line.startswith(("FAIL", "result", "  what")))
    say("# Your agent says it shipped. Git decides.")
    out.view = view
    return out


def _spans(kind, text):
    if kind == "say":
        return f'<tspan class="say">{escape(text)}</tspan>'
    if kind == "cmd":
        return f'<tspan class="prompt">$ </tspan><tspan class="cmd">{escape(text)}</tspan>'
    style = ""
    if text.startswith(("refused", "FAIL", "result: FAIL")):
        style = "bad"
    elif "verified" in text and "→" in text:
        style = "good"
    return f'<tspan class="{style}">{escape(text)}</tspan>' if style else escape(text)


def svg(lines, at=None):
    """A CSS timeline: each line appears at its moment, a command types itself out, and the screen scrolls when it fills."""
    t = POSTER + 0.5
    timed = []
    index = 0
    for kind, text in lines:
        if kind == "gap":
            t += AFTER_BLOCK
            timed.append(("gap", "", t, t, index))
            index += 1
            continue
        start = t
        if kind == "cmd":
            t += len(text) * TYPE_SECONDS + AFTER_COMMAND
        elif kind == "say":
            t += 0.9
        else:
            t += OUTPUT_SECONDS
        timed.append((kind, text, start, t, index))
        index += 1
    total = t + HOLD

    def pct(seconds):
        return f"{100 * seconds / total:.3f}"

    keyframes, body = [], []
    for n, (kind, text, start, end, row) in enumerate(timed):
        if kind == "gap":
            continue
        y = HEAD + (row + 1) * LINE - 5
        keyframes.append(f"@keyframes a{n}{{0%,{pct(POSTER)}%{{opacity:1}}{pct(POSTER + 0.01)}%,{pct(start)}%{{opacity:0}}{pct(start + 0.01)}%,100%{{opacity:1}}}}")
        body.append(f'<text x="{PAD}" y="{y}" style="animation-name:a{n}">{_spans(kind, text)}</text>')
        if kind == "cmd":
            width = round((len(text) + 1) * CHAR + 40)
            typed = pct(start + len(text) * TYPE_SECONDS)
            keyframes.append(f"@keyframes m{n}{{0%,{pct(POSTER)}%{{transform:translateX({width}px)}}{pct(POSTER + 0.01)}%,{pct(start)}%{{transform:translateX(0)}}{typed}%,100%{{transform:translateX({width}px)}}}}")
            x = round(PAD + 2 * CHAR)
            body.append(f'<rect class="mark" x="{x}" y="{y - 14}" width="{width}" height="{LINE}" '
                        f'style="animation-name:m{n};animation-timing-function:steps({max(len(text), 1)})"/>')
    final = max(0, len(timed) - ROWS) * LINE
    moves = [f"0%{{transform:translateY({-final}px)}}", f"{pct(POSTER + 0.01)}%{{transform:translateY(0)}}"]
    scrolled = 0
    for _, _, start, _, row in timed:
        needed = max(0, row + 1 - ROWS)
        if needed > scrolled:
            scrolled = needed
            moves.append(f"{pct(start)}%{{transform:translateY({-scrolled * LINE}px)}}")
    moves.append(f"100%{{transform:translateY({-final}px)}}")
    keyframes.append("@keyframes scroll{" + "".join(moves) + "}")
    freeze = f"*{{animation-play-state:paused!important;animation-delay:-{at}s!important}}" if at is not None else ""
    motion = f"text,.mark,.screen{{animation-duration:{total:.2f}s;animation-iteration-count:infinite;animation-fill-mode:both}}.screen{{animation-name:scroll;animation-timing-function:step-end}}"
    still = f".screen{{transform:translateY({-final}px)}}@media (prefers-reduced-motion:reduce){{text,.mark,.screen{{animation:none!important}}.mark{{display:none}}}}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="A terminal session: '
            'a commit from a spike branch is refused, the commit on main is accepted, a hand-edited claim stops the commit, and a reverted commit fails the gate.">\n'
            f"<style>{STYLE}{motion}{still}{freeze}\n" + "\n".join(keyframes) + "\n</style>\n"
            f'<clipPath id="c"><rect x="0" y="{HEAD - 2}" width="{WIDTH}" height="{HEIGHT - HEAD}"/></clipPath>\n'
            f'<rect class="bg" width="{WIDTH}" height="{HEIGHT}" rx="9"/><rect class="edge" x=".5" y=".5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="9"/>\n'
            '<circle class="dot" cx="18" cy="17" r="5"/><circle class="dot" cx="36" cy="17" r="5"/><circle class="dot" cx="54" cy="17" r="5"/>\n'
            f'<text class="title" x="{WIDTH / 2:.0f}" y="21" text-anchor="middle" style="animation:none">a real session, recorded by docs/demo/record.py</text>\n'
            '<g clip-path="url(#c)"><g class="screen">\n' + "\n".join(body) + "\n</g></g>\n</svg>\n")


def console_block(lines):
    """The same session as text, for the README."""
    out = []
    for kind, text in lines:
        if kind == "say":
            out.append(text)
        elif kind == "cmd":
            out.append(f"$ {text}")
        elif kind == "out":
            out.append(text)
        else:
            out.append("")
    return "\n".join(out)


def view_block(view):
    """The session's STATUS.md from its first section on, quoted so that its headings stay out of the README's outline."""
    body = view[view.index("\n## "):].strip()
    lines = []
    for line in body.split("\n"):
        if line.startswith("## "):
            line = f"**{line[3:]}**"
        lines.append(f"> {line}".rstrip())
    return "\n".join(lines)


def update_readme(path, lines):
    """Replace what sits between the markers, so that the README cannot drift from what the engine printed and wrote."""
    readme = pathlib.Path(path)
    text = readme.read_text(encoding="utf-8")
    demo = "<!-- demo:start -->\n```console\n" + console_block(lines) + "\n```\n<!-- demo:end -->"
    text = re.sub(r"<!-- demo:start -->.*?<!-- demo:end -->", lambda _: demo, text, flags=re.S)
    view = "<!-- view:start -->\n" + view_block(lines.view) + "\n<!-- view:end -->"
    text = re.sub(r"<!-- view:start -->.*?<!-- view:end -->", lambda _: view, text, flags=re.S)
    readme.write_text(text, encoding="utf-8")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    at = None
    readme = None
    if "--readme" in args:
        where = args.index("--readme")
        readme = args[where + 1]
        del args[where:where + 2]
    if "--at" in args:
        where = args.index("--at")
        at = float(args[where + 1])
        del args[where:where + 2]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as folder:
        lines = transcript(folder)
    wide = [t for k, t in lines if len(t) + (2 if k == "cmd" else 0) > COLUMNS]
    if wide:
        print("too wide for the screen:", *wide, sep="\n  ", file=sys.stderr)
    target = pathlib.Path(args[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg(lines, at=at), encoding="utf-8")
    if readme:
        update_readme(readme, lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
