"""`ci`: the gate in a pull request. Annotations on the table's lines, a summary, one sticky comment, and a badge branch.

Everything GitHub-specific is here and in action.yml. The comment and the badge are favours: if the token cannot write, it
says so and the gate's exit code still decides.
"""
import json
import os
import pathlib

from . import badge, chart, evidence, gate, gitio, history, render, table as tables
from .discover import POINTER
from .plan import PlanError

MARKER = "<!-- gitdone -->"
BOT = ["-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]


def _escape_data(text):
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text):
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotations(plan, table, report, cwd=None):
    """GitHub workflow commands: a finding about a row lands on that row's line in the pull request's diff."""
    try:  # GitHub places an annotation by its path from the repository's root, whatever folder the step ran in
        rel = os.path.relpath(plan.doc, cwd or os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
    except ValueError:  # another drive on Windows
        rel = str(plan.doc)
    rel = pathlib.PurePath(rel).as_posix()
    strict = "error" if report.strict else "warning"
    out = []
    for level, findings in (("error", report.fails), (strict, report.missing), ("notice", report.notes)):
        for finding in findings:
            lines = [table.rows[n].line for n in finding.rows if n in table.rows and table.rows[n].line is not None]
            where = f"file={_escape_property(rel)}"
            if lines:
                where += f",line={lines[0] + 1}"
            out.append(f"::{level} {where},title=gitdone::{_escape_data(gate.said(finding))}")
    return out


def event():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def touched(plan, base):
    """Whether the changes since `base` touch the plan, the table or the view. True when git cannot say."""
    top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top.code or not evidence.SAFE_REF.match(str(base)):
        return True
    done = gitio.git(top.out.strip(), "diff", "--no-renames", "--name-only", "-z", f"{base}...HEAD")
    if done.code:
        return True
    names = {os.path.realpath(os.path.join(top.out.strip(), p)) for p in done.out.split("\0") if p}
    return bool(names & {os.path.realpath(p) for p in plan.tracked}) or any(os.path.basename(n) == POINTER for n in names)


def rule_changes(plan, base):
    """What this change does to the gate's own rules, compared with the base. The plan is a file a pull request can edit."""
    top = gitio.git(plan.path.parent, "rev-parse", "--show-toplevel")
    if top.code or not evidence.SAFE_REF.match(str(base)):
        return []
    root = os.path.realpath(top.out.strip())

    def show(path):
        done = gitio.git(root, "show", f"{base}:{path}")
        return done.out if done.code == 0 else None
    old, moved_from = gate.plan_before(root, os.path.realpath(plan.path), show)
    return gate.rule_changes(plan, old, moved_from)


def summary(plan, table, report, base=None, branch=None):
    """The comment and the step summary: the numbers, what moved against the base, what the gate said."""
    data = render.opener_data(plan, table)
    verdict_words = {"pass": "PASS", "warnings": "PASS with warnings", "fail": "FAIL", "cannot run": "COULD NOT RUN"}[report.result()]
    L = [MARKER, f"**gitdone** · gate: **{verdict_words}**", "", "| | Rows | Strict | Weighted | |", "|---|---|---|---|---|"]
    for g in data["groups"]:
        L.append(f"| {g['label']} | {g['rows']} | {g['strict_rows']} ({render.pct(g['strict'])}) | {render.pct(g['weighted'])} | `{render.bar(g['weighted'], 12)}` |")
    L.append("")
    if base:
        try:
            L += [f"Against `{branch or 'the base'}`: {history.delta(plan, since=base)}", ""]
        except PlanError:
            L += [f"The status table is new against `{branch or 'the base'}`.", ""]
    if data["next"]:
        needs = f" Needs {data['next']['needs']}." if data["next"]["needs"] else ""
        L += [f"Next: **{data['next']['id']}** {data['next']['name']}.{needs}", ""]
    moved_rules = rule_changes(plan, base) if base else []
    if moved_rules:
        L += ["**⚠ This pull request changes the gate's own rules. Review these lines first:**", ""]
        L += [f"- {words}" for words in moved_rules]
        L.append("")
    findings = report.fails + report.missing
    if findings:
        L += ["<details open><summary>What the gate found</summary>", ""]
        L += [f"- {gate.said(f)}" for f in findings]
        L += ["", "</details>", ""]
    return "\n".join(L)


def _gh(args, stdin_text=None):
    env = gitio.clean_env()
    env["GH_PROMPT_DISABLED"] = "1"
    return gitio._run(["gh", *args], env=env, timeout=gitio.GH_TIMEOUT, stdin_text=stdin_text)


def sticky_comment(repository, number, body):
    """Update this tool's comment on a pull request, or add one. Returns None, or words saying why it could not."""
    found = _gh(["api", "--paginate", f"repos/{repository}/issues/{number}/comments", "--jq",
                 f'.[] | select(.user.type == "Bot" and (.body | startswith("{MARKER}"))) | .id'])
    if found.code:
        return (found.err.strip().splitlines() or ["gh could not read the comments"])[0]
    ids = found.out.split()
    payload = json.dumps({"body": body})
    if ids:
        done = _gh(["api", "-X", "PATCH", f"repos/{repository}/issues/comments/{ids[0]}", "--input", "-"], stdin_text=payload)
    else:
        done = _gh(["api", "-X", "POST", f"repos/{repository}/issues/{number}/comments", "--input", "-"], stdin_text=payload)
    return None if done.code == 0 else (done.err.strip().splitlines() or ["gh could not write the comment"])[0]


def publish(repo, branch, files, message):
    """Commit files to a branch without touching the work tree, and push it. Returns words saying what happened."""
    if not evidence.SAFE_REF.match(branch):
        return f"{branch!r} cannot be a branch name"
    remote = gitio.git(repo, "ls-remote", "origin", f"refs/heads/{branch}")
    parent = remote.out.split()[0] if remote.code == 0 and remote.out.strip() else None
    if parent and gitio.git(repo, "fetch", "-q", "origin", branch).code:
        return f"could not fetch {branch}"
    entries = {}
    if parent:  # the files join what the branch holds; they never replace it
        for entry in gitio.git(repo, "ls-tree", "-z", parent).out.split("\0"):
            meta, tab, name = entry.partition("\t")
            if tab:
                entries[name] = meta
    for name, text in sorted(files.items()):
        blob = gitio.git(repo, "hash-object", "-w", "--stdin", stdin_text=text)
        if blob.code:
            return f"could not store {name}: {blob.err.strip()}"
        entries[name] = f"100644 blob {blob.out.strip()}"
    tree = gitio.git(repo, "mktree", "-z", stdin_text="".join(f"{meta}\t{name}\0" for name, meta in entries.items()))
    if tree.code:
        return f"could not build the tree: {tree.err.strip()}"
    tree_id = tree.out.strip()
    if parent and gitio.git(repo, "rev-parse", f"{parent}^{{tree}}").out.strip() == tree_id:
        return f"{branch} already holds these files"
    args = [*BOT, "commit-tree", tree_id, "-m", message]
    if parent:
        args[len(BOT) + 2:len(BOT) + 2] = ["-p", parent]
    commit = gitio.git(repo, *args)
    if commit.code:
        return f"could not commit: {commit.err.strip()}"
    pushed = gitio.git(repo, "push", "-q", "origin", f"{commit.out.strip()}:refs/heads/{branch}")
    if pushed.code:
        return f"could not push {branch}: {(pushed.err.strip().splitlines() or ['no output'])[0]}"
    return f"published to {branch}"


def badge_files(plan, table):
    return {"badge.svg": badge.svg(plan, table), "badge.json": json.dumps(badge.endpoint(plan, table)) + "\n",
            "burnup.svg": chart.svg(chart.points(plan), plan.title), "burnup.csv": chart.csv_text(chart.points(plan))}


def _append(env_name, text):
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def run(plan, strict=False, comment=True, base=None, publish_branch=None, always=False):
    """Prints the annotations, writes the summary and the outputs, and returns the gate's exit code."""
    payload = event()
    pr = payload.get("pull_request") or {}
    base = base or (pr.get("base") or {}).get("sha")
    branch = (pr.get("base") or {}).get("ref")
    if pr and base and not always and not touched(plan, base):
        print("gitdone: this pull request does not touch the tracker, so it is not judged")
        _append("GITHUB_OUTPUT", "result=not touched\nexit-code=0\n")
        return gate.OK
    report = gate.report(plan, strict=strict)
    if report.error:
        print(f"::error title=gitdone::{_escape_data(report.error)}")
        _append("GITHUB_OUTPUT", f"result=cannot run\nexit-code={report.code}\n")
        return report.code
    table = tables.load(plan)
    for line in report.lines():
        print(" ".join(str(line).split("\n")))  # words from a plan must not be able to start a workflow command
    repository = os.environ.get("GITHUB_REPOSITORY")
    if plan.problems(table):
        body = "\n".join([MARKER, "**gitdone** · gate: **FAIL**", "", "The status table and the plan disagree:", ""]
                         + [f"- {gate.said(f)}" for f in report.fails] + [""])
        _append("GITHUB_STEP_SUMMARY", body + "\n")
        _append("GITHUB_OUTPUT", f"result=fail\nexit-code={report.code}\n")
        if comment and pr.get("number") and repository:
            sticky_comment(repository, pr["number"], body)
        return report.code
    for line in annotations(plan, table, report):
        print(line)
    for words in rule_changes(plan, base) if base else []:
        print(f"::warning title=gitdone::{_escape_data(words)}")
    body = summary(plan, table, report, base=base, branch=branch)
    _append("GITHUB_STEP_SUMMARY", body + "\n")
    strict_number, weighted_number = badge.numbers(plan, table)
    _append("GITHUB_OUTPUT", f"result={report.result()}\nexit-code={report.code}\n"
                             f"strict={render.pct(strict_number)}\nweighted={render.pct(weighted_number)}\n")
    if comment and pr.get("number") and repository:
        why = sticky_comment(repository, pr["number"], body)
        if why:
            print(f"::warning title=gitdone::could not comment on the pull request: {_escape_data(why)}")
    if publish_branch and not pr:
        _publish_step(plan, table, publish_branch)
    return report.code


def _publish_step(plan, table, branch):
    """A favour: whatever goes wrong here says so, and the gate's exit code still decides."""
    ref = os.environ.get("GITHUB_REF_NAME")
    if ref and ref != plan.default_branch:
        print(f"gitdone: not publishing from {ref}: only {plan.default_branch}'s numbers go on {branch}")
    elif branch == plan.default_branch:
        print(f"::warning title=gitdone::refusing to publish onto {branch}, the default branch")
    elif plan.repo is None:
        print("::warning title=gitdone::the plan names no repo, so there is nowhere to publish the badge")
    else:
        try:
            print(publish(plan.repo, branch, badge_files(plan, table), f"status: {badge.message(plan, table)}"))
        except PlanError as err:
            print(f"::warning title=gitdone::could not publish: {_escape_data(err)}")
