"""Make the suite runnable from the repo root with any interpreter:

    python -m unittest discover -s tests

The repo root is itself the `fishwitch` package, and the app mixes plain
imports (`import tactics`) with package imports (`from fishwitch import ...`),
so both the root and its parent must be importable.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)
