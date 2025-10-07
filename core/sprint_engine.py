# core/sprint_engine.py
from __future__ import annotations

import copy
import io
import mimetypes
import random
from pathlib import Path
from typing import Tuple, List, Dict, Any

import numpy as np
import pandas as pd
import plotly.express as px
from sklearn.cluster import KMeans

from core.tmf_synth_utils import call_gpt, embed_texts

# Optional libs (DOCX & PDF)
try:
    import docx
except ImportError:
    docx = None
try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

SEG_ALL = "All Segments"
SYSTEM_MSG = "You are simulating an investor responding in a conversational, candid tone."

REACTION_TEMPLATE = """You are {name}, a {age}-year-old {occupation} from {location}.
Below is a marketing creative you can read. Give your honest reaction in 2 short paragraphs, then
score your likelihood of taking the CTA from 0–10 on its own line in the form:
INTENT_SCORE: <number>

CREATIVE:
---------
{creative}
---------
"""

# ───────────────── Persona helpers ───────────────── #
def mutate_persona(seed, idx):
    p = copy.deepcopy(seed)
    first = p["name"].split()[0]
    p["name"] = f"{first} Variant {idx+1}"
    p["age"] = random.randint(max(18, seed["age"] - 5), seed["age"] + 5)
    p["income"] = int(seed.get("income", 80000) * random.uniform(0.7, 1.3))
    # Normalise a few keys that the template expects
    p.setdefault("occupation", "Investor")
    p.setdefault("location", p.get("location", "Australia"))
    return p


def get_50_personas(segment, persona_groups):
    seeds = persona_groups if segment == SEG_ALL else [
        g for g in persona_groups if g.get("segment") == segment
    ]
    base = []
    for grp in seeds:
        for gender in ("male", "female"):
            if grp.get(gender):
                base.append(grp[gender])
    out = []
    i = 0
    while len(out) < 50 and base:
        out.append(mutate_persona(random.choice(base), i))
        i += 1
    return out[:50]

# ───────────────── Creative extraction ───────────────── #
def _extract_pdf_text(file_obj) -> str:
    if PyPDF2 is None:
        return "[PDF uploaded, but PyPDF2 not installed.]"
    reader = PyPDF2.PdfReader(io.BytesIO(file_obj.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx_text(file_obj) -> str:
    if docx is None:
        return "[DOC/DOCX uploaded, but python-docx not installed.]"
    d = docx.Document(io.BytesIO(file_obj.read()))
    return "\n".join(p.text for p in d.paragraphs)


def extract_text(file_obj) -> str:
    fname = Path(getattr(file_obj, "name", "upload")).name.lower()
    mime, _ = mimetypes.guess_type(fname)

    if mime and mime.startswith("text"):
        return file_obj.read().decode("utf-8", errors="ignore")
    if fname.endswith((".doc", ".docx")):
        return _extract_docx_text(file_obj)
    if fname.endswith(".pdf"):
        return _extract_pdf_text(file_obj)
    try:
        return file_obj.read().decode("utf-8", errors="ignore")
    except Exception:
        return "[Unsupported file format. Please upload txt, html, md, doc, docx, or pdf.]"

# ───────────────── LLM pipeline ───────────────── #
def get_reaction(persona, creative_txt: str) -> Tuple[str, float]:
    prompt = REACTION_TEMPLATE.format(**persona, creative=creative_txt)
    msgs = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]
    text = call_gpt(msgs)
    if "INTENT_SCORE" in text:
        feedback, score_line = text.rsplit("INTENT_SCORE:", 1)
        try:
            score = float(score_line.strip())
        except ValueError:
            score = 0.0
    else:
        feedback, score = text, 0.0
    return feedback.strip(), score


def cluster_responses(feedbacks: List[str], k: int = 5) -> np.ndarray:
    vecs = embed_texts(feedbacks)
    km = KMeans(n_clusters=k, n_init="auto").fit(vecs)
    return km.labels_


def label_clusters(feedbacks: List[str], labels: np.ndarray) -> Dict[int, str]:
    summaries = {}
    for lab in sorted(set(labels)):
        snippets = [t for t, l in zip(feedbacks, labels) if l == lab][:10]
        prompt = (
            "Summarise the common theme in these snippets:\n"
            + "\n---\n".join(snippets)
        )
        summaries[lab] = call_gpt([{"role": "user", "content": prompt}]) or "Theme not available"
    return summaries

# ───────────────── Public API ───────────────── #
def run_sprint(
    file_obj,
    segment: str,
    persona_groups: List[Dict[str, Any]],
    *,
    return_cluster_df: bool = False,
    progress_cb=None,  # optional Streamlit progress object
):
    creative_txt = extract_text(file_obj)
    personas = get_50_personas(segment, persona_groups)

    feedbacks, scores = [], []
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
            "persona": [p["name"] for p in personas],
            "cluster": labels,
            "intent": scores,
            "feedback": feedbacks,
        }
    )

    cluster_means = (
        df.groupby("cluster")["intent"].mean()
        .rename("mean_intent")
        .reset_index()
        .merge(
            pd.DataFrame(
                {"cluster": list(summaries.keys()), "summary": list(summaries.values())}
            ),
            on="cluster",
        )
    )

    fig = px.bar(
        cluster_means,
        x="cluster",
        y="mean_intent",
        text="mean_intent",
        title="Mean Intent by Cluster",
    )
    fig.update_layout(yaxis_title="Intent 0–10")

    summary = f"**Overall mean intent:** {np.mean(scores):.1f}/10\n\n**Key clusters:**\n"
    for c, s in summaries.items():
        summary += f"- **Cluster {c}** — {s}\n"

    if return_cluster_df:
        return summary, df, fig, cluster_means
    return summary, df, fig
