"""`focus`: where the commits went. Each one advanced a row, kept the project running, or did neither, and that last kind is how one month
becomes three. It is a signal and never a gate: the commit has already happened, and it may have been right. Saying so lets the scope
change on purpose: `gitdone add` makes the work part of the plan, and the date moves.

On plan means someone said so: the message names the row, a row cites the commit, the commit moved the row, a merge is tied to the row, or the plan ties its files to
the row. What only looks like a row, by its words or its branch's name, is unclear, and it is listed with what is off plan, because a guess must not close a gap. Every answer says why.
"""
import datetime
import fnmatch
import os
import re

from . import evidence, forecast, gitio, history, render, table as tables
from .discover import POINTER
from .plan import PlanError, numbers

WINDOW = 14
NEXT_ROWS = 5
MOST_COMMITS_LISTED = 20000
UPKEEP_SUBJECT_LINES = 50  # a subject can say what a small change is. A large one is judged by what it did
LARGE_UPKEEP_LINES = 200
ON, UNCLEAR, UPKEEP, OFF, TRACKER = "on plan", "unclear", "upkeep", "off plan", "tracker"
ROW_WORDS = re.compile(r"\b(rows?)[\s:#_-]*#?(\d{1,9}(?:\s*(?:,|&|\band\b|-|–|\bto\b)\s*#?\d{1,9})*)", re.I)
ROW_ITEM = re.compile(r"(\d{1,9})(?:\s*(?:-|–|\bto\b)\s*(\d{1,9}))?", re.I)
PULL_REQUEST = re.compile(r"(?:\(#|pull request #)(\d{1,9})\b", re.I)
MERGE_REQUEST = re.compile(r"See merge request \S*!(\d{1,9})\b")
REVERT_SUBJECT = re.compile(r"^revert\b", re.I)
UPKEEP_SUBJECT = re.compile(r"^(?:fix|chore|ci|build|style|deps)(?:\([^)]*\))?!?:|^bump\b", re.I)
COMMIT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
NUMSTAT = re.compile(r"^(\d+|-)\t(\d+|-)\t(.*)$", re.S)
TESTS = ("tests/*", "test/*", "spec/*", "specs/*", "__tests__/*", "*/tests/*", "*/test/*", "*/spec/*", "*/__tests__/*", "test_*", "*/test_*",
         "*_test.*", "*.test.*", "*.spec.*")
UPKEEP_FILES = TESTS + ("docs/*", "doc/*", "*.md", "*.rst", ".github/*", ".gitlab-ci.yml", ".gitignore", ".gitattributes", ".editorconfig",
                        ".pre-commit-config.yaml", "LICENSE*", "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum", "go.mod", "Makefile", "Dockerfile*",
                        "docker-compose*.yml", "pyproject.toml", "setup.cfg", "tox.ini", "requirements*.txt", "package.json", "tsconfig*.json", "Cargo.toml")
SOURCE_ROOTS = {"src", "lib", "app", "apps", "pkg", "packages", "services", "internal", "cmd"}
FEW_WORDS = frozenset("a an and are as at be by for from in into is it its of on or that the this to with add adds added adding update updates "
                      "updated updating fix fixes fixed fixing make makes made making use uses used using change changes changed changing "
                      "remove removes removed removing new more less first row rows work works feat feature chore docs test tests refactor".split())


def matches(path, patterns):
    """A file against a plan's patterns. `*` crosses folders, and a bare folder name stands for all it holds. What a Python cannot read as a pattern matches nothing."""
    for pattern in patterns:
        try:
            if fnmatch.fnmatchcase(path, pattern) or path.startswith(pattern.rstrip("/") + "/"):
                return True
        except re.error:
            continue
    return False


def words_of(text):
    """The words of a name or a subject that could tell one piece of work from another."""
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) >= 3 and word not in FEW_WORDS:
            found.add(word[:-1] if len(word) > 4 and word.endswith("s") else word)
    return found


def _row_numbers(message):
    """(numbers, ranges) a message names. A range needs the plural: `rows 7-9`, while a branch `row-3-2fa-login` names row 3."""
    single, ranges = set(), []
    for match in ROW_WORDS.finditer(message):
        plural = match.group(1).lower().endswith("s")
        for low, high in ROW_ITEM.findall(match.group(2)):
            if high and plural:
                ranges.append((min(int(low), int(high)), max(int(low), int(high))))
            else:
                single.add(int(low))
    return single, ranges


