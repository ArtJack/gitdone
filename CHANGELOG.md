# Changelog

## 0.2.0 (unreleased)

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

**Not in it, deliberately.** No forecast. No reading of code. No runtime dependency. Windows is run in CI and not yet proven.

MIT license, CI, contribution and security notes, issue templates.

## 0.1.0 (2026-10-30)

The private tool: `render`, `counts`, `check`, `opener`, `shipped`, `week`, `where`, `install-hook`, `install-skill`, the
Claude Code plugin, 242 tests. One adopter.
