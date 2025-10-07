# app/streamlit/pages/0_Guided_Flow.py
import _bootstrap
import streamlit as st
from io import BytesIO
import numpy as np
import json, pathlib

# ── Adapters & engines (with safe fallbacks for import paths) ──────────
from adapters.trends_serp_adapter import fetch_trends_and_news
from adapters.copywriter_mf_adapter import generate as gen_copy
try:
    from core.sprint_engine import run_sprint
except Exception:
    # fallback if the file sits at project root
    from sprint_engine import run_sprint
from tmf_synth_utils import load_personas

from core.guided_flow import (
    GuidedFlowState,
    FocusTestIteration,
    begin_focus_testing,
    choose_theme,
    discover_trends,
    execute_focus_testing,
    generate_variants,
)

st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

state = st.session_state
flow: GuidedFlowState = state.setdefault("guided_flow", GuidedFlowState())

# ── Default trait rules (used if assets/traits_config.json is missing) ──
TRAITS_DEFAULT = {
    "Urgency": {
        "high_threshold": 8, "low_threshold": 3,
        "high_rule": "- Include a clear deadline phrase in both the headline/subject **and** the CTA (e.g., “midnight”, an explicit date, “today only”).",
        "mid_rule": "- Refer to timing **once only** (e.g., “later this week”) and use **no more than one** urgency synonym such as “quickly”, “act now”, “limited”, etc. Do not include hard countdowns or explicit deadlines.",
        "low_rule": "- DO NOT use countdowns, deadline words, scarcity cues or time‑pressure phrases; keep tone calm and informational.",
        "high_exemplar_allowed": True
    },
    "Data_Richness": {
        "high_threshold": 7, "low_threshold": 3,
        "high_rule": "- Cite at least **one** specific numeric performance figure (percentage return, CAGR, dollar amount, member count, etc.).",
        "mid_rule": "- You may use **one** light data point or ranking (e.g., “top‑quartile performer”), but no detailed stats tables or multiple figures.",
        "low_rule": "- Avoid statistics, percentages and dollar figures; rely purely on qualitative proof.",
        "high_exemplar_allowed": False
    },
    "Social_Proof": {
        "high_threshold": 6, "low_threshold": 3,
        "high_rule": "- Provide **three or more** credibility builders (testimonials, membership count, expert quote, third‑party award).",
        "mid_rule": "- Include **one** credibility builder (e.g., “trusted by 80,000 members”) but no lengthy testimonial blocks.",
        "low_rule": "- Omit testimonials, expert quotes, awards and membership numbers.",
        "high_exemplar_allowed": False
    },
    "Conversational_Tone": {
        "high_threshold": 8, "low_threshold": 3,
        "high_rule": "- Write in second‑person, use contractions, occasional rhetorical questions and short, friendly sentences.",
        "mid_rule": "- Use clear, neutral language (mix of second‑ and third‑person is fine). **Do not open with informal greetings (e.g., “Hi”, “Hey”, “Hi there”) or rhetorical questions.** Avoid more than one contraction per paragraph.",
        "low_rule": "- Write in third‑person, avoid contractions and questions; maintain a neutral, formal register.",
        "high_exemplar_allowed": False
    },
    "Imagery": {
        "high_threshold": 8, "low_threshold": 3,
        "high_rule": "- Use vivid metaphors or visual comparisons (e.g., snowball, rocket, tidal wave) to illustrate key points.",
        "mid_rule": "- Allow **one** mild metaphor or descriptive adjective; otherwise keep language straightforward.",
        "low_rule": "- Avoid metaphors and descriptive imagery; keep language literal. Use **no more than two adjectives** per paragraph.",
        "high_exemplar_allowed": False
    },
    "Comparative_Framing": {
        "high_threshold": 7, "low_threshold": 3,
        "high_rule": "- Draw explicit historical or sector comparisons (e.g., “like buying Netflix in 2002” or “this decade’s oil rush”).",
        "mid_rule": "- Use a single light comparison (e.g., “similar to past tech booms”) without deep storytelling.",
        "low_rule": "- Do not reference historical comparisons or analogies; focus only on the present opportunity.",
        "high_exemplar_allowed": False
    },
    "FOMO": {
        "high_threshold": 7, "low_threshold": 3,
        "high_rule": "- Highlight the emotional cost of missing out and potential regret (e.g., “don’t be left behind”).",
        "mid_rule": "- Note that the offer is attractive and may not last, **but do not mention regret, fear, or missing out.** Words such as “popular” or “worth considering soon” are acceptable.",
        "low_rule": "- Avoid any fear‑of‑missing‑out language or emotional urgency; present benefits objectively.",
        "high_exemplar_allowed": False
    },
    "Repetition": {
        "high_threshold": 6, "low_threshold": 2,
        "high_rule": "- Reinforce the main offer or deadline with **deliberate repetition** for emphasis (no more than two repeats).",
        "mid_rule": "- Restate the offer once in a different phrase; avoid obvious repetition techniques.",
        "low_rule": "- State each point only once; avoid repeated phrases entirely.",
        "high_exemplar_allowed": False
    }
}

def _load_traits_cfg() -> dict:
    cfg_path = pathlib.Path("assets/traits_config.json")
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            st.warning(f"Could not parse assets/traits_config.json, using built-in defaults. ({e})")
    else:
        st.info("No assets/traits_config.json found. Using built-in trait rules.")
    return TRAITS_DEFAULT

def _need(var: str, where: str = "secrets") -> str:
    if var == "SERP_API_KEY":
        # We keep the original structure: st.secrets['serpapi']['api_key']
        try:
            return st.secrets["serpapi"]["api_key"]
        except Exception:
            st.error("Missing SerpAPI key. Add to secrets as:\n\n[serpapi]\napi_key = \"YOUR_KEY\"")
            st.stop()
    return ""