def named_rows(message, known):
    """The rows a commit message names: `row 12`, `Row: 12`, `rows 12, 13`, `rows 7-9`, or a branch `row-12` in a merge's subject."""
    single, ranges = _row_numbers(message)
    return {n for n in known if n in single or any(low <= n <= high for low, high in ranges)}


def is_repository(repo):
    return gitio.git(repo, "rev-parse", "--git-dir").code == 0


def read_commits(repo, *spec, stdin_text=None):
    """[{sha, parents, date, message, files: [(path, lines changed)]}], newest first. In a repository's subfolder, only what touched that folder, with
    paths from it, so that a tracker in a monorepo answers for its own project and a plan's patterns mean what its other paths mean.
    """
    if not is_repository(repo):
        raise PlanError(f"{repo} is not a git repository, so it has no commits to read")
    if gitio.git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").code:
        return []
    below = ["--relative", "--full-history", "--", "."] if gitio.git(repo, "rev-parse", "--show-prefix").out.strip() else []
    done = gitio.git(repo, "log", "--no-renames", "--numstat", "-z", "--format=%H%x00%P%x00%as%x00%B%x00", *spec, *below, stdin_text=stdin_text, timeout=60)
    if done.code:
        raise PlanError(f"focus: git could not read the commits: {done.err.strip()[:200]}")
    tokens, at, commits = done.out.split("\0"), 0, []
    while at + 3 < len(tokens):  # a message cannot hold a NUL, so each field is where the format put it, whatever else the message holds
        sha = tokens[at].lstrip("\n")
        if not COMMIT_ID.match(sha):
            at += 1
            continue
        parents, date, message = tokens[at + 1], tokens[at + 2], tokens[at + 3]
        at += 4
        files = []
        while at < len(tokens):
            item = tokens[at].lstrip("\n")
            if COMMIT_ID.match(item):
                break
            at += 1
            stat = NUMSTAT.match(item)
            if stat:
                files.append((stat.group(3), (int(stat.group(1)) if stat.group(1).isdigit() else 1) + (int(stat.group(2)) if stat.group(2).isdigit() else 0)))
        commits.append({"sha": sha, "parents": parents.split(), "date": date, "message": message.strip(), "files": files})
    return commits


def _area(files):
    """Where a commit mostly happened: a top folder, or what is under one that only says `src`."""
    weight = {}
    for path, lines in files:
        parts = path.split("/")
        key = "/".join(parts[:2]) if parts[0] in SOURCE_ROOTS and len(parts) > 1 else parts[0]
        weight[key] = weight.get(key, 0) + lines
    return max(sorted(weight), key=weight.get) if weight else ""


def _top(path):
    done = gitio.git(path, "rev-parse", "--show-toplevel")
    return os.path.realpath(done.out.strip()) if done.code == 0 and done.out.strip() else None


