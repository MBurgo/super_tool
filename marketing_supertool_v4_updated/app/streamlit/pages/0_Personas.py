import streamlit as st, json, tempfile, os
from adapters.personas_portal_adapter import load_and_expand
from utils.store import save_json

st.title("Personas")
st.caption("Upload your Personas Portal JSON and convert to internal Persona objects.")

uploaded = st.file_uploader("Upload personas.json", type=["json"])
if uploaded:
    raw = json.load(uploaded)
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
        save_json("personas.json", [p.model_dump() for p in personas])
        st.success("Saved.")
else:
    st.info("Drop in the JSON you shared earlier to build your synthetic panel.")
