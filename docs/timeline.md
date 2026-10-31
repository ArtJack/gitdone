# Time, focus and traceability

A percent says how much. These say when, where the work went, and whether the table still answers what was asked. None of them can stop a
commit. They exist so that a change of plan is a decision somebody makes, and not something that happens to a project a commit at a time.

## `gitdone eta`: when

```text
Likely done Apr 14, 85% sure by Apr 29: a line through the last 28 days, not a promise.
Left: 8.7 of 16 rows (weighted 46%, strict 25%).
Pace: 0.21 rows a day; rows moved on 6 of 28 days.
Deadline Apr 15: likely 1 day early. It needs 0.2 rows a day from here; the pace is 0.21.
  Work █████████░░░░░░░░░░░ 46%
  Time ███████████░░░░░░░░░ 54%, Jan 12 to Apr 15
```

**What is left** is what the weights leave: a Live row leaves nothing, a Partial row at 0.4 leaves 0.6, and a row not built leaves all of it.

**The pace** is what moved existing rows toward done, per calendar day, over the last 28 days (`--days`), or over the table's life if that is shorter. It
comes from the table's history on the main line. A day when nothing moved counts, because the time passed. A row moving backwards counts against it.

**A row added or taken out is not pace.** It changes what is left, and so the date. That is the point: `gitdone add` and `gitdone remove` say what
they just did, as "That moves the likely date from Apr 14 to Apr 19 (+5 days)", and so does the Action's comment on a pull request that changes the scope. A
feature's cost in days is on the table at the moment someone decides to take it.

**The range** comes from the pace's own spread. The likely date is what is left over the pace. The later one is where 85% of futures with the same days,
drawn at random, have finished: a closed form takes the sum of many days as normal, a test holds it to a real resampling, and so the same history always gives the
same words. A pace that came in one burst gets a wide range, and the words say when one day made most of it.

**Scope that keeps growing** is extrapolated too, once it has grown on more than one day. If it grows as fast as the work moves, `eta` says the work never
catches up. That sentence is the reason this command exists.

**No date is an answer.** Under three days of movement, there is no line to draw. With nothing moved in the window, it says when the table last changed.
Past ten years, it says that.

**A deadline** is `"deadline": "2026-12-01"` in the plan, and `"start"` if the table is younger than the work. Against it, `eta` says how late, how much pace it
needs, and burns time against work on two bars. The view states the deadline, because that is the plan's word. The view never states the forecast, because
that changes with the day and the gate compares the view byte for byte. A moved deadline is said out loud by the hook and the Action.

**In the plan's order:** with workstreams, `eta` reads `order` as a sequence and dates each one. That is a roadmap with dates, and it is as good as the order is.

### What it cannot tell

It is a line through the past. It knows nothing about what a row costs, so it treats them alike, and a big one will surprise it. A table moved in one sitting
makes a poor pace. Use it for the decision it can inform: cut the scope, or move the date. Do not promise it to anyone in the words of a calendar.

### The candle

```bash
gitdone chart --burndown --out burndown.svg
```

What is left over time. It burns down with the work and steps up when the scope grows, with the change marked, `eta`'s line and its range past today,
and with a deadline, the line it would take to make it. The same history gives the same bytes. The Action publishes it as `burndown.svg` beside the badge. Plain `chart` stays the
burn-up: the record, with no forecast on it.

## `gitdone focus`: where the work went

```text
Last 14 days: 13 commits.
  On plan    8   62%  rows 7 (2), 10 (2), 3 (1), 6 (1), 9 (1), 15 (1)
  Upkeep     2   15%
  Off plan   3   23%  printer (2), theme (1)
```

Each commit on the current branch in the window (`--days`) is one of three. `--all` lists them with the reason, and so does `--json`.

**On plan** means something ties it to a row, strongest first:

