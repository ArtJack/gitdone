"""`focus`: where the commits went. Each one advanced a row, kept the project running, or did neither, and that last kind is how one month
becomes three. It is a signal and never a gate: the commit has already happened, and it may have been right. Saying so lets the scope
change on purpose: `gitdone add` makes the work part of the plan, and the date moves.

What ties a commit to a row, strongest first: the message names it (`row 12`), a row cites the commit as evidence, the commit moved the row
in the table, the plan ties the commit's files to the row, or the subject shares the row's words. Every answer says which.
"""
import datetime
import fnmatch
import os
import re

from . import evidence, forecast, gitio, render, table as tables
from .discover import POINTER
from .plan import PlanError, numbers

WINDOW = 14
NEXT_ROWS = 5
ON, UPKEEP, OFF, TRACKER = "on plan", "upkeep", "off plan", "tracker"
ROW_WORDS = re.compile(r"\brows?[\s:#_-]*#?(\d{1,9}(?:\s*(?:,|&|\band\b|-|–|\bto\b)\s*#?\d{1,9})*)", re.I)
ROW_ITEM = re.compile(r"(\d{1,9})(?:\s*(?:-|–|\bto\b)\s*(\d{1,9}))?", re.I)
PULL_REQUEST = re.compile(r"(?:\(#|pull request #)(\d{1,9})\b", re.I)
MERGE_REQUEST = re.compile(r"See merge request \S*!(\d{1,9})\b")
UPKEEP_SUBJECT = re.compile(r"^(?:fix|chore|docs?|tests?|ci|build|style|revert|deps)(?:\([^)]*\))?!?:|^(?:revert|bump)\b", re.I)
TESTS = ("tests/*", "test/*", "spec/*", "specs/*", "__tests__/*", "*/tests/*", "*/test/*", "*/spec/*", "*/__tests__/*", "test_*", "*/test_*",
         "*_test.*", "*.test.*", "*.spec.*")
UPKEEP_FILES = TESTS + ("docs/*", "doc/*", "*.md", "*.rst", ".github/*", ".gitlab-ci.yml", ".gitignore", ".gitattributes", ".editorconfig",
                        ".pre-commit-config.yaml", "LICENSE*", "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum")
SOURCE_ROOTS = {"src", "lib", "app", "apps", "pkg", "packages", "services", "internal", "cmd"}
FEW_WORDS = frozenset("a an and are as at be by for from in into is it its of on or that the this to with add adds added adding update updates "
                      "updated updating fix fixes fixed fixing make makes made making use uses used using change changes changed changing "
                      "remove removes removed removing new more less first row rows work works feat feature chore docs test tests refactor".split())


def matches(path, patterns):
    """A file against a plan's patterns. `*` crosses folders, and a bare folder name stands for all it holds."""
    return any(fnmatch.fnmatchcase(path, p) or path.startswith(p.rstrip("/") + "/") for p in patterns)


def words_of(text):
    """The words of a name or a subject that could tell one piece of work from another."""
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) >= 3 and word not in FEW_WORDS:
            found.add(word[:-1] if len(word) > 4 and word.endswith("s") else word)
    return found


def named_rows(message, known):
    """The rows a commit message names: `row 12`, `Row: 12`, `rows 12, 13`, `rows 7-9`, or a branch `row-12` in a merge's subject."""
    out = set()
    for match in ROW_WORDS.finditer(message):
        for low, high in ROW_ITEM.findall(match.group(1)):
            if high:
                out.update(n for n in known if int(low) <= n <= int(high))
            elif int(low) in known:
                out.add(int(low))
    return out


def is_repository(repo):
    return gitio.git(repo, "rev-parse", "--git-dir").code == 0


