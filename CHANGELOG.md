# Changelog

## 0.3.0 (unreleased)

The percent said how much. This says when, and where the time went.

**`eta`: when.** A line through the table's own git history, with a range, and the words say it is a line. Two lines, as the percent has strict and weighted: one on Live rows alone, and one with all work, because one commit can mark seven rows Partial and the
weighted date jumps. A row added or dropped moves the date, and `add` and `remove` say by how many days, so a feature's cost is on the table when someone decides to take it. When scope keeps growing, the headline says the date assumes it stops, `eta` gives the two rates, and
if it grows as fast as the work, it says the work never catches up. With too little history it gives no date. `chart --burndown` draws it: what is left on both lines, up when the scope grew, with the dates, the range and the deadline.

**A deadline.** `"deadline"` in the plan. `eta` says how late on each line, what pace each needs, and burns time against work on bars. The view states it, and moving it is said out loud.

**`focus`: where the commits went.** On plan means someone said so: the message names the row, a row cites the commit, it moved the row, a merge is tied to the row, or the plan ties its files to the row. What only looks like a row is unclear, and it is listed with what is off plan, with its lines, because a guess must not close a gap.
A signal that cannot stop anything. `next` lists the rows to work on now. `install-hook` adds a `post-commit` hook that says one line after a commit that was off plan. The opener, `week` and the Action say the numbers, and the agent rules now say: work on what `next` lists, name the row, and say so before starting work on no row.

**`matrix`: traceability read from git.** `"requirements"` names your spec and your roadmap, and `init --from-checklist` takes a spec of `REQ-12: words` lines and names it for you. A row holds a requirement if it names its id or says the same words; anything weaker is a suggestion, and `link` writes the id where later moves keep it. Each requirement goes to its evidence and tests. Two gaps are named:
a requirement no row names, which the opener, `check` and the Action say on every run, and a row nobody asked for. A test listed exists; whether it passes is your CI's word.

**Where others work.** The Action's comment says what a pull request does to the scope and the date, and it publishes `burndown.svg`. `portfolio` has a likely date per project. The MCP server has `eta`, `focus`, `next` and `matrix`.

**An independent attack reproduced 42 defects in the first cut of this layer, and two cold reads found what a stranger's first hour taught, and each now has a test.** A long line in a spec could hang the gate; a suggested command could run what a hostile spec put in it. `eta` chose its commits
by the committer's date, so a rebase moved the date and one old commit hid the rest: it now reads what the history keeps. A future clock, a broken commit, a renamed or copied table, a shallow clone and a tracker beside another all told it something false, and no longer do. A row's number is no longer given out again.

**A third reader, who had seen neither of the first two reports, found 23 more, and five of them mattered most.** A row closed a requirement that said different words, because the comparison dropped numbers and words like add and remove: `Add SMS login` held `Remove SMS login`, and now only the same words do. Any merge that moved the table made everything inside it read as on plan, and a pull request's own run is such a merge, so the Action's line could say the opposite of the branch: a commit is now judged by its own change. A line of comments in a spec, a list of patterns in a plan, the ranges in one commit message and a table's old versions could each hold up a run far longer than their bytes should allow, and each now has a limit. `focus` stops after ten seconds and says it looked at part of the history. The first commit is no longer told it is off plan, a lock file in a folder is upkeep, a test on record is a test written since the table began, and a date with groups says it covers them all.

**Still not in it.** No reading of code, and no gate on any of this: nothing here changes an exit code. A `deadline` is the plan's word and the view states it, so setting one takes a render, as any edit to what the view shows does. The burn-up and the view carry no forecast.

## 0.2.0 (2026-10-31)

The first version meant for other people's machines.

**Install anywhere.** `uvx gitdone` and `pipx install gitdone`, with zero dependencies, on Python 3.9 to 3.14. The Claude
Code plugin bundles the engine and needs no environment variable or home-folder convention. `install-hook` writes a hook that survives a
plugin update, a moved checkout or a replaced Python. Plan discovery no longer names a private folder, and `.gitdone.json` may be
the plan itself.

**Onboarding.** `init` starts a tracker from words, a checklist or GitHub issues, including in a repository with no commit yet. `add` and
`mark` change a table without touching its shape, and `remove` takes a row out. `rows` lists it. `doctor` checks everything on one screen. The bare command prints where
the project stands. `--json` on the reading commands, and a JSON schema for the plan.

