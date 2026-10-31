"""What a plan's requirement files ask for, and which of it has a row. A row nobody asked for and a requirement nobody tracked both make the
percent say less than it seems to, so both are said. Read from Markdown: `REQ-12: words` in a list, a heading or a table, or a checklist item.
"""
import os
import re

from . import focus
from .plan import PlanError, symlink_in
from .table import readable

CHECK_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\[( |x|X)\]\s+(.+?)\s*$")
ITEM_ID = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+(?:\[[ xX]\]\s+)?|\|\s*)?(?:\*\*|__|`)?"
                     r"([A-Z][A-Z0-9]{0,9}-\d{1,9}(?:\.\d{1,9})*)\b(?:\*\*|__|`)?(.*)$")


class Item:
    def __init__(self, ident, words, source, line):
        self.ident, self.words, self.source, self.line = ident, words, source, line

    def where(self):
        return f"{self.source}:{self.line}"

    def label(self):
        return f"{self.ident} {self.words}".strip() if self.ident else self.words


def _clean_words(text, in_a_table):
    """What follows an id: separators off the front, and of a table row only its next cell."""
    if in_a_table:
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", text) if c.strip()]
        text = cells[0] if cells else ""
    return re.sub(r"^[\s:.\-–—*_`]+", "", text.replace("\\|", "|")).strip().rstrip("*_`").strip()


def parse(text, source):
    """The requirements in one Markdown file, as a reader of it would see them: nothing from a code fence or a comment."""
    lines = text.lstrip("﻿").split("\n")
    out = []
    for index, line in readable(lines):
        found = ITEM_ID.match(line)
        if found:
            out.append(Item(found.group(1), _clean_words(found.group(2), line.lstrip().startswith("|")), source, index + 1))
            continue
        item = CHECK_ITEM.match(line)
        if item:
            out.append(Item(None, item.group(2), source, index + 1))
    return out


def read(plan):
    """(items, problems). A plan can come from a clone, and these words can reach a pull request's comment, so only files of this project are read."""
    root = plan.root()
    items, problems, seen = [], [], set()
    for name in plan.requirements:
        path = plan._path(name)
        if not os.path.realpath(path).startswith(root + os.sep):
            problems.append(f"requirements: {name} is outside this project, so it was not read")
            continue
        if symlink_in(plan.dir, os.path.expanduser(name)):
            problems.append(f"requirements: {name} is a symbolic link, or sits behind one, so it was not read")
            continue
        try:
            found = parse(plan.text_of(path, "the requirements file"), name)
        except PlanError as err:
            problems.append(str(err))
            continue
        if not found:
            problems.append(f"requirements: {name} names no requirement. Use `REQ-1: words`, or a checklist item")
        for item in found:
            key = item.ident or " ".join(item.words.lower().split())
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items, problems


def _names_id(ident, row):
    return re.search(rf"(?<![A-Za-z0-9-]){re.escape(ident)}(?![0-9A-Za-z-]|\.\d)", f"{row.name} {row.note}") is not None


def _same_work(words, row):
    """Words without an id against a row's name: the same words, or nearly all of the shorter one's."""
    theirs, ours = focus.words_of(words), focus.words_of(row.name)
    if not theirs or not ours:
        return " ".join(words.lower().split()) == " ".join(row.name.lower().split())
    shared = len(theirs & ours)
    return theirs == ours or (shared >= 2 and shared / min(len(theirs), len(ours)) >= 0.75)


def rows_for(item, rows):
    if item.ident:
        return [r for r in rows if _names_id(item.ident, r)]
    return [r for r in rows if _same_work(item.words, r)]


def coverage(plan, table):
    """{items: [(item, rows)], without: [items], unasked: [rows], problems}. Empty when the plan names no requirement file."""
    items, problems = read(plan)
    rows = [r for d in table.domains for r in d.rows if not r.prose]
    pairs = [(item, rows_for(item, rows)) for item in items]
    answered = {r.num for _, mine in pairs for r in mine}
    return {"items": pairs, "without": [item for item, mine in pairs if not mine],
            "unasked": [r for r in rows if r.num not in answered] if items else [], "problems": problems}


def opener_line(plan, table):
    """One line when the scope has moved past the table; None otherwise, and when the plan names no requirement file."""
    if not plan.requirements:
        return None
    found = coverage(plan, table)
    count = len(found["without"])
    if not count:
        return None
    first = found["without"][0]
    return f"⚠ {count} requirement{'' if count == 1 else 's'} {'has' if count == 1 else 'have'} no row, so the percent and the date leave {'it' if count == 1 else 'them'} out: {first.label()[:60]} ({first.where()})"
