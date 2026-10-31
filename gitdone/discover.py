"""Which plan a directory belongs to.

The nearest `.gitdone.json` decides. That file is either the plan itself or a pointer to one: `{"plan": "path"}`.

One extension, off unless asked for: with GITDONE_PACKS naming a folder of per-project notes, a line
`gitdone: path/to/plan.json` in `<folder>/<project name>.md` also counts, for plans kept outside the project.
"""
import json
import os
import pathlib
import re

from .plan import PlanError, symlink_in

POINTER = ".gitdone.json"
PACKS_ENV = "GITDONE_PACKS"
MARKER = re.compile(r"^\s*(?:<!--\s*)?gitdone:\s*(\S+?)\s*(?:-->)?\s*$", re.MULTILINE)


def _ancestors(start):
    """start and its parents, up to but not including the home directory or the root."""
    home = pathlib.Path.home().resolve()
    here = pathlib.Path(start).expanduser().resolve()
    while here != home and here != here.parent:
        yield here
        here = here.parent


def _from_pointer(directory):
    pointer = directory / POINTER
    if not pointer.is_file():
        return None
    if pointer.is_symlink():  # a clone can carry a link into a project beside it, and a command run here would write there
        raise PlanError(f"{pointer} is a symbolic link; the tracker's files must be real files")
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "status_doc" in data:  # the file is the plan
            return pointer.resolve()
        plan = data["plan"]
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise PlanError(f"{pointer} is unreadable: it needs to be a plan, or {{\"plan\": \"path\"}} ({err})")
    return _resolved(directory, plan, pointer)


def _from_pack(directory, packs):
    pack = packs / f"{directory.name}.md"
    if not pack.is_file():
        return None
    marker = MARKER.search(pack.read_text(encoding="utf-8"))
    return _resolved(directory, marker.group(1), pack) if marker else None


def _resolved(directory, value, source):
    path = pathlib.Path(value).expanduser()
    if symlink_in(directory, str(path)):
        raise PlanError(f"{source} names the plan {path}, a symbolic link; the tracker's files must be real files")
    path = path if path.is_absolute() else directory / path
    if not path.is_file():
        raise PlanError(f"{source} names the plan {path}, which does not exist")
    return path.resolve()


def pointer_directory(start=None):
    """The nearest directory holding a pointer file, or None."""
    for directory in _ancestors(start or os.getcwd()):
        if (directory / POINTER).is_file():
            return directory
    return None


def find_plan(start=None, packs=None):
    """The plan for a directory, or None. The nearest pointer wins; a pack marker, if packs are configured, comes after."""
    start = start or os.getcwd()
    directories = list(_ancestors(start))
    for directory in directories:
        found = _from_pointer(directory)
        if found:
            return found
    packs = packs or os.environ.get(PACKS_ENV)
    if packs:
        for directory in directories:
            found = _from_pack(directory, pathlib.Path(packs).expanduser())
            if found:
                return found
    return None
