# adapters/trends_serp_adapter.py
# Lightweight SerpAPI + meta description utilities (no serpapi pip dependency)

from __future__ import annotations
import os
from typing import List, Tuple, Dict, Any

import httpx
from bs4 import BeautifulSoup
import streamlit as st

SERP_ENDPOINT = "https://serpapi.com/search.json"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_serpapi_key(raise_on_missing: bool = False) -> str | None:
    """
    Resolve the SerpAPI key from Streamlit secrets (preferred) or environment.
    Checks:
      - st.secrets["serpapi"]["api_key"]
      - st.secrets["SERPAPI_API_KEY"]
      - os.environ["SERPAPI_API_KEY"] or "SERP_API_KEY" or "SERPAPI_KEY"
    """
    key = None
    try:
        # st.secrets behaves like a mapping but may raise if no secrets file
        if "serpapi" in st.secrets and "api_key" in st.secrets["serpapi"]:
            key = st.secrets["serpapi"]["api_key"]
        elif "SERPAPI_API_KEY" in st.secrets:
            key = st.secrets["SERPAPI_API_KEY"]
    except Exception:
        # If secrets not available (e.g., local run without secrets), fall through to env
        pass

    if not key:
        key = (
            os.getenv("SERPAPI_API_KEY")
            or os.getenv("SERP_API_KEY")
            or os.getenv("SERPAPI_KEY")
        )

    if raise_on_missing and not key:
        raise RuntimeError(
            "SerpAPI key not found. Add to Streamlit secrets as:\n"
            "[serpapi]\napi_key=\"...\"\n"
            "or set SERPAPI_API_KEY in the environment."
        )
    return key


def _get(client: httpx.Client, params: Dict[str, Any]) -> Dict[str, Any]:
    r = client.get(SERP_ENDPOINT, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_trends_and_news(
    api_key: str,
    *,
    google_trends_q: str = "/m/0bl5c2",  # ASX 200 topic id
    geo: str = "AU",
    date_window: str = "now 4-H",
    news_query: str = "asx 200",
    hl: str = "en",
    gl: str = "au",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_related_queries, news_results) using SerpAPI over HTTP.
    """
    if not api_key:
        raise RuntimeError("SerpAPI API key is required.")

    with httpx.Client(headers=BROWSER_HEADERS, follow_redirects=True) as client:
        # Google Trends (related queries, rising)
        trends_params = {
            "engine": "google_trends",
            "q": google_trends_q,
            "data_type": "RELATED_QUERIES",
            "geo": geo,
            "date": date_window,
            "tz": "-600",  # AEST (UTC+10) offset expressed in minutes
            "api_key": api_key,
        }
        trends = _get(client, trends_params)
        rising = (trends.get("related_queries") or {}).get("rising", []) or []

        # Google News for the same theme
        news_params = {
            "engine": "google",
            "q": news_query,
            "google_domain": "google.com.au",
            "tbm": "nws",
            "gl": gl,
            "hl": hl,
            "location": "Australia",
            "num": "40",
            "api_key": api_key,
            "no_cache": "true",
        }
        news = _get(client, news_params).get("news_results", []) or []

    return rising, news


def fetch_meta_descriptions(urls: List[str]) -> List[str]:
    """
    Fetch <meta name='description'> (or og:description) for a list of URLs.
    Synchronous (stable inside Streamlit). Returns placeholder strings on failure.
    """
    out: List[str] = []
    if not urls:
        return out

    with httpx.Client(headers=BROWSER_HEADERS, follow_redirects=True) as client:
        for u in urls:
            if not u or not u.startswith("http"):
                out.append("Invalid URL")
                continue
            try:
                r = client.get(u, timeout=15)
                if r.status_code != 200:
                    out.append(f"HTTP {r.status_code}")
                    continue
                soup = BeautifulSoup(r.content, "lxml")
                tag = (
                    soup.find("meta", attrs={"name": "description"})
                    or soup.find("meta", attrs={"property": "og:description"})
                )
                if tag and tag.get("content", "").strip():
                    out.append(tag["content"].strip())
                else:
                    out.append("No Meta Description")
            except Exception:
                out.append("Error Fetching Description")
    return out
