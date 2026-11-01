# GitDone

[![PyPI](https://img.shields.io/pypi/v/gitdone)](https://pypi.org/project/gitdone/)
[![Python](https://img.shields.io/pypi/pyversions/gitdone)](https://pypi.org/project/gitdone/)
[![CI](https://github.com/ArtJack/gitdone/actions/workflows/ci.yml/badge.svg)](https://github.com/ArtJack/gitdone/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![its own status](docs/img/status-badge.svg)](STATUS.md)
[![Sponsor](https://img.shields.io/badge/sponsor-%E2%9D%A4-ea4aaa?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/ArtJack)

**Your agent says it shipped. Git decides.**

One markdown table of what must exist for a project to be done, with every row held to git, and a percent you can defend. A row is Live only when a commit on
the default branch or a merged pull request says so. A commit that would make the numbers lie is refused, and a claim stops holding
the day its commit is reverted.

<p align="center"><img src="docs/img/demo.svg" width="760" alt="A terminal session: a commit from a spike branch is refused, the commit on main is accepted, a hand-typed claim with no evidence stops the commit, and a reverted commit fails the gate."></p>

No account, no server, no model calls, no dependencies. The files live in your repository and stay readable without the tool.

**[The scale](#the-scale-how-far-along-is-it)** · **[Install](#install)** · **[Instruction](#instruction)** · [The gate](#what-the-gate-does) · [Focus](#where-the-work-went) · [Commands](#commands) · [FAQ](#faq) · [Sponsor](#sponsor)

## The scale: how far along is it?

Every project answers that question with two numbers, side by side.

- **Strict** counts only the rows a commit on the default branch or a merged pull request says are Live. It is what an outside reviewer would count, and nobody can talk it up.
- **Weighted** also credits work that stopped short of that, at weights written in the plan: by default a row built on a branch counts 0.8, and a partial row 0.4.

The gap between them is work that exists and has not shipped. Strict 25% with weighted 46% is a lot in progress and little out the door, and it is a different project from strict 40% with weighted 46%.

<img src="docs/img/bramble-scale.svg" width="760" alt="A scale for a fictional project: all rows at 25 percent strict and 46 percent weighted, and one bar for each of its five domains.">

That is `gitdone chart --scale --out scale.svg`, for Bramble Kiosk, a [fictional sample](examples/bramble/STATUS.md) partway through its work. Here is the same state everywhere you would meet it.

**When you open the project.** Plain `gitdone`, with what comes next and where the recent commits went:

<!-- scale:start -->
```console
$ gitdone
All: strict 25% (4/16), weighted 46% · next: S1 (Reading lists and renewals), needs the head librarian's word at release
  All  strict ████░░░░░░░░░░░░  25%  weighted ███████░░░░░░░░░  46%
Focus, last 14 days: 8 of 13 commits on plan, 3 off plan (printer, theme).
```
<!-- scale:end -->

**In `STATUS.md`.** Generated and committed, so anyone who opens the repository can read it, and the gate refuses a view that no longer matches the table:

<!-- scale-view:start -->
> **Bramble Kiosk: 16 rows**
>
> - **Strict:** 4 of 16 live · `█████░░░░░░░░░░░░░░░` 25%
> - **Weighted:** `█████████░░░░░░░░░░░` 46%
> - Built on branches, not released: 2 · demo only: 1 · partial: 3 · not built: 6
>
> | Domain | Rows | Live | Built | Demo | Partial | Not built | Strict | Weighted | |
> |---|---|---|---|---|---|---|---|---|---|
> | 1. Catalogue search | 4 | 2 | 1 | 0 | 1 | 0 | 50% | 80% | `██████████░░` |
> | 2. Lending | 4 | 1 | 1 | 1 | 0 | 1 | 25% | 57% | `███████░░░░░` |
> | 3. Accounts | 3 | 1 | 0 | 0 | 1 | 1 | 33% | 47% | `██████░░░░░░` |
> | 4. Reporting | 3 | 0 | 0 | 0 | 0 | 3 | 0% | 0% | `░░░░░░░░░░░░` |
> | 5. Accessibility | 2 | 0 | 0 | 0 | 1 | 1 | 0% | 20% | `██░░░░░░░░░░` |
>
> **Workstreams, in the plan's order**
>
> | # | Workstream | Rows | Strict | Weighted | State | Needs |
> |---|---|---|---|---|---|---|
> | 1 | **S1** Reading lists and renewals | 3, 7 | 0/2 | 80% `████████░░` | built and reviewed; released with the next kiosk update | the head librarian's word at release |
> | 2 | **S2** Returns | 6, 8 | 0/2 | 25% `██░░░░░░░░` | self-return shown at the open day; fines not started | the fines policy from the library board |
> | 3 | **S3** Accounts | 9, 10, 11 | 1/3 | 47% `█████░░░░░` | card sign-in live; the override screen in progress |  |
>
> **Next, in order:** S1 → S2 → S3.
<!-- scale-view:end -->

**On every pull request that moves a row.** [The Action](docs/ci.md) keeps one comment, and puts each finding on its row's line in the diff:

<!-- scale-comment:start -->
> **gitdone** · gate: **PASS**
>
> | | Rows | Strict | Weighted | |
> |---|---|---|---|---|
> | All | 16 | 4 (25%) | 46% | `█████░░░░░░░` |
>
> Against `main`: Since 54a3bd4 (2026-03-02): All strict 3→4 of 16 (19%→25%), weighted 39%→46%. Moved: 7 Partial→Built, not live; 9 Partial→Live. Workstreams moved: S1, S3; not moved: S2.
>
> Next: **S1** Reading lists and renewals. Needs the head librarian's word at release.
<!-- scale-comment:end -->

**On your README.** `gitdone badge --keep` writes the badge with the view, and the gate holds it to the table: <img src="docs/img/bramble-badge.svg" alt="done: 25% strict, 46% weighted" height="20">

**Over time.** `gitdone chart --out burnup.svg` draws the table's own git history, with the scope line visible when it grows:

<img src="docs/img/bramble-burnup.svg" width="640" alt="A burn-up chart for a fictional project: 16 rows in scope, 46 percent weighted, 25 percent strict.">

**Across every project you keep.** `gitdone portfolio ~/code`, read offline, and a failing gate is hard to miss:

<!-- scale-portfolio:start -->
| Project | Rows | Strict | Weighted | | Next | Gate |
|---|---|---|---|---|---|---|
| bramble | 16 | 4 (25%) | 46% | `█████░░░░░` | S1 Reading lists and renewals | pass |
| kiosk | 4 | 1 (25%) | 25% | `██░░░░░░░░` | row 2 Search | **fail**, 1 contradicted |
<!-- scale-portfolio:end -->

**For someone who will never open the repository.** `gitdone report --out report.md` gives the evidence behind the numbers, row by row, as Markdown for a client or a manager.

## Install

You need Python 3.9 or newer and git. GitDone has no dependencies of its own. `gh` is used only for a row that names a pull request, and `glab` for a merge request.

| With | Command | Good for |
|---|---|---|
| **pipx** | `pipx install gitdone` | The usual way: its own environment, and on your PATH everywhere |
| **uv** | `uv tool install gitdone` | The same, if you use uv |
| **pip** | `pip install gitdone` | Inside a project's virtual environment |
| **uvx** | `uvx gitdone --version` | Trying it with nothing installed: put `uvx` in front of each command |

`gitdone --version` says it worked. `pipx upgrade gitdone` moves to a new version, and `pipx uninstall gitdone` removes it. Your table and view stay, and they read fine without the tool.
A hook lives in `.git/hooks`, in this clone only: delete `pre-commit`, `pre-merge-commit` and `post-commit` there to take it out.

### With a coding agent

| Agent | Command |
|---|---|
| **Claude Code** | `/plugin marketplace add ArtJack/gitdone`, then `/plugin install gitdone@gitdone`. A session then opens with the numbers |
| **Cursor, Codex, OpenCode and others** | `npx skills add ArtJack/gitdone` |
| **Any MCP client** | `claude mcp add gitdone -- uvx gitdone mcp`, or `{"mcpServers": {"gitdone": {"command": "uvx", "args": ["gitdone", "mcp"]}}}` in its config. Read-only tools |
| **Any agent that reads `AGENTS.md`** | `gitdone install-agents` adds the rules, and keeps what is already there |

[What each one does](docs/agents.md).

### As a gate

| Where | How |
|---|---|
| **This clone** | `gitdone install-hook`, or `init --hook`. Another clone runs it once too |
| **GitHub** | `gitdone install-ci`, or `init --ci`, adds [the Action](docs/ci.md): the gate no flag can skip. It needs no key and no install |
| **The pre-commit framework** | `repo: https://github.com/ArtJack/gitdone`, `rev: v0.3.0`, hook id `gitdone` |
| **Any other CI** | `uvx gitdone check --strict`, with the whole history checked out. [Exit codes](docs/gate.md) |

## Instruction

One project from nothing to a number you can defend. Run these in your repository, on your own rows. Every block is real output, and a test keeps it so.

### 1. Write down what done means

Rows are capabilities a stranger could check, like `Sign-in`, not tasks like `refactor auth`.

<!-- guide-begin:start -->
```console
$ gitdone init --rows "Sign-in, Search, Export, Reports" --hook
wrote .gitdone.json, status-table.md (4 rows) and STATUS.md
All: strict 0% (0/4), weighted 0% · next: row 1 (Sign-in)

$ git add -A && git commit -q -m 'Track the scope'
result: PASS
```
<!-- guide-begin:end -->

`--hook` guards the commits after this one, in this clone. `--ci` adds the Action, `--agents` the agents' rules, and `--badge` a badge.

Instead of `--rows`, start from a file's checklist or spec with `--from-checklist TODO.md`, or from GitHub issues with `--from-issues`. A checklist's checked items are Live only if what they name holds, and the rest start as Partial with the reason beside them, so the first number you see is already true.

### 2. Open the project with `gitdone`

<!-- guide-open:start -->
```console
$ gitdone
All: strict 0% (0/4), weighted 0% · next: row 1 (Sign-in)
  All  strict ░░░░░░░░░░░░░░░░   0%  weighted ░░░░░░░░░░░░░░░░   0%
```
<!-- guide-open:end -->

It says where things stand and what comes next. `gitdone next` lists the rows to work on now, and `gitdone rows --open` lists everything left.

### 3. Work, and name the row in the commit message

<!-- guide-work:start -->
```console
$ git commit -q -m 'row 1: sign-in'
```
<!-- guide-work:end -->

That is how `gitdone focus` knows where the work went. Nothing else depends on it.

### 4. Move a row when the work moves

<!-- guide-move:start -->
```console
$ gitdone shipped 1 b942cf2
row 1: Not built → Live (verified: commit b942cf2 is on main)
All: strict 25% (1/4), weighted 25% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md

$ gitdone mark 2 built --branch search
row 2: Not built → Built, not live
All: strict 25% (1/4), weighted 45% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md

$ gitdone mark 3 partial "CSV works, PDF does not yet"
row 3: Not built → Partial
All: strict 25% (1/4), weighted 55% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md
```
<!-- guide-move:end -->

Only these move the numbers, and each one is held to its rule. Git is asked, and `shipped` refuses a commit that is not on the default branch.

| The work is | Command | Strict | Weighted |
|---|---|---|---|
| On the default branch | `gitdone shipped 3 <commit>`, or `"PR #12"`, `"MR !12"`, `"tag v1.2"` | Counts | 1.0 |
| Finished on a branch that exists | `gitdone mark 3 built --branch NAME` | No | 0.8 |
| Partly there | `gitdone mark 3 partial "what exists"` | No | 0.4 |
| Not there after all | `gitdone mark 3 "not built"` | No | 0 |

The weights are yours to change in `.gitdone.json`, and so are the kinds. With a remote, `shipped` wants the commit pushed.

### 5. Change the scope out loud

<!-- guide-scope:start -->
```console
$ gitdone add "Password reset"
added row 5
All: strict 20% (1/5), weighted 44% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md

$ gitdone remove 4
row 4 (Reports) is out of the scope; `week` will say so
All: strict 25% (1/4), weighted 55% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md
```
<!-- guide-scope:end -->

Adding a row lowers the percent, and that is the point: the cost of a feature is on the table when someone decides to take it. Rows and domains can also be edited by hand in `status-table.md`, followed by `gitdone render --write`.

### 6. Commit the table and the view together

<!-- guide-commit:start -->
```console
$ git add status-table.md STATUS.md && git commit -q -m 'Sign-in is live'
result: PASS
```
<!-- guide-commit:end -->

The gate runs here, and it stays out of any commit that does not touch the tracker.

### 7. Read it back

<!-- guide-read:start -->
```console
$ gitdone
All: strict 25% (1/4), weighted 55% · next: row 2 (Search)
  All  strict ████░░░░░░░░░░░░  25%  weighted █████████░░░░░░░  55%

$ gitdone week "1 month"
No commit of the table before 1 month ago; since its first commit (d72f82a, 2026-03-02): All strict 0→1 of 4 (0%→25%), weighted 0%→55%. Moved: 1 Not built→Live; 2 Not built→Built, not live; 3 Not built→Partial. 1 rows are new since then. Removed: 4 (was Not built). Focus: 1 of 1 commits on plan, 0 unclear, 0 upkeep, 0 off plan.
```
<!-- guide-read:end -->

`gitdone focus` says where the commits went. `gitdone chart`, `gitdone report` and `gitdone portfolio` are [above](#the-scale-how-far-along-is-it). `gitdone doctor` checks the whole setup on one screen.

### 8. When the gate says no, believe it

It names the row and what to do. A reverted commit fails until someone says what is true now, with `gitdone mark`, or with `gitdone shipped` on the new commit. [The rules](docs/gate.md).

Going further: [the status table](docs/status-table.md), [the plan file](docs/plan-file.md), and groups, workstreams and asks in [a full example](examples/bramble/STATUS.md).

## What the gate does

<!-- demo:start -->
```text
# Four things must exist for this to be done.
$ gitdone init --rows "Sign-in, Search, Export, Reports" --hook
wrote .gitdone.json, status-table.md (4 rows) and STATUS.md
All: strict 0% (0/4), weighted 0% · next: row 1 (Sign-in)

# The agent says sign-in shipped, and names a commit from its spike branch.
$ gitdone shipped 1 705af2a
refused, nothing changed: commit 705af2a is not on main
Still on a branch? Record it with: gitdone mark 1 built --branch NAME

# The commit that really landed:
$ gitdone shipped 1 660d81a
row 1: Not built → Live (verified: commit 660d81a is on main)
All: strict 25% (1/4), weighted 25% · next: row 2 (Search)
to commit: git add status-table.md STATUS.md

# Someone types Live into the table by hand, with nothing behind it.
$ git add -A && git commit -m 'Search is live'
FAIL row 2 names no commit, pull request or tag; run `gitdone shipped 2 <commit>`
result: FAIL in --strict, evidence is missing or partly disproved

# Later, sign-in is reverted on main. The claim stops holding.
$ gitdone check
FAIL row 1 (Live): commit 660d81a was reverted on main by 3f6610b
  what is true now? gitdone mark 1 <kind> <words>, or shipped 1 <the new commit>
result: FAIL, 1 contradicted or inconsistent

# Your agent says it shipped. Git decides.
```
<!-- demo:end -->

Every line above is real output, with the longer commands trimmed: [`docs/demo/record.py`](docs/demo/record.py) runs it, and a test keeps this copy true.

- **It reads what the commit will contain.** The local hook judges git's index, not your disk, and stays out of every commit that does not touch the tracker. Sixty claims in a repository of a thousand commits take about 0.2 seconds.
- **Claims can stop holding.** Each run checks each row again. A reverted commit, through `git revert` or GitHub's button, turns its row into a failure until someone says what is true now, and the headline says so.
- **No flag skips the Action.** The hook is a courtesy that lives in one clone. The Action judges what arrived, whatever skipped the hook.
- **Agents are held to it.** They read what they are told, and they stop when a command refuses. An agent that cannot get `shipped` to accept its commit has told you something true, before the review instead of after the release.

## What it writes

| File | What it is | Who edits it |
|---|---|---|
| `status-table.md` | The table: one row per capability, one status each | You, or `shipped`, `mark`, `add`, `remove` |
| `STATUS.md` | The view: the numbers, what is left, what is live and why | Nobody: it is generated |
| `.gitdone.json` | The plan: the title, the repository, the kinds and their weights | You, rarely |

`STATUS.md` after the session in [the gate's demo](#what-the-gate-does), in a project with no groups or workstreams:

<!-- view:start -->
> **kiosk: 4 rows**
>
> - **Strict:** 1 of 4 live · `█████░░░░░░░░░░░░░░░` 25%
> - **Weighted:** `█████░░░░░░░░░░░░░░░` 25%
> - Built, not live: 0 · partial: 0 · not built: 3
>
> | Domain | Rows | Live | Built | Partial | Not built | Strict | Weighted | |
> |---|---|---|---|---|---|---|---|---|
> | 1. Scope | 4 | 1 | 0 | 0 | 3 | 25% | 25% | `███░░░░░░░░░` |
>
> **What is left: 3 of 4 rows**
>
> | # | Name | Status | Note |
> |---|---|---|---|
> | 2 | Search | Not built |  |
> | 3 | Export | Not built |  |
> | 4 | Reports | Not built |  |
>
> **Live: 1 of 4 rows**
>
> | # | Name | Evidence |
> |---|---|---|
> | 1 | Sign-in | *(Live 2026-03-04: `660d81a`; was Not built)* |
>
> ---
>
> Tracked with [gitdone](https://github.com/ArtJack/gitdone): every Live row names its evidence, and git holds it to that.
<!-- view:end -->

## Where the work went

A percent does not say why a month became three. These do, from the same two files, and none of them can stop a commit.

<!-- timeline:start -->
```console
$ gitdone focus
Last 14 days: 13 commits, 1,437 lines changed.
  On plan    8   62%    373 lines   26%  rows 7 (2), 10 (2), 3 (1), 6 (1), 9 (1), 15 (1)
  Upkeep     2   15%     34 lines    2%
  Off plan   3   23%  1,030 lines   72%  in printer (620 lines), theme (410 lines)

Off plan or unclear, newest first:
  2fb7709 Rewrite the receipt printer driver again (280 lines, printer)
  f8ebf86 Try a new theme engine for the kiosk (410 lines, theme)
  1fbaa7d Rewrite the receipt printer driver (340 lines, printer)

Next on the plan: S1 (Reading lists and renewals). It needs the head librarian's word at release.
Off plan is not wrong, only unplanned. If it belongs, `gitdone add "<what it is>"` puts it in the scope, and the percent moves.
To tie a commit to a row, name the row in its message: `row <number>`.
```
<!-- timeline:end -->

- **`focus`** sorts recent commits into on plan, unclear, upkeep and off plan, with the reason for each. Off plan is not wrong, only unplanned: the numbers are named while there is still time to ask why. A hook says one line when a commit was off plan, and `--no-focus` leaves it out.
- **`next`** lists the rows to work on now, in the plan's order.
- **`matrix`** ties each requirement in your spec to its row, evidence and tests, read from git each time, and names the two gaps: a requirement no row names, and a row nobody asked for.

[How each is worked out, and what it cannot tell](docs/timeline.md).

## What installs, and when it runs

Measured from the code, and [`SECURITY.md`](SECURITY.md) has the rest.

| | |
|---|---|
| Dependencies | None: Python 3.9 or newer and its standard library |
| Processes it starts | `git`. `gh` or `glab`, only for a row that names a pull request or merge request, and never with `--offline` |
| Files it writes | The table, the view and the badge (`shipped`, `mark`, `add`, `remove`, `render --write`), what `init` creates, the workflow (`install-ci`), what you pass to `--out`. Reading commands write nothing |
| Git hooks | Only with `install-hook` or `init --hook`. In `.git/hooks`, never committed, and it refuses to replace a hook it did not write. `post-commit` only ever says a line, and `--no-focus` leaves it out |
| Network | None of its own |
| Telemetry, model calls | None |
| Claude Code plugin | One SessionStart hook that prints a line and can never stop a session, two skills, no agent |

## Commands

| Command | What it does |
|---|---|
| `gitdone` | Where the project stands, on the scale, what is next, and whether the gate holds. Also `status`, `opener` |
| `init` | Start a tracker: `--rows`, `--from-checklist FILE`, `--from-issues [LABEL]`, `--hook`, `--ci`, `--agents`, `--badge` |
| `shipped <row> <evidence>` | Move a row to Live, or refuse. Evidence is a commit id, `PR #12`, `MR !12` or `tag v1.2`. `--allow-unverified` takes a claim nothing here could ever check, and the note says so |
| `mark <row> <kind> [note]` | Move a row short of Live, held to that kind's rule. `--branch NAME` |
| `add <name>`, `remove <row>` | Change the scope and keep the counts true. `--domain`, `--new-domain`, `--kind`, `--note` |
| `rows` | List rows. `--open`, `--kind`, `--domain` |
| `check` | The gate. Plain, it fails only on a proven contradiction. `--strict`, what the hook and the Action run, fails on anything not checked. `--offline`, `--if-staged`. [Rules and exit codes](docs/gate.md) |
| `next` | What to work on now: the next workstream's open rows |
| `focus` | Where the commits went: on plan, unclear, upkeep or off plan. `--days`, `--all` |
| `matrix` | A traceability matrix: requirement, row, evidence, tests. `--out`, `--offline` |
| `link <row> <id>` | Tie a requirement to a row, by putting its id in the row's note. The status does not change |
| `week [since]` | What moved since a date, a span or a commit, from the table's git history |
| `render`, `counts` | Print the view or the counts table. `render --write` writes the view; `counts --write` updates a counts table you pasted into the table |
| `chart` | The burn-up: `--out FILE` for an SVG, `--csv`, `--json`, `--group`. `--scale` draws how far along each part is today |
| `badge` | The numbers as a badge: `--svg FILE`, `--endpoint FILE`, `--keep`, `--label` |
| `report` | The evidence behind the numbers, row by row. `--out`, `--offline` |
| `portfolio [folder...]` | Every tracked project under a folder. `--out` |
| `doctor` | Everything the tracker needs here, on one screen. `--offline` |
| `where` | Which plan this folder resolves to |
| `install-hook`, `install-ci`, `install-agents`, `install-skill` | The local gate (`--lenient` only warns about missing evidence, `--no-focus` leaves out the post-commit line), the GitHub Action, the `AGENTS.md` section, a project-level skill |
| `ci`, `mcp` | What the Action runs, and read-only tools over stdio |
| `eta` | Experimental: a line through the table's history, on request. `--days`, `--group`, and `chart --burndown` draws it. [The FAQ](#faq) says why it is off by default |

`--json` works on `gitdone`, `status`, `check`, `next`, `eta`, `focus`, `matrix`, `week`, `where`, `rows`, `report`, `doctor`, `chart` and `portfolio`: [the shapes](docs/json.md).

## The method, in one paragraph

The table is the one place a status changes, and only on a release or a reviewed branch, never because work started. The view is generated
from it, and nobody edits it by hand. Rows are capabilities a stranger could check, not tasks, so the table is also your definition of done,
reviewed like code. [The whole method](docs/method.md) is a page, and it works without the tool. For more depth:
[the status table](docs/status-table.md), [the plan file](docs/plan-file.md), [evidence and the gate](docs/gate.md), [focus, traceability and the date](docs/timeline.md).

## How it compares

These tools are good at other jobs, and most pair well with this one.

| | The question it answers | "Done" means | Is the claim checked against git? |
|---|---|---|---|
| **gitdone** | How far along is this scope, provably? | A commit on the default branch or a merged PR says so | Yes: at commit time, in the PR, and again after a revert |
| Task trackers for agents (beads, Backlog.md, Taskmaster) | What should the agent do next? | Someone closed the task | No |
| Spec tools (spec-kit, OpenSpec) | What are we building? | The tasks under the spec got ticked | No |
| Issue boards (GitHub Projects, Linear) | Who is doing what? | The issue is closed | A linked PR can close it; nothing checks it stayed merged |
| Claim checkers (agent-claimcheck) | Did this agent do what it just said? | The session's trace supports it | At claim time, for one claim, with no view of the project |
| Delivery forecasts (Jira, LinearB, Jellyfish) | When will it ship? | The ticket closed | Against activity, not against what a row claims |
| Traceability tools (Jama, Polarion, DOORS) | Is every requirement covered? | Someone linked and approved it | No, and someone keeps it by hand |
| [Verdict](https://github.com/ArtJack/verdict) | Is what shipped any good? | A QA verdict with evidence | Yes, about quality. The sibling of this tool, and a plan can show its record |

## FAQ

**What gets past the gate?** The hook is a courtesy and CI is the gate: `--no-verify`, a rebase or a cherry-pick skip the hook, and the Action judges what arrived.
A real commit cited for the wrong row passes, and a reviewer sees that on one line of the diff. A pull request can edit the gate's own rules, and the Action says so out
loud. [The rules, and what the gate cannot tell](docs/gate.md#what-the-gate-cannot-tell).

**A commit was reverted and the number did not drop?** The number is what the table says, and only a person moves a row. The gate fails, and the headline
says so, until someone says what is true now. Then the number moves, in a commit with their name on it. The view and the badge change the same way.

**Can a row just be deleted?** Yes: scope is a person's decision, in a diff with their name on it. `week` and the Action's comment say which rows left, the chart's
top line moves, and `rows_total` in the plan makes it a deliberate edit.

**Two branches moved rows, and the table conflicts?** Resolve `status-table.md` as you would any file, then `gitdone render --write`. The gate names a conflict marker
it finds. The view is generated, so either side will do.

**Does it read my code?** No. A status is a person's claim, and the engine holds the claim to its evidence. It proves a commit is on the default
branch, not that the commit holds the feature. The claim and its commit sit on one line of the table's diff, where a reviewer sees them.

**Will it say when the project will be done?** Not unless you ask. No percentage is a date. `gitdone eta` draws a line through the table's own history and says what it is: a line, with a range, not a promise. It is experimental, so until 1.0.0 it shows only when asked for. `"dates": true` in a project's plan puts it beside the percent there. [What it cannot tell](docs/timeline.md#what-the-date-cannot-tell).

**Can `focus` stop a commit?** No. Off plan is not wrong, only unplanned. The hook says one line after the commit, and `--no-focus` takes it out. The numbers exist so that someone can ask, while it still matters.

**We squash-merge.** Cite the squash commit, or the pull request. A branch's old tip is not on the default branch.

**A monorepo?** One tracker per package: the nearest `.gitdone.json` wins. `repo` can also point elsewhere, so a tracker may live apart from
the code it measures.

**GitLab?** `MR !12` is verified through `glab`. So far that path is tested against a stub of `glab`, not a real GitLab; a report from one is welcome.

**Windows?** The suite passes there in CI, on the oldest and the newest Python. The tests that need a POSIX shell are left out, so the hooks, which are `sh` and which Git for Windows runs, are the less proven part.

**No git at all?** It still renders and counts, and every claim stays unproven until there is a repository.

**Do I need the plugin?** No. The engine stands alone. Everything else is a thin layer over the same commands.

## This repository tracks itself

[`STATUS.md`](STATUS.md) is this project's own view, under its own gate, with this roadmap as its scope. The rows that are Live name the commits that
made them so. Its scale and its burn-up, published by [the Action](docs/ci.md) on every push:

<img src="https://raw.githubusercontent.com/ArtJack/gitdone/status-badges/scale.svg" width="640" alt="This repository's own scale: how far along each part of it is.">

<img src="https://raw.githubusercontent.com/ArtJack/gitdone/status-badges/burnup.svg" width="640" alt="This repository's own burn-up chart, from its status table's git history.">

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md). The reports that matter most: a claim the gate accepted and should not have, or refused and should not have.

## Sponsor

GitDone is free and MIT-licensed. If it keeps a false "done" out of your project, you can [sponsor its development on GitHub](https://github.com/sponsors/ArtJack).

## License

[MIT](LICENSE).

GitDone is an independent project, not affiliated with or endorsed by the Git Project. Git is a trademark of Software Freedom Conservancy.
