---
name: status
description: "This project's status, held to git: print where it stands, move one row on evidence, list what is left, or print the weekly delta. Everything runs in the gitdone engine."
argument-hint: "[shipped <row> <evidence> | mark <row> <kind> [note] | rows | next | eta | focus | week [since] | matrix | check | doctor]"
disable-model-invocation: true
allowed-tools: Bash(gitdone:*)
---

Run the one engine command that `$ARGUMENTS` asks for, through the Bash tool, and show its output verbatim. Add nothing
else: no summary, no reading of code, no other file opened.

The command is `gitdone`, which this plugin puts on the Bash tool's PATH. If the shell cannot find it, use
`sh "${CLAUDE_PLUGIN_ROOT}/bin/gitdone"` in its place.

| `$ARGUMENTS` | Command |
|---|---|
| empty | `gitdone opener` |
| `shipped <row> <evidence...>` | `gitdone shipped <row> '<evidence...>'` (the evidence in single quotes, exactly as given) |
| `mark <row> <kind> <words...>` | `gitdone mark <row> '<kind>' '<words...>'` (each in single quotes, exactly as given) |
| `rows` | `gitdone rows --open` |
| `week` or `week <since>` | `gitdone week` or `gitdone week '<since>'` |
| `next` | `gitdone next` |
| `eta` | `gitdone eta` |
| `focus` | `gitdone focus` |
| `matrix` | `gitdone matrix --offline` |
| `check` | `gitdone check` |
| `doctor` | `gitdone doctor` |
| anything else | run nothing; say the forms above |

Rules:

- A status is a person's claim held to its evidence. Never pick a row, a status or a piece of evidence yourself, and
  never look in the code to decide one.
- If `shipped` or `mark` refuses, show the refusal and stop. Do not retry with other evidence unless the person gives it.
- `shipped` and `mark` edit the status table and regenerate the view. They do not commit; say nothing about committing unless asked.
