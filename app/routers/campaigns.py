"""
Campaign API — hand the agent a quota, review its plans, read its reports.

Mirrors the email approval endpoints one level up: plans wait in
pending_approval (org setting `campaign_autonomy`, default "approve"),
approving executes them, and every executed action is in the log.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.agents.campaign_agent import (
    CAMPAIGN_AUTONOMY_MODES,
    build_report,
    execute_plan,
    generate_plan,
)
from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import Campaign, CampaignActionLog, CampaignPlan, User
from app.services import campaign_metrics
from app.services.tenancy import get_org_setting, set_org_setting
from app.utils.time import utcnow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    goal_type: str = Field(default="meetings", pattern="^(meetings|replies|qualified_leads)$")
    goal_target: int = Field(ge=1, le=100_000)
    period_start: datetime
    period_end: datetime
    constraints: dict = Field(default_factory=dict)

    @field_validator("period_end")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("period_start")
        if start is not None and v <= start:
            raise ValueError("period_end must be after period_start")
        return v


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, pattern="^(active|paused|completed)$")
    goal_target: int | None = Field(default=None, ge=1, le=100_000)
    constraints: dict | None = None


def _serialize_plan(plan: CampaignPlan, log_entries: list[CampaignActionLog] | None = None) -> dict:
    data = {
        "id": plan.id,
        "version": plan.version,
        "status": plan.status,
        "generated_at": plan.generated_at.isoformat() if plan.generated_at else None,
        "diagnosis": plan.diagnosis,
        "actions": plan.actions or [],
        "metrics_snapshot": plan.metrics_snapshot,
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        "rejection_reason": plan.rejection_reason,
    }
    if log_entries is not None:
        data["execution_log"] = [
            {
                "action_type": e.action_type,
                "success": e.success,
                "error_message": e.error_message,
                "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                "result": (e.payload or {}).get("result"),
            }
            for e in log_entries
        ]
    return data


def _serialize_campaign(db: Session, campaign: Campaign, detail: bool = False) -> dict:
    data = {
        "id": campaign.id,
        "name": campaign.name,
        "goal_type": campaign.goal_type,
        "goal_target": campaign.goal_target,
        "period_start": campaign.period_start.isoformat(),
        "period_end": campaign.period_end.isoformat(),
        "status": campaign.status,
        "constraints": campaign.constraints or {},
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "pace": campaign_metrics.pace(db, campaign),
    }
    if detail:
        data["progress"] = campaign_metrics.campaign_progress(db, campaign)
        active_plan = (
            db.query(CampaignPlan)
            .filter(
                CampaignPlan.campaign_id == campaign.id,
                CampaignPlan.status.in_(("pending_approval", "approved", "active")),
            )
            .order_by(CampaignPlan.version.desc())
            .first()
        )
        data["current_plan"] = _serialize_plan(active_plan) if active_plan else None
    return data


def _org_campaign_or_404(db: Session, campaign_id: str, user: User) -> Campaign:
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign or (user.org_id is not None and campaign.org_id != user.org_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


# ── Autonomy dial (strategy level) ───────────────────────────────────────────

@router.get("/autonomy")
def get_campaign_autonomy(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    mode = get_org_setting(db, current_user.org_id, "campaign_autonomy", "approve")
    return {"mode": mode, "modes": list(CAMPAIGN_AUTONOMY_MODES)}


@router.put("/autonomy")
def set_campaign_autonomy(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    mode = (payload.get("mode") or "").strip().lower()
    if mode not in CAMPAIGN_AUTONOMY_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {CAMPAIGN_AUTONOMY_MODES}")
    set_org_setting(db, current_user.org_id, "campaign_autonomy", mode)
    return {"mode": mode}


# ── Campaign CRUD ────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_campaign(
    payload: CampaignCreate,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    campaign = Campaign(
        org_id=current_user.org_id,
        name=payload.name,
        goal_type=payload.goal_type,
        goal_target=payload.goal_target,
        period_start=payload.period_start,
        period_end=payload.period_end,
        constraints=payload.constraints,
        created_by_id=current_user.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    log.info(f"[campaigns] '{campaign.name}' created by {current_user.email} "
             f"({campaign.goal_target} {campaign.goal_type})")
    return _serialize_campaign(db, campaign, detail=True)


@router.get("")
def list_campaigns(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    q = db.query(Campaign)
    if current_user.org_id is not None:
        q = q.filter(Campaign.org_id == current_user.org_id)
    campaigns = q.order_by(Campaign.created_at.desc()).all()
    return {"total": len(campaigns),
            "campaigns": [_serialize_campaign(db, c) for c in campaigns]}


@router.get("/{campaign_id}")
def get_campaign(
    campaign_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    return _serialize_campaign(db, campaign, detail=True)


@router.put("/{campaign_id}")
def update_campaign(
    campaign_id: str,
    payload: CampaignUpdate,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    for field in ("name", "status", "goal_target", "constraints"):
        value = getattr(payload, field)
        if value is not None:
            setattr(campaign, field, value)
    db.commit()
    db.refresh(campaign)
    return _serialize_campaign(db, campaign, detail=True)


# ── Plans ────────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/plans")
def list_plans(
    campaign_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    plans = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id)
        .order_by(CampaignPlan.version.desc())
        .limit(limit)
        .all()
    )
    out = []
    for plan in plans:
        entries = (
            db.query(CampaignActionLog)
            .filter(CampaignActionLog.plan_id == plan.id)
            .order_by(CampaignActionLog.executed_at.asc())
            .all()
        )
        out.append(_serialize_plan(plan, log_entries=entries))
    return {"total": len(out), "plans": out}


@router.post("/{campaign_id}/replan")
def replan_now(
    campaign_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Manual 'think again now' — bypasses the drift/age heuristics."""
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    if campaign.status != "active":
        raise HTTPException(status_code=409, detail=f"Campaign is {campaign.status}, not active")
    plan = generate_plan(db, campaign)
    mode = get_org_setting(db, campaign.org_id, "campaign_autonomy", "approve")
    if mode == "auto":
        plan.status = "approved"
        plan.approved_at = utcnow()
        db.commit()
        execute_plan(db, plan)
        db.refresh(plan)
    return _serialize_plan(plan)


