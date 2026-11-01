"""`eta`: when the rows will be done if the work goes on as it has. A line through the status table's git history, and it says so.

The pace is what moved existing rows toward done, per calendar day. A day when nothing moved counts, because the time passed. A row added
or taken out is scope and not pace: it changes what is left, and so the date, which is the point of having one. The range comes from the
pace's own spread by a closed form, so the same history on the same day gives the same words, and no random number is involved.

Two lines are drawn, as the percent has strict and weighted: one through rows reaching the strict kind, which git holds to a commit on the default branch,
and one through everything the weights credit.

Nothing here reaches the view: it changes with the day, and the gate compares the view byte for byte.
"""
import datetime
import math
import os

from . import chart, evidence, gitio, history, render, table as tables
from .plan import PlanError

WINDOW = 28
ENOUGH = 3  # days with movement before a line is drawn through them
SURE = 1.0364  # the 85th percentile of a normal curve, in spreads from its middle
TOO_FAR = 3650
MOST_DAYS = 36500
STATES_BEFORE_THE_WINDOW = 5  # enough to find one the table could be read in


def _where(plan):
    top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top.code:
        raise PlanError(f"{plan.doc.name} is not in a git repository, so it has no history to read a pace from")
    root = top.out.strip()
    return root, os.path.relpath(os.path.realpath(plan.doc), os.path.realpath(root)).replace(os.sep, "/")


def _is_shallow(top):
    return gitio.git(top, "rev-parse", "--is-shallow-repository").out.strip() == "true"


def _kinds(plan, text, wanted=None):
    """({row: kind}, whether the table has problems) of a table as it stood. A status the plan no longer has is None: unknown, which is not the same as nothing done."""
    table = tables.parse(text.replace("\r\n", "\n"), plan.kinds)
    return {r.num: r.kind for d in table.domains if wanted is None or d.n in wanted for r in d.rows}, bool(table.problems)


def _left(plan, rows):
    return round(sum(1 - plan.credit.get(r.kind, 0.0) for r in rows), 6)


def table_steps(plan, start=None, today=None, wanted=None):
    """(steps, born, read_from). A step is (commit, date, rows before, rows after), oldest first, on the main line of this branch, from `start` on. `born` is the
    table's first day, and None if it has no commit. `read_from` is the first day it could be read from, when there was too much of it to read, and None otherwise.

    What is in the window is decided by when each commit was written, so a rebase, which rewrites only when a commit was made, moves nothing.
    """
    top, rel = _where(plan)
    today = today or datetime.date.today()
    commits = list(reversed(history.table_commits(top, rel, first_parent=True, today=today, forward=False)))
    if not commits:
        return [], None, None
    born, read_from = commits[0][1], None
    from_day = start.isoformat() if start is not None else ""
    first = next((i for i, c in enumerate(commits) if c[1] >= from_day), len(commits))
    read = commits[max(first - STATES_BEFORE_THE_WINDOW, 0):]
    fits = gitio.fitting(top, [f"{sha}:{path}" for sha, _, path in reversed(read)], gitio.MOST_BYTES_OF_HISTORY)
    if fits < len(read):  # more text than a signal should read: the newest of it
        read = read[len(read) - fits:]
        read_from = read[0][1] if read else today.isoformat()

    def stop(words):
        raise PlanError(f"git could not read the table's history: {words.strip()[:200]}")
    texts = gitio.blobs(top, [f"{sha}:{path}" for sha, _, path in read], failed=stop)
    before, steps, reached, strict = None, [], [], plan.strict_kind.name
    for (sha, date, _), text in zip(read, texts):
        if text is None:
            continue
        after, troubled = _kinds(plan, text, wanted)
        if not after or (troubled and before is not None and len(after) < len(before)):
            continue  # a table that lost rows to a broken line says nothing about them. One that still has them, with a typo or an old status, still says the rest
        if before is not None and date >= from_day and date > born:  # on its first day a table is still saying where the project stands
            steps.append((sha, date, before, after))
            nums = [n for n in after.keys() & before.keys() if after[n] == strict and before[n] != strict]
            if nums:
                reached.append((len(steps) - 1, nums, text))
        before = after
    return _old_work_set_aside(plan, top, steps, reached, born), born, read_from


