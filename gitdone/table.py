"""The status table: the only place a row's status changes.

    ### 3. Domain name (4)

    | # | Name | Status | Note |
    |---|---|---|---|
    | 12 | A row | Live | What exists, and the release that shipped it. |

A domain whose header has a count and no table below it is prose: every row counts as the plan's last kind.
"""
import html
import re

from .plan import PlanError

HEADER = re.compile(r"^### ([0-9]{1,18})\. (.+) \(([0-9]{1,18})\)")
HEADING = re.compile(r"^#{1,6} ")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})")  # a backtick fence's words cannot hold a backtick: that line is inline code
FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
INDENTED = re.compile(r"^(?: {4}| {0,3}\t)")
COMMENT_LINE = re.compile(r"^ {0,3}<!--")
CONFLICT = re.compile(r"^(?:<{7}|>{7}) ")
DOMAIN_SHAPED = re.compile(r"^### +[0-9]+[.:)]?\s")
FORMAT_CHARACTERS = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
HTML_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]{0,300})?/?>")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|[0-9]{1,9}[.)])[ \t]")
REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[([^\]\n]{1,300})\]:[ \t]*<?([^\s>]{1,600})>?")
REFERENCE_USE = re.compile(r"\[([^\[\]\n]{1,300})\](?:\[([^\[\]\n]{0,300})\])?(?!\()")
MAX_PROSE_ROWS = 100000
COUNTS_HEAD = "| # | Domain | All |"
ROW_NUMBER = re.compile(r"^[0-9]{1,18}$")  # past that it is no row, and past 4,300 digits Python's own answer depends on its version


class Row:
    def __init__(self, num, name, status, note, kind, line=None, prose=False):
        self.num = num
        self.name = name
        self.status = status
        self.note = note
        self.kind = kind
        self.line = line
        self.prose = prose
        self.references = {}  # the table's `[name]: url` lines

    def words(self):
        """What the row says, with a reference-style link spelled out, so that its target decides what it is worth."""
        text = f"{self.status} {self.note}"
        if not self.references:
            return text

        def spelled_out(match):
            target = self.references.get(_reference_name(match.group(2) or match.group(1)))
            return f"[{match.group(1)}]({target})" if target else match.group(0)
        return REFERENCE_USE.sub(spelled_out, text)


class Domain:
    def __init__(self, n, name, count, line=None):
        self.n = n
        self.name = name
        self.count = count
        self.line = line
        self.rows = []
        self.other_table_lines = 0


class Table:
    def __init__(self):
        self.domains = []
        self.rows = {}
        self.problems = []
        self.strays = []  # lines that look like rows and are not read as rows
        self.text = ""


def _without_comments(text):
    """Text with its HTML comments gone, in one pass: however many openers it holds, this costs what reading it once does."""
    kept, at = [], 0
    while True:
        opens = text.find("<!--", at)
        closes = text.find("-->", opens + 4) if opens >= 0 else -1
        if closes < 0:
            return "".join(kept) + text[at:]
        kept.append(text[at:opens])
        at = closes + 3


def has_words(text):
    """Whether a reader would see anything here. A zero-width space, a comment, `&nbsp;` and `<br>` are not words."""
    return bool(FORMAT_CHARACTERS.sub("", HTML_TAG.sub("", html.unescape(_without_comments(text)))).strip())


def _reference_name(words):
    return " ".join(words.lower().split())


def _is_divider(line):
    return "-" in line and not line.strip(" \t:|-")


def _is_table_head(lines, index):
    """A table's heading, as Markdown reads one: a divider as wide as itself below it, and no table row above it."""
    if index + 1 >= len(lines) or not _is_divider(lines[index + 1]) or (index and lines[index - 1].lstrip().startswith("|")):
        return False
    return len(split_cells(lines[index])) == len(split_cells(lines[index + 1]))


def _status_words(names):
    """A cell that starts with a kind's name, in any case, whatever comes after it: the way a person writes a status by mistake."""
    return re.compile("(?i)(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?!\w)")


def _row_shaped(cells, status_words):
    """A number first and a status third: outside any domain, the one line a reader would take for a row that went uncounted."""
    return len(cells) >= 3 and bool(ROW_NUMBER.match(cells[0])) and bool(status_words.match(cells[2]))


def match_kind(status, names):
    """The kind a status cell starts with; the longest name wins, and it must end on a word boundary. `Live?` is a doubt, not a status."""
    text = status.strip()
    for name in sorted(names, key=len, reverse=True):
        if text.startswith(name) and (len(text) == len(name) or (not text[len(name)].isalnum() and text[len(name)] != "?")):
            return name
    return None


