"""What a plan's requirement files ask for, and which of it has a row. A row nobody asked for and a requirement nobody tracked both make the
percent say less than it seems to, so both are said. Read from Markdown: `REQ-12: words` in a list, a heading or a table, or a checklist item.
"""
import os
import re
import shlex

from . import evidence, focus, render
from .plan import symlink_in

MOST_ITEMS = 10000
MOST_FILES = 50
LONGEST_LINE = 2000  # a requirement is a sentence. A longer line is not one, and nothing below should have to read it
CHECK_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+\[( |x|X)\]\s+(.*\S)\s*$")
ID = r"[A-Z][A-Z0-9]{0,19}-\d{1,9}(?:\.\d{1,9})*"
ITEM_ID = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,9}[.)]\s+(?:\[[ xX]\]\s+)?)?(\*\*|__|`)?"
                     rf"({ID})(?![A-Za-z0-9-])([:.]?)(\*\*|__|`)?\s*(:|\.|-|–|—)?\s*(.*)$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
ID_IN_TEXT = re.compile(rf"(?<![A-Za-z0-9-]){ID}(?![0-9A-Za-z-])")
NOT_REQUIREMENTS = frozenset("UTF ISO SHA MD RFC PEP HTTP IPV TLS SSL AES GPL CVE ASCII COVID TCP UDP WCAG SOC GPT IEEE ECMA PCI LLAMA".split())


class Item:
    def __init__(self, ident, words, source, line):
        self.ident, self.words, self.source, self.line = ident, words, source, line
        self.near = None
        self.is_section = False

    def where(self):
        return f"{self.source}:{self.line}"

    def label(self):
        return f"{self.ident} {self.words}".strip() if self.ident else self.words


def _clean_words(text):
    """What follows an id, with the marks around it taken off."""
    return render.one_line(text.replace("\\|", "|")).strip("*_`").strip()


def _table_item(line, index, source):
    """A row of a table: the first cell that starts with an id, in whichever column the table keeps them, with the words after it or else the next cell's."""
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)]
    for at, cell in enumerate(cells):
        found = ITEM_ID.match(cell)
        if found and not found.group(1) and found.group(3).split("-")[0] not in NOT_REQUIREMENTS:
            words = found.group(7) or next((c for c in cells[at + 1:] if c), "")
            return Item(found.group(3), _clean_words(words), source, index + 1)
    return None


def _item(line, index, source):
    if line.lstrip().startswith("|"):
        return _table_item(line, index, source)
    found = ITEM_ID.match(line)
    if found and found.group(3).split("-")[0] not in NOT_REQUIREMENTS:
        mark, wrapped, inner, outer = found.group(1) or "", found.group(2) and found.group(5), found.group(4), found.group(6)
        if mark.startswith("#") or "[" in mark:
            says_so = True  # a heading or a checklist item with an id is an id because of where it stands
        elif mark:
            says_so = bool(inner or outer or wrapped)  # in a list, `- IEEE-754 doubles everywhere` is a sentence
        else:
            says_so = inner == ":" or outer == ":" or bool(wrapped and (inner or outer))  # on a line of its own, its colon, or its mark with its stop: a sentence can start with `SOC-2.`, `GPT-4 -` or **BUG-12**
        if says_so:
            return Item(found.group(3), _clean_words(found.group(7)), source, index + 1)
    item = CHECK_ITEM.match(line)
    return Item(None, render.one_line(item.group(2)), source, index + 1) if item else None


