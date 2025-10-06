import _bootstrap
import streamlit as st, json
from adapters.copywriter_mf_adapter import generate as gen_copy
from utils.store import load_json
import pathlib

st.title("Copy Studio")

traits_cfg = json.loads(pathlib.Path("traits_config.json").read_text())
with st.sidebar.expander("🎚️ Linguistic Trait Intensity", True):
    traits = {
        "Urgency":             st.slider("Urgency & Time Sensitivity", 1, 10, 7),
        "Data_Richness":       st.slider("Data‑Richness & Numbers", 1, 10, 6),
        "Social_Proof":        st.slider("Social Proof", 1, 10, 5),
        "Comparative_Framing": st.slider("Comparative Framing", 1, 10, 5),
        "Imagery":             st.slider("Imagery & Metaphors", 1, 10, 6),
        "Conversational_Tone": st.slider("Conversational Tone", 1, 10, 8),
        "FOMO":                st.slider("FOMO", 1, 10, 6),
        "Repetition":          st.slider("Repetition for Emphasis", 1, 10, 4),
    }

country = st.selectbox("Target Country", ["Australia","United Kingdom","Canada","United States"])
length_choice = st.selectbox("Desired Length", ["📏 Short (100–200 words)",
                                                "📐 Medium (200–500 words)",
                                                "📖 Long (500–1500 words)"])

trends = load_json("trends/sample_trends.json", default=[])
opt = {t['headline']: t for t in trends} if trends else {}
brief_choice = st.selectbox("Pick a Trend (optional)", list(opt.keys()) or ["(none)"])

st.subheader("Campaign Brief")
hook    = st.text_input("Hook", value=(opt[brief_choice]["headline"] if opt and brief_choice in opt else ""))
details = st.text_area("Product / Offer Details")
col1, col2, col3 = st.columns(3)
offer_price  = col1.text_input("Special Offer Price")
retail_price = col2.text_input("Retail Price")
offer_term   = col3.text_input("Subscription Term")
reports         = st.text_area("Included Reports")
stocks_to_tease = st.text_input("Stocks to Tease (optional)")
quotes_news     = st.text_area("Quotes/News (optional)")

def mk_brief():
    b = opt.get(brief_choice, {"id":"manual"})
    b = dict(b)
    b.update({"hook":hook,"details":details,"offer_price":offer_price,"retail_price":retail_price,
              "offer_term":offer_term,"reports":reports,"stocks_to_tease":stocks_to_tease,
              "quotes_news":quotes_news,"length_choice":length_choice})
    return b

if st.button("✨ Generate 5 Variants"):
    brief = mk_brief()
    variants = gen_copy(brief, fmt="email_subject", n=5, trait_cfg=traits_cfg, traits=traits, country=country)
    st.session_state["copy_variants"] = [v.model_dump() for v in variants]

if "copy_variants" in st.session_state:
    st.subheader("Variants")
    for v in st.session_state["copy_variants"]:
        with st.expander(v["id"]):
            st.markdown(v["copy"])
            st.json(v["meta"], expanded=False)
