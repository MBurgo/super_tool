# app/streamlit/pages/0_Guided_Flow.py
"""
Guided Flow (No Sheets)
- Finds live AU trends + news via SerpAPI
- Lets user pick a theme
- Drafts campaign variants
- Iteratively focus-tests across personas and auto-improves until threshold
- Presents the finalised campaign

Dependencies expected elsewhere in the repo:
- assets/traits_config.json
- assets/personas.json
- adapters/copywriter_mf_adapter.py  (or top-level copywriter_mf_adapter.py)
- core/sprint_engine.py (or top-level sprint_engine.py)
- core/tmf_synth_utils.py (or top-level tmf_synth_utils.py)

Secrets (any one is enough):
- OPENAI_API_KEY env var OR st.secrets["openai"]["api_key"]
- SERPAPI_API_KEY env var OR st.secrets["serpapi"]["api_key"]
"""

import _bootstrap  # ensures repo root is in sys.path
import os
import json
import asyncio
from pathlib import Path
from io import BytesIO
import numpy as np
import streamlit as st

# ──────────────────────────────────────────────────────────────
# 0) Env/Secrets normalisation
# ──────────────────────────────────────────────────────────────
def _get_secret(path, default=None):
    """
    Read a dotted-path secret from st.secrets if available.
    E.g., _get_secret(("openai", "api_key"))
    """
    try:
        cur = st.secrets
        for p in path:
            cur = cur[p]
        return cur
    except Exception:
        return default

# OPENAI key: env first, then secrets
if not os.getenv("OPENAI_API_KEY"):
    key = _get_secret(("openai", "api_key")) or _get_secret(("openai_api_key",), "")
    if key:
        os.environ["OPENAI_API_KEY"] = key

# Model name (optional)
OPENAI_MODEL = _get_secret(("openai_model",), "gpt-4.1")

# SerpAPI key: env first, then secrets
SERP_KEY = os.getenv("SERPAPI_API_KEY") or _get_secret(("serpapi", "api_key"))

# ──────────────────────────────────────────────────────────────
# 1) Imports with resilient fallbacks
# ──────────────────────────────────────────────────────────────
# Copywriter adapter (try adapters/ then local file)
try:
    from adapters.copywriter_mf_adapter import generate as gen_copy
except ModuleNotFoundError:
    try:
        from copywriter_mf_adapter import generate as gen_copy  # type: ignore
    except ModuleNotFoundError as e:
        gen_copy = None  # we’ll gate on this later

# Sprint engine (try core/ then root)
try:
    from core.sprint_engine import run_sprint
except ModuleNotFoundError:
    try:
        from sprint_engine import run_sprint  # type: ignore
    except ModuleNotFoundError:
        run_sprint = None

# Personas loader (try core/ then root, else local file read)
try:
    from core.tmf_synth_utils import load_personas
except ModuleNotFoundError:
    try:
        from tmf_synth_utils import load_personas  # type: ignore
    except ModuleNotFoundError:
        def load_personas(path: str):
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data["personas"]

# Trends adapter: if missing, we provide a local fallback below
try:
    from adapters.trends_serp_adapter import fetch_trends_and_news, fetch_meta_descriptions  # type: ignore
    _HAVE_TRENDS_ADAPTER = True
except ModuleNotFoundError:
    _HAVE_TRENDS_ADAPTER = False

