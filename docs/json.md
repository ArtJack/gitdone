# JSON output

`--json` before or after the command, on `check`, `opener`, `week`, `where`, `rows`, `report`, `doctor`, `chart` and `portfolio`, gives the same findings as data,
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

## The rest

- **`where --json`:** `plan`, `table`, `view`, `repo`, `default_branch`, `verdict`.
- **`rows --json`:** a list of `row`, `name`, `kind`, `status`, `note`, `domain`, `domain_name`.
- **`report --json`:** every row with `claims`, each with `kind`, `value`, `state`, `detail` and, when git or `gh` found it, `found`.
- **`doctor --json`:** `exit_code` and `items`, each with `state` (`ok`, `warn`, `fail`), `name`, `detail`.
- **`chart --json`:** a list of `date`, `scope`, `strict`, `weighted`, in rows. `chart --csv` is the same as CSV.
- **`portfolio --json`:** a list of projects with `rows`, `strict_rows`, `strict`, `weighted`, `next`, `gate`, or `error`.
- **`badge`:** prints the JSON a [shields.io endpoint](https://shields.io/badges/endpoint-badge) reads.
