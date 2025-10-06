from core.models import CreativeVariant, EvaluationResult, Persona
from core.synthetic_focus import get_reaction
from statistics import mean

def evaluate_variant_with_synthetic(variant: CreativeVariant, personas: list[Persona]) -> EvaluationResult:
    persona_scores = {}
    qual = []
    for p in personas[:50]:
        fb, sc = get_reaction(
            {"name": p.name, "age": p.demographics.get("age", 35),
             "occupation": p.demographics.get("occupation","Investor"),
             "location": p.demographics.get("location","Australia")},
            variant.copy
        )
        persona_scores[p.id] = max(0.0, min(1.0, sc / 10.0))
        if fb: qual.append(fb)
    pa = mean(persona_scores.values()) if persona_scores else 0.0
    return EvaluationResult(
        variant_id=variant.id,
        persona_scores=persona_scores,
        qual_feedback=qual[:30],
        auto_checks={},
        predicted_ctr=0.02,
        composite_score=pa  # orchestrator will recompute final composite
    )