class _Reading:
    """What is needed to judge a commit: the rows, what each cites, what the plan ties to them, and what the table's history shows."""

    def __init__(self, plan, start, today):
        self.plan = plan
        self.repo = plan.repo or plan.doc.parent
        self.same_repository = _top(self.repo) is not None and _top(self.repo) == _top(plan.doc.parent)
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
        self.workstreams = {w["id"]: {n for n in render.workstream_rows_numbers(w) if n in self.known} for w in plan.workstreams
                            if isinstance(w.get("id"), str) and re.search(r"\d", w["id"]) and len(w["id"]) <= 12}
        self.workstream_word = re.compile(r"^(" + "|".join(re.escape(w) for w in sorted(self.workstreams, key=len, reverse=True)) + r"):") if self.workstreams else None
        self.upkeep = list(UPKEEP_FILES) + plan.focus.get("upkeep", [])
        self.not_upkeep = plan.focus.get("not_upkeep", [])
        self.tracker = self._tracker_files(plan)
        self.moved_by, self.finished_on = {}, {}
        top = plan.strict_kind.name
        self.born = None
        try:
            steps, self.born = forecast.table_steps(plan, start, today)
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
        out = []
        ids = {w.get("id"): w for w in plan.workstreams}
        for key, patterns in plan.focus.get("paths", {}).items():
            rows = render.workstream_rows_numbers(ids[key]) if key in ids else numbers(key, f"focus: paths: {key}")
            out.append((set(rows) & self.known, patterns))
        return out

    def _tracker_files(self, plan):
        """The tracker's files, as a commit in this folder names them."""
        prefix = gitio.git(self.repo, "rev-parse", "--show-toplevel")
        if prefix.code:
            return set()
        here = os.path.realpath(self.repo)
        out = set()
        for path in plan.tracked:
            real = os.path.realpath(path)
            if real.startswith(here + os.sep):
                out.add(os.path.relpath(real, here).replace(os.sep, "/"))
        return out

    def _is_tracker(self, path):
        return path in self.tracker or os.path.basename(path) == POINTER

    def _is_upkeep(self, path):
        return matches(path, self.upkeep) and not matches(path, self.not_upkeep)

    def _in_reach(self, num, date):
        """Whether a row could still have been advanced on a day: it is open, or it finished on or after that day."""
        return num in self.open or self.finished_on.get(num, "") >= date

    def direct_links(self, commit):
        """The rows a commit is tied to by someone's word: its message, a row's citation, its own move in the table."""
        named = named_rows(commit["message"], self.known)
        if named:
            return named, "named in the message"
        first_line = commit["message"].split("\n", 1)[0]
        if self.workstream_word:
            said = self.workstream_word.match(first_line)
            if said and self.workstreams[said.group(1)]:
                return set(self.workstreams[said.group(1)]), "its workstream starts the subject"
        cited = {num for value, num in self.cited if commit["sha"].startswith(value)}
        if cited:
            return cited, "cited as evidence"
        for pattern, table in ((PULL_REQUEST, self.pull_requests), (MERGE_REQUEST, self.merge_requests)):
            for number in pattern.findall(commit["message"] if table is self.merge_requests else first_line):
                if int(number) in table:
                    return set(table[int(number)]), "its pull request is cited as evidence"
        moved = self.moved_by.get(commit["sha"])
        if moved:
            return set(moved), "it moved the row in the table"
        return set(), ""

    def _off_plan_reason(self, commit):
        single, ranges = _row_numbers(commit["message"])
        unknown = sorted(n for n in single if n not in self.known) + [low for low, high in ranges if not any(low <= n <= high for n in self.known)]
        if unknown:
            return f"it names row {unknown[0]}, which the table does not have"
        return "it names no row and matches none"

    def judge(self, commit, inherited=None):
        """(class, rows, because) for one commit."""
        files = [path for path, _ in commit["files"]]
        if not files or all(self._is_tracker(path) for path in files):
            return TRACKER, set(), "only the tracker's own files" if files else "no files"
        subject = commit["message"].split("\n", 1)[0]
        if REVERT_SUBJECT.match(subject):
            return UPKEEP, set(), "it reverts something, which advances no row"
        rows, because = self.direct_links(commit)
        if rows:
            if because == "named in the message" and not any(self._in_reach(n, commit["date"]) for n in rows):
                return UNCLEAR, rows, f"row {min(rows)} had finished by then"
            return ON, rows, because
        if inherited and inherited[1] == MERGED_FOR_THE_ROW:
            if any(self._in_reach(n, commit["date"]) for n in inherited[0]):
                return ON, set(inherited[0]), inherited[1]
            return UNCLEAR, set(inherited[0]), f"row {min(inherited[0])} had finished by then"
        work = [(path, lines) for path, lines in commit["files"] if not self._is_tracker(path) and not self._is_upkeep(path)]
        if not work:
            return UPKEEP, set(), "tests, docs or project files"
        total = sum(lines for _, lines in work) or 1
        for rows_here, patterns in self.paths:
            reachable = {n for n in rows_here if self._in_reach(n, commit["date"])}
            if reachable and sum(lines for path, lines in work if matches(path, patterns)) * 2 >= total:
                return ON, reachable, "the plan ties its files to the row"
        if inherited:
            return UNCLEAR, set(inherited[0]), inherited[1]
        said = words_of(subject)
        best, shared_most = None, 0
        for num in sorted(self.words):
            shared = len(said & self.words[num])
            enough = shared >= 2 or (shared == 1 and len(self.words[num]) == 1)
            if enough and shared > shared_most and self._in_reach(num, commit["date"]):
                best, shared_most = num, shared
        if best is not None:
            return UNCLEAR, {best}, f"it looks like row {best}, by its words"
        if UPKEEP_SUBJECT.match(subject):
            if total <= UPKEEP_SUBJECT_LINES:
                return UPKEEP, set(), "its subject says it is upkeep"
            return UNCLEAR, set(), f"its subject says upkeep, and it changed {total} lines"
        return OFF, set(), self._off_plan_reason(commit)


