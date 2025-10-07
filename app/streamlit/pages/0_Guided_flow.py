# app/streamlit/pages/0_Guided_flow.py
import _bootstrap  # ensures project root is on sys.path
import os
from io import BytesIO
from pathlib import Path
import json
import numpy as np
import streamlit as st

import adapters.trends_serp_adapter as serp_adapter
from adapters.trends_serp_adapter import (
    get_serpapi_key,
    serp_key_diagnostics,
    fetch_trends_and_news,
    enrich_news_with_meta,
)

from adapters.copywriter_mf_adapter import generate as gen_copy
from core.sprint_engine import run_sprint

st.set_page_config(page_title="Guided Flow", page_icon="🧭", layout="wide")
st.title("Guided Flow: Trends → Variants → Synthetic Focus → Finalise")
st.caption("Live AU finance trends, draft copy, iterate with synthetic personas until intent target is met.")

# ---- Locate required assets ----
assets_dir = Path("assets")
traits_path_candidates = [
    assets_dir / "traits_config.json",
    Path("traits_config.json"),
    Path("data/traits_config.json"),
]
personas_path_candidates = [
    assets_dir / "personas.json",
    Path("personas.json"),
    Path("data/personas.json"),
]

traits_path = next((p for p in traits_path_candidates if p.exists()), None)
personas_path = next((p for p in personas_path_candidates if p.exists()), None)

if not traits_path:
    st.error("Missing traits config. Looked for assets/traits_config.json, ./traits_config.json, and data/traits_config.json.")
if not personas_path:
    st.error("Missing personas. Looked for assets/personas.json, ./personas.json, and data/personas.json.")

# Load trait config
traits_cfg = {}
default_traits = {}
try:
    if traits_path and traits_path.exists():
        traits_cfg = json.loads(traits_path.read_text(encoding="utf-8"))
        default_traits = {k: v.get("default","") for k, v in traits_cfg.get("traits", {}).items()}
except Exception as e:
    st.warning(f"Traits config read issue: {e}")

# Helper to recompute key each render
def _current_serp_key() -> str | None:
    k = get_serpapi_key()
    st.session_state["serpapi_key_present"] = bool(k and k.strip())
    return k

with st.expander("Live Trends & News", expanded=True):
    st.caption("Uses SerpAPI: Google Trends (rising related queries) and Google News for AU within your chosen window.")

    # Always recompute, no stale caching
    serp_key = _current_serp_key()

    colA, colB = st.columns([1, 1])
    with colA:
        st.write("SerpAPI status:", "✅ key found" if serp_key else "❌ no key")
    with colB:
        if st.button("🔄 Recheck key"):
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()

    # Visible, non-leaky diagnostics so you can prove what's loading
    diag = serp_key_diagnostics()
    st.markdown("**Key detection diagnostic (never shows values):**")
    st.code(
        json.dumps(
            {
                "adapter_version": diag.get("adapter_version"),
                "module_path": diag.get("module_path"),
                "env_value_lengths": diag.get("env_value_lengths"),
                "secrets_value_lengths": diag.get("secrets_value_lengths"),
            },
            indent=2,
        ),
        language="json",
    )
    st.caption("If `[serpapi].api_key` length > 0 here, the app can read your key from Streamlit Secrets.")

    query = st.text_input("Search theme for news & trends", "asx 200")
    news_when = st.selectbox("Time window for news", ["4h", "1d", "7d"], index=0)

    # Allow running even if the status line says no key; the fetch will re-check and error clearly if missing
    if st.button("🔎 Find live trends & news"):
        try:
            rising, news = fetch_trends_and_news(serp_key, query=query, news_when=news_when)
            news = enrich_news_with_meta(news)
            themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in (rising or [])[:10]]
            st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}
        except Exception as e:
            st.error(f"Trend fetch failed: {e}")
            st.stop()

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    if data["themes"]:
        choice = st.radio("Top Rising Queries (AU)", data["themes"], index=0)
        chosen_theme = choice.split(" — ")[0]
    else:
        st.info("No rising queries from SerpAPI. You can still proceed by typing a theme manually.")
        chosen_theme = st.text_input("Enter a theme", "ASX 200 rally")

    if st.button("✍️ Draft initial campaign for this theme"):
        st.session_state["chosen_theme"] = chosen_theme

