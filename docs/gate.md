# Evidence and the gate

`gitdone check` applies three rules:

1. **The view is true.** `STATUS.md` on disk equals a fresh render, apart from its generated-date line. So does the badge, if the
   plan names one.
2. **The counts sum.** Each domain's rows match its header, each group's rows match its total, the whole table matches
   `rows_total`, and a counts table inside the status table matches the rows.
3. **Each status has the evidence its kind asks for.**

## What counts as evidence

A **Live** row names a release in its status or note:

| Named as | Read as | Verified by |
|---|---|---|
| `` `1a2b3c4` ``, a bare id with a digit and a letter, or a commit URL of this repository | A commit | The rules below |
| `PR #12`, `pull request 12`, `PRs #12 and #13`, a `/pull/12` URL of this repository | A GitHub pull request | Merged into the default branch, through `gh`, and its commit holds to the rules below |
| `MR !12`, `merge request 12`, a `/merge_requests/12` URL | A GitLab merge request | The same, through `glab` |
| ``tag `v1.2.0` ``, `tag v1.2.0`, `release v1.2.0` | A git tag | Its commit holds to the rules below |
| A match of the plan's `evidence_pattern` | Your own convention | A named group `ref` as a commit id or a tag; anything else is only reported, and `--strict` does not count it |

A bare `#12` is not read as a pull request, because it may be an issue or a list number. A link into another repository is not evidence
here, whatever its number, and it takes its words with it: `[PR #12](https://github.com/vendor/lib/pull/12)`, the same as a reference-style link, and `PR #12` beside
a link to that number. A link is compared by host and whole path, against `origin` and `upstream` when they exist, so a vendor kept as another remote is not this repository. With no
remote to compare it with, no such link can be called ours. A link to your own site, a CI run or a ticket keeps its words: the claim is in the row, and git judges it. So does a link to a repository
root on a forge the engine has no name for, which reads as a site.

**The rules a commit answers to:**

- **It is on the default branch.** With a remote, that means the remote's: `origin` or `upstream`, or a lone remote of any name, or, among several others, the one git
  tracks the branch on (`branch.main.remote`, `remote.pushDefault`). A commit only on your local `main` has not shipped, and it is told to push, including when nothing has been
  pushed yet. Beside those, another remote's branch of that name does not count.
- **It resolves as a commit id.** A tag or branch that happens to be named like an id is not that commit. Two commits sharing a short id settle on
  the one on the default branch.
- **It was not reverted,** below.
- **It changes something.** An empty commit, or one that only changes the tracker's own files, is no evidence. A merge is held to what it changed against its first parent.
- **It does more than take work out.** A commit whose subject says `Revert "X"` is no evidence, so a claim cannot be mended by citing its own revert. `Revert "Revert "X""` and `Reapply "X"` put the work back, and count. If taking something out is what a row asks for, cite a commit that does more than the revert.
- **Its content arrived.** A commit that came in from the side is no evidence if the merge that landed it took none of its changes, as `git merge -s ours` does. Its files
  being there with those very bytes counts, whoever brought them, as with a hotfix cherry-picked and merged back.

A merged pull request or merge request answers to these same rules through the commit the forge names. One that only edits the table is no evidence. If the forge names no
commit, or on a rebase merge names a last commit that only edits the table, cite the commit that holds the work.

A **Built, not live** row names a branch that exists and is not the default branch: as ``branch `name` `` in the note, or else in its status cell's
parenthesis, through `branch_aliases` if the plan has them. With a remote, a branch only on this machine is told to push, since a clone and CI cannot find it.

A **Partial** row has a note a reader can see: a comment, `&nbsp;` or `<br>` is not one.

## A claim can stop holding

A row is checked again on every run, so a claim can go bad after it was accepted. A commit whose revert is on the default branch is a contradiction:
`commit 660d81a was reverted on main by 3f6610b`. That covers:

- `git revert`, with or without `--reference`, and a revert of a merge, which reverts what the merge brought in too;
- GitHub's revert button (`Reverts owner/repo#30`), for a row citing the pull request or the commit that landed it;
- GitLab's wording (`This reverts merge request !12`);
- a revert in the indented text of a local squash, and a revert whose target a rebase renamed, found by its subject.

A revert of the revert puts the claim back, however the history is dated. A commit that changes nothing reverts nothing, whatever its message says, and neither does a revert a
merge threw away. A revert only on this machine counts against a claim; a reapply only on this machine has not put it back. A merge with nothing left of what it brought in, each commit reverted, thrown away,
empty or only the table's, is undone, and so is the pull request it landed. Another repository's pull request in a message is not ours. In a squash quoting several reverts, each line answers for itself: it counts when the
commit's change is gone from its files, and not when the squash only touched them.

The rule reads messages. It does not see a revert with its words removed (an amended message, `git revert -n`), or a later commit or merge that takes the files away, including a revert of an
older commit that touches the same files. When one commit was reverted twice, or reapplied twice, and a later line names only one of them, the words can read differently from the files, in
either direction. A rebase-merged pull request of several commits leaves no trace of which commits it had, so a row citing the pull request sees the button's revert,
and a row citing one of its commits sees it only if that commit's subject is the title. Cite the pull request.

