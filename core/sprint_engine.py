# core/sprint_engine.py
from __future__ import annotations

import io
import random
from typing import Tuple, List, Dict, Any, Iterable

import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.cluster import KMeans

from core.synth_utils import call_gpt_json, embed_texts  # <- your repo's module

def extract_text(file_obj: io.BytesIO | io.StringIO) -> str:
    if hasattr(file_obj, "read"):
        try:
            data = file_obj.read()
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="ignore")
            return str(data)
        except Exception:
            pass
    return ""

def _pick_k(n: int) -> int:
    if n < 12:
        return 2
    if n < 24:
        return 3
    if n < 48:
        return 4
    return 5

def get_50_personas(segment: str, persona_groups: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    base = list(persona_groups or [])
    if not base:
        return []
    # Sample with replacement to 50
    out: List[Dict[str, Any]] = []
    while len(out) < 50:
        p = random.choice(base).copy()
        p["name"] = f"{p.get('name','Persona')} v{random.randint(1,9)}"
        out.append(p)
    return out[:50]

def _json_dumps_trim(obj: Any, max_chars: int = 1000) -> str:
    import json as _json
    s = _json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= max_chars else s[:max_chars] + "…"

def _safe_json(text: str) -> Any:
    import json
    try:
        return json.loads(text)
    except Exception:
        return {}

def get_reaction(persona: Dict[str, Any], creative_txt: str) -> Tuple[str, float]:
    sys = "You are this persona evaluating a marketing message. Be candid, specific, and concise. Output JSON."
    prompt = {
        "role": "user",
        "content": (
            "Persona (JSON):\n"
            + _json_dumps_trim(persona) + "\n\n"
            "Creative to evaluate:\n"
            + creative_txt[:6000] + "\n\n"
            "Return JSON: {\n"
            '  "feedback": "one paragraph of qualitative feedback",\n'
            '  "intent": number 0-10\n'
            "}"
        )
    }
    raw = call_gpt_json([{"role": "system", "content": sys}, prompt], model="gpt-4o-mini")
    try:
        data = _safe_json(raw)
        fb = str(data.get("feedback") or "").strip()
        sc = float(data.get("intent") or 0.0)
        sc = float(np.clip(sc, 0, 10))
        return fb or "No feedback", sc
    except Exception:
        return "No feedback", 0.0

def cluster_responses(feedbacks: List[str]) -> List[int]:
    if not feedbacks:
        return []
    embs = embed_texts(feedbacks, model="text-embedding-3-small")
    k = _pick_k(len(feedbacks))
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(embs)
    return labels.tolist()

def label_clusters(feedbacks: List[str], labels: List[int]) -> Dict[int, str]:
    import re
    by_c: Dict[int, List[str]] = {}
    for fb, lb in zip(feedbacks, labels):
        by_c.setdefault(lb, []).append(fb)
    summaries: Dict[int, str] = {}
    for c, items in by_c.items():
        items_sorted = sorted(items, key=lambda s: len(s))
        mid = items_sorted[len(items_sorted)//2]
        sent = re.split(r"[.!?]\s+", mid.strip())[0]
        summaries[c] = sent[:160]
    return summaries

def run_sprint(
    *,
    file_obj: io.BytesIO | io.StringIO,
    segment: str,
    persona_groups: Iterable[Dict[str, Any]],
    progress_cb=None,
    return_cluster_df: bool = True,
):
    creative_txt = extract_text(file_obj)
    personas = get_50_personas(segment, persona_groups)
    if not creative_txt.strip() or not personas:
        df = pd.DataFrame(columns=["persona", "cluster", "intent", "feedback"])
        fig = px.bar(x=[], y=[], title="Mean Intent by Cluster")
        return "No input or personas.", df, fig, {}

    feedbacks: List[str] = []
    scores: List[float] = []
    total = len(personas)
    for idx, p in enumerate(personas, start=1):
        fb, sc = get_reaction(p, creative_txt)
        feedbacks.append(fb)
        scores.append(sc)
        if progress_cb is not None:
            try:
                progress_cb.progress(idx / total, text=f"{idx}/{total} personas")
            except Exception:
                pass

    labels = cluster_responses(feedbacks)
    summaries = label_clusters(feedbacks, labels)

    df = pd.DataFrame(
        {
            "persona": [p.get("name","Persona") for p in personas],
            "cluster": labels,
            "intent": scores,
            "feedback": feedbacks,
        }
    )

    cluster_means: Dict[int, float] = (
        df.groupby("cluster")["intent"].mean().round(2).to_dict() if not df.empty else {}
    )
    cm_df = pd.DataFrame(
        {"cluster": list(cluster_means.keys()), "mean_intent": list(cluster_means.values())}
    ).sort_values("mean_intent", ascending=False)

    fig = px.bar(cm_df, x="cluster", y="mean_intent", text="mean_intent", title="Mean Intent by Cluster")
    fig.update_layout(yaxis_title="Intent 0–10")

    summary = f"**Overall mean intent:** {np.mean(scores):.1f}/10\n\n**Key clusters:**\n"
    for c, s in summaries.items():
        summary += f"- **Cluster {c}** — {s}\n"

    if return_cluster_df:
        return summary, df, fig, cluster_means
    return summary, df, fig, cluster_means
