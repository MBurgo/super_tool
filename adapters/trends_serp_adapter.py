# adapters/trends_serp_adapter.py
# Python 3.11 compatible; lazy optional deps; robust secrets handling; non-leaky diagnostics.
# Now with resilient Trends fallbacks and news-derived themes when Trends yields nada.

from typing import Optional, Tuple, List, Dict, Any
import os
import time
import re
from collections import Counter

ADAPTER_VERSION = "2025-10-07f"
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


# ------------------------------ Secrets utils ------------------------------

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


# ------------------------------ HTTP helpers ------------------------------

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


# ------------------------------ Parsing helpers ------------------------------

def _normalize_rising(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items or []:
        q = (it.get("query") or it.get("title") or "").strip()
        if not q:
            continue
        val = it.get("value")
        if val is None:
            fv = it.get("formattedValue") or ""
            # Interpret "Breakout" as strong interest
            val = 100 if isinstance(fv, str) and fv.lower().strip() == "breakout" else 0
        try:
            val = int(val)
        except Exception:
            try:
                val = int(float(val))
            except Exception:
                val = 0
        out.append({"query": q, "value": val})
    # de-dup preserving order
    seen = set()
    uniq = []
    for d in out:
        if d["query"].lower() in seen:
            continue
        seen.add(d["query"].lower())
        uniq.append(d)
    return uniq


_STOPWORDS = {
    "the","and","of","to","for","in","on","at","by","with","a","an","is","are","as","from","vs","vs.","into",
    "amid","after","before","over","under","more","less","than","up","down","new","will","may","sees","see",
    "year","today","this","week","month","report","reports","ahead","near","hits","asx","amp","amp;"
}

def _derive_themes_from_news(news: List[Dict[str, Any]], k: int = 10) -> List[Dict[str, Any]]:
    texts: List[str] = []
    for n in news or []:
        t = (n.get("title") or "").strip()
        if t:
            texts.append(t)
    if not texts:
        return []
    bigram_counts: Counter = Counter()
    for t in texts:
        # Keep words and symbols like &/+ within tokens
        tokens = re.findall(r"[A-Za-z0-9+/&']+", t.lower())
        tokens = [w for w in tokens if len(w) > 1]
        # Build bigrams ignoring stopword-only pairs
        for i in range(len(tokens) - 1):
            a, b = tokens[i], tokens[i+1]
            if a in _STOPWORDS and b in _STOPWORDS:
                continue
            phrase = f"{a} {b}".strip()
            bigram_counts[phrase] += 1
    top = [p for p, _c in bigram_counts.most_common(k)]
    return [{"query": p, "value": 0} for p in top]


def _map_news_when_to_trends_date(news_when: str) -> str:
    nm = str(news_when or "").lower().strip()
    if nm in ("4h", "4hr", "4 hours"):
        return "now 4-H"
    if nm in ("1d", "24h", "24 hr", "24 hours"):
        return "now 1-d"
    if nm in ("7d", "7 days", "week"):
        return "now 7-d"
    # sensible default
    return "today 3-m"


# ------------------------------ Main API ------------------------------

def fetch_trends_and_news(
    api_key: Optional[str] = None,
    *,
    query: str = "asx 200",
    geo: str = "AU",
    news_when: str = "4h",
    trends_date: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (rising_trends, news_results)
      rising_trends: [{"query": str, "value": int}, ...]
      news_results:  [{"title": str, "link": str, "snippet": str, "source": str, "date": str, "thumbnail": str}, ...]
    Robust fallbacks: tries RELATED_QUERIES (rising, then top), TRENDING_SEARCHES,
    then derives themes from Google News titles if Trends is empty.
    """
    key = api_key or get_serpapi_key()
    if not key:
        raise RuntimeError(
            'SerpAPI key not found. Set env SERPAPI_API_KEY or add to Streamlit secrets as [serpapi] api_key="...".'
        )

    tdate = trends_date or _map_news_when_to_trends_date(news_when)
    geo = (geo or "AU").upper()

    # ---- Always pull News first (we can derive themes from it if Trends is empty) ----
    news_params = {
        "engine": "google_news",
        "q": query,
        "gl": geo.lower(),
        "hl": "en",
        "when": news_when,  # e.g. 4h, 1d, 7d
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

    # ---- Try RELATED_QUERIES (RISING, then TOP) across a few synonymous terms ----
    search_terms = [
        query,
        "asx 200",
        "asx200",
        "asx",
        "s&p asx 200",
        "asx index",
        "australian shares",
    ]
    rising: List[Dict[str, Any]] = []
    tried_any = False
    for term in dict.fromkeys([t for t in search_terms if t]):  # de-dup in order
        # Rising
        rq_params = {
            "engine": "google_trends",
            "data_type": "RELATED_QUERIES",
            "trend_type": "rising",
            "q": term,
            "geo": geo,
            "hl": "en",
            "date": tdate,
        }
        rq = _serp_get(rq_params, key) or {}
        tried_any = tried_any or bool(rq)
        try:
            sections = rq.get("related_queries", []) or []
            temp = []
            for sec in sections:
                temp = sec.get("rising", []) or temp
            rising = _normalize_rising(temp)
            if rising:
                break
        except Exception:
            pass

        # Top as fallback
        if not rising:
            tq_params = dict(rq_params)
            tq_params["trend_type"] = "top"
            tq = _serp_get(tq_params, key) or {}
            try:
                sections = tq.get("related_queries", []) or []
                temp = []
                for sec in sections:
                    temp = sec.get("top", []) or temp
                rising = _normalize_rising(temp)
                if rising:
                    break
            except Exception:
                pass

    # ---- TRENDING_SEARCHES fallback for AU ----
    if not rising:
        ts_params = {
            "engine": "google_trends",
            "data_type": "TRENDING_SEARCHES",
            "pn": "australia",
            "hl": "en",
            "date": tdate,
        }
        ts = _serp_get(ts_params, key) or {}
        try:
            arr = ts.get("trending_searches", []) or []
            temp = []
            for it in arr:
                title = (it.get("title") or {}).get("query") if isinstance(it.get("title"), dict) else it.get("title")
                if title:
                    temp.append({"query": title, "value": it.get("formattedTraffic", 0)})
            rising = _normalize_rising(temp)
        except Exception:
            rising = []

    # ---- Last resort: derive themes from news titles ----
    if not rising and news_results:
        rising = _derive_themes_from_news(news_results, k=10)

    return rising, news_results


# ------------------------------ Meta descriptions ------------------------------

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
