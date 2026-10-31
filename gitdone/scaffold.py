"""`init`: a tracker in a project that has none, in under a minute.

It writes three files: `.gitdone.json` (the plan), `status-table.md` (the rows) and `STATUS.md` (the view). Rows come
from the command line, from a checklist, from GitHub issues, or from a prompt. A checked item is Live only if what its words name
holds. Otherwise it starts as Partial and says why, so the first number printed is already true.
"""
import json
import pathlib
import re
import sys

from . import evidence, gitio, table as tables
from .discover import POINTER
from .plan import DEFAULT_KINDS, PlanError, _kind
from .shipped import read_keeping_newlines, write_atomically

SCHEMA = "https://raw.githubusercontent.com/ArtJack/gitdone/main/schema/plan.schema.json"
TABLE_NAME = "status-table.md"
VIEW_NAME = "STATUS.md"
BADGE_NAME = "status-badge.svg"
FOOTER = "Tracked with [gitdone](https://github.com/ArtJack/gitdone): every Live row names its evidence, and git holds it to that."
CHECK_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[( |x|X)\]\s+(.+?)\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$")
FENCE = re.compile(r"^\s*(```+|~~~+)")
PLACEHOLDERS = ["First capability", "Second capability", "Third capability"]
TOP = DEFAULT_KINDS[0]["name"]
LAST = DEFAULT_KINDS[-1]["name"]
PARTIAL = "Partial"
CHECKED_NOTE = "*(Partial: checked off; no commit named yet)*"
NAMED_EVIDENCE = re.compile(r"\s*\(\s*(?:`?[0-9a-f]{7,64}`?|PR\s*#?\s*\d+|pull request\s*#?\s*\d+)\s*\)", re.I)
WORKFLOW = """name: status

on:
  push:
    branches: [{branch}]
  pull_request:

permissions:
  contents: read
  pull-requests: write  # for the comment

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0  # evidence needs the whole history
      - uses: ArtJack/gitdone@v0
"""
WORKFLOW_PATH = pathlib.PurePosixPath(".github/workflows/status.yml")

AGENTS_START = "<!-- gitdone:start -->"
AGENTS_END = "<!-- gitdone:end -->"
AGENTS_SNIPPET = f"""{AGENTS_START}
## Status tracking

This project tracks completion with [gitdone](https://github.com/ArtJack/gitdone).

- At the start of a session, run `gitdone`. It prints where the project stands and what comes next.
- `status-table.md` is the only place a status changes. `STATUS.md` is generated: never edit it by hand.
- When work is on the default branch, move its row with `gitdone shipped <row> <commit or PR>`. Use
  `gitdone mark <row> <kind>` for anything short of that.
- If `shipped` or the commit gate refuses, report the refusal. Do not reword the row to get past it, do not pass
  `--allow-unverified`, and do not commit with `--no-verify`.
- "Done" means the row moved. Say what the gate said, not what you believe.
{AGENTS_END}
"""


class Section:
    """One domain of a new table."""

    def __init__(self, name):
        self.name = name
        self.rows = []  # (name, status, note)


def _clean(words):
    return " ".join(str(words).split()).replace("|", "\\|")


def _evidence_words(text):
    """What a checklist item's own words name as a release, so a checked item with a commit starts out verified."""
    shas = [f"`{s}`" for s in evidence.find_shas(text)]
    prs = [f"PR #{n}" for n in evidence.find_prs(text)]
    return ", ".join(shas + prs)


def sections_from_rows(names):
    section = Section("Scope")
    section.rows = [(_clean(n), LAST, "") for n in names if _clean(n)]
    return [section]


def sections_from_checklist(text):
    """Each heading with items under it is a domain. `[x]` is the strict kind, and `[ ]` the last kind."""
    sections, current, heading, fence = [], None, "Scope", None
    for line in text.splitlines():
        opening = FENCE.match(line)
        if opening and fence is None:
            fence = opening.group(1)[0]
            continue
        if fence is not None:
            if opening and opening.group(1)[0] == fence:
                fence = None
            continue
        head = HEADING.match(line)
        if head:
            heading, current = _clean(head.group(1)), None
            continue
        item = CHECK_ITEM.match(line)
        if not item:
            continue
        if current is None:
            current = next((s for s in sections if s.name == heading), None)
            if current is None:
                current = Section(heading)
                sections.append(current)
        words = _clean(item.group(2))
        if item.group(1) == " ":
            current.rows.append((words, LAST, ""))
            continue
        named = _evidence_words(words)
        name = NAMED_EVIDENCE.sub("", words).strip() or words
        current.rows.append((name, TOP, named) if named else (words, PARTIAL, CHECKED_NOTE))
    return sections


