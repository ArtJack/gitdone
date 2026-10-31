"""A percent done you can defend: strict and weighted completion from one plan and one status table, each claim held to git."""
import argparse
import json
import os
import pathlib
import sys

from . import __version__, discover, gate, render, shipped, table as tables, verdict
from .plan import Plan, PlanError, read_file

# The commands a hook or a session starts run on every commit and session, so the rest is imported when it is asked for.


def _plan(args):
    if args.plan:
        return Plan(args.plan)
    found = discover.find_plan()
    if found is None:
        raise PlanError(f"no {discover.POINTER} here or above: run `gitdone init`, or pass --plan")
    return Plan(found)


def _annotate(plan, stream):
    line = verdict.release_line(plan)
    if line and plan.verdict_state is not None:
        print(line, file=stream)


def cmd_render(args):
    plan = _plan(args)
    table = tables.load_clean(plan)
    if args.write:
        shipped.write_view(plan, table)
        print("wrote", plan.out)
        if plan.badge:
            print("wrote", plan.badge)
        _annotate(plan, sys.stdout)
    else:
        # The view on stdout stays byte-exact for a pipe; the QA record goes beside it, on stderr.
        _annotate(plan, sys.stderr)
        print(render.status_md(plan, table), end="")
    return 0


def cmd_counts(args):
    plan = _plan(args)
    table = tables.load_clean(plan)
    fresh = render.counts_table(plan, table)
    if not args.write:
        print(fresh)
        return 0
    text, newline = shipped.read_keeping_newlines(plan.doc)
    if not render.embedded_counts(text):
        raise PlanError(f"{plan.doc.name} holds no counts table to update; paste the output of `counts` into it once")
    plan.check_writable(plan.doc)
    shipped.write_atomically(plan.doc, render.splice_counts(text, fresh), newline)
    print("updated the counts table in", plan.doc)
    return 0


def _print_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_check(args):
    if args.json:
        if args.if_staged:
            raise PlanError("--json and --if-staged do not go together: a hook has no reader for it")
        out = gate.report(_plan(args), strict=args.strict, offline=args.offline)
        args.exit_code = out.code
        _print_json(out.data())
        return out.code
    if args.if_staged and args.plan:
        lines, code = gate.check_staged(args.plan, strict=args.strict, offline=args.offline)
    elif args.if_staged:
        lines, code = gate.check_commit(strict=args.strict, offline=args.offline)
    else:
        lines, code = gate.check(_plan(args), strict=args.strict, offline=args.offline)
    args.exit_code = code  # a reader that stops early must not change what the gate said
    stream = sys.stderr if args.if_staged and code else sys.stdout
    for line in lines:
        # A commit that passes says only what it should know; the rest is a plain `check` away.
        if args.if_staged and code == 0 and line.startswith(("view:", "counts:", "evidence:")):
            continue
        print(line, file=stream)
    return code


def _gate_line(plan):
    """The headline must not outlive the gate: if a claim stopped holding, say so beside the number. Read offline."""
    report = gate.report(plan, offline=True)
    if report.error:
        return None
    if report.fails:
        count = len(report.fails)
        if count == 1:
            return f"⚠ the gate fails: {report.fails[0].text}; run `gitdone check`"
        return f"⚠ the gate fails: {count} things do not hold; run `gitdone check`"
    if report.missing:
        count = len(report.missing)
        return f"⚠ {count} {'claim has' if count == 1 else 'claims have'} no proof behind {'it' if count == 1 else 'them'}; run `gitdone check`"
    return None


def _time_lines(plan, table):
    """The date and where the commits went, for whoever opens the project. A session must start whatever is wrong with either, so neither may
    cost the lines above it.
    """
    from . import focus, forecast, requirements
    lines = []
    for step in (forecast.opener_line, focus.opener_line, lambda p: requirements.opener_line(p, table)):
        try:
            line = step(plan)
        except Exception:
            line = None
        if line:
            lines.append(line)
    return lines


def _opener_lines(plan, with_gate=False):
    table = tables.load_clean(plan)
    lines = [render.opener(plan, table)]
    release = verdict.release_line(plan)
    if release:
        lines.append(release)
    if not plan.out.exists():
        lines.append(f"⚠ {plan.out.name} does not exist; run `{plan.regenerate}`")
    elif render.normalize(read_file(plan.out)) != render.normalize(render.status_md(plan, table)):
        lines.append(f"⚠ {plan.out.name} is out of date; run `{plan.regenerate}`")
    elif with_gate:
        line = _gate_line(plan)
        if line:
            lines.append(line)
    if with_gate:
        lines += _time_lines(plan, table)
    return lines


