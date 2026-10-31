"""`shipped`: move one row to the strict kind, because a release says so, and regenerate the view.

It takes the evidence as given, checks what can be checked, and refuses what names no release or anything git and gh
disprove. It reads no code: the status is a person's claim, and the engine only holds it to its evidence.
"""
import datetime
import os
import re
import tempfile

from . import evidence, gitio, render, table as tables
from .plan import PlanError, read_file


class Refused(Exception):
    """The row was not moved; the message says why."""


def read_keeping_newlines(path):
    """(text with \\n line ends, the line end the file uses), so a rewrite does not turn a CRLF file into a whole-file diff."""
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            raw = handle.read()
    except OSError as err:
        raise PlanError(f"cannot read {path}: {err.strerror}")
    except UnicodeDecodeError:
        raise PlanError(f"{path} is not UTF-8")
    every_line_crlf = "\r\n" in raw and raw.count("\r\n") == raw.count("\n")
    return raw.replace("\r\n", "\n").lstrip("\ufeff"), ("\r\n" if every_line_crlf else "\n")  # a byte-order mark is not part of a heading


def write_atomically(path, text, newline="\n"):
    """Replace a file in one step, keeping its mode: a session reading it never sees half a table."""
    if path.exists():
        mode = os.stat(path).st_mode & 0o7777
    else:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write(text.replace("\n", newline))
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise


def fold_note(plan, note):
    """A note without the line the engine added at the last move. People's words stay, and git keeps the history."""
    kinds = "|".join(re.escape(name) for name in plan.kind_names)
    return re.sub(rf"[ \t]{{0,8}}\*\((?:{kinds})(?: \d{{4}}-\d{{2}}-\d{{2}}|:)[^*]*\)\*", "", note).strip()


def _check_evidence(plan, words, offline, allow_unverified=False):
    """Everything the evidence names must hold: this is a person writing it now, so a side remark has no excuse."""
    claims = evidence.release_claims(plan, words)
    if not claims:
        raise Refused("the evidence names no release. Give a commit id, a pull request (PR #12), a merge request (MR !12), a tag (tag v1.2.0)"
                      + (" or a match of the plan's evidence pattern." if plan.evidence_pattern else "."))
    verifier = evidence.Verifier(plan, offline=offline)
    problem = verifier.problem()
    if problem:
        raise PlanError(problem)
    results = [verifier.claim(c) for c in claims]
    for result in results:
        if result.state in (evidence.ABSENT, evidence.CONTRADICTED) or (result.state == evidence.UNPROVEN and not result.unanswerable):
            raise Refused(result.detail)
    if not allow_unverified:
        for result in results:
            if result.state == evidence.UNVERIFIED or result.unanswerable:
                raise Refused(f"{result.detail}, and nothing here can check it. Name the commit instead, or pass --allow-unverified")
    best = evidence.best(results)
    if best.state == evidence.VERIFIED and any(r.state == evidence.UNVERIFIED or r.unanswerable for r in results):
        return evidence.Result(evidence.UNVERIFIED, best.detail)  # the note says so whenever any part of it went in on a person's word
    return best


def _already_named(note, words):
    return re.search(r"(?<![\w#])" + re.escape(words) + r"(?!\w)", note) is not None


