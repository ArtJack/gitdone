"""`eta`: when the rows will be done if the work goes on as it has. A line through the status table's git history, and it says so.

The pace is what moved existing rows toward done, per calendar day. A day when nothing moved counts, because the time passed. A row added
or taken out is scope and not pace: it changes what is left, and so the date, which is the point of having one. The range comes from the
pace's own spread by a closed form, so the same history gives the same words, and no random number is involved.

Nothing here reaches the view: it changes with the day, and the gate compares the view byte for byte.
"""
import datetime
import math
import os

from . import chart, gitio, render, table as tables
from .plan import PlanError

WINDOW = 28
ENOUGH = 3  # days with movement before a line is drawn through them
SURE = 1.0364  # the 85th percentile of a normal curve, in spreads from its middle
TOO_FAR = 3650


def _where(plan):
    top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top.code:
        raise PlanError(f"{plan.doc.name} is not in a git repository, so it has no history to read a pace from")
    root = top.out.strip()
    return root, os.path.relpath(os.path.realpath(plan.doc), os.path.realpath(root)).replace(os.sep, "/")


def _weights(plan, text, wanted=None):
    """{row: weight} of a table as it stood. A status the plan no longer has is None: unknown, which is not the same as nothing done."""
    table = tables.parse(text, plan.kinds)
    return {r.num: plan.weights.get(r.kind) for d in table.domains if wanted is None or d.n in wanted for r in d.rows}


def _left(plan, rows):
    return round(sum(1 - plan.weights.get(r.kind, 0.0) for r in rows), 6)


def table_steps(plan, start, today, wanted=None):
    """(steps, born). A step is (commit, date, rows before, rows after), oldest first, on the main line. `born` is the table's first day
    if that falls in the window, and None if the table is older than that or has no commit.
    """
    top, rel = _where(plan)
    commits = list(reversed(chart._history(top, rel, f"--since={start.isoformat()}T00:00:00")))
    if not commits:
        return [], None
    texts = gitio.blobs(top, [f"{commits[0][0]}^:{commits[0][2]}"] + [f"{sha}:{path}" for sha, _, path in commits])
    before = _weights(plan, texts[0], wanted) if texts[0] is not None else None
    born = None if before is not None else min(commits[0][1], today.isoformat())
    steps = []
    for (sha, date, _), text in zip(commits, texts[1:]):
        if text is None:
            continue
        after = _weights(plan, text, wanted)
        if before is not None:
            steps.append((sha, min(date, today.isoformat()), before, after))
        before = after
    return steps, born


def _last_change(plan):
    top, rel = _where(plan)
    done = gitio.git(top, "log", "-1", "--format=%as", "--", rel)
    return done.out.strip() or None


def _birth(plan):
    top, rel = _where(plan)
    dates = gitio.git(top, "log", "--first-parent", "--follow", "--format=%as", "--", rel).out.split()
    return dates[-1] if dates else None


class Pace:
    """What a window of days held: per day, what moved rows toward done, and what scope added to what is left."""

    def __init__(self, today, days):
        self.today = today
        self.days = days
        self.moved = [0.0] * days
        self.grew = [0.0] * days
        self.added = self.removed = 0

    def _take(self, offset, before, after):
        new, gone = after.keys() - before.keys(), before.keys() - after.keys()
        self.moved[offset] += sum(after[n] - before[n] for n in after.keys() & before.keys() if after[n] is not None and before[n] is not None)
        self.grew[offset] += sum(1 - (after[n] or 0.0) for n in new) - sum(1 - (before[n] or 0.0) for n in gone)
        self.added += len(new)
        self.removed += len(gone)

    def moving_days(self):
        return sum(1 for x in self.moved if abs(x) > 1e-9)

    def per_day(self):
        return sum(self.moved) / self.days

    def net(self):
        return [m - g for m, g in zip(self.moved, self.grew)]

    def keeps_growing(self):
        """Scope that grew on one day is an event, and it is already in what is left. On several days it is a habit, and a habit can be extrapolated."""
        return sum(1 for x in self.grew if x > 1e-9) >= 2 and sum(self.grew) > 1e-9

    def largest_day_share(self):
        """How much of the movement one day made. A table moved in one sitting is a lumpy thing to draw a line through."""
        gains = [x for x in self.moved if x > 0]
        return max(gains) / sum(gains) if gains else 0.0


