# adapters/trends_serp_adapter.py
from __future__ import annotations

import os, time, asyncio
from typing import Tuple, List, Dict, Any

import httpx
from bs4 import BeautifulSoup

# Optional: Streamlit is only used inside try/except to avoid Secrets parsing crashes
try:
    import streamlit as st
except Exception:
    st = None  # not running under Streamlit (e.g., unit tests)

SERP_ENDPOINT = "https://serpapi.com/search.json"

# Same “real browser” headers we used elsewhere to reduce 403s on meta fetches
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def get_serpapi_key() -> str | None:
    """
    Prefer environment variables, then fall back to Streamlit secrets if present.
    Returns None if nothing found. Wraps secrets access to avoid StreamlitSecretNotFoundError.
    """
    # 1) Env (most reliable on Streamlit Cloud)
    key = os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERP_API_KEY")
    if key:
        return key

    # 2) Secrets (guarded)
    if st is not None:
        try:
            # secret schema used in your earlier apps: [serpapi] api_key="..."
            return st.secrets["serpapi"]["api_key"]
        except Exception:
            # allow None
            return None
    return None


def _serp_get(params: Dict[str, Any], api_key: str, tries: int = 4, timeout: float = 30.0) -> Dict[str, Any]:
    """
    Minimal SerpAPI GET via HTTPX with exponential backoff.
    """
    q = params.copy()
    q["api_key"] = api_key
    for i in range(tries):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(SERP_ENDPOINT, params=q)
                if r.status_code == 200:
                    return r.json()
                # Retry on 429/5xx
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"SerpAPI {r.status_code}")
                # Non-retriable -> return empty
                return {}
        except Exception:
            time.sleep(min(10, 2 ** i))
    return {}


def fetch_trends_and_news(
    api_key: str | None = None,
    *,
    topic_id: str = "/m/0bl5c2",   # Google Trends topic for ASX 200
    query: str = "asx 200",        # News query
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_trends, news_results)
    rising_trends: list of dicts like {"query": "...", "value": 123}
    news_results:  list of dicts like {"title": "...", "link": "...", "snippet": "...", ...}
    """
    key = api_key or get_serpapi_key()
    if not key:
        raise RuntimeError(
            'SerpAPI key not found. Set env SERPAPI_API_KEY or add to Streamlit secrets as [serpapi] api_key="...".'
        )

    # ---- Trends (Related Queries / Rising) ----
    trends_params = {
        "engine": "google_trends",
        "data_type": "RELATED_QUERIES",
        "q": topic_id,       # use topic id for ASX 200 for more relevance
        "geo": "AU",
        "date": "now 4-H",
        "tz": "-600",
        "no_cache": "true",
    }
    t_json = _serp_get(trends_params, key)
    related = t_json.get("related_queries", {}) if isinstance(t_json, dict) else {}
    rising = related.get("rising", []) or []

    # ---- News (Google News via SerpAPI) ----
    news_params = {
        "engine": "google",
        "q": query,
        "tbm": "nws",                # News vertical
        "google_domain": "google.com.au",
        "gl": "au",
        "hl": "en",
        "num": "40",
        "no_cache": "true",
    }
    n_json = _serp_get(news_params, key)
    raw_news = n_json.get("news_results", []) or []

    # Normalise a small subset (title/link/snippet/source/date)
    news = []
    for it in raw_news:
        news.append({
            "title": it.get("title") or "",
            "link": it.get("link") or "",
            "snippet": it.get("snippet") or "",
            "source": (it.get("source") or {}).get("name") if isinstance(it.get("source"), dict) else it.get("source"),
            "date": it.get("date"),
            "thumbnail": (it.get("thumbnail") or {}).get("static") if isinstance(it.get("thumbnail"), dict) else it.get("thumbnail"),
        })

    return rising, news


# ------------- Meta-description fetch (async) ----------------

async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=12.0)
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


async def fetch_meta_descriptions(urls: List[str], limit: int = 8) -> List[str]:
    """
    Concurrently fetch <meta name="description"> for a list of URLs.
    """
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient() as session:
        async def bound(u):
            async with sem:
                return await _grab_desc(session, u)
        return await asyncio.gather(*(bound(u) for u in urls))


def enrich_news_with_meta(news_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Adds 'meta_description' to each news dict. Falls back to 'snippet' if meta fails.
    """
    urls = [r.get("link", "") for r in news_rows]
    try:
        metas = asyncio.run(fetch_meta_descriptions(urls))
    except RuntimeError:
        # If we're already inside an event loop (rare on Streamlit), do a simple sequential fetch
        metas = []
        for u in urls:
            try:
                with httpx.Client() as client:
                    r = client.get(u, headers=BROWSER_HEADERS, follow_redirects=True, timeout=12.0)
                    if r.status_code != 200:
                        metas.append(f"HTTP {r.status_code}")
                    else:
                        soup = BeautifulSoup(r.content, "lxml")
                        tag = soup.find("meta", attrs={"name": "description"})
                        metas.append(tag["content"].strip() if tag and "content" in tag.attrs else "No Meta Description")
            except Exception:
                metas.append("Error Fetching Description")

    out = []
    for row, meta in zip(news_rows, metas):
        d = dict(row)
        if not meta or meta.startswith("HTTP") or meta.startswith("Error"):
            d["meta_description"] = row.get("snippet", "No Meta Description")
        else:
            d["meta_description"] = meta
        out.append(d)
    return out


__all__ = [
    "get_serpapi_key",
    "fetch_trends_and_news",
    "fetch_meta_descriptions",
    "enrich_news_with_meta",
]
