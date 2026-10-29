#!/usr/bin/env python3
"""Run mdrestyler from its skill folder with nothing installed: python3 scripts/mdrestyler.py COMMAND [ARGS]."""
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True   # an installed skill folder stays as installed
# Compiled caches are never read either: a __pycache__ beside the verified sources could hold other code. A cache
# prefix that does not exist makes Python compile from the source files it imports.
sys.pycache_prefix = os.path.join(tempfile.gettempdir(), f'mdrestyler-no-cache-{os.getpid()}-{os.urandom(4).hex()}')
here = str(Path(__file__).resolve().parent)
sys.path[:] = [here] + [p for p in sys.path if p not in ('', '.', here)]   # this folder's package, never one from the cwd

from mdrestyler.cli import main  # noqa: E402

if __name__ == '__main__':   # a spawned worker imports this file again; only the command line runs the command
    sys.exit(main())
