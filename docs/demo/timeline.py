#!/usr/bin/env python3
"""What the README and docs/timeline.md show of the fictional Bramble Kiosk, from its generated history, on a fixed day. A test runs this and compares.

    python3 docs/demo/timeline.py            print the README's blocks
    python3 docs/demo/timeline.py --write    rewrite the blocks, docs/timeline.md's samples and the pictures in docs/img
"""
import collections
import datetime
import importlib.util
import json
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from gitdone import chart, ci, edit, focus, forecast, gate, gitio, portfolio, render, shipped, table as tables  # noqa: E402
from gitdone.plan import Plan  # noqa: E402

TODAY = datetime.date(2026, 3, 3)
START, END = "<!-- timeline:start -->", "<!-- timeline:end -->"
Shown = collections.namedtuple("Shown", "blocks pictures samples")


def _module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "docs" / "demo" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quoted(text):
    """Quoted, so that a heading stays out of the README's outline."""
    lines = []
    for line in text.strip().split("\n"):
        lines.append("> " + (f"**{line[3:]}**" if line.startswith("## ") else line))
    return "\n".join(line.rstrip() for line in lines)


def _the_scale(plan, table):
    return "\n".join(["```console", "$ gitdone", render.opener(plan, table), *render.scale_lines(plan, table), focus.opener_line(plan, today=TODAY), "```"])


def _the_view(plan, table):
    view = render.status_md(plan, table)
    next_line = view.index("**Next, in order:**")
    return _quoted(view[view.index("\n## "):view.index("\n", next_line)])


def _the_comment(plan, table):
    base = gitio.git(plan.dir, "rev-parse", "--short", "HEAD~1").out.strip()
    words = ci.summary(plan, table, gate.report(plan, offline=True), base=base, branch="main")
    return _quoted(words.replace(ci.MARKER + "\n", ""))


def _the_portfolio(folder):
    record = _module("record")
    record.transcript(folder)
    page = portfolio.markdown(portfolio.scan([folder]), today=TODAY.isoformat())
    return "\n".join(line for line in page.split("\n") if line.startswith("|"))


def produce(folder):
    """What is shown, from a history built in `folder`."""
    repo = pathlib.Path(folder) / "bramble"
    _module("make_history").main([str(repo)])
    plan = Plan(repo / "plan.json")
    found = forecast.data(plan, today=TODAY)
    burndown = chart.burndown(chart.points(plan, today=TODAY.isoformat()), plan.title, found, forecast.headline(found))
    before = forecast.left_now(plan)
    number = edit.add(plan, "Self-service printing", domain="1")
    moved = forecast.shift_words(plan, before, today=TODAY)
    edit.remove(plan, number)
    table = tables.load_clean(plan)
    shipped.write_view(plan, table)
    drift = focus.text(focus.data(plan, today=TODAY))
    (repo / ".gitdone.json").write_text(json.dumps({"plan": "plan.json"}), encoding="utf-8")
    blocks = {"timeline": "\n".join(["```console", "$ gitdone focus", drift, "```"]), "scale": _the_scale(plan, table), "scale-view": _the_view(plan, table),
              "scale-comment": _the_comment(plan, table), "scale-portfolio": _the_portfolio(folder)}
    samples = {"eta": "```text\n" + forecast.text(found).split("\n\nIn the plan's order")[0] + "\n```",
               "add": "\n".join(["```console", '$ gitdone add "Self-service printing"', f"added row {number}", moved, "```"]),
               "focus": "```text\n" + drift.split("\n\nOff plan or unclear")[0] + "\n```"}
    return Shown(blocks, {"bramble-burndown.svg": burndown, "bramble-scale.svg": chart.scale(plan, table)}, samples)


def spliced(text, block, start=START, end=END):
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n{block}\n{end}{tail}"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory() as folder:
        shown = produce(folder)
    if "--write" not in args:
        print("\n\n".join(shown.blocks.values()))
        return 0
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for name, block in shown.blocks.items():
        text = spliced(text, block, f"<!-- {name}:start -->", f"<!-- {name}:end -->")
    readme.write_text(text, encoding="utf-8")
    for name, picture in shown.pictures.items():
        (ROOT / "docs" / "img" / name).write_text(picture, encoding="utf-8")
    doc = ROOT / "docs" / "timeline.md"
    text = doc.read_text(encoding="utf-8")
    for name, sample in shown.samples.items():
        text = spliced(text, sample, f"<!-- {name}:start -->", f"<!-- {name}:end -->")
    doc.write_text(text, encoding="utf-8")
    return 0


def normalized(text):
    """A commit's id is the one thing that can differ between machines' git."""
    return re.sub(r"\b[0-9a-f]{7}\b", "xxxxxxx", text)


if __name__ == "__main__":
    sys.exit(main())
