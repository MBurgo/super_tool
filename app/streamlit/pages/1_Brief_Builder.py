# app/streamlit/pages/1_Brief_Builder.py
import _bootstrap
import sys
import importlib
from pathlib import Path
from io import BytesIO
import json
import numpy as np
import streamlit as st

st.set_page_config(page_title="Brief Builder", page_icon="🧱", layout="wide")
st.title("Brief Builder: news → analyst brief → variants → synthetic focus")
st.caption("Pull AU finance headlines via SerpAPI, synthesise a publisher-ready brief, draft variants, iterate with personas, export.")

# Lazy imports with readable errors
def _lazy(name: str):
    try:
        m = importlib.import_module(name)
        return m, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

news_adapter, err1 = _lazy("adapters.news_serp_adapter")
if err1:
    st.error("Failed to import adapters.news_serp_adapter"); st.code(err1); st.stop()
brief_engine, err2 = _lazy("core.brief_engine")
if err2:
    st.error("Failed to import core.brief_engine"); st.code(err2); st.stop()
copy_adapter, err3 = _lazy("adapters.copywriter_mf_adapter")
if err3:
    st.error("Failed to import adapters.copywriter_mf_adapter"); st.code(err3); st.stop()
sprint_engine, err4 = _lazy("core.sprint_engine")
if err4:
    st.error("Failed to import core.sprint_engine"); st.code(err4); st.stop()

search_google_news = getattr(news_adapter, "search_google_news")
fetch_articles_content = getattr(news_adapter, "fetch_articles_content")
get_serpapi_key = getattr(news_adapter, "get_serpapi_key")
build_campaign_brief = getattr(brief_engine, "build_campaign_brief")
brief_to_markdown = getattr(brief_engine, "brief_to_markdown")
gen_copy = getattr(copy_adapter, "generate")
run_sprint = getattr(sprint_engine, "run_sprint")

with st.expander("Runtime", expanded=False):
    st.write({"python_version": sys.version})
    st.write({
        "news_adapter_path": getattr(news_adapter, "__file__", "n/a"),
        "news_adapter_version": getattr(news_adapter, "ADAPTER_VERSION", "n/a"),
    })

# Load shared assets (traits, personas)
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

traits_cfg = {}
default_traits = {}
try:
    if traits_path and traits_path.exists():
        traits_cfg = json.loads(traits_path.read_text(encoding="utf-8"))
        default_traits = {k: v.get("default","") for k, v in traits_cfg.get("traits", {}).items()}
except Exception as e:
    st.warning(f"Traits config read issue: {e}")

# Inputs
colq, colw, coln = st.columns([2, 1, 1])
with colq:
    topic = st.text_input("Research topic", "ASX 200 earnings season")
with colw:
    when = st.selectbox("Window", ["4h", "1d", "7d"], index=2)
with coln:
    limit = st.slider("Max articles", 10, 60, 30, 5)

st.divider()

# Step 1: Fetch news
if st.button("🔎 Research topic (Google News via SerpAPI)"):
    key = get_serpapi_key()
    if not key:
        st.error("No SerpAPI key available.")
        st.stop()
    try:
        results = search_google_news(topic, when=when, num=limit, api_key=key)
        st.session_state["bb_news"] = results
        st.session_state.pop("bb_brief", None)
        st.session_state.pop("bb_variants", None)
        st.success(f"Fetched {len(results)} sources.")
    except Exception as e:
        st.error(f"News fetch failed: {type(e).__name__}: {e}")
        st.stop()