# ──────────────────────────────────────────────────────────────
# 2) Local SerpAPI fallback (used only if adapter import fails)
# ──────────────────────────────────────────────────────────────
if not _HAVE_TRENDS_ADAPTER:
    try:
        from serpapi import GoogleSearch
    except Exception:
        GoogleSearch = None  # type: ignore

    USER_AGENT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    import httpx
    from bs4 import BeautifulSoup

    async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
        if not url or not url.startswith("http"):
            return "Invalid URL"
        try:
            r = await session.get(url, timeout=10, headers=USER_AGENT_HEADERS, follow_redirects=True)
            if r.status_code != 200:
                return f"HTTP {r.status_code}"
            soup = BeautifulSoup(r.content, "lxml")
            tag = soup.find("meta", attrs={"name": "description"})
            return (
                tag["content"].strip()
                if tag and "content" in tag.attrs and tag["content"].strip()
                else "No Meta Description"
            )
        except Exception:
            return "Error Fetching Description"

    async def _fetch_meta_descriptions(urls, limit: int = 10):
        sem = asyncio.Semaphore(limit)
        async with httpx.AsyncClient() as session:
            async def bound(u):
                async with sem:
                    return await _grab_desc(session, u)
            return await asyncio.gather(*(bound(u) for u in urls))

    def fetch_meta_descriptions(urls):
        return asyncio.run(_fetch_meta_descriptions(urls))

    def fetch_trends_and_news(serp_api_key: str):
        """
        Returns (rising, news)
        rising: list of dicts from Google Trends “related_queries.rising”
        news:   list of dicts from Google News results
        """
        if GoogleSearch is None:
            raise RuntimeError("SerpAPI is not installed. Add `serpapi` to requirements.txt.")

        # Google Trends: ASX 200 entity (/m/0bl5c2), AU, last 4 hours
        t_params = {
            "api_key": serp_api_key,
            "engine": "google_trends",
            "q": "/m/0bl5c2",
            "geo": "AU",
            "data_type": "RELATED_QUERIES",
            "tz": "-600",
            "date": "now 4-H",
        }
        t_res = GoogleSearch(t_params).get_dict()
        rising = (t_res.get("related_queries", {}) or {}).get("rising", []) or []

        # Google News
        n_params = {
            "api_key": serp_api_key,
            "engine": "google",
            "no_cache": "true",
            "q": "asx 200",
            "google_domain": "google.com.au",
            "tbs": "qdr:d",
            "gl": "au",
            "hl": "en",
            "location": "Australia",
            "tbm": "nws",
            "num": "40",
        }
        news = GoogleSearch(n_params).get_dict().get("news_results", []) or []

        return rising, news

# ──────────────────────────────────────────────────────────────
# 3) Small helpers
# ──────────────────────────────────────────────────────────────
def _read_json(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))

def _read_traits() -> dict:
    cfg_path = Path("assets/traits_config.json")
    if not cfg_path.exists():
        st.error("Missing required file: assets/traits_config.json")
        st.stop()
    return _read_json(cfg_path)

def _read_personas() -> list[dict]:
    pj = Path("assets/personas.json")
    if not pj.exists():
        st.error("Missing required file: assets/personas.json")
        st.stop()
    # Use loader if available (keeps parity), else raw
    try:
        return load_personas(str(pj))
    except Exception:
        data = _read_json(pj)
        return data["personas"]

class NamedBytes(BytesIO):
    """Bytes buffer with a `.name` attribute to mimic an uploaded file object."""
    def __init__(self, content: bytes, name: str = "copy.txt"):
        super().__init__(content)
        self.name = name

# ──────────────────────────────────────────────────────────────
# 4) UI
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Guided Flow", page_icon="🧭")
st.title("🧭 Guided Campaign Builder (No Sheets)")

# Gate required functions/modules
missing = []
if gen_copy is None:
    missing.append("copywriter adapter (adapters.copywriter_mf_adapter.py)")
if run_sprint is None:
    missing.append("sprint engine (core/sprint_engine.py)")
if missing:
    st.error(
        "Missing modules: " + ", ".join(missing) +
        ". Please ensure these files exist in the repo and that `_bootstrap.py` is imported at the top."
    )
    st.stop()

if not SERP_KEY:
    st.warning(
        "No SerpAPI key detected. Add `SERPAPI_API_KEY` to environment or "
        "[serpapi].api_key to Streamlit secrets to enable live trend fetching."
    )

# Step 1: Kick off trend finder
with st.container(border=True):
    st.subheader("1) Find live trends & news")
    c1, c2 = st.columns([1, 3])
    with c1:
        btn = st.button("🔎 Find live trends & news", type="primary", use_container_width=True)
    with c2:
        st.caption("We pull AU Google Trends (last 4 hours) for ASX‑200 and same‑day Google News headlines.")

    if btn:
        if not SERP_KEY:
            st.error("SerpAPI key not found. Please configure SERPAPI_API_KEY or st.secrets['serpapi']['api_key'].")
        else:
            with st.spinner("Contacting SerpAPI…"):
                try:
                    rising, news = fetch_trends_and_news(SERP_KEY)
                except Exception as e:
                    st.exception(e)
                    st.stop()

            themes = [f"{r.get('query','(n/a)')} — {r.get('value','')}" for r in rising[:10]]
            st.session_state["guidance_trends"] = {"rising": rising, "news": news, "themes": themes}
            st.success(f"Fetched {len(rising)} rising queries and {len(news)} news results.")

