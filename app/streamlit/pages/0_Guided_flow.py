# app/streamlit/pages/0_Guided_flow.py
import _bootstrap  # ensures repo root is on sys.path
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import streamlit as st

# Trends adapter (exports all needed functions)
from adapters.trends_serp_adapter import (
    get_serpapi_key,
    fetch_trends_and_news,
    enrich_news_with_meta,
)

# Copywriter
from adapters.copywriter_mf_adapter import generate as gen_copy

# Synthetic focus test engine + personas loader
try:
    from core.sprint_engine import run_sprint
except Exception:
    from sprint_engine import run_sprint  # fallback if file sits at repo root

try:
    from core.tmf_synth_utils import load_personas
except Exception:
    from tmf_synth_utils import load_personas  # fallback

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

st.caption(
    "Find live AU trends + news using SerpAPI, draft variants, then auto‑iterate "
    "through the synthetic persona focus test until the copy meets your threshold."
)

# ---- Step 1. Pull live trends/news
if st.button("🔎 Find live trends & news"):
    try:
        serp_key = get_serpapi_key()
    except Exception as e:
        st.error(str(e))
        st.stop()

    rising, news = fetch_trends_and_news(serp_key, query="ASX 200")
    news = enrich_news_with_meta(news)

    # Build quick pick-list from rising queries
    themes = []
    for r in rising[:10]:
        q = r.get("query", "").strip() or "(n/a)"
        val = r.get("value", "")
        themes.append(f"{q} — {val}")

    st.session_state["guidance_trends"] = {
        "rising": rising,
        "news": news,
        "themes": themes,
    }

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

# ---- Step 2. Generate variants for chosen theme
chosen = st.session_state.get("chosen_theme")
if chosen:
    st.subheader("Drafting campaign variants…")
    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "", "retail_price": "", "offer_term": "",
        "reports": "", "stocks_to_tease": "",
        "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)",
    }

    # Trait config + default sliders
    trait_cfg_path = Path("assets/traits_config.json")
    if not trait_cfg_path.exists():
        st.error("Missing traits config at assets/traits_config.json. Add it to the repo.")
        st.stop()
    trait_cfg = json.loads(trait_cfg_path.read_text(encoding="utf-8"))
    traits = {
        "Urgency": 7, "Data_Richness": 6, "Social_Proof": 6,
        "Comparative_Framing": 5, "Imagery": 6,
        "Conversational_Tone": 7, "FOMO": 6, "Repetition": 4
    }

    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=trait_cfg, traits=traits,
        country="Australia", model=st.secrets.get("openai_model", "gpt-4.1")
    )

    texts = [v.copy for v in variants]
    pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # ---- Step 3. Focus-test loop (auto-revise until pass)
    personas_path = Path("assets/personas.json")
    if not personas_path.exists():
        st.error("Missing personas at assets/personas.json. Add your personas file to the repo.")
        st.stop()

    personas = load_personas(str(personas_path))
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False

        for r in range(int(rounds)):
            # Wrap text as a small file-like object so sprint_engine can read it
            class _Text(BytesIO):
                name = "copy.txt"

            f = _Text(current.encode("utf-8"))

            summary, df, fig, clusters = run_sprint(
                file_obj=f, segment="All Segments", persona_groups=personas,
                return_cluster_df=True,
            )
            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
            st.plotly_chart(fig, use_container_width=True)
            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Build a short feedback brief from cluster summaries to improve copy
            tips = "\n".join(
                [f"- Cluster {int(row['cluster'])}: {row['summary']}" for _, row in clusters.iterrows()]
            )
            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(
                improve_brief, fmt="sales_page", n=1,
                trait_cfg=trait_cfg, traits=traits,
                country="Australia", model=st.secrets.get("openai_model", "gpt-4.1")
            )
            current = improved[0].copy

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