MERGED_FOR_THE_ROW = "its merge is tied to the row"
BRANCH_FOR_THE_ROW = "its branch is named for the row"


def _inherited(reading, commits):
    """What a commit brings from around it. A merge tied to a row brings its branch along, since a pull request's title says what the commits inside it were
    for. A branch named for a row does the same for what it holds, before any merge.
    """
    out = {}
    for commit in commits:
        if len(commit["parents"]) > 1:
            rows, _ = reading.direct_links(commit)
            if rows:
                inside = gitio.git(reading.repo, "rev-list", f"{commit['parents'][0]}..{commit['sha']}")
                for sha in inside.out.split():
                    out.setdefault(sha, (rows, MERGED_FOR_THE_ROW))
    branch = gitio.git(reading.repo, "symbolic-ref", "--quiet", "--short", "HEAD").out.strip()
    rows = named_rows(branch, reading.known)
    if rows and branch != reading.plan.default_branch:
        for ref in (f"refs/heads/{reading.plan.default_branch}", f"refs/remotes/origin/{reading.plan.default_branch}"):
            if gitio.git(reading.repo, "rev-parse", "--verify", "--quiet", ref).code == 0:
                for sha in gitio.git(reading.repo, "rev-list", f"{ref}..HEAD").out.split():
                    out.setdefault(sha, (rows, BRANCH_FOR_THE_ROW))
                break
    return out


def _judged(reading, spec, stdin_text=None):
    commits = read_commits(reading.repo, *spec, stdin_text=stdin_text)
    inherited = _inherited(reading, commits)
    out = []
    for commit in commits:
        if len(commit["parents"]) > 1:
            continue
        kind, rows, because = reading.judge(commit, inherited.get(commit["sha"]))
        work = [(path, lines) for path, lines in commit["files"] if not reading._is_tracker(path) and not reading._is_upkeep(path)]
        out.append({"commit": commit["sha"][:7], "date": commit["date"], "subject": commit["message"].split("\n", 1)[0], "class": kind, "rows": sorted(rows),
                    "because": because, "lines": sum(lines for _, lines in commit["files"]), "area": _area(work or commit["files"])})
    return out


def _in_the_window(reading, start, today):
    """The commits written since the window opened and since the table began: nothing could have been on a plan that did not exist yet. Chosen by the dates a
    commit keeps, as `eta` chooses them: `git log --since` goes by the committer's date and stops at the first old one, so one commit could hide the rest.
    """
    limit = []
    since = start.isoformat()
    if reading.same_repository:
        first = _first_table_commit(reading.plan)
        if first is None:
            return []
        limit = ["--not", first]
    elif reading.born:
        since = max(since, reading.born)
    if gitio.git(reading.repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}").code:
        return []
    listed = gitio.git(reading.repo, "log", "--format=%H %as", f"--max-count={MOST_COMMITS_LISTED}", "HEAD", *limit, timeout=60)
    if listed.code:
        raise PlanError(f"focus: git could not list the commits: {listed.err.strip()[:200]}")
    out, latest = [], today.isoformat()
    for line in listed.out.splitlines():
        sha, _, date = line.partition(" ")
        if min(date, latest) >= since:
            out.append(sha)
    return out


def _first_table_commit(plan):
    top, rel = forecast._where(plan)
    commits = history.table_commits(top, rel, first_parent=True)
    return commits[-1][0] if commits else None