def _hook_directory():
    """A SessionStart hook is told its directory on stdin; the environment and the cwd are the fallbacks."""
    try:
        if not sys.stdin.isatty():
            payload = json.loads(sys.stdin.read() or "{}")
            if payload.get("cwd"):
                return payload["cwd"]
    except (ValueError, OSError, AttributeError):
        pass
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _hook(args):
    """Never stops a session, and says nothing in a project with no tracker."""
    try:
        found = args.plan or discover.find_plan(_hook_directory())
        if found:
            print("\n".join(_opener_lines(Plan(found), with_gate=True)))
    except Exception as err:  # a session must start whatever is wrong with the plan
        print(f"gitdone: {err}")
    return 0


def cmd_opener(args):
    if args.hook:
        return _hook(args)
    plan = _plan(args)
    if args.json:
        table = tables.load_clean(plan)
        lines = _opener_lines(plan, with_gate=True)
        _print_json({"line": lines[0], **render.opener_data(plan, table), "release": verdict.release_line(plan) or None,
                     "time": [line for line in lines[1:] if not line.startswith("⚠ ") and line != verdict.release_line(plan)],
                     "warnings": [line[2:] for line in lines[1:] if line.startswith("⚠ ")]})
        return 0
    print("\n".join(_opener_lines(plan, with_gate=True)))
    return 0


def cmd_bare(args):
    """`gitdone` alone: where this project stands, or how to start."""
    found = discover.find_plan()
    if found is None:
        if args.json:
            raise PlanError(f"no {discover.POINTER} here or above: run `gitdone init`")
        print(f"No {discover.POINTER} here or above. Start one:\n\n"
              "  gitdone init --rows \"Sign-in, Search, Export\"\n\n"
              "or see `gitdone --help`.")
        return 0
    args.plan, args.hook = str(found), False
    return cmd_opener(args)


def _to_commit(plan):
    """The engine changes files and commits nothing, so it says what the commit should hold."""
    names = [plan.doc, plan.out] + ([plan.badge] if plan.badge else [])
    return "to commit: git add " + " ".join(_short(p) for p in names)


def _short(path):
    try:
        return os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)


def cmd_shipped(args):
    plan = _plan(args)
    try:
        print(shipped.ship(plan, args.row, " ".join(args.evidence), offline=args.offline, allow_unverified=args.allow_unverified))
    except shipped.Refused as refusal:
        print(f"refused, nothing changed: {refusal}", file=sys.stderr)
        branch_kind = next((k for k in plan.kinds if k.evidence == "branch"), None)
        if "is not on" in str(refusal) and branch_kind:
            print(f"Still on a branch? Record it with: gitdone mark {args.row} {branch_kind.short.lower()} --branch NAME", file=sys.stderr)
            print("Squashed or rebased? That gave the work a new commit id: name that one.", file=sys.stderr)
        return 1
    print("\n".join(_opener_lines(plan)))
    print(_to_commit(plan))
    return 0


def cmd_week(args):
    from . import history
    if args.json:
        _print_json(history.delta_data(_plan(args), since=args.since))
        return 0
    print(history.delta(_plan(args), since=args.since))
    return 0


def cmd_where(args):
    plan = _plan(args)
    if args.json:
        _print_json({"plan": str(plan.path), "table": str(plan.doc), "view": str(plan.out),
                     "repo": str(plan.repo) if plan.repo else None, "default_branch": plan.default_branch,
                     "verdict": str(plan.verdict_state) if plan.verdict_state else None})
        return 0
    print("plan     ", plan.path)
    print("table    ", plan.doc)
    print("view     ", plan.out)
    print("repo     ", plan.repo or "none")
    print("verdict  ", plan.verdict_state or "none")
    return 0


