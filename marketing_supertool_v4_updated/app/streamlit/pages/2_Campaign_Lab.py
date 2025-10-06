import streamlit as st, json, pathlib
from utils.store import load_json, save_json
from core.models import Persona
from adapters.copywriter_mf_adapter import generate as gen_copy
from adapters.evaluator_synthetic import evaluate_variant_with_synthetic
from core.orchestrator import run_loop_for_brief

st.title("Campaign Lab")

# Personas
pfile = pathlib.Path("data/personas.json")
if not pfile.exists():
    st.warning("No personas found. Import via Personas page.")
    personas = []
else:
    raw = json.loads(pfile.read_text())
    from core.models import Persona
    personas = [Persona(**p) for p in raw]

trends = load_json("trends/sample_trends.json", default=[])
if not trends:
    st.error("No trends loaded. Use Trends page first.")
    st.stop()

trend_options = {t['headline']: t for t in trends}
choice = st.selectbox("Pick a trend", list(trend_options.keys()))
brief = dict(trend_options[choice])
brief.update({"length_choice":"📏 Short (100–200 words)"})

evaluator = st.selectbox("Evaluator", ["heuristic","synthetic","hybrid"], index=0)
n_variants = st.slider("Initial variants", 3, 12, 6)
stop_threshold = st.slider("Stop threshold (composite)", 0.5, 0.95, 0.78, 0.01)
max_rounds = st.slider("Max rounds", 1, 6, 3, 1)

import json as _json, pathlib as _pl
traits_cfg = _json.loads(_pl.Path("traits_config.json").read_text())
default_traits = {"Urgency":7,"Data_Richness":6,"Social_Proof":5,"Comparative_Framing":5,"Imagery":6,"Conversational_Tone":8,"FOMO":6,"Repetition":4}
def writer(brief, fmt, n):
    return gen_copy(brief, fmt, n, trait_cfg=traits_cfg, traits=default_traits, country="Australia")

if st.button("Run optimisation loop"):
    finalist, history = run_loop_for_brief(
        brief, personas, writer, n_variants, stop_threshold, max_rounds,
        evaluator=evaluator, synthetic_eval_fn=evaluate_variant_with_synthetic
    )
    if finalist:
        st.success(f"Winner: {finalist.variant_id} | Composite {finalist.composite_score:.2f}")
        st.code(finalist.copy)
        save_json(f"finalists/{finalist.brief_id}.json", finalist.model_dump())
        st.caption("Saved to /data/finalists/")
    else:
        st.warning("No viable variants passed guardrails.")
    st.subheader("Evaluation history")
    for v, ev in history[:50]:
        with st.expander(f"{v.id} | {v.copy[:80]}"):
            st.write(f"Composite: {ev.composite_score:.2f} | Pred CTR: {ev.predicted_ctr:.3f}")
            st.write("Persona scores (n):", len(ev.persona_scores))
            st.write("Feedback sample:", ev.qual_feedback[:3])
