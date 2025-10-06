from .models import EvaluationResult

def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))

def composite_score(persona_affinity: float, predicted_ctr: float,
                    readability: float, brand_fit: float, compliance: float) -> float:
    return (
        0.35 * _clip(persona_affinity) +
        0.25 * _clip(predicted_ctr) +
        0.15 * _clip(readability) +
        0.15 * _clip(brand_fit) +
        0.10 * _clip(compliance)
    )

def simple_readability(copy: str) -> float:
    ln = len(copy)
    if ln <= 80: return 0.5
    if ln >= 1200: return 0.3
    if 180 <= ln <= 480: return 0.95
    return 0.7

def brand_fit(copy: str) -> float:
    hype = any(w in copy.lower() for w in ["get rich", "secret", "shocking"])
    has_number = any(c.isdigit() for c in copy)
    specific = any(w in copy.lower() for w in ["asx", "etf", "dividend", "small-cap", "small cap"])
    score = 0.7 + (0.1 if has_number else 0) + (0.1 if specific else 0) - (0.3 if hype else 0)
    return max(0.0, min(1.0, score))
