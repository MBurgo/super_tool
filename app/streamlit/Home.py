import _bootstrap
import streamlit as st
st.set_page_config(page_title="Marketing Super-Tool v4", page_icon="🛠️", layout="wide")
st.title("Marketing Super-Tool v4")
st.caption("Trends → Briefs → Copy → Persona feedback → Optimise → Finalists")

st.markdown("""
**Pages**
- Personas: import your Personas Portal JSON (overlays supported)
- Trends (Google Sheets): pull your existing sheet into TrendBriefs (now auto-uses secrets)
- Copy Studio: traits-driven copy generation with disclaimers
- Campaign Lab: pick a trend, generate variants, evaluate with Heuristic / Synthetic / Hybrid, iterate to a finalist
- Synthetic Focus: run the 50-persona clustered reaction test on any piece of copy
- Finalists: browse and export winners
""" )
