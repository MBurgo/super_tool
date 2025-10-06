import re
from .models import CreativeVariant

BANNED_PATTERNS = [
    r"\bguaranteed returns?\b",
    r"\bno risk\b",
    r"\bget\s+rich\b",
    r"\bwill\s+double\b",
]

def check(variant: CreativeVariant) -> dict:
    text = variant.copy.lower()
    flags = {
        "forbidden_claims": any(re.search(p, text) for p in BANNED_PATTERNS),
        "length_too_long": len(variant.copy) > 1200,
        "length_too_short": len(variant.copy) < 60,
    }
    return flags

def add_compliance_disclaimer(body: str) -> str:
    disclaimer = (
        "General advice only. Consider your objectives and circumstances. "
        "Past performance is not a reliable indicator of future results."
    )
    return f"{body}\n\n{disclaimer}"
