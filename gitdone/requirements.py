"""What a plan's requirement files ask for, and which of it has a row. A row nobody asked for and a requirement nobody tracked both make the
percent say less than it seems to, so both are said. Read from Markdown: `REQ-12: words` in a list, a heading or a table, or a checklist item.
"""
import collections
import os
import re
import shlex
import unicodedata

from . import evidence, focus, render
from .plan import symlink_in

MOST_ITEMS = 10000
MOST_FILES = 50
LONGEST_LINE = 2000  # a requirement is a sentence. A longer line is not one, and nothing below should have to read it
CHECK_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s+\[( |x|X)\]\s+(.*\S)\s*$")
ID = evidence.REQUIREMENT_ID
ITEM_ID = re.compile(r"^\s*(#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d{1,9}[.)]\s+(?:\[[ xX]\]\s+)?)?(\*\*|__|`)?"
                     rf"({ID})(?![A-Za-z0-9-])([:.]?)(\*\*|__|`)?\s*(:|\.|-|–|—)?\s*(.*)$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d{1,9}[.)])\s")
# What a table's heading says of a column, by its last word, as in `Req ID`. An id elsewhere in a table is a ticket, a severity or a standard, or refers to a requirement.
ID_HEADINGS = frozenset("id identifier reqid req requirement story feature ref reference item # no number".split())
WORDS_HEADINGS = ("requirement", "requirements", "title", "description", "summary", "statement", "want", "text", "capability", "story", "feature", "name", "what")  # the first of these that a table has
SAYS_REQUIREMENTS = frozenset("requirement requirements title summary statement want capability story feature".split())  # a table with one of these holds requirements, whatever its first column is called. `Description` does not say so: an error code has one
ASIDE_HEADINGS = frozenset("risk test covers case scenario milestone quarter sprint release version date term severity sev priority pri status owner assignee author bug defect incident result type effort estimate phase".split())
Columns = collections.namedtuple("Columns", "ids words aside says_requirements")
# A section a spec keeps beside its requirements, by the whole of its heading: `### Risk scoring` and `# Risk Dashboard: Requirements` are not one.
ASIDE_SECTION = re.compile(r"(?:\d+(?:\.\d+)*\.?\s+)?(?:open |known |key )?(?:questions?|risks?(?: and mitigations?)?|assumptions?(?: and (?:constraints?|dependencies))?|goals?|objectives?|glossary|revisions?|revision history|"
                           r"change ?log|references?|appendix(?: [\w.-]+)?|out of scope|not in scope|non-?goals?|decisions?)", re.I)
WHY_NOT_READ = {
    "column": "its column does not say it holds ids: head the column `ID`, or write the id with a colon and its words",
    "table": "its table does not say it holds requirements, and the file defines other ids more plainly: head the column `ID`",
    "section": "it stands under a heading that does not hold requirements: move it, if it is one",
    "prose": "it could be a sentence: write the id with a colon",
}
SAID = re.compile(r"\w+|(?<=\w)[+#＋＃]+|(?<!\w)[-+−](?=\d)|!=|[<>=≠≤≥＜＞＝]+|[%％$]")  # the words, and a mark that changes what is asked: `< 10 MB`, `C++`, `-1`. Everything else is punctuation, in any script
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
ID_IN_TEXT = evidence.REQUIREMENT_IN_TEXT
NOT_REQUIREMENTS = evidence.NOT_REQUIREMENTS


class Item:
    def __init__(self, ident, words, source, line):
        self.ident, self.words, self.source, self.line = ident, words, source, line
        self.near = None
        self.is_section = False
        self.weak = False  # its words were a guess at the table's next cell, or it has none, so that a line defining it says more
        self.passed_over = False  # not read as a requirement, and said
        self.why = ""
        self.also = []  # other ids in its cell
        self.needs_kin = None  # read only if its file defines nothing plainer, or defines its kind of id: a table's first column under a heading that does not say so, what is under a section that does not hold requirements, or `- REQ-4 words`, which could be prose (that one not even then, alone)

    def where(self):
        return f"{self.source}:{self.line}"

    def label(self):
        return f"{self.ident} {self.words}".strip() if self.ident else self.words


