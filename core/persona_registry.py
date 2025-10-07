# core/persona_registry.py
from __future__ import annotations
import json, tempfile
from pathlib import Path
from typing import List, Optional

try:
    import streamlit as st  # type: ignore
except Exception:
    st = None  # allows CLI/unit test usage

from adapters.personas_portal_adapter import load_and_expand  # reuse your adapter
from core.models import Persona

_ASSET_PATHS = [Path("assets/personas.json"), Path("data/personas.json")]
_CACHE: Optional[List[Persona]] = None

def _load_from_assets() -> Optional[List[Persona]]:
    for p in _ASSET_PATHS:
        if p.exists() and p.read_text(encoding="utf-8").strip():
            return load_and_expand(str(p))
    return None

def _load_from_secrets() -> Optional[List[Persona]]:
    # Don't hard-depend on secrets; swallow any parsing/availability errors.
    if not st:
        return None
    try:
        sect = st.secrets.get("personas", {})  # type: ignore[attr-defined]
        raw = sect.get("PERSONAS_JSON")
        if not raw:
            return None
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp:
            tmp.write(raw)
            tmp.flush()
            return load_and_expand(tmp.name)
    except Exception:
        return None

def get_personas(refresh: bool = False) -> List[Persona]:
    """Single place the whole app reads personas from."""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    personas = _load_from_assets() or _load_from_secrets()
    if not personas:
        raise FileNotFoundError(
            "No personas found. Commit a personas file at assets/personas.json "
            "or set [personas].PERSONAS_JSON in Streamlit secrets."
        )
    _CACHE = personas
    return personas
