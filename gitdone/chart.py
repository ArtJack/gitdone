"""`chart`: a picture from the status table's git history. One self-contained SVG, and the same history on the same day gives the same bytes.

The burn-up has three lines on one axis, in rows: the scope, what is weighted done, what is strictly done. It is the record, so it makes no
forecast. The burn-down is the candle: what is left over time, up when the scope grew, with `eta`'s line through it, labelled as a line.
Standard library only, so it can run wherever the engine runs.
"""
import datetime
import math
import os

from . import gitio, history as history_module, render, table as tables
from .plan import PlanError
from .render import escape_xml as escape

WIDTH, HEIGHT = 760, 340
LEFT, RIGHT, TOP, BOTTOM = 44, 148, 84, 30
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
LABEL_GAP = 17
HOVER_LIMIT = 200
BURNDOWN_RIGHT = 182  # a date with its year and its label
MOST_SCOPE_MARKS = 6
SCOPE_MARK_GAP = 28
HORIZON_FACTOR, HORIZON_DAYS = 3, 60  # how far past today the axis follows a line, so that a far date does not flatten the record
TOO_MUCH_HISTORY = "Only the newest part of the table's history was read: there is too much of it."

# The palette passes the dataviz six-check validator in both modes; the scope line is neutral ink, not a third hue.
STYLE = """
:root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d68;--grid:#e1e0d9;--axis:#c3c2b7;--edge:rgba(11,11,11,.10);--strict:#2a78d6;--weighted:#eb6834;--scope:#52514e}
@media (prefers-color-scheme:dark){:root{--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a3a198;--grid:#2c2c2a;--axis:#383835;--edge:rgba(255,255,255,.10);--strict:#3987e5;--weighted:#d95926;--scope:#c3c2b7}}
text{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--ink2);font-size:12px}
.title{fill:var(--ink);font-size:16px;font-weight:600}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.value{fill:var(--ink);font-weight:600}
.line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.dot{stroke:var(--surface);stroke-width:2}
"""


def _tally(plan, text, wanted):
    """(scope, strict, weighted, what is left, whether the table has problems) of a table as it stood."""
    table = tables.parse(text.replace("\r\n", "\n"), plan.kinds)
    rows = [r for d in table.domains if wanted is None or d.n in wanted for r in d.rows]
    top = plan.strict_kind.name
    return len(rows), sum(1 for r in rows if r.kind == top), sum(plan.weights.get(r.kind, 0.0) for r in rows), sum(1 - plan.credit.get(r.kind, 0.0) for r in rows), bool(table.problems)


class Points(list):
    """The chart's points, and whether they reach back as far as the table does."""
    newest_only = False


def points(plan, group=None, today=None):
    """[{date, scope, strict, weighted, left}] oldest first, one per day: the state the table ended that day in, in rows."""
    wanted = set(plan.group(group).domains) if group else None
    top_done = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top_done.code:
        raise PlanError(f"{plan.doc.name} is not in a git repository, so it has no history to chart")
    top = top_done.out.strip()
    rel = os.path.relpath(os.path.realpath(plan.doc), os.path.realpath(top)).replace(os.sep, "/")
    history = history_module.table_commits(top, rel, first_parent=True, today=_day(today) if today else None)
    fits = gitio.fitting(top, [f"{sha}:{path}" for sha, _, path in history], gitio.MOST_BYTES_OF_HISTORY)
    out = Points()
    out.newest_only = fits < len(history)
    history = history[:fits]
    texts = gitio.blobs(top, [f"{sha}:{path}" for sha, _, path in history])
    by_day, scope_before = {}, None
    for (_, date, _), text in zip(reversed(history), reversed(texts)):
        tally = _tally(plan, text, wanted) if text is not None else None
        if tally is None or (tally[4] and scope_before is not None and tally[0] < scope_before):
            continue  # a table that lost rows to a broken line says nothing about them
        by_day[date], scope_before = tally[:4], tally[0]
    if not history or gitio.git(top, "status", "--porcelain", "--", rel).out.strip():
        today = today or datetime.date.today().isoformat()
        by_day[today] = _tally(plan, plan.text_of(plan.doc, "the status table"), wanted)[:4]
    out.extend({"date": d, "scope": by_day[d][0], "strict": by_day[d][1], "weighted": round(by_day[d][2], 3), "left": round(by_day[d][3], 3)} for d in sorted(by_day))
    return out


