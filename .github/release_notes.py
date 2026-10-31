#!/usr/bin/env python3
"""Print the CHANGELOG section for one version: the body of its GitHub Release.

    python3 .github/release_notes.py 0.2.0           the section
    python3 .github/release_notes.py v0.2.0 --title  its one-line title

Exit 1 when the version has no section: a release without notes is a claim, and the workflow refuses to make one.
"""
import pathlib
import re
import sys

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)(?: \((?:\d{4}-\d{2}-\d{2}|unreleased)\))?(?: · (.*))?$", re.M)


def section(version):
    """(title, body) for a version, or None."""
    text = CHANGELOG.read_text(encoding="utf-8")
    heads = list(HEADING.finditer(text))
    for i, match in enumerate(heads):
        if match.group(1) == version:
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            words = (match.group(2) or "").strip().strip('"')
            return f"v{version}" + (f": {words}" if words else ""), text[match.end():end].strip("\n")
    return None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = list(sys.argv[1:] if argv is None else argv)
    want_title = "--title" in args
    args = [a for a in args if a != "--title"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    version = args[0].lstrip("v")
    found = section(version)
    if found is None:
        print(f"release_notes: CHANGELOG.md has no section for {version}; write it before tagging", file=sys.stderr)
        return 1
    sys.stdout.write(found[0 if want_title else 1] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
