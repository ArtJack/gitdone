"""`check`: the view matches the table, the counts sum, and each status has the evidence its kind asks for.

Exit codes:
    0  clean, or only warnings in the default mode
    1  a proven contradiction: a stale view, counts that do not sum, a row whose every claim git or gh disproves
    2  could not run: a usage error, an unreadable plan or table, a repo that is not one
    3  --strict only: evidence is missing or partly disproved, and no row is left with nothing but contradictions
"""
import collections
import errno
import json
import os

from . import evidence, gitio, render, table as tables, verdict
from .discover import POINTER
from .plan import DEFAULT_KINDS, RULE_KEYS, Plan, PlanError, read_file

OK, CONTRADICTION, CANNOT_RUN, MISSING = 0, 1, 2, 3
MOST_REQUIREMENTS_SAID = 10
FRESH, STALE, ABSENT_VIEW, NOT_COMPARED = "fresh", "stale", "missing", "not compared"
Finding = collections.namedtuple("Finding", "text rows next", defaults=(None,))  # next: what to do about it, on its own line


def said(finding):
    """A finding and what to do about it, for a place that has only the one line."""
    return finding.text + (f"; {finding.next}" if finding.next else "")


def _fix(plan, path, fresh, staged, same):
    """What to do about a stale file. In a commit, a file that is right on disk only needs staging."""
    if staged:
        try:
            if same(read_file(path), fresh):
                return f"it is right on disk and not staged: git add {os.path.relpath(path)}"
        except (OSError, UnicodeDecodeError):
            pass
        return f"run `{plan.regenerate}`, and stage the plan, the table and {path.name} together"
    return f"run `{plan.regenerate}`"


def _same_view(a, b):
    return render.normalize(a) == render.normalize(b)


def _view(plan, table, fails, staged):
    """(state, words) for the view, adding a failure when it does not match."""
    rendered = render.status_md(plan, table)
    fix = _fix(plan, plan.out, rendered, staged, _same_view)
    try:
        text = plan.read(plan.out)
    except (OSError, UnicodeDecodeError):
        fails.append(Finding(f"view: {plan.out.name} {'is not in this commit' if staged else 'does not exist'}; {fix}", []))
        return ABSENT_VIEW, "missing"
    on_disk = render.normalize(text).split("\n")
    fresh = render.normalize(rendered).split("\n")
    if on_disk == fresh:
        return FRESH, f"{plan.out.name} matches a fresh render, date line aside"
    line = next((i for i, (a, b) in enumerate(zip(on_disk, fresh), 1) if a != b), min(len(on_disk), len(fresh)) + 1)
    fails.append(Finding(f"view: {plan.out.name} differs from a fresh render at line {line}; {fix}", []))
    return STALE, "stale"


def _badge(plan, table, fails, staged):
    """A plan that names a badge holds it to the same rule as the view: a pure function of the plan and the table."""
    if not plan.badge:
        return
    from . import badge
    drawn = badge.svg(plan, table)
    fix = _fix(plan, plan.badge, drawn, staged, lambda a, b: a == b)
    try:
        text = plan.read(plan.badge)
    except (OSError, UnicodeDecodeError):
        fails.append(Finding(f"badge: {plan.badge.name} {'is not in this commit' if staged else 'does not exist'}; {fix}", []))
        return
    if text != drawn:
        fails.append(Finding(f"badge: {plan.badge.name} says something else than the table; {fix}", []))


def _counts(plan, table, fails):
    lines = table.text.split("\n")
    for start, end in render.embedded_counts(table.text):
        if "\n".join(lines[start:end]) != render.counts_table(plan, table):
            fails.append(Finding(f"counts: the counts table inside {plan.doc.name} (line {start + 1}) disagrees with its rows; "
                                 "run `gitdone counts --write`", []))
    words = [f"{g.label} {len(tables.group_rows(table, g))}" for g in plan.effective_groups(table)]
    if len(words) > 1:
        words.append(f"all {len(table.rows)}")
    return ", ".join(words)


def _rows_words(numbers, one, many):
    listed = ", ".join(str(n) for n in numbers)
    return f"row {listed} {one}" if len(numbers) == 1 else f"rows {listed} {many}"


