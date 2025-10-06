# adapters/copywriter_mf_adapter.py
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
    out: list[str] = []
    for name, score in traits.items():
        c = cfg.get(name)
        if not c:
            continue
        if score >= c["high_threshold"]:
            out.append(c["high_rule"])
        elif score <= c["low_threshold"]:
            out.append(c["low_rule"])
        elif c.get("mid_rule"):
            out.append(c["mid_rule"])
    return out

def _enforce_len(text: str, min_w: int, max_w: int | None) -> str:
    words = text.split()
    if max_w and len(words) > max_w:
        return " ".join(words[:max_w]) + "…"
    return text

def generate(
    brief: dict,
    fmt: str,
    n: int,
    *,
    trait_cfg: dict,
    traits: dict,
    country: str = "Australia",
    model: str = "gpt-4.1",
) -> List[CreativeVariant]:
    # Select copy type + structure
    copy_type = "📧 Email" if fmt in {"email", "email_subject"} else "📝 Sales Page"
    structure = (
        "### Subject Line\n### Greeting\n### Body (benefits, urgency, proofs)\n### Call-to-Action\n### Sign-off"
        if copy_type.startswith("📧")
        else "## Headline\n### Introduction\n### Key Benefit Paragraphs\n### Detailed Body\n### Call-to-Action"
    )

    # Length rules
    length_choice = brief.get("length_choice", "📏 Short (100–200 words)")
    min_len, max_len = LENGTH_RULES[length_choice]
    length_phrase = (
        f"between {min_len} and {max_len} words" if max_len else f"at least {min_len} words"
    )

    # Trait enforcement text
    hard_requirements = "\n".join(_trait_rules(traits, trait_cfg)) or "- None"

    # System message
    system_msg = dedent("""
    You are The Motley Fool’s senior direct‑response copy chief.
    • Use Markdown headings and standard '-' bullets.
    • Never make guaranteed return claims.
    """).strip()

    # Country rules appended explicitly (no f-string braces risk)
    country_line = COUNTRY_RULES.get(country, "Use the audience's local style and currency.")
    system_msg = f"{system_msg}\n{country_line}\nAppend this italic line at the end: {DISC}"

    # A literal JSON example as plain text (no f-string!)
    json_contract = (
        "{\n"
        '  "items": [\n'
        '    {"plan": "<the bullet outline>", "copy": "<the finished marketing copy>"}\n'
        "  ]\n"
        "}"
    )

    # Build the user instruction carefully (only inject variables, no literal braces)
    user_msg = dedent(f"""
    Produce {n} variations. Respond ONLY as JSON matching this shape (no extra keys, no commentary):

    {json_contract}

    The array must contain exactly {n} objects.

    #### Structure to Follow
    {structure}

    #### Hard Requirements
    {hard_requirements}

    #### Campaign Brief
    - Hook: {brief.get('hook','')}
    - Details: {brief.get('details','')}
    - Offer: Special {brief.get('offer_price','')} (Retail {brief.get('retail_price','')}), Term {brief.get('offer_term','')}
    - Reports: {brief.get('reports','')}
    - Stocks to Tease: {brief.get('stocks_to_tease','')}
    - Quotes/News: {brief.get('quotes_news','')}

    #### Length Requirement
    Write {length_phrase}. Limit bullet lists to three or fewer.
    """).strip()

    # Call model
    raw = call_gpt_json(
        [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        model=model,
    )

    data = safe_json(raw) or {}
    items = data.get("items") or []
    out: List[CreativeVariant] = []

    for i, it in enumerate(items[:n]):
        text = (it.get("copy") or "").strip()

        if text and DISC not in text:
            text += f"\n\n{DISC}"
        elif not text:
            text = DISC

        text = _enforce_len(text, min_len, max_len)

        out.append(
            CreativeVariant(
                id=f"mf_{uuid.uuid4().hex[:8]}_{i+1}",
                brief_id=brief.get("id", "brief"),
                format=fmt,
                copy=text,
                rationale="mf_copywriter",
                meta={
                    "plan": (it.get("plan") or "").strip(),
                    "country": country,
                    "length_choice": length_choice,
                },
                version=1,
            )
        )

    return out
