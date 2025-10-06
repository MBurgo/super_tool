from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class Persona(BaseModel):
    id: str
    name: str
    weight: float = 0.1
    segment: Optional[str] = None
    demographics: Dict[str, Any] = {}
    goals: List[str] = []
    fears: List[str] = []
    channels: List[str] = []
    language_style: List[str] = []
    compliance_risk: str = "low"
    version: str = "1.0"
    rubric: Dict[str, float] = {}
    sensitivities: Dict[str, List[str]] = {}
    overlays: List[str] = []

class TrendBrief(BaseModel):
    id: str
    headline: str
    summary: str
    signals: List[str] = []
    audiences: List[str] = []
    freshness: str = "same_day"
    evidence_links: List[str] = []
    priority_score: float = 0.5

class CreativeVariant(BaseModel):
    id: str
    brief_id: str
    format: str
    copy: str
    rationale: Optional[str] = None
    meta: Dict[str, str] = {}
    version: int = 1

class EvaluationResult(BaseModel):
    variant_id: str
    persona_scores: Dict[str, float] = {}
    qual_feedback: List[str] = []
    auto_checks: Dict[str, bool] = {}
    predicted_ctr: float = 0.01
    composite_score: float = 0.0

class Finalist(BaseModel):
    brief_id: str
    variant_id: str
    copy: str
    composite_score: float
    rationale: Optional[str] = None