def read_pace(plan, group=None, days=WINDOW, today=None):
    """The pace over the last `days` days, or over the table's life if that is shorter. None if the table has no commit in that time."""
    today = today or datetime.date.today()
    wanted = set(plan.group(group).domains) if group else None
    start = today - datetime.timedelta(days=days - 1)
    steps, born = table_steps(plan, start, today, wanted)
    if not steps and not born:
        return None
    if born:
        start = max(start, datetime.date.fromisoformat(born))
    pace = Pace(today, (today - start).days + 1)
    for _, date, before, after in steps:
        pace._take(max((datetime.date.fromisoformat(date) - start).days, 0), before, after)
    return pace


def _mean_and_spread(series):
    mean = sum(series) / len(series)
    if len(series) < 2:
        return mean, 0.0
    return mean, math.sqrt(sum((x - mean) ** 2 for x in series) / (len(series) - 1))


def days_for(left, series, spreads=0.0):
    """Days until `series` has covered `left`, with a sum of n days taken as normal: n·mean − spreads·spread·√n = left. None if it never does."""
    mean, spread = _mean_and_spread(series)
    if mean <= 1e-9:
        return None
    root = (spreads * spread + math.sqrt((spreads * spread) ** 2 + 4 * mean * left)) / (2 * mean)
    return root * root


def _dates(left, series, today):
    """{likely, sure} as dates, too_far if the line runs off the calendar, or None if it never gets there."""
    if left <= 0:
        return {"likely": today.isoformat(), "sure": today.isoformat(), "too_far": False}
    likely, sure = days_for(left, series), days_for(left, series, SURE)
    if likely is None:
        return None
    if likely > TOO_FAR:
        return {"likely": None, "sure": None, "too_far": True}

    def day(count):
        return (today + datetime.timedelta(days=min(max(math.ceil(round(count, 6)), 1), TOO_FAR))).isoformat()
    return {"likely": day(likely), "sure": day(sure), "too_far": False}


def _workstreams(plan, table, series, today):
    """The plan's order read as a sequence: each workstream finishes when everything up to it has been covered."""
    rows = {r.num: r for d in table.domains for r in d.rows}
    seen, running, out = set(), 0.0, []
    for ws_id in plan.order:
        w = plan.workstream(ws_id)
        mine = [n for n in render.workstream_rows_numbers(w) if n in rows and n not in seen]
        seen.update(mine)
        left = _left(plan, [rows[n] for n in mine])
        running += left
        out.append({"id": ws_id, "name": w.get("name", ""), "left": left, "dates": _dates(running, series, today) if series and left else None})
    rest = [r for n, r in rows.items() if n not in seen]
    if out and rest:
        left = _left(plan, rest)
        running += left
        out.append({"id": None, "name": "Everything else", "left": left, "dates": _dates(running, series, today) if series and left else None})
    return out


def _deadline(plan, found, pace, today):
    if plan.deadline is None:
        return None
    day = datetime.date.fromisoformat(plan.deadline)
    start = plan.start or _birth(plan) or today.isoformat()
    began = min(datetime.date.fromisoformat(start), day)
    whole = (day - began).days
    days_left = (day - today).days
    out = {"date": plan.deadline, "start": began.isoformat(), "days_left": days_left, "time_used": 1.0 if whole <= 0 else min(max((today - began).days / whole, 0.0), 1.0),
           "needs_per_day": round(found["left"] / days_left, 3) if days_left > 0 and found["left"] else None, "late_by": None, "late_by_if_sure": None}
    if found["likely"]:
        out["late_by"] = (datetime.date.fromisoformat(found["likely"]) - day).days
        out["late_by_if_sure"] = (datetime.date.fromisoformat(found["sure"]) - day).days
    return out


