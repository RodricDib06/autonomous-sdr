from pydantic import BaseModel


class EnrichmentOutput(BaseModel):
    job_title: str
    seniority: str
    company_size: str
    industry: str
    revenue_estimate: str
    tech_stack: list[str]
    confidence: float
    enrichment_source: str
