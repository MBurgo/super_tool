# app/streamlit/pages/0_Personas.py

import _bootstrap  # ensures repo root is on sys.path; keep this first
from pathlib import Path
import streamlit as st, json, os, tempfile

from adapters.personas_portal_adapter import load_and_expand
from utils.store import save_json

st.title("Personas")
st.caption("Load your Personas Portal JSON from the repo or upload, then convert to internal Persona objects.")

# ──────────────────────────────────────────────────────────────────────
# Helpers to locate personas JSON from repo or secrets
# ──────────────────────────────────────────────────────────────────────
def _read_repo_personas():
    """
    Return (json_text, origin_path|None) if a repo file exists and is non-empty.
    Search priority: data/personas.json → assets/personas.json → personas.json
    """
    for p in [Path("data/personas.json"), Path("assets/personas.json"), Path("personas.json")]:
        try:
            if p.exists():
                txt = p.read_text(encoding="utf-8").strip()
                if txt and txt not in ("[]", "{}"):
                    return txt, str(p)
        except Exception:
            # ignore unreadable files and keep searching
            pass
    return None, None


def _read_secrets_personas():
    """
    Return (json_text, origin_label|None) if personas are supplied via secrets.
    Supports either:
      st.secrets["personas"]["PERSONAS_JSON"]  or
      st.secrets["PERSONAS_JSON"]
    Guarded to avoid StreamlitSecretNotFoundError when no secrets exist.
    """
    # nested block first
    try:
        block = st.secrets.get("personas")
        if isinstance(block, dict) and block.get("PERSONAS_JSON"):
            return str(block["PERSONAS_JSON"]), "secrets[personas].PERSONAS_JSON"
    except Exception:
        pass

    # flat key fallback
    try:
        flat = st.secrets.get("PERSONAS_JSON")
        if flat:
            return str(flat), "secrets.PERSONAS_JSON"
    except Exception:
        pass

    return None, None


# ──────────────────────────────────────────────────────────────────────
# Load order: upload (override) → repo → secrets
# ──────────────────────────────────────────────────────────────────────
uploaded = st.file_uploader("Upload personas.json (optional; overrides repo file)", type=["json"])

repo_text, repo_origin = _read_repo_personas()
sec_text, sec_origin = _read_secrets_personas()

raw_text = None
source_label = None

if uploaded is not None:
    try:
        raw_obj = json.load(uploaded)
        raw_text = json.dumps(raw_obj, ensure_ascii=False)
        source_label = f"upload:{uploaded.name}"
        st.success(f"Loaded personas from uploaded file: {uploaded.name}")
    except Exception as e:
        st.error(f"Uploaded file isn't valid JSON: {e}")

elif repo_text:
    raw_text = repo_text
    source_label = repo_origin
    st.success(f"Loaded personas from {repo_origin}")

elif sec_text:
    raw_text = sec_text
    source_label = sec_origin
    st.success(f"Loaded personas from {sec_origin}")

else:
    st.info(
        "No personas loaded yet. Commit a personas.json to **data/personas.json** "
        "or **assets/personas.json** in the repo, add **PERSONAS_JSON** to secrets, "
        "or upload a file above."
    )

# ──────────────────────────────────────────────────────────────────────
# Parse, convert, preview, and optionally save to /data/personas.json
# ──────────────────────────────────────────────────────────────────────
if raw_text:
    try:
        # Validate that the text is JSON and write to a temp file so adapter accepts a path
        _ = json.loads(raw_text)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmp.write(raw_text)
            tmp_path = tmp.name

        personas = load_and_expand(tmp_path)
        os.unlink(tmp_path)

        st.success(f"Imported {len(personas)} personas from {source_label}")

        # Preview up to 60 to avoid rendering a novel
        for p in personas[:60]:
            overlays = ", ".join(getattr(p, "overlays", []) or []) or "base"
            with st.expander(f"{p.name} | {p.segment} | {overlays}"):
                st.json(p.model_dump(), expanded=False)

        if st.button("Save to repo as data/personas.json"):
            save_json("personas.json", [p.model_dump() for p in personas])
            st.success("Saved to data/personas.json")

    except Exception as e:
        st.error(f"Failed to parse or load personas: {e}")
