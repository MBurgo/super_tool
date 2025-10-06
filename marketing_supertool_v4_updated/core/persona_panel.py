import re, hashlib, random
from typing import List, Dict
from .models import CreativeVariant, EvaluationResult, Persona
from .scoring import simple_readability, brand_fit, composite_score

HYPE_PATTERNS = [
    r"\bget\s+rich\b",
    r"\bsecret\b",
    r"\bguarantee(?:d)?\b",
    r"\bno\s+risk\b",
    r"\bwill\s+double\b",
]
RISK_WORDS = ["risk", "volatility", "drawdown", "downside", "uncertain"]
ETF_WORDS = ["etf", "index", "index fund", "passive"]
TRADER_WORDS = ["trade", "trading", "setup", "options", "cfd", "leverage"]
INCOME_WORDS = ["dividend", "yield", "income", "franking"]
ASX_WORDS = ["asx", "small cap", "small-cap", "blue chip"]

def _stable_rand(s: str) -> random.Random:
    h = int(hashlib.sha256(s.encode()).hexdigest(), 16) % (2**32 - 1)
    return random.Random(h)

def evaluate_variant(variant: CreativeVariant, personas: List[Persona]) -> EvaluationResult:
    persona_scores: Dict[str, float] = {}
    qual = []
    for p in personas:
        t = variant.copy.lower()
        clarity = simple_readability(variant.copy)
        hype = any(re.search(h, t) for h in HYPE_PATTERNS)
        has_num = any(c.isdigit() for c in variant.copy)
        specifics = any(w in t for w in ASX_WORDS + ETF_WORDS + INCOME_WORDS)
        believability = max(0.0, min(1.0, 0.75 + (0.05 if has_num else 0) + (0.1 if specifics else 0) - (0.3 if hype else 0)))
        vf = 0.6
        if any(w in t for w in ETF_WORDS): vf += 0.2
        if any(w in t for w in INCOME_WORDS) and p.segment and ("Retirees" in p.segment or "Pre-Retirees" in p.segment): vf += 0.2
        if any(w in t for w in TRADER_WORDS) and ("Next Generation" in (p.segment or "") or "Emerging Wealth" in (p.segment or "")): vf += 0.1
        vf = max(0.0, min(1.0, vf))
        mentions_risk = any(w in t for w in RISK_WORDS)
        no_forbidden = not hype
        risk_controls = 0.5 + (0.25 if mentions_risk else 0) + (0.25 if no_forbidden else 0)
        tone_fit = brand_fit(variant.copy)

        weights = p.rubric or {"clarity":0.25,"believability":0.25,"value_fit":0.2,"risk_controls":0.2,"tone_fit":0.1}
        denom = sum(weights.values()) or 1.0
        affinity = (clarity*weights.get("clarity",0) + believability*weights.get("believability",0) +
                    vf*weights.get("value_fit",0) + risk_controls*weights.get("risk_controls",0) +
                    tone_fit*weights.get("tone_fit",0)) / denom
        persona_scores[p.id] = max(0.0, min(1.0, affinity))

    persona_affinity = sum(persona_scores.values()) / max(1, len(personas))
    rr = _stable_rand(variant.copy)
    predicted_ctr = 0.02 + (0.01 if any(c.isdigit() for c in variant.copy) else 0) + rr.uniform(-0.005, 0.005)
    readability = simple_readability(variant.copy)
    brand = brand_fit(variant.copy)
    compliance = 1.0
    comp = composite_score(persona_affinity, predicted_ctr, readability, brand, compliance)

    if len(variant.copy) > 480: qual.append("Too long")
    if not any(w in variant.copy.lower() for w in ["asx", "etf", "dividend", "yield"]): qual.append("Too vague")

    return EvaluationResult(
        variant_id=variant.id,
        persona_scores=persona_scores,
        qual_feedback=qual or ["Looks serviceable"],
        auto_checks={},
        predicted_ctr=max(0.0, predicted_ctr),
        composite_score=comp
    )
