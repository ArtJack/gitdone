"""What the engine installs into a project: the local gate, and a project-level skill."""
import os
import pathlib
import shlex
import sys

from . import discover, gitio
from .plan import PlanError
from .shipped import write_atomically

MARK = "gitdone gate"
SKILL_MARK = "gitdone project skill"
SKILL_NAME = "gitdone"
HERE = pathlib.Path(__file__).resolve().parent
HOME = HERE.parent  # on sys.path, this folder is all a Python needs to run the engine
HOOKS = ("pre-commit", "pre-merge-commit")
CHECK = "check --plan \"$plan\" --if-staged"
CHECK_FOUND = "check --if-staged"  # the plans come from the files the commit changes
STRICT = " --strict"
# -I keeps the repository off the import path: what is being judged must not be able to supply the engine, or break it.
LAUNCH = "import sys; sys.path.insert(0, sys.argv.pop(1)); from gitdone.cli import main; sys.exit(main())"

TEMPLATE = """#!/bin/sh
# {mark} (local, never committed). Written by `gitdone install-hook`.
# It judges what a commit will contain when the commit touches the plan, the status table or the view, and stays out
# of every other commit. It runs the engine that installed it, else the one on PATH, else the Claude Code plugin's.
top=$(git rev-parse --show-toplevel)
{plan_line}
home={home}
python={python}
[ -x "$python" ] || python=$(command -v python3 || command -v python)
if [ -f "$home/gitdone/__main__.py" ] && [ -n "$python" ]; then
  exec "$python" -I -c '{launch}' "$home" {check}
fi
if command -v gitdone >/dev/null 2>&1; then
  exec gitdone {check}
fi
plugin=$(ls -td "$HOME"/.claude/plugins/cache/*/gitdone/*/bin/gitdone 2>/dev/null | head -n 1)
if [ -n "$plugin" ]; then
  exec sh "$plugin" {check}
fi
if git -c core.quotePath=false diff --cached --name-only | grep -qxF{tracked}; then
  if command -v uvx >/dev/null 2>&1; then
    exec uvx gitdone {check}
  fi
  echo "gitdone: engine not found, and this commit touches the tracker, so it cannot be judged. Install it (pipx install gitdone) and run install-hook again, or commit with --no-verify." >&2
  exit 2
fi
exit 0
"""


def _inside(path, root):
    """A path below the repository's root, the way git writes it; or None."""
    real = os.path.realpath(path)
    return os.path.relpath(real, root).replace(os.sep, "/") if real.startswith(root + os.sep) else None


def _found_from_commit(plan, root):
    """Whether a commit's own files lead back to this plan, so that one hook serves every tracker in the repository."""
    directory = discover.pointer_directory(plan.dir)
    if directory is None or not _inside(directory / discover.POINTER, root):
        return False
    try:
        if discover.find_plan(directory) != plan.path:
            return False
    except PlanError:
        return False
    return all(os.path.realpath(p).startswith(os.path.realpath(directory) + os.sep) for p in plan.tracked)


def _hook_text(plan, root, strict=True):
    tracked = [_inside(p, root) for p in plan.tracked]
    tracked_words = "".join(f" -e {shlex.quote(rel)}" for rel in tracked if rel)
    if _found_from_commit(plan, root):
        plan_line = "# The plans come from the files a commit changes, so this one hook serves every tracker in the repository."
        check = CHECK_FOUND
    else:
        # A plan inside the repository is named from the top, so a linked worktree's hook judges that worktree's plan.
        plan_rel = _inside(plan.path, root)
        plan_line = "plan=" + ('"$top"/' + shlex.quote(plan_rel) if plan_rel else shlex.quote(str(plan.path)))
        check = CHECK
    return TEMPLATE.format(mark=MARK, home=shlex.quote(str(HOME)), python=shlex.quote(sys.executable), plan_line=plan_line,
                           tracked=tracked_words, check=check + (STRICT if strict else ""), launch=LAUNCH)


def is_ours(text):
    """A hook this engine wrote: the mark on its second line. Someone's hook that only mentions the words is theirs."""
    lines = text.split("\n")
    return len(lines) > 1 and lines[1].startswith(f"# {MARK} (local")


def install(plan, strict=True):
    """Returns the hooks' paths. Refuses to replace a hook this engine did not write, or to write one into the work tree.

    Strict is the default: a commit that would add a Live row with nothing behind it is refused, not warned about.
    """
    top = gitio.git(plan.doc.parent, "rev-parse", "--show-toplevel")
    if top.code:
        raise PlanError(f"{plan.doc.name} is not in a git repository, so there is nowhere to put a hook")
    root = os.path.realpath(top.out.strip())
    where = gitio.git(root, "rev-parse", "--git-path", "hooks").out.strip()
    hooks = pathlib.Path(where) if os.path.isabs(where) else pathlib.Path(root) / where
    inside = _inside(hooks, root)
    if inside and pathlib.PurePath(inside).parts[0] != ".git":
        raise PlanError(f"core.hooksPath points inside the work tree ({inside}), so a hook here could be committed; "
                        f"add the check by hand: gitdone check --plan {plan.path} --if-staged --strict")
    common = gitio.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").out.strip()
    if common and os.path.isdir(common) and not os.path.realpath(hooks).startswith(os.path.realpath(common) + os.sep):
        raise PlanError(f"core.hooksPath points at {hooks}, which other repositories share; add the check there by hand: "
                        f"gitdone check --plan {plan.path} --if-staged --strict")
    paths = [hooks / name for name in HOOKS]
    for path in paths:
        if path.exists() and not is_ours(path.read_text(encoding="utf-8", errors="replace")):
            raise PlanError(f"{path} exists and is not this gate; add the check to it by hand: "
                            f"gitdone check --plan {plan.path} --if-staged --strict")
    hooks.mkdir(parents=True, exist_ok=True)
    text = _hook_text(plan, root, strict=strict)
    for path in paths:
        write_atomically(path, text)
        path.chmod(0o755)
    return paths


def _skill_source():
    """The plugin's skill: beside the package in a checkout or the plugin, inside it in a wheel."""
    for candidate in (HERE / "_skill" / "SKILL.md", HOME / "skills" / "status" / "SKILL.md"):
        if candidate.is_file():
            return candidate
    raise PlanError("the skill's text is not with this engine")


def install_skill(directory):
    """Write <directory>/.claude/skills/<name>/SKILL.md from the plugin's skill, so the words have one source.

    A plugin's skill only gets a prefixed name. A skill in the project's own location takes the bare one, and installing
    it per project keeps that to projects that have a tracker.
    """
    target = pathlib.Path(directory) / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
    if target.exists() and SKILL_MARK not in target.read_text(encoding="utf-8"):
        raise PlanError(f"{target} exists and is not this skill; it was left alone")
    text = _skill_source().read_text(encoding="utf-8")
    text = text.replace("name: status\n", f"name: {SKILL_NAME}\n", 1)
    # This file is likely to be committed, so it names no folder of this machine.
    text = text.replace('sh "${CLAUDE_PLUGIN_ROOT}/bin/gitdone"', "uvx gitdone")
    text = text.replace("which this plugin puts on the Bash tool's PATH", "which the gitdone plugin or a pipx install puts on the Bash tool's PATH")
    head, close, body = text.partition("\n---\n")
    text = f"{head}{close}<!-- {SKILL_MARK}: written by `gitdone install-skill`; the plugin's skill is the source. -->\n{body}"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(target, text)
    return target