def data(plan, days=WINDOW, today=None, revisions=None):
    """Where the commits went over the last `days` days, or over a range of revisions, as data."""
    if days < 1:
        raise PlanError("focus: the window must be at least one day")
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=days - 1)
    reading = _Reading(plan, None if revisions else start, today)
    if not is_repository(reading.repo):
        raise PlanError(f"{reading.repo} is not a git repository, so it has no commits to read")
    if revisions:
        judged = _judged(reading, [revisions])
    else:
        chosen = _in_the_window(reading, start, today)
        judged = _judged(reading, ["--no-walk=unsorted", "--stdin"], stdin_text="\n".join(chosen) + "\n") if chosen else []
    counted = [c for c in judged if c["class"] != TRACKER]
    tally = {kind: [c for c in counted if c["class"] == kind] for kind in (ON, UNCLEAR, UPKEEP, OFF)}
    per_row, per_area = {}, {}
    for c in tally[ON]:
        for num in c["rows"]:
            per_row[num] = per_row.get(num, 0) + 1
    for c in tally[OFF]:
        per_area[c["area"]] = per_area.get(c["area"], 0) + c["lines"]
    following = render.opener_data(plan, reading.table)["next"]
    next_rows = next_data(plan)["rows"]
    return {"days": None if revisions else days, "since": None if revisions else start.isoformat(), "revisions": revisions, "commits": len(counted),
            "on_plan": len(tally[ON]), "unclear": len(tally[UNCLEAR]), "upkeep": len(tally[UPKEEP]), "off_plan": len(tally[OFF]),
            "tracker_only": len(judged) - len(counted), "shallow": forecast._is_shallow(reading.repo),
            "lines": {"on_plan": sum(c["lines"] for c in tally[ON]), "unclear": sum(c["lines"] for c in tally[UNCLEAR]), "upkeep": sum(c["lines"] for c in tally[UPKEEP]), "off_plan": sum(c["lines"] for c in tally[OFF])},
            "rows": [{"row": n, "commits": per_row[n]} for n in sorted(per_row, key=lambda n: (-per_row[n], n))],
            "areas": [{"area": a, "lines": per_area[a]} for a in sorted(per_area, key=lambda a: (-per_area[a], a))],
            "next": following, "next_row": next_rows[0]["row"] if next_rows else None, "list": judged}


def _lines(count):
    return f"{count:,} line{'' if count == 1 else 's'}"


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
    span = (f"Last {found['days']} days" if found["days"] != 1 else "Today") if found["days"] else f"In {render.one_line(found['revisions'])}"
    shallow = ["This clone is shallow, so only part of the history is here."] if found["shallow"] else []
    if not found["commits"]:
        return "\n".join(shallow + [line for line in (f"{span}: no commits but the tracker's own since the table began.", _next_words(found)) if line])
    lines_in_all = sum(found["lines"].values())
    L = shallow + [f"{span}: {found['commits']} commit{'' if found['commits'] == 1 else 's'}, {_lines(lines_in_all)} changed."]
    rows = _first(found["rows"], 6, lambda r: f"{r['row']} ({r['commits']})")
    areas = _first(found["areas"], 4, lambda a: f"{render.one_line(a['area'])} ({_lines(a['lines'])})")
    width = len(str(found["commits"]))
    breadth = max(len(f"{value:,}") for value in found["lines"].values())
    tails = {"on_plan": f"rows {rows}" if rows else "", "off_plan": f"in {areas}" if areas else "", "unclear": "", "upkeep": ""}
    for key, label in (("on_plan", "On plan"), ("unclear", "Unclear"), ("upkeep", "Upkeep"), ("off_plan", "Off plan")):
        if key == "unclear" and not found[key]:
            continue
        tail = f"  {tails[key]}" if tails[key] else ""
        L.append(f"  {label:<8}  {found[key]:>{width}}  {_share(found[key], found['commits']):>4}  {found['lines'][key]:>{breadth},} lines  {_share(found['lines'][key], lines_in_all):>4}{tail}")
    if show_all:
        chosen = [c for c in found["list"] if c["class"] != TRACKER]
        L += ["", "Every commit, newest first:"]
        for c in chosen:
            L.append(f"  {c['commit']} {render.one_line(c['subject'])} ({_lines(c['lines'])}) [{c['class']}: {c['because']}]")
    else:
        chosen = [c for c in found["list"] if c["class"] in (OFF, UNCLEAR)]
        if chosen:
            L += ["", "Off plan or unclear, newest first:"]
            for c in chosen[:12]:
                why = f" [{c['because']}]" if c["class"] == UNCLEAR else ""
                L.append(f"  {c['commit']} {render.one_line(c['subject'])} ({_lines(c['lines'])}, {render.one_line(c['area'])}){why}")
            if len(chosen) > 12:
                L.append(f"  and {len(chosen) - 12} more: gitdone focus --all")
        large = sorted((c for c in found["list"] if c["class"] == UPKEEP and c["lines"] > LARGE_UPKEEP_LINES), key=lambda c: -c["lines"])[:3]
        if large:
            L += ["", "Large upkeep:"] + [f"  {c['commit']} {render.one_line(c['subject'])} ({_lines(c['lines'])})" for c in large]
    next_words = _next_words(found)
    if next_words:
        L += ["", next_words]
    if found["off_plan"] or found["unclear"]:
        example = found["next_row"] or 12
        L += ["Off plan is not wrong, only unplanned. If it belongs, `gitdone add \"<what it is>\"` puts it in the scope, and the date moves.",
              f"To tie a commit to a row, name the row in its message: row {example}."]
    return "\n".join(L)