def _rows(plan, table, args):
    from . import edit
    wanted = edit.resolve_kind(plan, args.kind).name if args.kind else None
    if args.domain and not any(args.domain.lower() in (str(d.n), d.name.lower()) for d in table.domains):
        raise shipped.Refused(f"no domain is {args.domain!r}. The domains are: " + " · ".join(f"{d.n}. {d.name}" for d in table.domains))
    for domain in table.domains:
        if args.domain and args.domain.lower() not in (str(domain.n), domain.name.lower()):
            continue
        for row in domain.rows:
            if wanted and row.kind != wanted:
                continue
            if args.open and row.kind == plan.strict_kind.name:
                continue
            yield domain, row


def cmd_rows(args):
    plan = _plan(args)
    table = tables.load_clean(plan)
    try:
        found = list(_rows(plan, table, args))
    except shipped.Refused as refusal:
        raise PlanError(str(refusal))
    if args.json:
        _print_json([{"row": r.num, "name": r.name, "kind": r.kind, "status": r.status, "note": r.note,
                      "domain": d.n, "domain_name": d.name} for d, r in found])
        return 0
    width = max((len(r.kind or "") for _, r in found), default=0)
    for _, row in found:
        name = row.name or "(prose domain)"
        print(f"{row.num:>4}  {row.kind or '?':<{width}}  {name}")
    return 0


def _refusable(step):
    try:
        print(step())
    except shipped.Refused as refusal:
        print(f"refused, nothing changed: {refusal}", file=sys.stderr)
        return 1
    return 0


def _left_now(plan):
    from . import forecast
    try:
        return forecast.left_now(plan)
    except PlanError:
        return None


def _say_the_date_moved(plan, before):
    """A change of scope costs days, and this is where whoever made it hears how many. If there is no date yet, it has nothing to say."""
    from . import forecast
    if before is None:
        return
    try:
        words = forecast.shift_words(plan, before)
    except (PlanError, OSError, ValueError):
        return
    if words:
        print(words)


def cmd_add(args):
    from . import edit
    plan = _plan(args)
    before = _left_now(plan)
    code = _refusable(lambda: f"added row {edit.add(plan, ' '.join(args.name), domain=args.domain, kind=args.kind, note=args.note or '', new_domain=args.new_domain)}")
    if code == 0:
        print("\n".join(_opener_lines(plan)))
        _say_the_date_moved(plan, before)
        print(_to_commit(plan))
    return code


def cmd_remove(args):
    from . import edit
    plan = _plan(args)
    before = _left_now(plan)
    code = _refusable(lambda: edit.remove(plan, args.row))
    if code == 0:
        print("\n".join(_opener_lines(plan)))
        _say_the_date_moved(plan, before)
        print(_to_commit(plan))
    return code


def cmd_mark(args):
    from . import edit
    plan = _plan(args)
    code = _refusable(lambda: edit.mark(plan, args.row, args.kind, " ".join(args.words), branch=args.branch, offline=args.offline))
    if code == 0:
        print("\n".join(_opener_lines(plan)))
        print(_to_commit(plan))
    return code


def cmd_link(args):
    from . import edit
    plan = _plan(args)
    code = _refusable(lambda: edit.link(plan, args.row, args.id))
    if code == 0:
        print(_to_commit(plan))
    return code


def cmd_doctor(args):
    from . import doctor
    path = args.plan or discover.find_plan()
    items, code = doctor.run(path, offline=args.offline)
    if args.json:
        _print_json({"exit_code": code, "items": items})
    else:
        print("\n".join(doctor.lines(items)))
    return code


def _init_sections(args):
    from . import gitio, scaffold
    if args.from_checklist:
        try:
            text = open(args.from_checklist, encoding="utf-8").read()
        except OSError as err:
            raise PlanError(f"cannot read {args.from_checklist}: {err.strerror}")
        sections = scaffold.sections_from_checklist(text)
        if not sections:
            raise PlanError(f"{args.from_checklist} holds no `- [ ]` items and no `REQ-1: words` lines")
        return sections
    if args.from_issues is not None:
        items = gitio.issues(args.dir, args.from_issues or None)
        if isinstance(items, str):
            raise PlanError(items)
        sections = scaffold.sections_from_issues(items)
        if not sections:
            raise PlanError("no issues to start from")
        return sections
    if args.rows:
        names = args.rows if len(args.rows) > 1 else args.rows[0].split(",")
        return scaffold.sections_from_rows(names)
    if sys.stdin.isatty():
        names = scaffold.ask_for_rows()
        if names:
            return scaffold.sections_from_rows(names)
    return None


