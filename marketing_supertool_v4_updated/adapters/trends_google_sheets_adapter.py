from __future__ import annotations
from typing import List, Dict, Any, Tuple
import datetime as dt
import re

import gspread
from google.oauth2.service_account import Credentials

from core.models import TrendBrief

def _mk_client(service_account_info: dict) -> gspread.Client:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
    return gspread.authorize(creds)

def _safe_ws(sheet, title: str):
    try:
        return sheet.worksheet(title)
    except Exception:
        return None

def _topic_key(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    for w in ["asx", "au", "australia", "news", "today", "stock", "stocks", "market"]:
        s = s.replace(f" {w} ", " ")
    return re.sub(r"\s+", " ", s).strip()

def get_rows(ws) -> List[Dict[str, Any]]:
    if not ws:
        return []
    try:
        return ws.get_all_records()
    except Exception:
        return []

def _audience_guess(headline: str) -> List[str]:
    t = (headline or "").lower()
    out = []
    if any(k in t for k in ["dividend", "yield", "income", "franking"]):
        out.append("income seekers")
    if any(k in t for k in ["small cap", "small-cap", "speculative", "startup"]):
        out.append("growth-oriented")
    if any(k in t for k in ["etf", "index", "passive"]):
        out.append("etf-first")
    if not out:
        out = ["general investors"]
    return list(dict.fromkeys(out))

def _priority(value: Any, idx: int) -> float:
    try:
        v = float(value)
    except Exception:
        v = 50.0
    base = min(1.0, v / 100.0)
    pos_bonus = max(0.0, 0.2 - 0.02*idx)
    return round(min(1.0, base + pos_bonus), 3)

def build_trendbriefs_from_sheet(service_account_info: dict, spreadsheet_id: str, limit: int = 8) -> List[TrendBrief]:
    client = _mk_client(service_account_info)
    sheet = client.open_by_key(spreadsheet_id)

    ws_news = _safe_ws(sheet, "Google News")
    ws_top  = _safe_ws(sheet, "Top Stories")
    ws_rise = _safe_ws(sheet, "Google Trends Rising")
    ws_topq = _safe_ws(sheet, "Google Trends Top")

    news = get_rows(ws_news)
    top  = get_rows(ws_top)
    rising = get_rows(ws_rise)
    topq = get_rows(ws_topq)

    topic_links: Dict[str, List[str]] = {}
    for row in (news + top):
        title = row.get("Title") or row.get("title")
        link = row.get("Link") or row.get("link")
        if not title or not link:
            continue
        k = _topic_key(title)
        topic_links.setdefault(k, []).append(link)

    seeds = []
    for i, r in enumerate(rising):
        q = r.get("Query") or r.get("query")
        v = r.get("Value") or r.get("value")
        if not q:
            continue
        seeds.append((q, _priority(v, i)))
        if len(seeds) >= 20:
            break

    briefs = []
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    for idx, (query, score) in enumerate(seeds[:limit]):
        k = _topic_key(query)
        links = list(dict.fromkeys(topic_links.get(k, [])))[:4]
        headline = f"{query} trend in AU searches"
        summary = f"'{query}' is surfacing in Google Trends; relevant coverage appears across AU finance headlines."
        signals = []
        if topq:
            for trow in topq[:5]:
                tq = trow.get("Query") or trow.get("query")
                if tq and _topic_key(tq) == k:
                    signals.append(f"Also top query: {tq}")
        briefs.append(TrendBrief(
            id=f"trend_{ts}_{idx:02d}",
            headline=headline,
            summary=summary,
            signals=signals,
            audiences=_audience_guess(headline),
            freshness="same_day",
            evidence_links=links,
            priority_score=score
        ))

    if len(briefs) < limit:
        extra = []
        for row in (top + news):
            t = row.get("Title") or row.get("title")
            l = row.get("Link") or row.get("link")
            if not t or not l:
                continue
            k = _topic_key(t)
            if not any(_topic_key(b.headline) == k for b in briefs):
                extra.append((t, l))
            if len(extra) >= (limit - len(briefs)):
                break
        for i, (t, l) in enumerate(extra):
            briefs.append(TrendBrief(
                id=f"trend_{ts}_b{i:02d}",
                headline=t,
                summary="News headline included due to sheet backfill.",
                signals=[],
                audiences=_audience_guess(t),
                freshness="same_day",
                evidence_links=[l],
                priority_score=0.55
            ))
    return briefs