def csv_text(items):
    return "date,scope,strict,weighted\n" + "".join(f"{p['date']},{p['scope']},{p['strict']},{p['weighted']:g}\n" for p in items)


def burndown_csv(items):
    return "date,scope,left_all_work,left_strict\n" + "".join(f"{p['date']},{p['scope']},{p['left']:g},{p['scope'] - p['strict']}\n" for p in items)


def _day(text):
    return datetime.date.fromisoformat(text)


def _date_words(day, with_year):
    return f"{MONTHS[day.month - 1]} {day.day}" + (f", {day.year}" if with_year else "")


def _y_ticks(top):
    top = max(top, 1)
    for step in (1, 2, 4, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 2500, 5000):
        if top / step <= 5:
            break
    return list(range(0, top + step, step)) if top % step else list(range(0, top + 1, step))


def _x_ticks(items):
    """Up to six dates: the first, the last, and evenly spaced ones between them."""
    first, last = _day(items[0]["date"]), _day(items[-1]["date"])
    span = (last - first).days
    if span == 0:
        return [first]
    count = min(5, span)
    return [first + datetime.timedelta(days=round(span * i / count)) for i in range(count + 1)]


def _steps(items, x, y, key):
    """A stepped path: a value holds until the commit that changed it."""
    parts = [f"M{x(items[0]):.1f} {y(items[0][key]):.1f}"]
    for item in items[1:]:
        parts.append(f"H{x(item):.1f}V{y(item[key]):.1f}")
    return "".join(parts)


def _spread(wanted, low, high):
    """Label positions at least LABEL_GAP apart, as near as they can be to where each line ends."""
    order = sorted(range(len(wanted)), key=lambda i: wanted[i])
    placed = [wanted[i] for i in order]
    for i in range(1, len(placed)):
        placed[i] = max(placed[i], placed[i - 1] + LABEL_GAP)
    overflow = placed[-1] - high
    if overflow > 0:
        placed[-1] -= overflow
        for i in range(len(placed) - 2, -1, -1):
            placed[i] = min(placed[i], placed[i + 1] - LABEL_GAP)
    out = [0.0] * len(wanted)
    for rank, i in enumerate(order):
        out[i] = max(placed[rank], low)
    return out


