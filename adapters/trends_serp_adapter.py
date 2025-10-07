# adapters/trends_serp_adapter.py
# ---------------------------------------------------------------------
# Utilities to pull AU trends + news via SerpAPI and to fetch meta
# descriptions safely (no Streamlit secrets access at import time).
# ---------------------------------------------------------------------

from __future__ import annotations

import os
import asyncio
from typing import List, Tuple, Dict, Any, Optional

import requests
import httpx
from bs4 import BeautifulSoup

# Try to import SerpAPI client; fall back to raw HTTPS if missing.
try:
    from serpapi import GoogleSearch  # pip: google-search-results
    _HAS_SERP_CLIENT = True
except Exception:
    GoogleSearch = None  # type: ignore
    _HAS_SERP_CLIENT = False

# ---------------------------------------------------------------------
# Browser headers to reduce 403s when fetching page meta descriptions
# ---------------------------------------------------------------------
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------
# 1) Key resolution (safe at runtime only)
# ---------------------------------------------------------------------
def get_serpapi_key() -> Optional[str]:
    """
    Resolve the SerpAPI key without touching Streamlit secrets at import time.
    Priority:
      1) st.secrets["serpapi"]["api_key"]  (if Streamlit and secrets exist)
      2) env var SERPAPI_API_KEY
      3) env var SERP_API_KEY
    Returns None if not found.
    """
    # Try Streamlit secrets (only inside the function to avoid early parsing)
    try:
        import streamlit as st  # local import to avoid hard dependency at import-time
        try:
            if "serpapi" in st.secrets and "api_key" in st.secrets["serpapi"]:
                return st.secrets["serpapi"]["api_key"]
        except Exception:
            # If secrets are not configured in this environment, ignore and fall back
            pass
    except Exception:
        pass

    # Env fallbacks
    for env_var in ("SERPAPI_API_KEY", "SERP_API_KEY"):
        val = os.getenv(env_var)
        if val:
            return val
    return None

# ---------------------------------------------------------------------
# 2) Low-level SerpAPI call (client or raw HTTPS)
# ---------------------------------------------------------------------
def _serpapi_call(params: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
    if not api_key:
        raise RuntimeError(
            'SerpAPI key not found. Add to Streamlit secrets as [serpapi] api_key="..." '
            "or set SERPAPI_API_KEY / SERP_API_KEY environment variable."
        )
    params = dict(params)  # copy
    params["api_key"] = api_key

    if _HAS_SERP_CLIENT:
        return GoogleSearch(params).get_dict()  # type: ignore[arg-type]
    else:
        # Fallback to raw HTTPS
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

# ---------------------------------------------------------------------
# 3) Public API: fetch AU trends (rising queries) + Google News
# ---------------------------------------------------------------------
def fetch_trends_and_news(
    api_key: Optional[str] = None,
    *,
    trends_mid: str = "/m/0bl5c2",  # Freebase MID for S&P/ASX 200
    geo: str = "AU",
    hours: int = 4,
    news_query: str = "asx 200",
    news_num: int = 40,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_trends, news_results)

    rising_trends: list of { query, value, ... } from SerpAPI google_trends
    news_results:  normalised list of { title, link, snippet }
    """
    if api_key is None:
        api_key = get_serpapi_key()

    # Google Trends (RELATED_QUERIES -> rising)
    trends_params = {
        "engine": "google_trends",
        "q": trends_mid,
        "geo": geo,
        "data_type": "RELATED_QUERIES",
        "date": f"now {hours}-H",
        "tz": "-600",  # AEST/AEDT offset used in your earlier scripts
    }
    t_json = _serpapi_call(trends_params, api_key)
    rising: List[Dict[str, Any]] = (
        t_json.get("related_queries", {}).get("rising", []) or []
    )

    # Google News
    news_params = {
        "engine": "google",
        "q": news_query,
        "tbm": "nws",
        "hl": "en",
        "gl": geo.lower(),
        "google_domain": "google.com.au" if geo.upper() == "AU" else "google.com",
        "location": "Australia" if geo.upper() == "AU" else None,
        "num": str(news_num),
        "no_cache": "true",
    }
    # strip Nones
    news_params = {k: v for k, v in news_params.items() if v is not None}
    n_json = _serpapi_call(news_params, api_key)
    news_raw: List[Dict[str, Any]] = n_json.get("news_results", []) or []

    # normalise
    news = []
    for item in news_raw:
        title = item.get("title") or "No Title"
        link = item.get("link") or ""
        snippet = item.get("snippet") or ""

        # Some SerpAPI responses put highlight words separately
        if not snippet:
            hl = item.get("snippet_highlighted_words")
            if isinstance(hl, list) and hl:
                snippet = " ".join(hl)

        news.append({"title": title, "link": link, "snippet": snippet})

    return rising, news

# ---------------------------------------------------------------------
# 4) Public API: synchronous meta-description fetcher
# ---------------------------------------------------------------------
async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return "Invalid URL"
    try:
        r = await session.get(url, timeout=10, headers=BROWSER_HEADERS)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and "content" in tag.attrs:
            content = (tag["content"] or "").strip()
            return content if content else "No Meta Description"
        return "No Meta Description"
    except Exception:
        return "Error Fetching Description"

async def _fetch_meta_async(urls: List[str], limit: int = 10) -> List[str]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient(follow_redirects=True) as session:
        async def bound(u: str) -> str:
            async with sem:
                return await _grab_desc(session, u)
        tasks = [bound(u) for u in urls]
        return await asyncio.gather(*tasks)

def fetch_meta_descriptions(urls: List[str], limit: int = 10) -> List[str]:
    """
    Synchronous wrapper that returns a list of meta descriptions matching
    the input URL order. Uses concurrency under the hood.
    """
    if not urls:
        return []
    try:
        return asyncio.run(_fetch_meta_async(urls, limit=limit))
    except RuntimeError:
        # If already inside an event loop (rare in Streamlit), create a new loop:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_fetch_meta_async(urls, limit=limit))
        finally:
            loop.close()
