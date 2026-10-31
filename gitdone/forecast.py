"""`eta`: when the rows will be done if the work goes on as it has. A line through the status table's git history, and it says so.

The pace is what moved existing rows toward done, per calendar day. A day when nothing moved counts, because the time passed. A row added
or taken out is scope and not pace: it changes what is left, and so the date, which is the point of having one. The range comes from the
pace's own spread by a closed form, so the same history on the same day gives the same words, and no random number is involved.

Two lines are drawn, because a weight is a claim too: one through everything the weights credit, and one through what reached the strict
kind, which is the only movement git has held to anything.

Nothing here reaches the view: it changes with the day, and the gate compares the view byte for byte.
"""
import datetime
import math
import os

from . import chart, gitio, history, render, table as tables
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


def _is_shallow(top):
    return gitio.git(top, "rev-parse", "--is-shallow-repository").out.strip() == "true"


def _kinds(plan, text, wanted=None):
    """{row: kind} of a table as it stood, or None if it could not be read then. A broken commit is no statement about any row, and a status
    the plan no longer has is no statement about how far the row had got.
    """
    table = tables.parse(text.replace("\r\n", "\n"), plan.kinds)
    if table.problems or not table.rows:
        return None
    return {r.num: r.kind for d in table.domains if wanted is None or d.n in wanted for r in d.rows}


def _left(plan, rows):
    return round(sum(1 - plan.weights.get(r.kind, 0.0) for r in rows), 6)


def table_steps(plan, start=None, today=None, wanted=None):
    """(steps, born). A step is (commit, date, rows before, rows after), oldest first, on the main line of this branch, from `start` on, with
    the table as it stood just before that. `born` is the table's first day, and None if it has no commit.

    What is in the window is decided by the dates the history keeps, so a rebase, which rewrites only when a commit was made, moves nothing.
    """
    top, rel = _where(plan)
    today = today or datetime.date.today()
    commits = list(reversed(history.table_commits(top, rel, first_parent=True, today=today)))
    if not commits:
        return [], None
    born = commits[0][1]
    first = 0
    if start is not None:
        wanted_from = start.isoformat()
        first = next((i for i, c in enumerate(commits) if c[1] >= wanted_from), len(commits))
    read_from = max(first - 1, 0)

    def stop(words):
        raise PlanError(f"git could not read the table's history: {words.strip()[:200]}")
    texts = gitio.blobs(top, [f"{sha}:{path}" for sha, _, path in commits[read_from:]], failed=stop)
    before, steps = None, []
    for (sha, date, _), text in zip(commits[read_from:], texts):
        after = _kinds(plan, text, wanted) if text is not None else None
        if after is None:
            continue
        if before is not None:
            steps.append((sha, date, before, after))
        before = after
    return steps, born


class Pace:
    """What a window of days held: per day, what moved rows toward done, what of that reached the strict kind, and what scope added to what is left."""

    def __init__(self, plan, today, days):
        self.plan = plan
        self.today = today
        self.days = days
        self.moved = [0.0] * days
        self.reached = [0.0] * days  # the part of `moved` that landed on the strict kind
        self.live = [0.0] * days  # rows reaching the strict kind, less rows leaving it
        self.grew = [0.0] * days
        self.grew_live = [0.0] * days
        self.added = self.removed = 0

    def _take(self, offset, before, after):
        weights, top = self.plan.weights, self.plan.strict_kind.name
        new, gone = after.keys() - before.keys(), before.keys() - after.keys()
        for n in after.keys() & before.keys():
            was, now = before[n], after[n]
            if was is None or now is None or was == now:
                continue
            gain = weights.get(now, 0.0) - weights.get(was, 0.0)
            self.moved[offset] += gain
            if now == top:
                self.reached[offset] += gain
            self.live[offset] += (now == top) - (was == top)
        self.grew[offset] += sum(1 - weights.get(after[n], 0.0) for n in new) - sum(1 - weights.get(before[n], 0.0) for n in gone)
        self.grew_live[offset] += sum(after[n] != top for n in new) - sum(before[n] != top for n in gone)
        self.added += len(new)
        self.removed += len(gone)

    def moving_days(self):
        return sum(1 for x in self.moved if abs(x) > 1e-9)

    def live_days(self):
        return sum(1 for x in self.live if x)

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

    def short_of_live_share(self):
        """How much of the forward movement stopped short of the strict kind, which nothing but a note holds up."""
        gains = sum(x for x in self.moved if x > 0)
        return 1 - min(sum(x for x in self.reached if x > 0) / gains, 1.0) if gains else 0.0