def _preload(plan, table, verifier):
    """Everything the rows name, settled in a few git processes rather than a few per row."""
    claims, branches = [], []
    for row in table.rows.values():
        if row.prose:
            continue
        rule = next((k.evidence for k in plan.kinds if k.name == row.kind), None)
        if rule == "release":
            claims.extend(evidence.release_claims(plan, row.words()))
        elif rule == "branch":
            branches.extend(evidence.branch_names(plan, row))
    verifier.preload(claims, branches)


def _next_step(row, detail):
    """What to do about a claim that stopped holding, so that a line does not end on the bad news."""
    if " was reverted on " in detail:
        return f"what is true now? gitdone mark {row.num} <kind> <words>, or shipped {row.num} <the new commit>"
    if " is not on " in detail:
        return f"amended or rebased? Name the new id: gitdone shipped {row.num} <commit>. Still on a branch? gitdone mark {row.num} <kind> --branch NAME"
    return None


def _evidence(plan, table, verifier, fails, missing, notes, strict=False):
    tally = {evidence.VERIFIED: 0, evidence.UNVERIFIED: 0, evidence.CONTRADICTED: 0, "missing": 0}
    _preload(plan, table, verifier)
    no_release, no_branch, no_note, disproved = [], [], [], []
    unverified, on_default = [], []
    for row in table.rows.values():
        if row.prose:
            continue
        rule = next((k.evidence for k in plan.kinds if k.name == row.kind), None)
        if rule == "release":
            claims = evidence.release_claims(plan, row.words())
            if not claims:
                no_release.append(row.num)
                tally["missing"] += 1
                continue
            results = [verifier.claim(c) for c in claims]
            result = evidence.best(results)
            tally["missing" if result.state in (evidence.ABSENT, evidence.UNPROVEN) else result.state] += 1
            if result.state == evidence.CONTRADICTED:
                fails.append(Finding(f"row {row.num} ({row.kind}): {result.detail}", [row.num], _next_step(row, result.detail)))
            elif result.state == evidence.UNVERIFIED:
                unverified.append(Finding(f"row {row.num}: {result.detail}", [row.num]))
            elif result.state == evidence.UNPROVEN:
                disproved.append(Finding(f"row {row.num} ({row.kind}): {result.detail}", [row.num]))
            for claim, other in zip(claims, results):
                if other is not result or result.state == evidence.ABSENT:
                    if other.state in (evidence.ABSENT, evidence.CONTRADICTED, evidence.UNPROVEN):
                        if claim.kind == "bare" and result.state == evidence.VERIFIED:
                            # A bare word beside a claim that holds is probably a word: a file name, a colour, a flag.
                            notes.append(Finding(f"row {row.num}: {other.detail}", [row.num]))
                        else:
                            disproved.append(Finding(f"row {row.num} ({row.kind}): {other.detail}", [row.num], _next_step(row, other.detail)))
                    elif other.state == evidence.UNVERIFIED and other is not result:
                        if claim.kind == "named":  # a plan's own words, which nothing checks and strict does not count
                            notes.append(Finding(f"row {row.num}: {other.detail}", [row.num]))
                        else:
                            unverified.append(Finding(f"row {row.num}: {other.detail}", [row.num]))
        elif rule == "branch":
            names = evidence.branch_names(plan, row)
            if not names:
                no_branch.append(row.num)
                tally["missing"] += 1
                continue
            worst = evidence.VERIFIED
            for name in names:
                result, merged = verifier.branch_named(name)
                if result.state == evidence.CONTRADICTED:
                    worst = evidence.CONTRADICTED
                    hint = None if name == plan.default_branch else f"not pushed yet? Push it. If it merged: gitdone shipped {row.num} <commit>"
                    fails.append(Finding(f"row {row.num} ({row.kind}): {result.detail}", [row.num], hint))
                elif result.state == evidence.UNPROVEN:
                    if worst != evidence.CONTRADICTED:
                        worst = "missing"
                    disproved.append(Finding(f"row {row.num} ({row.kind}): {result.detail}", [row.num]))
                elif result.state == evidence.UNVERIFIED:
                    if worst == evidence.VERIFIED:
                        worst = evidence.UNVERIFIED
                    unverified.append(Finding(f"row {row.num}: {result.detail}", [row.num]))
                if merged:
                    on_default.append(Finding(f"row {row.num}: branch {name} is already on {plan.default_branch}; is the row {plan.strict_kind.name}?", [row.num]))
            tally[worst] += 1
        elif rule == "note":
            if not tables.has_words(row.note):
                no_note.append(row.num)
                tally["missing"] += 1
    if no_release:
        which = str(no_release[0]) if len(no_release) == 1 else "<row>"
        missing.append(Finding(f"{_rows_words(no_release, 'names', 'name')} no commit, pull request or tag; "
                               f"run `gitdone shipped {which} <commit>`", no_release))
    if no_branch:
        missing.append(Finding(f"{_rows_words(no_branch, 'names', 'name')} no branch; run `gitdone mark <row> <kind> --branch NAME`", no_branch))
    if no_note:
        missing.append(Finding(f"{_rows_words(no_note, 'has', 'have')} no note saying what exists; run `gitdone mark <row> <kind> <words>`", no_note))
    missing.extend(disproved)
    # Strict promises that every claim was checked, so a claim nothing could answer for does not pass it.
    (missing if strict else notes).extend(unverified)
    notes.extend(on_default)
    for line in table.strays:
        missing.append(Finding(f"{plan.doc.name} line {line + 1} looks like a row or a domain and is not read as one, so it is not counted",
                               [], "a row starts with its number, a domain is `### N. Name (count)`, and a table of your own goes under a heading of its own"))
    _release_words(plan, verifier, missing, notes, strict)
    return tally


