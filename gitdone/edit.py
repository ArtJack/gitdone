"""`add` and `mark`: the changes to a table that need no release, so that nobody has to hand-edit its shape.

`shipped` stays the only way a row reaches the strict kind. These two refuse that, and hold every other kind to its rule.
"""
import datetime
import os
import re

from . import evidence, gitio, history, table as tables
from .plan import PlanError
from .shipped import Refused, fold_note, read_keeping_newlines, save

TABLE_HEAD = ["| # | Name | Status | Note |", "|---|---|---|---|"]


ID_WORD = re.compile(r"[A-Z][A-Z0-9]{0,9}-\d{1,9}(?:\.\d{1,9})*")
OLD_ROW_NUMBER = re.compile(r"^\s*\|\s*(\d{1,9})\s*\|[^|\n]*\|\s*[A-Za-z]", re.M)  # a row: its number, its name, and a status in words


def resolve_kind(plan, words):
    """The kind a person meant: its name or short name in any case, or a prefix only one kind has."""
    wanted = " ".join(words.split()).lower()
    for kind in plan.kinds:
        if wanted in (kind.name.lower(), kind.short.lower()):
            return kind
    found = [k for k in plan.kinds if k.name.lower().startswith(wanted) or k.short.lower().startswith(wanted)]
    if len(found) == 1:
        return found[0]
    raise Refused(f"{words!r} is not one kind. The kinds are: " + " · ".join(plan.kind_names))


def _clean(words):
    return " ".join(str(words).split()).replace("|", "\\|")


def _loaded(plan):
    text, newline = read_keeping_newlines(plan.doc)
    table = tables.parse(text, plan.kinds)
    problems = plan.problems(table)
    if problems:
        raise PlanError("the status table and the plan disagree:\n  " + "\n  ".join(problems))
    return text, newline, table


def _domain(table, wanted):
    if wanted is None:
        if not table.domains:
            raise Refused("the table has no domain yet; give one with --new-domain")
        return table.domains[-1]
    for domain in table.domains:
        if str(domain.n) == str(wanted) or domain.name.lower() == str(wanted).lower():
            return domain
    raise Refused(f"no domain is {wanted!r}. The domains are: " + ", ".join(f"{d.n}. {d.name}" for d in table.domains))


def _with_count(line, domain, count):
    return tables.HEADER.sub(lambda _: f"### {domain.n}. {domain.name} ({count})", line, count=1)


def _highest_ever(plan):
    """The highest row number the table's history has held. A row's number is its identity, in the history and in commit messages, so a removed one is not given out again."""
    try:
        top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
        if top.code:
            return 0
        rel = os.path.relpath(os.path.realpath(plan.doc), os.path.realpath(top.out.strip())).replace(os.sep, "/")
        commits = history.table_commits(top.out.strip(), rel, first_parent=True)
    except PlanError:
        return 0
    highest = 0
    for text in gitio.blobs(top.out.strip(), [f"{sha}:{path}" for sha, _, path in commits]):
        for number in OLD_ROW_NUMBER.findall(text or ""):
            highest = max(highest, int(number))
    return highest


def add(plan, name, domain=None, kind=None, note="", new_domain=None):
    """Add one row at the end of a domain. Returns the row's number. It keeps the header's count and the view true."""
    name = _clean(name)
    if not name:
        raise Refused("a row needs a name")
    chosen = resolve_kind(plan, kind) if kind else plan.kinds[-1]
    if chosen.name == plan.strict_kind.name:
        raise Refused(f"a row reaches {chosen.name} on evidence: add it, then run `gitdone shipped`")
    if chosen.evidence == "branch":
        raise Refused(f"a {chosen.name} row needs a branch that exists: add it, then run `gitdone mark <row> {chosen.short.lower()} --branch NAME`")
    note = _clean(note)
    if chosen.evidence == "note" and not note:
        raise Refused(f"a {chosen.name} row needs a note saying what exists")
    text, newline, table = _loaded(plan)
    same = [r.num for r in table.rows.values() if r.name.lower() == name.lower()]
    if same:
        raise Refused(f"row {same[0]} already has that name")
    number = max(max(table.rows, default=0), _highest_ever(plan)) + 1
    row_line = f"| {number} | {name} | {chosen.name} | {note} |"
    lines = text.split("\n")
    if new_domain:
        n = max((d.n for d in table.domains), default=0) + 1
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"### {n}. {_clean(new_domain)} (1)", "", *TABLE_HEAD, row_line, ""]
    else:
        target = _domain(table, domain)
        if not target.rows:
            lines[target.line] = _with_count(lines[target.line], target, 1)
            lines[target.line + 1:target.line + 1] = ["", *TABLE_HEAD, row_line]
        elif target.rows[-1].prose:
            raise Refused(f"domain {target.n} ({target.name}) is prose; give it a table of rows first")
        else:
            lines[target.rows[-1].line + 1:target.rows[-1].line + 1] = [row_line]
            lines[target.line] = _with_count(lines[target.line], target, target.count + 1)
    if number not in tables.parse("\n".join(lines), plan.kinds).rows:
        raise Refused(f"{plan.doc.name} would not read the new row where it goes; look at what comes before it")
    save(plan, text, "\n".join(lines), newline)
    return number