def read_pace(plan, group=None, days=WINDOW, today=None):
    """The pace over the last `days` days, or over the table's life if that is shorter. None if the table has no commit at all."""
    today = today or datetime.date.today()
    wanted = set(plan.group(group).domains) if group else None
    start = today - datetime.timedelta(days=days - 1)
    steps, born = table_steps(plan, start, today, wanted)
    if born is None:
        return None
    start = max(start, datetime.date.fromisoformat(born))
    pace = Pace(plan, today, (today - start).days + 1)
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
    """{likely, sure} as dates, too_far if the line runs off the calendar, or None if it never gets there. Either date past ten years is not given."""
    if left <= 0:
        return {"likely": today.isoformat(), "sure": today.isoformat(), "too_far": False}
    likely, sure = days_for(left, series), days_for(left, series, SURE)
    if likely is None:
        return None
    if likely > TOO_FAR:
        return {"likely": None, "sure": None, "too_far": True}

    def day(count):
        return (today + datetime.timedelta(days=max(math.ceil(round(count, 6)), 1))).isoformat()
    return {"likely": day(likely), "sure": day(sure) if sure <= TOO_FAR else None, "too_far": False}


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
        out.append({"id": ws_id, "name": w.get("name", ""), "rows": len(mine), "left": left, "dates": _dates(running, series, today) if series and left else None})
    rest = [r for n, r in rows.items() if n not in seen]
    if out and rest:
        left = _left(plan, rest)
        running += left
        out.append({"id": None, "name": "Everything else", "rows": len(rest), "left": left, "dates": _dates(running, series, today) if series and left else None})
    return out


def _deadline(plan, found, born, today):
    if plan.deadline is None:
        return None
    day = datetime.date.fromisoformat(plan.deadline)
    began = min(datetime.date.fromisoformat(plan.start or born or today.isoformat()), day)
    whole = (day - began).days
    days_left = (day - today).days
    out = {"date": plan.deadline, "start": began.isoformat(), "days_left": days_left, "time_used": 1.0 if whole <= 0 else min(max((today - began).days / whole, 0.0), 1.0),
           "needs_per_day": round(found["left"] / days_left, 3) if days_left > 0 and found["left"] else None, "late_by": None, "late_by_if_sure": None, "late_by_live": None}

    def late(iso):
        return (datetime.date.fromisoformat(iso) - day).days if iso else None
    out["late_by"], out["late_by_if_sure"], out["late_by_live"] = late(found["likely"]), late(found["sure"]), late(found["live"]["likely"])
    return out


def _live_line(plan, rows, pace, today):
    """The same line through the strict kind alone. Its own count of what is left, its own pace, and its own answer about whether a line can be drawn."""
    top = plan.strict_kind.name
    left = sum(1 for r in rows if r.kind != top)
    out = {"kind": top, "left": left, "moving_days": 0, "pace_per_day": 0.0, "likely": None, "sure": None, "too_far": False}
    if pace is None:
        return out
    out.update(moving_days=pace.live_days(), pace_per_day=round(sum(pace.live) / pace.days, 3))
    if left and pace.live_days() >= ENOUGH and sum(pace.live) > 0:
        out.update(_dates(left, pace.live, today))
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
           "strict": top / len(rows) if rows else 0.0, "weighted": tables.score(rows, plan.weights), "window_days": days, "moving_days": 0,
           "pace_per_day": 0.0, "likely": None, "sure": None, "too_far": False, "largest_day_share": 0.0, "short_of_live_share": 0.0, "last_change": None,
           "scope": {"added": 0, "removed": 0, "keeps_growing": False, "per_day": 0.0, "if_it_goes_on": None, "never_catches_up": False},
           "live": _live_line(plan, rows, None, today), "deadline": None, "workstreams": []}
    root, rel = _where(plan)
    shallow = _is_shallow(root)
    pace = None if shallow else read_pace(plan, group=group, days=days, today=today)
    series = None
    if pace is not None:
        out.update(window_days=pace.days, moving_days=pace.moving_days(), pace_per_day=round(pace.per_day(), 3), largest_day_share=round(pace.largest_day_share(), 3),
                   short_of_live_share=round(pace.short_of_live_share(), 3), live=_live_line(plan, rows, pace, today))
        out["scope"].update(added=pace.added, removed=pace.removed, per_day=round(sum(pace.grew) / pace.days, 3))
        if pace.moving_days() >= ENOUGH and pace.per_day() > 1e-9:
            series = pace.moved
    if shallow:
        out["state"] = "shallow"
    elif not rows:
        out["state"] = "no_rows"
    elif not out["left"]:
        out["state"] = "done"
    elif series:
        out.update(state="dated", **_dates(out["left"], series, today))
        if pace.keeps_growing():
            grown = _dates(out["left"], pace.net(), today)
            out["scope"]["keeps_growing"] = True
            out["scope"]["if_it_goes_on"] = {"likely": grown["likely"], "too_far": grown["too_far"]} if grown else None
            out["scope"]["never_catches_up"] = grown is None
    elif pace is not None and (pace.moving_days() >= ENOUGH or (pace.days >= days and not pace.moving_days())):
        out["state"] = "stalled"
    if out["state"] == "stalled":
        out["last_change"] = _last_change(root, rel, today)
    if not group:
        out["workstreams"] = _workstreams(plan, table, series, today)
    born = None
    if plan.deadline and not plan.start and not shallow:
        commits = history.table_commits(root, rel, first_parent=True, today=today)
        born = commits[-1][1] if commits else None
    out["deadline"] = _deadline(plan, out, born, today)
    return out


