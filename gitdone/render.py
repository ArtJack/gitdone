"""The generated view: STATUS.md, the counts table and the opener line. A pure function of plan and table."""
import datetime
import re

from .plan import PlanError, numbers
from .table import counts, group_rows, readable, score

DATE_LINE = re.compile(r"^(# .* \(generated )\d{4}-\d{2}-\d{2}(\))$")
COUNTS_HEAD = "| # | Domain | All |"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
DEFAULT_WORKSTREAMS_TITLE = "Workstreams, in the plan's order"


def escape_xml(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def bar(p, width=20):
    n = round(p * width)
    if p < 1 and n >= width:  # nearly done must not draw as done
        n = width - 1
    return "█" * n + "░" * (width - n)


def pct(p):
    n = round(p * 100)
    if p < 1 and n >= 100:  # nearly done must not read as done, nor something as nothing
        n = 99
    elif p > 0 and n <= 0:
        n = 1
    return f"{n}%"


def printable(text):
    """Words from a table or a plan, safe to show: an escape sequence must not be able to erase a line and draw its own verdict."""
    return CONTROL.sub(lambda m: f"\\x{ord(m.group(0)):02x}", str(text))


def is_a_view(text):
    """Whether a file's first line is one this tool writes."""
    return bool(DATE_LINE.search(text.partition("\n")[0]))


def normalize(text):
    """The view with its generated date removed: two renders of one state differ in nothing else."""
    first, newline, rest = text.partition("\n")
    return DATE_LINE.sub(r"\1DATE\2", first) + newline + rest


def _capitalized(text):
    return text[:1].upper() + text[1:]


def _divider(columns):
    return "|" + "---|" * columns


def _scale_words(plan):
    if plan.scale:
        return plan.scale
    weights = " · ".join(f"{k.name} {k.weight:g}" for k in plan.kinds)
    return f"*Strict* counts only rows that are {plan.strict_kind.name}. *Weighted* gives: {weights}."


def _group_section(L, plan, table, section):
    groups = plan.effective_groups(table)
    group = plan.group(section["group"]) if section.get("group") else groups[0]
    rows = group_rows(table, group)
    total = group.total if group.total is not None else len(rows)
    tally = counts(rows, plan.kind_names)
    top = tally[plan.strict_kind.name]
    weighted = score(rows, plan.weights)
    L.append(f"## {group.title}: {total} {plan.noun}")
    L.append("")
    if section.get("style", "full") == "summary":
        rest = ", ".join(f"{k.phrase} {tally[k.name]}" for k in plan.kinds[1:] if tally[k.name])
        rest = f" ({rest})" if rest else ""
        L.append(f"- **Strict:** {top} of {total} · **Weighted:** `{bar(weighted)}` {pct(weighted)}{rest}")
        L.append("")
        return
    strict = top / total if total else 0.0
    L.append(f"- **Strict:** {top} of {total} {plan.strict_kind.phrase} · `{bar(strict)}` {pct(strict)}")
    L.append(f"- **Weighted:** `{bar(weighted)}` {pct(weighted)}")
    L.append("- " + _capitalized(" · ".join(f"{k.phrase}: {tally[k.name]}" for k in plan.kinds[1:])))
    L.append("")
    L.append("| Domain | Rows | " + " | ".join(k.short for k in plan.kinds) + " | Strict | Weighted | |")
    L.append(_divider(len(plan.kinds) + 5))
    wanted = set(group.domains)
    for d in table.domains:
        if d.n not in wanted:
            continue
        c = counts(d.rows, plan.kind_names)
        s = score(d.rows, plan.weights)
        cells = " | ".join(str(c[name]) for name in plan.kind_names)
        share = c[plan.strict_kind.name] / d.count if d.count else 0.0
        L.append(f"| {d.n}. {d.name} | {d.count} | {cells} | {pct(share)} | {pct(s)} | `{bar(s, 12)}` |")
    L.append("")


def workstream_rows_numbers(w):
    return numbers(w.get("rows", []), f"workstream {w.get('id')}: rows")


def workstream_rows(w, table):
    return [table.rows[n] for n in workstream_rows_numbers(w)]


def _unfinished(plan, table):
    """The workstreams not yet fully at the strict kind, in the plan's order."""
    out = []
    for ws_id in plan.order:
        w = plan.workstream(ws_id)
        rows = workstream_rows(w, table)
        if not rows or sum(1 for r in rows if r.kind == plan.strict_kind.name) < len(rows):
            out.append(w)
    return out


def _workstreams_section(L, plan, table, section):
    L.append(f"## {section.get('title', DEFAULT_WORKSTREAMS_TITLE)}")
    L.append("")
    L.append("| # | Workstream | Rows | Strict | Weighted | State | Needs |")
    L.append(_divider(7))
    for i, ws_id in enumerate(plan.order, 1):
        w = plan.workstream(ws_id)
        rows = workstream_rows(w, table)
        top = counts(rows, plan.kind_names)[plan.strict_kind.name]
        s = score(rows, plan.weights)
        numbered = ", ".join(str(r.num) for r in rows)
        L.append(f"| {i} | **{w['id']}** {w.get('name', '')} | {numbered} | {top}/{len(rows)} | "
                 f"{pct(s)} `{bar(s, 10)}` | {w.get('state', '')} | {w.get('needs', '')} |")
    L.append("")
    left = _unfinished(plan, table)
    if left:
        L.append("**Next, in order:** " + " → ".join(w["id"] for w in left) + ".")
    else:
        L.append(f"**Next, in order:** nothing; every workstream is fully {plan.strict_kind.phrase}.")
    L.append("")


def _items(plan, section):
    key = section.get("from")
    items = plan.data.get(key, [])
    if not isinstance(items, list):
        raise PlanError(f"sections: {key!r} is not a list in the plan")
    return items


def _table_section(L, plan, table, section):
    columns = section.get("columns", [])
    L.append(f"## {section['title']}")
    L.append("")
    L.append("| " + " | ".join(c["head"] for c in columns) + " |")
    L.append(_divider(len(columns)))
    for item in _items(plan, section):
        L.append("| " + " | ".join(str(item.get(c["key"], "")) for c in columns) + " |")
    L.append("")


def _list_section(L, plan, table, section):
    L.append(f"## {section['title']}")
    L.append("")
    for item in _items(plan, section):
        try:
            L.append(section["format"].format_map(item))
        except KeyError as err:
            raise PlanError(f"sections: {section['title']}: an item has no key {err}")
    L.append("")


def _measured(plan, rows, measures):
    top = counts(rows, plan.kind_names)[plan.strict_kind.name]
    words = {"strict": f"strict {pct(top / len(rows) if rows else 0.0)}",
             "weighted": f"weighted {pct(score(rows, plan.weights))}"}
    return ", ".join(words[m] for m in measures)


def _product_cells(plan, table, product):
    name = product.get("name", "")
    if "group" in product:
        rows = group_rows(table, plan.group(product["group"]))
    elif "rows" in product:
        rows = [table.rows[n] for n in numbers(product["rows"], f"product {name}: rows")]
    else:
        return name, product.get("state", ""), product.get("measure", "")
    tally = counts(rows, plan.kind_names)
    state = product.get("state") or ", ".join(f"{tally[k.name]} {k.short.lower()}" for k in plan.kinds if tally[k.name])
    return name, state, _measured(plan, rows, product.get("measures", ["strict", "weighted"]))


def _products_section(L, plan, table, section):
    L.append(f"## {section.get('title', 'Products')}")
    L.append("")
    L.append("| " + " | ".join(section.get("heads", ["Product", "State", "Measure"])) + " |")
    L.append(_divider(3))
    for product in plan.data.get(section.get("from", "products"), []):
        L.append("| " + " | ".join(_product_cells(plan, table, product)) + " |")
    L.append("")


def _cell(text):
    return " ".join(str(text).split())


def _rows_section(L, plan, table, section):
    """What is left, then what is done with its evidence: the two questions a reader of the view has."""
    rows = [r for d in table.domains for r in d.rows if not r.prose]
    top = plan.strict_kind.name
    left = [r for r in rows if r.kind != top]
    done = [r for r in rows if r.kind == top]
    if left:
        L += [f"## What is left: {len(left)} of {len(rows)} {plan.noun}", "", "| # | Name | Status | Note |", _divider(4)]
        L += [f"| {r.num} | {_cell(r.name)} | {_cell(r.status)} | {_cell(r.note)} |" for r in left]
        L.append("")
    if done:
        L += [f"## {top}: {len(done)} of {len(rows)} {plan.noun}", "", "| # | Name | Evidence |", _divider(3)]
        L += [f"| {r.num} | {_cell(r.name)} | {_cell(r.note)} |" for r in done]
        L.append("")


_SECTIONS = {
    "group": _group_section,
    "workstreams": _workstreams_section,
    "table": _table_section,
    "list": _list_section,
    "products": _products_section,
    "rows": _rows_section,
}


def status_md(plan, table, today=None):
    today = today or datetime.date.today().isoformat()
    name = plan.path.name
    L = [f"# {' '.join(str(plan.title).split())} (generated {today})", ""]
    head = (f"> Generated by `{plan.generated_by}` from `{plan.doc.name}` and `{name}`. Do not edit by hand: "
            f"change a row's status in the status table, or a workstream in `{name}`, and run `{plan.regenerate}`.")
    if plan.release:
        head += f" Release: {plan.release}."
    L.append(head)
    L.append(">")
    L.append(f"> **Scale.** {_scale_words(plan)}")
    L.append("")
    for section in plan.sections:
        _SECTIONS[section["type"]](L, plan, table, section)
    if plan.footer:
        L += ["---", "", plan.footer]
    return "\n".join(L) + "\n"


def counts_table(plan, table):
    names = plan.kind_names
    last = len(names) - 1
    out = ["| # | Domain | All | " + " | ".join(names) + " |", _divider(len(names) + 3)]
    groups = plan.groups
    closes = {}
    for g in groups:
        members = [d.n for d in table.domains if d.n in set(g.domains)]
        if members:
            closes.setdefault(members[-1], []).append(g)

    def total_row(label, rows):
        c = counts(rows, names)
        cells = " | ".join(f"**{c[k]}**" if c[k] else "" for k in names)
        return f"| | **{label}** | **{len(rows)}** | {cells} |"

    for d in table.domains:
        c = counts(d.rows, names)
        # The first and last columns always show their number; a zero between them stays blank to keep the table readable.
        cells = " | ".join(str(c[k]) if c[k] or i in (0, last) else "" for i, k in enumerate(names))
        out.append(f"| {d.n} | {d.name} | {d.count} | {cells} |")
        for g in closes.get(d.n, []):
            out.append(total_row(g.label, group_rows(table, g)))
    if len(groups) != 1:
        out.append(total_row("All", [r for d in table.domains for r in d.rows]))
    return "\n".join(out)


def embedded_counts(text):
    """[(first line, line after the last)] of each counts table a reader can see in the status table. One in a code fence is an example."""
    lines = text.lstrip("\ufeff").split("\n")
    spans = []
    for start, line in readable(lines):
        if line.startswith(COUNTS_HEAD):
            end = start
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            spans.append((start, end))
    return spans


def splice_counts(text, table_md):
    """The status table's text with its embedded counts tables replaced; unchanged when it has none."""
    lines = text.split("\n")
    for start, end in reversed(embedded_counts(text)):
        lines[start:end] = table_md.split("\n")
    return "\n".join(lines)


def next_workstream(plan, table):
    left = _unfinished(plan, table)
    return left[0] if left else None


def opener_data(plan, table):
    """Strict and weighted per group, and the next workstream in order, as data."""
    groups = []
    for g in plan.effective_groups(table):
        rows = group_rows(table, g)
        top = counts(rows, plan.kind_names)[plan.strict_kind.name]
        groups.append({"label": g.label, "rows": len(rows), "strict_rows": top, "strict": top / len(rows) if rows else 0.0,
                       "weighted": score(rows, plan.weights)})
    w = next_workstream(plan, table) if plan.order else None
    following = {"id": w["id"], "name": w.get("name", ""), "state": w.get("state", ""), "needs": w.get("needs", "")} if w else None
    if not plan.order:  # with no workstreams, the table's own order is the queue
        row = next((r for d in table.domains for r in d.rows if r.kind != plan.strict_kind.name and not r.prose), None)
        following = {"id": f"row {row.num}", "name": row.name, "state": row.kind or "", "needs": ""} if row else None
    return {"groups": groups, "next": following, "all_workstreams_done": bool(plan.order) and w is None}


def opener(plan, table):
    """One line: strict and weighted per group, the next workstream in order, what it needs."""
    data = opener_data(plan, table)
    parts = [f"{g['label']}: strict {pct(g['strict'])} ({g['strict_rows']}/{g['rows']}), weighted {pct(g['weighted'])}" for g in data["groups"]]
    if data["all_workstreams_done"]:
        parts.append(f"every workstream is fully {plan.strict_kind.phrase}")
    elif data["next"]:
        w = data["next"]
        needs = f", needs {w['needs']}" if w["needs"] else ""
        parts.append(f"next: {w['id']} ({w['name']}){needs}")
    return " · ".join(parts)
