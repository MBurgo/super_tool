# adapters/personas_portal_adapter.py
from __future__ import annotations
import json, pathlib
import streamlit as st

# If you have a Pydantic Persona model, import and construct it.
# Otherwise we just return dicts and let the page render them.
try:
    from core.models import Persona
except Exception:
    Persona = None  # fallback

CANDIDATE_FILES = [
    pathlib.Path("data/personas.json"),
    pathlib.Path("personas.json"),
]

def _load_from_secrets() -> dict | None:
    """
    Try secrets in two forms:
    1) [personas].PERSONAS_JSON  (what you posted)
    2) PERSONAS_JSON             (legacy)
    Return parsed dict or None.
    """
    try:
        # Modern nested table
        if "personas" in st.secrets and isinstance(st.secrets["personas"], dict):
            tbl = st.secrets["personas"]
            if "PERSONAS_JSON" in tbl and str(tbl["PERSONAS_JSON"]).strip():
                return json.loads(tbl["PERSONAS_JSON"])
        # Legacy flat key
        if "PERSONAS_JSON" in st.secrets and str(st.secrets["PERSONAS_JSON"]).strip():
            return json.loads(st.secrets["PERSONAS_JSON"])
    except Exception as e:
        # Don’t crash the import; we’ll fall back to files.
        st.info(f"Skipping personas from secrets due to parse/format issue: {e}")
    return None

def _load_from_files() -> dict | None:
    for p in CANDIDATE_FILES:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return None

def load_and_expand() -> list:
    """
    Returns a flat list of persona objects/dicts:
    one entry per gendered persona per segment (ignores overlays with only 'type').
    """
    data = _load_from_secrets() or _load_from_files()
    if not data:
        raise RuntimeError(
            "No personas found. Add [personas].PERSONAS_JSON to secrets or ship data/personas.json."
        )

    out = []
    for group in data.get("personas", []):
        # Skip overlays that are not standard segment blocks
        for gender in ("male", "female"):
            if gender in group:
                seg = group.get("segment", "Unknown Segment")
                person = group[gender]
                if Persona:
                    out.append(Persona.from_seed(seg, person))  # if your model has a helper
                else:
                    # plain dict with segment merged in
                    d = dict(person)
                    d["segment"] = seg
                    out.append(d)
    return out
