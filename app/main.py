from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db, create_all_tables
from app.database import crud
from app.schemas.lead import LeadCreate, LeadResponse, LeadDetail
from app.services.queue_service import push_lead_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all_tables()
    yield


app = FastAPI(title="AutonomousSDR", lifespan=lifespan)


@app.post("/leads", response_model=LeadResponse)
def receive_lead(payload: LeadCreate, db: Session = Depends(get_db)):
    lead = crud.create_lead(
        db,
        name=payload.name,
        email=payload.email,
        company=payload.company,
        source=payload.source,
    )
    push_lead_job(lead.id)
    return lead


@app.get("/leads", response_model=list[LeadResponse])
def list_leads(db: Session = Depends(get_db)):
    return crud.get_all_leads(db)


@app.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: str, db: Session = Depends(get_db)):
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    enrichment = lead.enrichments[0] if lead.enrichments else None
    verdict = lead.verdicts[0] if lead.verdicts else None

    detail = LeadDetail.model_validate(lead)
    if enrichment:
        detail.enrichment = {
            "job_title": enrichment.job_title,
            "seniority": enrichment.seniority,
            "company_size": enrichment.company_size,
            "industry": enrichment.industry,
            "revenue_estimate": enrichment.revenue_estimate,
            "tech_stack": enrichment.tech_stack,
            "confidence": enrichment.confidence,
            "enrichment_source": enrichment.enrichment_source,
        }
    if verdict:
        detail.verdict = {
            "analysis_verdict": verdict.analysis_verdict,
            "final_verdict": verdict.final_verdict,
            "confidence_score": verdict.confidence_score,
            "reasoning": verdict.analysis_reasoning,
            "bant_scores": verdict.bant_scores,
            "icp_match": verdict.icp_match,
            "validated": verdict.validated,
            "consistency_notes": verdict.consistency_notes,
            "flags": verdict.flags,
        }
    return detail
