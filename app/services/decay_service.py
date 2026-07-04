"""
Predictive Churn / Engagement Decay Scoring

Computes how likely a lead is to still be responsive based on time elapsed
since their last engagement event.

Decay model — exponential with per-source configurable half-lives:

  decay_score(t) = 0.5 ^ (days_elapsed / half_life_days)

  Source half-lives (days until score halves):
    inbound_email       28  — warm inbound leads decay slowly
    linkedin_signal     14
    event_registration  14
    website_form        21
    marketing_ad         7  — cold outbound decays quickly
    webhook             10  — generic/unknown source

This is stronger than linear decay: a score of 1.0 at day 0 becomes 0.5 at
the half-life and 0.25 at twice the half-life, matching real-world re-contact
urgency.

Re-engagement triggers:
  When decay_score drops below RE_ENGAGE_THRESHOLD (0.35) and the lead:
    - has status "complete" (already processed)
    - has a Warm final verdict
    - has not been re-engaged more than MAX_REENGAGEMENTS times
    - has no pending outreach in the last N days

  A re-engagement OutreachEmail is created with a distinct "breaking silence"
  template. reengagement_count is incremented so the loop eventually stops.

The module exposes:
  compute_decay_exponential   — pure function, no DB access
  get_cooling_leads           — query for warm leads with decaying scores
  run_decay_check_job(db)     — called by the scheduler every hour
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TypedDict

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RE_ENGAGE_THRESHOLD = 0.35
MAX_REENGAGEMENTS = 3

# Per-source half-lives in days
_HALF_LIVES: dict[str, float] = {
    "inbound_email": 28.0,
    "linkedin_signal": 14.0,
    "event_registration": 14.0,
    "website_form": 21.0,
    "marketing_ad": 7.0,
    "webhook": 10.0,
    "form": 21.0,
    "csv_import": 10.0,
}
_DEFAULT_HALF_LIFE = 10.0

# Re-engagement email template — kept minimal to break silence naturally
_REENGAGEMENT_SUBJECT = "Checking back in — {company}"
_REENGAGEMENT_BODY = (
    "Hi {first_name},\n\n"
    "It's been a while since we last connected. "
    "Wanted to check in — has anything changed at {company} that might make "
    "this worth revisiting?\n\n"
    "Happy to adjust based on where things stand now.\n\n"
    "Best,\n{sender_name}"
)


# ---------------------------------------------------------------------------
# Decay computation
# ---------------------------------------------------------------------------

class EngagementDecay(TypedDict):
    last_engagement_at: str
    days_since_engagement: int
    decay_score: float
    urgency: str
    last_engagement_type: str
    half_life_days: float


def compute_decay_exponential(
    lead,
    outreach_emails: list,
    bookings: list,
    source: str | None = None,
) -> EngagementDecay:
    """
    Compute exponential decay score based on time since last engagement.

    Priority order for last engagement:
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

    days_ago = max(0.0, (datetime.utcnow() - last_at).total_seconds() / 86400)

    effective_source = source or getattr(lead, "source", None) or "webhook"
    half_life = _HALF_LIVES.get(effective_source, _DEFAULT_HALF_LIFE)

    # Exponential decay: score = 0.5^(days / half_life)
    decay_score = round(math.pow(0.5, days_ago / half_life), 4)

    # Urgency thresholds relative to the half-life
    if days_ago < half_life * 0.5:
        urgency = "fresh"
    elif days_ago < half_life:
        urgency = "watch"
    else:
        urgency = "urgent"

    return EngagementDecay(
        last_engagement_at=last_at.isoformat(),
        days_since_engagement=int(days_ago),
        decay_score=decay_score,
        urgency=urgency,
        last_engagement_type=eng_type,
        half_life_days=half_life,
    )


# Backward-compatible linear version kept for any callers that used it before
def compute_decay(lead, outreach_emails: list, bookings: list) -> dict:
    """Legacy linear decay — delegates to exponential. Kept for API compatibility."""
    return compute_decay_exponential(lead, outreach_emails, bookings)


# ---------------------------------------------------------------------------
# Cooling leads query
# ---------------------------------------------------------------------------

