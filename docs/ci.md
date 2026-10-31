# CI and other gates

## The GitHub Action

The hook is a courtesy, and this is the gate: no flag skips it. `gitdone install-ci`, or `init --ci`, writes this to `.github/workflows/status.yml`:

```yaml
name: status

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read
  pull-requests: write  # for the comment

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0  # evidence needs the whole history
      - uses: ArtJack/gitdone@v0
```

A tracker in a subfolder gets `working-directory` as well. A plan whose `repo` is another repository cannot use the Action, which only sees what it checks out.

On a pull request that touches the plan, the table or the view, it:

- runs the gate, strict by default, and fails the job on what the gate fails on;
- puts each finding on its row's line in the pull request's diff;
- keeps one comment up to date with the numbers, what moved against the base, where its commits went, what it does to the scope and the date, and what the gate found;
- says out loud when the change touches the gate's own rules: the kinds, the default branch, the repository, the evidence pattern;
- writes the same to the job summary.

A pull request that touches none of those is left alone, so a tracker's old warnings never block unrelated work, with where its commits went, and any requirement no row names, in the run's log and summary. Set
`always: true` to judge every pull request.

On a push, with `publish-branch` set (and `contents: write`), it commits `badge.svg`, `badge.json`, `burnup.svg`, `burnup.csv` and `burndown.svg` to that
branch without touching the work tree, and your README can show them:

```markdown
![status](https://raw.githubusercontent.com/OWNER/REPO/status-badges/badge.svg)
![burn-up](https://raw.githubusercontent.com/OWNER/REPO/status-badges/burnup.svg)
```

| Input | Default | Meaning |
|---|---|---|
| `plan` | found | The plan file |
| `strict` | `true` | Fail on missing evidence too |
| `comment` | `true` | Keep one comment on the pull request |
| `always` | `false` | Judge a pull request that does not touch the tracker |
| `publish-branch` | none | The branch for the badge and the chart |
| `working-directory` | `.` | Where to run |

Outputs: `result`, `exit-code`, `strict`, `weighted`.

A token that cannot write, as on a pull request from a fork, gets a warning, and the gate's exit code still decides. The job needs
no install and no key: it runs the engine from the Action's own checkout with the runner's Python.

## Any other CI

The engine's exit codes are the interface. With Python 3.9 or newer and the whole history checked out:

```bash
uvx gitdone check --strict
```

On GitLab, `check` verifies `MR !12` through `glab` when it is installed and logged in.

## The pre-commit framework

```yaml
repos:
  - repo: https://github.com/ArtJack/gitdone
    rev: v0.2.0
    hooks:
      - id: gitdone
```

It stays out of a commit that does not touch the tracker, so it costs nothing on most commits.

## Husky, lefthook and others

Add one line to the hook you already have:

```bash
gitdone check --if-staged --strict
```

`install-hook` refuses to replace a hook it did not write, and its message gives you the same line.