data = st.session_state.get("guidance_trends")
if data:
    with st.container(border=True):
        st.subheader("2) Pick a theme to pursue")
        left, right = st.columns([2, 1])
        with left:
            choice = st.radio("Top Rising Queries (last 4h, AU)", data["themes"], index=0)
        with right:
            if st.button("✍️ Draft campaign for this theme", use_container_width=True):
                st.session_state["chosen_theme"] = choice
                st.toast("Theme locked for drafting.", icon="✍️")

chosen = st.session_state.get("chosen_theme")
if chosen:
    # Step 3: Generate initial variants
    with st.container(border=True):
        st.subheader("3) Drafting campaign variants")
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
        traits = {
            "Urgency": 7,
            "Data_Richness": 6,
            "Social_Proof": 6,
            "Comparative_Framing": 5,
            "Imagery": 6,
            "Conversational_Tone": 7,
            "FOMO": 6,
            "Repetition": 4,
        }

        trait_cfg = _read_traits()

        with st.spinner("Crafting 3 variants…"):
            try:
                variants = gen_copy(
                    brief,
                    fmt="sales_page",
                    n=3,
                    trait_cfg=trait_cfg,
                    traits=traits,
                    country="Australia",
                    model=OPENAI_MODEL,
                )
            except Exception as e:
                st.exception(e)
                st.stop()

        texts = [v.copy for v in variants]
        pick = st.radio(
            "Choose a base variant for focus testing",
            [f"Variant {i+1}" for i in range(len(texts))],
            index=0,
        )
        idx = int(pick.split()[-1]) - 1
        base_text = texts[idx]
        st.markdown(base_text)

    # Step 4: Focus-test loop with auto-improve
    with st.container(border=True):
        st.subheader("4) Focus test & auto‑improve")
        personas = _read_personas()
        threshold = st.slider("Passing mean intent threshold", 6.0, 9.0, 7.5, 0.1)
        rounds = st.number_input("Max revision rounds", 1, 5, 3)

        if st.button("🧪 Run focus test + auto‑improve", type="primary"):
            current = base_text
            passed = False

            for r in range(int(rounds)):
                st.write(f"**Round {r+1}** — evaluating…")
                try:
                    f = NamedBytes(current.encode("utf-8"), "copy.txt")
                    summary, df, fig, cluster_means = run_sprint(
                        file_obj=f,
                        segment="All Segments",
                        persona_groups=personas,
                        return_cluster_df=True,
                        progress_cb=None,
                    )
                except Exception as e:
                    st.exception(e)
                    st.stop()

                mean_intent = float(np.mean(df["intent"])) if not df.empty else 0.0
                st.plotly_chart(fig, use_container_width=True)
                st.write(summary)
                st.write(f"**Round {r+1} mean intent:** {mean_intent:.2f}/10")

                if mean_intent >= threshold:
                    passed = True
                    break

                # Build a short feedback brief from cluster summaries to improve copy
                # cluster_means has columns: cluster, mean_intent, summary
                tip_lines = []
                for _, row in cluster_means.iterrows():
                    tip_lines.append(f"- Cluster {int(row['cluster'])}: {row['summary']}")
                tips = "\n".join(tip_lines) if tip_lines else "- (no cluster summaries)"

                improve_brief = dict(brief)
                improve_brief["quotes_news"] = f"Persona feedback themes to address:\n{tips}"

                try:
                    improved = gen_copy(
                        improve_brief,
                        fmt="sales_page",
                        n=1,
                        trait_cfg=trait_cfg,
                        traits=traits,
                        country="Australia",
                        model=OPENAI_MODEL,
                    )
                    current = improved[0].copy
                except Exception as e:
                    st.exception(e)
                    st.stop()

            st.subheader("✅ Finalised Campaign" if passed else "⚠️ Best Attempt (threshold not reached)")
            st.markdown(current)

# Handy reset
with st.sidebar:
    if st.button("🧹 Clear guided flow state"):
        for k in list(st.session_state.keys()):
            if k.startswith("guidance_") or k in {"chosen_theme"}:
                del st.session_state[k]
        st.toast("State cleared.")
