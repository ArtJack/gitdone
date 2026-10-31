#!/usr/bin/env python3
"""The README's timeline section, from the fictional Bramble Kiosk's generated history, on a fixed day. A test runs this and compares.

    python3 docs/demo/timeline.py            print the blocks
    python3 docs/demo/timeline.py --write    rewrite the README's blocks and docs/img/bramble-burndown.svg
"""
import datetime
import importlib.util
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from gitdone import chart, edit, focus, forecast  # noqa: E402
from gitdone.plan import Plan  # noqa: E402

TODAY = datetime.date(2026, 3, 3)
START, END = "<!-- timeline:start -->", "<!-- timeline:end -->"


def _history():
    spec = importlib.util.spec_from_file_location("make_history", ROOT / "docs" / "demo" / "make_history.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def produce(folder):
    """(the console block, the burn-down, the docs' samples) from a history built in `folder`."""
    repo = pathlib.Path(folder) / "bramble"
    _history().main([str(repo)])
    plan = Plan(repo / "plan.json")
    found = forecast.data(plan, today=TODAY)
    picture = chart.burndown(chart.points(plan, today=TODAY.isoformat()), plan.title, found, forecast.headline(found))
    before = forecast.left_now(plan)
    number = edit.add(plan, "Self-service printing", domain="1")
    moved = forecast.shift_words(plan, before, today=TODAY)
    edit.remove(plan, number)
    drift = focus.data(plan, today=TODAY)
    block = ["```console", "$ gitdone eta", forecast.text(found), "", '$ gitdone add "Self-service printing"', f"added row {number}", moved, "",
             "$ gitdone focus", focus.text(drift), "```"]
    samples = {"eta": "```text\n" + forecast.text(found).split("\n\nIn the plan's order")[0] + "\n```", "focus": "```text\n" + focus.text(drift).split("\n\nOff plan or unclear")[0] + "\n```"}
    return "\n".join(block), picture, samples


def spliced(text, block, start=START, end=END):
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    return f"{head}{start}\n{block}\n{end}{tail}"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    with tempfile.TemporaryDirectory() as folder:
        block, picture, samples = produce(folder)
    if "--write" not in args:
        print(block)
        return 0
    readme = ROOT / "README.md"
    readme.write_text(spliced(readme.read_text(encoding="utf-8"), block), encoding="utf-8")
    (ROOT / "docs" / "img" / "bramble-burndown.svg").write_text(picture, encoding="utf-8")
    doc = ROOT / "docs" / "timeline.md"
    text = doc.read_text(encoding="utf-8")
    for name, sample in samples.items():
        text = spliced(text, sample, f"<!-- {name}:start -->", f"<!-- {name}:end -->")
    doc.write_text(text, encoding="utf-8")
    return 0


def normalized(text):
    """A commit's id is the one thing that can differ between machines' git."""
    return re.sub(r"\b[0-9a-f]{7}\b", "xxxxxxx", text)


if __name__ == "__main__":
    sys.exit(main())