def _source_inside(args):
    """A spec the rows came from stays what they answer to: when it grows and the table does not, the gate says so. A file of this project only, and one with ids:
    a living to-do list is not a list of requirements, and every ordinary task on it would read as a gap.
    """
    from . import requirements
    if not args.from_checklist:
        return None
    try:
        items = requirements.parse(read_file(args.from_checklist), args.from_checklist)
    except (OSError, UnicodeDecodeError):
        return None
    if not any(item.ident for item in items):
        return None
    here = os.path.realpath(args.dir)
    source = os.path.realpath(args.from_checklist)
    if not source.startswith(here + os.sep):
        return None
    return [os.path.relpath(source, here).replace(os.sep, "/")]


def cmd_init(args):
    from . import install, scaffold
    sections = _init_sections(args)
    path, in_git = scaffold.create(args.dir, title=args.title, sections=sections, table=args.table, view=args.view,
                                   badge=scaffold.BADGE_NAME if args.badge else None, requirements=_source_inside(args))
    plan = Plan(path)
    held_back = scaffold.hold_to_git(plan)
    table = tables.load_clean(plan)
    shipped.write_view(plan, table)
    print(f"wrote {path.name}, {plan.doc.name} ({len(table.rows)} rows) and {plan.out.name}")
    if in_git and plan.default_branch not in ("main", "master"):
        print(f"the default branch is {plan.default_branch}: only a commit there counts. If that is wrong, set default_branch in {path.name}")
    if args.agents:
        for written in scaffold.install_agents(args.dir):
            print("wrote", written.name)
    code = 0
    for wanted, step in ((args.hook, lambda: install.install(plan)), (args.ci, lambda: [scaffold.install_ci(plan)])):
        if wanted:
            try:  # the tracker is written, and the summary below is still what the person needs
                for written in step():
                    print("installed", written)
            except PlanError as err:
                print(f"gitdone: {err}", file=sys.stderr)
                code = gate.CANNOT_RUN
    print()
    print(render.opener(plan, table))
    for number, why in held_back:
        print(f"row {number} starts as Partial: {why}")
    lines, _ = gate.check(plan, offline=True)
    for line in lines:
        if line.startswith(("WARN", "FAIL")):
            print(line)
    checked = scaffold.unproven_checked(sections or [])
    if checked:
        print(f"{len(checked)} checked {'item names' if len(checked) == 1 else 'items name'} no commit, so "
              f"{'it starts' if len(checked) == 1 else 'they start'} as Partial: row {', '.join(map(str, checked))}.")
    print()
    print("Next:")
    if not sections:
        print(f"  edit {plan.doc.name}: replace the placeholder rows with what must exist for this to be done")
    print("  gitdone shipped <row> <commit or PR>   move a row to Live; refused unless git agrees")
    print("  gitdone mark <row> <kind> [note]       record anything short of a release")
    print("  gitdone check                          the gate")
    if not args.hook:
        print("  gitdone install-hook                   refuse a commit that would make the numbers lie")
    if not args.agents:
        print("  gitdone install-agents                 tell coding agents the rules, in AGENTS.md")
    if args.badge:
        print(f"  in your README: [![status]({scaffold.BADGE_NAME})]({plan.out.name})")
    if not in_git:
        print("  git init                                      evidence needs a repository")
    if not args.ci:
        print("  gitdone install-ci                     the gate in pull requests, which no flag can skip")
    print(f"  git add {' '.join(_short(p) for p in plan.tracked)}{' .github' if args.ci else ''}")
    return code


def _write_or_print(path, text):
    if path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shipped.write_atomically(target, text)
        print("wrote", target)
    else:
        sys.stdout.write(text)


def cmd_eta(args):
    from . import forecast
    plan = _plan(args)
    found = forecast.data(plan, group=_group(plan, args.group), days=args.days)
    if args.json:
        _print_json(found)
    else:
        print(forecast.text(found))
    return 0


def cmd_focus(args):
    from . import focus
    if args.last:
        try:  # a post-commit hook: the commit has already happened, so nothing here may be noisy about itself
            line = focus.last_line(_plan(args))
        except Exception:
            return 0
        if line:
            print(line)
        return 0
    found = focus.data(_plan(args), days=args.days)
    if args.json:
        _print_json(found)
    else:
        print(focus.text(found, show_all=args.all))
    return 0


