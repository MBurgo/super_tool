# app/streamlit/pages/0_Guided_Flow.py
import _bootstrap
import streamlit as st
from io import BytesIO
import numpy as np

from adapters.trends_serp_adapter import fetch_trends_and_news, fetch_meta_descriptions
from adapters.copywriter_mf_adapter import generate as gen_copy
from sprint_engine import run_sprint
from tmf_synth_utils import load_personas

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# 1) Kick off trend finder
if st.button("🔎 Find live trends & news"):
    serp_key = st.secrets["serpapi"]["api_key"]
    rising, news = fetch_trends_and_news(serp_key)

    # Quick theme list from rising queries
    themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in rising[:10]]
    st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

chosen = st.session_state.get("chosen_theme")
if chosen:
    # 2) Generate initial variants
    st.subheader("Drafting campaign variants…")
    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "", "retail_price": "", "offer_term": "",
        "reports": "", "stocks_to_tease": "", "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)"
    }
    traits = {"Urgency":7, "Data_Richness":6, "Social_Proof":6,
              "Comparative_Framing":5, "Imagery":6,
              "Conversational_Tone":7, "FOMO":6, "Repetition":4}
    import json, pathlib
    trait_cfg = json.loads(pathlib.Path("assets/traits_config.json").read_text())

    variants = gen_copy(brief, fmt="sales_page", n=3,
                        trait_cfg=trait_cfg, traits=traits,
                        country="Australia", model=st.secrets.get("openai_model","gpt-4.1"))
    texts = [v.copy for v in variants]
    pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # 3) Focus-test loop (auto-revise until pass)
    personas = load_personas("assets/personas.json")
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False
        for r in range(int(rounds)):
            # wrap text as a small file so sprint_engine can read it
            class _Text(BytesIO): name="copy.txt"
            f = _Text(current.encode("utf-8"))

            summary, df, fig, clusters = run_sprint(
                file_obj=f, segment="All Segments", persona_groups=personas, return_cluster_df=True
            )
            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
            st.plotly_chart(fig, use_container_width=True)
            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Build a short feedback brief from cluster summaries to improve copy
            tips = "\n".join([f"- Cluster {int(c['cluster'])}: {c['summary']}" for _, c in clusters.iterrows()])
            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(improve_brief, fmt="sales_page", n=1,
                                trait_cfg=trait_cfg, traits=traits,
                                country="Australia", model=st.secrets.get("openai_model","gpt-4.1"))
            current = improved[0].copy

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
