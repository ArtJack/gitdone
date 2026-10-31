"""`report`: the evidence behind the numbers, row by row, for someone who has to trust them without opening the repository."""
import datetime

from . import evidence, gate, gitio, render, table as tables
from .plan import PlanError


def _commit_words(plan, value):
    if plan.repo is None or not evidence.SAFE_REF.match(str(value)):
        return None
    done = gitio.git(plan.repo, "log", "-1", "--format=%h%x00%as%x00%s", f"{value}^{{commit}}")
    if done.code or not done.out.strip():
        return None
    short, date, subject = done.out.strip().split("\0", 2)
    return {"commit": short, "date": date, "subject": subject}


def _pull_request_words(verifier, number):
    if isinstance(verifier._prs, dict) and number in verifier._prs:
        pr = verifier._prs[number]
        merged = str(pr.get("mergedAt") or "")[:10]
        landed = pr.get("mergeCommit") or {}
        return {"title": pr.get("title", ""), "date": merged, "url": pr.get("url", ""), "commit": str(landed.get("oid") or "")[:12] or None}
    return None


def _claim_data(plan, verifier, claim):
    result = verifier.claim(claim)
    item = {"kind": claim.kind, "value": claim.value, "state": result.state, "detail": result.detail}
    if claim.kind in ("sha", "bare", "ref") and verifier.repo is not None:
        # An id resolves to objects, never to a tag named like it, here as in the gate. Words of the plan's own pattern may name a tag.
        full = verifier._resolve_id(claim.value) if evidence.HEX_ID.match(str(claim.value)) else f"refs/tags/{claim.value}"
        item["found"] = _commit_words(plan, full) if full else None
    elif claim.kind == "tag":
        item["found"] = _commit_words(plan, f"refs/tags/{claim.value}")
    elif claim.kind == "pr":
        item["found"] = _pull_request_words(verifier, claim.value)
    return item


def rows_data(plan, offline=False):
    """Every row with what it claims and what git and gh say about each claim."""
    table = tables.load_clean(plan)
    verifier = evidence.Verifier(plan, offline=offline)
    problem = verifier.problem()
    if problem:  # what stops the gate stops the report: a shallow clone must not read as verified
        raise PlanError(problem)
    out = []
    for domain in table.domains:
        for row in domain.rows:
            if row.prose:
                out.append({"row": row.num, "name": "", "kind": row.kind, "domain": domain.name, "note": "", "claims": [], "prose": True})
                continue
            rule = next((k.evidence for k in plan.kinds if k.name == row.kind), None)
            claims = []
            if rule == "release":
                claims = [_claim_data(plan, verifier, c) for c in evidence.release_claims(plan, row.words())]
            elif rule == "branch":
                for name in evidence.branch_names(plan, row):
                    result, _ = verifier.branch_named(name)
                    claims.append({"kind": "branch", "value": name, "state": result.state, "detail": result.detail})
            out.append({"row": row.num, "name": row.name, "kind": row.kind, "domain": domain.name, "note": row.note,
                        "rule": rule, "claims": claims})
    return out


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def _said(claim):
    words = claim["detail"]
    found = claim.get("found")
    if found:
        said = found.get("subject") or found.get("title")
        if said:
            words += " (" + ", ".join(part for part in (found.get("date"), said) if part) + ")"
    return _cell(words)


def markdown(plan, offline=False, today=None):
    today = today or datetime.date.today().isoformat()
    table = tables.load_clean(plan)
    data = rows_data(plan, offline=offline)
    outcome = gate.report(plan, offline=offline)
    L = [f"# {plan.title}: evidence (generated {today})", "",
         f"> {render.opener(plan, table)}", ">",
         f"> The gate: {outcome.result()}. {', '.join(f'{outcome.tally.get(k, 0)} {k}' for k in (evidence.VERIFIED, evidence.UNVERIFIED, 'missing', evidence.CONTRADICTED))}."]
    if plan.release:
        L += [">", f"> Release: {plan.release}."]
    L.append("")
    for kind in plan.kinds:
        rows = [r for r in data if r["kind"] == kind.name and not r.get("prose")]
        prose = sum(1 for r in data if r["kind"] == kind.name and r.get("prose"))
        if not rows and not prose:
            continue
        L += [f"## {kind.name}: {len(rows) + prose} of {len(data)}", ""]
        if rows:
            if kind.evidence in ("release", "branch"):
                L += ["| # | Row | Named | What git or the forge says |", "|---|---|---|---|"]
                for row in rows:
                    if not row["claims"]:
                        L.append(f"| {row['row']} | {_cell(row['name'])} | nothing | **no evidence named** |")
                    for i, claim in enumerate(row["claims"]):
                        first = f"{row['row']} | {_cell(row['name'])}" if i == 0 else " | "
                        L.append(f"| {first} | {_cell(claim['value'])} | {_said(claim)} |")
            else:
                L += ["| # | Row | Note |", "|---|---|---|"]
                for row in rows:
                    L.append(f"| {row['row']} | {_cell(row['name'])} | {_cell(row['note'])} |")
        if prose:
            L += ["", f"{prose} more rows are counted in domains that have no table yet."]
        L.append("")
    L += ["## What this cannot tell", "",
          "A commit on the default branch proves the commit is there, not that it holds the feature. A row's status is a",
          "person's claim, and this report holds the claim to its evidence. No percentage is a date.", ""]
    return "\n".join(L)