def _last_change(top, rel, today):
    commits = history.table_commits(top, rel, first_parent=True, today=today)
    return commits[0][1] if commits else None


def _day_words(iso, today):
    day = datetime.date.fromisoformat(iso)
    return chart._date_words(day, day.year != datetime.date.fromisoformat(today).year)


def _rows_words(value):
    return f"{value:.1f}".rstrip("0").rstrip(".") if value % 1 else f"{value:.0f}"


def _pace_words(value):
    if 0 < abs(value) < 0.01:
        return "under 0.01"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _late_words(late):
    return f"{_plural(late, 'day')} late" if late > 0 else (f"{_plural(-late, 'day')} early" if late < 0 else "on the day")


def _deadline_words(found):
    d = found["deadline"]
    when = _day_words(d["date"], found["as_of"])
    if d["days_left"] < 0 and found["left"]:
        return f"Deadline {when}: passed {_plural(-d['days_left'], 'day')} ago, with {_rows_words(found['left'])} rows left."
    if not found["left"]:
        return f"Deadline {when}: nothing left."
    if found["likely"]:
        said = f"likely {_late_words(d['late_by'])}"
        if d["late_by_live"] is not None and d["late_by_live"] != d["late_by"]:
            said += f", or {_late_words(d['late_by_live'])} counting only {render.one_line(found['live']['kind'])} rows"
    else:
        said = f"{_plural(d['days_left'], 'day')} left"
    needs = ""
    if d["needs_per_day"]:
        needs = f" It needs {_pace_words(d['needs_per_day'])} rows a day from here" + (f"; the pace is {_pace_words(found['pace_per_day'])}." if found["moving_days"] else ".")
    return f"Deadline {when}: {said}.{needs}"


def _no_date_words(found):
    days = found["window_days"]
    if found["moving_days"]:
        return f"No date: rows moved on {found['moving_days']} of the last {_plural(days, 'day')}, and went back as far as they came."
    since = f" The table last changed {found['last_change']}." if found["last_change"] else ""
    return f"No date: nothing moved a row in the last {_plural(days, 'day')}.{since}"


def headline(found):
    """The one thing `eta` is asked."""
    state, days = found["state"], found["window_days"]
    if state == "dated":
        if found["too_far"]:
            return f"At the pace of the last {_plural(days, 'day')}, this is more than ten years away. That is a line, not a promise."
        likely = _day_words(found["likely"], found["as_of"])
        condition = " if the scope stops growing" if found["scope"]["keeps_growing"] else ""
        sure = f"85% sure by {_day_words(found['sure'], found['as_of'])}" if found["sure"] else "and the 85% date is more than ten years away"
        return f"Likely done {likely}{condition}, {sure}: a line through the last {_plural(days, 'day')}, not a promise."
    if state == "done":
        rows, strict = found["rows"], found["strict"]
        if strict >= 1:
            return "Nothing left: every row is done."
        return f"Nothing left by the plan's weights, though {_plural(rows - round(strict * rows), 'row')} short of {render.one_line(found['live']['kind'])}."
    if state == "no_rows":
        return "No date: the table has no rows."
    if state == "shallow":
        return "No date: this clone is shallow, so the table's history is cut off. `git fetch --unshallow` brings it back."
    if state == "stalled":
        return _no_date_words(found)
    return f"No date yet: rows moved on {found['moving_days']} of the last {_plural(days, 'day')}, and a line needs {ENOUGH}."


def _live_words(found):
    """The date a reviewer would stand behind, beside the one the weights give."""
    live = found["live"]
    kind = render.one_line(live["kind"])
    if not live["left"]:
        return None
    if live["likely"]:
        sure = f", 85% sure by {_day_words(live['sure'], found['as_of'])}" if live["sure"] else ""
        return f"Counting only {kind} rows: likely {_day_words(live['likely'], found['as_of'])}{sure}."
    if live["too_far"]:
        return f"Counting only {kind} rows: more than ten years away."
    return f"Counting only {kind} rows: no date, with {_plural(live['moving_days'], 'day')} of movement in that time."