def cmd_next(args):
    from . import focus
    found = focus.next_data(_plan(args))
    if args.json:
        _print_json(found)
    else:
        print(focus.next_text(found))
    return 0


def cmd_matrix(args):
    from . import trace
    plan = _plan(args)
    if args.json:
        _print_json(trace.data(plan, offline=args.offline))
    else:
        _write_or_print(args.out, trace.markdown(plan, offline=args.offline))
    return 0


def _group(plan, words):
    """What the opener calls the whole table is a fair thing to ask for by name, when the plan has no groups of its own."""
    return None if words and not plan.groups and words.lower() == "all" else words


def _burndown(args, plan, items):
    from . import chart, forecast
    found = forecast.data(plan, group=_group(plan, args.group))
    if args.json:
        _print_json({"points": items, "forecast": found})
    elif not args.out and sys.stdout.isatty():
        print(forecast.text(found))
        print("To draw it: gitdone chart --burndown --out burndown.svg")
    else:
        _write_or_print(args.out, chart.burndown(items, plan.title, found, forecast.headline(found)))
    return 0


def cmd_chart(args):
    from . import chart
    plan = _plan(args)
    items = chart.points(plan, group=_group(plan, args.group))
    if args.burndown and not args.csv:
        return _burndown(args, plan, items)
    if args.json:
        _print_json(items)
    elif args.csv:
        _write_or_print(args.out, chart.csv_text(items))
    elif not args.out and sys.stdout.isatty():
        print(chart.csv_text(items), end="")
        print("That is the history in rows. To draw it: gitdone chart --out burnup.svg")
    else:
        _write_or_print(args.out, chart.svg(items, plan.title))
    return 0


def cmd_badge(args):
    from . import badge
    plan = _plan(args)
    if args.keep:
        from . import scaffold
        name = scaffold.keep_badge(plan.path, args.keep)
        plan = Plan(plan.path)
        shipped.write_badge(plan, tables.load_clean(plan))
        print(f"{_short(plan.badge)} is now written with the view, and held to the table by the gate.")
        print(f"In your README: [![status]({name})]({_short(plan.out)})")
        return 0
    table = tables.load_clean(plan)
    if args.svg:
        _write_or_print(args.svg, badge.svg(plan, table, group=args.group, label=args.label))
    if args.endpoint:
        _write_or_print(args.endpoint, json.dumps(badge.endpoint(plan, table, group=args.group, label=args.label)) + "\n")
    if not args.svg and not args.endpoint:
        _print_json(badge.endpoint(plan, table, group=args.group, label=args.label))
    return 0


def cmd_report(args):
    from . import report
    plan = _plan(args)
    if args.json:
        _print_json(report.rows_data(plan, offline=args.offline))
    else:
        _write_or_print(args.out, report.markdown(plan, offline=args.offline))
    return 0


def cmd_portfolio(args):
    from . import portfolio
    entries = portfolio.scan(args.folders or ["."])
    if args.json:
        _print_json(entries)
    else:
        _write_or_print(args.out, portfolio.markdown(entries))
    return 0


def cmd_ci(args):
    from . import ci
    return ci.run(_plan(args), strict=args.strict, comment=not args.no_comment, base=args.base, publish_branch=args.publish, always=args.always)


def cmd_mcp(args):
    from . import mcp
    return mcp.serve()


def cmd_install_agents(args):
    from . import scaffold
    directory = args.into or discover.pointer_directory() or "."
    written = scaffold.install_agents(directory)
    for path in written:
        print("wrote", path)
    if not written:
        print("already there")
    return 0


def cmd_install_hook(args):
    from . import install
    plan = _plan(args)
    for hook in install.install(plan, strict=not args.lenient, focus=not args.no_focus):
        print("installed", hook)
    theirs = None if args.no_focus else install.someones_post_commit(plan)
    if theirs:
        print(f"left {theirs} alone, so a commit off plan will not be said. To have it said, add `gitdone focus --last` to that hook")
    return 0


def cmd_install_ci(args):
    from . import scaffold
    print("installed", _short(scaffold.install_ci(_plan(args))))
    return 0


