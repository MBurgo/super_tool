import _bootstrap
import streamlit as st, json, tempfile, os
from adapters.personas_portal_adapter import load_and_expand
from utils.store import save_json

st.title("Personas")
st.caption("Upload your Personas Portal JSON and convert to internal Persona objects.")

# Auto-load from secrets if available
personas_json_text = None
if "PERSONAS_JSON" in st.secrets:
    st.success("Loaded personas from Streamlit secrets (PERSONAS_JSON).")
    personas_json_text = st.secrets["PERSONAS_JSON"]
elif Path("data/personas.json").exists() and Path("data/personas.json").read_text().strip() not in ("[]", ""):
    st.success("Loaded personas from data/personas.json.")
    personas_json_text = Path("data/personas.json").read_text(encoding="utf-8")

uploaded = st.file_uploader("Upload personas.json (optional)", type=["json"])

if personas_json_text or uploaded:
    try:
        raw = json.loads(personas_json_text) if personas_json_text else json.load(uploaded)
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp:
            json.dump(raw, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
        personas = load_and_expand(tmp_path)
        os.unlink(tmp_path)
        st.success(f"Imported {len(personas)} personas.")
        for p in personas[:60]:
            with st.expander(f"{p.name} | {p.segment} | {', '.join(p.overlays) if p.overlays else 'base'}"):
                st.json(p.model_dump(), expanded=False)
        if st.button("Save to /data/personas.json"):
            from utils.store import save_json
            save_json("personas.json", [p.model_dump() for p in personas])
            st.success("Saved.")
    except Exception as e:
        st.error(f"Failed to parse personas: {e}")
else:
    st.info("Provide personas via secrets (PERSONAS_JSON), check in data/personas.json, or upload here.")