def _old_work_set_aside(plan, top, steps, reached, born):
    """A row that reaches the strict kind on commits from before the table began was done already. Saying so is where the project stood, and not how fast it moves, and a project
    brought under a tracker a row at a time would otherwise get a date from its own bookkeeping.
    """
    cited = {}
    for at, nums, text in reached:
        rows = tables.parse(text.replace("\r\n", "\n"), plan.kinds).rows
        for num in nums:
            commits = [str(claim.value) for claim in evidence.release_claims(plan, rows[num].words()) if claim.kind in ("sha", "bare")]
            if commits:
                cited[(at, num)] = commits
    if not cited:
        return steps
    wanted = sorted({commit for commits in cited.values() for commit in commits})
    dates = {line[:7]: line.split()[-1] for line in gitio.git(top, "log", "--no-walk", "--ignore-missing", "--format=%H %as", "--stdin", stdin_text="\n".join(wanted) + "\n", timeout=60).out.splitlines()}
    for (at, num), commits in cited.items():
        if all(dates.get(commit[:7], born) < born for commit in commits):
            sha, date, before, after = steps[at]
            steps[at] = (sha, date, {**before, num: after[num]}, after)
    return steps


class Pace:
    """What a window of days held: per day, what moved rows toward done, what of that reached the strict kind, and what scope added to what is left."""

    def __init__(self, plan, today, days):
        self.plan = plan
        self.today = today
        self.days = days
        self.moved = [0.0] * days
        self.live = [0.0] * days  # rows reaching the strict kind, less rows leaving it
        self.grew = [0.0] * days
        self.added = self.removed = 0
        self.newest_only = False

    def _take(self, offset, before, after):
        weights, top = self.plan.credit, self.plan.strict_kind.name
        new, gone = after.keys() - before.keys(), before.keys() - after.keys()
        for n in after.keys() & before.keys():
            was, now = before[n], after[n]
            if was is None or now is None or was == now:
                continue
            self.moved[offset] += weights.get(now, 0.0) - weights.get(was, 0.0)
            self.live[offset] += (now == top) - (was == top)
        self.grew[offset] += sum(1 - weights.get(after[n], 0.0) for n in new) - sum(1 - weights.get(before[n], 0.0) for n in gone)
        self.added += len(new)
        self.removed += len(gone)

    def moving_days(self):
        return sum(1 for x, y in zip(self.moved, self.live) if abs(x) > 1e-9 or y)

    def only_backwards(self):
        return self.moving_days() > 0 and not any(x > 1e-9 for x in self.moved) and not any(y > 0 for y in self.live)

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

def read_pace(plan, group=None, days=WINDOW, today=None):
    """The pace over the last `days` days, or over the table's life if that is shorter. None if the table has no commit at all, or this clone has lost its history."""
    if _is_shallow(_where(plan)[0]):
        return None
    today = today or datetime.date.today()
    wanted = set(plan.group(group).domains) if group else None
    start = today - datetime.timedelta(days=days - 1)
    steps, born, read_from = table_steps(plan, start, today, wanted)
    if born is None:
        return None
    start = max(start, datetime.date.fromisoformat(read_from or born))
    pace = Pace(plan, today, (today - start).days + 1)
    pace.newest_only = read_from is not None
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
    known = plan.start or born
    began = min(datetime.date.fromisoformat(known), day) if known else None
    whole = (day - began).days if began else 0
    days_left = (day - today).days

    def needs(left):
        return round(left / days_left, 3) if days_left > 0 and left else None

    def late(iso):
        return (datetime.date.fromisoformat(iso) - day).days if iso else None
    used = None if not began else (1.0 if whole <= 0 else min(max((today - began).days / whole, 0.0), 1.0))
    return {"date": plan.deadline, "start": began.isoformat() if began else None, "days_left": days_left, "time_used": used,
            "needs_per_day": needs(found["left"]), "needs_per_day_live": needs(found["live"]["left"]), "late_by": late(found["likely"]), "late_by_if_sure": late(found["sure"]),
            "late_by_live": late(found["live"]["likely"])}


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
    if not 1 <= days <= MOST_DAYS:
        raise PlanError(f"eta: the window must be from 1 to {MOST_DAYS} days")
    today = today or datetime.date.today()
    table = tables.load_clean(plan)
    wanted = set(plan.group(group).domains) if group else None
    rows = [r for d in table.domains if wanted is None or d.n in wanted for r in d.rows]
    top = sum(1 for r in rows if r.kind == plan.strict_kind.name)
    out = {"state": "too_little", "as_of": today.isoformat(), "rows": len(rows), "left": _left(plan, rows),
           "strict": top / len(rows) if rows else 0.0, "weighted": tables.score(rows, plan.weights), "window_days": days, "moving_days": 0,
           "pace_per_day": 0.0, "likely": None, "sure": None, "too_far": False, "largest_day_share": 0.0, "only_backwards": False, "last_change": None, "plan_problems": list(plan.signal_problems),
           "scope": {"added": 0, "removed": 0, "keeps_growing": False, "per_day": 0.0, "never_catches_up": False},
           "live": _live_line(plan, rows, None, today), "deadline": None, "workstreams": [], "all_groups": bool(plan.groups) and not group, "newest_only": False}
    root, rel = _where(plan)
    shallow = _is_shallow(root)
    pace = read_pace(plan, group=group, days=days, today=today)
    series = None
    if pace is not None:
        out.update(window_days=pace.days, moving_days=pace.moving_days(), pace_per_day=round(pace.per_day(), 3), largest_day_share=round(pace.largest_day_share(), 3),
                   only_backwards=pace.only_backwards(), live=_live_line(plan, rows, pace, today), newest_only=pace.newest_only)
        out["scope"].update(added=pace.added, removed=pace.removed, per_day=round(sum(pace.grew) / pace.days, 3))
        if sum(1 for x in pace.moved if abs(x) > 1e-9) >= ENOUGH and pace.per_day() > 1e-9:
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
            out["scope"]["keeps_growing"] = True
            out["scope"]["never_catches_up"] = sum(pace.net()) <= 1e-9
    elif out["live"]["likely"] or out["live"]["too_far"]:
        out["state"] = "dated"  # kinds of equal weight: nothing moved by the weights, and rows still reached the strict kind
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


