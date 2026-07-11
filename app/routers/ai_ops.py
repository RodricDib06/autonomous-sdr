"""
AI operations telemetry — what the LLM layer costs and how it performs.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import BookingRequest, Lead, LLMCall, OutreachEmail, User, Verdict
from app.utils.time import utcnow

router = APIRouter(tags=["ai-ops"])

# A human SDR handles roughly this many leads per year (≈250/month) —
# used only for the cost-comparison denominator, and overridable per request.
HUMAN_SDR_LEADS_PER_YEAR = 3000


@router.get("/analytics/llm-costs")
def llm_costs(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """
    LLM spend and performance: totals, per-agent and per-model breakdowns,
    and a daily cost series. All figures cover the trailing `days` window.
    """
    cutoff = utcnow() - timedelta(days=days)
    base = db.query(LLMCall).filter(LLMCall.created_at >= cutoff)

    totals = db.query(
        func.count(LLMCall.id),
        func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
        func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
        func.coalesce(func.avg(LLMCall.latency_ms), 0.0),
    ).filter(LLMCall.created_at >= cutoff).one()

    failures = base.filter(LLMCall.success.is_(False)).count()

    by_agent = [
        {
            "agent": agent or "unattributed",
            "calls": calls,
            "tokens": int(tokens or 0),
            "cost_usd": round(float(cost or 0), 4),
            "avg_latency_ms": round(float(latency or 0)),
        }
        for agent, calls, tokens, cost, latency in db.query(
            LLMCall.agent_name,
            func.count(LLMCall.id),
            func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens),
            func.sum(LLMCall.cost_usd),
            func.avg(LLMCall.latency_ms),
        ).filter(LLMCall.created_at >= cutoff).group_by(LLMCall.agent_name)
        .order_by(func.sum(LLMCall.cost_usd).desc()).all()
    ]

    by_model = [
        {
            "provider": provider,
            "model": model,
            "calls": calls,
            "cost_usd": round(float(cost or 0), 4),
        }
        for provider, model, calls, cost in db.query(
            LLMCall.provider,
            LLMCall.model,
            func.count(LLMCall.id),
            func.sum(LLMCall.cost_usd),
        ).filter(LLMCall.created_at >= cutoff).group_by(LLMCall.provider, LLMCall.model).all()
    ]

    daily = [
        {"day": str(day), "calls": calls, "cost_usd": round(float(cost or 0), 4)}
        for day, calls, cost in db.query(
            func.date(LLMCall.created_at),
            func.count(LLMCall.id),
            func.sum(LLMCall.cost_usd),
        ).filter(LLMCall.created_at >= cutoff)
        .group_by(func.date(LLMCall.created_at))
        .order_by(func.date(LLMCall.created_at)).all()
    ]

    calls, tokens, cost, latency = totals
    return {
        "window_days": days,
        "total_calls": calls,
        "total_tokens": int(tokens),
        "total_cost_usd": round(float(cost), 4),
        "avg_latency_ms": round(float(latency)),
        "failure_count": failures,
        "avg_cost_per_call_usd": round(float(cost) / calls, 6) if calls else 0.0,
        "by_agent": by_agent,
        "by_model": by_model,
        "daily": daily,
    }


@router.get("/leads/{lead_id}/llm-cost")
def lead_llm_cost(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """What it cost, in LLM spend, to qualify and work this specific lead."""
    calls, tokens, cost, latency = db.query(
        func.count(LLMCall.id),
        func.coalesce(func.sum(LLMCall.prompt_tokens + LLMCall.completion_tokens), 0),
        func.coalesce(func.sum(LLMCall.cost_usd), 0.0),
        func.coalesce(func.avg(LLMCall.latency_ms), 0.0),
    ).filter(LLMCall.lead_id == lead_id).one()

    by_agent = [
        {"agent": agent or "unattributed", "calls": n, "cost_usd": round(float(c or 0), 6)}
        for agent, n, c in db.query(
            LLMCall.agent_name, func.count(LLMCall.id), func.sum(LLMCall.cost_usd)
        ).filter(LLMCall.lead_id == lead_id).group_by(LLMCall.agent_name).all()
    ]

    return {
        "lead_id": lead_id,
        "calls": calls,
        "tokens": int(tokens),
        "cost_usd": round(float(cost), 6),
        "avg_latency_ms": round(float(latency)),
        "by_agent": by_agent,
    }


@router.get("/analytics/roi")
def roi(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    days: int = Query(90, ge=7, le=365),
    acv: float = Query(25000, ge=100, description="Average contract value (USD)"),
    sdr_annual_cost: float = Query(75000, ge=1000, description="Fully-loaded human SDR cost (USD/yr)"),
):
    """
    The buyer's question, answered with the org's own data: what does a
    qualified lead / booked meeting cost on this platform vs. a human SDR?

    Every figure is computed from real pipeline activity in the window —
    the only assumptions are the two overridable parameters (ACV, SDR cost).
    """
    cutoff = utcnow() - timedelta(days=days)

    def _org_scope(q):
        if current_user.org_id is not None:
            return q.filter(Lead.org_id == current_user.org_id)
        return q

    leads_processed = _org_scope(
        db.query(Lead).filter(Lead.status == "complete", Lead.created_at >= cutoff)
    ).count()

    hot_leads = _org_scope(
        db.query(Lead)
        .join(Verdict, Verdict.lead_id == Lead.id)
        .filter(Verdict.final_verdict == "Hot", Lead.created_at >= cutoff)
    ).count()

    emails_sent = _org_scope(
        db.query(Lead)
        .join(OutreachEmail, OutreachEmail.lead_id == Lead.id)
        .filter(OutreachEmail.sent_at.isnot(None), OutreachEmail.sent_at >= cutoff)
    ).count()

    meetings_booked = _org_scope(
        db.query(Lead)
        .join(BookingRequest, BookingRequest.lead_id == Lead.id)
        .filter(BookingRequest.created_at >= cutoff)
    ).count()

    conversions = _org_scope(
        db.query(Lead).filter(
            Lead.conversion_status.in_(("won", "converted")),
            Lead.created_at >= cutoff,
        )
    ).count()

    llm_cost = float(
        db.query(func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
        .filter(LLMCall.created_at >= cutoff)
        .scalar() or 0.0
    )

    ai_cost_per_lead = llm_cost / leads_processed if leads_processed else 0.0
    human_cost_per_lead = sdr_annual_cost / HUMAN_SDR_LEADS_PER_YEAR
    annualized_leads = leads_processed * (365 / days)

    return {
        "window_days": days,
        "assumptions": {
            "acv_usd": acv,
            "sdr_annual_cost_usd": sdr_annual_cost,
            "human_sdr_leads_per_year": HUMAN_SDR_LEADS_PER_YEAR,
        },
        "activity": {
            "leads_processed": leads_processed,
            "hot_leads": hot_leads,
            "emails_sent": emails_sent,
            "meetings_booked": meetings_booked,
            "conversions": conversions,
            "llm_cost_usd": round(llm_cost, 4),
        },
        "unit_economics": {
            "ai_cost_per_lead_usd": round(ai_cost_per_lead, 4),
            "human_cost_per_lead_usd": round(human_cost_per_lead, 2),
            "cost_per_hot_lead_usd": round(llm_cost / hot_leads, 4) if hot_leads else None,
            "cost_per_meeting_usd": round(llm_cost / meetings_booked, 4) if meetings_booked else None,
            "savings_multiple": round(human_cost_per_lead / ai_cost_per_lead, 1) if ai_cost_per_lead > 0 else None,
        },
        "projections": {
            "annualized_lead_volume": round(annualized_leads),
            "projected_annual_ai_cost_usd": round(ai_cost_per_lead * annualized_leads, 2),
            "projected_annual_human_cost_usd": round(human_cost_per_lead * annualized_leads, 2),
            "projected_annual_savings_usd": round(
                (human_cost_per_lead - ai_cost_per_lead) * annualized_leads, 2
            ),
            "pipeline_value_usd": round(conversions * acv, 2),
        },
    }
