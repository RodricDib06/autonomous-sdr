from typing import Literal
from pydantic import BaseModel, field_validator


class BANTScores(BaseModel):
    budget: Literal["High", "Medium", "Low", "Unknown"] = "Unknown"
    authority: Literal["High", "Medium", "Low", "Unknown"] = "Unknown"
    need: Literal["High", "Medium", "Low", "Unknown"] = "Unknown"
    timeline: Literal["High", "Medium", "Low", "Unknown"] = "Unknown"


class AnalysisOutput(BaseModel):
    verdict: Literal["Hot", "Warm", "Cold"]
    reasoning: str
    bant_scores: BANTScores
    icp_match: bool

    @field_validator("bant_scores", mode="before")
    @classmethod
    def coerce_bant(cls, v):
        if isinstance(v, dict):
            cleaned = {}
            for k, val in v.items():
                cleaned[k] = val if val in ("High", "Medium", "Low", "Unknown") else "Unknown"
            return cleaned
        return v


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