def _release_words(plan, verifier, missing, notes, strict):
    """The view's header can name a release, and that claim answers to the same rules as a row's."""
    for claim in evidence.release_claims(plan, plan.release):
        result = verifier.claim(claim)
        if result.state in (evidence.ABSENT, evidence.CONTRADICTED, evidence.UNPROVEN):
            missing.append(Finding(f"the plan's release: {result.detail}", []))
        elif result.state == evidence.UNVERIFIED:
            (missing if strict and claim.kind != "named" else notes).append(Finding(f"the plan's release: {result.detail}", []))


def _workstream_notes(plan, notes):
    named = set(plan.order)
    for w in plan.workstreams:
        if w.get("id") not in named:
            notes.append(Finding(render.one_line(f"workstream {w.get('id')} is in the plan and not in its order, so the view does not show it"), []))


def _requirement_notes(plan, table, notes):
    """A scope document that has moved past the table is said, and it stops nothing: it is not a claim anybody made. So nothing here may change the gate's answer."""
    from . import requirements
    try:
        found = requirements.coverage(plan, table)
    except Exception as err:
        notes.append(Finding(render.one_line(f"the requirement files could not be read: {err}"), []))
        return
    missing = found["without"]
    for item in missing[:MOST_REQUIREMENTS_SAID]:
        notes.append(Finding(f"requirement {item.label()[:80]} ({item.where()}) has no row, so the percent leaves it out", [], requirements.what_to_do(item)))
    if len(missing) > MOST_REQUIREMENTS_SAID:
        notes.append(Finding(f"and {len(missing) - MOST_REQUIREMENTS_SAID} more requirements have no row: gitdone matrix", []))
    notes.extend(Finding(render.one_line(words), []) for words in found["problems"])


def _staged_reader(root, plan_path):
    """Reads a file as this commit will contain it. A file outside the repository is not part of the commit."""
    def read(path):
        real = os.path.realpath(path)
        if not real.startswith(root + os.sep):
            return read_file(path)
        code, raw = gitio.staged_bytes(os.path.relpath(real, root).replace(os.sep, "/"))
        if code == 0:  # what a plain `check` could not read must not pass here
            return raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        if real == plan_path:  # an untracked plan is still how the project is configured
            return read_file(path)
        raise FileNotFoundError(errno.ENOENT, "not in this commit", str(path))
    return read


USUAL_NAMES = {"status-table.md", "STATUS.md"}