def ship(plan, row_number, words, offline=False, today=None, allow_unverified=False):
    """Returns one line saying what happened. Raises Refused with the table untouched."""
    words = " ".join(words.split()) if words else ""
    if not words:
        raise Refused("no evidence given. Usage: shipped <row> <evidence>")
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", words):
        words = f"`{words.lower()}`"
    words = words.replace("|", "\\|")
    text, newline = read_keeping_newlines(plan.doc)
    table = tables.parse(text, plan.kinds)
    problems = plan.problems(table)
    if problems:
        raise PlanError("the status table and the plan disagree:\n  " + "\n  ".join(problems))
    row = table.rows.get(row_number)
    if row is None:
        raise Refused(f"row {row_number} is not in {plan.doc.name}")
    if row.prose:
        raise Refused(f"row {row_number} sits in a prose domain; give that domain a table of rows first")
    result = _check_evidence(plan, words, offline, allow_unverified)
    top = plan.strict_kind.name
    if row.kind == top and _already_named(row.note, words):
        return f"row {row_number} is already {top} and its note already names {words}; nothing changed"
    today = today or datetime.date.today().isoformat()
    kept = row.note
    trace = "" if result.state == evidence.VERIFIED else ", unverified"  # the person said so, and git did not: the row keeps that apart
    if row.kind == top:
        status, addition = row.status, f"*({top} {today}: {words}{trace})*"
        verifier = evidence.Verifier(plan, offline=offline)  # a claim the engine added, and which has since stopped holding, goes
        if any(verifier.claim(c).state in (evidence.ABSENT, evidence.CONTRADICTED) for c in evidence.release_claims(plan, row.note)):
            kept = fold_note(plan, row.note)
    else:
        status, addition = top, f"*({top} {today}: {words}{trace}; was {row.status})*"
        kept = fold_note(plan, row.note)
    note = f"{kept} {addition}" if kept else addition
    lines = text.split("\n")
    lines[row.line] = f"| {row.num} | {row.name} | {status} | {note} |"
    save(plan, text, "\n".join(lines), newline)
    if row.kind == top:
        return f"row {row_number} was already {top}; evidence added ({result.state}: {result.detail})"
    return f"row {row_number}: {row.kind} → {top} ({result.state}: {result.detail})"


def save(plan, old_text, new_text, newline="\n"):
    """Write a changed table and its regenerated view, or neither."""
    fresh = tables.parse(new_text, plan.kinds)
    problems = plan.problems(fresh)
    if problems:
        raise PlanError("the move would break the table:\n  " + "\n  ".join(problems))
    moved = render.splice_counts(new_text, render.counts_table(plan, fresh))
    view = render.status_md(plan, fresh)
    plan.check_writable(*plan.tracked)
    _only_replace_what_is_ours(plan)
    current, _ = read_keeping_newlines(plan.doc)
    if current != old_text:  # `shipped` may have waited on gh, and somebody's `mark` may have landed meanwhile
        raise Refused(f"{plan.doc.name} changed while this was being checked; run it again")
    try:
        old_view = read_file(plan.out)
    except (OSError, UnicodeDecodeError):
        old_view = None
    write_atomically(plan.doc, moved, newline)
    try:
        write_atomically(plan.out, view)
        write_badge(plan, fresh)
    except OSError as err:  # files cannot change as one: never leave a moved table with no view to match
        write_atomically(plan.doc, old_text, newline)
        if old_view is not None:
            try:
                write_atomically(plan.out, old_view)
            except OSError:
                pass  # the file that failed may be the view itself, and then it never changed
        raise PlanError(f"cannot write {err.filename or plan.out}: {err.strerror}; the table was put back")


def _only_replace_what_is_ours(plan):
    """A view replaces a view, and git can bring back what it holds as it stands. Anything else, such as an ignored `.env` a plan names or a file
    with uncommitted work in it, is left alone.
    """
    for path, ours in ((plan.out, render.is_a_view), (plan.badge, lambda text: text.startswith("<svg"))):
        if path is None or not path.exists():
            continue
        try:
            if ours(read_file(path)):
                continue
        except (OSError, UnicodeDecodeError):
            pass
        rel = os.path.relpath(path, plan.dir)
        held = gitio.git(plan.dir, "ls-files", "-s", "--", rel).out.split()
        if len(held) < 2 or held[1] != gitio.git(plan.dir, "hash-object", "--", rel).out.strip():
            raise PlanError(f"{rel} exists, is not one of this tool's files, and git does not hold it as it stands, so nothing could bring it back; refusing to overwrite it")


def write_view(plan, table):
    """The view and its badge, for `render --write`."""
    plan.check_writable(*plan.tracked)
    _only_replace_what_is_ours(plan)
    write_atomically(plan.out, render.status_md(plan, table))
    write_badge(plan, table)


def write_badge(plan, table):
    """A plan that names a badge gets it written with the view: the two are one pure function of the plan and the table."""
    if plan.badge:
        from . import badge
        plan.check_writable(plan.badge)
        plan.badge.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(plan.badge, badge.svg(plan, table))
