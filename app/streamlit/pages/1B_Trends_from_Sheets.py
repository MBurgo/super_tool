import _bootstrap
import streamlit as st, json
from adapters.trends_google_sheets_adapter import build_trendbriefs_from_sheet
from utils.store import save_json

st.title("Trends (Google Sheets)")
st.caption("Pulls data from your existing spreadsheet and converts to TrendBriefs.")

# Prefer secrets → fall back to upload/paste
sa = None
if "service_account" in st.secrets:
    sa = dict(st.secrets["service_account"])
    email = sa.get("client_email", "service account")
    st.success(f"Using Google service account from secrets ({email}).")
else:
    with st.expander("Provide Service Account JSON", expanded=True):
        st.write("Upload your Google Service Account JSON or paste it below. It is used only in-session.")
        uploaded = st.file_uploader("Upload JSON", type=["json"])
        sa_text = st.text_area("Or paste JSON here")
        if uploaded and not sa_text.strip():
            sa_text = uploaded.read().decode("utf-8")

default_sheet = st.secrets.get("GOOGLE_TRENDS_SHEET_ID", "1BzTJgX7OgaA0QNfzKs5AgAx2rvZZjDdorgAz0SD9NZg")
spreadsheet_id = st.text_input("Spreadsheet ID", value=default_sheet)
limit = st.slider("Max TrendBriefs", 5, 20, 8)

if st.button("Fetch from Sheet"):
    try:
        if sa is None:
            if not sa_text.strip():
                st.error("Provide service account JSON.")
                st.stop()
            sa = json.loads(sa_text)

        briefs = build_trendbriefs_from_sheet(sa, spreadsheet_id, limit=limit)
        st.success(f"Pulled {len(briefs)} briefs.")
        for b in briefs:
            with st.expander(b.headline[:80]):
                st.json(b.model_dump(), expanded=False)
        if st.button("Save to /data/trends/sample_trends.json"):
            save_json("trends/sample_trends.json", [b.model_dump() for b in briefs])
            st.success("Saved. Go run Campaign Lab.")
    except Exception as e:
        st.error(f"Failed: {e}")
