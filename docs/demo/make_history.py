#!/usr/bin/env python3
"""Give the fictional Bramble Kiosk a git history, so that the README's chart is produced by the real command.

    python3 docs/demo/make_history.py /tmp/bramble     build the repository there (the folder must not exist)

The history is invented, and the README says so. Its last commit holds the same statuses as examples/bramble. Every date
is fixed, so two runs give the same chart.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
EXAMPLE = ROOT / "examples" / "bramble"
IDENTITY = {"GIT_AUTHOR_NAME": "Bramble", "GIT_AUTHOR_EMAIL": "kiosk@example.com", "GIT_COMMITTER_NAME": "Bramble",
            "GIT_COMMITTER_EMAIL": "kiosk@example.com"}

# (date, what changed): the kinds a row holds from that date on. Domain 5 joins the scope on the third date.
TIMELINE = [
    ("2026-01-12", {}),
    ("2026-01-20", {1: "Partial"}),
    ("2026-01-29", {1: "Live", 2: "Partial"}),
    ("2026-02-06", {5: "Partial", 4: "Partial", "scope": "later"}),
    ("2026-02-13", {2: "Live", 5: "Demo only"}),
    ("2026-02-20", {3: "Partial", 9: "Partial", 15: "Partial"}),
    ("2026-02-24", {6: "Demo only", 7: "Partial"}),
    ("2026-02-27", {3: "Built, not live (reading-lists)", 5: "Live", 10: "Partial"}),
    ("2026-03-02", {7: "Built, not live (renewals)", 9: "Live"}),
]


def git(repo, *args, date=None):
    env = {**os.environ, **IDENTITY}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00+00:00"
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], env=env, check=True, capture_output=True, text=True).stdout.strip()


def table_at(body, kinds, with_later):
    """The example's domains with each row at the kind it held then. The later domains stay out until they join the scope."""
    text = body if with_later else body[:body.index("## Later")]
    out = []
    for line in text.split("\n"):
        row = re.match(r"^\| (\d+) \| (.+?) \| ", line)
        if not row:
            out.append(line)
            continue
        number = int(row.group(1))
        status = kinds.get(number, "Not built")
        note = {"Live": f"`{kinds['shas'].get(number)}`", "Partial": "in progress"}.get(status, "")
        out.append(f"| {number} | {row.group(2)} | {status} | {note} |")
    return "\n".join(out)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    repo = pathlib.Path(args[0])
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    plan = json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))
    for key in ("rows_total", "groups", "sections", "products", "workstreams", "order", "decisions", "asks", "candidates", "release", "scale", "noun"):
        plan.pop(key, None)
    plan.update({"title": "Bramble Kiosk", "repo": ".", "default_branch": "main"})
    (repo / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    text = (EXAMPLE / "status-table.md").read_text(encoding="utf-8")
    body = "# Bramble Kiosk: status table\n\n" + text[text.index("### 1. "):]
    kinds = {"shas": {}}
    with_later = False
    for number, (date, change) in enumerate(TIMELINE, 1):
        (repo / "kiosk.txt").write_text(f"kiosk code, step {number}\n", encoding="utf-8")
        git(repo, "add", "kiosk.txt")
        git(repo, "commit", "-q", "--no-verify", "-m", f"Kiosk code, step {number}", date=date)
        sha = git(repo, "rev-parse", "--short", "HEAD")
        for key, status in change.items():
            if key == "scope":
                with_later = True
                continue
            kinds[key] = status
            if status == "Live":
                kinds["shas"][key] = sha
        (repo / "status-table.md").write_text(table_at(body, kinds, with_later), encoding="utf-8")
        git(repo, "add", "status-table.md", "plan.json")
        git(repo, "commit", "-q", "--no-verify", "-m", f"Status on {date}", date=date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
