# app/streamlit/pages/0_Personas.py

import _bootstrap  # ensures repo root is on sys.path
import json, tempfile, os
from pathlib import Path

import streamlit as st
from adapters.personas_portal_adapter import load_and_expand

# Try to use utils.store if available; otherwise fallback to plain write
try:
    from utils.store import save_json as _save_json_util
except Exception:
    _save_json_util = None

st.title("Personas")
st.caption("Load your Personas Portal JSON from the repo or upload, then convert to internal Persona objects.")

DEFAULT_PATH = Path("data/personas.json")


def _load_repo_personas() -> dict | None:
    """Return parsed JSON from data/personas.json if present and valid."""
    if not DEFAULT_PATH.exists():
        return None
    try:
        text = DEFAULT_PATH.read_text(encoding="utf-8").strip()
        if not text or text in ("[]", ""):
            return None
        return json.loads(text)
    except Exception as e:
        st.warning(f"Found {DEFAULT_PATH} but could not parse JSON: {e}")
        return None


def _save_personas_list(persona_objs) -> None:
    """Save expanded personas list to data/personas.json, via utils.store if available."""
    payload = [p.model_dump() for p in persona_objs]
    if _save_json_util:
        # utils.store writes into data/ under the hood
        _save_json_util("personas.json", payload)
    else:
        DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Load source ----------
source_label = None
data_obj: dict | None = _load_repo_personas()
if data_obj:
    source_label = f"Loaded personas from {DEFAULT_PATH}"
    st.success(source_label)

uploaded = st.file_uploader("Upload personas.json (optional; overrides repo file)", type=["json"])
if uploaded is not None:
    try:
        data_obj = json.load(uploaded)
        source_label = "Loaded personas from uploaded file"
        st.success(source_label)
    except Exception as e:
        st.error(f"Failed to parse uploaded JSON: {e}")

# ---------- Parse and render ----------
if data_obj:
    try:
        # Write to a temp path because the adapter expects a file path
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp:
            json.dump(data_obj, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name

        try:
            personas = load_and_expand(tmp_path)  # returns List[Persona]
        finally:
            # Always clean up temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        st.success(f"Imported {len(personas)} personas.")
        st.caption(source_label or "Loaded personas")

        # Preview up to 60
        for p in personas[:60]:
            overlays = ", ".join(p.overlays) if getattr(p, "overlays", None) else "base"
            with st.expander(f"{p.name} | {p.segment} | {overlays}"):
                st.json(p.model_dump(), expanded=False)

        col1, col2 = st.columns(2)
        if col1.button("💾 Save expanded to /data/personas.json"):
            try:
                _save_personas_list(personas)
                st.success(f"Saved expanded personas to {DEFAULT_PATH}")
            except Exception as e:
                st.error(f"Failed to save: {e}")

        if col2.button("🔁 Reset (clear cache)"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.rerun()

    except Exception as e:
        st.error(f"Failed to convert personas: {e}")
else:
    st.info(
        f"No personas loaded yet. Commit a personas.json to **{DEFAULT_PATH}** in the repo "
        f"or upload a file above."
    )