## Modes and exit codes

A plain `check` warns on missing evidence and fails only on a proven contradiction. `--strict` promises that **every claim was checked**. The hook and the
Action are strict by default, because that is what "refused" has to mean.

| What it found | Plain `check` | `--strict` |
|---|---|---|
| A claim disproved, with nothing better beside it | `FAIL` | `FAIL` |
| A row that names nothing its kind asks for | `WARN` | `FAIL` |
| A claim nothing could ever settle: no repository, a pull request with no remote, merged into another branch | `WARN` | `FAIL` |
| A claim that holds in name only: an empty commit, a tracker-only commit, a merge that took nothing, a commit or a branch only on this machine | `WARN` | `FAIL` |
| A commit the local clone lacks, when a remote exists | `WARN` | `FAIL` |
| A claim disproved or unproven beside one that holds | `WARN` | `FAIL` |
| A line that looks like a row and is not read as one | `WARN` | `FAIL` |
| A claim nothing can answer for right now: `--offline`, or `gh` not there or not answering | `NOTE` | `FAIL` |
| A bare word that only looks like an id, or a match of the plan's own pattern, beside a claim that holds | `NOTE` | `NOTE` |

A row stands on the strongest thing it names, because a note may also mention a commit that is not the release. Offline, a strict commit that touches a
table naming pull requests stops: cite the commit instead, or commit with `--no-verify` and let CI judge it.

`shipped` holds everything it is given to this: nothing unverified goes in unless `--allow-unverified` says so, and the note then says it was unverified. That flag takes only
what nothing here can answer for (a pull request with `gh` down or no remote, a commit with no repository yet), never a claim git disproves or one that holds in name only, and
`--strict` goes on failing on it.
`install-hook --lenient` writes the gentler hook, where only a proven contradiction stops a commit. It suits a table moving onto the method with history
behind it.

A shallow clone stops the gate with exit 2, since a commit or a revert could be missed.

| Exit | Meaning |
|---|---|
| 0 | Clean, or only warnings in a plain `check` |
| 1 | A proven contradiction: a stale view, counts that do not sum, a row whose every claim git or the forge disproves |
| 2 | Could not run: a usage error, an unreadable plan or table, a `repo` that is not a repository, git itself failing |
| 3 | `--strict` only: evidence is missing, unverified or partly disproved, and no row is left with nothing but contradictions |

## The local gate

`gitdone install-hook` writes `pre-commit` and `pre-merge-commit` hooks into the repository holding the status table. They
are never committed, and the command refuses a `core.hooksPath` inside the work tree or shared with other repositories, and refuses to
replace a hook it did not write. They run `check --if-staged --strict`, and `--if-staged` differs from a plain `check` in two ways:

- **It judges what the commit will contain,** read from git's index, not what is on disk. A table staged without its view is
  refused, and so is a bad row fixed on disk but not staged. An unstaged edit in progress does not count against a good commit.
- **It stays out of every other commit.** A commit that does not touch the plan, the table, the view or the badge is not checked at
  all.

The hook outlives whatever installed it. It runs the engine that installed it, else `gitdone` on `PATH`, else the Claude Code
plugin's newest copy, else `uvx`. If none of those is there, a commit that touches the tracker is stopped, since it cannot be
judged, and any other commit goes through. A fast-forward merge runs no hook; what it brings in was judged when it was committed.

One hook serves every tracker in a repository: the plans come from the files a commit changes. Removing the tracker's files is allowed. A plan that cannot be read
stops a commit that touches it or what is usually the table.

Already use a hook manager? See [CI and other gates](ci.md).

## What the gate cannot tell

**The hook is a courtesy; CI is the gate.** git runs no pre-commit hook for a fast-forward, a cherry-pick, a rebase, `git am`, or plumbing, and `--no-verify`
and a fresh clone with no hook skip it too. The Action judges what reached the pull request however it got there, and the headline says so at the next
session's start when a table no longer holds.

**The local gate trusts `.git`.** Someone who can edit `.git` can make git say other things: a hand-made ref, a replaced object. A clone in CI is out of reach of that.

**The rules live in a file a change can edit.** A pull request can change the plan's weights, kinds or `default_branch`, or move them to a new file. The gate holds what it can
(the strict kind must ask for a release, and a key given twice, an unknown key in a kind or a key nearly named like a rule is refused), and both the hook and the Action say
out loud when a change touches the rules. A reviewer decides whether that is right.

**Tables are read for what they most plainly are.** A table in a quote with no leading pipes is not seen, a table in a list item after a line of plain text may not be, and an invisible
heading made of unusual characters can end a domain. The count in each domain's heading, and `rows_total` in the plan, are what catch a row that went missing this way.

**It proves a commit is on the default branch, not that the commit holds the feature.** A real commit cited for the wrong row passes. The claim and its commit sit on
one line of the diff, where a reviewer sees them. It compares files, not meaning, so a merge that rewrites the commit's own file counts as having taken it.

**A squash-merged branch's tip is not on the default branch,** so cite the squash commit or the pull request. A tag on a release branch that never reaches the default
branch fails; point `default_branch` at the branch you release from if that is your flow.
