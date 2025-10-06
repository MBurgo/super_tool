import _bootstrap
import streamlit as st
from pathlib import Path
from utils.store import load_json

st.title("Finalists")
data_dir = Path(__file__).resolve().parents[2] / "data" / "finalists"
files = list(data_dir.glob("*.json"))
if not files:
    st.info("No finalists yet. Run the Campaign Lab.")
else:
    for p in files:
        st.subheader(p.name)
        st.json(load_json(f"finalists/{p.name}"), expanded=False)
