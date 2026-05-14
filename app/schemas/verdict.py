from typing import Literal
from pydantic import BaseModel, field_validator


class BANTScores(BaseModel):
    """BANT scores as probabilities (0-1), not categories.

    Each dimension represents confidence that this lead qualifies on that axis.
    - budget: 0.0 = no budget, 1.0 = unlimited budget
    - authority: 0.0 = no decision power, 1.0 = sole decision-maker
    - need: 0.0 = no fit, 1.0 = perfect product-market fit
    - timeline: 0.0 = won't buy for years, 1.0 = buying this month
    """
    budget: float = 0.5
    authority: float = 0.5
    need: float = 0.5
    timeline: float = 0.5

    @field_validator("budget", "authority", "need", "timeline", mode="before")
    @classmethod
    def clamp_score(cls, v):
        if isinstance(v, str):
            try:
                v = float(v)
            except (ValueError, TypeError):
                return 0.5
        return max(0.0, min(1.0, float(v)))


class AnalysisOutput(BaseModel):
    verdict: Literal["Hot", "Warm", "Cold"]
    reasoning: str
    bant_scores: BANTScores
    overall_score: float = 0.5
    icp_match: bool

    @field_validator("overall_score", mode="before")
    @classmethod
    def clamp_overall(cls, v):
        if isinstance(v, str):
            try:
                v = float(v)
            except (ValueError, TypeError):
                return 0.5
        return max(0.0, min(1.0, float(v)))


class ValidatedOutput(BaseModel):
    validated: bool
    final_verdict: Literal["Hot", "Warm", "Cold"]
    confidence_score: float
    consistency_check: str
    flags: list[str] = []

    @field_validator("confidence_score")
    @classmethod
    def clamp_score(cls, v):
        return max(0.0, min(1.0, float(v)))