def read_commits(repo, *spec):
    """[{sha, parents, date, message, files: [(path, lines changed)]}], newest first."""
    if not is_repository(repo):
        raise PlanError(f"{repo} is not a git repository, so it has no commits to read")
    if gitio.git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").code:
        return []
    done = gitio.git(repo, "log", "--no-renames", "--numstat", "-z", "--format=%x01%H%x00%P%x00%as%x00%B%x02", *spec, timeout=60)
    if done.code:
        raise PlanError(f"focus: git could not read the commits: {done.err.strip()[:200]}")
    commits = []
    for chunk in done.out.split("\x01")[1:]:
        head, _, stats = chunk.partition("\x02")
        fields = head.split("\0", 3)
        if len(fields) < 4:
            continue
        files = []
        for item in stats.split("\0"):
            parts = item.strip("\n").split("\t", 2)
            if len(parts) == 3:
                added, removed = parts[0], parts[1]
                files.append((parts[2], (int(added) if added.isdigit() else 1) + (int(removed) if removed.isdigit() else 0)))
        commits.append({"sha": fields[0], "parents": fields[1].split(), "date": fields[2], "message": fields[3].strip(), "files": files})
    return commits


def _area(files):
    """Where a commit mostly happened: a top folder, or the second level under one that only says `src`."""
    weight = {}
    for path, lines in files:
        parts = path.split("/")
        key = "/".join(parts[:2]) if parts[0] in SOURCE_ROOTS and len(parts) > 2 else parts[0]
        weight[key] = weight.get(key, 0) + lines
    return max(sorted(weight), key=weight.get) if weight else ""