def _scope_words(found):
    scope = found["scope"]
    if not scope["added"] and not scope["removed"]:
        return None
    words = f"Scope: {scope['added']} rows added, {scope['removed']} taken out in that time."
    if scope["keeps_growing"]:
        words = (f"Scope: {scope['added']} rows added, {scope['removed']} taken out in that time, or {_pace_words(scope['per_day'])} rows a day "
                 f"against {_pace_words(found['pace_per_day'])} of work.")
        if scope["never_catches_up"]:
            words += " If it goes on like that, the work never catches up."
        elif scope["if_it_goes_on"] and scope["if_it_goes_on"]["likely"]:
            words += f" If it goes on like that: likely {_day_words(scope['if_it_goes_on']['likely'], found['as_of'])}."
    return words


def opener_line(plan, today=None):
    """One line for whoever opens the project; None if there is nothing worth a line yet."""
    found = data(plan, today=today)
    parts = []
    if found["state"] == "dated" and not found["too_far"]:
        condition = " if the scope stops growing" if found["scope"]["keeps_growing"] else ""
        sure = f" (85%: {_day_words(found['sure'], found['as_of'])})" if found["sure"] else ""
        parts.append(f"Likely done {_day_words(found['likely'], found['as_of'])}{sure}{condition}, at the last {_plural(found['window_days'], 'day')}' pace.")
        if found["short_of_live_share"] > 0.5 and found["live"]["left"]:
            parts.append(_live_words(found))
    elif found["state"] in ("dated", "stalled", "shallow"):
        parts.append(headline(found))
    if found["scope"]["never_catches_up"]:
        parts.append("Scope is growing as fast as the work.")
    elif found["scope"]["keeps_growing"]:
        parts.append(f"Scope takes {_pace_words(found['scope']['per_day'])} rows a day of the {_pace_words(found['pace_per_day'])} the work moves.")
    if found["deadline"]:
        parts.append(_deadline_words(found))
    return " ".join(parts) or None


def text(found):
    L = [headline(found)]
    if found["state"] == "dated":
        live = _live_words(found)
        if live:
            L.append(live)
    if found["rows"]:
        L.append(f"Left: {_rows_words(found['left'])} of {found['rows']} rows (weighted {render.pct(found['weighted'])}, strict {render.pct(found['strict'])}).")
    if found["state"] not in ("shallow",) and found["moving_days"]:
        words = f"Pace: {_pace_words(found['pace_per_day'])} rows a day; rows moved on {found['moving_days']} of {_plural(found['window_days'], 'day')}."
        if found["short_of_live_share"] > 0.5 and found["state"] == "dated":
            words += f" {render.pct(found['short_of_live_share'])} of that stopped short of {render.one_line(found['live']['kind'])}, which only a note holds up."
        L.append(words)
    if found["state"] == "dated" and found["largest_day_share"] > 0.5:
        L.append(f"One day made {render.pct(found['largest_day_share'])} of that, so read the date loosely.")
    scope = _scope_words(found)
    if scope:
        L.append(scope)
    d = found["deadline"]
    if d:
        L.append(_deadline_words(found))
        L.append(f"  Work {render.bar(found['weighted'])} {render.pct(found['weighted'])}")
        L.append(f"  Time {render.bar(d['time_used'])} {render.pct(d['time_used'])}, {_day_words(d['start'], found['as_of'])} to {_day_words(d['date'], found['as_of'])}")
    if any(w["left"] for w in found["workstreams"]):
        L += ["", "In the plan's order:"]
        names = [render.one_line(f"{w['id'] or ''} {w['name']}") for w in found["workstreams"]]
        width = max(len(name) for name in names)
        for name, w in zip(names, found["workstreams"]):
            if not w["rows"]:
                when = "no rows"
            elif not w["left"]:
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
    change = (datetime.date.fromisoformat(now["likely"]) - datetime.date.fromisoformat(then["likely"])).days
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
    before = _kinds(plan, then.out)
    if before is None:
        return None
    table = tables.load_clean(plan)
    now = {r.num: r.kind for d in table.domains for r in d.rows}
    added, removed = sorted(now.keys() - before.keys()), sorted(before.keys() - now.keys())
    if not added and not removed:
        return None
    pace = read_pace(plan, today=today)
    moved = None
    if pace is not None and pace.moving_days() >= ENOUGH:
        weights = plan.weights
        moved = _moved_words(sum(1 - weights.get(k, 0.0) for k in before.values()), sum(1 - weights.get(k, 0.0) for k in now.values()), pace.moved, today)
    return {"added": added, "removed": removed, "date_moved": moved}
