# app/streamlit/pages/0_Guided_flow.py
import _bootstrap
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import streamlit as st

# ── External adapters (SERP-based trend finder, copywriter) ───────────
from adapters.trends_serp_adapter import fetch_trends_and_news
from adapters.copywriter_mf_adapter import generate as gen_copy

# ── Sprint engine (try packaged path first, then flat fallback) ────────
try:
    from core.sprint_engine import run_sprint
except Exception:
    from sprint_engine import run_sprint  # flat layout fallback

# ───────────────────────────────────────────────────────────────────────
# Helpers (local loaders, robust secrets discovery)
# ───────────────────────────────────────────────────────────────────────
def _find_serp_key() -> str | None:
    # Try Streamlit secrets (nested and flat) then environment
    try:
        if "serpapi" in st.secrets and "api_key" in st.secrets["serpapi"]:
            return st.secrets["serpapi"]["api_key"]
    except Exception:
        pass
    try:
        if "SERPAPI_API_KEY" in st.secrets:
            return st.secrets["SERPAPI_API_KEY"]
        if "SERP_API_KEY" in st.secrets:
            return st.secrets["SERP_API_KEY"]
    except Exception:
        pass

    import os
    return os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY")


def _load_personas_from_repo() -> list[dict]:
    """
    Looks for personas.json in the repo so the page doesn't require uploads.
    Priority:
      1) assets/personas.json
      2) data/personas.json
      3) personas.json (repo root)
    """
    candidates = [
        Path("assets/personas.json"),
        Path("data/personas.json"),
        Path("personas.json"),
    ]
    for p in candidates:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("personas") or data  # support both shapes
    raise FileNotFoundError(
        "No personas.json found. Commit one of: "
        "assets/personas.json, data/personas.json, or repo-root personas.json."
    )


def _load_traits_cfg() -> dict:
    """
    Reads traits_config.json with failover so we’re resilient to where you keep it.
    Priority:
      1) assets/traits_config.json
      2) traits_config.json (repo root)
    """
    for p in [Path("assets/traits_config.json"), Path("traits_config.json")]:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "Missing traits config. Commit assets/traits_config.json "
        "or traits_config.json at the repo root."
    )


# ───────────────────────────────────────────────────────────────────────
# Page UI
# ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# 1) Kick off trend finder
if st.button("🔎 Find live trends & news", type="primary"):
    serp_key = _find_serp_key()
    if not serp_key:
        st.error(
            "SerpAPI key not found. Add to Streamlit secrets as "
            '`[serpapi]\napi_key="..."` or set the SERPAPI_API_KEY env var.'
        )
    else:
        rising, news = fetch_trends_and_news(serp_key)
        # Keep a compact list of themes (top 10 rising queries)
        themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in (rising or [])[:10]]
        st.session_state["guidance_trends"] = {"rising": rising or [], "news": news or [], "themes": themes}

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    if not data["themes"]:
        st.warning("No rising queries returned. Try again in a moment.")
    else:
        choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
        if st.button("✍️ Draft campaign for this theme"):
            st.session_state["chosen_theme"] = choice

# 2) Generate initial variants for chosen theme
chosen = st.session_state.get("chosen_theme")
if chosen:
    st.subheader("Drafting campaign variants…")

    try:
        trait_cfg = _load_traits_cfg()
    except Exception as e:
        st.error(str(e))
        st.stop()

    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "", "retail_price": "", "offer_term": "",
        "reports": "", "stocks_to_tease": "", "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)",
    }
    traits = {"Urgency": 7, "Data_Richness": 6, "Social_Proof": 6,
              "Comparative_Framing": 5, "Imagery": 6,
              "Conversational_Tone": 7, "FOMO": 6, "Repetition": 4}

    # Generate 3 variants via the copywriter adapter
    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=trait_cfg, traits=traits,
        country="Australia",
        model=st.secrets.get("openai_model", "gpt-4.1")
    )

    texts = [v.copy for v in variants] if variants else []
    if not texts:
        st.error("The copywriter returned no variants. Check your OpenAI key and model.")
        st.stop()

    pick = st.radio(
        "Choose a base variant",
        [f"Variant {i+1}" for i in range(len(texts))],
        index=0
    )
    idx = int(pick.split()[-1]) - 1
    base_text = texts[idx]
    st.markdown(base_text)

    # 3) Focus-test loop (auto-revise until pass)
    try:
        personas = _load_personas_from_repo()
    except Exception as e:
        st.error(str(e))
        st.stop()

    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if st.button("🧪 Run focus test + auto‑improve"):
        current = base_text
        passed = False

        for r in range(int(rounds)):
            # Wrap current copy as a file-like object for sprint_engine
            f = BytesIO(current.encode("utf-8"))
            f.name = "copy.txt"  # sprint_engine.extract_text expects a .name

            summary, df, fig, clusters = run_sprint(
                file_obj=f,
                segment="All Segments",
                persona_groups=personas,
                return_cluster_df=True,
            )

            mean_intent = float(np.mean(df["intent"])) if (df is not None and not df.empty) else 0.0
            st.plotly_chart(fig, use_container_width=True)
            st.write(summary)
            st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

            if mean_intent >= threshold:
                passed = True
                break

            # Build short feedback brief from cluster summaries to improve copy
            if clusters is not None and not clusters.empty:
                tips = "\n".join(
                    [f"- Cluster {int(row['cluster'])}: {row['summary']}" for _, row in clusters.iterrows()]
                )
            else:
                tips = "- (No cluster summaries available; improve clarity and benefits emphasis.)"

            improve_brief = dict(brief)
            improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

            improved = gen_copy(
                improve_brief, fmt="sales_page", n=1,
                trait_cfg=trait_cfg, traits=traits,
                country="Australia",
                model=st.secrets.get("openai_model", "gpt-4.1")
            )
            if improved:
                current = improved[0].copy
            else:
                st.warning("Improver returned no text—continuing with last best draft.")
                break

        st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
        st.markdown(current)
