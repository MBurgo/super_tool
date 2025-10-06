import sys
from pathlib import Path

# Walk up until we find a directory that contains our top-level packages
here = Path(__file__).resolve()
for i in range(1, 8):
    cand = here.parents[i-1]
    if (cand / "adapters").exists() and (cand / "core").exists() and (cand / "utils").exists():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break
