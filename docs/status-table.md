# The status table

The only place a row's status changes. `init` writes it, `shipped`, `mark` and `add` keep it true, and it stays plain markdown
you can edit by hand and read without the tool.

```markdown
### 3. Domain name (4)

| # | Name | Status | Note |
|---|---|---|---|
| 12 | A row | Live | What exists, and the release that shipped it: `1a2b3c4`. |
```

- **A domain header** is `### N. Name (count)`, and its number appears once. Any other heading ends the domain.
- **A table** has `Status` as its third column, if it has a heading row at all.
- **A status cell** starts with a kind's name and may say more after it: `Built, not live (some-branch)`. `Live?` is a doubt, not a status.
- **What no reader can see is not the scope:** rows in a code fence, an HTML comment or an indented block are not read, and a fence or a comment that never closes is a
  failure, because it hides the rest of the file. A comment opened in the middle of a line depends on the renderer, so what it would hide is not read, and it is said.
- **Nothing drops out of the count in silence.** Inside a domain, every table line is a row or gets a warning, which `--strict` fails on. As in Markdown, under an open table any line
  with a pipe is a table line, leading pipe or not. A Total row or a row that groups others is a table line too, so it goes outside the domain's table. A heading shaped like the next
  domain's and not read as one, such as `### 2. Later`, whose count is lost, gets the same warning.
- **A table of your own goes under a heading of its own,** such as `## What the statuses mean`. A `#` heading with words in it ends the domain, and from there on the tables are yours,
  unless a line has a number first and a status third, which a reader would take for a row. An underlined heading ends nothing here: a line of dashes reads as a rule.
- **A row number** is the row's identity, and numbers need not be contiguous. `remove` takes a row out; `week` says so.
- **A note** is yours. `shipped` and `mark` add one line in italics saying what moved it, and replace the line the last move added, since git keeps
  the history. Your words stay.
- **A domain with a count and no table** is prose: each row counts as the plan's last kind, numbered on from the row before. A
  table none of whose rows can be read stops the engine rather than counting as prose.
- **A counts table** (a line starting `| # | Domain | All |`) is optional. If the file holds one, `check` holds it to the rows,
  and `shipped` and `counts --write` keep it true.

Anything else in the file is yours: an introduction, definitions of your statuses, notes between domains.

## Kinds

The kinds are the plan's. The default four:

| Kind | Weight | The gate asks for |
|---|---|---|
| Live | 1.0 | A release: a commit on the default branch, a merged pull request or merge request, or a tag |
| Built, not live | 0.8 | A branch that exists |
| Partial | 0.4 | A note saying what exists |
| Not built | 0 | Nothing |

The first kind is what *strict* counts. The last is what a prose domain's rows count as. See [the plan file](plan-file.md) to
change them.