def split_cells(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in CELL_SPLIT.split(body)]


def readable(lines, problems=None, unsure=None):
    """(index, line) for the lines a reader takes as this file's own: no code fence, no HTML comment, no indented block. A comment opened
    mid-line lasts as long as its paragraph, which is a guess about the renderer, so the lines it would hide go to `unsure`.
    """
    fence, fence_line, comment_line, skip_to, paragraph_end, in_list = None, None, None, -1, -1, False
    for index, line in enumerate(lines):
        if index <= skip_to:
            continue
        if fence is not None:
            closing = FENCE_CLOSE.match(line)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
            continue
        if comment_line is not None:
            if "-->" in line:
                comment_line = None
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence, fence_line = opening.group(1), index
            continue
        if INDENTED.match(line):
            if in_list and unsure is not None:  # code, or a list item's own content, which a renderer draws as a table
                unsure.append(index)
            continue
        if line.strip() and (not line.startswith(" ") or LIST_ITEM.match(line)):  # a line indented to the item does not end the list
            in_list = bool(LIST_ITEM.match(line))
        if COMMENT_LINE.match(line) and "-->" not in line:
            comment_line = index
            continue
        if not line.lstrip().startswith("|") and not HEADING.match(line):  # a row or a heading is one line, and closes what opens in it
            opened = line.rfind("<!--")
            if opened >= 0 and "-->" not in line[opened:]:
                if paragraph_end <= index:  # read once, however many openers share a paragraph
                    paragraph_end = index + 1
                    while paragraph_end < len(lines) and lines[paragraph_end].strip() and "-->" not in lines[paragraph_end]:
                        paragraph_end += 1
                if paragraph_end < len(lines) and "-->" in lines[paragraph_end]:
                    skip_to = paragraph_end
                    if unsure is not None:
                        unsure.extend(range(index + 1, skip_to + 1))
        yield index, line
    if problems is not None:
        if fence is not None:
            problems.append(f"line {fence_line + 1} opens a code fence that never closes, so nothing after it is read")
        if comment_line is not None:
            problems.append(f"line {comment_line + 1} opens an HTML comment that never closes, so nothing after it is read")


def _say_what_is_hidden(lines, unsure, table, in_domain):
    """What a comment opened mid-line would hide, or a list item would hold, is said, whichever way a renderer reads it."""
    for index in unsure:
        cells = split_cells(lines[index].lstrip("> \t")) if "|" in lines[index] else []
        if HEADER.match(lines[index]) or (len(cells) >= 2 and (ROW_NUMBER.match(cells[0]) or (in_domain and not _is_divider(lines[index])))):
            table.strays.append(index)
    del unsure[:]


def _read_status_row(table, current, line, index, cells, names):
    row = Row(int(cells[0]), cells[1], cells[2], " | ".join(cells[3:]), match_kind(cells[2], names), line=index)
    if row.kind is None:
        table.problems.append(f"row {row.num}: unknown status {row.status!r}")
    current.rows.append(row)
    if row.num in table.rows:
        table.problems.append(f"row {row.num} appears twice")
    table.rows[row.num] = row


