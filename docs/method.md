# The method

The tool enforces a small method. It works without the tool, and the tool only makes it cheap.

## One source, one view, one plan

- **The source is the status table.** Every row of the scope has one status and its evidence. A status changes only there,
  and only on one of two events: a release, or a branch that passed a review, with the branch named. A status never changes
  because work started.
- **The view is `STATUS.md`.** It is generated: percentages by domain and by workstream, strict and weighted, then the order
  and whatever else the plan holds. Nobody edits it by hand.
- **The plan holds the moving parts:** the order, each workstream's state and what it needs, the asks, the decisions, the
  candidates. When the plan changes, the plan file changes with it, in the same commit.

There is no fourth list. The view's workstream table is the project's queue.

## What a row is

A row is a capability a stranger could check: "Self-checkout", not "refactor the scanner module". Tasks come and go, and a
good tracker of tasks can reach 100% while the product does not work. The rows are what must exist for the project to be
done, so the table is also the project's definition of done, in one place, reviewed like code.

Choosing them is the part no tool can do for you. It is also the part that pays: the first honest table usually shows a
project is further from done than anyone was saying, and shows it early.

## The rhythm

1. **Every session starts with the view.** One line: strict and weighted percent, the next workstream, what blocks it. That
   takes thirty seconds, and it answers the drift question before work starts.
2. **Work is one of three kinds:** the plan's next workstream, the owner's pick (something named instead, in their words), or
   work outside the scope. Nothing is forbidden; everything is visible. `focus` shows which commits were which.
3. **A step is done when a row's status changed,** with the evidence beside it and the view regenerated.
4. **Weekly, fifteen minutes:** `week` prints what moved. Write one line: what moved, what did not, and why. A monthly report
   is written from those lines.
5. **A request from outside becomes a candidate in the plan.** A candidate enters a workstream only when the owner says so.
6. **Asks of other people live in the plan,** with the date asked and the state.
7. **Decisions stay listed until decided.** A decided one moves to a decision journal in the owner's words, and leaves the list.

## What the percentages mean, and what they do not

- **Strict** is what an outside reviewer would count: rows that are Live.
- **Weighted** also credits work short of a release, at weights the plan states, so that the number can be argued with.
- **No percentage is a date.** Only a pace can say when. `eta` draws a line through the table's own history, gives a range, and says in the same
  sentence that it is a line. It is there for one decision: cut the scope, or move the date. It is experimental and shows only when asked for, unless a plan says `"dates": true`. The view never shows it, and the burn-up stays a record.

Strict alone hides real work and punishes a project with a long review queue. Weighted alone lets a project look nearly done
for a year. The gap between them is itself a signal: work built and not shipped.

## How it stays honest

- The engine checks the table's shape. If a count, a total or a status does not fit, it stops rather than guess.
- Weights, order and states are data, not code. Changing them is a commit with a reason.
- If the view and the table disagree, the table wins and the view is regenerated.
- A change of scope shows: the chart's top line moves, and `week` says "rows are new since then". Set `rows_total` in the plan,
  and growing the scope becomes a deliberate edit.
- Nothing here rates a row by reading code. A status is a person's claim, and the engine holds the claim to its evidence.

## What it cannot tell

The gate proves a commit is on the default branch, not that the commit holds the feature. A reviewer reading the table's diff
is still the last check, and it is a good one: the claim and its commit are side by side on one line. Quality is a separate
question. [Verdict](https://github.com/ArtJack/verdict), by the same author, judges it, and a plan can name Verdict's state
file so that the QA record shows beside the release line.

## A sample

[`examples/bramble/STATUS.md`](../examples/bramble/STATUS.md) is the view for Bramble Kiosk, a fictional library kiosk, generated
from [`plan.json`](../examples/bramble/plan.json) and [`status-table.md`](../examples/bramble/status-table.md) beside it. It uses
most of what a plan can do: groups, workstreams, a custom kind, candidates, decisions and asks.
