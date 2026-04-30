from datetime import datetime
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