news = st.session_state.get("bb_news", [])
if news:
    st.subheader("Sources")
    st.caption("Balanced across publishers, de-duplicated by title.")

    # Compact table with excerpt preview if present
    def _compact(n: dict) -> dict:
        exc = (n.get("excerpt") or n.get("snippet") or "").strip()
        if len(exc) > 180:
            exc = exc[:180] + "…"
        return {
            "title": n.get("title",""),
            "publisher": n.get("source",""),
            "date": n.get("date",""),
            "url": n.get("link",""),
            "excerpt_preview": exc,
        }
    table = [_compact(n) for n in news]
    st.dataframe(table, hide_index=True, use_container_width=True)

    # Per-row expanders to read full excerpt/snippet when available
    with st.expander("Read excerpts", expanded=False):
        for i, n in enumerate(news, start=1):
            title = n.get("title","")
            src = n.get("source","")
            date = n.get("date","")
            url = n.get("link","")
            exc = (n.get("excerpt") or n.get("snippet") or "").strip()
            if not exc:
                continue
            with st.expander(f"{i}. {title}  ·  {src}  ·  {date}"):
                st.write(exc)
                st.caption(url)

    # Step 2: Optional: fetch article bodies for more context (best-effort)
    with st.expander("Fetch article bodies (optional, slower)", expanded=False):
        st.caption("We normalise URLs and skip anything without http/https.")
        if st.button("⬇️ Fetch bodies for top 12"):
            urls = [n.get("link","") for n in news][:12]
            bodies = fetch_articles_content(urls, limit=12)
            # attach short excerpts back to news entries for LLM context
            by_url = {b.get("url",""): b.get("text","") for b in bodies if b.get("url")}
            enriched = []
            for n in news:
                t = n.copy()
                body = by_url.get(n.get("link",""), "")
                if body:
                    # keep a compact excerpt so we don't blow tokens
                    t["excerpt"] = body[:1200]
                enriched.append(t)
            st.session_state["bb_news"] = enriched
            st.success("Attached short excerpts to top sources.")
            news = enriched

st.divider()

# Step 3: Build the brief
if news and st.button("🧠 Synthesize brief"):
    try:
        brief = build_campaign_brief(topic, news, country="Australia", service_name="Share Advisor", model="gpt-4o-mini")
        st.session_state["bb_brief"] = brief
        st.success("Brief ready.")
    except Exception as e:
        st.error(f"Brief synthesis failed: {type(e).__name__}: {e}")
        st.stop()

