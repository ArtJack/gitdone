# gitdone: where each capability stands

This repository holds itself to its own gate. This table is the only place a row's status changes, and `STATUS.md` is generated
from it.

### 1. The engine (6)

| # | Capability | Status | Note |
|---|---|---|---|
| 1 | The view: a pure function of a plan and a table | Partial | `render`, `counts`. |
| 2 | The gate: view true, counts sum, evidence per kind, four exit codes | Partial | `check`, `--strict`, `--offline`. |
| 3 | A row moves on evidence, and refuses what git disproves | Partial | `shipped`. |
| 4 | What moved, from the table's git history | Partial | `week`. |
| 5 | A local gate that judges what the commit will contain | Partial | `install-hook`, `check --if-staged`, worktrees and merges. |
| 6 | A session starts with where the project stands | Partial | The SessionStart hook. |

### 2. Installs anywhere (8)

| # | Capability | Status | Note |
|---|---|---|---|
| 7 | `uvx` and `pipx` install it with zero dependencies, on Python 3.9 and up | Partial | Wheel built and run on 3.9 and 3.14 from an empty folder. |
| 8 | The Claude Code plugin bundles the engine and needs no environment | Partial | Validated and installed into a clean Claude config, and run under `env -i`. |
| 9 | The hook survives a plugin update, a moved checkout and a replaced Python | Partial | Falls back from the installing engine to PATH, the plugin, then `uvx`. |
| 10 | Plan discovery names no private folder | Partial | The plan may be the pointer file itself. |
| 11 | MIT license and the policy files | Partial | LICENSE, CONTRIBUTING, SECURITY, AGENTS, llms.txt, issue templates. |
| 12 | CI on three operating systems, on the floor and the newest Python | Partial | Written and lint-clean with actionlint; it has never run, because there is no remote. |
| 13 | A release workflow by Trusted Publishing that refuses a mismatched tag | Partial | Written and lint-clean; never run. PyPI needs the trusted publisher set up by its owner. |
| 14 | The name reserved on PyPI | Not built | `gitdone` was free on 2026-10-31; reserving it leaves the machine, so it waits for the first push. |

### 3. Onboarding (7)

| # | Capability | Status | Note |
|---|---|---|---|
| 15 | `init`: a tracker from words, a checklist or GitHub issues, in a real repository | Partial | Includes a repository with no commit yet. |
| 16 | `add`, `remove`, `mark` and `rows`: no hand-editing of the table's shape | Partial | In the first public commit. |
| 17 | `doctor`: everything the tracker needs, on one screen | Partial | In the first public commit. |
| 18 | JSON output and a schema for the plan | Partial | `check`, `opener`, `week`, `where`, `rows`, `report`, `doctor`. |
| 19 | A README that shows before it explains, with real output a test keeps true | Partial | The demo is produced by `docs/demo/record.py`. |
| 20 | A stranger gets a gated STATUS.md in five minutes from the README alone | Partial | Two readers with no context reached a gated commit, in 1 min 42 s and then 41 s, and what they found is fixed; not yet tried by a person. |
| 43 | install-ci: the Action in one command | Partial | In the first public commit. |

### 4. Visibility (6)

| # | Capability | Status | Note |
|---|---|---|---|
| 21 | A burn-up chart from git history, with no forecast | Partial | Palette validated in both modes; the same history gives the same bytes. |
| 22 | A badge, kept with the view and held to the table, or as a shields.io endpoint | Partial | In the first public commit. |
| 23 | `report`: the evidence row by row | Partial | In the first public commit. |
| 24 | `portfolio`: every tracked project on one page | Partial | In the first public commit. |
| 25 | A GitHub Action: annotations, one comment, a badge branch | Partial | The script and the logic are tested against stubs and a local remote; never run on GitHub. |
| 26 | This README shows its own badge and chart | Partial | The badge is there, written with the view; the chart comes from the Action, which needs a first push. |

### 5. Evidence and agents (10)

| # | Capability | Status | Note |
|---|---|---|---|
| 27 | A claim stops holding when its commit or pull request is reverted | Partial | `git revert`, GitHub's button, a revert of a revert. |
| 28 | Tags as evidence | Partial | In the first public commit. |
| 29 | A pull request past gh's list limit is asked about on its own | Partial | In the first public commit. |
| 30 | GitLab merge requests through `glab` | Partial | Tested against a stub of `glab` only. |
| 31 | A skill for every coding agent | Partial | `skills/gitdone/SKILL.md`. |
| 32 | `install-agents`: the rules in `AGENTS.md` | Partial | In the first public commit. |
| 33 | A read-only MCP server with no dependency | Partial | A test walks its imports; nothing that writes is reachable. |
| 34 | Listed on skills.sh | Not built | Needs the public repository. |
| 41 | A claim in name only is refused: an empty commit, a table-only commit or pull request, a merge that took nothing, a commit not pushed | Partial | *(Built, not live 2026-10-31: branch `public-release`, Attacked by two independent readers; each finding has a test.; was Not built)* |
| 42 | A repository being judged cannot run anything here, write outside its project, or reach into git's own folder | Partial | *(Built, not live 2026-10-31: branch `public-release`, Attacked by two independent readers; each finding has a test.; was Not built)* |

### 6. Adoption (2)

| # | Capability | Status | Note |
|---|---|---|---|
| 35 | One real project runs on it | Partial | The first adopter has run on the engine since before this repository had a history. Nothing of it is here. |
| 36 | A second real project runs on it, with its gate on | Not built | |

### 7. Launch (4)

| # | Capability | Status | Note |
|---|---|---|---|
| 37 | The repository is public, with a clean history | Not built | |
| 38 | Version 1.0 on PyPI, after two weeks of its own gate | Not built | |
| 39 | Listed where people look: awesome lists, a Show HN | Not built | |
| 40 | A write-up with real numbers | Not built | |

### 8. Time and focus (5)

| # | Capability | Status | Note |
|---|---|---|---|
| 44 | `eta`: a date with its range, from the table's own history, that moves with the scope and answers to a deadline | Partial | On a branch until the first release is out. |
| 45 | `focus` and `next`: where the commits went, what comes next, and a hook that says when a commit was off plan | Partial | On a branch until the first release is out. |
| 46 | `matrix`: requirement to row to evidence to tests, with the two gaps said on every run | Partial | On a branch until the first release is out. |
| 47 | The burn-down: what is left, up when the scope grew, with the line, the range and the deadline | Partial | On a branch until the first release is out. |
| 48 | The agent rules, the skill and the MCP tools say all of this | Partial | On a branch until the first release is out. |
