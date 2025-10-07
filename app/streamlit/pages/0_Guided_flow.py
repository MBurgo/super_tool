# app/streamlit/pages/0_Guided_flow.py
# -----------------------------------------------------------------------------
# NO-SHEETS guided flow:
# 1) Pull rising queries + latest news via SerpAPI
# 2) User picks a theme
# 3) Generate variants (copywriter adapter)
# 4) Synthetic focus test loop until threshold
# -----------------------------------------------------------------------------
import _bootstrap  # keeps repo modules importable
import os, json, pathlib
from io import BytesIO

import numpy as np
import streamlit as st

from adapters.trends_serp_adapter import (
    get_serpapi_key,
    fetch_trends_and_news,
    enrich_news_with_meta,
)
from adapters.copywriter_mf_adapter import generate as gen_copy

# Localized imports from core
try:
    from core.sprint_engine import run_sprint
    from core.tmf_synth_utils import load_personas
except Exception:
    # Fallback to project root if core is at top level (rare)
    from sprint_engine import run_sprint  # type: ignore
    from tmf_synth_utils import load_personas  # type: ignore

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")


# ---------- tiny helpers ----------
def _load_traits_cfg() -> dict:
    candidates = [
        "assets/traits_config.json",
        "traits_config.json",
        "app/assets/traits_config.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    st.error(f"Missing traits_config.json. Add one of: {', '.join(candidates)}")
    st.stop()


def _load_personas() -> list:
    candidates = [
        "assets/personas.json",
        "data/personas.json",
        "personas.json",
    ]
    for p in candidates:
        if os.path.exists(p):
            return load_personas(p)
    st.error("Missing personas.json. Add to assets/personas.json (recommended).")
    st.stop()


def _get_openai_model() -> str:
    # Use OPENAI_MODEL secret if present, else default
    try:
        return st.secrets.get("openai_model") or "gpt-4.1"
    except Exception:
        return "gpt-4.1"


# ---------- 1) Find live trends & news ----------
if st.button("🔎 Find live trends & news", type="primary"):
    key = get_serpapi_key()
    if not key:
        st.error('SerpAPI key not found. Add to secrets as [serpapi] api_key="...".')
        st.stop()

    try:
        rising, news = fetch_trends_and_news(key)
    except Exception as e:
        st.error(f"Failed to fetch trends/news: {e}")
        st.stop()

    # Attach meta to the news (best-effort)
    news_enriched = enrich_news_with_meta(news)

    # Prepare theme strings from rising
    themes = []
    for r in (rising or [])[:10]:
        q = r.get("query", "(n/a)")
        v = r.get("value")
        v_str = f"{v}" if v is not None else ""
        themes.append(f"{q} — {v_str}")

    st.session_state["guidance"] = {
        "rising": rising,
        "news": news_enriched,
        "themes": themes or ["(no trends returned)"],
    }
    st.success("Fetched live rising queries and news.")


data = st.session_state.get("guidance")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice


# ---------- 2) Generate variants ----------
chosen = st.session_state.get("chosen_theme")
if chosen:
    st.subheader("Drafting campaign variants…")

    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "",
        "retail_price": "",
        "offer_term": "",
        "reports": "",
        "stocks_to_tease": "",
        "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)",
    }

    # Sensible default trait intensities
    traits = {
        "Urgency": 7,
        "Data_Richness": 6,
        "Social_Proof": 6,
        "Comparative_Framing": 5,
        "Imagery": 6,
        "Conversational_Tone": 7,
        "FOMO": 6,
        "Repetition": 4,
    }

    trait_cfg = _load_traits_cfg()
    model_name = _get_openai_model()

    try:
        variants = gen_copy(
            brief,
            fmt="sales_page",
            n=3,
            trait_cfg=trait_cfg,
            traits=traits,
            country="Australia",
            model=model_name,
        )
    except Exception as e:
        st.error(f"Copy generation failed: {e}")
        st.stop()

    texts = [v.copy for v in variants]
    if not texts:
        st.error("Model returned no variants. Please try again.")
        st.stop()

    st.markdown("### Variants")
    for i, t in enumerate(texts, 1):
        with st.expander(f"Variant {i}", expanded=(i == 1)):
            st.markdown(t)

    pick = st.radio(
        "Choose a base variant",
        [f"Variant {i+1}" for i in range(len(texts))],
        index=0,
        horizontal=True,
    )
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]

    st.session_state["guided_base_copy"] = base_text


# ---------- 3) Focus-test loop ----------
base_text = st.session_state.get("guided_base_copy")
if base_text:
    st.subheader("🧪 Synthetic Focus Test")
    personas = _load_personas()

    col1, col2 = st.columns(2)
    threshold = col1.slider("Passing mean intent threshold", 6.0, 9.5, 7.5, 0.1)
    rounds = int(col2.number_input("Max revision rounds", 1, 6, 3))

    if st.button("Run focus test + auto‑improve", type="primary"):
        current = base_text
        passed = False

        for r in range(rounds):
            # Wrap text into a file-like object for the sprint engine
            class _Text(BytesIO):
                name = "copy.txt"

            f = _Text(current.encode("utf-8"))

            # Evaluate
            summary, df, fig, clusters = run_sprint(
                file_obj=f,
                segment="All Segments",
                persona_groups=personas,
                return_cluster_df=True,
            )

            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(summary)

            if mean_intent >= threshold:
                passed = True
                break

            # Build targeted feedback for the next revision
            tips = "\n".join(
                f"- Cluster {int(row['cluster'])}: {row['summary']}"
                for _, row in clusters.iterrows()
            )
            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(
                improve_brief,
                fmt="sales_page",
                n=1,
                trait_cfg=trait_cfg,
                traits=traits,
                country="Australia",
                model=model_name,
            )
            current = improved[0].copy if improved else current

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt")
        st.markdown(current)
