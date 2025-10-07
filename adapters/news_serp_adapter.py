# adapters/news_serp_adapter.py
# Python 3.11 compatible. Robust SerpAPI Google News fetch, de-dupe, host balancing, and simple article text extraction.

from typing import Optional, List, Dict, Any, Tuple
import os
import re
from urllib.parse import urlparse

# Lazy optional deps so import never dies
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

SERP_ENDPOINT = "https://serpapi.com/search.json"

BROWSER_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

ADAPTER_VERSION = "news_serp_adapter/2025-10-07"


# ---------------- Secrets ----------------

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


# ---------------- HTTP helpers ----------------

def _http_get_json(url: str, params: Dict[str, Any], timeout: float = 25.0) -> Dict[str, Any]:
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

def _http_get_text(url: str, timeout: float = 15.0) -> str:
    if httpx is not None:
        r = httpx.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=timeout)  # type: ignore
        return r.text if r.status_code == 200 else ""
    if requests is not None:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)  # type: ignore
        return r.text if r.status_code == 200 else ""
    return ""


# ---------------- News search ----------------

def search_google_news(
    query: str,
    *,
    when: str = "24h",
    gl: str = "au",
    hl: str = "en",
    num: int = 50,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Returns list of news dicts {title, link, snippet, source, date, thumbnail}.
    De-dupes by normalised title and balances across hosts.
    """
    key = api_key or get_serpapi_key()
    if not key:
        raise RuntimeError("SerpAPI key missing for news fetch.")

    params = {
        "engine": "google_news",
        "q": query,
        "gl": gl.lower(),
        "hl": hl,
        "when": when,
        "num": min(max(num, 10), 100),
        "api_key": key,
    }
    data = _http_get_json(SERP_ENDPOINT, params) or {}
    raw = data.get("news_results", []) or []
    rows: List[Dict[str, Any]] = []
    for it in raw:
        src = it.get("source", {})
        source_name = src.get("name") if isinstance(src, dict) else src
        rows.append({
            "title": it.get("title", "") or "",
            "link": it.get("link", "") or "",
            "snippet": it.get("snippet", "") or "",
            "source": source_name or "",
            "date": it.get("date", "") or "",
            "thumbnail": it.get("thumbnail", "") or "",
        })

    # Normalize & de-dupe by title
    def norm_title(t: str) -> str:
        t = (t or "").lower().strip()
        t = re.sub(r"[^a-z0-9\s:&$%+/\-\.]", "", t)
        t = re.sub(r"\s+", " ", t)
        return t

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for r in rows:
        keyt = norm_title(r["title"])
        if not keyt or keyt in seen:
            continue
        seen.add(keyt)
        deduped.append(r)

    # Host balancing: avoid 10 from the same publisher
    by_host: Dict[str, List[Dict[str, Any]]] = {}
    for r in deduped:
        host = urlparse(r.get("link", "")).netloc.lower()
        by_host.setdefault(host, []).append(r)

    balanced: List[Dict[str, Any]] = []
    # round-robin across hosts
    hosts = list(by_host.keys())
    i = 0
    while len(balanced) < min(len(deduped), num):
        progressed = False
        for h in hosts:
            bucket = by_host.get(h, [])
            if i < len(bucket):
                balanced.append(bucket[i])
                progressed = True
                if len(balanced) >= num:
                    break
        if not progressed:
            break
        i += 1

    return balanced or deduped[:num]


# ---------------- Simple article text extraction ----------------

def extract_readable_text(html: str) -> str:
    """
    Minimal heuristic extraction so we don't drag in heavy dependencies.
    Tries <article>, then common content divs, falls back to paragraphs.
    """
    if not html:
        return ""
    if BeautifulSoup is None:
        return ""
    soup = BeautifulSoup(html, "lxml")  # type: ignore
    # remove cruft
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form"]):
        try:
            tag.decompose()
        except Exception:
            pass

    # candidates in order
    candidates = [
        ("article", {}),
        ("div", {"itemprop": "articleBody"}),
        ("div", {"class": re.compile(r"(article|story|content|post|entry)", re.I)}),
        ("section", {"class": re.compile(r"(article|story|content|post|entry)", re.I)}),
    ]
    text = ""
    for name, attrs in candidates:
        node = soup.find(name, attrs=attrs)  # type: ignore
        if node:
            ps = [p.get_text(" ", strip=True) for p in node.find_all(["p", "li"]) if p.get_text(strip=True)]
            text = "\n".join(ps)
            if len(text.split()) > 120:
                break

    if len(text.split()) < 40:
        # fall back to all paragraphs
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        text = "\n".join(ps)

    # basic cleanup
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def fetch_articles_content(urls: List[str], limit: int = 15, timeout: float = 15.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for url in urls[:limit]:
        html = _http_get_text(url, timeout=timeout)
        body = extract_readable_text(html) if html else ""
        out.append({"url": url, "text": body})
    return out