class _Reading:
    """What is needed to judge a commit: the rows, what each cites, what the plan ties to them, and what the table's history shows."""

    def __init__(self, plan, start, today):
        self.plan = plan
        self.repo = plan.repo or plan.doc.parent
        table = tables.load_clean(plan)
        self.table = table
        rows = [r for d in table.domains for r in d.rows if not r.prose]
        self.known = {r.num for r in rows}
        self.open = {r.num for r in rows if r.kind != plan.strict_kind.name}
        self.words = {r.num: words_of(r.name) for r in rows}
        self.cited, self.pull_requests, self.merge_requests = [], {}, {}
        for row in rows:
            for claim in evidence.release_claims(plan, row.words()):
                if claim.kind in ("sha", "bare"):
                    self.cited.append((str(claim.value), row.num))
                elif claim.kind == "pr":
                    self.pull_requests.setdefault(int(claim.value), set()).add(row.num)
                elif claim.kind == "mr":
                    self.merge_requests.setdefault(int(claim.value), set()).add(row.num)
        self.paths = self._paths(plan)
        self.upkeep = plan.focus.get("upkeep", list(UPKEEP_FILES))
        if not isinstance(self.upkeep, list) or not all(isinstance(p, str) for p in self.upkeep):
            raise PlanError(f"focus: upkeep: expected a list of file patterns, got {self.upkeep!r}")
        self.tracker = self._tracker_files(plan)
        self.moved_by, self.finished_on = {}, {}
        top = plan.strict_kind.weight
        try:
            steps = forecast.table_steps(plan, start, today)[0]
        except PlanError:  # a table outside any repository has no history, and the commits can still be read
            steps = []
        for sha, date, before, after in steps:
            changed = {n for n in after.keys() & before.keys() if after[n] != before[n]} | (after.keys() - before.keys())
            if changed:
                self.moved_by[sha] = changed
            for n in after.keys() & before.keys():
                if after[n] == top and before[n] != top:
                    self.finished_on[n] = date

    def _paths(self, plan):
        raw = plan.focus.get("paths", {})
        if not isinstance(raw, dict):
            raise PlanError(f"focus: paths: expected rows or workstreams and their file patterns, got {raw!r}")
        out = []
        ids = {w.get("id"): w for w in plan.workstreams}
        for key, patterns in raw.items():
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise PlanError(f"focus: paths: {key}: expected a list of file patterns, got {patterns!r}")
            rows = render.workstream_rows_numbers(ids[key]) if key in ids else numbers(key, f"focus: paths: {key}")
            out.append((set(rows), patterns))
        return out

    def _tracker_files(self, plan):
        top = gitio.git(self.repo, "rev-parse", "--show-toplevel")
        if top.code:
            return set()
        root = os.path.realpath(top.out.strip())
        out = set()
        for path in plan.tracked:
            real = os.path.realpath(path)
            if real.startswith(root + os.sep):
                out.add(os.path.relpath(real, root).replace(os.sep, "/"))
        return out

    def _is_tracker(self, path):
        return path in self.tracker or os.path.basename(path) == POINTER

    def _in_reach(self, num, date):
        """Whether a row could still have been advanced on a day: it is open, or it finished on or after that day."""
        return num in self.open or self.finished_on.get(num, "") >= date

    def direct_links(self, commit):
        """The rows a commit is tied to by someone's word: its message, a row's citation, its own move in the table."""
        named = named_rows(commit["message"], self.known)
        if named:
            return named, "named in the message"
        cited = {num for value, num in self.cited if commit["sha"].startswith(value)}
        if cited:
            return cited, "cited as evidence"
        first_line = commit["message"].split("\n", 1)[0]
        for pattern, table in ((PULL_REQUEST, self.pull_requests), (MERGE_REQUEST, self.merge_requests)):
            for number in pattern.findall(commit["message"] if table is self.merge_requests else first_line):
                if int(number) in table:
                    return set(table[int(number)]), "its pull request is cited as evidence"
        moved = self.moved_by.get(commit["sha"])
        if moved:
            return set(moved), "it moved the row in the table"
        return set(), ""

    def judge(self, commit, inherited=None):
        """(class, rows, because) for one commit."""
        files = [path for path, _ in commit["files"]]
        if not files or all(self._is_tracker(path) for path in files):
            return TRACKER, set(), "only the tracker's own files" if files else "no files"
        rows, because = self.direct_links(commit)
        if rows:
            return ON, rows, because
        if inherited:
            return ON, set(inherited), "its merge is tied to the row"
        work = [(path, lines) for path, lines in commit["files"] if not self._is_tracker(path) and not matches(path, self.upkeep)]
        if not work:
            return UPKEEP, set(), "tests, docs or project files"
        total = sum(lines for _, lines in work) or 1
        for rows_here, patterns in self.paths:
            reachable = {n for n in rows_here if n in self.known and self._in_reach(n, commit["date"])}
            if reachable and sum(lines for path, lines in work if matches(path, patterns)) * 2 >= total:
                return ON, reachable, "the plan ties its files to the row"
        subject = commit["message"].split("\n", 1)[0]
        said = words_of(subject)
        best, shared_most = None, 0
        for num in sorted(self.words):
            shared = len(said & self.words[num])
            enough = shared >= 2 or (shared == 1 and len(self.words[num]) == 1)
            if enough and shared > shared_most and self._in_reach(num, commit["date"]):
                best, shared_most = num, shared
        if best is not None:
            return ON, {best}, "its subject shares the row's words"
        if UPKEEP_SUBJECT.match(subject):
            return UPKEEP, set(), "its subject says it is upkeep"
        return OFF, set(), "it names no row and matches none"


def _inherited(reading, commits):
    """A merge tied to a row brings its branch along: the pull request's title says what the commits inside it were for."""
    out = {}
    for commit in commits:
        if len(commit["parents"]) > 1:
            rows, _ = reading.direct_links(commit)
            if rows:
                inside = gitio.git(reading.repo, "rev-list", f"{commit['parents'][0]}..{commit['sha']}")
                for sha in inside.out.split():
                    out.setdefault(sha, set()).update(rows)
    return out


