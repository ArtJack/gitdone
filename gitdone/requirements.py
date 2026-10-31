"""What a plan's requirement files ask for, and which of it has a row. A row nobody asked for and a requirement nobody tracked both make the
percent say less than it seems to, so both are said. Read from Markdown: `REQ-12: words` in a list, a heading or a table, or a checklist item.
"""
import os
import re
import shlex

from . import focus, render
from .plan import symlink_in
from .table import readable

MOST_ITEMS = 10000
LONGEST_LINE = 2000  # a requirement is a sentence. A longer line is not one, and nothing below should have to read it
CHECK_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+\[( |x|X)\]\s+(.*\S)\s*$")
ID = r"[A-Z][A-Z0-9]{0,9}-\d{1,9}(?:\.\d{1,9})*"
ITEM_ID = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,9}[.)]\s+(?:\[[ xX]\]\s+)?|\|\s*)?(?:\*\*|__|`)?"
                     rf"({ID})(?![A-Za-z0-9-])([:.]?)(?:\*\*|__|`)?\s*([:.\-–—]?)\s*(.*)$")
ID_IN_TEXT = re.compile(rf"(?<![A-Za-z0-9-]){ID}(?![0-9A-Za-z-])")
NOT_REQUIREMENTS = frozenset("UTF ISO SHA MD RFC PEP HTTP IPV TLS SSL AES GPL CVE ASCII COVID TCP UDP WCAG".split())


class Item:
    def __init__(self, ident, words, source, line):
        self.ident, self.words, self.source, self.line = ident, words, source, line
        self.near = None

    def where(self):
        return f"{self.source}:{self.line}"

    def label(self):
        return f"{self.ident} {self.words}".strip() if self.ident else self.words


def _clean_words(text, in_a_table):
    """What follows an id: of a table row only its next cell, with the marks around it taken off."""
    if in_a_table:
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", text) if c.strip()]
        text = cells[0] if cells else ""
    return render.one_line(text.replace("\\|", "|")).strip("*_`").strip()


def _item(line, index, source):
    if len(line) > LONGEST_LINE:
        return None
    found = ITEM_ID.match(line)
    if found and found.group(2).split("-")[0] not in NOT_REQUIREMENTS:
        # With a list mark, a heading or a table cell in front, the id stands for itself. On a line of its own it needs its separator, or a sentence wrapped to start with an id would count.
        if found.group(1) or found.group(3) or found.group(4):
            return Item(found.group(2), _clean_words(found.group(5), line.lstrip().startswith("|")), source, index + 1)
    item = CHECK_ITEM.match(line)
    return Item(None, render.one_line(item.group(2)), source, index + 1) if item else None


def parse(text, source, problems=None):
    """The requirements in one Markdown file, as a reader of it would see them: a nested item counts, and nothing in a code fence or a comment does."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    trouble, nested = [], []
    seen = list(readable(lines, trouble, nested))
    out = []
    for index, line in sorted(seen + [(index, lines[index]) for index in nested]):
        item = _item(line, index, source)
        if item:
            out.append(item)
    if problems is not None:
        problems.extend(f"requirements: {source}: {words}" for words in trouble)
    return out


def read(plan):
    """(items, problems). A plan can come from a clone, and these words can reach a pull request's comment, so only files of this project are read."""
    items, problems, seen = [], [], set()
    for name in plan.requirements:
        said = render.one_line(name)
        try:
            root = plan.root()
            path = plan._path(name)
            if not os.path.realpath(path).startswith(root + os.sep):
                problems.append(f"requirements: {said} is outside this project, so it was not read")
                continue
            if symlink_in(plan.dir, os.path.expanduser(name)):
                problems.append(f"requirements: {said} is a symbolic link, or sits behind one, so it was not read")
                continue
            found = parse(plan.text_of(path, "the requirements file"), said, problems)
        except Exception as err:  # a name no system can open, or a file that cannot be read: said, and nothing stops
            problems.append(render.one_line(f"requirements: {said} could not be read: {err}"))
            continue
        if not found:
            problems.append(f"requirements: {said} names no requirement. Use `REQ-1: words`, or a checklist item")
        for item in found:
            key = item.ident or " ".join(item.words.lower().split())
            if key not in seen:
                seen.add(key)
                items.append(item)
    if len(items) > MOST_ITEMS:
        problems.append(f"requirements: {len(items)} of them, and only the first {MOST_ITEMS} were read")
        del items[MOST_ITEMS:]
    return items, problems


