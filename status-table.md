# gitdone: where each capability stands

This repository holds itself to its own gate. This table is the only place a row's status changes, and `STATUS.md` is generated
from it.

### 1. The engine (6)

| # | Capability | Status | Note |
|---|---|---|---|
| 1 | The view: a pure function of a plan and a table | Live | `render`, `counts`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 2 | The gate: view true, counts sum, evidence per kind, four exit codes | Live | `check`, `--strict`, `--offline`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 3 | A row moves on evidence, and refuses what git disproves | Live | `shipped`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 4 | What moved, from the table's git history | Live | `week`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 5 | A local gate that judges what the commit will contain | Live | `install-hook`, `check --if-staged`, worktrees and merges. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 6 | A session starts with where the project stands | Live | The SessionStart hook. *(Live 2026-10-31: `cc13a2b`; was Partial)* |

### 2. Installs anywhere (8)

| # | Capability | Status | Note |
|---|---|---|---|
| 7 | `uvx` and `pipx` install it with zero dependencies, on Python 3.9 and up | Live | Wheel built and run on 3.9 and 3.14 from an empty folder. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 8 | The Claude Code plugin bundles the engine and needs no environment | Live | Validated and installed into a clean Claude config, and run under `env -i`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 9 | The hook survives a plugin update, a moved checkout and a replaced Python | Live | Falls back from the installing engine to PATH, the plugin, then `uvx`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 10 | Plan discovery names no private folder | Live | The plan may be the pointer file itself. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 11 | MIT license and the policy files | Live | LICENSE, CONTRIBUTING, SECURITY, AGENTS, llms.txt, issue templates. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 12 | CI on three operating systems, on the floor and the newest Python | Live | Green on all three. On Windows the tests that need a POSIX shell are left out. *(Live 2026-10-31: `1a8403d`; was Partial)* |
| 13 | A release workflow by Trusted Publishing that refuses a mismatched tag | Live | It published 0.2.0 to PyPI, the GitHub Release, the `v0` tag and the MCP registry, after stopping two runs at its own test step, before anything was published. *(Live 2026-10-31: tag v0.2.0; was Partial)* |
| 14 | The name reserved on PyPI | Live | `gitdone` is ours on PyPI. 0.2.0 installs from there with uvx, pip and pipx, on the floor Python too. *(Live 2026-10-31: tag v0.2.0; was Not built)* |

### 3. Onboarding (7)

| # | Capability | Status | Note |
|---|---|---|---|
| 15 | `init`: a tracker from words, a checklist or GitHub issues, in a real repository | Live | Includes a repository with no commit yet. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 16 | `add`, `remove`, `mark` and `rows`: no hand-editing of the table's shape | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 17 | `doctor`: everything the tracker needs, on one screen | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 18 | JSON output and a schema for the plan | Live | `check`, `opener`, `week`, `where`, `rows`, `report`, `doctor`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 19 | A README that shows before it explains, with real output a test keeps true | Live | The demo is produced by `docs/demo/record.py`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 20 | A stranger gets a gated STATUS.md in five minutes from the README alone | Partial | Two readers with no context reached a gated commit, in 1 min 42 s and then 41 s, and what they found is fixed; not yet tried by a person. |
| 43 | install-ci: the Action in one command | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |

### 4. Visibility (6)

| # | Capability | Status | Note |
|---|---|---|---|
| 21 | A burn-up chart from git history, with no forecast | Live | Palette validated in both modes; the same history gives the same bytes. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 22 | A badge, kept with the view and held to the table, or as a shields.io endpoint | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 23 | `report`: the evidence row by row | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 24 | `portfolio`: every tracked project on one page | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 25 | A GitHub Action: annotations, one comment, a badge branch | Partial | Runs on GitHub: the gate and the badge branch. The comment on a pull request has not run there yet. |
| 26 | This README shows its own badge and chart | Live | Both are there, and the chart's link resolves now that the repository is public. *(Live 2026-10-31: `cc13a2b`; was Partial)* |

### 5. Evidence and agents (10)

| # | Capability | Status | Note |
|---|---|---|---|
| 27 | A claim stops holding when its commit or pull request is reverted | Live | `git revert`, GitHub's button, a revert of a revert. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 28 | Tags as evidence | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 29 | A pull request past gh's list limit is asked about on its own | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 30 | GitLab merge requests through `glab` | Partial | Tested against a stub of `glab` only. |
| 31 | A skill for every coding agent | Live | `skills/gitdone/SKILL.md`. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 32 | `install-agents`: the rules in `AGENTS.md` | Live | In the first public commit. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 33 | A read-only MCP server with no dependency | Live | A test walks its imports; nothing that writes is reachable. *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 34 | Listed on skills.sh | Not built | The repository is public. A listing needs the owner's word. |
| 41 | A claim in name only is refused: an empty commit, a table-only commit or pull request, a merge that took nothing, a commit not pushed | Live | *(Live 2026-10-31: `cc13a2b`; was Partial)* |
| 42 | A repository being judged cannot run anything here, write outside its project, or reach into git's own folder | Live | *(Live 2026-10-31: `cc13a2b`; was Partial)* |

### 6. Adoption (2)

| # | Capability | Status | Note |
|---|---|---|---|
| 35 | One real project runs on it | Partial | The first adopter has run on the engine since before this repository had a history. Nothing of it is here. |
| 36 | A second real project runs on it, with its gate on | Not built | |

### 7. Launch (4)

| # | Capability | Status | Note |
|---|---|---|---|
| 37 | The repository is public, with a clean history | Live | Public since 2026-10-31, from one clean commit. *(Live 2026-10-31: `cc13a2b`; was Not built)* |
| 38 | Version 1.0 on PyPI, after two weeks of its own gate | Not built | |
| 39 | Listed where people look: awesome lists, a Show HN | Not built | |
| 40 | A write-up with real numbers | Not built | |
