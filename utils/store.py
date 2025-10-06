import json, time
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DATA_DIR.mkdir(exist_ok=True)

def save_json(rel_path: str, obj: Any):
    p = DATA_DIR / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_json(rel_path: str, default=None):
    p = DATA_DIR / rel_path
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
