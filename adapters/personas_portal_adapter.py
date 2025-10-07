# adapters/personas_portal_adapter.py
from __future__ import annotations

import json
import os
import pathlib
from typing import List, Dict, Any

# Streamlit is optional here; import lazily so we don't explode if secrets are missing
def _maybe_read_secrets_json() -> Dict[str, Any] | None:
    try:
        import streamlit as st  # local import to avoid import-time parsing
    except Exception:
        return None

    # Do NOT probe with `"in st.secrets"`; Streamlit tries to parse immediately.
    # Just try to read and swallow errors if secrets are absent or malformed.
    try:
        # Prefer nested [personas] block
        blob = None
        try:
            blob = st.secrets["personas"]["PERSONAS_JSON"]
        except Exception:
            # Allow a top-level PERSONAS_JSON too, if someone configured it that way
            blob = st.secrets.get("PERSONAS_JSON")

        if not blob:
            return None

        if isinstance(blob, str):
            data = json.loads(blob)
        else:
            # If it's already dict-like
            data = dict(blob)

        # Accept either {"personas": [...]} or just [...]
        return data if isinstance(data, dict) else {"personas": data}
    except Exception:
        return None


def _read_file_candidates(explicit_path: str | None = None) -> Dict[str, Any] | None:
    """
    Try a few sensible locations for personas.json, returning the parsed dict if found.
    """
    candidates: list[pathlib.Path] = []

    if explicit_path:
        candidates.append(pathlib.Path(explicit_path))

    # Allow env override
    env_path = os.environ.get("PERSONAS_PATH")
    if env_path:
        candidates.append(pathlib.Path(env_path))

    here = pathlib.Path(__file__).resolve()
    # Common locations relative to repo root / working dir
    candidates.extend([
        pathlib.Path.cwd() / "assets" / "personas.json",
        pathlib.Path.cwd() / "personas.json",
        here.parents[2] / "assets" / "personas.json",   # <repo>/assets/personas.json
        here.parents[2] / "personas.json",               # <repo>/personas.json
        here.parents[1] / "assets" / "personas.json",    # if adapters/ is at repo root
        here.parents[1] / "personas.json",
    ])

    for p in candidates:
        try:
            if p and p.exists():
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                # Accept either {"personas": [...]} or just [...]
                return data if isinstance(data, dict) else {"personas": data}
        except Exception:
            # Try next candidate quietly
            continue

    return None


def _patch_minimums(p: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep behavior consistent with your earlier portal: fill a few default keys so downstream
    UI doesn’t trip over missing fields.
    """
    p.setdefault("future_confidence", 3)
    p.setdefault("family_support_received", False)
    p.setdefault("ideal_salary_for_comfort", 120_000)
    p.setdefault("budget_adjustments_6m", [])
    p.setdefault("super_engagement", "Unknown")
    p.setdefault("property_via_super_interest", "No")
    return p


def load_and_expand(personas_path: str | None = None) -> List[Dict[str, Any]]:
    """
    Returns the *grouped* personas structure: a list of dicts like
    { "segment": "…", "male": {...}, "female": {...} }.

    Load order:
      1) repo file (assets/personas.json or explicit path / env)
      2) Streamlit secrets [personas].PERSONAS_JSON (or top-level PERSONAS_JSON)
    """
    data = _read_file_candidates(personas_path) or _maybe_read_secrets_json()
    if not data or "personas" not in data or not isinstance(data["personas"], list):
        raise FileNotFoundError(
            "Personas JSON not found. Add assets/personas.json to the repo "
            "or set PERSONAS_PATH env, or put PERSONAS_JSON inside [personas] in secrets."
        )

    groups: List[Dict[str, Any]] = []
    for group in data["personas"]:
        # Keep shape identical to your original file so existing UI works
        seg = group.get("segment", "")
        out = {"segment": seg}
        for gender in ("male", "female"):
            if isinstance(group.get(gender), dict):
                out[gender] = _patch_minimums({**group[gender]})
        groups.append(out)

    return groups