def _kind(found):
    return render.one_line(found["live"]["kind"])


def _deadline_words(found, short=False):
    d = found["deadline"]
    when = _day_words(d["date"], found["as_of"]) + (", all groups" if found.get("all_groups") else "")
    if d["days_left"] < 0 and found["left"]:
        return f"Deadline {when}: passed {_plural(-d['days_left'], 'day')} ago, with {_rows_words(found['left'])} rows left."
    if not found["left"]:
        return f"Deadline {when}: nothing left."
    kind = _kind(found)
    if d["late_by_live"] is not None and d["late_by"] is not None and d["late_by_live"] != d["late_by"]:
        said = f"{_late_words(d['late_by_live'])} on {kind} rows alone, {_late_words(d['late_by'])} with all work"
    elif d["late_by"] is not None:
        said = f"likely {_late_words(d['late_by'])}"
    else:
        said = f"{_plural(d['days_left'], 'day')} left"
    if short or not d["needs_per_day"]:
        return f"Deadline {when}: {said}."
    live = f"{_pace_words(d['needs_per_day_live'])} {kind} rows a day, or " if d["needs_per_day_live"] and d["needs_per_day_live"] != d["needs_per_day"] else ""
    return f"Deadline {when}: {said}. It needs {live}{_pace_words(d['needs_per_day'])} of all work from here."


def _both_dates(found):
    """The two answers side by side, each labelled, as the percent gives strict and weighted."""
    kind = _kind(found)
    live, likely = found["live"]["likely"], found["likely"]
    if live and not likely:
        return f"{_day_words(live, found['as_of'])} on {kind} rows alone"
    if live and live != likely:
        return f"{_day_words(live, found['as_of'])} on {kind} rows alone, or {_day_words(likely, found['as_of'])} with all work"
    if live:
        return _day_words(likely, found["as_of"])
    return f"{_day_words(likely, found['as_of'])} with all work, and {kind} rows alone give no date yet"


def _likely_done(found):
    """A date is of what it says it is."""
    return "All groups: likely done" if found.get("all_groups") else "Likely done"


def headline(found):
    """The one thing `eta` is asked."""
    state, days = found["state"], found["window_days"]
    if state == "dated":
        if found["too_far"] or (found["live"]["too_far"] and not found["likely"]):
            return f"At the pace of the last {_plural(days, 'day')}, this is more than ten years away. That is a line, not a promise."
        condition = " if the scope stops growing" if found["scope"]["keeps_growing"] else ""
        return f"{_likely_done(found)} {_both_dates(found)}{condition}: a line through the last {_plural(days, 'day')}, not a promise."
    if state == "done":
        rows, strict = found["rows"], found["strict"]
        if strict >= 1:
            return "Nothing left: every row is done."
        return f"Nothing left by the plan's weights, though {_plural(rows - round(strict * rows), 'row')} short of {_kind(found)}."
    if state == "no_rows":
        return "No date: the table has no rows."
    if state == "shallow":
        return "No date: this clone is shallow, so the table's history is cut off. `git fetch --unshallow` brings it back."
    if state == "stalled":
        if found["only_backwards"]:
            return f"No date: rows moved on {found['moving_days']} of the last {_plural(days, 'day')}, and only backwards."
        if found["moving_days"]:
            return f"No date: rows moved on {found['moving_days']} of the last {_plural(days, 'day')}, and went back as far as they came."
        since = f" The table last changed {found['last_change']}." if found["last_change"] else ""
        return f"No date: nothing moved a row in the last {_plural(days, 'day')}.{since}"
    return f"No date yet: rows moved on {found['moving_days']} of the last {_plural(days, 'day')}, and a line needs {ENOUGH}."


