"""
Engagement decay scoring.

Computes how long ago a lead last engaged (opened email, replied, booked a
meeting) and turns that into a normalised decay score and urgency label.

Decay model:
  - 0 days ago  → decay_score 1.0  (fresh)
  - 7 days ago  → decay_score 0.77 (watch)
  - 14 days ago → decay_score 0.53 (urgent)
  - 30 days ago → decay_score 0.0  (stale)

The ceiling is 30 days — anything older than 30 days scores 0.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import TypedDict


_DECAY_WINDOW_DAYS = 30
_URGENCY_URGENT_DAYS = 14
_URGENCY_WATCH_DAYS = 7


class EngagementDecay(TypedDict):
    last_engagement_at: str         # ISO-8601
    days_since_engagement: int
    decay_score: float              # 0.0 – 1.0
    urgency: str                    # "fresh" | "watch" | "urgent"
    last_engagement_type: str       # "booking" | "reply" | "open" | "sent" | "created"


def compute_decay(lead, outreach_emails: list, bookings: list) -> EngagementDecay:
    """
    Derive the last engagement timestamp and return decay metrics.

    Priority order for last-engagement:
      booking created → email replied → email opened → email sent → lead created
    """
    candidates: list[tuple[datetime, str]] = []

    for booking in bookings:
        if booking.created_at:
            candidates.append((booking.created_at, "booking"))

    for email in outreach_emails:
        if email.replied_at:
            candidates.append((email.replied_at, "reply"))
        if email.opened_at:
            candidates.append((email.opened_at, "open"))
        if email.sent_at:
            candidates.append((email.sent_at, "sent"))

    if candidates:
        last_at, eng_type = max(candidates, key=lambda t: t[0])
    else:
        last_at = lead.created_at or datetime.utcnow()
        eng_type = "created"

    days_ago = max(0, (datetime.utcnow() - last_at).days)
    decay_score = round(max(0.0, 1.0 - days_ago / _DECAY_WINDOW_DAYS), 3)

    if days_ago >= _URGENCY_URGENT_DAYS:
        urgency = "urgent"
    elif days_ago >= _URGENCY_WATCH_DAYS:
        urgency = "watch"
    else:
        urgency = "fresh"

    return {
        "last_engagement_at": last_at.isoformat(),
        "days_since_engagement": days_ago,
        "decay_score": decay_score,
        "urgency": urgency,
        "last_engagement_type": eng_type,
    }


def get_cooling_leads(db, limit: int = 20) -> list[dict]:
    """
    Return warm leads that haven't engaged recently, sorted by urgency
    (most overdue first).  Only considers complete leads with Warm verdict.
    """
    from app.database.models import Lead, Verdict, OutreachEmail, BookingRequest
    from sqlalchemy.orm import selectinload

    warm_leads = (
        db.query(Lead)
        .join(Verdict, Lead.id == Verdict.lead_id)
        .filter(
            Lead.status == "complete",
            Lead.archived == False,  # noqa: E712
            Verdict.final_verdict == "Warm",
        )
        .options(
            selectinload(Lead.outreach_emails),
            selectinload(Lead.booking_requests),
            selectinload(Lead.verdicts),
            selectinload(Lead.enrichments),
        )
        .all()
    )

    results = []
    for lead in warm_leads:
        decay = compute_decay(lead, lead.outreach_emails, lead.booking_requests)
        if decay["urgency"] in ("urgent", "watch"):
            verdict = lead.verdicts[0] if lead.verdicts else None
            enrichment = lead.enrichments[0] if lead.enrichments else None
            results.append({
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "company": lead.company,
                "job_title": enrichment.job_title if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "confidence": verdict.confidence_score if verdict else None,
                "decay": decay,
            })

    results.sort(key=lambda r: r["decay"]["days_since_engagement"], reverse=True)
    return results[:limit]
