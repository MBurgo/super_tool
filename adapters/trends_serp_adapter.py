# adapters/trends_serp_adapter.py
# Python 3.11 compatible; lazy optional deps; robust secrets handling; non-leaky diagnostics.

from typing import Optional, Tuple, List, Dict, Any
import os
import time
import re

ADAPTER_VERSION = "2025-10-07e"
SERP_ENDPOINT = "https://serpapi.com/search.json"

# Optional imports guarded so module import never fails
try:
    import httpx  # type: ignore
except Exception:
    httpx = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore

try:
    import streamlit as st  # type: ignore
except Exception:
    st = None  # type: ignore


BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}


def _nested_get(mapping: Any, keys: List[str]) -> Optional[Any]:
    cur = mapping
    for k in keys:
        nxt = None
        try:
            nxt = cur[k]  # type: ignore[index]
        except Exception:
            try:
                nxt = cur.get(k)  # type: ignore[attr-defined]
            except Exception:
                return None
        cur = nxt
        if cur is None:
            return None
    return cur


def get_serpapi_key() -> Optional[str]:
    for name in ("SERPAPI_API_KEY", "SERP_API_KEY", "serpapi_api_key"):
        val = os.environ.get(name)
        if isinstance(val, str) and val.strip():
            return val.strip()

    if st is not None:
        sec_val = _nested_get(st.secrets, ["serpapi", "api_key"])  # type: ignore[arg-type]
        if isinstance(sec_val, str) and sec_val.strip():
            return sec_val.strip()
        for name in ("serpapi_api_key", "SERPAPI_API_KEY", "SERP_API_KEY"):
            v = _nested_get(st.secrets, [name])  # type: ignore[arg-type]
            if isinstance(v, str) and v.strip():
                return v.strip()

    return None


def serp_key_diagnostics() -> Dict[str, Any]:
    """Return lengths only. Never the actual key."""
    env = {
        "SERPAPI_API_KEY": len(os.environ.get("SERPAPI_API_KEY", "")) or 0,
        "SERP_API_KEY": len(os.environ.get("SERP_API_KEY", "")) or 0,
        "serpapi_api_key": len(os.environ.get("serpapi_api_key", "")) or 0,
    }
    secrets = {"[serpapi].api_key": 0, "serpapi_api_key": 0, "SERPAPI_API_KEY": 0, "SERP_API_KEY": 0}
    secrets_top: List[str] = []
    if st is not None:
        try:
            secrets_top = list(getattr(st, "secrets", {}).keys())  # type: ignore
        except Exception:
            secrets_top = []
        v = _nested_get(st.secrets, ["serpapi", "api_key"])  # type: ignore[arg-type]
        secrets["[serpapi].api_key"] = len(v) if isinstance(v, str) else 0
        for name in ("serpapi_api_key", "SERPAPI_API_KEY", "SERP_API_KEY"):
            t = _nested_get(st.secrets, [name])  # type: ignore[arg-type]
            secrets[name] = len(t) if isinstance(t, str) else 0
    return {
        "adapter_version": ADAPTER_VERSION,
        "module_path": __file__,
        "env_value_lengths": env,
        "secrets_value_lengths": secrets,
        "secrets_top_level_keys": secrets_top,
    }


def _http_get(url: str, params: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    if httpx is not None:
        with httpx.Client(timeout=timeout, headers=BROWSER_HEADERS) as cli:  # type: ignore
            r = cli.get(url, params=params)
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception:
                    return {}
            return {}
    if requests is not None:
        r = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=timeout)  # type: ignore
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return {}
        return {}
    raise RuntimeError("No HTTP client available (install httpx or requests).")


def _serp_get(params: Dict[str, Any], api_key: str, tries: int = 4, timeout: float = 30.0) -> Dict[str, Any]:
    q = params.copy()
    q["api_key"] = api_key
    last_err: Optional[Exception] = None
    for i in range(tries):
        try:
            return _http_get(SERP_ENDPOINT, q, timeout=timeout)
        except Exception as e:
            last_err = e
            time.sleep(min(10, 2 ** i))
    if last_err:
        raise last_err
    return {}


def fetch_trends_and_news(
    api_key: Optional[str] = None,
    *,
    query: str = "asx 200",
    geo: str = "AU",
    news_when: str = "4h",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    key = api_key or get_serpapi_key()
    if not key:
        raise RuntimeError(
            'SerpAPI key not found. Set env SERPAPI_API_KEY or add to Streamlit secrets as [serpapi] api_key="...".'
        )

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
        sections = trends.get("related_queries", []) or []
        for sec in sections:
            rising = sec.get("rising", []) or rising
        rising = [
            {"query": it.get("query") or it.get("title") or "", "value": it.get("value") or it.get("formattedValue") or 0}
            for it in rising
            if it
        ]
    except Exception:
        rising = []

    news_params = {
        "engine": "google_news",
        "q": query,
        "gl": geo.lower(),
        "hl": "en",
        "when": news_when,
    }
    news_json = _serp_get(news_params, key) or {}
    news_results: List[Dict[str, Any]] = []
    try:
        for it in news_json.get("news_results", []) or []:
            src = it.get("source", {})
            src_name = src.get("name") if isinstance(src, dict) else src
            news_results.append(
                {
                    "title": it.get("title", "") or "",
                    "link": it.get("link", "") or "",
                    "snippet": it.get("snippet", "") or "",
                    "source": src_name or "",
                    "date": it.get("date", "") or "",
                    "thumbnail": it.get("thumbnail", "") or "",
                }
            )
    except Exception:
        news_results = []

    return rising, news_results


def _extract_meta_description(html: str) -> str:
    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "lxml")  # type: ignore
        except Exception:
            try:
                soup = BeautifulSoup(html, "html.parser")  # type: ignore
            except Exception:
                soup = None  # type: ignore
        if soup is not None:
            og = soup.find("meta", attrs={"property": "og:description"})  # type: ignore
            if og and og.get("content"):
                return str(og["content"]).strip()
            tag = soup.find("meta", attrs={"name": "description"})  # type: ignore
            if tag and tag.get("content"):
                return str(tag["content"]).strip()
    m = re.search(
        r'<meta[^>]+(?:name=["\']description["\']|property=["\']og:description["\'])[^>]+content=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return "No Meta Description"


def fetch_meta_descriptions(urls: List[str], timeout: float = 12.0) -> List[str]:
    out: List[str] = []
    for url in urls:
        if not url or not url.startswith("http"):
            out.append("Invalid URL")
            continue
        try:
            if httpx is not None:
                r = httpx.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=timeout)  # type: ignore
                if r.status_code == 200:
                    out.append(_extract_meta_description(r.text))
                else:
                    out.append(f"HTTP {r.status_code}")
                continue
            if requests is not None:
                r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)  # type: ignore
                if r.status_code == 200:
                    out.append(_extract_meta_description(r.text))
                else:
                    out.append(f"HTTP {r.status_code}")
                continue
            out.append("No HTTP client available")
        except Exception:
            out.append("Error Fetching Description")
    return out


def enrich_news_with_meta(news: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    urls = [n.get("link", "") for n in news]
    metas = fetch_meta_descriptions(urls) if urls else []
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
    "ADAPTER_VERSION",
    "get_serpapi_key",
    "serp_key_diagnostics",
    "fetch_trends_and_news",
    "fetch_meta_descriptions",
    "enrich_news_with_meta",
]