def _clean_words(text):
    """What follows an id, with the marks around it taken off."""
    return render.one_line(text.replace("\\|", "|")).strip("*_`").strip()


def _cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _columns(heading):
    """What a table's heading says of its columns: those that hold ids, those that hold their words, the best first, and those that hold neither."""
    lasts = [next(filter(None, reversed(re.split(r"[\s_.-]+", cell.strip("*_`: ").lower()))), "") for cell in _cells(heading)]
    return Columns([at for at, last in enumerate(lasts) if last in ID_HEADINGS],
                   sorted((at for at, last in enumerate(lasts) if last in WORDS_HEADINGS), key=lambda at: WORDS_HEADINGS.index(lasts[at])),
                   {at for at, last in enumerate(lasts) if last in ASIDE_HEADINGS},
                   any(last in SAYS_REQUIREMENTS for last in lasts))


def _cell_id(cell):
    """The match of an id at the start of a cell, a link to it read as the id."""
    if cell.startswith("[") and "](" in cell and ")" in cell:
        cell = cell[1:cell.index("](")] + cell[cell.index(")", cell.index("](")) + 1:]
    found = ITEM_ID.match(cell)
    return found if found and not found.group(1) and found.group(3).split("-")[0] not in NOT_REQUIREMENTS else None


def _table_item(line, index, source, columns):
    """A row of a table. Its id is in a column the heading says holds them, or at the start of the first column unless the heading says that holds something else, or in any
    cell with its colon and its words. An id anywhere else is a ticket, a severity or a standard, or refers to a requirement: it is passed over, and `matrix` says so, because
    neither a requirement lost nor one invented should go unseen. Its words follow the id in its cell, or are in a column the heading says holds them. Failing that they are a
    guess at the next cell along or the one before, which anything that defines the id outranks.
    """
    cells = _cells(line)
    ids, words, aside, says_requirements = columns or ((), (), (), False)
    sure = list(ids) + ([1] if 1 not in aside else [])
    passed = None
    for at in sure + [at for at in range(1, len(cells)) if at not in sure]:
        found = _cell_id(cells[at]) if at < len(cells) else None
        if not found:
            continue
        own = found.group(7)
        also = ID_IN_TEXT.findall(own)
        if also and not ID_IN_TEXT.sub("", own).strip(" ,;/&+"):
            own = ""
        else:
            also = []
        if at not in sure and not (own and ":" in (found.group(4), found.group(6))):
            passed = passed or found.group(3)
            continue
        named = next((cells[w] for w in words if w != at and w < len(cells) and cells[w]), "")
        order = list(range(at + 1, len(cells))) + list(range(at - 1, 0, -1))
        near = next((cells[n] for n in order if n not in aside and any(c.isalpha() for c in cells[n]) and not ID_IN_TEXT.fullmatch(cells[n])), "")
        item = Item(found.group(3), _clean_words(own or named or near), source, index + 1)
        item.weak, item.also = not (own or named), also
        if columns and at == 1 and at not in ids and not says_requirements:
            item.needs_kin = "table"
        return item
    if passed:
        item = Item(passed, "", source, index + 1)
        item.passed_over, item.why = True, WHY_NOT_READ["column"]
        return item
    return None


def outranks(item, held):
    """Whether this says more of a requirement than what was read first: words where it had none, or words of its own where those were a guess."""
    return bool(item.words) and (not held.words or (held.weak and not item.weak))


