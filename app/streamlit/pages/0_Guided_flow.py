# app/streamlit/pages/0_Guided_Flow.py
# ─────────────────────────────────────────────────────────────────────────────
# Guided Campaign Builder (no Sheets). Robust imports + graceful fallbacks.
# ─────────────────────────────────────────────────────────────────────────────
import sys, os
from pathlib import Path

# --- Robust path bootstrap (works from inside /app/streamlit/pages) ----------
_THIS = Path(__file__).resolve()
STREAMLIT_DIR = _THIS.parent                 # .../app/streamlit/pages
APP_DIR       = STREAMLIT_DIR.parent         # .../app/streamlit
PROJECT_DIR   = APP_DIR.parent               # .../app
REPO_ROOT     = PROJECT_DIR.parent           # repo root (where core/, adapters/, assets/ live)

for p in [str(REPO_ROOT), str(PROJECT_DIR), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st
from io import BytesIO
import numpy as np
import json

# --- Imports with fallbacks ---------------------------------------------------
# Trends fetcher (requests-based SerpAPI; no serpapi lib required)
try:
    from adapters.trends_serp_adapter import fetch_trends_and_news
except Exception as e:
    fetch_trends_and_news = None

# Copy generator
try:
    from adapters.copywriter_mf_adapter import generate as gen_copy
except Exception as e:
    gen_copy = None

# Sprint engine (NumPy-only k-means + Altair chart)
try:
    from core.sprint_engine import run_sprint
except Exception:
    # Fallback to root-level sprint_engine.py if present
    try:
        from sprint_engine import run_sprint  # type: ignore
    except Exception:
        run_sprint = None

# Personas loader
try:
    from core.tmf_synth_utils import load_personas
except Exception:
    try:
        from tmf_synth_utils import load_personas  # type: ignore
    except Exception:
        load_personas = None

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# --- Guard rails for missing modules -----------------------------------------
missing = []
if fetch_trends_and_news is None:
    missing.append("adapters/trends_serp_adapter.py")
if gen_copy is None:
    missing.append("adapters/copywriter_mf_adapter.py")
if run_sprint is None:
    missing.append("core/sprint_engine.py (or sprint_engine.py)")
if load_personas is None:
    missing.append("core/tmf_synth_utils.py (or tmf_synth_utils.py)")

if missing:
    st.error(
        "Missing modules: " + ", ".join(missing) +
        "\n\n• Ensure these files exist in your repo.\n"
        "• This page bootstraps paths automatically, so no extra sys.path hacks are needed.\n"
        f"• Expected repo root: {REPO_ROOT}"
    )
    st.stop()

# --- Config files & defaults --------------------------------------------------
TRAITS_CFG_PATH = REPO_ROOT / "assets" / "traits_config.json"
PERSONAS_PATH   = REPO_ROOT / "assets" / "personas.json"

if not TRAITS_CFG_PATH.exists():
    st.error(f"Missing traits config at {TRAITS_CFG_PATH}. Add assets/traits_config.json.")
    st.stop()

if not PERSONAS_PATH.exists():
    st.error(f"Missing personas at {PERSONAS_PATH}. Add assets/personas.json.")
    st.stop()

trait_cfg = json.loads(TRAITS_CFG_PATH.read_text(encoding="utf-8"))
personas  = load_personas(str(PERSONAS_PATH))  # returns data["personas"]

# --- Controls ----------------------------------------------------------------
st.caption("This flow pulls live rising queries + news via SerpAPI, drafts campaign copy, then refines it with a synthetic focus test.")
colA, colB = st.columns([1,1])
with colA:
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.5, 7.5, 0.1)
with colB:
    max_rounds = st.number_input("Max revision rounds", 1, 6, 3)

# --- 1) Kick off trend finder -------------------------------------------------
if st.button("🔎 Find live trends & news", type="primary"):
    serp_key = (
        st.secrets.get("serpapi", {}).get("api_key")
        if hasattr(st, "secrets") else None
    ) or os.getenv("SERP_API_KEY")

    if not serp_key:
        st.error("No SerpAPI key found. Add `[serpapi].api_key` to Streamlit secrets or set SERP_API_KEY env var.")
        st.stop()

    rising, news = fetch_trends_and_news(serp_key)
    # Reduce to top 10 rising by value if present
    def _val(x): 
        v = x.get("value", 0)
        try: return float(v)
        except Exception: return 0.0
    rising = sorted(rising, key=_val, reverse=True)[:10]

    themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in rising]
    st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

# --- 2) Generate initial variants --------------------------------------------
chosen = st.session_state.get("chosen_theme")
if chosen:
    st.subheader("Drafting campaign variants…")

    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "", "retail_price": "", "offer_term": "",
        "reports": "", "stocks_to_tease": "", "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)"
    }
    traits = {
        "Urgency":7, "Data_Richness":6, "Social_Proof":6,
        "Comparative_Framing":5, "Imagery":6,
        "Conversational_Tone":7, "FOMO":6, "Repetition":4
    }

    model_name = None
    # Prefer nested [openai].api_key, fallback to openai_api_key
    if hasattr(st, "secrets"):
        if "openai" in st.secrets and isinstance(st.secrets["openai"], dict):
            model_name = st.secrets.get("openai", {}).get("model") or st.secrets.get("openai_model") or "gpt-4.1"
        else:
            model_name = st.secrets.get("openai_model") or "gpt-4.1"
    else:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4.1")

    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=trait_cfg, traits=traits,
        country="Australia", model=model_name
    )
    texts = [v.copy for v in variants]
    pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # --- 3) Focus-test loop (auto-revise until pass) -------------------------
    st.subheader("🧪 Focus test & auto‑improve")
    st.write("Running synthetic focus group on **assets/personas.json** (50 variants).")

    if st.button("Run focus test + auto‑improve", type="primary"):
        current = base_text
        passed  = False

        for r in range(int(max_rounds)):
            # Wrap text as a small file-like so run_sprint can read it.
            class _Text(BytesIO):
                name = "copy.txt"
            f = _Text(current.encode("utf-8"))

            summary, df, fig, clusters = run_sprint(
                file_obj=f,
                segment="All Segments",
                persona_groups=personas,
                return_cluster_df=True
            )
            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0

            # Render chart (Altair)
            try:
                import altair as alt
                st.altair_chart(fig, use_container_width=True)
            except Exception:
                # If someone swaps the engine back to plotly in their local code
                st.plotly_chart(fig, use_container_width=True)

            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Build a short feedback brief from cluster summaries to improve copy
            tips = "\n".join([
                f"- Cluster {int(row['cluster'])}: {row['summary']}"
                for _, row in clusters.iterrows()
            ])
            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(
                improve_brief, fmt="sales_page", n=1,
                trait_cfg=trait_cfg, traits=traits,
                country="Australia", model=model_name
            )
            current = improved[0].copy

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
