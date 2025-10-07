# app/streamlit/pages/1B_Trends_from_Sheets.py
import _bootstrap  # sets up sys.path for "adapters", "core", "utils"
import json, os
from pathlib import Path
import streamlit as st

from adapters.trends_google_sheets_adapter import build_trendbriefs_from_sheet

st.title("Trends (Google Sheets)")
st.caption("Pulls data from your existing spreadsheet and converts to TrendBriefs.")

# ---------- helpers ----------
def _default_sheet_id() -> str:
    # Prefer secrets; fall back to env; finally optional file in repo
    for key in ("GOOGLE_TRENDS_SHEET_ID", "SPREADSHEET_ID"):
        try:
            val = st.secrets[key]  # works on Streamlit Cloud
            if val:
                return str(val).strip()
        except Exception:
            pass
    sid = os.getenv("GOOGLE_TRENDS_SHEET_ID") or os.getenv("SPREADSHEET_ID")
    if sid:
        return sid.strip()
    sid_file = Path("assets/sheet_id.txt")
    return sid_file.read_text(encoding="utf-8").strip() if sid_file.exists() else ""

def _default_service_account_json_text() -> str:
    # 1) secrets as mapping (recommended)
    try:
        sa = st.secrets["service_account"]  # [service_account] block in secrets.toml
        if isinstance(sa, dict):
            # Convert to a plain dict (st.Secrets is mapping-like) then JSON
            sa_dict = {k: sa[k] for k in sa.keys()}
            return json.dumps(sa_dict, ensure_ascii=False, indent=2)
        if isinstance(sa, str) and sa.strip().startswith("{"):
            return sa.strip()
    except Exception:
        pass

    # 2) secrets as raw string (less common)
    try:
        raw = st.secrets["SERVICE_ACCOUNT_JSON"]
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    except Exception:
        pass

    # 3) env variables
    for env_key in ("SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON"):
        v = os.getenv(env_key)
        if v and v.strip():
            return v.strip()

    # 4) repo fallbacks (optional)
    for p in ("assets/service_account.json", "data/service_account.json"):
        fp = Path(p)
        if fp.exists():
            return fp.read_text(encoding="utf-8")

    return ""  # nothing found

# ---------- UI ----------
sheet_id = st.text_input(
    "Spreadsheet ID",
    value=_default_sheet_id(),
    help="The long key from your Google Sheets URL.",
)

sa_json_text = _default_service_account_json_text()
has_sa = bool(sa_json_text.strip())

st.checkbox("Show raw Service Account JSON (sensitive)", value=False, key="show_sa_json")
if st.session_state.show_sa_json:
    st.text_area("Service Account JSON", value=sa_json_text, height=220)

if st.button("Connect & Load Trends", type="primary"):
    if not sheet_id.strip():
        st.error("Please provide a Spreadsheet ID.")
        st.stop()

    sa_info = None
    if has_sa:
        try:
            sa_info = json.loads(sa_json_text)
        except json.JSONDecodeError as e:
            st.error(f"Your Service Account JSON is not valid JSON: {e}")
            st.stop()

    with st.spinner("Connecting to Google Sheets and building TrendBriefs…"):
        try:
            # Support both adapter signatures
            try:
                briefs = build_trendbriefs_from_sheet(sheet_id, service_account_info=sa_info)
            except TypeError:
                briefs = build_trendbriefs_from_sheet(sheet_id, service_account=sa_info)
        except Exception as e:
            st.error(f"Failed to load from Google Sheets: {e}")
            st.stop()

    st.success(f"Loaded {len(briefs)} TrendBriefs from the sheet.")
    for b in briefs:
        with st.expander(b.title or "Trend"):
            # If your TrendBrief is a Pydantic model:
            try:
                st.json(b.model_dump())
            except Exception:
                # Fallback if it's a plain dict or dataclass
                st.json(getattr(b, "__dict__", b))
