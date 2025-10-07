# app/streamlit/pages/1_Brief_Builder.py
import _bootstrap
import sys
import importlib
from pathlib import Path
import json
import streamlit as st

st.set_page_config(page_title="Brief Builder", page_icon="🧱", layout="wide")
st.title("Brief Builder: news → analyst brief → export")
st.caption("Pull AU finance headlines via SerpAPI, synthesise a publisher-ready brief, export Markdown or JSON. No Trends, no fluff.")

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

search_google_news = getattr(news_adapter, "search_google_news")
fetch_articles_content = getattr(news_adapter, "fetch_articles_content")
get_serpapi_key = getattr(news_adapter, "get_serpapi_key")
build_campaign_brief = getattr(brief_engine, "build_campaign_brief")
brief_to_markdown = getattr(brief_engine, "brief_to_markdown")

with st.expander("Runtime", expanded=False):
    st.write({"python_version": sys.version})
    st.write({"news_adapter_path": getattr(news_adapter, "__file__", "n/a"),
              "adapter_version": getattr(news_adapter, "ADAPTER_VERSION", "n/a")})

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
    except Exception as e:
        st.error(f"News fetch failed: {type(e).__name__}: {e}")
        st.stop()

news = st.session_state.get("bb_news", [])
if news:
    st.subheader("Sources")
    st.caption("Balanced across publishers, de-duplicated by title.")
    # Show a compact table
    def _compact(n: dict) -> dict:
        return {"title": n.get("title",""), "publisher": n.get("source",""), "date": n.get("date",""), "url": n.get("link","")}
    table = [_compact(n) for n in news]
    st.dataframe(table, use_container_width=True, hide_index=True)

    # Step 2: Optional: fetch article bodies for more context (best-effort)
    with st.expander("Fetch article bodies (optional, slower)", expanded=False):
        if st.button("⬇️ Fetch bodies for top 12"):
            urls = [n.get("link","") for n in news][:12]
            bodies = fetch_articles_content(urls, limit=12)
            # attach short excerpts back to news entries for LLM context
            by_url = {b["url"]: b.get("text","") for b in bodies}
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

st.divider()

# Step 3: Build the brief
if news and st.button("🧠 Synthesize brief"):
    try:
        # Prefer items with excerpts; otherwise titles+snippets are used
        # To keep tokens sane, only ship top 18 to the model (brief_engine does that).
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
