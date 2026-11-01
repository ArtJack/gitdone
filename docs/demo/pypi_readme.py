#!/usr/bin/env python3
"""PyPI's page, made from the README: one instruction in two places, with links that resolve there, pinned to the release they describe. A test compares.

    python3 docs/demo/pypi_readme.py            print it
    python3 docs/demo/pypi_readme.py --write    rewrite README-pypi.md
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from gitdone import __version__  # noqa: E402

REPOSITORY = "https://github.com/ArtJack/gitdone"
RAW = "https://raw.githubusercontent.com/ArtJack/gitdone"
REGISTRY_NAME = "<!-- mcp-name: io.github.ArtJack/gitdone -->"  # the MCP registry reads this to know the package is ours
PICTURE = (".svg", ".png")


def _target(path, version):
    """Where a path in the repository lives, seen from PyPI. A heading there has no anchor, so a link to one goes to the repository's page."""
    if path.startswith("#"):
        return f"{REPOSITORY}{path}"
    name, _, anchor = path.partition("#")
    if name.endswith(PICTURE):
        return f"{RAW}/v{version}/{name}"
    kind = "tree" if (ROOT / name).is_dir() else "blob"
    return f"{REPOSITORY}/{kind}/v{version}/{name}" + (f"#{anchor}" if anchor else "")


def made_from(readme, version=__version__):
    text = re.sub(r"\]\((?!https?://|mailto:)([^)\s]+)\)", lambda m: f"]({_target(m.group(1), version)})", readme)
    text = re.sub(r'<img src="(?!https?://)([^"]+)"', lambda m: f'<img src="{_target(m.group(1), version)}"', text)
    title, _, rest = text.partition("\n")
    return f"{title}\n\n{REGISTRY_NAME}\n{rest}"


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    text = made_from((ROOT / "README.md").read_text(encoding="utf-8"))
    if "--write" in args:
        (ROOT / "README-pypi.md").write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
