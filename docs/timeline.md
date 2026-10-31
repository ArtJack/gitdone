# Time, focus and traceability

A percent says how much. These say when, where the work went, and whether the table still answers what was asked. None of them can stop a
commit. They exist so that a change of plan is a decision somebody makes, and not something that happens to a project a commit at a time.

## `gitdone eta`: when

```text
Likely done Apr 14, 85% sure by Apr 29: a line through the last 28 days, not a promise.
Counting only Live rows: likely Jun 23, 85% sure by Jul 31.
Left: 8.7 of 16 rows (weighted 46%, strict 25%).
Pace: 0.21 rows a day; rows moved on 6 of 28 days. 71% of that stopped short of Live, which only a note holds up.
Deadline Apr 15: likely 1 day early, or 69 days late counting only Live rows. It needs 0.2 rows a day from here; the pace is 0.21.
  Work █████████░░░░░░░░░░░ 46%
  Time ███████████░░░░░░░░░ 54%, Jan 12 to Apr 15
```

**What is left** is what the weights leave: a Live row leaves nothing, a Partial row at 0.4 leaves 0.6, and a row not built leaves all of it.

**The pace** is what moved existing rows toward done, per calendar day, over the last 28 days (`--days`), or over the table's life if that is shorter. It
comes from the table's history along this branch's first parents, by the dates the commits keep, so a rebase moves nothing. A day when nothing moved counts, because the time passed. A row moving backwards counts against it.

**Two lines, because a weight is a claim too.** Marking seven rows Partial takes one commit and a word each, and the weighted date jumps. So `eta` also draws the line through rows reaching Live, the only
movement git has held to anything, and says how much of the pace stopped short of it. If the two dates disagree, believe the later one until a row has moved.

**A row added or taken out is not pace.** It changes what is left, and so the date. That is the point: `gitdone add` and `gitdone remove` say what
they just did, as "That moves the likely date from Apr 14 to Apr 19 (+5 days)", and so does the Action's comment on a pull request that changes the scope. A
feature's cost in days is on the table at the moment someone decides to take it.

**The range** comes from the pace's own spread. The likely date is what is left over the pace. The later one is where 85% of futures with the same days,
drawn at random, have finished: a closed form takes the sum of many days as normal, a test holds it to a real resampling, and so the same history always gives the
same words. A pace that came in one burst gets a wide range, and the words say when one day made most of it.

**Scope that keeps growing** changes what the date means, so the headline then says "if the scope stops growing", and `eta` gives the two rates: rows a day of scope against rows a day of work.
If the scope grows as fast as the work moves, it says the work never catches up. That sentence is the reason this command exists. The line through both rates is rough, so it gets a likely date and no range.

**No date is an answer.** Under three days of movement, there is no line to draw. With nothing moved in the window, it says when the table last changed. If rows moved and went back as far, it says that. Past
ten years, it says that. A shallow clone has lost the history, and it says that too.

**A deadline** is `"deadline": "2026-12-01"` in the plan, and `"start"` if the table is younger than the work. Against it, `eta` says how late, how much pace it
needs, and burns time against work on two bars. The view states the deadline, because that is the plan's word. The view never states the forecast, because
that changes with the day and the gate compares the view byte for byte. A moved deadline is said out loud by the hook and the Action.

**In the plan's order:** a workstream is a named set of rows in the plan, and `order` says which comes first:

```json
"workstreams": [{"id": "P1", "name": "Get paid", "rows": "3-5", "needs": "a Stripe test account"}, {"id": "P2", "name": "Launch", "rows": [6, 9]}],
"order": ["P1", "P2"]
```

`eta` reads the order as a sequence and dates each one. That is a roadmap with dates, and it is as good as the order is. `next` lists the first one's open rows. With no workstreams, `next` lists the table's first five open rows.

### What it cannot tell

It is a line through the past. It knows nothing about what a row costs, so it treats them alike, and a big one will surprise it. A table moved in one sitting
makes a poor pace. Use it for the decision it can inform: cut the scope, or move the date. Do not promise it to anyone in the words of a calendar.

### The candle

```bash
gitdone chart --burndown --out burndown.svg
```

What is left over time. It burns down with the work and steps up when the scope grows, with the change marked, or when a row goes back. Past today it has `eta`'s line and its range,
and with a deadline, the line it would take to make it. The same history on the same day gives the same bytes. With `publish-branch` set, [the Action](ci.md) publishes it as `burndown.svg` beside the badge. Plain `chart` stays the
burn-up: the record, with no forecast on it.

## `gitdone focus`: where the work went

```text
Last 14 days: 13 commits.
  On plan    8   62%  rows 7 (2), 10 (2), 3 (1), 6 (1), 9 (1), 15 (1)
  Upkeep     2   15%
  Off plan   3   23%  printer (2), theme (1)
```

Each commit on the current branch in the window (`--days`), since the table's first commit, is one of three. `--all` lists them with the reason, and so does `--json`. The areas are the folders where the commits changed the most.

**On plan** means something ties it to a row, strongest first:

