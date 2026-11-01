# Contributing

The bar for a change is the bar the tool holds everyone else to: say what you measured, and leave a tree a stranger can
reproduce.

## The short version

- **Run the suite before and after.** `python3 -m unittest discover -s tests` needs nothing installed and takes under a
  minute. It builds real git repositories, and `gh` is a stub.
- **A rule needs a test that can fail.** Put the defect back and watch the test go red before you trust it.
- **Python 3.9 is the floor, and the standard library is the whole dependency list.** A stock Mac has 3.9, and it is the
  machine this is installed on most. CI runs the floor and the newest.
- **Lint is narrow on purpose.** `uvx ruff check .`: correctness rules only. The comment style is a house idiom, so
  `ruff format` is not run.
- **Versions move together.** `gitdone/__init__.py`, `.claude-plugin/plugin.json` and `server.json` carry one version.
  `tests/test_versions.py` refuses a commit where they disagree, and `release.yml` refuses a tag that disagrees with them.
- **Every change gets a CHANGELOG entry:** what was wrong, what changed, what is deliberately not in it.
- **The repository tracks itself.** `STATUS.md` is generated from `status-table.md` and `.gitdone.json`, under the
  same gate as everyone else's. A row moves with `gitdone shipped`, after the commit is on `main`.

## What is welcome

- A report of a claim the gate accepted and should not have, or refused and should not have. Those are the bugs that matter
  most here.
- A real project's numbers: what the first `check` said, and what the method changed.
- Support for another forge's merge requests, written the way `gitio.py` asks `gh`: one small function, one stub in the
  tests.

## What is not

- Reading code to decide a status. A status is a person's claim held to its evidence, and that line is structural.
- A date read off a percent. No percentage is a date: `eta` is a line through the past, and it says so.
- A runtime dependency.
- A check that cannot fail.

## Where things are

| Path | What |
|---|---|
| `gitdone/` | The engine, one module per job. `cli.py` is the commands, `gate.py` the rules, `evidence.py` what a row claims |
| `bin/`, `hooks/`, `skills/`, `.claude-plugin/` | The Claude Code plugin: a shim, one hook, the skills |
| `examples/bramble/` | A fictional library kiosk; tests keep its view true |
| `docs/` | The reference, one file per contract |
| `tests/` | The suite |

Questions go in an issue. There is no chat.
