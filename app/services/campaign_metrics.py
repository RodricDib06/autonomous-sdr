"""
Campaign metrics — the campaign agent's eyes.

Everything here is deterministic SQL over existing tables; no LLM anywhere.
The planner reasons over this snapshot, and the snapshot is persisted on
every plan so a reviewer can always answer "what did the agent see when it
decided this?".

Definitions (documented because they ARE the goal semantics):
  meetings         — BookingRequest.status == "confirmed", created inside the
                     campaign period
  replies          — OutreachEmail.status == "replied", replied_at in period
  qualified_leads  — Verdict.final_verdict in (Hot, Warm), created in period
  bounce_rate      — bounced / (sent-ish states) over the period
  spend            — sum(LLMCall.cost_usd) attributed to the org's leads
Pace is measured in weekdays, matching the send guardrails (no weekend sends
means weekend days shouldn't count against the agent).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.models import (
    BookingRequest,
    Campaign,
    Enrichment,
    Lead,
    LLMCall,
    OutreachEmail,
    OutreachSequence,
    Verdict,
)
from app.services.icp_service import parse_company_size
from app.utils.time import utcnow

# OutreachEmail states that count as "delivered or beyond" for rate math
_DISPATCHED_STATES = ("sent", "opened", "clicked", "replied", "bounced")


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

def segment_label(segment: dict | None) -> str:
    if not segment:
        return "all leads"
    parts = []
    if segment.get("industry"):
        parts.append(str(segment["industry"]))
    if segment.get("seniority"):
        parts.append(str(segment["seniority"]))
    lo, hi = segment.get("company_size_min"), segment.get("company_size_max")
    if lo is not None or hi is not None:
        parts.append(f"{lo or 0}–{hi or '∞'} employees")
    return ", ".join(parts) or "all leads"


def segment_lead_ids(db: Session, org_id: str | None, segment: dict | None) -> list[str]:
    """
    Lead ids matching a segment filter. Industry/seniority match against the
    lead's enrichment (substring, case-insensitive); company size bounds are
    parsed from the enrichment's size-range string in Python because ranges
    like "50-200" cannot be compared in SQL.
    """
    q = db.query(Lead.id, Enrichment.company_size).outerjoin(
        Enrichment, Enrichment.lead_id == Lead.id
    ).filter(Lead.archived == False)  # noqa: E712
    if org_id is not None:
        q = q.filter(Lead.org_id == org_id)

    segment = segment or {}
    if segment.get("industry"):
        q = q.filter(Enrichment.industry.ilike(f"%{segment['industry']}%"))
    if segment.get("seniority"):
        q = q.filter(Enrichment.seniority.ilike(f"%{segment['seniority']}%"))

    lo = segment.get("company_size_min")
    hi = segment.get("company_size_max")
    ids = []
    for lead_id, size_raw in q.all():
        if lo is not None or hi is not None:
            headcount = parse_company_size(size_raw)
            if headcount is None:
                continue  # size filter set but size unknown → not in segment
            if lo is not None and headcount < lo:
                continue
            if hi is not None and headcount > hi:
                continue
        ids.append(lead_id)
    return ids


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def _segment_stats(db: Session, campaign: Campaign, lead_ids: list[str]) -> dict:
    start, end = campaign.period_start, campaign.period_end
    if not lead_ids:
        return {"leads": 0, "sends": 0, "replies": 0, "bounces": 0,
                "bounce_rate": None, "meetings": 0, "qualified": 0}

    def _email_count(status_filter) -> int:
        return (
            db.query(OutreachEmail)
            .filter(
                OutreachEmail.lead_id.in_(lead_ids),
                status_filter,
                OutreachEmail.sent_at.isnot(None),
                OutreachEmail.sent_at >= start,
                OutreachEmail.sent_at <= end,
            )
            .count()
        )

    sends = _email_count(OutreachEmail.status.in_(_DISPATCHED_STATES))
    bounces = _email_count(OutreachEmail.status == "bounced")
    replies = (
        db.query(OutreachEmail)
        .filter(
            OutreachEmail.lead_id.in_(lead_ids),
            OutreachEmail.status == "replied",
            OutreachEmail.replied_at.isnot(None),
            OutreachEmail.replied_at >= start,
            OutreachEmail.replied_at <= end,
        )
        .count()
    )
    meetings = (
        db.query(BookingRequest)
        .filter(
            BookingRequest.lead_id.in_(lead_ids),
            BookingRequest.status == "confirmed",
            BookingRequest.created_at >= start,
            BookingRequest.created_at <= end,
        )
        .count()
    )
    qualified = (
        db.query(Verdict)
        .filter(
            Verdict.lead_id.in_(lead_ids),
            Verdict.final_verdict.in_(("Hot", "Warm")),
            Verdict.created_at >= start,
            Verdict.created_at <= end,
        )
        .count()
    )

    return {
        "leads": len(lead_ids),
        "sends": sends,
        "replies": replies,
        "bounces": bounces,
        "bounce_rate": round(bounces / sends, 4) if sends else None,
        "meetings": meetings,
        "qualified": qualified,
    }


def campaign_progress(db: Session, campaign: Campaign) -> dict:
    """Totals plus a per-segment breakdown for the campaign's segments."""
    segments = (campaign.constraints or {}).get("segments") or []

    all_ids = segment_lead_ids(db, campaign.org_id, None)
    total = _segment_stats(db, campaign, all_ids)

    spend = (
        db.query(func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
        .join(Lead, LLMCall.lead_id == Lead.id)
        .filter(
            LLMCall.created_at >= campaign.period_start,
            LLMCall.created_at <= campaign.period_end,
        )
    )
    if campaign.org_id is not None:
        spend = spend.filter(Lead.org_id == campaign.org_id)
    total["spend_usd"] = round(float(spend.scalar() or 0.0), 4)

    per_segment = []
    for segment in segments:
        ids = segment_lead_ids(db, campaign.org_id, segment)
        per_segment.append({
            "segment": segment,
            "label": segment_label(segment),
            **_segment_stats(db, campaign, ids),
        })

    goal_actual = {
        "meetings": total["meetings"],
        "replies": total["replies"],
        "qualified_leads": total["qualified"],
    }.get(campaign.goal_type, total["meetings"])

    return {"goal_actual": goal_actual, "total": total, "segments": per_segment}


# ---------------------------------------------------------------------------
# Pace
# ---------------------------------------------------------------------------

def _weekdays_between(start: datetime, end: datetime) -> int:
    """Inclusive count of weekday dates in [start, end]; 0 when end < start."""
    if end < start:
        return 0
    days = (end.date() - start.date()).days + 1
    return sum(
        1 for i in range(days) if (start.date() + timedelta(days=i)).weekday() < 5
    )


def pace(db: Session, campaign: Campaign, now: datetime | None = None) -> dict:
    """
    Where the campaign stands against a linear weekday pace.

    pace_ratio > 1 = ahead, < 1 = behind, None = period hasn't started or the
    target is zero. projected_end_total extrapolates the current rate.
    """
    now = now or utcnow()
    total_days = _weekdays_between(campaign.period_start, campaign.period_end)
    elapsed_days = _weekdays_between(campaign.period_start, min(now, campaign.period_end))

    actual = campaign_progress(db, campaign)["goal_actual"]

    if total_days == 0 or campaign.goal_target <= 0:
        return {"expected_by_now": None, "actual": actual, "pace_ratio": None,
                "projected_end_total": None, "elapsed_weekdays": elapsed_days,
                "total_weekdays": total_days}

    fraction = elapsed_days / total_days
    expected = campaign.goal_target * fraction
    return {
        "expected_by_now": round(expected, 2),
        "actual": actual,
        "pace_ratio": round(actual / expected, 3) if expected > 0 else None,
        "projected_end_total": round(actual / fraction) if fraction > 0 else None,
        "elapsed_weekdays": elapsed_days,
        "total_weekdays": total_days,
    }


# ---------------------------------------------------------------------------
# Sequence performance — what the planner can pause / build on
# ---------------------------------------------------------------------------

def sequence_performance(db: Session, campaign: Campaign) -> list[dict]:
    """Per-sequence funnel stats within the campaign period (org-scoped)."""
    seq_q = db.query(OutreachSequence)
    if campaign.org_id is not None:
        seq_q = seq_q.filter(
            (OutreachSequence.org_id == campaign.org_id)
            | (OutreachSequence.org_id.is_(None))
        )

    results = []
    for seq in seq_q.all():
        base = db.query(OutreachEmail).join(Lead, OutreachEmail.lead_id == Lead.id).filter(
            OutreachEmail.sequence_id == seq.id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= campaign.period_start,
            OutreachEmail.sent_at <= campaign.period_end,
        )
        if campaign.org_id is not None:
            base = base.filter(Lead.org_id == campaign.org_id)

        sent = base.filter(OutreachEmail.status.in_(_DISPATCHED_STATES)).count()
        replied = base.filter(OutreachEmail.status == "replied").count()
        bounced = base.filter(OutreachEmail.status == "bounced").count()

        results.append({
            "sequence_id": seq.id,
            "name": seq.name,
            "ab_variant": seq.ab_variant,
            "is_active": seq.is_active,
            "sent": sent,
            "replied": replied,
            "bounced": bounced,
            "reply_rate": round(replied / sent, 4) if sent else None,
            "bounce_rate": round(bounced / sent, 4) if sent else None,
        })
    return results


def build_snapshot(db: Session, campaign: Campaign, now: datetime | None = None) -> dict:
    """The full picture the planner sees — persisted on every plan."""
    from app.services.reply_classifier import aggregate_objections

    objections = aggregate_objections(db, org_id=campaign.org_id, limit_examples=2)
    return {
        "generated_at": (now or utcnow()).isoformat(),
        "progress": campaign_progress(db, campaign),
        "pace": pace(db, campaign, now=now),
        "sequences": sequence_performance(db, campaign),
        # What prospects actually say — create_variant drafts should answer
        # the top objections, closing the replies→messaging loop
        "top_objections": objections["top"][:3],
        "objection_examples": {
            k: v for k, v in objections["examples"].items()
            if any(t["subtype"] == k for t in objections["top"][:3])
        },
    }
