# AGENTS.md: for agents that use gitdone, and agents that work on it

## If you are here to use it in a project

- `gitdone` prints where the project stands: strict and weighted percent, the next workstream, what it needs.
- `status-table.md` is the only place a status changes. `STATUS.md` is generated, so never edit it by hand.
- A row moves to Live only through `gitdone shipped <row> <commit or PR>`, after the work is on the default branch: the remote's, when
  there is one, so push first.
  If it refuses, report the refusal. Do not reword the row to get past it, do not pass `--allow-unverified`, and do not commit with
  `--no-verify`.
- "Done" in a message means the row moved. Say what the gate said, not what you believe.
- `--json` on `check`, `opener`, `week`, `where`, `rows`, `report` and `doctor` is for you. So is `gitdone mcp`, a read-only
  server over stdio.

## If you are here to change it

- Run the tests before anything else and again before you hand off: `python3 -m unittest discover -s tests`. Also run them on
  the floor: `/usr/bin/python3` on a Mac, or `uv run --no-project --python 3.9 python -m unittest discover -s tests`.
- Standard library only. Python 3.9 syntax only. No model calls. The engine starts `git`, `gh` and `glab` and nothing else.
- Exit codes are a contract: 0 clean, 1 a proven contradiction, 2 could not run, 3 `--strict` evidence missing. A crash must
  never read as exit 1.
- The view is a pure function of the plan and the table. Anything that changes at any hour (a QA record, a date beyond the
  header line) stays out of it, or the gate could not compare it byte for byte.
- A rule needs a test that can fail, and every change gets a CHANGELOG entry. A commit in a test touches more than one file, because the code that reads a commit does.
- Before a release, run `GITDONE_ORACLE_SEEDS=400 python3 -m unittest discover -s tests -p test_oracle.py` and read what it lists. Contrived chains of reverts of one commit can be refused.
