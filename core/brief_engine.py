# core/brief_engine.py
# Compose a publisher-grade campaign brief from news items.
# Produces a structured JSON brief and a Markdown export.

from typing import List, Dict, Any, Tuple
from textwrap import dedent
import json

from core.synth_utils import call_gpt_json


SCHEMA_EXAMPLE = {
    "summary": "one-paragraph market summary for AU retail investors",
    "drivers": ["bullet", "bullet", "bullet"],
    "risks": ["bullet", "bullet"],
    "talking_points": ["bullet", "bullet", "bullet"],
    "seo_keywords": ["asx 200", "dividend shares", "rba rates"],
    "hooks": ["short hook", "contrarian hook", "FOMO hook"],
    "email_subjects": ["subject A", "subject B", "subject C"],
    "headlines": ["headline A", "headline B", "headline C"],
    "social_captions": ["caption A", "caption B"],
    "cta_angles": [
        "Share Advisor: get the low-cost starter portfolio",
        "Share Advisor: 2 ASX ideas to watch this quarter"
    ],
    "notes": "compliance reminders, sensitivities, disclaimers if needed",
    "citations": [
        {"title": "ASX rises to record", "publisher": "AFR", "date": "2025-10-06", "url": "https://..."}
    ]
}


def _news_items_to_prompt(news: List[Dict[str, Any]], max_items: int = 18) -> str:
    lines: List[str] = []
    for i, n in enumerate(news[:max_items], start=1):
        title = n.get("title", "")
        src = n.get("source", "")
        date = n.get("date", "")
        link = n.get("link", "")
        snippet = n.get("snippet", "")
        lines.append(f"{i}. {title} — {src} — {date}\n   {snippet}\n   {link}")
    return "\n".join(lines)


def build_campaign_brief(
    topic: str,
    news: List[Dict[str, Any]],
    *,
    country: str = "Australia",
    service_name: str = "Share Advisor",
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    """
    Returns parsed dict in SCHEMA_EXAMPLE shape.
    """
    system = dedent(f"""
    You are a senior financial editor in {country} building a campaign brief for a regulated publisher.
    Output STRICT JSON only, matching this top-level schema:
    {json.dumps(SCHEMA_EXAMPLE, ensure_ascii=False)}
    • Audience: retail investors, low-to-mid experience.
    • Tone: clear, measured, opportunity-focused but compliant.
    • Do not promise results. Avoid superlatives. Mention risks.
    • Tailor "cta_angles" to the product "{service_name}".
    """).strip()

    user = dedent(f"""
    Topic: {topic}

    Source headlines (title — publisher — date, then snippet and URL):
    { _news_items_to_prompt(news, max_items=18) }

    Tasks:
    1) Write the one-paragraph "summary".
    2) List 3–6 "drivers" (forces behind the theme) and 2–4 "risks".
    3) Give 4–8 "talking_points" an editor can expand into paragraphs.
    4) Provide 8–14 "seo_keywords" (a mix of head and long-tail).
    5) Suggest 3–6 "hooks" (punchy angles), 3–7 "email_subjects", 3–7 "headlines", and 2–4 "social_captions".
    6) Provide 2–4 "cta_angles" aligned to "{service_name}" offers.
    7) Add any "notes" a compliance-minded editor should keep in mind.
    8) Build "citations" from the sources you used (title, publisher, date, url).
    """).strip()

    raw = call_gpt_json(
        [{"role": "system", "content": system},
         {"role": "user", "content": user}],
        model=model,
    )

    try:
        data = json.loads(raw)
    except Exception:
        # Attempt to salvage JSON if model added stray prose
        start = raw.find("{"); end = raw.rfind("}")
        data = json.loads(raw[start:end+1]) if start != -1 and end != -1 else {}

    # Defensive shaping
    out = {k: data.get(k) for k in SCHEMA_EXAMPLE.keys()}
    for key, val in out.items():
        if isinstance(val, list):
            out[key] = [str(x).strip() for x in val if str(x).strip()]
        elif isinstance(val, str):
            out[key] = val.strip()
    if not isinstance(out.get("citations"), list):
        out["citations"] = []
    return out


def brief_to_markdown(topic: str, brief: Dict[str, Any]) -> str:
    def section(title: str, body: str) -> str:
        return f"## {title}\n\n{body.strip()}\n\n"

    md = [f"# Campaign Brief: {topic}\n"]
    if brief.get("summary"):
        md.append(section("Summary", brief["summary"]))
    if brief.get("drivers"):
        md.append(section("Drivers", "\n".join([f"- {x}" for x in brief["drivers"]])))
    if brief.get("risks"):
        md.append(section("Risks", "\n".join([f"- {x}" for x in brief["risks"]])))
    if brief.get("talking_points"):
        md.append(section("Talking points", "\n".join([f"- {x}" for x in brief["talking_points"]])))
    if brief.get("seo_keywords"):
        md.append(section("SEO keywords", ", ".join(brief["seo_keywords"])))
    if brief.get("hooks"):
        md.append(section("Hooks", "\n".join([f"- {x}" for x in brief["hooks"]])))
    if brief.get("email_subjects"):
        md.append(section("Email subjects", "\n".join([f"- {x}" for x in brief["email_subjects"]])))
    if brief.get("headlines"):
        md.append(section("Headlines", "\n".join([f"- {x}" for x in brief["headlines"]])))
    if brief.get("social_captions"):
        md.append(section("Social captions", "\n".join([f"- {x}" for x in brief["social_captions"]])))
    if brief.get("cta_angles"):
        md.append(section("CTA angles", "\n".join([f"- {x}" for x in brief["cta_angles"]])))
    if brief.get("notes"):
        md.append(section("Notes", brief["notes"]))
    if brief.get("citations"):
        lines = []
        for i, c in enumerate(brief["citations"], start=1):
            lines.append(f"[{i}] {c.get('title','')} — {c.get('publisher','')} — {c.get('date','')} — {c.get('url','')}")
        md.append(section("Sources", "\n".join(lines)))
    return "".join(md)