chosen = st.session_state.get("chosen_theme")
if chosen and traits_path and personas_path:
    # ---- 2) Generate initial variants ----
    st.subheader("Drafting campaign variants…")
    brief = {
        "id": "guided",
        "theme": chosen,
        "hook": f"Investing insights tied to {chosen}",
        "details": "Retail investor friendly, educational tone, actionable guidance.",
        "offer_price": "$99",
        "offer_term": "12 months",
        "reports": "New member report bundle",
        "stocks_to_tease": "2–3 ASX names",
        "quotes_news": "",
        "structure": "Hook, Problem, Insight, Proof, Offer, CTA",
        "requirements": "Avoid promises. Emphasise risk and education. Include price and term.",
    }

    col1, col2 = st.columns([1, 2])
    with col1:
        length_choice = st.selectbox(
            "Length",
            ["📏 Short (100–200 words)", "📐 Medium (200–500 words)", "📖 Long (500–1500 words)"],
            index=1,
        )
        n_variants = st.slider("Number of variants", 1, 5, 3)

    with col2:
        st.caption("Traits to emphasise (optional)")
        t_sel = {}
        for k, v in (traits_cfg.get("traits", {}) or {}).items():
            if isinstance(v, dict) and "options" in v:
                t_sel[k] = st.selectbox(k, v["options"], index=0)
            else:
                t_sel[k] = st.text_input(k, value=str(default_traits.get(k, "")))
        traits_in_use = t_sel or default_traits

    with st.spinner("Calling copywriter…"):
        variants = gen_copy(
            brief, fmt="sales_page", n=n_variants, trait_cfg=traits_cfg, traits=traits_in_use, country="Australia"
        )

    if not variants:
        st.error("Copywriter returned no variants.")
    else:
        idx = st.radio(
            "Pick a base variant",
            [f"Variant {i+1}" for i in range(len(variants))],
            index=0,
            horizontal=True,
        )
        base_index = int(idx.split()[-1]) - 1
        base = variants[base_index]
        st.markdown("### Selected base variant")
        base_text = base.copy
        st.markdown(base_text)

        # ---- 3) Focus-test loop (auto revise until pass) ----
        personas = json.loads(personas_path.read_text(encoding="utf-8")).get("personas", [])

        threshold = st.slider("Passing mean intent threshold", 6.0, 9.5, 7.5, 0.1)
        rounds = st.number_input("Max revision rounds", 1, 5, 3)

        if st.button("🧪 Run focus test + auto‑improve"):
            current = base_text
            passed = False
            for r in range(int(rounds)):
                class _Text(BytesIO):
                    name = "copy.txt"
                f = _Text(current.encode("utf-8"))

                summary, df, fig, clusters = run_sprint(
                    file_obj=f,
                    segment="All Segments",
                    persona_groups=personas,
                    progress_cb=st.progress(0.0),
                    return_cluster_df=True,
                )

                st.plotly_chart(fig, use_container_width=True)
                st.markdown(summary)

                mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
                st.write(f"Mean intent this round: **{mean_intent:.2f}/10**")
                if mean_intent >= float(threshold):
                    passed = True
                    break

                if clusters:
                    worst = min(clusters, key=clusters.get)
                else:
                    worst = 0
                worst_rows = df[df["cluster"] == worst].sort_values("intent").head(5)
                bullets = "\n".join([f"- {t}" for t in worst_rows["feedback"].tolist()])

                improve_brief = {
                    **brief,
                    "structure": "Keep same structure but address the critique points explicitly.",
                    "quotes_news": f"Persona critique to address:\n{bullets}",
                }

                improved = gen_copy(
                    improve_brief, fmt="sales_page", n=1,
                    trait_cfg=traits_cfg, traits=traits_in_use,
                    country="Australia",
                )
                current = improved[0].copy if improved else current

            st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
            st.markdown(current)
else:
    if not st.session_state.get("guidance_trends"):
        st.info("Click **Find live trends & news** to begin.")
