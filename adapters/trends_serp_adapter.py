# adapters/trends_serp_adapter.py
from __future__ import annotations

import os, asyncio
from typing import List, Tuple, Dict, Any

import httpx
from bs4 import BeautifulSoup

# SerpAPI SDK (package: google-search-results)
# requirements.txt should include: google-search-results>=2.4.2
try:
    from serpapi import GoogleSearch
except Exception as e:  # pragma: no cover
    GoogleSearch = None

# Optional Streamlit (this module is also importable without Streamlit)
try:
    import streamlit as st
except Exception:
    st = None

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def _read_from_secrets() -> str | None:
    """Try several shapes in st.secrets without crashing if secrets are unavailable."""
    if st is None:
        return None
    try:
        # canonical nested: [serpapi] api_key = "..."
        sect = getattr(st, "secrets", None)
        if sect:
            # nested section
            sec = sect.get("serpapi")
            if isinstance(sec, dict):
                k = sec.get("api_key") or sec.get("API_KEY") or sec.get("key")
                if k:
                    return str(k).strip()
            # flat keys
            for kname in ("SERPAPI_API_KEY", "SERP_API_KEY", "serpapi_api_key", "serp_api_key"):
                if kname in sect:
                    v = sect.get(kname)
                    if v:
                        return str(v).strip()
    except Exception:
        # Don't blow up if Streamlit can't parse secrets yet
        return None
    return None


def get_serp_api_key() -> str:
    """
    Resolve SerpAPI key from Streamlit secrets or environment.
    Accepted locations:
      - st.secrets['serpapi']['api_key']  (preferred)
      - st.secrets['SERPAPI_API_KEY'] / ['SERP_API_KEY']
      - env SERPAPI_API_KEY / SERP_API_KEY
    """
    # 1) Streamlit secrets (various shapes)
    key = _read_from_secrets()
    # 2) Environment fallback
    key = key or os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY")
    if not key:
        raise RuntimeError(
            'SerpAPI key not found. Add to Streamlit secrets as:\n'
            '[serpapi]\napi_key="YOUR_KEY"\n'
            'or set env SERPAPI_API_KEY.'
        )
    return key.strip()


def fetch_trends_and_news(serp_api_key: str | None = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_trends, news_items).
    rising_trends: [{'query': str, 'value': int|str, ...}, ...]
    news_items:     SerpAPI news_results list: [{'title','link','snippet',...}, ...]
    """
    if GoogleSearch is None:
        raise RuntimeError("Package 'google-search-results' is not installed.")

    api_key = serp_api_key or get_serp_api_key()

    # ---- Google Trends: related queries (AU, last 4 hours)
    t_params = {
        "api_key": api_key,
        "engine": "google_trends",
        "q": "/m/0bl5c2",     # ASX 200 topic id (as per your earlier scripts)
        "geo": "AU",
        "data_type": "RELATED_QUERIES",
        "tz": "-600",
        "date": "now 4-H",
    }
    t_res = GoogleSearch(t_params).get_dict()
    rising = (t_res.get("related_queries") or {}).get("rising", []) or []

    # ---- Google News (AU, last 24h)
    n_params = {
        "api_key": api_key,
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


async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, timeout=10, headers=BROWSER_HEADERS, follow_redirects=True)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and "content" in tag.attrs and tag["content"].strip():
            return tag["content"].strip()
        return "No Meta Description"
    except Exception:
        return "Error Fetching Description"


async def fetch_meta_descriptions(urls: List[str], limit: int = 10) -> List[str]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient() as session:
        async def bound(u):
            async with sem:
                return await _grab_desc(session, u)
        return await asyncio.gather(*(bound(u) for u in urls))