brief = st.session_state.get("bb_brief")
if brief:
    st.subheader("Brief")
    st.markdown(f"**Summary:** {brief.get('summary','')}")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Drivers**")
        for x in brief.get("drivers", []):
            st.write(f"- {x}")
        st.markdown("**Risks**")
        for x in brief.get("risks", []):
            st.write(f"- {x}")
        st.markdown("**SEO keywords**")
        st.write(", ".join(brief.get("seo_keywords", [])))
    with cols[1]:
        st.markdown("**Hooks**")
        for x in brief.get("hooks", []):
            st.write(f"- {x}")
        st.markdown("**CTA angles**")
        for x in brief.get("cta_angles", []):
            st.write(f"- {x}")

    st.markdown("**Talking points**")
    for x in brief.get("talking_points", []):
        st.write(f"- {x}")

    st.markdown("**Email subjects**")
    for x in brief.get("email_subjects", []):
        st.write(f"- {x}")

    st.markdown("**Headlines**")
    for x in brief.get("headlines", []):
        st.write(f"- {x}")

    st.markdown("**Social captions**")
    for x in brief.get("social_captions", []):
        st.write(f"- {x}")

    if brief.get("notes"):
        st.info(brief.get("notes"))

    st.markdown("**Sources**")
    cites = brief.get("citations", [])
    if cites:
        for i, c in enumerate(cites, start=1):
            st.write(f"[{i}] {c.get('title','')} — _{c.get('publisher','')}_ — {c.get('date','')} — {c.get('url','')}")

    # Exports
    md = brief_to_markdown(topic, brief)
    st.download_button("📥 Download Markdown", data=md, file_name=f"brief_{topic.replace(' ','_')}.md", mime="text/markdown")
    st.download_button("📥 Download JSON", data=json.dumps(brief, ensure_ascii=False, indent=2), file_name=f"brief_{topic.replace(' ','_')}.json", mime="application/json")

    st.divider()

    # Step 4: Generate campaign variants from the brief
    st.subheader("Generate campaign variants from this brief")
    # Build a copywriter-friendly brief
    news_bullets = []
    for c in cites[:6]:
        t = c.get("title","")
        s = c.get("publisher","")
        if t:
            news_bullets.append(f"- {t} ({s})")
    quotes_news = "\n".join(news_bullets) if news_bullets else ""

    # Traits controls
    col1, col2 = st.columns([1, 2])
    with col1:
        n_variants = st.slider("Number of variants", 1, 5, 3)
        length_choice = st.selectbox(
            "Length",
            ["📏 Short (100–200 words)", "📐 Medium (200–500 words)", "📖 Long (500–1500 words)"],
            index=1,
        )
    with col2:
        st.caption("Traits to emphasise (optional)")
        t_sel = {}
        for k, v in (traits_cfg.get("traits", {}) or {}).items():
            if isinstance(v, dict) and "options" in v:
                t_sel[k] = st.selectbox(k, v["options"], index=0)
            else:
                t_sel[k] = st.text_input(k, value=str(default_traits.get(k, "")))
        traits_in_use = t_sel or default_traits

    if st.button("✍️ Draft variants"):
        cw_brief = {
            "id": "brief_builder",
            "theme": topic,
            "hook": (brief.get("hooks") or ["A grounded, opportunity‑focused angle for AU investors."])[0],
            "details": brief.get("summary", ""),
            "offer_price": "$99",
            "offer_term": "12 months",
            "reports": "New member report bundle",
            "stocks_to_tease": "",
            "quotes_news": quotes_news,
            "structure": "Hook, Problem, Insight, Proof, Offer, CTA",
            "requirements": "Avoid promises. Emphasise risk and education. Include price and term.",
        }
        try:
            variants = gen_copy(
                cw_brief,
                fmt="sales_page",
                n=n_variants,
                trait_cfg=traits_cfg,
                traits=traits_in_use,
                country="Australia",
                length_choice=length_choice,
            )
            st.session_state["bb_variants"] = variants
            st.success(f"Generated {len(variants)} variant(s).")
        except Exception as e:
            st.error(f"Copywriter failed: {type(e).__name__}: {e}")
            st.stop()

variants = st.session_state.get("bb_variants", [])
if variants:
    st.subheader("Pick a base variant")
    labels = [f"Variant {i+1}" for i in range(len(variants))]
    idx = st.radio("Variants", labels, index=0, horizontal=True)
    base_index = int(idx.split()[-1]) - 1
    base = variants[base_index]
    st.markdown("### Selected base variant")
    base_text = base.copy
    st.markdown(base_text)

    # Personas
    if not personas_path:
        st.error("Missing personas. Looked for assets/personas.json, ./personas.json, and data/personas.json.")
    else:
        pdata = json.loads(personas_path.read_text(encoding="utf-8"))
        personas = pdata.get("personas", [])

        st.subheader("Synthetic focus test")
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

                # New Streamlit plotting API prefers width='stretch'
                try:
                    st.plotly_chart(fig, width="stretch")
                except TypeError:
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
                    "id": "brief_builder_improve",
                    "theme": topic,
                    "hook": (brief.get("hooks") or ["A grounded, opportunity‑focused angle for AU investors."])[0],
                    "details": brief.get("summary", ""),
                    "offer_price": "$99",
                    "offer_term": "12 months",
                    "reports": "New member report bundle",
                    "stocks_to_tease": "",
                    "quotes_news": f"Persona critique to address:\n{fb_bullets}",
                    "structure": "Keep same structure but address the critique points explicitly.",
                    "requirements": "Avoid promises. Emphasise risk and education. Include price and term.",
                }

                improved = gen_copy(
                    improve_brief,
                    fmt="sales_page",
                    n=1,
                    trait_cfg=traits_cfg,
                    traits=traits_in_use,
                    country="Australia",
                )
                current = improved[0].copy if improved else current

            st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
            st.markdown(current)
