"""`doctor`: everything that has to be true for the tracker to work here, on one screen. It changes nothing."""
import os
import re
import shlex
import sys

from . import __version__, evidence, gate, gitio, render, table as tables
from .install import HOOKS, is_ours
from .plan import Plan, PlanError, read_file

OK, WARN, FAIL = "ok", "warn", "fail"


def _item(state, name, detail):
    return {"state": state, "name": name, "detail": detail}


def _hook(plan):
    top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top.code:
        return _item(WARN, "hook", f"{plan.doc.name} is not in a git repository, so there is nowhere to put a hook")
    where = gitio.git(top.out.strip(), "rev-parse", "--git-path", "hooks").out.strip()
    hooks = where if os.path.isabs(where) else os.path.join(top.out.strip(), where)
    missing, moved, lenient = [], [], False
    for name in HOOKS:
        path = os.path.join(hooks, name)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            missing.append(name)
            continue
        if not is_ours(text):
            missing.append(f"{name} (someone else's)")
            continue
        lenient = lenient or "--strict" not in text
        if not os.access(path, os.X_OK):
            return _item(WARN, "hook", f"{name} is not executable, so git ignores it: run `gitdone install-hook`")
        if "\nexit 0\ntop=" in text or not text.rstrip().endswith("exit 0"):
            return _item(WARN, "hook", f"{name} was edited by hand: run `gitdone install-hook`")
        home = re.search(r"^home=(.*)$", text, re.M)
        if home and not os.path.exists(os.path.join("".join(shlex.split(home.group(1))), "gitdone", "__main__.py")):
            moved.append(name)
    if missing:
        return _item(WARN, "hook", f"not installed ({', '.join(missing)}): run `gitdone install-hook`")
    if moved:
        return _item(WARN, "hook", f"{', '.join(moved)} names an engine that has moved; it falls back to PATH. Run `gitdone install-hook`")
    if lenient:
        return _item(WARN, "hook", "lenient: a Live row with no evidence only warns. Run `gitdone install-hook` to make it strict")
    return _item(OK, "hook", "pre-commit and pre-merge-commit run the gate, strict")


def _gh(plan, table, offline):
    named = [n for r in table.rows.values() for n in evidence.find_prs(f"{r.status} {r.note}")]
    if not named:
        return _item(OK, "gh", "no row names a pull request, so it is not needed")
    if offline:
        return _item(OK, "gh", f"{len(named)} pull requests named; not asked, because of --offline")
    done = gitio.gh_status()
    if done is None:
        return _item(OK, "gh", f"{len(named)} pull requests named, and gh is logged in")
    return _item(WARN, "gh", f"{len(named)} pull requests named, and {done}: they stay unverified")


def _time_and_scope(plan, table):
    """Nothing here is broken if it says no: these are what the tracker can tell, not what it needs."""
    from . import forecast, requirements
    out = []
    try:
        out.append(_item(OK, "date", forecast.headline(forecast.data(plan))))
    except Exception as err:
        out.append(_item(WARN, "date", render.one_line(err)))
    if plan.requirements:
        try:
            found = requirements.coverage(plan, table)
        except Exception as err:
            return out + [_item(WARN, "scope", render.one_line(err))]
        count = len(found["items"]) - len(found["without"])
        words = f"{count} of {len(found['items'])} have a row" + "".join(f"; {p}" for p in found["problems"])
        out.append(_item(WARN if found["without"] or found["problems"] else OK, "scope", f"requirements: {words}"))
    return out


def run(plan_path, offline=False):
    """(items, exit code). Exit 0 unless something is plainly broken."""
    python = ".".join(str(v) for v in sys.version_info[:3])
    items = [_item(OK, "engine", f"{__version__} on Python {python}")]
    if plan_path is None:
        items.append(_item(FAIL, "plan", "no .gitdone.json here or above: run `gitdone init`"))
        return items, 1
    try:
        plan = Plan(plan_path)
        table = tables.load(plan)
    except PlanError as err:
        items.append(_item(FAIL, "plan", str(err)))
        return items, 1
    items.append(_item(OK, "plan", f"{plan.path}: {len(plan.kinds)} kinds, {len(plan.workstreams)} workstreams"))
    problems = plan.problems(table)
    if problems:
        items.append(_item(FAIL, "table", "; ".join(problems)))
        return items, 1
    items.append(_item(OK, "table", f"{plan.doc.name}: {len(table.rows)} rows in {len(table.domains)} domains"))
    if plan.repo is None:
        items.append(_item(WARN, "repo", "the plan names no repo, so no evidence can be verified: set \"repo\": \".\""))
    else:
        remote = gitio.git(plan.repo, "remote").out.split()
        verifier = evidence.Verifier(plan, offline=True)
        problem = verifier.problem()
        if problem:
            items.append(_item(FAIL, "repo", problem))
            return items, 1
        items.append(_item(OK, "repo", f"{plan.repo}: default branch {plan.default_branch}, " + (f"remote {remote[0]}" if remote else "no remote")))
    items.append(_gh(plan, table, offline))
    items.append(_hook(plan))
    fresh = render.normalize(render.status_md(plan, table))
    try:
        same = render.normalize(read_file(plan.out)) == fresh
    except (OSError, UnicodeDecodeError):
        same = None
    if same is None:
        items.append(_item(FAIL, "view", f"{plan.out.name} does not exist: run `{plan.regenerate}`"))
    elif same:
        items.append(_item(OK, "view", f"{plan.out.name} matches a fresh render"))
    else:
        items.append(_item(FAIL, "view", f"{plan.out.name} is out of date: run `{plan.regenerate}`"))
    report = gate.report(plan, offline=True)
    tally = report.tally
    state = FAIL if tally.get(evidence.CONTRADICTED) else (WARN if tally.get("missing") else OK)
    words = ", ".join(f"{tally.get(k, 0)} {k}" for k in (evidence.VERIFIED, evidence.UNVERIFIED, "missing", evidence.CONTRADICTED))
    findings = report.fails + report.missing
    if findings:
        words += f". {findings[0].text}" + (f"; and {len(findings) - 1} more: `gitdone check`" if len(findings) > 1 else "")
    items.append(_item(state, "evidence", words))
    items.extend(_time_and_scope(plan, table))
    return items, 1 if any(i["state"] == FAIL for i in items) else 0


def lines(items):
    return [f"{i['state']:<5}{i['name']:<10}{i['detail']}" for i in items]
