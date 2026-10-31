"""`badge`: the two numbers as a badge, for a README. A self-contained SVG, or the JSON a shields.io endpoint reads."""
from . import render, table as tables
from .render import escape_xml as escape

BLUE, GREEN = "#2a78d6", "#0a7d33"
NARROW = {"i": 3.0, "l": 3.0, "j": 3.4, ".": 4.0, ",": 4.0, ":": 4.7, ";": 4.7, "'": 3.0, "!": 4.4, "|": 5.0, " ": 3.9, "f": 3.9,
          "t": 4.3, "r": 4.7, "I": 4.6, "-": 5.0, "·": 4.0, "(": 5.0, ")": 5.0, "/": 5.0, "m": 10.7, "w": 9.0, "%": 11.8, "M": 9.5, "W": 10.9}
TYPICAL = 6.9
PADDING = 6


def _width(text):
    """Verdana at 11px, near enough: `textLength` makes the text fit whatever font a machine draws it in."""
    return round(sum(NARROW.get(c, TYPICAL) for c in text))


def numbers(plan, table, group=None):
    rows = tables.group_rows(table, plan.group(group)) if group else [r for d in table.domains for r in d.rows]
    top = tables.counts(rows, plan.kind_names)[plan.strict_kind.name]
    return (top / len(rows) if rows else 0.0), tables.score(rows, plan.weights)


def message(plan, table, group=None):
    strict, weighted = numbers(plan, table, group)
    return f"{render.pct(strict)} strict · {render.pct(weighted)} weighted"


def color(plan, table, group=None):
    return GREEN if numbers(plan, table, group)[0] >= 1 else BLUE


def endpoint(plan, table, group=None, label="done"):
    return {"schemaVersion": 1, "label": label, "message": message(plan, table, group), "color": color(plan, table, group)}


def svg(plan, table, group=None, label="done"):
    text = message(plan, table, group)
    left, right = _width(label) + 2 * PADDING, _width(text) + 2 * PADDING
    total = left + right
    words = escape(f"{label}: {text}")

    def caption(x, width, content):
        safe = escape(content)
        return (f'<text x="{x}" y="15" fill="#010101" fill-opacity=".3" textLength="{width}">{safe}</text>'
                f'<text x="{x}" y="14" fill="#fff" textLength="{width}">{safe}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{words}">'
            f"<title>{words}</title>"
            f'<clipPath id="r"><rect width="{total}" height="20" rx="3"/></clipPath>'
            f'<g clip-path="url(#r)"><rect width="{left}" height="20" fill="#555"/>'
            f'<rect x="{left}" width="{right}" height="20" fill="{color(plan, table, group)}"/></g>'
            f'<g font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-rendering="geometricPrecision">'
            f"{caption(PADDING, _width(label), label)}{caption(left + PADDING, _width(text), text)}</g></svg>\n")
