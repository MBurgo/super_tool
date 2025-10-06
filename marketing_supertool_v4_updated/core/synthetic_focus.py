import re, random, numpy as np, pandas as pd
from collections import defaultdict
from sklearn.cluster import KMeans
import plotly.express as px
from core.synth_utils import call_gpt, embed_texts

SYSTEM_MSG = "You are simulating an Australian retail investor responding candidly. Do not reward hype or guaranteed-return claims."

REACTION_TEMPLATE = """You are {name}, a {age}-year-old {occupation} from {location}.
Below is marketing copy. Give your honest reaction in 2 short paragraphs, then on a new line:
INTENT_SCORE: <0-10>

COPY:
---------
{creative}
---------
"""

RNG_SEED = 42

def _parse_intent(text: str) -> float:
    m = re.search(r"INTENT\s*_?SCORE\s*:\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not m: return 0.0
    try:
        val = float(m.group(1))
        return max(0.0, min(10.0, val))
    except ValueError:
        return 0.0

def get_reaction(persona: dict, creative_txt: str) -> tuple[str, float]:
    prompt = REACTION_TEMPLATE.format(**persona, creative=creative_txt)
    msgs = [{"role":"system","content":SYSTEM_MSG},{"role":"user","content":prompt}]
    text = call_gpt(msgs)
    score = _parse_intent(text)
    feedback = text.split("INTENT", 1)[0].strip() or text.strip()
    return feedback, score

def cluster_and_label(feedbacks: list[str]):
    random.seed(RNG_SEED); np.random.seed(RNG_SEED)
    vecs = embed_texts(feedbacks)
    k = min(5, max(2, int(len(feedbacks)/10)))
    km = KMeans(n_clusters=k, n_init=10, random_state=RNG_SEED).fit(vecs)
    labels = km.labels_

    buckets = defaultdict(list)
    for t, lab in zip(feedbacks, labels):
        if len(buckets[lab]) < 12: buckets[lab].append(t)

    summaries = {}
    for lab, snippets in buckets.items():
        prompt = "Summarise the common theme in one crisp sentence:\n\n" + "\n---\n".join(snippets)
        summaries[lab] = call_gpt([{"role":"system","content":"Be concise, neutral, specific."},{"role":"user","content":prompt}])
    return labels, summaries

def evaluate_copy_across_personas(copy_text: str, personas: list[dict]):
    feedbacks, scores = [], []
    for p in personas:
        fb, sc = get_reaction(
            {"name": p.get("name","Persona"), "age": p.get("demographics",{}).get("age", 35),
             "occupation": p.get("demographics",{}).get("occupation","Investor"),
             "location": p.get("demographics",{}).get("location","Australia")},
            copy_text
        )
        feedbacks.append(fb); scores.append(sc)

    labels, summaries = cluster_and_label(feedbacks)
    import pandas as pd, numpy as np
    df = pd.DataFrame({"persona":[p.get("name") for p in personas],"cluster":labels,"intent":scores,"feedback":feedbacks})
    cluster_means = (df.groupby("cluster")["intent"].mean().rename("mean_intent").reset_index())
    cluster_means["summary"] = cluster_means["cluster"].map(summaries)
    fig = px.bar(cluster_means, x="cluster", y="mean_intent", text="mean_intent", title="Mean Intent by Cluster")
    fig.update_layout(yaxis_title="Intent 0–10")
    overall = float(np.mean(scores)) if scores else 0.0
    summary = f"**Overall mean intent:** {overall:.1f}/10\n\n**Key clusters:**\n" +               "\n".join([f"- **Cluster {int(c)}** — {summaries[int(c)]}" for c in cluster_means["cluster"]])
    return summary, df, fig, cluster_means
