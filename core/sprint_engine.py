# core/sprint_engine.py
import random, copy, mimetypes, io, re
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd
import altair as alt

from core.tmf_synth_utils import call_gpt, embed_texts

# Optional libs (DOCX & PDF)
try:
    import docx
except Exception:
    docx = None
try:
    import PyPDF2
except Exception:
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
    p["age"] = int(np.clip(random.randint(seed.get("age", 35) - 5, seed.get("age", 35) + 5), 18, 90))
    if "income" in p:
        try:
            p["income"] = int(seed["income"] * random.uniform(0.7, 1.3))
        except Exception:
            pass
    return p

def _flat_gendered(persona_group):
    # original schema has keys "male" / "female"
    out = []
    for k in ("male", "female"):
        if k in persona_group and persona_group[k]:
            base = dict(persona_group[k])
            base["segment"] = persona_group.get("segment", "Unspecified")
            out.append(base)
    return out

def get_50_personas(segment, persona_groups):
    seeds = persona_groups if segment == SEG_ALL else [
        g for g in persona_groups if g.get("segment") == segment
    ]
    base = [p for grp in seeds for p in _flat_gendered(grp)]
    if not base:
        base = [random.choice([g for g in persona_groups for g in _flat_gendered(g)])]
    out = []
    i = 0
    while len(out) < 50:
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
    if hasattr(file_obj, "read"):
        # NamedTemporaryFile/BytesIO with .name
        fname = getattr(file_obj, "name", "uploaded.txt").lower()
        mime, _ = mimetypes.guess_type(fname)
        data = file_obj.read()
        if mime and mime.startswith("text"):
            return data.decode("utf-8", errors="ignore")
        if fname.endswith((".doc", ".docx")):
            file_obj.seek(0)
            return _extract_docx_text(file_obj)
        if fname.endswith(".pdf"):
            file_obj.seek(0)
            return _extract_pdf_text(file_obj)
        return data.decode("utf-8", errors="ignore")
    return str(file_obj)

# ───────────────── LLM pipeline ───────────────── #
def get_reaction(persona, creative_txt):
    prompt = REACTION_TEMPLATE.format(**persona, creative=creative_txt)
    msgs = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]
    text = call_gpt(msgs)
    if "INTENT_SCORE" in text:
        feedback, score_line = text.rsplit("INTENT_SCORE:", 1)
        try:
            score = float(re.findall(r"[-+]?\d*\.?\d+", score_line)[0])
        except Exception:
            score = 0.0
    else:
        feedback, score = text, 0.0
    return feedback.strip(), float(np.clip(score, 0.0, 10.0))

def _kmeans_numpy(X: np.ndarray, k: int = 5, iters: int = 20, seed: int = 42) -> np.ndarray:
    """
    Simple NumPy-only k-means to avoid scikit-learn dependency.
    Returns labels for each row of X.
    """
    rng = np.random.default_rng(seed)
    n, d = X.shape
    if n == 0:
        return np.zeros((0,), dtype=int)
    # init: choose k random unique indices
    centers = X[rng.choice(n, size=min(k, n), replace=False)]
    labels = np.zeros(n, dtype=int)

    for _ in range(iters):
        # compute distances and labels
        dists = np.linalg.norm(X[:, None, :] - centers[None, :, :], axis=2)
        new_labels = np.argmin(dists, axis=1)
        if np.array_equal(new_labels, labels) and centers.shape[0] == k:
            break
        labels = new_labels
        # recompute centers
        new_centers = []
        for c in range(centers.shape[0]):
            pts = X[labels == c]
            if len(pts) == 0:
                new_centers.append(centers[c])
            else:
                new_centers.append(pts.mean(axis=0))
        centers = np.vstack(new_centers)
        # if we had fewer centers than k because n < k, pad by duplicating
        while centers.shape[0] < k:
            centers = np.vstack([centers, centers[-1]])
    return labels

def cluster_responses(feedbacks, k=5):
    if not feedbacks:
        return np.array([], dtype=int)
    vecs = embed_texts(feedbacks)
    labels = _kmeans_numpy(vecs, k=min(k, max(1, len(feedbacks))))
    return labels

def label_clusters(feedbacks, labels):
    summaries = {}
    for lab in sorted(set(labels)):
        snippets = [t for t, l in zip(feedbacks, labels) if l == lab][:10]
        prompt = (
            "Summarise the common theme in these snippets:\n"
            + "\n---\n".join(snippets)
        )
        summaries[lab] = call_gpt([{"role": "user", "content": prompt}])
    return summaries

# ───────────────── Public API ───────────────── #
def run_sprint(
    file_obj,
    segment,
    persona_groups,
    *,
    return_cluster_df: bool = False,
    progress_cb=None,
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
        df.groupby("cluster", as_index=False)
          .agg(mean_intent=("intent", "mean"), count=("intent", "size"))
          .merge(
              pd.DataFrame(
                  {"cluster": list(summaries.keys()), "summary": list(summaries.values())}
              ),
              on="cluster",
          )
          .sort_values("cluster")
          .reset_index(drop=True)
    )

    # Altair chart (0–10 y-axis)
    fig = (
        alt.Chart(cluster_means)
        .mark_bar()
        .encode(
            x=alt.X("cluster:N", title="Cluster"),
            y=alt.Y("mean_intent:Q", title="Mean Intent (0–10)", scale=alt.Scale(domain=[0, 10])),
            tooltip=["cluster:N", alt.Tooltip("mean_intent:Q", format=".2f"), "count:Q"],
        )
        .properties(title="Mean Intent by Cluster")
    )

    summary = f"**Overall mean intent:** {float(np.mean(scores)):.1f}/10\n\n**Key clusters:**\n"
    for _, row in cluster_means.iterrows():
        summary += f"- **Cluster {int(row['cluster'])}** — {row['summary']}\n"

    if return_cluster_df:
        return summary, df, fig, cluster_means
    return summary, df, fig
