"""`matrix`: a traceability matrix an agent can keep true. Requirement to row to evidence to tests, read from the plan, the table and git, so
nobody fills it in by hand. A test listed here exists, and came with the work or is named in the row's note. Whether it passes is your CI's
word, or Verdict's. The tool does not run it, and it does not judge whether the code does what the requirement says.
"""
import datetime
import re

from . import focus, gitio, render, report, requirements, table as tables

BACKTICKED = re.compile(r"`([^`\s]+)`")
MOST_TESTS_SHOWN = 3
TEST_CODE = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".rb", ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".groovy", ".swift", ".m", ".c", ".cc", ".cpp", ".cs", ".fs",
             ".php", ".sh", ".bash", ".bats", ".ex", ".exs", ".erl", ".clj", ".lua", ".dart", ".r", ".pl", ".pm", ".feature", ".robot")
NOT_TESTS = ("fixtures/*", "*/fixtures/*", "testdata/*", "*/testdata/*", "tests/data/*", "*/tests/data/*", "test/data/*", "*/test/data/*", "spec/data/*", "*/spec/data/*", "*/__snapshots__/*", "*/snapshots/*",
             "__init__.py", "*/__init__.py", "conftest.py", "*/conftest.py")


def _is_test(path):
    """What a test's folder holds is not all tests. A test is code, and a fixture or a data file a commit touched says nothing about a row being tested."""
    return focus.matches(path, focus.TESTS) and path.lower().endswith(TEST_CODE) and not focus.matches(path, NOT_TESTS)


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def _evidence_commits(row):
    return [c["found"]["commit"] for c in row["claims"] if c.get("found") and c["found"].get("commit")]


def _files_by_commit(repo, shas):
    """{full sha: [paths]} of commits in one process. A merge is what it brought to its first parent."""
    if not shas:
        return {}
    out = {}
    for commit in focus.read_commits(repo, "--no-walk", "-m", "--first-parent", *sorted(set(shas))):
        out[commit["sha"]] = [path for path, _ in commit["files"]]
    return out


def _since_the_table(plan, repo):
    """What keeps a walk to the table's first commit and what came after it, and None if it has none: `row 1` in a commit from before there was a row 1 was about something else."""
    if focus._top(repo) != focus._top(plan.doc.parent):
        return []
    first = focus._first_table_commit(plan)
    return [f"^{first}^@"] if first else None


def _naming_commits(repo, known, limit):
    """{row: [(sha, paths)]} from every commit in reach whose message names a row."""
    out = {}
    for commit in focus.read_commits(repo, "-i", "--grep=row", "--no-merges", "HEAD", *limit) if limit is not None else ():
        for num in focus.named_rows(commit["message"], known):
            out.setdefault(num, []).append((commit["sha"], [path for path, _ in commit["files"]]))
    return out


def _tree(repo):
    done = gitio.git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    return set(done.out.split("\0")) if done.code == 0 else set()


def _says_tests(note, tree):
    return [word for word in BACKTICKED.findall(note) if word in tree and _is_test(word)]


def rows_data(plan, offline=False):
    """Every row with the evidence behind it, the commits that name it, and the tests that came with them and still exist."""
    base = report.rows_data(plan, offline=offline)
    repo = plan.repo or plan.dir
    known = {r["row"] for r in base if not r.get("prose")}
    if not focus.is_repository(repo):  # with no repository there is nothing to tie a row to, and the rows themselves still stand
        return [{**row, "named_by": [], "tests": []} for row in base if not row.get("prose")]
    tree = _tree(repo)
    to_plan = focus._from_plan_folder(repo, plan.dir)
    named_in_a_note = tree | {to_plan(path) for path in tree}  # from the plan's folder, as its other paths are, or from the folder it names as `repo`
    cited = {row["row"]: _evidence_commits(row) for row in base}
    full = {}
    for shas in cited.values():
        for sha in shas:
            resolved = gitio.git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
            if resolved.code == 0:
                full[sha] = resolved.out.strip()
    files = _files_by_commit(repo, full.values())
    naming = _naming_commits(repo, known, _since_the_table(plan, repo))
    out = []
    for row in base:
        if row.get("prose"):
            continue
        num = row["row"]
        touched = [path for sha in cited[num] for path in files.get(full.get(sha), [])]
        commits = [sha[:7] for sha, _ in naming.get(num, [])]
        for _, paths in naming.get(num, []):
            touched += paths
        tests = sorted({path for path in touched if path in tree and _is_test(path)} | set(_says_tests(row["note"], named_in_a_note)))
        out.append({**row, "named_by": commits, "tests": tests})
    return out


