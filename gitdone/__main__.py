"""`python -m gitdone`: the same commands as the script."""
import sys

from .cli import main

sys.exit(main())