def _item(line, index, source, columns=None):
    if line.lstrip().startswith("|"):
        return _table_item(line, index, source, columns)
    found = ITEM_ID.match(line)
    if found and found.group(3).split("-")[0] not in NOT_REQUIREMENTS:
        mark, wrapped, inner, outer = found.group(1) or "", found.group(2) and found.group(5), found.group(4), found.group(6)
        if mark.startswith("#") or "[" in mark:
            says_so = True  # a heading or a checklist item with an id is an id because of where it stands
        elif mark:
            says_so = bool(inner or outer or wrapped)  # in a list, `- IEEE-754 doubles everywhere` is a sentence
        else:
            says_so = inner == ":" or outer == ":" or bool(wrapped and (inner or outer))  # on a line of its own, its colon, or its mark with its stop: a sentence can start with `SOC-2.`, `GPT-4 -` or **BUG-12**
        if says_so or mark or outer in ("-", "–", "—"):
            item = Item(found.group(3), _clean_words(found.group(7)), source, index + 1)
            if not says_so:
                item.weak, item.needs_kin = True, "prose"
            return item
    item = CHECK_ITEM.match(line)
    if not item:
        return None
    words = render.one_line(item.group(2))
    if is_struck(words):
        return None
    ident, words = _id_at_the_end(words)
    return Item(ident, words, source, index + 1)


def is_struck(words):
    return words.startswith("~~") and words.endswith("~~")


def _id_at_the_end(words):
    """(id, the rest): a to-do item can say which requirement it is: `Sign in (REQ-1)`."""
    if words.endswith(")") and "(" in words:
        inner = words[words.rindex("(") + 1:-1].strip()
        if ID_IN_TEXT.fullmatch(inner) and inner.split("-")[0] not in NOT_REQUIREMENTS:
            return inner, words[:words.rindex("(")].strip()
    return None, words


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


def lines_with_columns(text, problems=None):
    """(index, line, what the heading of the table it stands in says of its columns), for what a reader of the file takes as its words."""
    columns, before = None, ""
    for index, line in lines_to_read(text, problems):
        if "-" in line and "|" in line and "|" in before and not line.strip("|-: \t"):  # the rule under a table's heading
            columns = _columns(before if before.lstrip().startswith("|") else f"| {before}")
        elif "|" not in line:
            columns = None
        elif columns is not None and not line.lstrip().startswith("|"):  # a table may leave off its outer pipes
            line = f"| {line}"
        before = line if len(line) <= LONGEST_LINE else ""
        yield index, line, columns


def parse(text, source, problems=None, passed_over=None):
    """The requirements in one Markdown file, as a reader of it would see them: an item nested in a list counts, and code indented under one does not. A heading with an id
    is a requirement, unless what stands under it is a plain checklist: then it is that list's section.
    """
    trouble, out, in_list, too_long, heading, aside_at = [], [], False, [], None, None
    for index, line, columns in lines_with_columns(text, trouble):
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
        item = _item(line, index, source, columns)
        if HEADING.match(line):
            heading = item
            level = len(line.lstrip()) - len(line.lstrip().lstrip("#"))
            if aside_at is None or level <= aside_at:
                aside_at = level if ASIDE_SECTION.fullmatch(line.strip().lstrip("#").strip("*_:` ")) and not (item and item.ident) else None
        elif item and heading:
            heading.is_section, heading = not item.ident, None
        if item and aside_at is not None and not item.passed_over:
            if item.ident:
                item.needs_kin = "section"
            else:
                item.passed_over, item.why = True, WHY_NOT_READ["section"]
        if item and item.passed_over:
            if passed_over is not None:
                passed_over.append(item)
        elif item:
            out.append(item)
            out.extend(Item(other, item.words, source, index + 1) for other in item.also)
    plain = {item.ident.split("-")[0] for item in out if item.ident and not item.needs_kin and not item.is_section}
    left_out = set()
    for item in out:
        if item.needs_kin and item.ident.split("-")[0] not in plain and (plain or item.needs_kin == "prose"):  # with nothing plainer in the file, a table's first column is its ids
            left_out.add(id(item))
            item.why = WHY_NOT_READ[item.needs_kin]
            if passed_over is not None:
                passed_over.append(item)
    if passed_over is not None:
        passed_over.sort(key=lambda item: item.line)
    out = [item for item in out if id(item) not in left_out]
    if problems is not None:
        problems.extend(f"requirements: {source}: {words}" for words in trouble)
        if too_long:
            problems.append(f"requirements: {source}: line {too_long[0]} is over {LONGEST_LINE} characters, so it was not read" + (f", and {len(too_long) - 1} more" if len(too_long) > 1 else ""))
    return [item for item in out if not item.is_section]


