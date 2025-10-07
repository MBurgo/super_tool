# adapters/copywriter_mf_adapter.py
from __future__ import annotations

import uuid
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
}

def _enforce_len(text: str, lo: int | None, hi: int | None) -> str:
    # Advisory only; we rely on prompt control. No brutal post-trim that wrecks sentences.
    return text.strip()

def generate(
    brief: Dict[str, Any],
    fmt: str = "sales_page",
    n: int = 3,
    trait_cfg: Dict[str, Any] | None = None,
    traits: Dict[str, Any] | None = None,
    country: str = "Australia",
    model: str = "gpt-4o-mini",
    length_choice: str = "📐 Medium (200–500 words)",
) -> List[CreativeVariant]:
    """
    Return up to n CreativeVariant objects. Uses call_gpt_json to get structured items with 'copy' and 'plan'.
    """
    trait_cfg = trait_cfg or {}
    traits = traits or {}

    lo, hi = LENGTH_RULES.get(length_choice, (200, 550))
    length_phrase = f"between {lo} and {hi} words" if hi else f"at least {lo} words"

    system_msg = dedent(f'''
    You are a senior direct-response copywriter for a regulated financial publisher in {country}.
    Write persuasive, compliant copy for retail investors. Always include the exact disclaimer at the end:
    {DISC}

    Output MUST be valid JSON in this schema:
    {{
      "items": [{{"copy": "string", "plan": "string"}}]
    }}

    Constraints:
    - Maintain an informative, trustworthy tone suitable for Australian investors.
    - Do not claim certainty. Avoid promissory language.
    - Include a clear CTA for a low-cost, entry-level newsletter subscription.
    - Honour the requested structure if provided.
    ''').strip()

    structure = brief.get("structure") or "Hook, Problem, Insight, Proof, Offer, CTA"
    hard_requirements = brief.get("requirements") or "Avoid promissory language. Mention risk. Include price and term."

    user_msg = dedent(f'''
    Generate {n} alternative {fmt.replace("_", " ")} variants for the following campaign brief.
    Each variant must be {length_phrase} and end with the exact disclaimer line:
    {DISC}

    ## Structure to Follow
    {structure}

    ## Hard Requirements
    {hard_requirements}

    ## Campaign Brief
    - Theme: {brief.get('theme','')}
    - Hook: {brief.get('hook','')}
    - Details: {brief.get('details','')}
    - Offer: {brief.get('offer_price','')} for {brief.get('offer_term','')}
    - Reports: {brief.get('reports','')}
    - Stocks to Tease: {brief.get('stocks_to_tease','')}
    - Quotes/News: {brief.get('quotes_news','')}

    ## Trait Emphasis
    Consider these weighted traits if relevant: {traits}
    ''').strip()

    raw = call_gpt_json(
        [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        model=model,
    )

    data = safe_json(raw) or {}
    items = data.get("items") or []
    out: List[CreativeVariant] = []

    for i, it in enumerate(items[:n]):
        text = (it.get("copy") or "").strip()
        if not text:
            continue
        text = _enforce_len(text, lo, hi)
        if DISC not in text:
            text = f"{text.rstrip()}\n\n{DISC}"
        out.append(
            CreativeVariant(
                id=str(uuid.uuid4()),
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