# ── 1) Kick off trend finder ───────────────────────────────────────────
st.header("1. Discover live trends", divider="blue")
if st.button("🔎 Start trend finder"):
    serp_key = _need("SERP_API_KEY", "secrets")

    def _fetch():
        return fetch_trends_and_news(serp_key)

    with st.spinner("Contacting SERP and news sources…"):
        discover_trends(flow, _fetch)

    state.pop("guided_theme_pick", None)
    state.pop("guided_variant_pick", None)

payload = flow.trends
if payload:
    st.success("Latest trend insights loaded. Pick a theme to continue.")
    with st.expander("See fetched data", expanded=False):
        st.write("### Rising queries")
        st.json(payload.rising)
        st.write("### Related news")
        st.json(payload.news)

    st.header("2. Select a campaign theme", divider="blue")
    options = payload.themes or ["(No rising queries returned)"]
    disable_choice = not payload.themes
    choice = st.radio(
        "Top Rising Queries (last 4h AU)",
        options,
        index=0,
        key="guided_theme_pick",
        disabled=disable_choice,
    )
    if st.button("✍️ Continue with this theme", disabled=disable_choice):
        choose_theme(flow, choice)
        state.pop("guided_variant_pick", None)

# ── 2) Generate initial variants ───────────────────────────────────────
chosen = flow.chosen_theme
if chosen:
    st.header("3. Draft campaign variants", divider="blue")
    st.caption(f"Theme selected: **{chosen}**")

    brief = {
        "id": "guided",
        "hook": chosen.split(" — ")[0],
        "details": "Campaign based on live AU rising queries + latest news.",
        "offer_price": "", "retail_price": "", "offer_term": "",
        "reports": "", "stocks_to_tease": "", "quotes_news": "",
        "length_choice": "📐 Medium (200–500 words)"
    }

    traits = {
        "Urgency": 7, "Data_Richness": 6, "Social_Proof": 6,
        "Comparative_Framing": 5, "Imagery": 6,
        "Conversational_Tone": 7, "FOMO": 6, "Repetition": 4
    }
    trait_cfg = _load_traits_cfg()

    if flow.stage == "draft_variants" and not flow.variants:
        def _generate():
            variants = gen_copy(
                brief, fmt="sales_page", n=3,
                trait_cfg=trait_cfg, traits=traits,
                country="Australia", model=st.secrets.get("openai_model", "gpt-4.1")
            )
            return [v.copy for v in variants]

        with st.spinner("Generating copy variants…"):
            generate_variants(flow, _generate)

    texts = list(flow.variants)
    if texts:
        pick = st.radio(
            "Choose a base variant",
            [f"Variant {i+1}" for i in range(len(texts))],
            index=0,
            key="guided_variant_pick",
        )
        idx = int(pick.split()[-1]) - 1
        base_text = texts[idx]
        st.markdown(base_text)

        if flow.stage == "draft_variants":
            if st.button("🚀 Start focus testing & improvements"):
                begin_focus_testing(flow, base_text)
        else:
            base_text = flow.focus_source or base_text

    # ── 3) Focus-test loop (auto-revise until pass) ────────────────────
    personas_path = pathlib.Path("assets/personas.json")
    if not personas_path.exists():
        st.error("Missing assets/personas.json. Commit your persona pack to assets/personas.json.")
        st.stop()

    personas = load_personas(str(personas_path))
    threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
    rounds = st.number_input("Max revision rounds", 1, 5, 3)

    if flow.stage in {"focus_test", "complete"}:
        st.header("4. Focus test & refine", divider="blue")
        st.caption("We iterate until the copy meets the target intent score or max rounds is reached.")

        if flow.focus_result is None and flow.stage == "focus_test":
            def _tester(copy: str, round_idx: int) -> FocusTestIteration:
                f = BytesIO(copy.encode("utf-8"))
                f.name = "copy.txt"

                summary, df, fig, clusters = run_sprint(
                    file_obj=f,
                    segment="All Segments",
                    persona_groups=personas,
                    return_cluster_df=True
                )
                mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
                return FocusTestIteration(
                    round=round_idx,
                    copy=copy,
                    summary=summary,
                    mean_intent=mean_intent,
                    figure=fig,
                    clusters=clusters,
                )

            def _improver(copy: str, iteration: FocusTestIteration) -> str:
                if hasattr(iteration.clusters, "iterrows"):
                    tips = "\n".join(
                        [f"- Cluster {int(row['cluster'])}: {row['summary']}" for _, row in iteration.clusters.iterrows()]
                    )
                else:
                    tips = "No persona feedback clusters returned."

                improve_brief = dict(brief)
                improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

                improved = gen_copy(
                    improve_brief, fmt="sales_page", n=1,
                    trait_cfg=trait_cfg, traits=traits,
                    country="Australia", model=st.secrets.get("openai_model", "gpt-4.1")
                )
                return improved[0].copy

            with st.spinner("Running persona focus group…"):
                execute_focus_testing(
                    flow,
                    _tester,
                    _improver,
                    threshold=float(threshold),
                    max_rounds=int(rounds),
                )

        focus_result = flow.focus_result
        if focus_result:
            for entry in focus_result.iterations:
                st.write(f"### Round {entry.round}")
                if entry.figure is not None:
                    st.plotly_chart(entry.figure, use_container_width=True)
                st.write(entry.summary)
                st.write(f"**Mean intent:** {entry.mean_intent:.2f}/10")

            passed = focus_result.passed
            st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
            st.markdown(focus_result.final_copy)

            if st.button("🔄 Start over"):
                flow.reset()
                state.pop("guided_theme_pick", None)
                state.pop("guided_variant_pick", None)