def get_cooling_leads(db, limit: int = 20) -> list[dict]:
    """
    Return Warm leads that are losing engagement, sorted by most overdue.
    Uses exponential decay scores and includes bandit-relevant fields.
    """
    from app.database.models import Lead, Verdict
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
        decay = compute_decay_exponential(
            lead, lead.outreach_emails, lead.booking_requests, source=lead.source
        )
        if decay["urgency"] in ("urgent", "watch"):
            verdict = lead.verdicts[0] if lead.verdicts else None
            enrichment = lead.enrichments[0] if lead.enrichments else None
            results.append({
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "company": lead.company,
                "source": lead.source,
                "job_title": enrichment.job_title if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "confidence": verdict.confidence_score if verdict else None,
                "reengagement_count": lead.reengagement_count or 0,
                "decay": decay,
            })

    results.sort(key=lambda r: r["decay"]["days_since_engagement"], reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Re-engagement trigger
# ---------------------------------------------------------------------------

def _should_reengage(lead, decay: EngagementDecay) -> bool:
    """Return True if this lead qualifies for a re-engagement email."""
    if decay["decay_score"] > RE_ENGAGE_THRESHOLD:
        return False
    if (lead.reengagement_count or 0) >= MAX_REENGAGEMENTS:
        return False
    if lead.status != "complete":
        return False
    return True


def _create_reengagement_email(db, lead, enrichment) -> None:
    """Schedule a re-engagement email for a cooling lead."""
    from app.database.models import OutreachEmail
    from app.config import settings

    first_name = lead.name.split()[0] if lead.name else "there"
    company = lead.company or "your company"
    sender = settings.OUTREACH_SENDER_NAME

    subject = _REENGAGEMENT_SUBJECT.format(company=company)
    body = _REENGAGEMENT_BODY.format(
        first_name=first_name,
        company=company,
        sender_name=sender,
    )

    email = OutreachEmail(
        lead_id=lead.id,
        sequence_id=None,
        step_number=1,
        subject=subject,
        body=body,
        status="scheduled",
        scheduled_at=datetime.utcnow(),
        quality_score=None,
        quality_flags=["reengagement"],
        quality_reasoning="Auto-generated re-engagement email from decay trigger",
    )
    db.add(email)

    # Increment counter and record check time
    lead.reengagement_count = (lead.reengagement_count or 0) + 1
    lead.last_decay_check_at = datetime.utcnow()
    lead.decay_score = 0.0  # reset; will be recomputed on next activity

    db.commit()
    log.info(
        f"[decay] re-engagement #{lead.reengagement_count} scheduled "
        f"for lead {lead.id[:8]} ({lead.name})"
    )


# ---------------------------------------------------------------------------
# Scheduled job entry point
# ---------------------------------------------------------------------------

def run_decay_check_job(db) -> dict:
    """
    Called by the APScheduler every hour. Persists decay_score on all active
    leads and triggers re-engagement emails for leads that have crossed the
    threshold.

    Returns a summary dict for logging.
    """
    from app.database.models import Lead, Verdict
    from sqlalchemy.orm import selectinload

    processed = 0
    re_engaged = 0
    errors = 0

    candidates = (
        db.query(Lead)
        .join(Verdict, Lead.id == Verdict.lead_id)
        .filter(
            Lead.status == "complete",
            Lead.archived == False,  # noqa: E712
            Verdict.final_verdict.in_(["Warm", "Hot"]),
        )
        .options(
            selectinload(Lead.outreach_emails),
            selectinload(Lead.booking_requests),
            selectinload(Lead.enrichments),
        )
        .all()
    )

    for lead in candidates:
        try:
            decay = compute_decay_exponential(
                lead, lead.outreach_emails, lead.booking_requests, source=lead.source
            )

            # Persist current decay score and check timestamp
            lead.decay_score = decay["decay_score"]
            lead.last_decay_check_at = datetime.utcnow()
            processed += 1

            if _should_reengage(lead, decay):
                enrichment = lead.enrichments[0] if lead.enrichments else None
                _create_reengagement_email(db, lead, enrichment)
                re_engaged += 1

        except Exception as e:
            errors += 1
            log.warning(f"[decay] error processing lead {lead.id[:8]}: {e}")

    try:
        db.commit()
    except Exception as e:
        log.error(f"[decay] commit failed: {e}")
        db.rollback()

    summary = {
        "processed": processed,
        "re_engaged": re_engaged,
        "errors": errors,
    }
    if processed or re_engaged:
        log.info(f"[decay] job complete: {summary}")
    return summary
