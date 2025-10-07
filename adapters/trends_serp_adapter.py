# adapters/trends_serp_adapter.py
from __future__ import annotations

import os
import time
import asyncio
from typing import Tuple, List, Dict, Any

import httpx
from bs4 import BeautifulSoup

# Optional import of Streamlit so local/unit tests don't blow up
try:
    import streamlit as st  # type: ignore
except Exception:  # pragma: no cover
    st = None  # type: ignore

SERP_ENDPOINT = "https://serpapi.com/search.json"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}


def _secrets_has(path: List[str]) -> bool:
    """
    Return True if st.secrets has the given nested path without raising.
    Does NOT reveal any values.
    """
    if st is None:
        return False
    try:
        cur = st.secrets  # type: ignore[attr-defined]
        for key in path:
            try:
                # Try dict-style first
                cur = cur[key]  # type: ignore[index]
            except Exception:
                # Try .get if available
                try:
                    cur = cur.get(key)  # type: ignore[attr-defined]
                except Exception:
                    return False
            if cur is None:
                return False
        return True
    except Exception:
        return False


def _secrets_get(path: List[str]) -> str | None:
    """
    Safely fetch a nested value from st.secrets if present, else None.
    """
    if not _secrets_has(path):
        return None
    try:
        cur = st.secrets  # type: ignore[attr-defined]
        for key in path:
            try:
                cur = cur[key]  # type: ignore[index]
            except Exception:
                cur = cur.get(key)  # type: ignore[attr-defined]
        return str(cur) if cur else None
    except Exception:
        return None


def serp_key_sources() -> Dict[str, Dict[str, bool]]:
    """
    Non-sensitive diagnostics: which lookups appear to exist.
    Does not return or print the key itself.
    """
    env_flags = {
        "SERPAPI_API_KEY": bool(os.environ.get("SERPAPI_API_KEY")),
        "SERP_API_KEY": bool(os.environ.get("SERP_API_KEY")),
        "serpapi_api_key": bool(os.environ.get("serpapi_api_key")),
    }
    secrets_flags = {
        "[serpapi].api_key": _secrets_has(["serpapi", "api_key"]),
        "serpapi_api_key": _secrets_has(["serpapi_api_key"]),
        "SERPAPI_API_KEY": _secrets_has(["SERPAPI_API_KEY"]),
        "SERP_API_KEY": _secrets_has(["SERP_API_KEY"]),
    }
    return {"env": env_flags, "secrets": secrets_flags}


def get_serpapi_key() -> str | None:
    """
    Prefer environment variables, then Streamlit secrets if present.
    Supports both nested [serpapi].api_key and common flat keys.
    Returns None if nothing found. Never raises on missing secrets.
    """
    # 1) Env (most reliable on Streamlit Cloud)
    for name in ("SERPAPI_API_KEY", "SERP_API_KEY", "serpapi_api_key"):
        val = os.environ.get(name)
        if val:
            return val

    # 2) Secrets (guarded, no isinstance checks that block Streamlit's Secrets object)
    if st is not None:
        # Preferred schema: [serpapi] api_key="..."
        val = _secrets_get(["serpapi", "api_key"])
        if val:
            return val

        # Flat fallbacks if someone set a top-level key
        for name in ("serpapi_api_key", "SERPAPI_API_KEY", "SERP_API_KEY"):
            val = _secrets_get([name])
            if val:
                return val

    return None


def _serp_get(params: Dict[str, Any], api_key: str, tries: int = 4, timeout: float = 30.0) -> Dict[str, Any]:
    """
    Minimal SerpAPI GET via HTTPX with exponential backoff.
    """
    q = params.copy()
    q["api_key"] = api_key
    last_err: Exception | None = None
    for i in range(tries):
        try:
            with httpx.Client(timeout=timeout, headers=BROWSER_HEADERS) as cli:
                r = cli.get(SERP_ENDPOINT, params=q)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"SerpAPI {r.status_code}")
                # Non-retriable -> return empty
                return {}
        except Exception as e:  # pragma: no cover
            last_err = e
            time.sleep(min(10, 2 ** i))
    if last_err:
        raise last_err
    return {}


