# _bootstrap.py
# Put project root (where 'adapters' and 'core' live) at the front of sys.path.

import sys
from pathlib import Path

_here = Path(__file__).resolve()
candidates = [
    _here.parent,            # repo root if _bootstrap.py is at root
    _here.parent.parent,     # if _bootstrap.py sits in app/
    _here.parent.parent.parent,  # if deeper
]

root = None
for p in candidates:
    if (p / "adapters").exists() and (p / "core").exists():
        root = p
        break

if root and str(root) not in sys.path:
    sys.path.insert(0, str(root))