def data(plan, group=None, days=WINDOW, today=None):
    """Everything `eta` says, as data."""
    if days < 1:
        raise PlanError("eta: the window must be at least one day")
    today = today or datetime.date.today()
    table = tables.load_clean(plan)
    wanted = set(plan.group(group).domains) if group else None
    rows = [r for d in table.domains if wanted is None or d.n in wanted for r in d.rows]
    top = sum(1 for r in rows if r.kind == plan.strict_kind.name)
    out = {"state": "too_little", "as_of": today.isoformat(), "rows": len(rows), "left": _left(plan, rows),
           "strict": top / len(rows) if rows else 0.0, "weighted": tables.score(rows, plan.weights), "window_days": 0, "moving_days": 0,
           "pace_per_day": 0.0, "likely": None, "sure": None, "too_far": False, "largest_day_share": 0.0, "last_change": None,
           "scope": {"added": 0, "removed": 0, "if_it_goes_on": None, "never_catches_up": False}, "deadline": None, "workstreams": []}
    pace = read_pace(plan, group=group, days=days, today=today)
    series = None
    out["window_days"] = days
    if pace is not None:
        out.update(window_days=pace.days, moving_days=pace.moving_days(), pace_per_day=round(pace.per_day(), 3), largest_day_share=round(pace.largest_day_share(), 3))
        out["scope"].update(added=pace.added, removed=pace.removed)
        if pace.moving_days() >= ENOUGH and pace.per_day() > 1e-9:
            series = pace.moved
    else:
        out["last_change"] = _last_change(plan)
    if not rows:
        out["state"] = "no_rows"
    elif not out["left"]:
        out["state"] = "done"
    elif series:
        out.update(state="dated", **_dates(out["left"], series, today))
        if pace.keeps_growing():
            grown = _dates(out["left"], pace.net(), today)
            out["scope"]["if_it_goes_on"] = grown
            out["scope"]["never_catches_up"] = grown is None
    elif pace is None and out["last_change"]:
        out["state"] = "stalled"
    elif pace is not None and (pace.moving_days() >= ENOUGH or (pace.days >= days and not pace.moving_days())):
        out["state"] = "stalled"
        out["last_change"] = _last_change(plan)
    if not group:
        out["workstreams"] = _workstreams(plan, table, series, today)
    out["deadline"] = _deadline(plan, out, pace, today)
    return out


def _day_words(iso, today):
    day = datetime.date.fromisoformat(iso)
    return chart._date_words(day, day.year != datetime.date.fromisoformat(today).year)


def _rows_words(value):
    return f"{value:.1f}".rstrip("0").rstrip(".") if value % 1 else f"{value:.0f}"