def _json_of(text):
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _names_it_now(root, place, rel):
    """Whether the pointer file at this path, as it stands, names the plan at `rel`."""
    try:
        data = _json_of(read_file(os.path.join(root, place)))
    except (OSError, UnicodeDecodeError):
        return False
    if data is None:
        return False
    return place == rel if "status_doc" in data else os.path.normpath(os.path.join(os.path.dirname(place), str(data.get("plan")))).replace(os.sep, "/") == rel


def plan_before(root, plan_path, show, pointer=None):
    """(the rules as the base holds them, the path they lived at if that is another). `show` reads a path at the base. What the pointer
    named at the base comes first: a plan already in the tree is not the plan that was in force, and moving the rules is changing them.
    `pointer` says where the pointer is, for a plan outside the repository.
    """
    inside = plan_path.startswith(root + os.sep)
    if not inside and pointer is None:
        return None, None
    rel = os.path.relpath(plan_path, root).replace(os.sep, "/") if inside else None
    folder = os.path.dirname(pointer if pointer is not None else rel)
    while True:
        place = f"{folder}/{POINTER}" if folder else POINTER
        said = _json_of(show(place))
        if said is not None:
            named = place if "status_doc" in said else os.path.normpath(os.path.join(folder, str(said.get("plan")))).replace(os.sep, "/")
            if named != rel:
                if pointer is None and inside and show(rel) is not None and not _names_it_now(root, place, rel):
                    break  # a plan given by name, beside another plan's pointer, has not moved
                return _json_of(show(named)), named
            break
        if not folder:
            break
        folder = os.path.dirname(folder)
    return (_json_of(show(rel)), None) if inside else (None, None)


def _committed_show(path):
    done = gitio.git_here("show", "HEAD:" + path)
    return done.out if done.code == 0 else None


def _is_plain(value):
    return not isinstance(value, (dict, list))


def _kinds_changed(old, new):
    """The kinds that changed, by name, and how."""
    def by_name(kinds):
        return {k.get("name"): k for k in kinds if isinstance(k, dict)} if isinstance(kinds, list) else {}
    before, after = by_name(old or DEFAULT_KINDS), by_name(new or DEFAULT_KINDS)
    words = [f"{name} added" for name in after if name not in before] + [f"{name} removed" for name in before if name not in after]
    for name in before:
        if name in after and before[name] != after[name]:
            keys = [k for k in sorted({*before[name], *after[name]}) if before[name].get(k) != after[name].get(k)]
            words.append(f"{name}: " + ", ".join(f"{k} {json.dumps(before[name].get(k))} to {json.dumps(after[name].get(k))}" for k in keys))
    return "; ".join(words) or "their order changed"


def rule_changes(plan, old, moved_from=None):
    """The rules live in a file that the change under review can edit, so a change to them is said out loud."""
    if not isinstance(old, dict):
        return []
    out = [f"this changes the gate's own rules: the plan moved here from {moved_from}"] if moved_from else []
    for key in RULE_KEYS:
        was, now = old.get(key), plan.data.get(key)
        if was == now:
            continue
        if key == "kinds":
            out.append(f"this changes the gate's own rules: kinds: {_kinds_changed(was, now)}")
        elif _is_plain(was) and _is_plain(now):
            out.append(f"this changes the gate's own rules: {key} was {json.dumps(was)}, now {json.dumps(now)}")
        else:
            out.append(f"this changes the gate's own rules: {key} changed")
    return out


def deadline_moved(plan, old):
    """A deadline is not a rule of the gate, and moving one is still a thing a reviewer should read."""
    if not isinstance(old, dict) or old.get("deadline") == plan.data.get("deadline"):
        return None
    return render.one_line(f"the deadline moved: it was {old.get('deadline') or 'not set'}, now {plan.data.get('deadline') or 'not set'}")


def _plan_named_by(root, rel, staged_paths):
    """The plan a `.gitdone.json` at this path names, read as the commit will hold it; None if it is not usable."""
    from_index = gitio.git_here("show", ":" + rel)
    text = from_index.out if from_index.code == 0 else None
    if text is None:
        try:
            text = read_file(os.path.join(root, rel))
        except (OSError, UnicodeDecodeError):
            return None
    try:
        data = json.loads(text)
        if "status_doc" in data:
            return os.path.join(root, rel)
        return os.path.join(root, os.path.dirname(rel), os.path.expanduser(data["plan"]))
    except (ValueError, KeyError, TypeError, AttributeError):
        # A half-typed file on disk is nobody's commit. One that is being committed is this commit's business.
        return os.path.join(root, rel) if rel in staged_paths else None