def cmd_install_skill(args):
    from . import install
    directory = args.into or discover.pointer_directory()
    if directory is None:
        raise PlanError(f"no {discover.POINTER} here to say where the project starts; pass --into")
    print("installed", install.install_skill(directory))
    return 0


def _row_number(text):
    if not text.isdigit() or len(text) > 18:
        raise argparse.ArgumentTypeError(f"{text!r} is not a row number; `gitdone rows` lists them")
    return int(text)


def _parser():
    parser = argparse.ArgumentParser(prog="gitdone", description=__doc__,
                                     epilog="With no command, it prints where the project stands. https://github.com/ArtJack/gitdone")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--json", action="store_true", help="with no command: where the project stands, as data")
    parser.set_defaults(func=cmd_bare)
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    parser.json_commands = set()

    def command(name, func, help_text, aliases=(), plan=True, as_data=None):
        sub = commands.add_parser(name, help=help_text, description=help_text, aliases=list(aliases))
        if plan:
            sub.add_argument("--plan", help="the plan file (default: found from this directory)")
        if as_data:  # SUPPRESS: unsaid here, so `gitdone --json check` keeps what was said before the command
            sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=as_data)
            parser.json_commands.update([name, *aliases])
        sub.set_defaults(func=func)
        return sub

    sub = command("init", cmd_init, "Start a tracker here: writes the plan, the status table and the view.", plan=False)
    sub.add_argument("--rows", nargs="+", metavar="ROW", help="the rows: one string split on commas, or several strings taken whole")
    sub.add_argument("--from-checklist", metavar="FILE", help="take the rows from a file's - [ ] and - [x] items, a domain per heading")
    sub.add_argument("--from-issues", nargs="?", const="", metavar="LABEL", help="take the rows from GitHub issues, a domain per milestone")
    sub.add_argument("--title", help="the view's title (default: the folder's name)")
    sub.add_argument("--dir", default=".", help="the project folder (default: here)")
    sub.add_argument("--table", default="status-table.md", help="the status table's file name (default: status-table.md)")
    sub.add_argument("--view", default="STATUS.md", help="the view's file name (default: STATUS.md)")
    sub.add_argument("--hook", action="store_true", help="also install the local git gate")
    sub.add_argument("--agents", action="store_true", help="also tell coding agents the rules, in AGENTS.md")
    sub.add_argument("--badge", action="store_true", help="also keep a badge for your README, written with the view and held to the gate")
    sub.add_argument("--ci", action="store_true", help="also add the GitHub Action workflow, the gate no flag can skip")

    sub = command("render", cmd_render, "Print STATUS.md, or write it with --write.")
    sub.add_argument("--write", action="store_true", help="write the view beside the plan")
    sub = command("counts", cmd_counts, "Print the counts table, or update the one inside the status table with --write.")
    sub.add_argument("--write", action="store_true", help="update the counts table inside the status table")
    sub = command("check", cmd_check, "The gate. Exit 0 clean, 1 contradiction, 2 could not run, 3 --strict evidence missing or partly disproved.",
                  as_data="the same findings as data")
    sub.add_argument("--strict", action="store_true", help="fail on missing evidence too")
    sub.add_argument("--offline", action="store_true", help="do not call gh; pull requests are reported as unverified")
    sub.add_argument("--if-staged", action="store_true", help="for a git hook: judge what the commit will contain, and only if it touches the plan, the table or the view")
    sub = command("opener", cmd_opener, "Print where the project stands: strict and weighted per group, the next workstream, what it needs.", aliases=["status"],
                  as_data="the same as data")
    sub.add_argument("--hook", action="store_true", help="for a SessionStart hook: silent without a plan, never fails")
    sub = command("shipped", cmd_shipped, "Move one row to the strict kind on evidence, and regenerate the view.")
    sub.add_argument("row", type=_row_number, help="the row number")
    sub.add_argument("evidence", nargs="*", help="a commit id, `PR #12`, `MR !12` or `tag v1.2`; refused without one")
    sub.add_argument("--offline", action="store_true", help="do not call gh or glab; a pull request cannot be checked, so it is refused")
    sub.add_argument("--allow-unverified", action="store_true", help="take evidence nothing here can check: a pull request with gh unavailable or no remote, a commit with no repository. The note says so, and --strict still fails on it")
    sub = command("week", cmd_week, "Print the delta line from the status table's git history.", as_data="the same as data")
    sub.add_argument("since", nargs="?", help="a date, a span like '2 weeks', or a commit (default: 7 days ago)")
    sub = command("mark", cmd_mark, "Move one row to any kind short of the strict one. A kind that needs a branch or a note is held to it.")
    sub.add_argument("row", type=_row_number, help="the row number")
    sub.add_argument("kind", help="the kind: its name, its short name, or a prefix only one kind has")
    sub.add_argument("words", nargs="*", help="words for the note")
    sub.add_argument("--branch", help="the branch this row is built on; it must exist")
    sub.add_argument("--offline", action="store_true", help=argparse.SUPPRESS)
    sub = command("remove", cmd_remove, "Take one row out of the scope, and keep the counts and the view true.")
    sub.add_argument("row", type=_row_number, help="the row number")
    sub = command("add", cmd_add, "Add one row to a domain, and keep the counts and the view true.")
    sub.add_argument("name", nargs="+", help="the row's name")
    sub.add_argument("--domain", help="the domain's number or name (default: the last one)")
    sub.add_argument("--new-domain", metavar="NAME", help="start a new domain with this row")
    sub.add_argument("--kind", help="the row's kind (default: the plan's last kind)")
    sub.add_argument("--note", help="words for the note")
    sub = command("rows", cmd_rows, "List the rows, optionally by kind or domain.", as_data="the same as data")
    sub.add_argument("--kind", help="only this kind")
    sub.add_argument("--domain", help="only this domain, by number or name")
    sub.add_argument("--open", action="store_true", help="only rows not yet at the strict kind")
    command("where", cmd_where, "Print which plan this directory resolves to, and what it names.", as_data="the same as data")
    sub = command("doctor", cmd_doctor, "Check everything the tracker needs here, on one screen. Changes nothing. Exit 1 if something is broken.",
                  as_data="the same as data")
    sub.add_argument("--offline", action="store_true", help="do not ask gh whether it is logged in")
    sub = command("chart", cmd_chart, "A burn-up from the status table's git history, with no forecast; or with --burndown, what is left and eta's line through it.", as_data="the numbers as data")
    sub.add_argument("--out", help="write here instead of printing")
    sub.add_argument("--group", help="only this group's rows")
    sub.add_argument("--csv", action="store_true", help="the numbers as CSV")
    sub.add_argument("--burndown", action="store_true", help="what is left over time, with the likely date, the range and the deadline")
    sub = command("eta", cmd_eta, "When it will be done if the work goes on as it has: a line through the table's git history, with a range. Adding a row moves it, and so does dropping one.", as_data="the same as data")
    sub.add_argument("--group", help="only this group's rows")
    sub.add_argument("--days", type=int, default=28, help="how many days of pace to read (default: 28)")
    sub = command("focus", cmd_focus, "Where the commits went: on plan, upkeep, or off plan. A signal, never a gate.", as_data="the same as data")
    sub.add_argument("--days", type=int, default=14, help="how many days to read (default: 14)")
    sub.add_argument("--all", action="store_true", help="every commit, and why it counts as it does")
    sub.add_argument("--last", action="store_true", help="one line if the last commit was off plan, and nothing otherwise: what the post-commit hook runs")
    command("next", cmd_next, "What to work on now: the next workstream's open rows, and nothing else.", as_data="the same as data")
    sub = command("link", cmd_link, "Put a requirement's id in a row's note, where a later move keeps it. The status does not change.")
    sub.add_argument("row", type=_row_number)
    sub.add_argument("id", help="the requirement's id, like REQ-12")
    sub = command("matrix", cmd_matrix, "A traceability matrix from the plan, the table and git: requirement, row, evidence, tests.", as_data="the same as data")
    sub.add_argument("--out", help="write here instead of printing")
    sub.add_argument("--offline", action="store_true", help="do not call gh or glab")
    sub = command("badge", cmd_badge, "The two numbers as a badge: a self-contained SVG, or the JSON a shields.io endpoint reads.")
    sub.add_argument("--svg", metavar="FILE", help="write an SVG badge")
    sub.add_argument("--endpoint", metavar="FILE", help="write the shields.io endpoint JSON (with neither flag, it is printed)")
    sub.add_argument("--keep", nargs="?", const="status-badge.svg", metavar="FILE", help="name a badge in the plan, so that it is written with the view and held to the table by the gate")
    sub.add_argument("--label", default="done", help="the badge's left side (default: done)")
    sub.add_argument("--group", help="only this group's rows")
    sub = command("report", cmd_report, "The evidence behind the numbers, row by row, as Markdown, for someone who will not open the repository.", as_data="the same as data")
    sub.add_argument("--out", help="write here instead of printing")
    sub.add_argument("--offline", action="store_true", help="do not call gh or glab")
    sub = command("portfolio", cmd_portfolio, "Every tracked project under a folder on one page. Reads each one offline, and changes nothing.", plan=False, as_data="the same as data")
    sub.add_argument("folders", nargs="*", help="project folders, or folders holding them (default: here)")
    sub.add_argument("--out", help="write here instead of printing")
    sub = command("ci", cmd_ci, "What the Action runs: annotations, a summary, a sticky comment, a badge branch. To add the Action: install-ci.")
    sub.add_argument("--strict", action="store_true", help="fail on missing evidence too")
    sub.add_argument("--no-comment", action="store_true", help="do not comment on the pull request")
    sub.add_argument("--base", help="the commit to compare with (default: the pull request's base)")
    sub.add_argument("--publish", metavar="BRANCH", help="on a push, commit the badge and the chart to this branch")
    sub.add_argument("--always", action="store_true", help="judge a pull request that does not touch the tracker too")
    command("mcp", cmd_mcp, "Serve read-only tools over stdio to a coding agent (Model Context Protocol). Writes nothing.", plan=False)
    sub = command("install-hook", cmd_install_hook, "Install the gate as local pre-commit and pre-merge-commit hooks in the status table's repository. Strict unless told otherwise.")
    sub.add_argument("--lenient", action="store_true", help="only a proven contradiction stops a commit; a Live row with no evidence warns")
    sub.add_argument("--no-focus", action="store_true", help="leave out the post-commit hook that says when a commit was off plan")
    command("install-ci", cmd_install_ci, "Add the GitHub Action workflow: the gate in every pull request, which no flag can skip.")
    sub = command("install-skill", cmd_install_skill, "Give a project its bare slash command: writes a project-level Claude Code skill there.")
    sub.add_argument("--into", help="the project root (default: the nearest folder with a pointer file)")
    sub = command("install-agents", cmd_install_agents, "Tell coding agents the rules: adds a section to AGENTS.md, and to CLAUDE.md if there is one.", plan=False)
    sub.add_argument("--into", help="the project root (default: the nearest folder with a pointer file, or here)")
    return parser


