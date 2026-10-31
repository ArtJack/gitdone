"""The engine as a script with an absolute path, for tests that start it as a process from another folder."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from gitdone.cli import main  # noqa: E402

sys.exit(main())