def _judged(reading, spec):
    commits = read_commits(reading.repo, *spec)
    inherited = _inherited(reading, commits)
    out = []
    for commit in commits:
        if len(commit["parents"]) > 1:
            continue
        kind, rows, because = reading.judge(commit, inherited.get(commit["sha"]))
        work = [(path, lines) for path, lines in commit["files"] if not reading._is_tracker(path) and not matches(path, reading.upkeep)]
        out.append({"commit": commit["sha"][:7], "date": commit["date"], "subject": commit["message"].split("\n", 1)[0], "class": kind, "rows": sorted(rows),
                    "because": because, "lines": sum(lines for _, lines in commit["files"]), "area": _area(work or commit["files"])})
    return out


def data(plan, days=WINDOW, today=None, revisions=None):
    """Where the commits went over the last `days` days, or over a range of revisions, as data."""
    if days < 1:
        raise PlanError("focus: the window must be at least one day")
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)
    reading = _Reading(plan, start, today)
    judged = _judged(reading, [revisions] if revisions else [f"--since={start.isoformat()}T00:00:00"])
    counted = [c for c in judged if c["class"] != TRACKER]
    tally = {kind: [c for c in counted if c["class"] == kind] for kind in (ON, UPKEEP, OFF)}
    per_row, per_area = {}, {}
    for c in tally[ON]:
        for num in c["rows"]:
            per_row[num] = per_row.get(num, 0) + 1
    for c in tally[OFF]:
        per_area[c["area"]] = per_area.get(c["area"], 0) + 1
    following = render.opener_data(plan, reading.table)["next"]
    return {"days": None if revisions else days, "since": None if revisions else start.isoformat(), "revisions": revisions, "commits": len(counted),
            "on_plan": len(tally[ON]), "upkeep": len(tally[UPKEEP]), "off_plan": len(tally[OFF]), "tracker_only": len(judged) - len(counted),
            "lines": {"on_plan": sum(c["lines"] for c in tally[ON]), "upkeep": sum(c["lines"] for c in tally[UPKEEP]), "off_plan": sum(c["lines"] for c in tally[OFF])},
            "rows": [{"row": n, "commits": per_row[n]} for n in sorted(per_row, key=lambda n: (-per_row[n], n))],
            "areas": [{"area": a, "commits": per_area[a]} for a in sorted(per_area, key=lambda a: (-per_area[a], a))],
            "next": following, "list": judged}


def _share(part, whole):
    return render.pct(part / whole) if whole else "0%"


def _first(items, count, word):
    shown = ", ".join(word(i) for i in items[:count])
    return shown + (f", and {len(items) - count} more" if len(items) > count else "")


def _next_words(found):
    following = found["next"]
    if not following:
        return ""
    needs = f" It needs {following['needs']}." if following["needs"] else ""
    return f"Next on the plan: {following['id']} ({following['name']}).{needs}"


def text(found, show_all=False):
    span = (f"Last {found['days']} days" if found["days"] != 1 else "Today") if found["days"] else f"In {found['revisions']}"
    if not found["commits"]:
        return "\n".join(line for line in (f"{span}: no commits but the tracker's own.", _next_words(found)) if line)
    L = [f"{span}: {found['commits']} commit{'' if found['commits'] == 1 else 's'}."]
    rows = _first(found["rows"], 6, lambda r: f"{r['row']} ({r['commits']})")
    areas = _first(found["areas"], 4, lambda a: f"{a['area']} ({a['commits']})")
    width = len(str(found["commits"]))
    L.append(f"  On plan   {found['on_plan']:>{width}}  {_share(found['on_plan'], found['commits']):>4}" + (f"  rows {rows}" if rows else ""))
    L.append(f"  Upkeep    {found['upkeep']:>{width}}  {_share(found['upkeep'], found['commits']):>4}")
    L.append(f"  Off plan  {found['off_plan']:>{width}}  {_share(found['off_plan'], found['commits']):>4}" + (f"  {areas}" if areas else ""))
    chosen = [c for c in found["list"] if c["class"] != TRACKER] if show_all else [c for c in found["list"] if c["class"] == OFF]
    if chosen:
        L += ["", "Every commit, newest first:" if show_all else "Off plan, newest first:"]
        limit = len(chosen) if show_all else 10
        for c in chosen[:limit]:
            where = f" ({c['area']})" if c["area"] and not show_all else ""
            why = f" [{c['class']}: {c['because']}]" if show_all else ""
            L.append(f"  {c['commit']} {c['subject']}{where}{why}")
        if len(chosen) > limit:
            L.append(f"  and {len(chosen) - limit} more: gitdone focus --all")
    next_words = _next_words(found)
    if next_words:
        L += ["", next_words]
    if found["off_plan"]:
        L += ["Off plan is not wrong, only unplanned. If it belongs, `gitdone add \"<what it is>\"` puts it in the scope, and the date moves.",
              "To tie a commit to a row, name the row in its message: row 12."]
    return "\n".join(L)


