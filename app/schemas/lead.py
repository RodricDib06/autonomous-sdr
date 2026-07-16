from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, model_validator


class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    company: str
    source: str = "webhook"


class LeadResponse(BaseModel):
    id: str
    name: str
    email: str
    company: str
    source: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None
    data_quality_score: float | None = None
    completeness_score: float | None = None
    tags: list | None = None
    archived: bool = False
    final_verdict: str | None = None
    lookalike_score: float | None = None
    referred_by_lead_id: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def extract_final_verdict(cls, v):
        if hasattr(v, "verdicts"):
            try:
                fv = v.verdicts[0].final_verdict if v.verdicts else None
            except Exception:
                fv = None
            return {
                "id": v.id,
                "name": v.name,
                "email": v.email,
                "company": v.company,
                "source": v.source,
                "status": v.status,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
                "data_quality_score": v.data_quality_score,
                "completeness_score": v.completeness_score,
                "tags": v.tags,
                "archived": v.archived,
                "final_verdict": fv,
                "lookalike_score": getattr(v, "lookalike_score", None),
                "referred_by_lead_id": getattr(v, "referred_by_lead_id", None),
            }
        return v


class LeadDetail(LeadResponse):
    enrichment: dict | None = None
    verdict: dict | None = None
    # Deliverability: valid | risky | undeliverable | unknown (email_verification.py)
    email_verification_status: str | None = None
    email_verified_at: datetime | None = None
    email_verification_reason: str | None = None


class BatchRequest(BaseModel):
    action: Literal["tag_add", "tag_remove", "status_update", "archive", "delete"]
    lead_ids: list[str]
    payload: dict = {}


class ImportHistoryResponse(BaseModel):
    id: str
    filename: str
    started_at: datetime
    completed_at: datetime | None = None
    total: int
    successful: int
    failed: int
    duplicates: int
    imported_by: str | None = None

    model_config = {"from_attributes": True}


class AssignRequest(BaseModel):
    rep_id: str
    reason: str | None = None


class ConversionRequest(BaseModel):
    status: Literal[
        "unqualified",
        "qualified",
        "contacted",
        "scheduled",
        "won",
        "lost",
        "no_contact",
    ]
    notes: str | None = None


class LeadHistoryEntry(BaseModel):
    id: str
    lead_id: str
    event_type: str
    old_value: str | None = None
    new_value: str | None = None
    changed_by_id: str | None = None
    changed_at: datetime

    model_config = {"from_attributes": True}


class AssignmentStats(BaseModel):
    rep_id: str
    rep_email: str
    assigned_count: int
    contacted_count: int
    contacted_pct: float
    won_count: int
    won_pct: float