def _no_live_date(found):
    live = found["live"]
    if live["too_far"]:
        return "more than ten years away"
    days = found["window_days"]
    if live["moving_days"] >= ENOUGH:
        return f"no date: they went back as far as they came in the last {_plural(days, 'day')}"
    return f"no date: they moved on {live['moving_days']} of the last {_plural(days, 'day')}, and a line needs {ENOUGH}"


def _date_table(found):
    """What the headline rests on: for each line, its dates, what it has left, and how fast it moves, so that each can be checked by hand."""
    def day(iso):
        return _day_words(iso, found["as_of"]) if iso else "past ten years"
    live, kind = found["live"], _kind(found)
    same = live["likely"] == found["likely"] and live["sure"] == found["sure"] and live["left"] == found["left"]
    rows = []
    if live["left"]:
        if live["likely"]:
            rows.append((f"{kind} rows" if same else f"{kind} alone", day(live["likely"]), day(live["sure"]), f"{_rows_words(live['left'])} rows", _pace_words(live["pace_per_day"])))
        else:
            rows.append((f"{kind} alone", _no_live_date(found), None, None, None))
    if not same:
        if found["likely"]:
            rows.append(("All work", day(found["likely"]), day(found["sure"]), f"{_rows_words(found['left'])} rows", _pace_words(found["pace_per_day"])))
        else:
            rows.append(("All work", "no date: nothing moved by the weights", None, None, None))
    heads = ("", "Likely", "85% sure", "Left", "A day")
    full = [r for r in rows if r[2] is not None]
    widths = [max([len(r[i]) for r in full] + [len(head)]) for i, head in enumerate(heads)]
    widths[0] = max(len(r[0]) for r in rows)
    L = ["  " + "  ".join(head.ljust(width) for head, width in zip(heads, widths)).rstrip()] if full else []
    for r in rows:
        if r[2] is None:
            L.append(f"  {r[0].ljust(widths[0])}  {r[1]}")
        else:
            L.append("  " + "  ".join(cell.ljust(width) for cell, width in zip(r, widths)).rstrip())
    return L


def _scope_words(found):
    scope = found["scope"]
    if not scope["added"] and not scope["removed"]:
        return None
    words = f"Scope: {scope['added']} rows added, {scope['removed']} taken out in that time."
    if scope["keeps_growing"]:
        words = (f"Scope: {scope['added']} rows added, {scope['removed']} taken out in that time, or {_pace_words(scope['per_day'])} rows a day "
                 f"against {_pace_words(found['pace_per_day'])} of work.")
        words += " If it goes on like that, the work never catches up." if scope["never_catches_up"] else " The dates assume it stops."
    return words


def opener_line(plan, today=None):
    """One line for whoever opens the project; None if there is nothing worth a line yet."""
    found = data(plan, today=today)
    parts = []
    if found["state"] == "dated" and (found["likely"] or found["live"]["likely"]):
        parts.append(f"{_likely_done(found)} {_both_dates(found)}, at the last {_plural(found['window_days'], 'day')}' pace.")
    elif found["state"] in ("dated", "stalled", "shallow"):
        parts.append(headline(found))
    if found["scope"]["never_catches_up"]:
        parts.append("Scope is growing as fast as the work.")
    elif found["scope"]["keeps_growing"]:
        parts.append(f"Scope takes {_pace_words(found['scope']['per_day'])} rows a day of the {_pace_words(found['pace_per_day'])} the work moves, and that date assumes it stops.")
    if found["deadline"]:
        parts.append(_deadline_words(found, short=True))
    return " ".join(parts) or None