def svg(items, title):
    if not items:
        raise PlanError("the table has no history to chart")
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    first, last = _day(items[0]["date"]), _day(items[-1]["date"])
    span = (last - first).days
    ticks = _y_ticks(max(p["scope"] for p in items))
    y_top = ticks[-1] or 1

    def x_of_day(day):
        return LEFT + (plot_w / 2 if span == 0 else plot_w * (day - first).days / span)

    def x(item):
        return x_of_day(_day(item["date"]))

    def y(value):
        return TOP + plot_h - plot_h * value / y_top

    end = items[-1]
    scope = end["scope"] or 1
    words = (f"As of {end['date']}: scope {end['scope']} rows, weighted {render.pct(end['weighted'] / scope)}, "
             f"strict {render.pct(end['strict'] / scope)}.")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="t d">',
           f'<title id="t">{escape(title)}: burn-up</title>', f'<desc id="d">{escape(words)}</desc>', f"<style>{STYLE}</style>",
           f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" fill="var(--surface)" stroke="var(--edge)"/>',
           f'<text class="title" x="16" y="28">{escape(title)}: burn-up</text>',
           f'<text x="16" y="47">Rows over time, read from the status table\'s git history. {_too_much(items) or "No forecast: no percentage is a date."}</text>']
    legend_x = 16
    for name, color in (("Scope", "scope"), ("Weighted", "weighted"), ("Strict", "strict")):
        out.append(f'<rect x="{legend_x}" y="61" width="14" height="3" rx="1.5" fill="var(--{color})"/>')
        out.append(f'<text x="{legend_x + 19}" y="67">{name}</text>')
        legend_x += 19 + 8 * len(name) + 12
    for value in ticks:
        out.append(f'<line x1="{LEFT}" x2="{LEFT + plot_w}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="var(--{"axis" if value == 0 else "grid"})"/>')
        out.append(f'<text class="tick" x="{LEFT - 8}" y="{y(value) + 4:.1f}" text-anchor="end">{value}</text>')
    x_days = _x_ticks(items)
    for i, day in enumerate(x_days):
        anchor = "middle"
        if len(x_days) > 1:
            anchor = "start" if i == 0 else ("end" if i == len(x_days) - 1 else "middle")
        with_year = i == 0 or day.year != x_days[i - 1].year
        out.append(f'<text class="tick" x="{x_of_day(day):.1f}" y="{TOP + plot_h + 19}" text-anchor="{anchor}">{_date_words(day, with_year)}</text>')
    strict_path = _steps(items, x, y, "strict")
    baseline = y(0)
    out.append(f'<path d="{strict_path}V{baseline:.1f}H{x(items[0]):.1f}Z" fill="var(--strict)" fill-opacity=".1"/>')
    out.append(f'<path class="line" d="{_steps(items, x, y, "scope")}" stroke="var(--scope)"/>')
    out.append(f'<path class="line" d="{_steps(items, x, y, "weighted")}" stroke="var(--weighted)"/>')
    out.append(f'<path class="line" d="{strict_path}" stroke="var(--strict)"/>')
    series = [("rows in scope", "scope", str(end["scope"])),
              ("weighted", "weighted", render.pct(end["weighted"] / scope)),
              ("strict", "strict", render.pct(end["strict"] / scope))]
    end_x = x(end)
    label_x = LEFT + plot_w + 14
    wanted = [y(end[key]) for _, key, _ in series]
    placed = _spread(wanted, TOP - 2, TOP + plot_h + 2)
    for (name, key, value), line_y, label_y in zip(series, wanted, placed):
        if abs(label_y - line_y) > 1.5 or end_x < LEFT + plot_w - 1:
            out.append(f'<line x1="{end_x + 6:.1f}" y1="{line_y:.1f}" x2="{label_x - 4:.1f}" y2="{label_y:.1f}" stroke="var(--axis)"/>')
        out.append(f'<circle class="dot" cx="{end_x:.1f}" cy="{line_y:.1f}" r="5" fill="var(--{key})"/>')
        out.append(f'<text x="{label_x}" y="{label_y + 4:.1f}"><tspan class="value">{escape(value)}</tspan> {name}</text>')
    stride = max(1, len(items) // HOVER_LIMIT)
    shown = items[::stride]
    for i, item in enumerate(shown):
        left = x(item)
        right = x(shown[i + 1]) if i + 1 < len(shown) else LEFT + plot_w
        tip = (f"{item['date']}: scope {item['scope']}, weighted {item['weighted']:g}, strict {item['strict']}")
        out.append(f'<rect x="{left:.1f}" y="{TOP}" width="{max(right - left, 1):.1f}" height="{plot_h}" fill="transparent"><title>{escape(tip)}</title></rect>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _too_much(items):
    return TOO_MUCH_HISTORY if getattr(items, "newest_only", False) else ""


def _toward(start, left, end, edge):
    """Where a straight burn from (start, left) to (end, 0) stands at the chart's right edge, as (day, left)."""
    if end <= edge or end <= start:
        return end, 0.0
    return edge, left * (1 - (edge - start).days / (end - start).days)


def _scope_marks(items, x, y):
    """The days the scope changed, biggest first, none on top of another: the bumps a reader asks about."""
    marks = []
    for before, after in zip(items, items[1:]):
        change = after["scope"] - before["scope"]
        if change:
            marks.append((abs(change), change, after))
    placed, out = [], []
    for _, change, item in sorted(marks, key=lambda m: (-m[0], m[2]["date"]))[:MOST_SCOPE_MARKS]:
        at = x(item)
        if all(abs(at - other) >= SCOPE_MARK_GAP for other in placed):
            placed.append(at)
            out.append(f'<text class="tick" x="{at:.1f}" y="{y(item["left"]) - 8:.1f}" text-anchor="middle">{"+" if change > 0 else "−"}{abs(change)}</text>')
    return out


def burndown(items, title, found, words):
    """What is left, day by day, and where a line through the pace lands. `found` is what `forecast.data` returned; `words` is its headline."""
    if not items:
        raise PlanError("the table has no history to chart")
    today = _day(found["as_of"])
    points = [{"date": p["date"], "left": p["left"], "left_live": p["scope"] - p["strict"], "scope": p["scope"]} for p in items]
    if _day(points[-1]["date"]) < today:
        points.append({**points[-1], "date": found["as_of"]})
    first = _day(points[0]["date"])
    plot_w, plot_h = WIDTH - LEFT - BURNDOWN_RIGHT, HEIGHT - TOP - BOTTOM
    likely = _day(found["likely"]) if found.get("likely") else None
    sure = _day(found["sure"]) if found.get("sure") else (likely and likely + datetime.timedelta(days=3650))  # past ten years: as far as this axis could care
    deadline = _day(found["deadline"]["date"]) if found.get("deadline") else None
    live = found.get("live") or {}
    live_likely = _day(live["likely"]) if live.get("likely") else None
    horizon = today + datetime.timedelta(days=max((today - first).days * HORIZON_FACTOR, HORIZON_DAYS))
    edge = max([today] + [min(day, horizon) for day in (likely, sure, deadline, live_likely) if day])
    span = (edge - first).days
    ticks = _y_ticks(max(math.ceil(max(p["left_live"] for p in points)), 1))
    y_top = ticks[-1] or 1

    def x_of_day(day):
        return LEFT + (plot_w / 2 if span == 0 else plot_w * (day - first).days / span)

    def x(item):
        return x_of_day(_day(item["date"]))

    def y(value):
        return TOP + plot_h - plot_h * value / y_top

    left_now = found["left"]
    needed = bool(deadline and today < deadline <= edge and left_now)
    scope_words = "A step up is scope, marked with its size, or a row going back. Either moves the date." + (" Dotted: what the deadline needs." if needed else "")
    kind = " ".join(str(live.get("kind", "Live")).split())
    subtitle = f"Rows left, in blue on {kind} rows alone, in orange with all work, from the table's git history."
    if _too_much(items):
        subtitle = _too_much(items)
    elif likely:
        subtitle += f" Dashed: a line through the last {found['window_days']} days, not a promise."
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="t d">',
           f'<title id="t">{escape(title)}: burn-down</title>', f'<desc id="d">{escape(words)}</desc>', f"<style>{STYLE}</style>",
           f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" fill="var(--surface)" stroke="var(--edge)"/>',
           f'<text class="title" x="16" y="28">{escape(title)}: burn-down</text>', f'<text x="16" y="47">{escape(subtitle)}</text>',
           f'<text x="16" y="67">{escape(words if not likely else scope_words)}</text>']
    for value in ticks:
        out.append(f'<line x1="{LEFT}" x2="{LEFT + plot_w}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="var(--{"axis" if value == 0 else "grid"})"/>')
        out.append(f'<text class="tick" x="{LEFT - 8}" y="{y(value) + 4:.1f}" text-anchor="end">{value}</text>')
    x_days = _x_ticks([{"date": first.isoformat()}, {"date": edge.isoformat()}])
    for i, day in enumerate(x_days):
        anchor = "middle"
        if len(x_days) > 1:
            anchor = "start" if i == 0 else ("end" if i == len(x_days) - 1 else "middle")
        with_year = i == 0 or day.year != x_days[i - 1].year
        out.append(f'<text class="tick" x="{x_of_day(day):.1f}" y="{TOP + plot_h + 19}" text-anchor="{anchor}">{_date_words(day, with_year)}</text>')
    if deadline and first <= deadline <= edge:
        at = x_of_day(deadline)
        out.append(f'<line x1="{at:.1f}" x2="{at:.1f}" y1="{TOP}" y2="{TOP + plot_h}" stroke="var(--ink2)" stroke-dasharray="2 4"/>')
        out.append(f'<text class="tick" x="{at + 5:.1f}" y="{TOP + 12}">deadline</text>')
    origin = (x_of_day(today), y(left_now))
    if needed:
        out.append(f'<line x1="{origin[0]:.1f}" y1="{origin[1]:.1f}" x2="{x_of_day(deadline):.1f}" y2="{y(0):.1f}" stroke="var(--ink2)" stroke-width="1.5" stroke-dasharray="2 4"/>')
    if likely:
        likely_day, likely_left = _toward(today, left_now, likely, edge)
        sure_day, sure_left = _toward(today, left_now, sure, edge)
        corner = [] if likely_left or not sure_left else [(x_of_day(edge), y(0))]
        shape = [origin, (x_of_day(likely_day), y(likely_left))] + corner + [(x_of_day(sure_day), y(sure_left))]
        out.append('<path d="M' + "L".join(f"{a:.1f} {b:.1f}" for a, b in shape) + 'Z" fill="var(--weighted)" fill-opacity=".14"/>')
        out.append(f'<line class="line" x1="{origin[0]:.1f}" y1="{origin[1]:.1f}" x2="{x_of_day(likely_day):.1f}" y2="{y(likely_left):.1f}" stroke="var(--weighted)" stroke-dasharray="6 5"/>')
    left_live = live.get("left", points[-1]["left_live"])
    live_origin = (x_of_day(today), y(left_live))
    if live_likely:
        end_day, end_left = _toward(today, left_live, live_likely, edge)
        out.append(f'<line class="line" x1="{live_origin[0]:.1f}" y1="{live_origin[1]:.1f}" x2="{x_of_day(end_day):.1f}" y2="{y(end_left):.1f}" stroke="var(--strict)" stroke-dasharray="6 5"/>')
    out.append(f'<path class="line" d="{_steps(points, x, y, "left_live")}" stroke="var(--strict)"/>')
    out.append(f'<path class="line" d="{_steps(points, x, y, "left")}" stroke="var(--weighted)"/>')
    out.extend(_scope_marks(points, x, y))
    out.append(f'<circle class="dot" cx="{live_origin[0]:.1f}" cy="{live_origin[1]:.1f}" r="5" fill="var(--strict)"/>')
    out.append(f'<circle class="dot" cx="{origin[0]:.1f}" cy="{origin[1]:.1f}" r="5" fill="var(--weighted)"/>')
    label_x = LEFT + plot_w + 14
    label_y = TOP + 4
    said = [(f"{left_now:g}", "rows left, all work")]
    if likely:
        said.append((_date_words(likely, likely.year != today.year), "likely"))
        if found.get("sure"):
            said.append((_date_words(sure, sure.year != today.year), "85% sure"))
    said.append((f"{left_live:g}", f"rows left, {escape(kind)} alone"))
    if live_likely:
        said.append((_date_words(live_likely, live_likely.year != today.year), "likely"))
    for value, name in said:
        out.append(f'<text x="{label_x}" y="{label_y:.1f}"><tspan class="value">{escape(value)}</tspan> {name}</text>')
        label_y += LABEL_GAP + 3
    if deadline:
        out.append(f'<text x="{label_x}" y="{label_y:.1f}"><tspan class="value">{escape(_date_words(deadline, deadline.year != today.year))}</tspan> deadline</text>')
    stride = max(1, len(points) // HOVER_LIMIT)
    shown = points[::stride]
    for i, item in enumerate(shown):
        left = x(item)
        right = x(shown[i + 1]) if i + 1 < len(shown) else x_of_day(today)
        tip = f"{item['date']}: {item['left']:g} rows left of {item['scope']}"
        out.append(f'<rect x="{left:.1f}" y="{TOP}" width="{max(right - left, 1):.1f}" height="{plot_h}" fill="transparent"><title>{escape(tip)}</title></rect>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
