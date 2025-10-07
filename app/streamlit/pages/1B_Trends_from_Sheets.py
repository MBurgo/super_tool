# app/streamlit/pages/1B_Trends_from_Sheets.py
import _bootstrap  # keeps absolute imports working on Streamlit Cloud
import json, os
import streamlit as st

from adapters.trends_google_sheets_adapter import build_trendbriefs_from_sheet

st.title("Trends (Google Sheets)")
st.caption("Pulls data from your existing spreadsheet and converts to TrendBriefs.")

# ─────────────────────────────────────────────────────────────────────────────
# Safe access helpers — avoid `in st.secrets` so we don't trigger parser errors
# ─────────────────────────────────────────────────────────────────────────────
def get_secret_or_env(secret_path, env_var, default=None):
    """
    Try to fetch a value from st.secrets using a dotted path like 'google.spreadsheet_id'.
    If secrets are missing or the key doesn't exist, fall back to os.environ[env_var].
    """
    # 1) Try secrets
    try:
        parts = secret_path.split(".")
        cur = st.secrets
        for p in parts:
            cur = cur[p]  # will raise if any level is missing or secrets file absent
        return cur
    except Exception:
        pass

    # 2) Try environment
    val = os.getenv(env_var)
    return val if val else default


def get_service_account_dict():
    """
    Return a dict for the GCP service account.
    Sources (in order):
      - st.secrets["service_account"] (if present)
      - os.environ["SERVICE_ACCOUNT_JSON"] (full JSON blob)
      - None (handled by UI paste field)
    """
    # Try st.secrets
    try:
        sa = st.secrets["service_account"]
        # st.secrets mapping is already dict-like
        return dict(sa)
    except Exception:
        pass

    # Try env var
    raw = os.getenv("SERVICE_ACCOUNT_JSON")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Pre-fill inputs from secrets/env when available
# ─────────────────────────────────────────────────────────────────────────────
spreadsheet_id = get_secret_or_env(
    "google.spreadsheet_id",
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    default=""
)
sa_guess = get_service_account_dict()
sa_text_default = json.dumps(sa_guess, indent=2) if sa_guess else ""

# ─────────────────────────────────────────────────────────────────────────────
# UI – connection pane
# ─────────────────────────────────────────────────────────────────────────────
st.subheader("Connect Google Sheets")

spreadsheet_id = st.text_input(
    "Spreadsheet ID",
    value=spreadsheet_id,
    help="The long ID from your Google Sheet URL (between /d/ and /edit)."
)

st.markdown(
    "Provide a Service Account JSON below (auto‑filled if present in secrets or env)."
)
sa_text = st.text_area(
    "Service Account JSON",
    value=sa_text_default,
    height=220,
    help="Paste the full JSON for your GCP service account. "
         "Alternatively, set [service_account] in Streamlit secrets "
         "or SERVICE_ACCOUNT_JSON env var."
)

colA, colB = st.columns([1, 3])
run_btn = colA.button("Load Briefs", type="primary")

# ─────────────────────────────────────────────────────────────────────────────
# Action – build briefs
# ─────────────────────────────────────────────────────────────────────────────
if run_btn:
    if not spreadsheet_id.strip():
        st.error("Please provide a Spreadsheet ID.")
        st.stop()

    sa_dict = None
    if sa_text.strip():
        try:
            sa_dict = json.loads(sa_text)
        except json.JSONDecodeError as e:
            st.error(f"Service Account JSON is not valid JSON: {e}")
            st.stop()
    else:
        # If textarea empty, try to recover from secrets/env again
        sa_dict = get_service_account_dict()

    if not sa_dict:
        st.error("No Service Account credentials provided. Paste the JSON or add it to secrets/env.")
        st.stop()

    with st.spinner("Reading sheets and building briefs…"):
        try:
            # The adapter should handle creating the gspread client from sa_dict internally.
            briefs = build_trendbriefs_from_sheet(
                spreadsheet_id=spreadsheet_id,
                service_account=sa_dict,
            )
        except Exception as e:
            st.exception(e)
            st.stop()

    if not briefs:
        st.warning("No briefs were produced from the spreadsheet.")
    else:
        st.success(f"Loaded {len(briefs)} brief(s).")

        for i, b in enumerate(briefs, 1):
            with st.expander(f"Brief {i}", expanded=(i == 1)):
                # Render gracefully whether adapter returns pydantic model or dict
                try:
                    payload = b.model_dump()  # pydantic v2
                except Exception:
                    try:
                        payload = b.dict()  # pydantic v1
                    except Exception:
                        payload = b if isinstance(b, dict) else {"brief": str(b)}

                # Pretty print common fields if present
                title = payload.get("title") or payload.get("headline") or f"Brief {i}"
                st.markdown(f"**{title}**")
                if payload.get("synopsis"):
                    st.write(payload["synopsis"])
                if payload.get("themes"):
                    st.markdown("**Themes**")
                    st.write(payload["themes"])
                if payload.get("entities"):
                    st.markdown("**Entities**")
                    st.write(payload["entities"])
                if payload.get("sources"):
                    st.markdown("**Sources**")
                    st.write(payload["sources"])

                st.markdown("—")
                st.json(payload)
