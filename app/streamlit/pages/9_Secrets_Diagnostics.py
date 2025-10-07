# app/streamlit/pages/9_Secrets_Diagnostics.py
import _bootstrap
import json
import streamlit as st
import adapters.trends_serp_adapter as serp_adapter
from adapters.trends_serp_adapter import get_serpapi_key, serp_key_diagnostics

st.set_page_config(page_title="Diagnostics: Secrets & Imports", page_icon="🛠️", layout="wide")
st.title("Diagnostics: Secrets & Imports")

st.markdown("This page shows non‑sensitive checks to confirm your app is reading Streamlit secrets and importing the right modules. It never prints secret values.")

diag = serp_key_diagnostics()
st.subheader("SerpAPI key diagnostics (lengths only)")
st.code(json.dumps(diag, indent=2), language="json")

key_present = bool(get_serpapi_key())
st.write("Resolved `get_serpapi_key()`:", "✅ found" if key_present else "❌ not found")

st.subheader("Import path checks")
st.write("Adapter module path:", serp_adapter.__file__)
st.write("Adapter version:", getattr(serp_adapter, "ADAPTER_VERSION", "n/a"))