def _staged_names(*extra):
    """What the index changes. A rename is two changes here: the commit takes the old name away too."""
    return gitio.git_here("diff", "--cached", "--no-renames", "--name-only", "-z", *extra)


def check_commit(strict=False, offline=False):
    """A hook with no --plan: the plans come from the files the commit changes, so that it serves a monorepo, and stays out of a
    branch with no tracker at all.
    """
    top = gitio.git_here("rev-parse", "--show-toplevel")
    staged = _staged_names()
    if top.code or staged.code:
        return [f"gitdone: cannot read this commit: {(top.err or staged.err).strip()}"], CANNOT_RUN
    root = os.path.realpath(top.out.strip())
    paths = [p for p in staged.out.split("\0") if p]
    plans, looked = {}, set()
    for path in paths:
        folder = os.path.dirname(path)
        while True:
            rel = f"{folder}/{POINTER}" if folder else POINTER
            if rel not in looked:
                looked.add(rel)
                found = _plan_named_by(root, rel, paths)
                if found and (found not in plans or rel in paths):
                    plans[found] = rel if rel in paths else plans.get(found)
            if not folder:
                break
            folder = os.path.dirname(folder)
    lines, worst = [], OK
    for plan_path, pointer in plans.items():
        more, code = check_staged(plan_path, strict=strict, offline=offline, pointer=pointer)
        lines.extend(more)
        order = [OK, MISSING, CONTRADICTION, CANNOT_RUN]
        worst = max(worst, code, key=order.index)
    return lines, worst


def _staged_as_a_link(path):
    """Whether the commit holds this path as a symbolic link, whatever the disk says."""
    return gitio.git_here("ls-files", "-s", "--", path).out.startswith("120000")


def check_staged(plan_path, strict=False, offline=False, pointer=None):
    """For a git hook: judge what the commit will contain, and stay out of a commit that does not touch the tracker. `pointer` is the staged
    pointer file that names this plan, if there is one.
    """
    top = gitio.git_here("rev-parse", "--show-toplevel")
    staged = _staged_names()
    if top.code or staged.code:
        return [f"gitdone: cannot read this commit: {(top.err or staged.err).strip()}"], CANNOT_RUN
    root = os.path.realpath(top.out.strip())
    names = {os.path.realpath(os.path.join(root, p)) for p in staged.out.split("\0") if p}
    given = os.path.expanduser(str(plan_path))
    if os.path.islink(given) or (pointer and _staged_as_a_link(pointer)):
        words = f"{pointer or plan_path} is a symbolic link; the tracker's files must be real files"
        if pointer or os.path.realpath(given) in names or {os.path.basename(n) for n in names} & USUAL_NAMES:
            return [f"gitdone: {words}"], CANNOT_RUN
        return [f"gitdone: this commit was not checked: {words}"], OK
    plan_path = os.path.realpath(given)
    deleted = _staged_names("--diff-filter=D")
    if plan_path in {os.path.realpath(os.path.join(root, p)) for p in deleted.out.split("\0") if p}:
        return ["gitdone: the tracker leaves with this commit"], OK
    try:
        plan = Plan(plan_path, read=_staged_reader(root, plan_path))
    except Exception as err:  # whatever is wrong with a plan, a commit that does not touch the tracker is not this gate's business
        words = err if isinstance(err, PlanError) else f"the plan cannot be used: {type(err).__name__}: {err}"
        # With no readable plan, nothing says where the table is. A commit touching what is usually the table cannot be judged.
        if plan_path in names or pointer or {os.path.basename(n) for n in names} & USUAL_NAMES:
            return [f"gitdone: {words}"], CANNOT_RUN
        return [f"gitdone: this commit was not checked: {words}"], OK
    tracked = {os.path.realpath(p) for p in plan.tracked}
    if gitio.git_here("config", "--bool", "core.ignorecase").out.strip() == "true":
        names, tracked = {n.lower() for n in names}, {t.lower() for t in tracked}
    if not names & tracked and not pointer:
        return [], OK
    lines, code = check(plan, strict=strict, offline=offline, staged=True)
    old, moved_from = plan_before(root, plan_path, _committed_show, pointer)
    moved = deadline_moved(plan, old)
    return lines + [f"NOTE {words}" for words in rule_changes(plan, old, moved_from)] + ([f"NOTE {moved}"] if moved else []), code


