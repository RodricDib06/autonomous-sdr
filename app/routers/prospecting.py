"""
Prospecting API — the agent (or a manager) builds its own lead lists.

Dry runs return the gated candidate preview without importing anything;
real runs import, seed enrichment, and push into the qualification pipeline.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.config import settings
from app.database.connection import get_db
from app.database.models import Campaign, ProspectingRun, User
from app.services.prospecting.service import accepted_today, run_prospecting

log = logging.getLogger(__name__)

router = APIRouter(prefix="/prospecting", tags=["prospecting"])


class ProspectingRequest(BaseModel):
    criteria: dict = Field(default_factory=dict)
    campaign_id: str | None = None
    limit: int = Field(default=25, ge=1, le=200)
    dry_run: bool = False


def _serialize(run: ProspectingRun) -> dict:
    data = {
        "id": run.id,
        "provider": run.provider,
        "criteria": run.criteria or {},
        "campaign_id": run.campaign_id,
        "requested": run.requested,
        "found": run.found,
        "accepted": run.accepted,
        "rejected": run.rejected or {},
        "cost_usd": run.cost_usd,
        "dry_run": run.dry_run,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if hasattr(run, "preview"):
        data["candidates"] = run.preview
    return data


@router.post("/runs", status_code=201)
def create_run(
    payload: ProspectingRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Source leads. With `campaign_id`, criteria default to the campaign's
    first segment and the run is attributed to that campaign.
    """
    criteria = payload.criteria
    if payload.campaign_id:
        campaign = db.query(Campaign).filter(Campaign.id == payload.campaign_id).first()
        if not campaign or (current_user.org_id is not None and campaign.org_id != current_user.org_id):
            raise HTTPException(status_code=404, detail="Campaign not found")
        if not criteria:
            segments = (campaign.constraints or {}).get("segments") or []
            criteria = segments[0] if segments else {}

    run = run_prospecting(
        db,
        criteria=criteria,
        limit=payload.limit,
        org_id=current_user.org_id,
        campaign_id=payload.campaign_id,
        created_by_id=current_user.id,
        dry_run=payload.dry_run,
    )
    return _serialize(run)


@router.get("/runs")
def list_runs(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    q = db.query(ProspectingRun)
    if current_user.org_id is not None:
        q = q.filter(ProspectingRun.org_id == current_user.org_id)
    runs = q.order_by(ProspectingRun.created_at.desc()).limit(limit).all()
    return {
        "total": len(runs),
        "runs": [_serialize(r) for r in runs],
        "budget": {
            "max_per_day": settings.PROSPECTING_MAX_LEADS_PER_DAY,
            "accepted_today": accepted_today(db, current_user.org_id),
        },
    }
