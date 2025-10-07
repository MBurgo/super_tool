# app/streamlit/pages/0_Guided_Flow.py
import _bootstrap
import os
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import streamlit as st

# Robust SerpAPI + meta fetch
from adapters.trends_serp_adapter import (
    fetch_trends_and_news,
    fetch_meta_descriptions,
    get_serp_api_key,
)

# Copywriter + focus group
from adapters.copywriter_mf_adapter import generate as gen_copy

# sprint_engine / tmf_synth_utils can live under core/ or project root; import defensively
try:
    from core.sprint_engine import run_sprint
except Exception:
    from sprint_engine import run_sprint

try:
    from core.tmf_synth_utils import load_personas
except Exception:
    from tmf_synth_utils import load_personas


st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────
def load_json_safely(path_candidates):
    for p in path_candidates:
        p = Path(p)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None

def load_trait_cfg():
    data = load_json_safely(["assets/traits_config.json", "traits_config.json"])
    if not data:
        # Minimal safe defaults if file missing
        return {
            "Urgency": {"high_threshold": 8, "low_threshold": 3,
                        "high_rule": "- Include an explicit deadline in headline and CTA.",
                        "mid_rule": "- Refer to timing once, no countdowns.",
                        "low_rule": "- Avoid urgency and scarcity."},
            "Data_Richness": {"high_threshold": 7, "low_threshold": 3,
                              "high_rule": "- Cite at least one numeric figure.",
                              "mid_rule": "- One light data point allowed.",
                              "low_rule": "- Avoid stats and percentages."},
        }
    return data

def load_personas_from_repo():
    # Uses your committed file (recommended to avoid secrets headaches)
    # You already committed assets/personas.json earlier.
    return load_personas("assets/personas.json")


# ────────────────────────────────────────────────────────────────────
# Non-sensitive key diagnostics (does not print secrets)
# ────────────────────────────────────────────────────────────────────
def has_serp_key_in_secrets() -> bool:
    try:
        sec = getattr(st, "secrets", None)
        if not sec:
            return False
        if "serpapi" in sec and isinstance(sec["serpapi"], dict):
            return bool(sec["serpapi"].get("api_key") or sec["serpapi"].get("API_KEY") or sec["serpapi"].get("key"))
        # flat key variants
        return any(k in sec for k in ("SERPAPI_API_KEY", "SERP_API_KEY", "serpapi_api_key", "serp_api_key"))
    except Exception:
        return False

def has_serp_key_in_env() -> bool:
    return bool(os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY"))

with st.expander("⚙️ Debug (safe)"):
    s_ok = has_serp_key_in_secrets()
    e_ok = has_serp_key_in_env()
    st.markdown(
        f"SerpAPI in **secrets**: "
        f"{'✅ found' if s_ok else '⬜ not found'} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"SerpAPI in **env**: {'✅ found' if e_ok else '⬜ not found'}"
    )

# ────────────────────────────────────────────────────────────────────
# 1) Kick off trend finder
# ────────────────────────────────────────────────────────────────────
if st.button("🔎 Find live trends & news"):
    try:
        serp_key = get_serp_api_key()  # robust resolver (secrets or env)
        rising, news = fetch_trends_and_news(serp_key)
        # Fetch meta descriptions for better summaries
        urls = [n.get("link") for n in news if n.get("link")]
        metas = asyncio.run(fetch_meta_descriptions(urls)) if urls else []
        for n, m in zip(news, metas):
            n["fetched_meta"] = m

        themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in (rising or [])[:10]]
        st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}
        st.success("Fetched fresh rising queries & news.")
    except Exception as e:
        st.error(str(e))

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

# ────────────────────────────────────────────────────────────────────
# 2) Generate initial variants
# ────────────────────────────────────────────────────────────────────
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
    traits_cfg = load_trait_cfg()
    traits = {"Urgency":7, "Data_Richness":6, "Social_Proof":6,
              "Comparative_Framing":5, "Imagery":6,
              "Conversational_Tone":7, "FOMO":6, "Repetition":4}

    # model name pulled from secrets or default
    model_name = st.secrets.get("openai_model", "gpt-4.1") if hasattr(st, "secrets") else "gpt-4.1"

    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=traits_cfg, traits=traits,
        country="Australia", model=model_name
    )
    texts = [v.copy for v in variants]

    pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # ────────────────────────────────────────────────────────────────
    # 3) Focus-test loop (auto-revise until pass)
    # ────────────────────────────────────────────────────────────────
    personas = load_personas_from_repo()
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False

        for r in range(int(rounds)):
            # wrap text as a file-like for run_sprint
            f = BytesIO(current.encode("utf-8"))
            f.name = "copy.txt"

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

            improved = gen_copy(
                improve_brief, fmt="sales_page", n=1,
                trait_cfg=traits_cfg, traits=traits,
                country="Australia", model=model_name
            )
            current = improved[0].copy

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