def unproven_checked(sections):
    """Rows that were checked off and named nothing: `init` says so, so nobody reads Partial as a mistake."""
    return [n for n, row in enumerate((r for s in sections for r in s.rows), 1) if row[1] == PARTIAL and "no commit" in row[2]]


def sections_from_issues(items):
    """GitHub issues as rows, a domain per milestone. Closed as not planned is out of scope, so it is left out."""
    sections = {}
    for issue in sorted(items, key=lambda i: i["number"]):
        reason = str(issue.get("stateReason") or "").upper()
        if reason == "NOT_PLANNED":
            continue
        milestone = (issue.get("milestone") or {}).get("title") or "Scope"
        section = sections.setdefault(milestone, Section(_clean(milestone)))
        name = _clean(issue["title"])
        if str(issue.get("state", "")).upper() == "OPEN":
            section.rows.append((name, LAST, f"issue #{issue['number']}"))
            continue
        merged = [p["number"] for p in issue.get("closedByPullRequestsReferences") or [] if p.get("number")]
        if merged:
            section.rows.append((name, TOP, f"issue #{issue['number']}, " + ", ".join(f"PR #{n}" for n in merged)))
        else:
            section.rows.append((name, PARTIAL, f"issue #{issue['number']} *(Partial: closed; no commit named yet)*"))
    return list(sections.values())


def table_text(title, sections):
    lines = [f"# {title}: status table", "",
             f"The one place a row's status changes. `{VIEW_NAME}` is generated from this file: run",
             "`gitdone render --write` after editing it by hand, or use `shipped`, `mark` and `add`.", ""]
    number = 1
    for n, section in enumerate(sections, 1):
        lines += [f"### {n}. {section.name} ({len(section.rows)})", "", "| # | Name | Status | Note |", "|---|---|---|---|"]
        for name, status, note in section.rows:
            lines.append(f"| {number} | {name} | {status} | {note} |")
            number += 1
        lines.append("")
    return "\n".join(lines)