class Report:
    """What the gate found: the lines a person reads and the data a program reads come from the same place."""

    def __init__(self, strict):
        self.strict = strict
        self.error = None
        self.code = OK
        self.view_state = NOT_COMPARED
        self.head = []
        self.counts = None
        self.tally = {}
        self.verdict = None
        self.fails, self.missing, self.notes = [], [], []

    def result(self):
        if self.error:
            return "cannot run"
        if self.fails or (self.missing and self.strict):
            return "fail"
        return "warnings" if self.missing else "pass"

    def lines(self):
        if self.error:
            return [f"gitdone: {self.error}"]
        level = "FAIL" if self.strict else "WARN"
        out = list(self.head)
        for word, items in (("FAIL", self.fails), (level, self.missing), ("NOTE", self.notes)):
            for finding in items:
                out.append(f"{word} {finding.text}")
                if finding.next:
                    out.append(f"  {finding.next}")
        if self.fails:
            out.append(f"result: FAIL, {len(self.fails)} contradicted or inconsistent")
        elif self.missing and self.strict:
            out.append("result: FAIL in --strict, evidence is missing or partly disproved")
        elif self.missing:
            out.append("result: PASS with warnings; --strict would fail")
        else:
            out.append("result: PASS")
        return [render.printable(line) for line in out]

    def data(self):
        if self.error:
            return {"result": self.result(), "exit_code": self.code, "error": self.error}

        def findings(items):
            return [{"text": f.text, "rows": f.rows, **({"next": f.next} if f.next else {})} for f in items]
        return {
            "result": self.result(),
            "exit_code": self.code,
            "strict": self.strict,
            "view": self.view_state,
            "counts": self.counts,
            "evidence": self.tally,
            "verdict": self.verdict,
            "failures": findings(self.fails),
            "warnings": findings(self.missing),
            "notes": findings(self.notes),
        }


def report(plan, strict=False, offline=False, staged=False):
    """Run the gate. Returns a Report; a plan that cannot be read raises PlanError as it always has."""
    out = Report(strict)
    verifier = evidence.Verifier(plan, offline=offline)
    problem = verifier.problem()
    if problem:
        out.error, out.code = problem, CANNOT_RUN
        return out
    table = tables.load(plan)
    shape = plan.problems(table)
    out.fails.extend(Finding(text, []) for text in shape)
    if shape:
        out.head.append("view: not compared, the table's shape is broken")
    else:
        out.view_state, words = _view(plan, table, out.fails, staged)
        out.head.append(f"view: {words}")
        _badge(plan, table, out.fails, staged)
        out.counts = _counts(plan, table, out.fails)
        out.head.append(f"counts: {out.counts}")
    out.tally = _evidence(plan, table, verifier, out.fails, out.missing, out.notes, strict=strict)
    out.head.append("evidence: " + ", ".join(f"{out.tally[k]} {k}" for k in (evidence.VERIFIED, evidence.UNVERIFIED, "missing", evidence.CONTRADICTED)))
    _workstream_notes(plan, out.notes)
    if plan.requirements:
        _requirement_notes(plan, table, out.notes)
    note = verdict.annotate(plan)
    if note:
        out.verdict = note.line
        out.head.append(note.line)
        if note.flag:  # a QA run elsewhere changes this at any hour, so it never stops somebody's commit
            (out.notes if staged else out.missing).append(Finding(note.flag, []))
    out.code = CONTRADICTION if out.fails else (MISSING if out.missing and strict else OK)
    return out


def check(plan, strict=False, offline=False, staged=False):
    """Returns (lines to print, exit code)."""
    out = report(plan, strict=strict, offline=offline, staged=staged)
    return out.lines(), out.code
