"""`week`: what moved since a date, read from the status table's git history. Writes nothing."""
import datetime
import os
import re

from . import gitio, render, table as tables
from .plan import PlanError
from .table import counts, score

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPAN = re.compile(r"^(\d+)\s*(d|day|w|week|m|month)s?(\s+ago)?$")
DAYS = {"d": 1, "day": 1, "w": 7, "week": 7, "m": 30, "month": 30}
UNIT = {"d": "day", "day": "day", "w": "week", "week": "week", "m": "month", "month": "month"}


def _is_a_day(text):
    if not DATE.match(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def table_commits(top, rel, first_parent=False, today=None, forward=True, topological=False):
    """(commit, date, the table's path then), newest first, following a rename and stopping where a copy began: a table copied from another
    project's has not lived that project's life. `topological` puts no commit after one it came from, whatever the clocks said.

    A date is when the commit was written, by the author's clock, which survives a rebase. A date past today is a wrong clock: the committer's is used instead,
    and with both wrong the commit has no date of its own, so that it cannot carry every commit after it along. `forward` makes the dates run in history's order, for
    what asks how the table stood on a day; without it each commit keeps its own, for what asks when the work was done.
    """
    if gitio.git(top, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").code:
        return []
    args = (["--first-parent", "-m"] if first_parent else []) + (["--topo-order"] if topological else [])
    done = gitio.git(top, "log", *args, "--follow", "-z", "--name-status", "--format=%x01%H %as %cs", "--", rel, timeout=60)
    if done.code:
        raise PlanError(f"git could not read the history of {rel}: {done.err.strip()[:200]}")
    today = today or datetime.date.today()
    latest = today.isoformat()
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()  # the author's clock may simply be east of this one
    out, tokens, at = [], done.out.split("\0"), 0
    while at < len(tokens):
        head = tokens[at].lstrip("\n")
        at += 1
        if not head.startswith("\x01"):
            continue
        fields = head[1:].split()
        if at < len(tokens) and tokens[at].lstrip("\n")[:1] in ("A", "M", "D", "T", "R", "C"):
            status = tokens[at].lstrip("\n")
            two_names = status[0] in "RC"
            source = tokens[at + 1] if at + 1 < len(tokens) else rel
            path = tokens[at + 2 if two_names else at + 1] if at + (2 if two_names else 1) < len(tokens) else rel
            at += 3 if two_names else 2
        else:
            status, source, path = "", rel, out[-1][2] if out else rel
        date = next((d for d in fields[1:] if _is_a_day(d) and d <= tomorrow), "")
        out.append((fields[0], min(date, latest) if date else "", path))
        if status.startswith("C") and gitio.git(top, "cat-file", "-e", f"HEAD:{source}").code == 0:
            break  # copied from a table that still lives its own life. One moved in two steps has none left, and this one goes on
    dated = forward_dates(out)
    known = next((entry[1] for entry in reversed(dated) if entry[1]), latest)
    dated = [(sha, date or known, path) for sha, date, path in dated]
    return dated if forward else [(sha, raw or kept, path) for (sha, raw, path), (_, kept, _) in zip(out, dated)]


def table_text_at(top, rel, commits, commit):
    """The table as a commit held it. A commit that deleted it holds the last state before that, and one from before a rename holds it under its old name."""
    done = gitio.git(top, "show", f"{commit}:{rel}")
    if done.code == 0:
        return done.out
    paths = {path for _, _, path in commits}
    for path in sorted(paths):
        done = gitio.git(top, "show", f"{commit}:{path}")
        if done.code == 0:
            return done.out
    older = False
    for sha, _, path in commits:
        if older or sha == commit:
            older = True
            done = gitio.git(top, "show", f"{sha}:{path}")
            if done.code == 0:
                return done.out
    return None


def forward_dates(commits):
    """(commit, date, ...) newest first. A commit authored early and landed late counts from when it landed: an author date
    survives a rebase, which is why it is read at all, but history's order is the truth about what came after what.
    """
    latest, fresh = "", []
    for entry in reversed(commits):
        latest = max(latest, entry[1])
        fresh.append((entry[0], latest, *entry[2:]))
    fresh.reverse()
    return fresh


def _cutoff(since, today):
    if DATE.match(since):
        return since
    span = SPAN.match(since)
    if not span:
        raise PlanError(f"week: {since!r} is not a date (2026-01-31), a span (2 weeks, 7d) or a commit")
    return (today - datetime.timedelta(days=int(span.group(1)) * DAYS[span.group(2)])).isoformat()


def _base_commit(top, commits, since, today):
    """(commit, words saying where it came from) for a commit, a date or a span; the commit is None if nothing is older."""
    done = gitio.git(top, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    if done.code == 0:
        return done.out.strip(), since[:7]
    cutoff = _cutoff(since, today)
    span = SPAN.match(since)
    words = since
    if span:
        count = int(span.group(1))
        words = f"{count} {UNIT[span.group(2)]}{'s' if count != 1 else ''} ago"
    for commit, date, _ in commits:
        if date < cutoff:
            return commit, words
    return None, words


def delta_data(plan, since=None, today=None):
    """What moved since a date or commit, as data; `delta` puts it in words."""
    doc = plan.doc
    top_done = gitio.git(doc.parent, "rev-parse", "--show-toplevel")
    if top_done.code:
        raise PlanError(f"{doc.name} is not in a git repository, so it has no history to compare")
    top = top_done.out.strip()
    rel = os.path.relpath(os.path.realpath(doc), os.path.realpath(top)).replace(os.sep, "/")
    commits = table_commits(top, rel)
    if not commits:
        raise PlanError(f"{doc.name} has no commit yet, so it has no history to compare")
    today = today or datetime.date.today()
    since = since or (today - datetime.timedelta(days=7)).isoformat()
    base, words = _base_commit(top, commits, since, today)
    older = base is not None
    if not older:
        base = commits[-1][0]
    known = {sha: (date, path) for sha, date, path in commits}
    stamp = known[base][0] if base in known else gitio.git(top, "log", "-1", "--format=%as", base).out.strip()
    then_text = table_text_at(top, rel, commits, base)
    if then_text is None:
        raise PlanError(f"week: {rel} is not in commit {base[:7]}")
    then = tables.parse(then_text, plan.kinds)
    now = tables.load_clean(plan)
    moved = _moved(then, now)
    went, stayed = _workstreams(plan, moved)
    removed = sorted(set(then.rows) - set(now.rows))
    return {
        "since": words,
        "base": base[:7],
        "base_date": stamp,
        "older_commit_found": older,
        "groups": [_percentages(plan, g, then, now) for g in plan.effective_groups(now)],
        "moved": [{"row": n, "from": moved[n][0], "to": moved[n][1]} for n in sorted(moved)],
        "workstreams_moved": went,
        "workstreams_not_moved": stayed,
        "new_rows": sorted(set(now.rows) - set(then.rows)),
        "renamed": [{"row": n, "from": then.rows[n].name, "to": now.rows[n].name} for n in sorted(set(now.rows) & set(then.rows))
                    if then.rows[n].name and now.rows[n].name and then.rows[n].name != now.rows[n].name],
        "removed": [{"row": n, "was": then.rows[n].kind or then.rows[n].status} for n in removed],
        "uncommitted_changes": bool(gitio.git(top, "status", "--porcelain", "--", rel).out.strip()),
        "focus": _focus_since(plan, since, today),
    }


def _focus_since(plan, since, today):
    """Where the commits went in the same span. A plan's code may live elsewhere, and that must not cost this line its other words."""
    from . import focus
    try:
        if DATE.match(since) or SPAN.match(since):
            days = (today - datetime.date.fromisoformat(_cutoff(since, today))).days + 1
            found = focus.data(plan, days=max(days, 1), today=today)
        else:
            found = focus.data(plan, revisions=f"{since}..HEAD", today=today)
    except Exception:
        return None
    return {key: found[key] for key in ("commits", "on_plan", "unclear", "upkeep", "off_plan", "newest_only")}


def delta(plan, since=None, today=None):
    """One line: the percentages then and now, the rows that moved, the workstreams that did and did not."""
    d = delta_data(plan, since=since, today=today)
    head = f"Since {d['since']}" if d["older_commit_found"] else f"No commit of the table before {d['since']}; since its first commit"
    line = f"{head} ({d['base']}, {d['base_date']}): " + "; ".join(_group_words(g) for g in d["groups"]) + ". "
    line += _moved_words(d["moved"]) + _workstream_words(d["workstreams_moved"], d["workstreams_not_moved"])
    if d["new_rows"]:
        line += f" {len(d['new_rows'])} rows are new since then."
    if d["renamed"]:
        line += " Renamed: " + ", ".join(f"{r['row']} ({r['from']} → {r['to']})" for r in d["renamed"]) + "."
    if d["removed"]:
        line += " Removed: " + ", ".join(f"{r['row']} (was {r['was']})" for r in d["removed"]) + "."
    if d["uncommitted_changes"]:
        line += " The table has uncommitted changes, counted here."
    if d["focus"]:
        from . import focus
        words = focus.counts_words(d["focus"])
        line += f" {words}" if words else ""
    return line


def _percentages(plan, group, then, now):
    wanted = set(group.domains)
    old = [r for d in then.domains if d.n in wanted for r in d.rows]
    new = tables.group_rows(now, group)
    top = plan.strict_kind.name
    old_top, new_top = counts(old, plan.kind_names)[top], counts(new, plan.kind_names)[top]
    return {
        "label": group.label,
        "rows": len(new),
        "strict_rows_then": old_top,
        "strict_rows_now": new_top,
        "strict_then": old_top / len(old) if old else 0.0,
        "strict_now": new_top / len(new) if new else 0.0,
        "weighted_then": score(old, plan.weights),
        "weighted_now": score(new, plan.weights),
    }


def _group_words(g):
    return (f"{render.one_line(g['label'])} strict {g['strict_rows_then']}→{g['strict_rows_now']} of {g['rows']} "
            f"({render.pct(g['strict_then'])}→{render.pct(g['strict_now'])}), "
            f"weighted {render.pct(g['weighted_then'])}→{render.pct(g['weighted_now'])}")


def _moved(then, now):
    moved = {}
    for num, row in now.rows.items():
        old = then.rows.get(num)
        if old is not None and (old.kind or old.status) != row.kind:
            moved[num] = (old.kind or old.status, row.kind)
    return moved


def _moved_words(moved):
    if not moved:
        return "Moved: nothing."
    paths = {}
    for item in moved:
        paths.setdefault((item["from"], item["to"]), []).append(str(item["row"]))
    return "Moved: " + "; ".join(f"{', '.join(nums)} {a}→{b}" for (a, b), nums in paths.items()) + "."


def _workstreams(plan, moved):
    went, stayed = [], []
    for ws_id in plan.order:
        rows = render.workstream_rows_numbers(plan.workstream(ws_id))
        (went if any(n in moved for n in rows) else stayed).append(ws_id)
    return went, stayed


def _workstream_words(went, stayed):
    words = []
    if went:
        words.append("workstreams moved: " + render.one_line(", ".join(went)))
    if stayed:
        words.append("not moved: " + render.one_line(", ".join(stayed)))
    if not words:
        return ""
    return " " + words[0][0].upper() + "; ".join(words)[1:] + "."