def _pace_words(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _deadline_words(found):
    d = found["deadline"]
    when = _day_words(d["date"], found["as_of"])
    if d["days_left"] < 0 and found["left"]:
        return f"Deadline {when}: passed {_plural(-d['days_left'], 'day')} ago, with {_rows_words(found['left'])} rows left."
    if not found["left"]:
        return f"Deadline {when}: nothing left."
    if found["likely"]:
        late = d["late_by"]
        said = f"likely {_plural(late, 'day')} late" if late > 0 else (f"likely {_plural(-late, 'day')} early" if late < 0 else "likely on the day")
    else:
        said = f"{_plural(d['days_left'], 'day')} left"
    needs = ""
    if d["needs_per_day"]:
        needs = f" It needs {_pace_words(d['needs_per_day'])} rows a day from here" + (f"; the pace is {_pace_words(found['pace_per_day'])}." if found["window_days"] and found["moving_days"] else ".")
    return f"Deadline {when}: {said}.{needs}"


def headline(found):
    """The one thing `eta` is asked."""
    state, days = found["state"], found["window_days"]
    if state == "dated":
        if found["too_far"]:
            return f"At the pace of the last {_plural(days, 'day')}, this is more than ten years away. That is a line, not a promise."
        return (f"Likely done {_day_words(found['likely'], found['as_of'])}, 85% sure by {_day_words(found['sure'], found['as_of'])}: "
                f"a line through the last {_plural(days, 'day')}, not a promise.")
    if state == "done":
        return "Nothing left: every row is done."
    if state == "no_rows":
        return "No date: the table has no rows."
    if state == "stalled":
        since = f" The table last changed {found['last_change']}." if found["last_change"] else ""
        return f"No date: nothing moved a row in the last {_plural(found['window_days'], 'day')}.{since}"
    return f"No date yet: rows moved on {_plural(found['moving_days'], 'day')} so far, and a line needs {ENOUGH}."


def opener_line(plan, today=None):
    """One line for whoever opens the project; None if there is nothing worth a line yet."""
    found = data(plan, today=today)
    parts = []
    if found["state"] == "dated" and not found["too_far"]:
        parts.append(f"Likely done {_day_words(found['likely'], found['as_of'])} (85%: {_day_words(found['sure'], found['as_of'])}), at the last {_plural(found['window_days'], 'day')}' pace.")
    elif found["state"] in ("dated", "stalled"):
        parts.append(headline(found))
    if found["scope"]["never_catches_up"]:
        parts.append("Scope is growing as fast as the work.")
    if found["deadline"]:
        parts.append(_deadline_words(found))
    return " ".join(parts) or None


def text(found):
    L = [headline(found)]
    if found["rows"]:
        L.append(f"Left: {_rows_words(found['left'])} of {found['rows']} rows (weighted {render.pct(found['weighted'])}, strict {render.pct(found['strict'])}).")
    if found["window_days"]:
        L.append(f"Pace: {_pace_words(found['pace_per_day'])} rows a day; rows moved on {found['moving_days']} of {_plural(found['window_days'], 'day')}.")
    if found["state"] == "dated" and found["largest_day_share"] > 0.5:
        L.append(f"One day made {render.pct(found['largest_day_share'])} of that, so read the date loosely.")
    scope = found["scope"]
    if scope["added"] or scope["removed"]:
        words = f"Scope: {scope['added']} rows added, {scope['removed']} taken out in that time."
        if scope["never_catches_up"]:
            words += " If it goes on growing like that, the work never catches up."
        elif scope["if_it_goes_on"] and scope["if_it_goes_on"]["likely"]:
            grown = scope["if_it_goes_on"]
            words += f" If it goes on growing like that: likely {_day_words(grown['likely'], found['as_of'])}, 85% sure by {_day_words(grown['sure'], found['as_of'])}."
        L.append(words)
    d = found["deadline"]
    if d:
        L.append(_deadline_words(found))
        L.append(f"  Work {render.bar(found['weighted'])} {render.pct(found['weighted'])}")
        L.append(f"  Time {render.bar(d['time_used'])} {render.pct(d['time_used'])}, {_day_words(d['start'], found['as_of'])} to {_day_words(d['date'], found['as_of'])}")
    if any(w["left"] for w in found["workstreams"]):
        L += ["", "In the plan's order:"]
        width = max(len(f"{w['id'] or ''} {w['name']}".strip()) for w in found["workstreams"])
        for w in found["workstreams"]:
            name = f"{w['id'] or ''} {w['name']}".strip()
            if not w["left"]:
                when = "done"
            elif w["dates"] and w["dates"]["likely"]:
                when = f"{_rows_words(w['left'])} left, likely {_day_words(w['dates']['likely'], found['as_of'])}"
            else:
                when = f"{_rows_words(w['left'])} left"
            L.append(f"  {name:<{width}}  {when}")
    return "\n".join(L)


def left_now(plan):
    table = tables.load_clean(plan)
    return _left(plan, [r for d in table.domains for r in d.rows])


def _moved_words(before, after, series, today):
    """What a change in what is left does to the likely date; None if there is no date for it to move."""
    then, now = _dates(max(before, 0.0), series, today), _dates(max(after, 0.0), series, today)
    if not then or not now or not then["likely"] or not now["likely"]:
        return None
    was, is_now = datetime.date.fromisoformat(then["likely"]), datetime.date.fromisoformat(now["likely"])
    change = (is_now - was).days
    if not change:
        return "The likely date stays " + _day_words(now["likely"], today.isoformat()) + "."
    return f"That moves the likely date from {_day_words(then['likely'], today.isoformat())} to {_day_words(now['likely'], today.isoformat())} ({change:+d} days)."


def shift_words(plan, before, today=None):
    """What `add` or `remove` just did to the date. The pace comes from what is committed, so it is the same before and after."""
    today = today or datetime.date.today()
    pace = read_pace(plan, today=today)
    if pace is None or pace.moving_days() < ENOUGH:
        return None
    return _moved_words(before, left_now(plan), pace.moved, today)


def against(plan, base, today=None):
    """What a change did to the scope, against a base commit: for a reviewer, who is deciding whether a feature is worth its days."""
    today = today or datetime.date.today()
    top, rel = _where(plan)
    then = gitio.git(top, "show", f"{base}:{rel}")
    if then.code:
        return None
    before = _weights(plan, then.out)
    table = tables.load_clean(plan)
    now = {r.num: plan.weights.get(r.kind) for d in table.domains for r in d.rows}
    added, removed = sorted(now.keys() - before.keys()), sorted(before.keys() - now.keys())
    if not added and not removed:
        return None
    pace = read_pace(plan, today=today)
    moved = None
    if pace is not None and pace.moving_days() >= ENOUGH:
        moved = _moved_words(sum(1 - (w or 0.0) for w in before.values()), sum(1 - (w or 0.0) for w in now.values()), pace.moved, today)
    return {"added": added, "removed": removed, "date_moved": moved}
