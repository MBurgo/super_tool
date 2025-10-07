# app/streamlit/pages/0_Guided_flow.py
# Guided end-to-end flow: find trends -> pick theme -> draft -> synthetic test -> improve

import _bootstrap  # ensures repo root is on sys.path
import os
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import streamlit as st

from adapters.trends_serp_adapter import (
    fetch_trends_and_news,
    fetch_meta_descriptions,
    get_serpapi_key,
)

# sprint_engine location is different across branches; import robustly
try:
    from core.sprint_engine import run_sprint
except Exception:
    from sprint_engine import run_sprint  # type: ignore

# copywriter adapter
from adapters.copywriter_mf_adapter import generate as gen_copy

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# ---------------- Helpers ---------------- #
def _load_json_first(path_candidates):
    for p in path_candidates:
        p = Path(p)
        if p.exists() and p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


def load_personas() -> list[dict]:
    data = _load_json_first(
        ["assets/personas.json", "data/personas.json", "personas.json"]
    )
    if not data:
        st.error(
            "Missing personas. Add **assets/personas.json** (preferred) or **data/personas.json** to the repo."
        )
        return []
    # support both the { "personas": [...] } and raw list variants
    return data.get("personas", data)


def load_traits_cfg() -> dict:
    data = _load_json_first(
        ["assets/traits_config.json", "traits_config.json", "data/traits_config.json"]
    )
    if not data:
        st.error("Missing traits config. Add **assets/traits_config.json**.")
        return {}
    return data


def _serp_key_status() -> bool:
    try:
        key = get_serpapi_key(raise_on_missing=False)
        if key:
            st.caption("🔐 SerpAPI key detected.")
            return True
        st.caption("⚠️ SerpAPI key not detected yet.")
        return False
    except Exception:
        st.caption("⚠️ SerpAPI key not detected yet.")
        return False


# --------------- Step 1: Find trends --------------- #
with st.expander("Step 1 — Find live ASX‑200 trends & news", expanded=True):
    _serp_key_status()
    if st.button("🔎 Fetch trends & news"):
        key = get_serpapi_key(raise_on_missing=True)
        try:
            rising, news = fetch_trends_and_news(key)
        except Exception as e:
            st.error(f"SerpAPI call failed: {e}")
            st.stop()

        # Show a compact preview
        st.write("**Top Rising Queries (Google Trends, AU, last 4h):**")
        for r in rising[:10]:
            st.write(f"- {r.get('query','(n/a)')} — {r.get('value','')}")

        # Pull meta for the first few news links (helps the picker later)
        links = [n.get("link") for n in news[:10] if n.get("link")]
        metas = fetch_meta_descriptions(links) if links else []

        st.session_state["guidance_trends"] = {
            "rising": rising,
            "news": news,
            "news_meta": metas,
        }
        st.success("Fetched latest rising queries and news.")


data = st.session_state.get("guidance_trends")

# --------------- Step 2: Pick a theme --------------- #
if data:
    st.markdown("### Step 2 — Pick a theme to pursue")
    theme_options = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in data["rising"][:10]] or [
        "ASX 200 market moves"
    ]
    choice = st.radio("Top Rising Queries (last 4h, AU)", theme_options, index=0)
    if st.button("✍️ Draft campaign for this theme"):
        st.session_state["chosen_theme"] = choice

# --------------- Step 3: Draft initial copy --------------- #
chosen = st.session_state.get("chosen_theme")
if chosen:
    st.markdown("### Step 3 — Drafting initial variants")
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

    # Default “balanced but lively” traits
    default_traits = {
        "Urgency": 7,
        "Data_Richness": 6,
        "Social_Proof": 6,
        "Comparative_Framing": 5,
        "Imagery": 6,
        "Conversational_Tone": 7,
        "FOMO": 6,
        "Repetition": 4,
    }

    traits_cfg = load_traits_cfg()
    if not traits_cfg:
        st.stop()

    model_name = (
        (st.secrets.get("openai", {}) or {}).get("api_key") and st.secrets.get("openai_model")
    ) or st.secrets.get("OPENAI_MODEL") or "gpt-4.1"

    try:
        variants = gen_copy(
            brief,
            fmt="sales_page",
            n=3,
            trait_cfg=traits_cfg,
            traits=default_traits,
            country="Australia",
            model=model_name,
        )
    except Exception as e:
        st.error(f"Copy generation failed: {e}")
        st.stop()

    texts = [v.copy for v in variants]
    pick = st.radio(
        "Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0
    )
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # --------------- Step 4: Synthetic focus test loop --------------- #
    st.markdown("### Step 4 — Focus‑test across personas & auto‑improve")
    personas = load_personas()
    if not personas:
        st.stop()

    threshold = st.slider(
        "Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1, help="Target average intent score (0–10)."
    )
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False

        for r in range(int(rounds)):
            # wrap text as a small file so sprint_engine can read it
            class _Text(BytesIO):
                name = "copy.txt"

            f = _Text(current.encode("utf-8"))

            try:
                summary, df, fig, clusters = run_sprint(
                    file_obj=f,
                    segment="All Segments",
                    persona_groups=personas,
                    return_cluster_df=True,
                )
            except Exception as e:
                st.error(f"Focus test failed: {e}")
                st.stop()

            mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
            st.plotly_chart(fig, use_container_width=True)
            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Build concise feedback from cluster summaries
            tips = ""
            if clusters is not None and "summary" in clusters.columns:
                tips = "\n".join(
                    f"- Cluster {int(row['cluster'])}: {row['summary']}"
                    for _, row in clusters.iterrows()
                )

            improve_brief = dict(brief)
            improve_brief["quotes_news"] = (
                f"Persona feedback themes to address:\n{tips}" if tips else "Address persona objections and clarity."
            )

            improved = gen_copy(
                improve_brief,
                fmt="sales_page",
                n=1,
                trait_cfg=traits_cfg,
                traits=default_traits,
                country="Australia",
                model=model_name,
            )
            current = improved[0].copy

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
