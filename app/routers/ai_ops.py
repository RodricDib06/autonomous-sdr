"""
AI operations telemetry — what the LLM layer costs and how it performs.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import LLMCall, User
from app.utils.time import utcnow

router = APIRouter(tags=["ai-ops"])


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
