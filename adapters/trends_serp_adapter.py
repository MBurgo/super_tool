# adapters/trends_serp_adapter.py
from __future__ import annotations

import os
import asyncio
import httpx
from bs4 import BeautifulSoup
import streamlit as st

# Provided by pip package "google-search-results" (import name: serpapi)
try:
    from serpapi import GoogleSearch
except Exception as e:  # noqa: BLE001
    GoogleSearch = None
    _IMPORT_ERR = e

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

class SerpApiMissing(RuntimeError):
    """Raised when SerpAPI client or API key is missing."""

def _get_serpapi_key() -> str | None:
    # Try Streamlit secrets first
    try:
        if "serpapi" in st.secrets:
            key = st.secrets["serpapi"].get("api_key")
            if key:
                return key
    except Exception:
        pass
    # Then environment variables
    return os.getenv("SERPAPI_API_KEY") or os.getenv("SERP_API_KEY")

def _require_serpapi() -> str:
    if GoogleSearch is None:
        raise SerpApiMissing(
            "SerpAPI client not installed. Add `google-search-results` to requirements.txt."
        )
    key = _get_serpapi_key()
    if not key:
        raise SerpApiMissing(
            "No SerpAPI key found. Add `[serpapi].api_key` to Streamlit secrets or set "
            "SERPAPI_API_KEY / SERP_API_KEY in the environment."
        )
    return key

def fetch_trends_and_news(query: str = "asx 200"):
    """
    Returns: (news_results, top_stories, trends_rising, trends_top)
    Each element is a list[dict] like what SerpAPI returns.
    """
    api_key = _require_serpapi()

    news = GoogleSearch({
        "api_key": api_key,
        "engine": "google",
        "q": query,
        "tbm": "nws",
        "num": "40",
        "google_domain": "google.com.au",
        "gl": "au",
        "hl": "en",
        "location": "Australia",
        "tbs": "qdr:d",
        "no_cache": "true",
    }).get_dict().get("news_results", []) or []

    top_stories = GoogleSearch({
        "api_key": api_key,
        "q": query,
        "gl": "au",
        "hl": "en",
    }).get_dict().get("top_stories", []) or []

    trends_raw = GoogleSearch({
        "api_key": api_key,
        "engine": "google_trends",
        "q": "/m/0bl5c2",          # ASX 200 topic
        "geo": "AU",
        "data_type": "RELATED_QUERIES",
        "tz": "-600",
        "date": "now 4-H",
    }).get_dict().get("related_queries", {}) or {}

    rising = trends_raw.get("rising", []) or []
    top = trends_raw.get("top", []) or []

    return news, top_stories, rising, top

async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and "content" in tag.attrs and tag["content"].strip():
            return tag["content"].strip()
        return "No Meta Description"
    except Exception:
        return "Error Fetching Description"

async def fetch_meta_descriptions(urls: list[str], limit: int = 10) -> list[str]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient(follow_redirects=True) as session:
        async def bound(u):
            async with sem:
                return await _grab_desc(session, u)
        return await asyncio.gather(*(bound(u) for u in urls))
