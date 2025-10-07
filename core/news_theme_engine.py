# core/news_theme_engine.py
# News-driven theming: cluster AU finance headlines, label clusters, return usable themes.
# Python 3.11 compatible.

from typing import List, Dict, Any, Optional, Tuple
import math
import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans

# We rely on your existing helper that wraps OpenAI and returns JSON strings
from core.synth_utils import call_gpt_json

# ------------------------ text utils ------------------------

_STOP = {
    "the","and","of","to","for","in","on","at","by","with","a","an","is","are","as","from",
    "vs","vs.","amid","after","before","over","under","more","less","than","up","down",
    "new","will","may","sees","see","today","this","week","month","report","reports",
    "ahead","near","hits","asx","amp","amp;","australia","au","stock","stocks","shares"
}

def _normalize_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _mk_doc(title: str, snippet: str) -> str:
    title = _normalize_text(title)
    snippet = _normalize_text(snippet)
    return f"{title}. {snippet}" if snippet else title

def _top_terms_from_centroid(centroid: np.ndarray, feature_names: np.ndarray, k: int = 6) -> List[str]:
    idx = np.argsort(centroid)[::-1][:k]
    terms: List[str] = []
    for i in idx:
        t = feature_names[i]
        if t.lower() in _STOP:
            continue
        if re.fullmatch(r"\d+", t):
            continue
        terms.append(t)
    # dedupe preserving order
    seen = set()
    out = []
    for t in terms:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out[:k]

def _label_from_terms(terms: List[str]) -> str:
    if not terms:
        return "Market theme"
    label = " ".join(terms[:3]).strip()
    return label.title()

def _choose_k(n_articles: int) -> int:
    # Simple heuristic: 3..8 topics depending on how much news we have
    if n_articles <= 8:
        return 3
    if n_articles <= 15:
        return 4
    if n_articles <= 24:
        return 5
    if n_articles <= 36:
        return 6
    if n_articles <= 48:
        return 7
    return 8

def _prep_documents(news: List[Dict[str, Any]]) -> Tuple[List[str], List[Dict[str, Any]]]:
    docs: List[str] = []
    items: List[Dict[str, Any]] = []
    seen = set()
    for n in news or []:
        title = (n.get("title") or "").strip()
        link = (n.get("link") or "").strip()
        if not title or not link:
            continue
        # prevent exact dups by title+source
        key = f"{title.lower()}::{(n.get('source') or '').lower()}"
        if key in seen:
            continue
        seen.add(key)
        doc = _mk_doc(title, n.get("snippet") or "")
        docs.append(doc)
        items.append(n)
    return docs, items

# ------------------------ theming core ------------------------

def analyze_news_to_themes(
    news: List[Dict[str, Any]],
    rising: Optional[List[Dict[str, Any]]] = None,
    *,
    country: str = "Australia",
    top_k: Optional[int] = None,
    use_llm: bool = True,
    model: str = "gpt-4o-mini",
) -> List[Dict[str, Any]]:
    """
    Returns a sorted list of theme dicts:
      {
        "query": str               # good human-facing theme label
        "score": float             # strength proxy (article count-weighted)
        "keywords": List[str]      # top terms for recall/targeting
        "reason": str              # analyst-style explanation
        "articles": [ {title, link, source, date} ... ]  # representative headlines
      }
    Uses TF-IDF + KMeans to form clusters, then optionally calls LLM to refine labels/summary.
    """
    docs, items = _prep_documents(news)
    if not docs:
        # fall back to rising if no news
        themes: List[Dict[str, Any]] = []
        for r in (rising or [])[:10]:
            q = (r.get("query") or "").strip()
            if not q:
                continue
            themes.append({
                "query": q.title(),
                "score": float(r.get("value") or 0),
                "keywords": [q],
                "reason": "Trending query (no news available).",
                "articles": [],
            })
        return themes

    # Vectorize
    vec = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=5000,
        min_df=1
    )
    X = vec.fit_transform(docs)
    n = X.shape[0]
    k = top_k or _choose_k(n)

    # Cluster
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(X)
    feature_names = vec.get_feature_names_out()

    # Group items per cluster
    buckets: Dict[int, List[int]] = defaultdict(list)
    for i, c in enumerate(labels):
        buckets[c].append(i)

    # Build raw themes
    raw_themes: List[Dict[str, Any]] = []
    for cid, idxs in buckets.items():
        centroid = km.cluster_centers_[cid]
        terms = _top_terms_from_centroid(centroid, feature_names, k=8)
        label = _label_from_terms(terms)
        reps = idxs[:5]  # representative articles (first few)
        arts = [{
            "title": items[i].get("title", ""),
            "link": items[i].get("link", ""),
            "source": items[i].get("source", ""),
            "date": items[i].get("date", ""),
        } for i in reps]
        raw_themes.append({
            "label": label,
            "terms": terms,
            "idxs": idxs,
            "articles": arts,
            "score": float(len(idxs)),
        })

    # Sort by score desc
    raw_themes.sort(key=lambda d: (-d["score"], d["label"]))

    # Optional LLM refinement: generate cleaner label and a short reason
    themes: List[Dict[str, Any]] = []
    for rt in raw_themes:
        label = rt["label"]
        terms = rt["terms"]
        arts = rt["articles"]
        reason = "Theme derived from clustering of AU finance headlines."
        query = label

        if use_llm and model:
            # Build compact input for the LLM
            titles = "; ".join([a["title"] for a in arts if a.get("title")][:3])
            sys = (
                f"You are a financial analyst for {country}. "
                "Given a set of top terms and representative headlines, produce a crisp campaign theme."
            )
            user = (
                "Top terms: " + ", ".join(terms[:8]) + "\n"
                "Sample headlines: " + titles + "\n\n"
                "Return JSON with keys: label (<= 60 chars), reason (<= 180 chars), keywords (3-6 short phrases)."
            )
            try:
                raw = call_gpt_json(
                    [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                    model=model,
                )
                import json
                data = json.loads(raw)
                lbl = (data.get("label") or "").strip()
                rsn = (data.get("reason") or "").strip()
                kw = data.get("keywords") or []
                if lbl:
                    label = lbl
                if rsn:
                    reason = rsn
                if isinstance(kw, list) and kw:
                    terms = [str(x) for x in kw][:8]
                    query = label
            except Exception:
                # keep heuristic label/reason
                pass

        themes.append({
            "query": query,
            "score": rt["score"],
            "keywords": terms[:8],
            "reason": reason,
            "articles": arts,
        })

    # Cap to 10 to keep UI tidy
    return themes[:10]
