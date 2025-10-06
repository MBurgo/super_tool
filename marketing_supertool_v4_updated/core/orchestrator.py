from typing import List, Tuple, Callable
from .models import TrendBrief, CreativeVariant, EvaluationResult, Finalist, Persona
from .guardrails import check as guard_check
from .persona_panel import evaluate_variant as heuristic_eval
from .scoring import composite_score, simple_readability, brand_fit

def run_loop_for_brief(brief: dict, personas: List[Persona], writer_fn: Callable, n_variants: int = 6,
                       stop_threshold: float = 0.78, max_rounds: int = 3, evaluator: str = "heuristic",
                       synthetic_eval_fn: Callable | None = None) -> Tuple[Finalist, List[Tuple[CreativeVariant, EvaluationResult]]]:
    variants = writer_fn(brief, "email_subject", n_variants)
    history: List[Tuple[CreativeVariant, EvaluationResult]] = []
    round_num = 0

    def eval_variant(v: CreativeVariant) -> EvaluationResult:
        if evaluator == "heuristic":
            return heuristic_eval(v, personas)
        elif evaluator == "synthetic" and synthetic_eval_fn:
            return synthetic_eval_fn(v, personas)
        elif evaluator == "hybrid" and synthetic_eval_fn:
            h = heuristic_eval(v, personas)
            s = synthetic_eval_fn(v, personas)
            pa = (sum(h.persona_scores.values())/max(1,len(h.persona_scores)) + 
                  sum(s.persona_scores.values())/max(1,len(s.persona_scores))) / 2.0
            h.composite_score = composite_score(pa, h.predicted_ctr, simple_readability(v.copy), brand_fit(v.copy), 1.0)
            h.qual_feedback = (h.qual_feedback or []) + (s.qual_feedback or [])
            return h
        else:
            return heuristic_eval(v, personas)

    while round_num < max_rounds and variants:
        evaluated = []
        for v in variants:
            checks = guard_check(v)
            if any(checks.values()):
                continue
            ev = eval_variant(v)
            ev.composite_score = composite_score(
                sum(ev.persona_scores.values()) / max(1, len(ev.persona_scores)),
                ev.predicted_ctr,
                simple_readability(v.copy),
                brand_fit(v.copy),
                1.0
            )
            evaluated.append((v, ev))
            history.append((v, ev))

        if not evaluated:
            break

        evaluated.sort(key=lambda x: x[1].composite_score, reverse=True)
        best = evaluated[0]
        if best[1].composite_score >= stop_threshold:
            return Finalist(
                brief_id=brief.get("id", "unknown"),
                variant_id=best[0].id,
                copy=best[0].copy,
                composite_score=best[1].composite_score,
                rationale=best[0].rationale
            ), history

        keep = [v for v, e in evaluated[:max(1, len(evaluated)//2)]]
        mutate_src = evaluated[max(1, len(evaluated)//2):]
        new_vars = []
        for v, e in mutate_src:
            txt = v.copy
            if len(txt) > 320:
                txt = txt[:320].rsplit(" ", 1)[0] + "…"
            if "risk" not in txt.lower():
                txt += " | Know the risks"
            v2 = v.copy(update={"copy": txt, "version": v.version+1})
            new_vars.append(v2)
        variants = keep + new_vars
        round_num += 1

    if history:
        history.sort(key=lambda x: x[1].composite_score, reverse=True)
        top = history[0]
        return Finalist(
            brief_id=brief.get("id", "unknown"),
            variant_id=top[0].id,
            copy=top[0].copy,
            composite_score=top[1].composite_score,
            rationale=top[0].rationale
        ), history
    else:
        return None, []
