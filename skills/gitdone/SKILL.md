---
name: gitdone
description: "Use when a person asks how far along a project is, what is left, what shipped, or what to work on next, and the project has a .gitdone.json; when finishing work that a row of status-table.md describes; or when someone wants progress tracked with evidence rather than by feel. It reads strict and weighted completion from git-checked evidence, and moves a row only when git agrees."
---

# gitdone

A project's status lives in two files and one rule. `status-table.md` holds one row per capability, each with one status.
`STATUS.md` is generated from it. A row is Live only when a commit on the default branch or a merged pull request says so.

The command is `gitdone`. If it is not installed, `uvx gitdone` runs it with nothing to set up.

## Read freely

| To learn | Run |
|---|---|
| Where the project stands, and what is next | `gitdone` |
| Which rows are left | `gitdone rows --open` |
| What moved lately | `gitdone week` |
| Whether the claims hold | `gitdone check` |
| What each claim rests on | `gitdone report --offline` |
| Everything the tracker needs, on one screen | `gitdone doctor` |
| What to work on now | `gitdone next` |
| Where the recent commits went: on plan, upkeep, off plan | `gitdone focus` |
| Requirement to row to evidence to tests | `gitdone matrix --offline` |
| When it will be done, if the person asks | `gitdone eta` |

Add `--json` to any of these for data.

Answer from what these print. Do not estimate a percentage from reading the code, and do not turn a percentage into a date. The only
date to quote is the one `gitdone eta` prints, when the person asks, with its range and its words: it is an experimental line through the past, not a promise. If it has no date, there is none.

## Hold the line

Start from `gitdone next`. Work on those rows, and name the row in the commit message (`row 12`), so that the work traces to it.
If what you are about to do is on no row, say so before you start it, and let the person decide: if it belongs, `gitdone add` puts it in
the scope, and the percent moves. If `gitdone focus` shows work drifting off plan, say that too, in its own numbers. A requirement no row names: `gitdone link <row> <id>` if a row holds it, and that is the person's call.

## Change a row only like this

- **Work reached the default branch:** `gitdone shipped <row> '<commit or PR #n>'`. It refuses evidence git or `gh`
  disproves, and it edits the table and the view. It does not commit.
- **Work short of that:** `gitdone mark <row> <kind> [note]`, with `--branch <name>` for a built branch.
- **A change of scope:** `gitdone add "<name>"` or `gitdone remove <row>`. A change of scope is the person's decision, so ask first.

Move a row when the person asked you to, or when the project's own instructions say to ship rows as work lands. Never choose
a status from your own reading of the code.

## When the gate says no

If `shipped` or the commit gate refuses, report the refusal in its own words and stop. Do not reword the row, do not hand-edit
the table to Live, do not edit `STATUS.md`, do not pass `--allow-unverified`, and do not commit with `--no-verify`. A refusal is the
tool working.

"Done" in your message means the row moved. Say what the gate said, not what you believe.

## Starting a tracker

`gitdone init --rows "A, B, C"`, or `--from-checklist TODO.md`, or `--from-issues <label>`. Rows are capabilities a
stranger could check, not tasks. Propose them and let the person decide the scope. `--hook` adds the local gate, and `--agents`
writes these rules into `AGENTS.md`.
