# app/streamlit/pages/0_Guided_flow.py
import _bootstrap
import os, json, pathlib
from io import BytesIO

import numpy as np
import streamlit as st

# Trends adapter (fixed)
from adapters.trends_serp_adapter import (
    get_serpapi_key,
    fetch_trends_and_news,
    fetch_meta_descriptions,   # now exported by the adapter
    enrich_news_with_meta,
)

# Robust imports for sprint engine + personas loader
try:
    from core.sprint_engine import run_sprint  # preferred location
except Exception:
    try:
        from sprint_engine import run_sprint   # flat repo fallback
    except Exception:
        run_sprint = None

def _local_load_personas(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # supports both {"personas":[...]} and raw list
    return data["personas"] if isinstance(data, dict) and "personas" in data else data

try:
    from core.tmf_synth_utils import load_personas  # preferred
except Exception:
    try:
        from tmf_synth_utils import load_personas   # flat fallback
    except Exception:
        load_personas = _local_load_personas

# UI
st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# 0) Pre-flight checks
traits_path = pathlib.Path("assets/traits_config.json")
personas_path = pathlib.Path("assets/personas.json")

if not traits_path.exists():
    st.error("Missing traits config at assets/traits_config.json.")
    st.stop()
if not personas_path.exists():
    st.error("Missing personas at assets/personas.json.")
    st.stop()
if run_sprint is None:
    st.error("Missing sprint engine module. Expected core/sprint_engine.py or sprint_engine.py at repo root.")
    st.stop()

# 1) Kick off trend finder
if st.button("🔎 Find live ASX trends & news"):
    try:
        serp_key = get_serpapi_key()
    except Exception as e:
        st.error(str(e))
        st.stop()

    rising, news = fetch_trends_and_news(serp_key, query="ASX 200")
    news = enrich_news_with_meta(news)

    # Build theme labels from top rising queries
    themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in (rising or [])[:10]]

    st.session_state["guidance_trends"] = {
        "rising": rising,
        "news": news,
        "themes": themes or ["(no rising queries found)"],
    }

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    st.write("Recent headlines (first ~10):")
    # small table of titles + meta
    if data["news"]:
        tbl = [
            {
                "Title": n.get("title", ""),
                "Source": (n.get("source") or {}).get("name", ""),
                "Meta": n.get("meta_description") or n.get("snippet") or "",
            }
            for n in data["news"][:10]
        ]
        st.dataframe(tbl, use_container_width=True, hide_index=True)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

chosen = st.session_state.get("chosen_theme")
if chosen:
    st.subheader("Drafting campaign variants…")

    # 2) Generate initial variants
    brief = {
        "id": "guided",
        "hook": (chosen.split(" — ")[0] if " — " in chosen else chosen),
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "",
        "retail_price": "",
        "offer_term": "",
        "reports": "",
        "stocks_to_tease": "",
        "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)",
    }
    with open(traits_path, "r", encoding="utf-8") as f:
        trait_cfg = json.load(f)
    default_traits = {
        "Urgency": 7, "Data_Richness": 6, "Social_Proof": 6,
        "Comparative_Framing": 5, "Imagery": 6,
        "Conversational_Tone": 7, "FOMO": 6, "Repetition": 4,
    }

    # lazy import to keep page snappy
    from adapters.copywriter_mf_adapter import generate as gen_copy

    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=trait_cfg, traits=default_traits,
        country="Australia",
        model=st.secrets.get("openai_model", "gpt-4.1"),
    )

    texts = [v.copy for v in variants] if variants else []
    if not texts:
        st.error("No copy variants returned. Check OpenAI API key and logs.")
        st.stop()

    pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # 3) Focus-test loop (auto-revise until pass)
    personas = load_personas(str(personas_path))
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False

        class _TextFile(BytesIO):
            def __init__(self, b: bytes):
                super().__init__(b)
                self.name = "copy.txt"

        for r in range(int(rounds)):
            f = _TextFile(current.encode("utf-8"))

            summary, df, fig, clusters = run_sprint(
                file_obj=f,
                segment="All Segments",
                persona_groups=personas,
                return_cluster_df=True,
            )
            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
            st.plotly_chart(fig, use_container_width=True)
            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Use cluster summaries to drive a revision
            tips = "\n".join([f"- Cluster {int(c['cluster'])}: {c['summary']}" for _, c in clusters.iterrows()])
            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(
                improve_brief, fmt="sales_page", n=1,
                trait_cfg=trait_cfg, traits=default_traits,
                country="Australia",
                model=st.secrets.get("openai_model", "gpt-4.1"),
            )
            current = improved[0].copy if improved else current

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
