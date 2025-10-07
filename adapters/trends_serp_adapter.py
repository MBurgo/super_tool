# adapters/trends_serp_adapter.py
# -----------------------------------------------------------------------------
# Minimal SerpAPI + meta-description utilities used by the Guided Flow.
# - No dependency on the serpapi SDK (uses plain HTTP via `requests`)
# - Exports: get_serpapi_key, fetch_trends_and_news, fetch_meta_descriptions,
#            enrich_news_with_meta
# -----------------------------------------------------------------------------

from __future__ import annotations
import os, asyncio
from typing import List, Dict, Tuple, Optional

import requests
import httpx
from bs4 import BeautifulSoup

# Browser-like headers for publisher sites (to reduce 403s)
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SERP_BASE = "https://serpapi.com/search.json"


# ---------- Keys & config ----------
def get_serpapi_key() -> Optional[str]:
    """
    Retrieve SerpAPI key from:
      - Streamlit secrets: st.secrets["serpapi"]["api_key"] or st.secrets["SERPAPI_API_KEY"]
      - Environment: SERPAPI_API_KEY or SERP_API_KEY
    Returns None if not found.
    """
    key = None
    try:
        import streamlit as st  # import here to avoid hard dependency
        # Prefer nested config [serpapi] api_key="..."
        if isinstance(st.secrets.get("serpapi"), dict):
            key = st.secrets["serpapi"].get("api_key")
        if not key:
            # Allow flat key too
            key = st.secrets.get("SERPAPI_API_KEY") or st.secrets.get("serpapi_api_key")
    except Exception:
        pass

    if not key:
        key = os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY")
    return key


# ---------- SerpAPI fetchers (HTTP) ----------
def _serp_get(params: Dict) -> Dict:
    """GET helper with basic error handling."""
    r = requests.get(SERP_BASE, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_trends_and_news(
    serp_key: str,
    *,
    topic_id: str = "/m/0bl5c2",      # ASX 200
    geo: str = "AU",
    date: str = "now 4-H",
    q_news: str = "asx 200",
    gl: str = "au",
    hl: str = "en",
    num_news: int = 40,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Returns (rising_queries, news_results).
      rising_queries: list of {"query": str, "value": int|str}
      news_results:   list of SerpAPI news dicts (title, link, snippet, source, etc.)
    """
    if not serp_key:
        raise RuntimeError("SerpAPI key missing")

    # Google Trends (RELATED_QUERIES)
    trends_params = {
        "engine": "google_trends",
        "q": topic_id,
        "geo": geo,
        "data_type": "RELATED_QUERIES",
        "date": date,
        "tz": "-600",    # AET
        "api_key": serp_key,
    }
    trends_json = _serp_get(trends_params)
    rq = trends_json.get("related_queries", {})
    rising = rq.get("rising") or []

    # Google News
    news_params = {
        "engine": "google",
        "q": q_news,
        "google_domain": "google.com.au",
        "tbm": "nws",
        "tbs": "qdr:d",
        "gl": gl,
        "hl": hl,
        "num": str(num_news),
        "no_cache": "true",
        "api_key": serp_key,
    }
    news_json = _serp_get(news_params)
    news = news_json.get("news_results") or []

    return rising, news


# ---------- Meta description fetch ----------
async def _grab_meta(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, timeout=10, headers=BROWSER_HEADERS)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and tag.get("content"):
            return tag["content"].strip() or "No Meta Description"
        # Some sites use property="og:description"
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            return og["content"].strip() or "No Meta Description"
        return "No Meta Description"
    except Exception:
        return "Error Fetching Description"


async def _gather_meta(urls: List[str], limit: int = 10) -> List[str]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient(follow_redirects=True) as session:
        async def bounded(u):
            async with sem:
                return await _grab_meta(session, u)
        return await asyncio.gather(*(bounded(u) for u in urls))


def fetch_meta_descriptions(urls: List[str], concurrency: int = 10) -> List[str]:
    """Synchronous wrapper for async meta fetch."""
    if not urls:
        return []
    try:
        return asyncio.run(_gather_meta(urls, limit=concurrency))
    except RuntimeError:
        # If already in a loop (rare in Streamlit), fallback to sequential
        out = []
        with httpx.Client(follow_redirects=True) as c:
            for u in urls:
                try:
                    r = c.get(u, timeout=10, headers=BROWSER_HEADERS)
                    if r.status_code != 200:
                        out.append(f"HTTP {r.status_code}")
                        continue
                    soup = BeautifulSoup(r.content, "lxml")
                    tag = soup.find("meta", attrs={"name": "description"})
                    if tag and tag.get("content"):
                        out.append(tag["content"].strip() or "No Meta Description")
                    else:
                        og = soup.find("meta", attrs={"property": "og:description"})
                        if og and og.get("content"):
                            out.append(og["content"].strip() or "No Meta Description")
                        else:
                            out.append("No Meta Description")
                except Exception:
                    out.append("Error Fetching Description")
        return out


# ---------- Helpers ----------
def _dedupe_by_key(items: List[Dict], key: str) -> List[Dict]:
    seen, out = set(), []
    for it in items:
        v = (it or {}).get(key)
        if not v:
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(it)
    return out


def enrich_news_with_meta(news: List[Dict]) -> List[Dict]:
    """
    Returns list of {title, link, snippet, meta} deduped by link.
    Falls back to snippet when meta fetch fails.
    """
    rows = [
        {
            "title":  (n.get("title") or "").strip(),
            "link":   n.get("link") or "",
            "snippet": (n.get("snippet") or "").strip(),
        }
        for n in news or []
    ]
    rows = _dedupe_by_key(rows, "link")
    urls = [r["link"] for r in rows]
    metas = fetch_meta_descriptions(urls)

    out = []
    for r, m in zip(rows, metas):
        meta = m if (m and not m.startswith("HTTP") and not m.startswith("Error")) else (r["snippet"] or "No Meta Description")
        out.append({**r, "meta": meta})
    return out