1. **The message names it:** `row 12`, `Row: 12`, `rows 12, 13`, `rows 7-9`, or in the subject, a workstream that has a digit in its id: `P2: reminder sender`.
2. **A row cites it as evidence,** by its id, or by the pull request in its subject.
3. **It moved the row in the table,** or added it.
4. **Its branch or its merge is named for the row:** on a branch `row-12-export`, or a merge tied to the row, which brings along the commits inside it.
5. **The plan ties its files to the row:** at least half of the lines it changed, outside upkeep. `"focus": {"paths": {"12": ["src/export/"], "P1": ["src/auth/*.py"]}}`, by row, range or workstream, from the plan's folder.
6. **Its subject shares the row's words:** two of them, or the row's only one. The numbers say how many counted by this alone.

For a row that has finished, rules 5 and 6 hold only up to the day it finished: after that, a commit on its files or in its words is polish, and it counts as off plan or upkeep.

**Upkeep** is a revert, whatever it reverts; a commit that only touches tests, docs and project files; or one whose subject says `fix:`, `chore:`, `docs:`, `test:`, `ci:`, `build:`, `style:`, `deps:` or `bump`, as long as it changed
200 lines or fewer outside those files, and the rules above did not tie it to a row. A large change is not upkeep for saying so, and `refactor:` is not on the list on purpose.

The files: `tests/`, `test/`, `spec/`, `specs/`, `__tests__/` and the same under any folder, `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`; `docs/`, `doc/`, `*.md`, `*.rst`; `.github/`, `.gitlab-ci.yml`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.pre-commit-config.yaml`; `LICENSE*`; `*.lock`, `package-lock.json`, `pnpm-lock.yaml`, `go.sum`, `go.mod`; `Makefile`, `Dockerfile*`, `docker-compose*.yml`, `pyproject.toml`, `setup.cfg`, `tox.ini`, `requirements*.txt`, `package.json`, `tsconfig*.json`, `Cargo.toml`. `"focus": {"upkeep": ["ops/*"]}` adds to the list, and `"not_upkeep": ["docs/*"]` takes out, for a project whose product is its docs.

**Off plan** is everything else. It names no row and matches none. That is not wrong, only unplanned. If it belongs, `gitdone add "<what it is>"` puts it in the scope,
and the date moves. If it does not, this is where the time went.

Commits that only touch the tracker do not count. A merge does not count as a commit of its own. In a repository's subfolder, with `"repo": "."`, only commits that touch that folder count: a sibling's work is not off this plan.

**When it speaks.** `install-hook` adds a `post-commit` hook, which says one line after a commit that is off plan, and nothing otherwise. It cannot fail a commit: the commit has already
happened, and a rebase is left alone. `--no-focus` takes it out, and someone's own `post-commit` keeps its place, with a word about what that means. The opener says the numbers at the start of a session, `week` says them for its span, and a pull request
that leaves the table alone still gets them in its run's log.

**`gitdone next`** is the other half: the next workstream's open rows, and nothing else. An agent that starts there and names the row in its message needs no other rule.

### What it cannot tell

It reads messages and file names, not code. A commit can say `row 12` and do something else, and a reviewer sees that. The words rule can be wrong in both directions, and
says when it was the rule used. A commit is a poor unit of time: this counts where commits went, with their lines beside them, not hours. So read the percent loosely, and the list of subjects closely.

## `gitdone matrix`: traceability

```markdown
**4 of 5 requirements have a row, and 3 are fully Live (60%).** 8 of 12 rows answer to no requirement. 2 of 3 Live rows have a test on record.

| Requirement | Where | Row | Status | Evidence | Tests |
|---|---|---|---|---|---|
| REQ-1 Sign-in with a magic link | docs/spec.md:3 | 1 | Live | `c5f634c` | `tests/test_link.py` |
| REQ-4 Export to PDF | docs/spec.md:6 | **no row** | | | |
```

A traceability matrix is usually a spreadsheet somebody keeps by hand, which is why it is usually wrong. This one is read from the plan, the table and git, each time. `--out`, `--offline`, `--json`.

**Requirements** come from the files you name: `"requirements": ["docs/spec.md", "ROADMAP.md"]`, inside the project. `init --from-checklist` names its file for you, and takes a spec of `REQ-12: words` lines as well as a checklist. In them, a requirement is `REQ-12: words` in a list, a heading or a
table (any capitals, a dash and a number: `FR-3`, `US-12`, `AC-7.1`), at any depth of a list, or on a line of its own with its colon; or a checklist item. Nothing in a code fence or a comment counts, and neither does prose that happens to mention one, nor a standard like `UTF-8`.

**A requirement finds its row** by its id in the row's name or note, and otherwise by its words: the same words, or three quarters of the shorter one's and at least two. So `- REQ-1: Create an invoice` finds a row named `Create an invoice`. When the words differ, put the id in the row, and there is nothing to guess:

```bash
gitdone mark 4 partial "REQ-7: the template exists"
```

**The two gaps** are the point. A requirement with no row means the percent and the date leave it out, so the opener warns, and `check` and the Action's comment say so on every run, including a pull request that only changes the spec. It stops nothing:
it is not a claim anybody made. A row no requirement asks for is scope nobody asked for, or a requirement nobody wrote down.

**Tests** on record are the ones that changed in a commit the row cites or a commit that names the row, and that still exist; and any test path in backticks in the row's note, if it exists. With no requirement
files, the matrix is the rows, with their evidence and tests.

### What it cannot tell

A test listed here exists. Whether it passes is your CI's word, and whether it tests the requirement is a reviewer's, or [Verdict](https://github.com/ArtJack/verdict)'s. It does not judge whether the
code does what a requirement says. No tool that does not read the code could.
