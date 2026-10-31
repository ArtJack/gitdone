# The plan file

JSON. Only `status_doc` is required. `init` writes it as `.gitdone.json` at the project root, and an editor gets
completion from [the schema](../schema/plan.schema.json). Paths are relative to the plan file, and `~` is the home directory.

The plan sets the gate's rules, so it is read strictly: a key given twice is refused, and so are an unknown key in a kind and a key nearly named like a rule (`default_brnach`,
`DEFAULT_BRANCH`). Keys of your own are fine, including one like `repos` when a section reads it. The first kind must have `"evidence": "release"`, and a plan has at least two kinds. The plan, the table and the view are real, regular files,
not symbolic links, and three different files. A plan never writes outside its own repository, or its own folder when it is in none, and never into `.git`. A view replaces a view or a file git holds as it stands: any other file already at
that path, or one with uncommitted work in it, is left alone, because nothing could bring it back.

| Key | Meaning |
|---|---|
| `status_doc` | The status table |
| `status_out` | The view; default `STATUS.md`. It must not be the table or the plan |
| `title` | The view's title |
| `badge` | A badge file to keep with the view: written whenever the view is, and held to the table by the gate |
| `footer` | Words for the end of the view. `init` puts a link to the tool here; it is yours to change or delete |
| `release` | Words for the release line in the view's header |
| `release_sha` | Which commit counts as the release, when `release` names several |
| `repo`, `default_branch` | The repository evidence is checked against; the branch defaults to `main`. With `"repo": "."` and no repository yet, evidence starts working the moment one exists. Use an absolute or `~` path if the tracker may run from a linked worktree |
| `branch_aliases` | Short names a status cell may use for branches: `{"A": "some-branch"}` |
| `evidence_pattern` | A regular expression that also counts as naming a release. A named group `ref` is held to the commit rules as a commit id or a tag, never a branch. Any other match is only reported, and `--strict` does not count it |
| `verdict_state` | A [Verdict](https://github.com/ArtJack/verdict) `state.json`, read and never written |
| `deadline` | A date, `2026-12-01`. The view states it, `eta` measures against it, and moving it is said out loud. [Details](timeline.md) |
| `start` | When the work began, for the time bar, if the table is younger than the work; default the table's first commit |
| `requirements` | Markdown files inside the project that hold what was asked for, read by `matrix` and said by `check`. [Details](timeline.md#gitdone-matrix-traceability) |
| `focus` | `paths`: row, range or workstream to file patterns, which ties commits to rows. `upkeep`: file patterns added to the default list. `not_upkeep`: file patterns taken out of it. [Details](timeline.md#gitdone-focus-where-the-work-went) |
| `generated_by`, `regenerate` | The command words in the view's header |
| `noun` | The word after a group's total; default `rows` |
| `scale` | The words of the scale paragraph; default generated from the kinds |
| `rows_total` | The table's row count. Set it, and growing the scope becomes a deliberate edit: `add` refuses until this changes |
| `kinds` | The ordered statuses: `name`, `weight` (0 to 1), and optional `short` (table heading), `phrase` (running text) and `evidence` (`release`, `branch` or `note`). The first kind is the one *strict* counts; the last is what prose domains count as |
| `groups` | `id`, `label`, `domains` (`"1-11,14"` or a list), optional `title` and `total` |
| `workstreams` | `id`, `name`, `rows`, `state`, `needs` |
| `order` | Workstream ids; default their order in the list. `check` notes a workstream left out of it |
| `sections` | What the view shows after its header, in order (below) |
| `products` | Rows of a measure table: static (`name`, `state`, `measure`), or computed from a `group` or `rows` (`"11-25"`), with optional `state` and `measures` (`["strict", "weighted"]`) |

Section types: `group` (`group`, `style`: `full` or `summary`), `workstreams` (`title`), `table` (`title`, `from`: any list in
the plan, `columns`: `head` and `key`), `list` (`title`, `from`, `format`), `products` (`title`, `heads`).

[`examples/bramble/plan.json`](../examples/bramble/plan.json) uses nearly all of it.

## Finding the plan

A command finds its plan from its directory, nearest first, and the search stops below the home directory.

1. **`.gitdone.json`** at the project root. It is either the plan itself, or a pointer: `{"plan": "path/to/plan.json"}`.
   A pointer suits a plan kept outside the repository, or several trackers in one.
2. **`--plan`** on any command overrides the search.

A monorepo can hold one tracker per package: the nearest file wins.

One extension, off unless asked for: with `GITDONE_PACKS` naming a folder of per-project notes, a line
`gitdone: path/to/plan.json` in `<folder>/<project folder's name>.md` also counts, after any `.gitdone.json`.
