# adapters/trends_serp_adapter.py
# Utilities for AU trends/news via SerpAPI, plus safe meta-description fetching.

from __future__ import annotations

import os
import asyncio
from typing import List, Tuple, Dict, Any

import httpx
from bs4 import BeautifulSoup

# Optional Streamlit reference (safe if not running inside Streamlit)
try:
    import streamlit as st  # type: ignore
except Exception:  # pragma: no cover
    st = None  # type: ignore

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------- 1) Key resolution ----------
def get_serpapi_key() -> str:
    """
    Resolve the SerpAPI key (secrets or environment).
      - st.secrets["serpapi"]["api_key"]
      - st.secrets["SERPAPI_API_KEY"] or st.secrets["serpapi_api_key"]
      - env: SERPAPI_API_KEY or SERP_API_KEY
    """
    key = None
    if st is not None:
        try:
            sec = st.secrets
            if "serpapi" in sec and isinstance(sec["serpapi"], dict):
                key = sec["serpapi"].get("api_key")
            if not key:
                key = sec.get("SERPAPI_API_KEY") or sec.get("serpapi_api_key")
        except Exception:
            pass

    key = key or os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY")
    if not key:
        raise RuntimeError(
            'SerpAPI key not found. Add to Streamlit secrets as:\n'
            '[serpapi]\napi_key="YOUR_KEY"\n'
            'or set the SERPAPI_API_KEY environment variable.'
        )
    return key


# ---------- 2) SerpAPI request helper ----------
def _serpapi_request(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Use serpapi.GoogleSearch if available; otherwise fallback to REST endpoint.
    """
    api_key = params.pop("api_key")
    try:
        from serpapi import GoogleSearch  # pip: google-search-results
        return GoogleSearch({**params, "api_key": api_key}).get_dict()
    except Exception:
        base = "https://serpapi.com/search.json"
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            r = client.get(base, params={"api_key": api_key, **params})
            r.raise_for_status()
            return r.json()


# ---------- 3) Public API: trends + news ----------
def fetch_trends_and_news(
    api_key: str | None = None,
    *,
    query: str = "ASX 200",
    geo: str = "AU",
    hl: str = "en",
    gl: str = "au",
    date: str = "now 4-H",
    location: str = "Australia",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_trends, news_results)
      rising_trends: SerpAPI google_trends RELATED_QUERIES (rising)
      news_results : SerpAPI google tbm=nws results
    """
    if api_key is None:
        api_key = get_serpapi_key()

    # Google Trends (Rising queries)
    t_params = {
        "api_key": api_key,
        "engine": "google_trends",
        "q": query,                 # SerpAPI accepts plain text here
        "geo": geo,
        "data_type": "RELATED_QUERIES",
        "tz": "-600",
        "date": date,
    }
    t = _serpapi_request(t_params)
    rising = t.get("related_queries", {}).get("rising", []) or []

    # Google News
    n_params = {
        "api_key": api_key,
        "engine": "google",
        "q": query,
        "google_domain": "google.com.au" if geo.upper() == "AU" else "google.com",
        "tbm": "nws",
        "gl": gl,
        "hl": hl,
        "location": location,
        "num": "40",
        "no_cache": "true",
    }
    n = _serpapi_request(n_params)
    # Prefer normalised 'news_results'; fall back to 'top_stories' if present
    news = n.get("news_results", []) or n.get("top_stories", []) or []

    return rising, news


# ---------- 4) Meta descriptions ----------
async def _fetch_one_meta(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, timeout=10, headers=BROWSER_HEADERS)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        # Try standard description, then og:description
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and tag.get("content") and tag["content"].strip():
            return tag["content"].strip()
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content") and og["content"].strip():
            return og["content"].strip()
        return "No Meta Description"
    except Exception:
        return "Error Fetching Description"


async def _fetch_meta_async(urls: List[str], limit: int = 10) -> List[str]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient(follow_redirects=True) as session:
        async def bound(u: str) -> str:
            async with sem:
                return await _fetch_one_meta(session, u)
        tasks = [bound(u) for u in urls]
        return await asyncio.gather(*tasks)


def fetch_meta_descriptions(urls: List[str], limit: int = 10) -> List[str]:
    """
    Synchronous wrapper that returns meta descriptions in input order.
    Uses concurrency under the hood.
    """
    if not urls:
        return []
    try:
        return asyncio.run(_fetch_meta_async(urls, limit=limit))
    except RuntimeError:
        # If already inside an event loop (rare in Streamlit), create a new loop
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_fetch_meta_async(urls, limit=limit))
        finally:
            loop.close()


def enrich_news_with_meta(news_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Adds a 'meta_description' to each news item, falling back to 'snippet'
    when the fetch fails or returns an error/HTTP status.
    """
    links = [i.get("link") or "" for i in news_items]
    metas = fetch_meta_descriptions(links)
    out: List[Dict[str, Any]] = []
    for item, meta in zip(news_items, metas):
        snippet = item.get("snippet") or ""
        if not meta or meta.startswith(("HTTP", "Error")):
            item["meta_description"] = snippet or "No Meta Description"
        else:
            item["meta_description"] = meta
        out.append(item)
    return out