class _Rows:
    """The rows, indexed once, so that a long spec against a long table costs what the two of them hold, and not their product."""

    def __init__(self, rows):
        self.by_id, self.by_words, self.by_word, self.words, self.rows = {}, {}, {}, {}, {r.num: r for r in rows}
        for row in rows:
            for ident in set(ID_IN_TEXT.findall(f"{row.name} {row.note}")):
                self.by_id.setdefault(ident, []).append(row)
            ours = focus.words_of(row.name)
            self.words[row.num] = ours
            self.by_words.setdefault(frozenset(ours) or " ".join(row.name.lower().split()), []).append(row)
            for word in ours:
                self.by_word.setdefault(word, []).append(row)

    def for_item(self, item):
        """A row holds a requirement if it names its id, or says the same words. Nothing weaker counts, because a guess must not close a gap."""
        if item.ident and item.ident in self.by_id:
            return list(self.by_id[item.ident])
        return list(self.by_words.get(frozenset(focus.words_of(item.words)) or " ".join(item.words.lower().split()), []))

    def looks_like(self, item):
        """The row that shares the most of a requirement's words, for the suggestion only. Two words, or the only one."""
        theirs = focus.words_of(item.words)
        best, most = None, 0
        for word in sorted((w for w in theirs if w in self.by_word), key=lambda w: (len(self.by_word[w]), w))[:3]:
            for row in self.by_word[word][:200]:
                shared = len(theirs & self.words[row.num])
                if shared > most or (shared == most and best is not None and row.num < best.num):
                    best, most = row, shared
        return best if best is not None and (most >= 2 or len(theirs) == 1) else None


def coverage(plan, table):
    """{items: [(item, rows)], without: [items], unasked: [rows], problems}. Empty when the plan names no requirement file. An item with no row has `near`, the row it looks like."""
    items, problems = read(plan)
    rows = [r for d in table.domains for r in d.rows if not r.prose]
    index = _Rows(rows)
    pairs = [(item, index.for_item(item)) for item in items]
    answered = {r.num for _, mine in pairs for r in mine}
    for item, mine in pairs:
        item.near = index.looks_like(item) if not mine else None
    return {"items": pairs, "without": [item for item, mine in pairs if not mine],
            "unasked": [r for r in rows if r.num not in answered] if items else [], "problems": problems}


def what_to_do(item):
    """The next step for a requirement with no row. The words come from a file a clone can hold, so what is printed cannot run anything if pasted."""
    add = f"gitdone add {shlex.quote(item.label()[:60])}"
    near = getattr(item, "near", None)
    if near is not None and item.ident:
        return f"row {near.num} looks like it: gitdone link {near.num} {item.ident}. If it is not: {add}"
    if near is not None:
        return f"row {near.num} looks like it: give the two the same words. If it is not: {add}"
    return f"{add}, or if a row holds it: gitdone link <row> {item.ident}" if item.ident else add


def opener_line(plan, table):
    """One line when the scope has moved past the table; None otherwise, and when the plan names no requirement file."""
    if not plan.requirements:
        return None
    found = coverage(plan, table)
    count = len(found["without"])
    if not count:
        return None
    first = found["without"][0]
    return f"⚠ {count} requirement{'' if count == 1 else 's'} {'has' if count == 1 else 'have'} no row, so the percent and the date may leave {'it' if count == 1 else 'them'} out: {first.label()[:60]} ({first.where()})"
