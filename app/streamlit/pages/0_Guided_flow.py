# app/streamlit/pages/0_Guided_flow.py
import _bootstrap  # ensures project root is on sys.path
import sys
import importlib
from io import BytesIO
from pathlib import Path
import json
import numpy as np
import streamlit as st

st.set_page_config(page_title="Guided Flow", page_icon="🧭", layout="wide")
st.title("Guided Flow: Trends → Variants → Synthetic Focus → Finalise")
st.caption("Live AU finance trends, draft copy, iterate with synthetic personas until the intent target is met.")

# ---- Runtime / import helpers ----
with st.expander("Runtime info", expanded=False):
    st.write({"python_version": sys.version})

def _lazy_import(name: str):
    try:
        mod = importlib.import_module(name)
        return mod, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

serp_adapter, serp_err = _lazy_import("adapters.trends_serp_adapter")
if serp_err:
    st.error("Failed to import adapters.trends_serp_adapter")
    st.code(serp_err)
    st.stop()

copy_adapter, copy_err = _lazy_import("adapters.copywriter_mf_adapter")
if copy_err:
    st.error("Failed to import adapters.copywriter_mf_adapter")
    st.code(copy_err)
    st.stop()

sprint_engine, sprint_err = _lazy_import("core.sprint_engine")
if sprint_err:
    st.error("Failed to import core.sprint_engine")
    st.code(sprint_err)
    st.stop()

theme_engine, theme_err = _lazy_import("core.news_theme_engine")
if theme_err:
    st.error("Failed to import core.news_theme_engine")
    st.code(theme_err)
    st.stop()

get_serpapi_key = getattr(serp_adapter, "get_serpapi_key")
serp_key_diagnostics = getattr(serp_adapter, "serp_key_diagnostics")
fetch_trends_and_news = getattr(serp_adapter, "fetch_trends_and_news")
enrich_news_with_meta = getattr(serp_adapter, "enrich_news_with_meta")
gen_copy = getattr(copy_adapter, "generate")
run_sprint = getattr(sprint_engine, "run_sprint")
analyze_news_to_themes = getattr(theme_engine, "analyze_news_to_themes")

with st.expander("Import diagnostics", expanded=False):
    st.write({
        "adapter_module_path": getattr(serp_adapter, "__file__", "n/a"),
        "adapter_version": getattr(serp_adapter, "ADAPTER_VERSION", "n/a"),
        "theme_engine_path": getattr(theme_engine, "__file__", "n/a"),
    })

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

# ---- Trends & News panel ----
with st.expander("Live Trends & News", expanded=True):
    st.caption("Uses SerpAPI for Google News and Trends, then clusters headlines to produce analyst-grade themes for AU finance.")
    serp_key = get_serpapi_key()
    colA, colB = st.columns([1, 1])
    with colA:
        st.write("SerpAPI status:", "✅ key found" if serp_key else "❌ no key")
    with colB:
        if st.button("🔄 Recheck key"):
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()

    diag = {}
    try:
        diag = serp_key_diagnostics()
    except Exception:
        diag = {}
    st.markdown("**Key detection diagnostic (never shows values):**")
    st.code(json.dumps(diag, indent=2), language="json")

    # Inputs
    query = st.text_input("Search theme for news & trends", "asx 200")
    news_when = st.selectbox("Time window for news", ["4h", "1d", "7d"], index=2)

    # Fetch
    if st.button("🔎 Find live trends & news"):
        try:
            rising, news = fetch_trends_and_news(serp_key, query=query, news_when=news_when)
            news = enrich_news_with_meta(news)
            st.session_state["raw_news"] = news
            st.session_state["raw_rising"] = rising

            # NEW: analyze into proper themes
            # Use LLM if OpenAI key is configured through your existing call_gpt_json wrapper
            themes = analyze_news_to_themes(news, rising, country="Australia", top_k=None, use_llm=True, model="gpt-4o-mini")
            st.session_state["themes"] = themes

        except Exception as e:
            st.error(f"Trend fetch failed: {type(e).__name__}: {e}")
            st.stop()

# ---- Theme selection ----
themes = st.session_state.get("themes", [])
news = st.session_state.get("raw_news", [])
if themes:
    st.subheader("Pick a theme to pursue")

    labels = [f"{t['query']}  ·  {int(t['score'])} articles" for t in themes]
    idx = st.radio("Top Themes (AU)", labels, index=0)
    choice = themes[labels.index(idx)]
    st.session_state["chosen_theme"] = choice

    # Show why + supporting headlines
    st.markdown(f"**Why this matters:** {choice.get('reason','')}")
    with st.expander("Representative headlines", expanded=False):
        for a in choice.get("articles", []):
            title = a.get("title","")
            src = a.get("source","")
            date = a.get("date","")
            st.write(f"- {title}  ·  _{src}_  ·  {date}")

    st.caption("Keywords for targeting:")
    st.write(", ".join(choice.get("keywords", [])[:8]))

    if st.button("✍️ Draft initial campaign for this theme"):
        st.session_state["chosen_theme_label"] = choice.get("query")

# ---- Copy generation & focus test ----
chosen_label = st.session_state.get("chosen_theme_label")
if chosen_label and traits_path and personas_path:
    st.subheader("Drafting campaign variants…")

    # Derive some “quotes/news” bullets from the selected cluster to ground copy
    sel = st.session_state.get("chosen_theme", {})
    bullets = "\n".join([f"- {a.get('title','')}" for a in sel.get("articles", [])[:4]])

    brief = {
        "id": "guided",
        "theme": chosen_label,
        "hook": f"Investing insights tied to {chosen_label}",
        "details": "Retail investor friendly, educational tone, actionable guidance.",
        "offer_price": "$99",
        "offer_term": "12 months",
        "reports": "New member report bundle",
        "stocks_to_tease": "2–3 ASX names",
        "quotes_news": bullets,
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

        # Personas
        pdata = json.loads(personas_path.read_text(encoding="utf-8"))
        personas = pdata.get("personas", [])

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

                # Target worst cluster and improve
                if clusters:
                    worst = min(clusters, key=clusters.get)
                else:
                    worst = 0
                worst_rows = df[df["cluster"] == worst].sort_values("intent").head(5)
                fb_bullets = "\n".join([f"- {t}" for t in worst_rows["feedback"].tolist()])

                improve_brief = {
                    **brief,
                    "structure": "Keep same structure but address the critique points explicitly.",
                    "quotes_news": f"Persona critique to address:\n{fb_bullets}",
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
    if not st.session_state.get("themes"):
        st.info("Click **Find live trends & news** to begin.")
