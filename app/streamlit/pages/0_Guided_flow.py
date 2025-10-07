# app/streamlit/pages/0_Guided_flow.py
import _bootstrap  # ensures project root is on sys.path
from io import BytesIO
from pathlib import Path
import json
import numpy as np
import streamlit as st

# Trends adapter (exports all needed functions)
from adapters.trends_serp_adapter import (
    get_serpapi_key,
    fetch_trends_and_news,
    enrich_news_with_meta,
)

# Copywriter adapter
from adapters.copywriter_mf_adapter import generate as gen_copy

# Sprint / synthetic focus imports (robust fallbacks)
try:
    from core.sprint_engine import run_sprint
except Exception:
    try:
        from sprint_engine import run_sprint
    except Exception:
        run_sprint = None

try:
    from core.tmf_synth_utils import load_personas
except Exception:
    try:
        from tmf_synth_utils import load_personas
    except Exception:
        load_personas = None

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# ---- Locate required assets ----
assets_dir = Path("assets")
traits_path_candidates = [assets_dir / "traits_config.json", Path("traits_config.json")]
personas_path_candidates = [assets_dir / "personas.json", Path("personas.json")]

traits_path = next((p for p in traits_path_candidates if p.exists()), None)
personas_path = next((p for p in personas_path_candidates if p.exists()), None)

if not traits_path:
    st.error("Missing traits config at **assets/traits_config.json**. Add that file to the repo.")
if not personas_path:
    st.error("Missing personas at **assets/personas.json**. Add that file to the repo.")

# ---- Get SerpAPI key (env or secrets) ----
serp_key = get_serpapi_key()
if serp_key is None:
    st.warning("SerpAPI key not found. Set env **SERPAPI_API_KEY** or add in secrets as `[serpapi] api_key=\"...\"`.")

# ---- 1) Kick off trend finder ----
if st.button("🔎 Find live trends & news", disabled=serp_key is None):
    try:
        rising, news = fetch_trends_and_news(serp_key)
        news = enrich_news_with_meta(news)
        # Build top 10 rising themes
        themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in (rising or [])[:10]]
        st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}
    except Exception as e:
        st.error(f"Trend fetch failed: {e}")

data = st.session_state.get("guidance_trends")
if data:
    st.subheader("Pick a theme to pursue")
    if data["themes"]:
        choice = st.radio("Top Rising Queries (last 4h AU)", data["themes"], index=0)
    else:
        st.info("No rising queries from SerpAPI. You can still proceed by typing a theme manually.")
        choice = st.text_input("Enter a theme", "ASX 200 rally")

    if st.button("✍️ Draft initial campaign for this theme"):
        st.session_state["chosen_theme"] = choice

chosen = st.session_state.get("chosen_theme")
if chosen and traits_path and personas_path:
    # ---- 2) Generate initial variants ----
    st.subheader("Drafting campaign variants…")
    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0] if " — " in chosen else chosen,
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "",
        "retail_price": "",
        "offer_term": "",
        "reports": "",
        "stocks_to_tease": "",
        "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)",
    }
    traits_cfg = json.loads(traits_path.read_text(encoding="utf-8"))
    default_traits = {
        "Urgency": 7, "Data_Richness": 6, "Social_Proof": 6,
        "Comparative_Framing": 5, "Imagery": 6, "Conversational_Tone": 7,
        "FOMO": 6, "Repetition": 4,
    }

    variants = gen_copy(
        brief, fmt="sales_page", n=3,
        trait_cfg=traits_cfg, traits=default_traits,
        country="Australia",
        model=st.secrets.get("openai_model", "gpt-4.1") if hasattr(st, "secrets") else "gpt-4.1"
    )

    texts = [v.copy for v in variants] if variants else []
    if not texts:
        st.error("No draft variants were generated.")
    else:
        pick = st.radio("Choose a base variant", [f"Variant {i+1}" for i in range(len(texts))], index=0)
        idx = int(pick.split()[-1]) - 1
        base_text = texts[idx]
        st.markdown(base_text)

        # ---- 3) Focus-test loop (auto revise until pass) ----
        # Load personas
        if load_personas is not None:
            personas = load_personas(str(personas_path))
        else:
            # Minimal fallback loader
            pdata = json.loads(personas_path.read_text(encoding="utf-8"))
            personas = pdata["personas"]

        threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
        rounds = st.number_input("Max revision rounds", 1, 5, 3)

        if run_sprint is None:
            st.error("`run_sprint` not found. Ensure `core/sprint_engine.py` (or `sprint_engine.py`) exists and is importable.")
        else:
            if st.button("🧪 Run focus test + auto‑improve"):
                current = base_text
                passed = False
                for r in range(int(rounds)):
                    # Wrap text like a file object for sprint_engine
                    class _Text(BytesIO):
                        name = "copy.txt"
                    f = _Text(current.encode("utf-8"))

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

                    # Build concise feedback brief to improve copy
                    tips = "\n".join(
                        [f"- Cluster {int(c['cluster'])}: {c['summary']}" for _, c in clusters.iterrows()]
                    )
                    improve_brief = dict(brief)
                    improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

                    improved = gen_copy(
                        improve_brief, fmt="sales_page", n=1,
                        trait_cfg=traits_cfg, traits=default_traits,
                        country="Australia",
                        model=st.secrets.get("openai_model", "gpt-4.1") if hasattr(st, "secrets") else "gpt-4.1"
                    )
                    current = improved[0].copy if improved else current

                st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
                st.markdown(current)
else:
    if not st.session_state.get("guidance_trends"):
        st.info("Click **Find live trends & news** to begin.")