def data(plan, offline=False):
    table = tables.load_clean(plan)
    rows = rows_data(plan, offline=offline)
    by_number = {r["row"]: r for r in rows}
    found = requirements.coverage(plan, table)
    entries = [{"id": item.ident, "words": item.words, "where": item.where(), "rows": [r.num for r in mine], "looks_like": item.near.num if item.near is not None else None} for item, mine in found["items"]]
    top = plan.strict_kind.name
    live = [r for r in rows if r["kind"] == top]
    finished = [e for e in entries if e["rows"] and all(by_number[n]["kind"] == top for n in e["rows"])]
    return {"requirements": entries, "rows": rows, "problems": found["problems"],
            "summary": {"requirements": len(entries), "with_a_row": sum(1 for e in entries if e["rows"]), "without_a_row": [e["where"] for e in entries if not e["rows"]],
                        "requirements_finished": len(finished),
                        "rows": len(rows), "rows_nobody_asked_for": [r.num for r in found["unasked"]],
                        "live": len(live), "live_without_a_test": [r["row"] for r in live if not r["tests"]],
                        "with_a_test": sum(1 for r in rows if r["tests"])},
            "by_number": {str(n): r["kind"] for n, r in by_number.items()}}


def _evidence_cell(row):
    words = []
    for claim in row["claims"]:
        mark = {"verified": "", "contradicted": " ✗"}.get(claim["state"], " ?")
        value = claim["value"]
        if claim["kind"] in ("sha", "bare", "ref"):
            words.append(f"`{str(value)[:7]}`{mark}")
        elif claim["kind"] == "pr":
            words.append(f"PR #{value}{mark}")
        elif claim["kind"] == "mr":
            words.append(f"MR !{value}{mark}")
        else:
            words.append(f"{_cell(value)}{mark}")
    return ", ".join(words)


def _tests_cell(row):
    tests = row["tests"]
    shown = ", ".join(f"`{_cell(path)}`" for path in tests[:MOST_TESTS_SHOWN])
    return shown + (f", and {len(tests) - MOST_TESTS_SHOWN} more" if len(tests) > MOST_TESTS_SHOWN else "")


def _row_line(row, lead=""):
    named = ", ".join(f"`{sha}`" for sha in row["named_by"][:3]) + (f", and {len(row['named_by']) - 3} more" if len(row["named_by"]) > 3 else "")
    return f"| {lead}{row['row']} | {_cell(row['name'])} | {_cell(row['kind'])} | {_evidence_cell(row)} | {named} | {_tests_cell(row)} |"


def markdown(plan, offline=False, today=None):
    today = today or datetime.date.today().isoformat()
    found = data(plan, offline=offline)
    s = found["summary"]
    by_number = {r["row"]: r for r in found["rows"]}
    title = " ".join(str(plan.title).split())
    L = [f"# {title}: traceability matrix (generated {today})", "",
         "> Read from the plan, the status table and git. A test listed here exists; whether it passes is your CI's word. "
         "This does not judge whether the code does what a requirement says.", ""]
    headline = []
    if found["requirements"]:
        headline.append(f"**{s['with_a_row']} of {s['requirements']} requirements have a row, and {s['requirements_finished']} are fully {_cell(plan.strict_kind.name)} ({render.pct(s['requirements_finished'] / s['requirements'])}).**")
        if s["rows_nobody_asked_for"]:
            headline.append(f"{len(s['rows_nobody_asked_for'])} of {s['rows']} rows answer to no requirement.")
    headline.append(f"{s['live'] - len(s['live_without_a_test'])} of {s['live']} {_cell(plan.strict_kind.name)} rows have a test on record.")
    L += [" ".join(headline), ""]
    if found["requirements"]:
        L += ["| Requirement | Where | Row | Status | Evidence | Tests |", "|---|---|---|---|---|---|"]
        for entry in found["requirements"]:
            label = _cell(f"{entry['id']} {entry['words']}".strip() if entry["id"] else entry["words"])
            if not entry["rows"]:
                near = f" (row {entry['looks_like']} looks like it)" if entry["looks_like"] else ""
                L.append(f"| {label} | {_cell(entry['where'])} | **no row**{near} | | | |")
            for num in entry["rows"]:
                row = by_number[num]
                L.append(f"| {label} | {_cell(entry['where'])} | {num} | {_cell(row['kind'])} | {_evidence_cell(row)} | {_tests_cell(row)} |")
        L.append("")
    unasked = s["rows_nobody_asked_for"]
    if unasked:
        L += ["## Rows no requirement asks for", "", "| # | Name | Status | Evidence | Named by | Tests |", "|---|---|---|---|---|---|"]
        L += [_row_line(by_number[n]) for n in unasked]
        L.append("")
    if not found["requirements"]:
        L += ["| # | Name | Status | Evidence | Named by | Tests |", "|---|---|---|---|---|---|"]
        L += [_row_line(r) for r in found["rows"]]
        L.append("")
    if found["problems"]:
        L += ["## Could not be read", ""] + [f"- {_cell(p)}" for p in found["problems"]] + [""]
    return "\n".join(L)