def lines_to_read(text, problems=None):
    """(index, line) for what a reader of a Markdown file takes as its words: no code fence at any depth, and no HTML comment, however it opens."""
    fence, fence_line, in_comment, comment_line = None, 0, False, 0
    for index, line in enumerate(text.lstrip("\ufeff").replace("\r\n", "\n").split("\n")):
        if fence:
            closing = FENCE.match(line)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence) and not line.strip()[len(closing.group(1)):].strip():
                fence = None
            continue
        shown, at = [], 0
        while at < len(line):
            if in_comment:
                end = line.find("-->", at)
                if end < 0:
                    break
                at, in_comment = end + 3, False
            else:
                begin = line.find("<!--", at)
                if begin < 0:
                    shown.append(line[at:])
                    break
                shown.append(line[at:begin])
                at, in_comment, comment_line = begin + 4, True, index
        visible = "".join(shown)
        opening = FENCE.match(visible)
        if opening:
            fence, fence_line = opening.group(1), index
            continue
        if visible.strip():
            yield index, visible
    if problems is not None:
        if fence:
            problems.append(f"line {fence_line + 1} opens a code fence that never closes, so nothing after it is read")
        if in_comment:
            problems.append(f"line {comment_line + 1} opens an HTML comment that never closes, so nothing after it is read")


def parse(text, source, problems=None):
    """The requirements in one Markdown file, as a reader of it would see them: an item nested in a list counts, and code indented under one does not. A heading with an id
    is a requirement, unless what stands under it is a plain checklist: then it is that list's section.
    """
    trouble, out, in_list, too_long, heading = [], [], False, [], None
    for index, line in lines_to_read(text, trouble):
        if len(line) > LONGEST_LINE:
            too_long.append(index + 1)
            continue
        indented = len(line) - len(line.lstrip()) >= 4 or line.startswith("\t")
        marked = bool(LIST_MARK.match(line))
        if marked and not indented:
            in_list = True
        elif not line[0].isspace():  # a list's words can wrap, and only what starts at the margin ends it
            in_list = False
        if indented and not (marked and in_list):
            continue
        item = _item(line, index, source)
        if HEADING.match(line):
            heading = item
        elif item and heading:
            heading.is_section, heading = not item.ident, None
        if item:
            out.append(item)
    if problems is not None:
        problems.extend(f"requirements: {source}: {words}" for words in trouble)
        if too_long:
            problems.append(f"requirements: {source}: line {too_long[0]} is over {LONGEST_LINE} characters, so it was not read" + (f", and {len(too_long) - 1} more" if len(too_long) > 1 else ""))
    return [item for item in out if not item.is_section]


def read(plan):
    """(items, problems). A plan can come from a clone, and these words can reach a pull request's comment, so only files of this project are read."""
    items, problems, seen = [], [], set()
    root = plan.root()
    for name in plan.requirements[:MOST_FILES]:
        said = render.one_line(name)
        try:
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


def _said(words):
    """The words themselves, in their order, with capitals and punctuation aside. `Add SMS login` and `Remove SMS login`, or `step 1` and `step 2`, are two requirements, whatever else they share.
    The commit a checklist item names is what it says of itself, not what it asks for.
    """
    return " ".join(re.findall(r"\w+", evidence.NAMED_EVIDENCE.sub("", words).lower()))


class _Rows:
    """The rows, indexed once, so that a long spec against a long table costs what the two of them hold, and not their product."""

    def __init__(self, rows):
        self.by_id, self.by_words, self.by_word, self.words, self.rows = {}, {}, {}, {}, {r.num: r for r in rows}
        for row in rows:
            for ident in set(ID_IN_TEXT.findall(f"{row.name} {row.note}")):
                self.by_id.setdefault(ident, []).append(row)
            ours = focus.words_of(row.name)
            self.words[row.num] = ours
            if _said(row.name):
                self.by_words.setdefault(_said(row.name), []).append(row)
            for word in ours:
                self.by_word.setdefault(word, []).append(row)

    def for_item(self, item):
        """A row holds a requirement if it names its id, or says the same words. Nothing weaker counts, because a guess must not close a gap."""
        if item.ident and item.ident in self.by_id:
            return list(self.by_id[item.ident])
        return list(self.by_words.get(_said(item.words), []))

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
    add = f"gitdone add {shlex.quote(item.label())}"  # all of it: a row closes the gap by having its id or its words
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