def opener_line(plan, today=None):
    """One line for whoever opens the project; None if too little has happened to say anything."""
    found = data(plan, today=today)
    if found["commits"] < 3:
        return None
    areas = _first(found["areas"], 2, lambda a: render.one_line(a["area"]))
    off = f"{found['off_plan']} off plan ({areas})" if found["off_plan"] else "none off plan"
    unclear = f", {found['unclear']} unclear" if found["unclear"] else ""
    return f"Focus, last {found['days']} days: {found['on_plan']} of {found['commits']} commits on plan, {off}{unclear}."


def last_line(plan):
    """What a post-commit hook says about the commit just made: one line if it was off plan, and nothing otherwise."""
    today = datetime.date.today()
    reading = _Reading(plan, today - datetime.timedelta(days=WINDOW - 1), today)
    if not reading.same_repository:  # the hook runs in the tracker's repository, and the plan's code is in another: this commit is not one of its commits
        return None
    judged = _judged(reading, ["-1", "HEAD"])
    if not judged or judged[0]["class"] != OFF:
        return None
    following = render.opener_data(plan, reading.table)["next"]
    next_rows = next_data(plan)["rows"]
    next_words = f" Next on the plan: {following['id']} ({following['name']})." if following else ""
    example = next_rows[0]["row"] if next_rows else 12
    return (f"gitdone: {judged[0]['commit']} is off plan: {judged[0]['because']}.{next_words} "
            f"Name the row in the message (row {example}), or put the work in the scope: gitdone add \"<what it is>\"")


def counts_words(found):
    """A few words for a pull request's run."""
    if not found["commits"]:
        return ""
    return f"Focus: {found['on_plan']} of {found['commits']} commits on plan, {found['unclear']} unclear, {found['upkeep']} upkeep, {found['off_plan']} off plan."


def next_data(plan):
    """What to work on now: the next workstream with something open in it, or the table's next open rows, and nothing else."""
    table = tables.load_clean(plan)
    top = plan.strict_kind.name
    chosen, rows = None, []
    for ws_id in plan.order:
        w = plan.workstream(ws_id)
        rows = [r for r in render.workstream_rows(w, table) if r.kind != top and not r.prose]
        if rows:
            chosen = {"id": render.one_line(ws_id), "name": render.one_line(w.get("name", "")), "state": render.one_line(w.get("state", "")), "needs": render.one_line(w.get("needs", ""))}
            break
    if not chosen:
        rows = [r for d in table.domains for r in d.rows if r.kind != top and not r.prose][:NEXT_ROWS]
    left = sum(1 for d in table.domains for r in d.rows if r.kind != top)
    return {"workstream": chosen, "rows": [{"row": r.num, "name": r.name, "kind": r.kind, "note": r.note} for r in rows], "open_rows": left}


def next_text(found):
    if not found["open_rows"]:
        return "Nothing is open: every row is done."
    if not found["rows"]:
        return f"{found['open_rows']} rows are open, and all of them sit in a domain with no table of rows yet. Give it one, and they can be named."
    w = found["workstream"]
    L = []
    if w:
        needs = f" It needs {w['needs']}." if w["needs"] else ""
        L.append(f"Next: {w['id']} ({w['name']}).{needs}")
    else:
        L.append(f"Next, of {found['open_rows']} open rows:")
    width = max(len(str(r["row"])) for r in found["rows"])
    for r in found["rows"]:
        note = f": {render.one_line(r['note'])[:80]}" if r["note"].strip() else ""
        L.append(f"  {r['row']:>{width}}  {render.one_line(r['name'])} ({render.one_line(r['kind'])}){note}")
    L += ["", f"Name the row in the commit message (row {found['rows'][0]['row']}), so that the work traces to it.",
          "Work on no row is a change of scope. Say so before starting it: `gitdone add` puts it in the plan, and the date moves."]
    return "\n".join(L)