def remove(plan, row_number):
    """Take one row out of the scope, keeping the counts and the view true. Returns one line saying what happened."""
    text, newline, table = _loaded(plan)
    row = table.rows.get(row_number)
    if row is None:
        raise Refused(f"row {row_number} is not in {plan.doc.name}")
    if row.prose:
        raise Refused(f"row {row_number} sits in a prose domain; give that domain a table of rows first")
    domain = next(d for d in table.domains if row in d.rows)
    lines = text.split("\n")
    lines[domain.line] = _with_count(lines[domain.line], domain, domain.count - 1)
    if len(domain.rows) == 1:  # a table with no rows left would read as a table nothing could be read from
        start = row.line
        while start > domain.line + 1 and lines[start - 1].lstrip().startswith("|"):
            start -= 1
        del lines[start:row.line + 1]
    else:
        del lines[row.line]
    save(plan, text, "\n".join(lines), newline)
    return f"row {row_number} ({row.name}) is out of the scope; `week` will say so"


def link(plan, row_number, ident):
    """Put a requirement's id in a row's note, where a later move keeps it. The status does not change, so this works on a row of any kind."""
    if not ID_WORD.fullmatch(ident):
        raise Refused(f"{ident!r} is not a requirement's id; one looks like REQ-12")
    text, newline, table = _loaded(plan)
    row = table.rows.get(row_number)
    if row is None:
        raise Refused(f"row {row_number} is not in {plan.doc.name}")
    if row.prose:
        raise Refused(f"row {row_number} sits in a prose domain; give that domain a table of rows first")
    if re.search(rf"(?<![A-Za-z0-9-]){re.escape(ident)}(?![0-9A-Za-z-])", f"{row.name} {row.note}"):
        return f"row {row_number} already names {ident}; nothing changed"
    note = f"{ident}. {row.note}".strip() if row.note.strip() else ident
    lines = text.split("\n")
    lines[row.line] = f"| {row.num} | {row.name} | {row.status} | {note} |"
    save(plan, text, "\n".join(lines), newline)
    return f"row {row_number} answers to {ident}"


def _branch_words(plan, words, branch, offline):
    """The note's words, with the branch this kind asks for named and checked."""
    names = [branch] if branch else evidence.NOTE_BRANCH.findall(words)
    if not names:
        raise Refused("this kind needs a branch that exists: pass --branch NAME")
    verifier = evidence.Verifier(plan, offline=offline)
    problem = verifier.problem()
    if problem:
        raise PlanError(problem)
    said = []
    for name in names:
        result, _ = verifier.branch_named(name)
        if result.state == evidence.CONTRADICTED:
            raise Refused(result.detail)
        if result.state == evidence.UNPROVEN:  # true here, and not yet where anyone else looks. The row says so; the gate holds it to that.
            said.append(result.detail)
    return (f"branch `{branch}`" + (f", {words}" if words else "") if branch else words), said


def mark(plan, row_number, kind_words, words="", branch=None, offline=False, today=None):
    """Move one row to any kind but the strict one. Returns one line saying what happened."""
    kind = resolve_kind(plan, kind_words)
    if kind.name == plan.strict_kind.name:
        raise Refused(f"{kind.name} needs evidence: run `gitdone shipped {row_number} <commit or PR>`")
    text, newline, table = _loaded(plan)
    row = table.rows.get(row_number)
    if row is None:
        raise Refused(f"row {row_number} is not in {plan.doc.name}")
    if row.prose:
        raise Refused(f"row {row_number} sits in a prose domain; give that domain a table of rows first")
    words = _clean(words)
    said = []
    if kind.evidence == "branch":
        words, said = _branch_words(plan, words, branch, offline)
    elif kind.evidence == "note" and not (words or row.note.strip()):
        raise Refused(f"a {kind.name} row needs a note saying what exists")
    if row.kind == kind.name and not words:
        return f"row {row_number} is already {kind.name}; nothing changed"
    today = today or datetime.date.today().isoformat()
    was = "" if row.kind == kind.name else f"; was {row.status}"
    addition = f"*({kind.name} {today}: {words}{was})*" if words else f"*({kind.name} {today}{was})*"
    kept = row.note if row.kind == kind.name and not branch else fold_note(plan, row.note)
    note = f"{kept} {addition}" if kept else addition
    status = row.status if row.kind == kind.name else kind.name
    lines = text.split("\n")
    lines[row.line] = f"| {row.num} | {row.name} | {status} | {note} |"
    save(plan, text, "\n".join(lines), newline)
    return "\n".join([f"row {row_number}: {row.kind} → {kind.name}", *said])