class _Terminal:
    """A person's terminal. Words from a table reach it as they are written, so an escape sequence is shown and not obeyed. A pipe gets the bytes."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(render.printable(text))

    def __getattr__(self, name):
        return getattr(self._stream, name)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if sys.stdout is not None and sys.stdout.isatty():  # None: the stream was closed before this started
        sys.stdout = _Terminal(sys.stdout)
    if sys.stderr is not None and sys.stderr.isatty():
        sys.stderr = _Terminal(sys.stderr)
    args = argparse.Namespace()
    try:
        parser = _parser()
        args = parser.parse_args(argv)
        if args.json and args.command and args.command not in parser.json_commands:
            parser.error(f"--json does not go with {args.command}")
        code = args.func(args)
        if sys.stdout is not None:
            sys.stdout.flush()
        return code
    except PlanError as err:
        if getattr(args, "json", False):
            print(json.dumps({"result": "cannot run", "exit_code": gate.CANNOT_RUN, "error": str(err)}, ensure_ascii=False))
        else:
            print(render.printable(f"gitdone: {err}"), file=sys.stderr)  # a plan's words: they must not be able to start a workflow command
        return gate.CANNOT_RUN
    except BrokenPipeError:  # `render | head`: the reader has what it wanted
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return getattr(args, "exit_code", 0)
    except Exception as err:  # a crash must not read as exit 1, a proven contradiction
        words = f"could not run: {type(err).__name__}: {err}"
        if getattr(args, "json", False):
            print(json.dumps({"result": "cannot run", "exit_code": gate.CANNOT_RUN, "error": words}, ensure_ascii=False))
        else:
            print(render.printable(f"gitdone: {words}"), file=sys.stderr)
        return gate.CANNOT_RUN
