import json, re
from typing import List, Dict, Any
from core.models import Persona

def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s[:64]

def _merge_lists(a, b):
    seen = set()
    out = []
    for item in (a or []) + (b or []):
        if item not in seen:
            out.append(item); seen.add(item)
    return out

def _merge_weights(base: Dict[str, float], over: Dict[str, float]) -> Dict[str, float]:
    if not base: return over or {}
    if not over: return base
    keys = set(base) | set(over)
    return {k: (base.get(k, 0) + over.get(k, 0)) / 2 for k in keys}

def _apply_overlay(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for fld in ["goals", "values"]:
        merged[fld] = _merge_lists(base.get(fld, []), overlay.get(fld, []))
    b_base = base.get("behavioural_traits", {}) or {}
    b_over = overlay.get("behavioural_traits", {}) or {}
    b_m = dict(b_base)
    for k in ["investment_experience", "risk_tolerance"]:
        if b_over.get(k): b_m[k] = b_over[k]
    for k in ["information_sources", "preferred_channels"]:
        b_m[k] = _merge_lists(b_base.get(k, []), b_over.get(k, []))
    merged["behavioural_traits"] = b_m
    merged["compliance_sensitivities"] = _merge_lists(base.get("compliance_sensitivities", []), overlay.get("compliance_sensitivities", []))
    merged["proof_trust"] = _merge_lists(base.get("proof_trust", []), overlay.get("proof_trust", []))
    merged["creative_rubric_weights"] = _merge_weights(base.get("creative_rubric_weights", {}), overlay.get("creative_rubric_weights", {}))
    return merged

def _persona_from(source: Dict[str, Any], segment: str, overlays):
    demo = {
        "age": source.get("age"),
        "location": source.get("location"),
        "education": source.get("education"),
        "occupation": source.get("occupation"),
        "income": source.get("income"),
        "marital_status": source.get("marital_status"),
        "time_horizon_years": source.get("time_horizon_years"),
        "super_engagement": source.get("super_engagement"),
        "property_via_super_interest": source.get("property_via_super_interest"),
        "pricing_sensitivity": source.get("pricing_sensitivity"),
    }
    channels = (source.get("behavioural_traits", {}) or {}).get("preferred_channels", [])
    lang = ["plain", "numbers backed", "no jargon"]
    sens = {"compliance": source.get("compliance_sensitivities", []), "proof_trust": source.get("proof_trust", [])}
    rubric = source.get("creative_rubric_weights", {})
    pid = f"{_slug(segment)}_{_slug(source.get('name','persona'))}"
    return Persona(
        id=pid if not overlays else f"{pid}_{'_'.join(map(_slug, overlays))}",
        name=source.get("name", "Unknown"),
        weight=0.1,
        segment=segment,
        demographics=demo,
        goals=source.get("goals", []),
        fears=source.get("concerns", []),
        channels=channels,
        language_style=lang,
        compliance_risk="low",
        version="1.0",
        rubric=rubric,
        sensitivities=sens,
        overlays=list(overlays) if overlays else []
    )

def load_and_expand(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    base_entries = []
    overlays_def = []

    for group in data.get("personas", []):
        if group.get("type") == "behavioural_overlay":
            overlays_def.append(group)
        else:
            seg = group.get("segment")
            for gender in ("male", "female"):
                if gender in group:
                    base_entries.append( (seg, group[gender], gender) )

    seg_to_overlays = {}
    for ov in overlays_def:
        applies = set(ov.get("applies_to", []))
        for seg in applies:
            seg_to_overlays.setdefault(seg, []).append(ov)

    personas = []
    for seg, src, gender in base_entries:
        base_p = _persona_from(src, seg, overlays=[])
        personas.append(base_p)
        for ov in seg_to_overlays.get(seg, []):
            ov_src = ov.get(gender) or {}
            merged = _apply_overlay(src, ov_src)
            p = _persona_from(merged, seg, overlays=[ov.get("segment", ov.get("type","overlay"))])
            personas.append(p)

    if personas:
        w = 1.0/len(personas)
        for p in personas:
            p.weight = w
    return personas
