from typing import List, Dict, Optional, Any

from pydantic import BaseModel, Field

class Persona(BaseModel):
    id: str
    name: str
    weight: float = 0.1
    segment: Optional[str] = None
    demographics: Dict[str, Any] = Field(default_factory=dict)
    goals: List[str] = Field(default_factory=list)
    fears: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    language_style: List[str] = Field(default_factory=list)
    compliance_risk: str = "low"
    version: str = "1.0"
    rubric: Dict[str, float] = Field(default_factory=dict)
    sensitivities: Dict[str, List[str]] = Field(default_factory=dict)
    overlays: List[str] = Field(default_factory=list)

class TrendBrief(BaseModel):
    id: str
    headline: str
    summary: str
    signals: List[str] = Field(default_factory=list)
    audiences: List[str] = Field(default_factory=list)
    freshness: str = "same_day"
    evidence_links: List[str] = Field(default_factory=list)
    priority_score: float = 0.5

class CreativeVariant(BaseModel):
    id: str
    brief_id: str
    format: str
    copy: str
    rationale: Optional[str] = None
    meta: Dict[str, str] = Field(default_factory=dict)
    version: int = 1

class EvaluationResult(BaseModel):
    variant_id: str
    persona_scores: Dict[str, float] = Field(default_factory=dict)
    qual_feedback: List[str] = Field(default_factory=list)
    auto_checks: Dict[str, bool] = Field(default_factory=dict)
    predicted_ctr: float = 0.01
    composite_score: float = 0.0

class Finalist(BaseModel):
    brief_id: str
    variant_id: str
    copy: str
    composite_score: float
    rationale: Optional[str] = None