@router.post("/{campaign_id}/plans/{plan_id}/approve")
def approve_plan(
    campaign_id: str,
    plan_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    plan = db.query(CampaignPlan).filter(
        CampaignPlan.id == plan_id, CampaignPlan.campaign_id == campaign.id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Plan is '{plan.status}', not pending approval")

    plan.status = "approved"
    plan.approved_by_id = current_user.id
    plan.approved_at = utcnow()
    db.commit()
    result = execute_plan(db, plan)
    db.refresh(plan)
    log.info(f"[campaigns] plan v{plan.version} approved by {current_user.email}")
    entries = (
        db.query(CampaignActionLog)
        .filter(CampaignActionLog.plan_id == plan.id)
        .order_by(CampaignActionLog.executed_at.asc())
        .all()
    )
    return {"execution": result, "plan": _serialize_plan(plan, log_entries=entries)}


@router.post("/{campaign_id}/plans/{plan_id}/reject")
def reject_plan(
    campaign_id: str,
    plan_id: str,
    payload: dict | None = None,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    plan = db.query(CampaignPlan).filter(
        CampaignPlan.id == plan_id, CampaignPlan.campaign_id == campaign.id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Plan is '{plan.status}', not pending approval")
    plan.status = "rejected"
    plan.rejection_reason = (payload or {}).get("reason")
    plan.approved_by_id = current_user.id
    plan.approved_at = utcnow()
    db.commit()
    return _serialize_plan(plan)


# ── Report ───────────────────────────────────────────────────────────────────

@router.get("/{campaign_id}/report")
def get_report(
    campaign_id: str,
    regenerate: bool = Query(False),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    campaign = _org_campaign_or_404(db, campaign_id, current_user)
    latest = (
        db.query(CampaignPlan)
        .filter(CampaignPlan.campaign_id == campaign.id, CampaignPlan.report_md.isnot(None))
        .order_by(CampaignPlan.version.desc())
        .first()
    )
    if latest is not None and not regenerate:
        return {"report_md": latest.report_md, "generated": False}
    return {"report_md": build_report(db, campaign), "generated": True}
