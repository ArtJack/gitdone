# Coding agents

An agent is the fastest way to get a false "done", and the easiest to hold to evidence: it reads what it is told, and it stops when
a command refuses. Four ways in, from least to most.

## Any agent: AGENTS.md

```bash
gitdone install-agents
```

This adds a short section to `AGENTS.md`, and to `CLAUDE.md` if the project has one: run `gitdone` at the start of a session, work on what `gitdone next`
lists, name the row in the commit message, say so before doing anything else, move a row only with `shipped`, report a refusal instead of working around it. It keeps what is already in
those files, and running it again changes nothing.

Agents drift because nothing in front of them says where the line is. Here it is the first thing a session prints, the commit that leaves it is told so, and the [numbers](timeline.md) show up in the
next session. The files and the gate hold the line. No agent has to.

`--json` on every reading command is there for agents, and [`AGENTS.md`](../AGENTS.md) in this repository is a model.

## Cursor, Codex, OpenCode and others: the skill

```bash
npx skills add ArtJack/gitdone
```

The skill is [`skills/gitdone/SKILL.md`](../skills/gitdone/SKILL.md): when to read the status, how a row moves, and what
to do when the gate says no.

## Claude Code: the plugin

```
/plugin marketplace add ArtJack/gitdone
/plugin install gitdone@gitdone
```

The plugin is thin: a shim over the engine it bundles, the two skills, and one SessionStart hook.

| Typed | What it does |
|---|---|
| `/gitdone:status` | Prints where the project stands |
| `/gitdone:status shipped <row> <evidence>` | Moves one row to Live through the engine |
| `/gitdone:status mark <row> <kind> <words>` | Moves one row short of Live |
| `/gitdone:status rows` | Lists what is left |
| `/gitdone:status next` | What to work on now |
| `/gitdone:status eta` or `focus` or `matrix` | The date, where the commits went, the traceability matrix |
| `/gitdone:status week [since]` | Prints the delta line |
| `/gitdone:status check` or `doctor` | The gate, or the health check |

The SessionStart hook prints the opener in a project with a tracker, and says nothing anywhere else. It never stops a session. The
`status` skill can only be started by a person; the `gitdone` skill is the method, which Claude may read when you ask how far
along a project is.


## Any MCP client: the server

For an agent that would rather call a tool than run a command:

```bash
claude mcp add gitdone -- uvx gitdone mcp
```

Or, in a client's JSON config:

```json
{"mcpServers": {"gitdone": {"command": "uvx", "args": ["gitdone", "mcp"]}}}
```

It is read-only: `status`, `rows`, `evidence`, `check`, `week`, `portfolio`. Each takes an optional `project`. It has no dependency,
and a test walks its imports to prove that nothing able to write a file is reachable from it.

## What to tell an agent

"Done means the row moved." Then let the gate be the one who says so. An agent that cannot get `shipped` to accept its commit has
told you something true about the work, and you have learned it before the review instead of after the release.