def fetch_trends_and_news(
    api_key: str | None = None,
    *,
    query: str = "asx 200",
    geo: str = "AU",
    news_when: str = "4h",
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
        "trend_type": "rising",
        "q": query,
        "geo": geo,
        "hl": "en",
    }
    trends = _serp_get(trends_params, key) or {}
    rising: List[Dict[str, Any]] = []
    try:
        sections = trends.get("related_queries", [])
        for sec in sections:
            # prefer 'rising' field when present
            rising = sec.get("rising", []) or rising
        rising = [
            {"query": it.get("query") or it.get("title") or "", "value": it.get("value") or it.get("formattedValue") or 0}
            for it in rising
            if it
        ]
    except Exception:  # pragma: no cover
        rising = []

    # ---- Google News ----
    news_params = {
        "engine": "google_news",
        "q": query,
        "gl": geo.lower(),
        "hl": "en",
        "when": news_when,  # e.g. 4h
    }
    news_json = _serp_get(news_params, key) or {}
    news_results: List[Dict[str, Any]] = []
    try:
        for it in news_json.get("news_results", []):
            news_results.append(
                {
                    "title": it.get("title", ""),
                    "link": it.get("link", ""),
                    "snippet": it.get("snippet", ""),
                    "source": (it.get("source", {}) or {}).get("name") if isinstance(it.get("source"), dict) else it.get("source"),
                    "date": it.get("date", ""),
                    "thumbnail": it.get("thumbnail", ""),
                }
            )
    except Exception:  # pragma: no cover
        news_results = []

    return rising, news_results


# ------------- Meta-description fetch (async) ----------------

async def _grab_desc(session: httpx.AsyncClient, url: str) -> str:
    if not url or not url.startswith("http"):
        return "Invalid URL"
    try:
        r = await session.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=12.0)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        soup = BeautifulSoup(r.content, "lxml")
        og = soup.find("meta", attrs={"property": "og:description"})
        if og and og.get("content"):
            return og["content"].strip()
        tag = soup.find("meta", attrs={"name": "description"})
        return (
            tag["content"].strip()
            if tag and "content" in tag.attrs and tag["content"].strip()
            else "No Meta Description"
        )
    except Exception:  # pragma: no cover
        return "Error Fetching Description"


async def fetch_meta_descriptions(urls: List[str], limit: int = 8) -> List[str]:
    sem = asyncio.Semaphore(limit)

    async def bounded(url: str) -> str:
        async with sem:
            async with httpx.AsyncClient(timeout=15.0, headers=BROWSER_HEADERS, follow_redirects=True) as cli:
                return await _grab_desc(cli, url)

    tasks = [bounded(u) for u in urls]
    return await asyncio.gather(*tasks)


def enrich_news_with_meta(news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    urls = [n.get("link", "") for n in news]
    try:
        metas = asyncio.run(fetch_meta_descriptions(urls)) if urls else []
    except RuntimeError:
        # In case we're already inside an event loop (Streamlit sometimes reuses), use alternative
        metas = []
        try:
            loop = asyncio.new_event_loop()
            metas = loop.run_until_complete(fetch_meta_descriptions(urls))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    out: List[Dict[str, Any]] = []
    for row, meta in zip(news, metas or []):
        d = dict(row)
        if not meta or meta.startswith("HTTP") or meta.startswith("Error"):
            d["meta_description"] = row.get("snippet", "No Meta Description")
        else:
            d["meta_description"] = meta
        out.append(d)
    for row in news[len(out):]:
        d = dict(row)
        d["meta_description"] = row.get("snippet", "No Meta Description")
        out.append(d)
    return out


__all__ = [
    "get_serpapi_key",
    "serp_key_sources",
    "fetch_trends_and_news",
    "fetch_meta_descriptions",
    "enrich_news_with_meta",
]