def passed_over_in(text, source):
    passed_over = []
    parse(text, source, None, passed_over)
    return passed_over


def read(plan):
    """(items, problems, ids passed over that nothing else defines). A plan can come from a clone, and these words can reach a pull request's comment, so only files of this project are read."""
    items, problems, seen, passed_over = [], [], {}, []
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
            found = parse(plan.text_of(path, "the requirements file"), said, problems, passed_over)
        except Exception as err:  # a name no system can open, or a file that cannot be read: said, and nothing stops
            problems.append(render.one_line(f"requirements: {said} could not be read: {err}"))
            continue
        if not found:
            problems.append(f"requirements: {said} names no requirement. Use `REQ-1: words`, or a checklist item")
        for item in found:
            key = item.ident or " ".join(item.words.lower().split())
            if key not in seen:
                seen[key] = len(items)
                items.append(item)
            elif outranks(item, items[seen[key]]):
                items[seen[key]] = item
    if len(items) > MOST_ITEMS:
        problems.append(f"requirements: {len(items)} of them, and only the first {MOST_ITEMS} were read")
        del items[MOST_ITEMS:]
    return items, problems, [item for item in passed_over if item.ident not in seen]


def _marks_kept(text):
    """`\\w` leaves out what combines with a letter, and in Indic scripts and Thai that can be the vowel: मेल and माल are two words. Nor does it know a currency."""
    def kept(char):
        kind = unicodedata.category(char)
        return f"_{ord(char):x}_" if kind[0] == "M" else (f" _{ord(char):x}_ " if kind == "Sc" and char != "$" else char)
    return "".join(kept(char) for char in text)


def _said(words):
    """The words themselves, in their order, with capitals and punctuation aside. `Add SMS login` and `Remove SMS login`, `step 1` and `step 2`, are two requirements, whatever else they share.
    The commit a checklist item names is what it says of itself, not what it asks for.
    """
    text = evidence.NAMED_EVIDENCE.sub(lambda named: named.group(0) if named.group(0).strip(" ()`").isdigit() else "", words).lower()  # a commit, and not a number someone asked for
    for arrow in ("->", "=>", "<-"):
        text = text.replace(arrow, " ")
    return " ".join(SAID.findall(text if text.isascii() else _marks_kept(unicodedata.normalize("NFC", text))))


class _Rows:
    """The rows, indexed once, so that a long spec against a long table costs what the two of them hold, and not their product."""

    def __init__(self, rows):
        self.by_id, self.by_words, self.by_word, self.words, self.rows = {}, {}, {}, {}, {r.num: r for r in rows}
        for row in rows:
            for ident in set(evidence.requirements_held(row.name, row.note)):
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
    items, problems, passed_over = read(plan)
    rows = [r for d in table.domains for r in d.rows if not r.prose]
    index = _Rows(rows)
    pairs = [(item, index.for_item(item)) for item in items]
    answered = {r.num for _, mine in pairs for r in mine}
    for item, mine in pairs:
        item.near = index.looks_like(item) if not mine else None
    return {"items": pairs, "without": [item for item, mine in pairs if not mine],
            "unasked": [r for r in rows if r.num not in answered] if items else [], "problems": problems, "passed_over": passed_over}


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