def text(found):
    L = [headline(found)]
    if found["state"] == "dated" and (found["likely"] or found["live"]["likely"]):
        L += [""] + _date_table(found) + [""]
    if found["rows"]:
        L.append(f"Scope now{', all groups' if found.get('all_groups') else ''}: {_plural(found['rows'], 'row')}, strict {render.pct(found['strict'])}, weighted {render.pct(found['weighted'])}.")
    if found["state"] != "shallow" and found["moving_days"]:
        words = f"Rows moved on {found['moving_days']} of {_plural(found['window_days'], 'day')}."
        if found["state"] == "dated":
            if found["largest_day_share"] > 0.5:
                words += f" One day made {render.pct(found['largest_day_share'])} of it, so read the dates loosely."
        L.append(words)
    scope = _scope_words(found)
    if scope:
        L.append(scope)
    d = found["deadline"]
    if d:
        L.append(_deadline_words(found))
        L.append(f"  {_kind(found)[:4]:<4} {render.bar(found['strict'])} {render.pct(found['strict'])}")
        L.append(f"  Work {render.bar(found['weighted'])} {render.pct(found['weighted'])}")
        if d["time_used"] is not None:
            L.append(f"  Time {render.bar(d['time_used'])} {render.pct(d['time_used'])}, {_day_words(d['start'], found['as_of'])} to {_day_words(d['date'], found['as_of'])}")
    if any(w["left"] for w in found["workstreams"]):
        L += ["", "In the plan's order, with all work:"]
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
    L += [chart.TOO_MUCH_HISTORY] if found["newest_only"] else []
    L += [f"⚠ {render.one_line(words)}" for words in found["plan_problems"]]
    return "\n".join(L)


def left_now(plan):
    """(what is left with all work, what is left on the strict kind alone)."""
    table = tables.load_clean(plan)
    rows = [r for d in table.domains for r in d.rows]
    return _left(plan, rows), sum(1 for r in rows if r.kind != plan.strict_kind.name)


def _shift(before, after, series, today):
    """(from, to, days) of the likely date when what is left changes, or None if there is no date for it to move."""
    then, now = _dates(max(before, 0.0), series, today), _dates(max(after, 0.0), series, today)
    if not then or not now or not then["likely"] or not now["likely"] or then["likely"] == now["likely"]:
        return None
    return then["likely"], now["likely"], (datetime.date.fromisoformat(now["likely"]) - datetime.date.fromisoformat(then["likely"])).days


def _moved_words(before, after, pace, today, kind):
    """What a change in what is left does to the likely dates; None if there is no date for it to move."""
    def said(shift):
        return f"{shift[2]:+d} days, {_day_words(shift[0], today.isoformat())} to {_day_words(shift[1], today.isoformat())}"
    work = _shift(before[0], after[0], pace.moved, today) if pace.moving_days() >= ENOUGH and pace.per_day() > 1e-9 else None
    live = _shift(before[1], after[1], pace.live, today) if pace.live_days() >= ENOUGH and sum(pace.live) > 0 else None
    if not work and not live:
        return None
    parts = ([f"on {render.one_line(kind)} rows alone, {said(live)}"] if live else []) + ([f"with all work, {said(work)}"] if work else [])
    return "That moves the likely date " + ", and ".join(parts) + "."


def shift_words(plan, before, today=None):
    """What `add` or `remove` just did to the date. The pace comes from what is committed, so it is the same before and after."""
    today = today or datetime.date.today()
    pace = read_pace(plan, today=today)
    if pace is None:
        return None
    return _moved_words(before, left_now(plan), pace, today, plan.strict_kind.name)


def against(plan, base, today=None):
    """What a change did to the scope, against a base commit: for a reviewer, who is deciding whether a feature is worth its days."""
    today = today or datetime.date.today()
    top, rel = _where(plan)
    then = history.table_text_at(top, rel, history.table_commits(top, rel, first_parent=True, today=today), base)
    if then is None:
        return None
    before = _kinds(plan, then)[0]
    if not before:
        return None
    table = tables.load_clean(plan)
    now = {r.num: r.kind for d in table.domains for r in d.rows}
    added, removed = sorted(now.keys() - before.keys()), sorted(before.keys() - now.keys())
    if not added and not removed:
        return None
    pace = read_pace(plan, today=today)
    moved = None
    if pace is not None:
        weights, strict = plan.credit, plan.strict_kind.name

        def left(kinds):
            return sum(1 - weights.get(k, 0.0) for k in kinds.values()), sum(k != strict for k in kinds.values())
        moved = _moved_words(left(before), left(now), pace, today, strict)
    return {"added": added, "removed": removed, "date_moved": moved}
