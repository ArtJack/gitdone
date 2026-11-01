# Security

## What this can do on your machine

Everything below is measured from the code, and `tests/` pins it.

| | |
|---|---|
| Processes it starts | `git`, always on a named repository. `gh` or `glab`, only for a row that names a pull request or merge request, never with `--offline`. `gh` for `init --from-issues` and for `ci`'s comment. Nothing else |
| Files it writes | The status table, the view and the badge (`shipped`, `mark`, `add`, `render --write`, `counts --write`), the files `init` creates, the local git hooks (`install-hook`), one workflow (`install-ci`), a section of `AGENTS.md` and `CLAUDE.md` (`install-agents`), one project-level skill (`install-skill`), and what you name with `--out`, `--svg` or `--endpoint`. Every other command writes nothing |
| Network | None of its own. `gh` and `glab` talk to their forge with your login. `ci --publish` pushes to the branch you name, with the job's token |
| Telemetry | None. Nothing routes through the author |
| Model calls | None |
| Claude Code plugin | One SessionStart hook that prints a line and can never stop a session, a command skill that only a person can start, a method skill the model may read, no agent |
| MCP server | Read-only tools over stdio, only if you add it. A test walks its imports to prove nothing that writes is reachable |
| Git hooks | Live in `.git/hooks`, never committed. `install-hook` refuses to replace a hook it did not write, and refuses a `core.hooksPath` inside the work tree or shared with other repositories |

## What a repository you did not write can do

A plan and a table can arrive with a clone or a pull request, so they are treated as untrusted:

- **The engine never comes from the repository being judged.** The plugin's shim, the git hook and the Action run Python with `-I`, which keeps the
  working folder off the import path, so a planted `gitdone/` or `json.py` is not what runs. `pipx` and `uvx` installs are immune anyway.
- **A plan cannot make git run a command.** Every call sets `safe.bareRepository=explicit` (git 2.38 and up), `protocol.ext.allow=never` and
  `core.fsmonitor=false`, which outrank a config file committed inside a project.
- **A plan cannot make a command overwrite a file outside its project,** directly or through a symbolic link, **or inside git's own folder,** where a file it wrote would run as a
  hook or break the repository. The plan, the table and the view must be real, regular files, so a gate never reads something a commit does not hold, and a device or a
  pipe cannot hang it. A view only replaces a view or a file git holds as it stands, so a plan cannot wipe an ignored `.env` or uncommitted work.
- **A plan's requirement files are read only inside the project.** A plan can come from a clone, and those words can reach a pull request's comment, so a file outside it, or behind a symbolic link, is not read.
  The comment names where a requirement is, not what it says. A commit's subject never goes in it.
- **The plan is read strictly where it sets the gate's rules:** a key given twice and an unknown key in a kind are refused, and the hook and the Action say out loud when
  a change touches the rules.
- **Row text is never executed,** and a git reference taken from a row must match a strict pattern before it reaches `git`. `git replace` cannot rewrite what a
  commit's history says, and a tag named like a commit id is not that commit.
- **A stranger's words cannot talk to your terminal or to a workflow.** An escape sequence or a carriage return from a table or a plan is shown, not obeyed, in what the gate prints, in its
  errors, and in anything else at a terminal. A pipe gets the bytes the table holds. Only `gitdone ci` speaks to a workflow's runner: a plan's words that reach the start of a line anywhere else cannot. `install-ci` refuses a branch name that could shape the workflow.
- **A few bytes cannot ask for much.** Ranges in a plan and rows counted with no table have limits across the whole file, and the regular expressions the engine reads a stranger's words with
  run in linear time. A plan's file patterns, a commit's message and list of files, and the text of a table's old versions, however little they weigh in the pack, have limits too, and `focus` stops after ten seconds and says it looked at part of the history.

What is left is yours to know: a plan's `evidence_pattern` is a regular expression, so a hostile one can be slow, and `verdict_state` names a file the
engine opens to read as JSON. The local gate trusts `.git`: someone who can edit it can make git say other things, which a clone in CI is out of reach of. Running `check`
on a stranger's pull request reads their words and starts your `git`, and nothing more.

The git hook's last fallback, when no engine is found and the commit touches the tracker, is `uvx gitdone`, which fetches the latest release.

## Reporting a vulnerability

Report privately first:

- **Email:** hello@artjeck.com with `[gitdone security]` in the subject.
- Or open a [GitHub security advisory](https://github.com/ArtJack/gitdone/security/advisories/new).

Include the command or file that demonstrates it. Expect an acknowledgement within a few days and a fix in a tagged release.
Credit goes in the CHANGELOG unless you prefer otherwise.