def opener_line(plan, today=None):
    """One line for whoever opens the project; None if too little has happened to say anything."""
    found = data(plan, today=today)
    if found["commits"] < 3:
        return None
    areas = _first(found["areas"], 2, lambda a: f"{a['area']} {a['commits']}")
    off = f"{found['off_plan']} off plan ({areas})" if found["off_plan"] else "none off plan"
    return f"Focus, last {found['days']} days: {found['on_plan']} of {found['commits']} commits on plan, {off}."


def last_line(plan):
    """What a post-commit hook says about the commit just made: one line if it was off plan, and nothing otherwise."""
    today = datetime.date.today()
    reading = _Reading(plan, today - datetime.timedelta(days=WINDOW - 1), today)
    judged = _judged(reading, ["-1", "HEAD"])
    if not judged or judged[0]["class"] != OFF:
        return None
    following = render.opener_data(plan, reading.table)["next"]
    next_words = f" Next on the plan: {following['id']} ({following['name']})." if following else ""
    return (f"gitdone: {judged[0]['commit']} is off plan: it names no row and matches none.{next_words} "
            "Name the row in the message (row 12), or put the work in the scope: gitdone add \"<what it is>\"")


def counts_words(found):
    """A few words for `week` and a pull request's comment."""
    if not found["commits"]:
        return ""
    return f"Focus: {found['on_plan']} of {found['commits']} commits on plan, {found['upkeep']} upkeep, {found['off_plan']} off plan."


def next_data(plan):
    """What to work on now: the next workstream's open rows, or the table's next open rows, and nothing else."""
    table = tables.load_clean(plan)
    top = plan.strict_kind.name
    following = render.opener_data(plan, table)["next"] if plan.order else None
    if following:
        rows = [r for r in render.workstream_rows(plan.workstream(following["id"]), table) if r.kind != top and not r.prose]
    else:
        rows = [r for d in table.domains for r in d.rows if r.kind != top and not r.prose][:NEXT_ROWS]
    left = sum(1 for d in table.domains for r in d.rows if r.kind != top)
    return {"workstream": following, "rows": [{"row": r.num, "name": r.name, "kind": r.kind, "note": r.note} for r in rows], "open_rows": left}


def next_text(found):
    if not found["open_rows"]:
        return "Nothing is open: every row is done."
    w = found["workstream"]
    L = []
    if w:
        needs = f" It needs {w['needs']}." if w["needs"] else ""
        L.append(f"Next: {w['id']} ({w['name']}).{needs}")
    else:
        L.append(f"Next, of {found['open_rows']} open rows:")
    width = max((len(str(r["row"])) for r in found["rows"]), default=1)
    for r in found["rows"]:
        note = f": {' '.join(r['note'].split())[:80]}" if r["note"].strip() else ""
        L.append(f"  {r['row']:>{width}}  {r['name']} ({r['kind']}){note}")
    example = found["rows"][0]["row"] if found["rows"] else 1
    L += ["", f"Name the row in the commit message (row {example}), so that the work traces to it.",
          "Something not on this list is a change of scope. Say so before starting it: `gitdone add` puts it in the plan, and the date moves."]
    return "\n".join(L)