**A gate that means it.** `install-hook` is strict by default: a commit that adds a Live row with nothing behind it is refused, not warned about, and
`--lenient` is there for a table with history behind it. A claim nothing could ever settle (no repository, a pull request with no remote, merged into
another branch) now counts as missing evidence. `shipped` refuses what nothing here can check unless `--allow-unverified` says otherwise. A checked
checklist item with no commit starts as Partial, so the first number printed is true. The headline says when the gate fails. A cold reader found all
of these, in the first hour of the first test.

**Evidence.** A claim stops holding when its commit or pull request is reverted on the default branch, through `git revert` or GitHub's
button, including what a reverted merge brought in. Tags count as evidence, and GitLab merge requests through `glab` (so far tested against a stub). A pull
request past `gh`'s list limit is asked about on its own.

**Claims that hold in name only are refused.** Two independent readers attacked the gate before release, about 250 attacks in all, and these closed what they found: a tag
named like a commit id is not that commit; an empty commit, a tracker-only commit, and a commit that arrived through `git merge -s ours` are no evidence; a commit only on your
local branch has not shipped; another repository's link is not evidence; an empty commit with revert words reverts nothing; a merged pull request's commit must really be on the
branch. `--strict` now means every claim was checked, so `MR !1` on a machine with no `glab` does not pass it. Rows cannot hide in a code fence, a comment or a typo, a table's
third column must say Status, and a shallow clone stops the gate.

**Then an independent code review reproduced 47 more defects, and four more passes 34, 22, 16 and 6 in the fixes, and each now has a test.** A property test, from the same reader, now builds random
histories whose every commit adds files of its own, so that a commit's bytes at the tip say whether its content arrived. A plan could name `.git/hooks/pre-commit` as its view, so that a stranger's words ran on the next
commit: refused now, under any spelling. A pull request answers to the commit rules through the commit the forge names, so one that only edits the table is no evidence. A merge answers
to them too. A commit is not verified until it is pushed, including to a remote with nothing on it yet. `--strict` fails a claim in name only even beside a good one. Reverts are read
newest first in topological order, so no date can hide one, and `git revert --reference`, `Reapply` and SHA-256 ids are understood. "Its content arrived" is judged per commit at the
merge that landed it, which finds `-s ours` on a side branch and stops calling a merged-back hotfix hollow. A link's words go with the link, so `[PR #12](another repo)` is no claim. A
table defining your statuses no longer fails strict, and rows hidden or dropped by inline code, an odd fence or a comment now read the way Markdown reads them. git failing is never an
answer, moving the table or the rules away is judged, and three slow regular expressions are gone.

**The repository being judged is untrusted.** The hook, the shim and the Action run Python with `-I`, so a planted module is not what runs. A committed bare repository cannot make
git run a command. A plan cannot write outside its project, or reach through a symbolic link. A change to the gate's own rules is said out loud, by the hook and the Action.
`--publish` joins what a branch holds and refuses the default branch. A device or a pipe named in a plan is not read, and an escape sequence from a table is shown and not obeyed.

**From a second cold read.** `init` holds checked items to git before printing the first number, so its first commit is never refused for what it accepted. `install-ci` and `init --ci` add
the Action. `--json` goes before or after the command. `--allow-unverified` takes every claim nothing here can answer for, leaves a mark in the note, and is refused for a claim that holds in name
only. A failure says what to do next, on its own line and as `next` in JSON. `doctor` and the headline name the row. A merge conflict in the table says so.

**Visibility.** `chart` draws a burn-up from the table's git history, and makes no forecast. `badge` writes an SVG or a shields.io endpoint,
and a plan can keep one with the view, held to the table by the gate, so a README can show the numbers with no CI. `report` gives the
evidence row by row. `portfolio` puts every tracked project on one page.

**Where others work.** A GitHub Action with annotations on the table's lines, one sticky comment and a badge branch. `.pre-commit-hooks.yaml`
for the pre-commit framework. A skill for every coding agent, `install-agents` for `AGENTS.md`, and a read-only MCP server with no dependency.

**Speed.** `check` settles a table's claims in a few git processes rather than a few per row: 546 ms down to about 100 ms on 40 rows, and a test
pins it. Rarely used commands are imported only when asked for.

**Not in it, deliberately.** No forecast. No reading of code. No runtime dependency. On Windows the suite runs in CI, with the tests that need a POSIX shell left out, so the hook is less proven there.

MIT license, CI, contribution and security notes, issue templates.

## 0.1.0 (2026-10-30)

The private tool: `render`, `counts`, `check`, `opener`, `shipped`, `week`, `where`, `install-hook`, `install-skill`, the
Claude Code plugin, 242 tests. One adopter.
