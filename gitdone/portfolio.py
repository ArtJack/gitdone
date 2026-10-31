"""`portfolio`: every tracked project under a folder, on one page. It reads each tracker and changes nothing."""
import datetime
import pathlib

from . import evidence, forecast, gate, render, table as tables
from .discover import POINTER, find_plan
from .plan import Plan, PlanError


def _projects(roots):
    for root in roots:
        root = pathlib.Path(root).expanduser().resolve()
        if (root / POINTER).is_file():
            yield root
            continue
        if root.is_dir():
            for child in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
                if (child / POINTER).is_file():
                    yield child


def _entry(directory):
    entry = {"project": directory.name, "path": str(directory)}
    try:
        return {**entry, **_numbers(directory)}
    except PlanError as err:
        return {**entry, "error": str(err)}
    except Exception as err:  # one broken project must not lose the whole page
        return {**entry, "error": f"could not run: {type(err).__name__}: {err}"}


def _numbers(directory):
    plan = Plan(find_plan(directory))
    table = tables.load_clean(plan)
    rows = [r for d in table.domains for r in d.rows]
    top = sum(1 for r in rows if r.kind == plan.strict_kind.name)
    following = render.opener_data(plan, table)["next"]
    report = gate.report(plan, offline=True)
    try:
        likely = forecast.data(plan)["likely"]
    except PlanError:  # a tracker outside any repository has no pace, and the rest of its line still stands
        likely = None
    return {"likely": likely, "title": plan.title, "rows": len(rows), "strict_rows": top, "strict": top / len(rows) if rows else 0.0,
            "weighted": tables.score(rows, plan.weights), "next": following["id"] if following else None,
            "next_name": following["name"] if following else None, "gate": report.result(),
            "contradicted": report.tally.get(evidence.CONTRADICTED, 0), "missing": report.tally.get("missing", 0)}


def scan(roots):
    return [_entry(directory) for directory in _projects(roots)]


def markdown(entries, today=None):
    today = today or datetime.date.today().isoformat()
    L = [f"# Portfolio (generated {today})", "", "> Read offline from each project's tracker: a pull request is left unverified, and nothing is written.", "",
         "| Project | Rows | Strict | Weighted | | Likely done | Next | Gate |", "|---|---|---|---|---|---|---|---|"]
    for e in entries:
        if "error" in e:
            first = " ".join(e["error"].split())[:120]
            L.append(f"| {e['project']} |  |  |  |  |  |  | cannot run: {first} |")
            continue
        following = f"{e['next']} {e['next_name']}".strip() if e["next"] else ""
        gate_words = {"pass": "pass", "warnings": f"pass, {e['missing']} missing", "fail": f"**fail**, {e['contradicted']} contradicted"}.get(e["gate"], e["gate"])
        L.append(f"| {e['project']} | {e['rows']} | {e['strict_rows']} ({render.pct(e['strict'])}) | {render.pct(e['weighted'])} | "
                 f"`{render.bar(e['weighted'], 10)}` | {e['likely'] or ''} | {following} | {gate_words} |")
    if not entries:
        L.append(f"|  |  |  |  |  |  |  | no {POINTER} found |")
    return "\n".join(L) + "\n"
