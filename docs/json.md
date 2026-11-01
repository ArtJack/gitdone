# JSON output

`--json` before or after the command, on `check`, `opener`, `next`, `eta`, `focus`, `matrix`, `week`, `where`, `rows`, `report`, `doctor`, `chart` and `portfolio`, gives the same findings as data,
from the same code as the words. Exit codes do not change. An engine error is JSON too: `{"result": "cannot run", "exit_code": 2, "error": "..."}`.

## `check --json`

```json
{
  "result": "warnings",
  "exit_code": 0,
  "strict": false,
  "view": "fresh",
  "counts": "Launch 11, Later 5, all 16",
  "evidence": {"verified": 3, "unverified": 2, "missing": 1, "contradicted": 0},
  "verdict": null,
  "failures": [],
  "warnings": [{"text": "row 9 names no commit, pull request or tag; run `gitdone shipped 9 <commit>`", "rows": [9]}],
  "notes": [{"text": "row 2: PR #12: offline", "rows": [2]}]
}
```

`result` is `pass`, `warnings`, `fail` or `cannot run`. `view` is `fresh`, `stale`, `missing` or `not compared`. `rows` lists the row
numbers a finding is about, and is empty for a finding about the whole table. A finding may also carry `next`, what to do about it.

## `opener --json`

```json
{
  "line": "Launch: strict 36% (4/11), weighted 63% · next: S1 (Reading lists and renewals)",
  "groups": [{"label": "Launch", "rows": 11, "strict_rows": 4, "strict": 0.3636, "weighted": 0.6273}],
  "next": {"id": "S1", "name": "Reading lists and renewals", "state": "built and reviewed", "needs": ""},
  "all_workstreams_done": false,
  "release": null,
  "warnings": []
}
```

## `week --json`

```json
{
  "since": "2026-03-01",
  "base": "1a2b3c4",
  "base_date": "2026-02-27",
  "older_commit_found": true,
  "groups": [{"label": "All", "rows": 16, "strict_rows_then": 3, "strict_rows_now": 4, "strict_then": 0.1875, "strict_now": 0.25, "weighted_then": 0.39, "weighted_now": 0.456}],
  "moved": [{"row": 9, "from": "Partial", "to": "Live"}],
  "workstreams_moved": ["S3"],
  "workstreams_not_moved": ["S1", "S2"],
  "new_rows": [],
  "removed": [],
  "uncommitted_changes": false
}
```

## `eta --json`

```json
{
  "state": "dated",
  "as_of": "2026-03-03",
  "rows": 16,
  "left": 8.7,
  "strict": 0.25,
  "weighted": 0.456,
  "window_days": 28,
  "moving_days": 6,
  "pace_per_day": 0.211,
  "likely": "2026-04-14",
  "sure": "2026-04-29",
  "too_far": false,
  "largest_day_share": 0.31,
  "only_backwards": false,
  "last_change": null,
  "plan_problems": [],
  "all_groups": false,
  "newest_only": false,
  "set_aside": 0,
  "scope": {"added": 5, "removed": 0, "keeps_growing": false, "per_day": 0.179, "never_catches_up": false},
  "live": {"kind": "Live", "left": 12, "moving_days": 3, "pace_per_day": 0.107, "likely": "2026-06-23", "sure": "2026-07-31", "too_far": false},
  "deadline": {"date": "2026-04-15", "start": "2026-01-12", "days_left": 43, "time_used": 0.54, "needs_per_day": 0.202, "needs_per_day_live": 0.279, "late_by": -1, "late_by_if_sure": 14, "late_by_live": 69},
  "workstreams": [{"id": "S1", "name": "Reading lists and renewals", "left": 0.4, "dates": {"likely": "2026-03-05", "sure": "2026-03-06", "too_far": false}}]
}
```

`state` is `dated`, `too_little`, `stalled`, `shallow`, `done` or `no_rows`. `likely` and `sure` are null unless it is `dated`, and with `too_far` too. `sure` is the 85% date, and null if that is past ten years. A negative `late_by` is early. `live` is the same line through rows reaching the strict kind alone. `all_groups` says the plan has groups and these numbers cover all of them. `newest_only` says there was too much of the table's history to read, and the window is what could be. `set_aside` is how many rows moved on the table's first day or on commits from before it, which is not pace.

## `focus --json`

`days`, `since`, `revisions`, `folder` (the plan's folder, in a repository's subfolder), `commits`, `on_plan`, `unclear`, `upkeep`, `off_plan`, `tracker_only`, `shallow`, `newest_only` (only the newest part of the history was looked at, and the rest is not in these numbers), `plan_problems`, `lines` (the same four, in changed lines), `rows` (each `row`, `commits`), `areas` (each `area`, `lines`), `next`, and
`list`: every commit with `commit`, `date`, `subject`, `class` (`on plan`, `unclear`, `upkeep`, `off plan`, `tracker`), `rows`, `because`, `lines`, `area`.

## The rest

- **`next --json`:** `workstream` (or null), `rows` (each `row`, `name`, `kind`, `note`), `open_rows`.
- **`matrix --json`:** `requirements` (each `id`, `words`, `where`, `rows`, `looks_like`), `rows` (what `report --json` gives, with `named_by` and `tests`), `problems`, `not_read` (lines of a spec not read as requirements, each `id`, `words`, `where`, `why`), and `summary`.
- **`where --json`:** `plan`, `table`, `view`, `repo`, `default_branch`, `verdict`.
- **`rows --json`:** a list of `row`, `name`, `kind`, `status`, `note`, `domain`, `domain_name`.
- **`report --json`:** every row with `claims`, each with `kind`, `value`, `state`, `detail` and, when git or `gh` found it, `found`.
- **`doctor --json`:** `exit_code` and `items`, each with `state` (`ok`, `warn`, `fail`), `name`, `detail`.
- **`chart --json`:** a list of `date`, `scope`, `strict`, `weighted`, `left`, in rows. `chart --csv` has the first four. With `--scale`: a list of `label`, `rows`, `strict_rows`, `strict`, `weighted`, `part`, where `part` marks a domain within its group. With `--burndown`: `points` and `forecast`, which is what `eta --json` gives, and as CSV `date`, `scope`, `left_all_work`, `left_strict`.
- **`portfolio --json`:** a list of projects with `rows`, `strict_rows`, `strict`, `weighted`, `likely`, `likely_words`, `all_groups`, `next`, `gate`, or `error`.
- **`badge`:** prints the JSON a [shields.io endpoint](https://shields.io/badges/endpoint-badge) reads.
