import json, uuid
from textwrap import dedent
from typing import List, Dict, Any
from core.models import CreativeVariant
from core.synth_utils import call_gpt_json, safe_json

DISC = "*Past performance is not a reliable indicator of future results.*"

LENGTH_RULES = {
    "📏 Short (100–200 words)":        (100, 220),
    "📐 Medium (200–500 words)":       (200, 550),
    "📖 Long (500–1500 words)":        (500, 1600),
    "📚 Extra Long (1500–3000 words)": (1500, 3200),
    "📜 Scrolling Monster (3000+ words)": (3000, None),
}

COUNTRY_RULES = {
    "Australia":      "Use Australian English, prices in AUD, reference the ASX.",
    "United Kingdom": "Use British English, prices in GBP, reference the FTSE.",
    "Canada":         "Use Canadian English, prices in CAD, reference the TSX.",
    "United States":  "Use American English, prices in USD, reference the S&P 500.",
}

def _trait_rules(traits: dict, cfg: dict) -> list[str]:
    out = []
    for name, score in traits.items():
        c = cfg.get(name); 
        if not c: continue
        if score >= c["high_threshold"]: out.append(c["high_rule"])
        elif score <= c["low_threshold"]: out.append(c["low_rule"])
        elif c.get("mid_rule"): out.append(c["mid_rule"])
    return out

def _enforce_len(text: str, min_w: int, max_w: int|None) -> str:
    words = text.split()
    if len(words) < min_w: return text
    if max_w and len(words) > max_w:
        return " ".join(words[:max_w]) + "…"
    return text

def generate(brief: dict, fmt: str, n: int, *, trait_cfg: dict, traits: dict,
             country="Australia", model="gpt-4.1") -> List[CreativeVariant]:
    copy_type = "📧 Email" if fmt in {"email","email_subject"} else "📝 Sales Page"
    min_len, max_len = LENGTH_RULES[brief.get("length_choice","📏 Short (100–200 words)")]
    hard = "\n".join(_trait_rules(traits, trait_cfg))

    structure = "### Subject Line\n### Greeting\n### Body\n### Call-to-Action\n### Sign-off" if copy_type.startswith("📧") else                 "## Headline\n### Introduction\n### Key Benefit Paragraphs\n### Detailed Body\n### Call-to-Action"

    sys = dedent(f"""
    You are The Motley Fool’s senior direct‑response copy chief.
    • Use Markdown headings and normal '-' bullets.
    • Never make guaranteed return claims.
    • {COUNTRY_RULES.get(country,'Use the audience\'s local style and currency.')}
    Append this italic line at the end: {DISC}
    """).strip()

    user = dedent(f"""
    Produce {n} variations. Respond ONLY as JSON:
    {{
      "items": [{{"plan":"...","copy":"..."}}, ...]  // exactly {n} items
    }}

    #### Structure to Follow
    {structure}

    #### Hard Requirements
    {hard}

    #### Campaign Brief
    - Hook: {brief.get('hook','')}
    - Details: {brief.get('details','')}
    - Offer: Special {brief.get('offer_price','')} (Retail {brief.get('retail_price','')}), Term {brief.get('offer_term','')}
    - Reports: {brief.get('reports','')}
    - Stocks to Tease: {brief.get('stocks_to_tease','')}
    - Quotes/News: {brief.get('quotes_news','')}

    #### Length Requirement
    Write {"between " + str(min_len) + " and " + str(max_len) + " words" if max_len else "at least " + str(min_len) + " words"}.
    Limit bullet lists to three or fewer.
    """).strip()

    raw = call_gpt_json(
        [{"role":"system","content":sys},{"role":"user","content":user}], model=model
    )
    data = safe_json(raw) or {}
    items = data.get("items") or []
    out = []
    for i, it in enumerate(items[:n]):
        text = (it.get("copy") or "").strip()
        if DISC not in text:
            text += "\n\n" + DISC
        text = _enforce_len(text, min_len, max_len)
        out.append(CreativeVariant(
            id=f"mf_{uuid.uuid4().hex[:8]}_{i+1}",
            brief_id=brief.get("id","brief"),
            format=fmt,
            copy=text,
            rationale="mf_copywriter",
            meta={"plan": (it.get("plan") or "").strip(), "country": country},
            version=1
        ))
    return out