def parse(text, kinds):
    """Inside a domain, every table line is a row or is said. As in Markdown, under an open table any line with a pipe is a table line, and so is one
    with a divider below it. A table of your own goes under a heading of its own, and outside a domain only a line shaped like a row, a number first
    and a status third, is said.
    """
    names = [k.name for k in kinds]
    table = Table()
    current = None
    if text.startswith("\ufeff"):  # a byte-order mark must not hide a first line
        text = text[1:]
    lines = text.split("\n")
    status_words = _status_words(names)
    unsure, references, conflict_said, open_table, in_counts = [], {}, False, False, False
    for index, line in readable(lines, table.problems, unsure):
        _say_what_is_hidden(lines, [i for i in unsure if i < index], table, current is not None)
        unsure[:] = [i for i in unsure if i >= index]
        if CONFLICT.match(line) and not conflict_said:
            conflict_said = True
            table.problems.insert(0, f"line {index + 1} is a merge conflict marker: resolve the conflict in the table, then run `gitdone render --write`")
        if line.startswith(COUNTS_HEAD):  # a counts table is a summary, wherever it sits, and it ends no domain
            in_counts = True
            continue
        if in_counts and line.startswith("|"):
            continue
        in_counts = False
        header = HEADER.match(line)
        if header:
            current, open_table = Domain(int(header.group(1)), header.group(2), int(header.group(3)), line=index), False
            table.domains.append(current)
            continue
        if HEADING.match(line):
            if has_words(line.strip("# \t")):  # a heading with nothing in it draws nothing, and ends nothing
                if current is not None and DOMAIN_SHAPED.match(line):  # shaped like the next domain, and not read as one: its count is lost or mistyped
                    table.strays.append(index)
                current, open_table = None, False
            continue
        piped = line.lstrip().startswith("|")
        table_line = "|" in line and (piped or open_table or _is_divider(line) or (index + 1 < len(lines) and _is_divider(lines[index + 1])))
        open_table = table_line
        if not table_line:
            definition = REFERENCE_DEFINITION.match(line)
            if definition:
                references[_reference_name(definition.group(1))] = definition.group(2)
                continue
        quoted = line.lstrip("> \t")  # a table in a quote is still a table to a reader
        cells = split_cells(quoted) if "|" in line else []
        if current is None:
            if _row_shaped(cells, status_words):
                table.strays.append(index)
            continue
        if not table_line:
            if quoted.startswith("|") or (len(cells) >= 2 and ROW_NUMBER.match(cells[0])):
                table.strays.append(index)
            continue
        head = _is_table_head(lines, index)
        if head and not ROW_NUMBER.match(cells[0]) and len(cells) >= 3 and cells[2].lower() != "status":
            table.problems.append(f"domain {current.n} ({current.name}): the third column is the status, and its heading says {cells[2]!r}")
        if not piped or len(cells) < 3 or not ROW_NUMBER.match(cells[0]):
            current.other_table_lines += 1
            if not head and not _is_divider(line):
                table.strays.append(index)
            continue
        _read_status_row(table, current, line, index, cells, names)
    _say_what_is_hidden(lines, unsure, table, current is not None)
    for row in table.rows.values():
        row.references = references
    _count_the_domains(table, kinds[-1].name)
    return table


def _count_the_domains(table, last):
    """Each domain against its heading. One with a count and no table is prose, and its rows count as the plan's last kind."""
    next_num = 1
    numbers = [d.n for d in table.domains]
    for repeated in sorted({n for n in numbers if numbers.count(n) > 1}):
        table.problems.append(f"domain {repeated} appears twice")
    prose_rows = 0
    for domain in table.domains:
        if not domain.rows:
            if domain.other_table_lines:  # a table nothing could be read from is not prose
                table.problems.append(f"domain {domain.n} ({domain.name}) has a table, and none of its rows could be read")
            prose_rows += domain.count
            if prose_rows > MAX_PROSE_ROWS:
                table.problems.append(f"domain {domain.n} ({domain.name}) brings the rows counted with no table to {prose_rows}; the most is {MAX_PROSE_ROWS}")
                continue
            for i in range(domain.count):
                row = Row(next_num + i, "", last, "", last, prose=True)
                domain.rows.append(row)
                if row.num in table.rows:  # never let a counted row silently replace a real one, which would then go unjudged
                    table.problems.append(f"row {row.num} is named in a table, and domain {domain.n} ({domain.name}), which has no table, counts it too")
                else:
                    table.rows[row.num] = row
        if len(domain.rows) != domain.count:
            table.problems.append(
                f"domain {domain.n} ({domain.name}) has {len(domain.rows)} rows, its header says {domain.count}; correct the number in its heading, or use `add` and `remove`")
        if domain.rows:
            next_num = domain.rows[-1].num + 1


def load(plan):
    """The status table, whatever its shape; `plan.problems` says whether it can be rendered."""
    text = plan.text_of(plan.doc, "the status table").lstrip("\ufeff")
    table = parse(text, plan.kinds)
    table.text = text
    return table


def load_clean(plan):
    """The table, or a stop: if the shape changed, nothing downstream should guess."""
    table = load(plan)
    problems = plan.problems(table)
    if problems:
        raise PlanError("the status table and the plan disagree:\n  " + "\n  ".join(problems))
    return table


def counts(rows, names):
    tally = {name: 0 for name in names}
    for row in rows:
        if row.kind in tally:
            tally[row.kind] += 1
    return tally


def score(rows, weights):
    return sum(weights.get(r.kind, 0.0) for r in rows) / len(rows) if rows else 0.0


def group_rows(table, group):
    domains = set(group.domains)
    return [row for d in table.domains if d.n in domains for row in d.rows]
