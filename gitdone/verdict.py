"""The QA record beside the release line. Read-only: Verdict owns the state file; this module only opens it for reading.

The annotation goes to the terminal and the opener, never into STATUS.md. A QA run elsewhere changes the state file
at any hour, and a view that moved with it could not be gated byte for byte.
"""
import collections
import json

from .evidence import find_shas

Annotation = collections.namedtuple("Annotation", "line flag")


def release_shas(plan):
    if plan.release_sha:
        return [plan.release_sha]
    return find_shas(plan.release)


def annotate(plan):
    """Annotation(line, flag), or None when the plan names no state file."""
    if plan.verdict_state is None:
        return None
    try:
        with open(plan.verdict_state, encoding="utf-8") as handle:
            state = json.load(handle)
        last_run = state.get("last_run") or {}
        gated = last_run.get("git_sha") or ""
        if not isinstance(gated, str):
            raise ValueError(f"git_sha is {gated!r}")
    except (OSError, ValueError, AttributeError) as err:
        return Annotation(f"Verdict: state unreadable ({plan.verdict_state}: {err})", None)
    words = [f"run {state.get('run_number', '?')}", str(state.get("verdict", "no verdict")),
             f"gated {gated[:7] or 'unknown'}"]
    base, dots, head = str(last_run.get("sha_range") or "").partition("..")
    if dots and base != head:
        words.append(f"range {base[:7]}..{head[:7]}")
    words.append(f"model {last_run.get('model', 'unknown')}")
    return Annotation("Verdict: " + ", ".join(words), _flag(plan, gated))


def _flag(plan, gated):
    shas = release_shas(plan)
    if not gated or not shas:
        return None
    if any(gated.startswith(s) or s.startswith(gated) for s in shas):
        return None
    named = ", ".join(s[:7] for s in shas)
    return f"the plan's release ({named}) is not the gated commit ({gated[:7]})"


def release_line(plan):
    """The release and its gate, one line; a second line if they disagree. Empty when the plan names neither."""
    words = []
    if plan.release:
        words.append(f"Release: {plan.release}.")
    note = annotate(plan)
    if note:
        words.append(note.line + ".")
    line = " ".join(words)
    if note and note.flag:
        line += f"\n⚠ {note.flag}"
    return line