1. **The message names it:** `row 12`, `Row: 12`, `rows 12, 13`, `rows 7-9`, or in a merge, a branch `row-12-export`. A merge tied to a row brings along the commits inside it.
2. **A row cites it as evidence,** by its id, or by the pull request in its subject.
3. **It moved the row in the table,** or added it.
4. **The plan ties its files to the row:** at least half of the lines it changed, outside upkeep. `"focus": {"paths": {"12": ["src/export/"], "P1": ["src/auth/*.py"]}}`, by row, range or workstream.
5. **Its subject shares the row's words:** two of them, or the row's only one. For a row that finished, this holds only up to the day it finished.

**Upkeep** is a commit that only touches tests, docs and project files, or whose subject says `fix:`, `chore:`, `docs:`, `test:`, `ci:`, `build:`, `style:`, `revert` or `bump`. Set
`"focus": {"upkeep": ["ops/*"]}` to replace the list of files. `refactor:` is not on it on purpose.

**Off plan** is everything else. It names no row and matches none. That is not wrong, only unplanned. If it belongs, `gitdone add "<what it is>"` puts it in the scope,
and the date moves. If it does not, this is where the time went.

Commits that only touch the tracker do not count. A merge does not count as a commit of its own.

**When it speaks.** `install-hook` adds a `post-commit` hook, which says one line after a commit that is off plan, and nothing otherwise. It cannot fail a commit: the commit has already
happened. `--no-focus` leaves it out, and someone's own `post-commit` keeps its place. The opener says the numbers at the start of a session, `week` says them for its span, and a pull request
that leaves the table alone still gets them in its run's log.

**`gitdone next`** is the other half: the next workstream's open rows, and nothing else. An agent that starts there and names the row in its message needs no other rule.

### What it cannot tell

It reads messages and file names, not code. A commit can say `row 12` and do something else, and a reviewer sees that. The words rule can be wrong in both directions, and
says when it was the rule used. A commit is a poor unit of time: this counts where commits went, not hours.

## `gitdone matrix`: traceability

```markdown
**4 of 5 requirements have a row, and 3 of them are all Live (60%).** 8 of 12 rows answer to no requirement. 2 of 3 Live rows have a test on record.

| Requirement | Where | Row | Status | Evidence | Tests |
|---|---|---|---|---|---|
| REQ-1 Sign-in with a magic link | docs/spec.md:3 | 1 | Live | `c5f634c` | `tests/test_link.py` |
| REQ-4 Export to PDF | docs/spec.md:6 | **no row** | | | |
```

A traceability matrix is usually a spreadsheet somebody keeps by hand, which is why it is usually wrong. This one is read from the plan, the table and git, each time, and
an agent has nothing to keep up but the commit messages. `--out`, `--offline`, `--json`.

**Requirements** come from the files you name: `"requirements": ["docs/spec.md", "ROADMAP.md"]`, inside the project. In them, a requirement is `REQ-12: words` in a list, a heading or a
table (any capitals, a dash and a number: `FR-3`, `US-12`, `AC-7.1`), at the start of the line, or a checklist item. Nothing in a code fence or a comment counts, and neither does prose that happens to mention one.

**A requirement finds its row** by its id in the row's name or note, or a checklist item by its words. Name the id in the row, and there is nothing to guess.

**The two gaps** are the point. A requirement with no row means the percent and the date leave it out, so the opener warns, and `check` and the Action's comment say so on every run. It stops nothing:
it is not a claim anybody made. A row no requirement asks for is scope nobody asked for, or a requirement nobody wrote down.

**Tests** on record are the ones that changed in a commit the row cites or a commit that names the row, and that still exist; and any test path in backticks in the row's note, if it exists. With no requirement
files, the matrix is the rows, with their evidence and tests.

### What it cannot tell

A test listed here exists. Whether it passes is your CI's word, and whether it tests the requirement is a reviewer's, or [Verdict](https://github.com/ArtJack/verdict)'s. It does not judge whether the
code does what a requirement says. No tool that does not read the code could.