def default_branch(directory):
    """The branch a repository calls its default: the remote's word, else main or master, else the current one."""
    remote = gitio.git(directory, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if remote.code == 0 and "/" in remote.out:
        return remote.out.strip().split("/", 1)[1]
    for name in ("main", "master"):
        if gitio.git(directory, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").code == 0:
            return name
    current = gitio.git(directory, "symbolic-ref", "--short", "HEAD")
    return current.out.strip() if current.code == 0 else "main"


def plan_data(title, in_git, branch, table=TABLE_NAME, view=VIEW_NAME, badge=None):
    data = {"$schema": SCHEMA, "title": title, "status_doc": table, "status_out": view}
    if badge:
        data["badge"] = badge
    data["repo"] = "."  # before `git init`, this waits: evidence starts working the moment there is a repository
    data["default_branch"] = branch if in_git else "main"
    data["footer"] = FOOTER
    data["kinds"] = DEFAULT_KINDS
    return data


def _json_text(data):
    """Short kinds stay on one line each, so the file reads like a table of weights."""
    kinds = data["kinds"]
    rest = dict(data)
    rest["kinds"] = "@KINDS@"
    text = json.dumps(rest, indent=2, ensure_ascii=False)
    body = ",\n".join("    " + json.dumps(k, ensure_ascii=False) for k in kinds)
    return text.replace('"@KINDS@"', "[\n" + body + "\n  ]") + "\n"


def create(directory, title=None, sections=None, table=TABLE_NAME, view=VIEW_NAME, badge=None):
    """Write the plan and the table; the caller renders the view. Refuses to overwrite anything."""
    directory = pathlib.Path(directory).resolve()
    if not directory.is_dir():
        raise PlanError(f"{directory} is not a folder")
    if directory == pathlib.Path.home().resolve():
        raise PlanError("the home directory is not a project; run this in the project's folder")
    plan_path, table_path, view_path = directory / POINTER, directory / table, directory / view
    for path, flag in ((plan_path, None), (table_path, "--table"), (view_path, "--view"), *([(directory / badge, None)] if badge else [])):
        if path.exists():
            hint = f"; pass {flag} to use another name" if flag else ("; this project already has a tracker" if path == plan_path else "")
            raise PlanError(f"{path.name} exists and was left alone{hint}")
    sections = [s for s in (sections or []) if s.rows] or sections_from_rows(PLACEHOLDERS)
    title = title or directory.name
    in_git = gitio.git(directory, "rev-parse", "--git-dir").code == 0
    text = table_text(title, sections)
    problems = tables.parse(text, [_kind(k) for k in DEFAULT_KINDS]).problems
    if problems:  # write nothing that the next command could not read
        raise PlanError("these rows cannot make a table: " + "; ".join(problems))
    write_atomically(table_path, text)
    data = plan_data(title, in_git, default_branch(directory) if in_git else None, table, view, badge)
    write_atomically(plan_path, _json_text(data))
    return plan_path, in_git


def hold_to_git(plan):
    """A checked item says it is done, and git has the last word. A row whose claims do not hold starts as Partial, with the reason, before
    the first number is printed. Returns [(row, why)].
    """
    text, newline = read_keeping_newlines(plan.doc)
    table = tables.parse(text, plan.kinds)
    verifier = evidence.Verifier(plan)
    problem = verifier.problem()  # a shallow clone, say: nothing can be held to it, so nothing starts as held
    claims = {row.num: evidence.release_claims(plan, row.words()) for row in table.rows.values() if row.kind == plan.strict_kind.name}
    if not problem:
        verifier.preload([c for found in claims.values() for c in found])
    lines = text.split("\n")
    held_back = []
    for number, found in claims.items():
        results = [] if problem else [verifier.claim(c) for c in found]
        bad = next((r for r in results if r.state != evidence.VERIFIED), None)
        if found and results and not bad:
            continue
        row = table.rows[number]
        why = problem or (bad.detail if bad else "it names no commit")
        note = f"{row.note} *({PARTIAL}: checked off; {_clean(why)})*".strip()
        lines[row.line] = f"| {number} | {row.name} | {PARTIAL} | {note} |"
        held_back.append((number, why))
    if held_back:
        write_atomically(plan.doc, "\n".join(lines), newline)
    return held_back


def install_ci(plan):
    """The workflow that runs the gate on every pull request. The hook is a courtesy, and this is what cannot be skipped. Returns its path."""
    top = gitio.git(plan.dir, "rev-parse", "--show-toplevel")
    if top.code:
        raise PlanError(f"{plan.doc.name} is not in a git repository yet: run `git init` first")
    root = pathlib.Path(top.out.strip()).resolve()
    if plan.repo is not None and gitio.git(plan.repo, "rev-parse", "--show-toplevel").out.strip() != top.out.strip():
        raise PlanError("the plan's repo is another repository, and the Action can only see the one it checks out; see docs/ci.md")
    path = root / WORKFLOW_PATH
    if path.exists():
        raise PlanError(f"{WORKFLOW_PATH} exists and was left alone; add the Action to it by hand: `uses: ArtJack/gitdone@v0`")
    if not evidence.SAFE_REF.match(plan.default_branch):  # a plan is a stranger's words, and this file runs
        raise PlanError(f"default_branch: {plan.default_branch!r} cannot go into a workflow")
    text = WORKFLOW.format(branch=plan.default_branch)
    if plan.dir != root:
        text += f"        with:\n          working-directory: {json.dumps(plan.dir.relative_to(root).as_posix())}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, text)
    return path


def ask_for_rows(ask=input, stream=sys.stderr):
    """At a terminal with no rows given: ask for them, one per line."""
    print("What must exist for this to be done? One per line; an empty line ends.", file=stream)
    names = []
    while True:
        try:
            line = ask(f"  {len(names) + 1}. ").strip()
        except EOFError:
            break
        if not line:
            break
        names.append(line)
    return names


def keep_badge(plan_path, name=BADGE_NAME):
    """Name a badge in an existing plan, touching only that one line of the file."""
    path = pathlib.Path(plan_path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if data.get("badge"):
        return data["badge"]
    fresh = re.sub(r'^(\s*)("status_(?:out|doc)"\s*:\s*"[^"\n]*")(,?)[ \t]*$',
                   lambda m: f'{m.group(1)}{m.group(2)},\n{m.group(1)}"badge": {json.dumps(name)}{m.group(3)}',
                   text, count=1, flags=re.M)
    try:
        if json.loads(fresh).get("badge") != name:
            raise ValueError
    except ValueError:  # a plan on one line, or laid out some other way
        data["badge"] = name
        fresh = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    write_atomically(path, fresh)
    return name


def install_agents(directory):
    """Add the snippet to AGENTS.md, and to CLAUDE.md if the project has one. Returns the files written."""
    directory = pathlib.Path(directory)
    written = []
    targets = [directory / "AGENTS.md"] + ([directory / "CLAUDE.md"] if (directory / "CLAUDE.md").exists() else [])
    for path in targets:
        text, newline = read_keeping_newlines(path) if path.exists() else ("", "\n")
        if AGENTS_START in text and AGENTS_END in text.partition(AGENTS_START)[2]:
            head, _, rest = text.partition(AGENTS_START)
            _, _, tail = rest.partition(AGENTS_END + "\n" if AGENTS_END + "\n" in rest else AGENTS_END)
            fresh = head + AGENTS_SNIPPET + tail
        else:
            fresh = (text.rstrip("\n") + "\n\n" if text.strip() else "") + AGENTS_SNIPPET
        if fresh != text:
            write_atomically(path, fresh, newline)
            written.append(path)
    return written
