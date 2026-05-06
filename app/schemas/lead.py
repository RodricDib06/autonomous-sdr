from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr


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
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeadDetail(LeadResponse):
    enrichment: dict | None = None
    verdict: dict | None = None


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
