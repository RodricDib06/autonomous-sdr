"""
Compliance & deliverability service.

Everything that makes autonomous outreach safe for a real company to run:

  - Suppression list (do-not-contact) — email- and domain-level, checked
    before every send. Sources: one-click unsubscribe, unsubscribe-intent
    keywords in replies, hard bounces, manual entry, GDPR requests.
  - Unsubscribe-intent detection on inbound reply text.
  - Sequence cancellation — stop all remaining scheduled follow-ups for a
    lead the moment they reply or unsubscribe.
  - Send guardrails — daily send cap and a quiet-hours window so the agent
    never blasts 3 a.m. emails or burns the sending domain's reputation.
"""

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Lead, OutreachEmail, SuppressionEntry
from app.utils.time import utcnow

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Suppression list
# ---------------------------------------------------------------------------

def normalise(value: str) -> str:
    return (value or "").strip().lower()


def domain_of(email: str) -> str:
    email = normalise(email)
    return email.split("@", 1)[1] if "@" in email else email


def is_suppressed(db: Session, email: str, org_id: str | None = None) -> SuppressionEntry | None:
    """Return the matching suppression entry (exact email or its domain), or None."""
    email = normalise(email)
    if not email:
        return None
    candidates = [email]
    if "@" in email:
        candidates.append(domain_of(email))
    q = db.query(SuppressionEntry).filter(SuppressionEntry.value.in_(candidates))
    if org_id is not None:
        q = q.filter(SuppressionEntry.org_id == org_id)
    return q.first()


def add_suppression(
    db: Session,
    value: str,
    source: str = "manual",
    reason: str | None = None,
    lead_id: str | None = None,
    created_by_id: str | None = None,
    org_id: str | None = None,
) -> SuppressionEntry:
    """Idempotently add an email or domain to the org's do-not-contact list."""
    value = normalise(value)
    kind = "email" if "@" in value else "domain"

    q = db.query(SuppressionEntry).filter(SuppressionEntry.value == value)
    if org_id is not None:
        q = q.filter(SuppressionEntry.org_id == org_id)
    existing = q.first()
    if existing:
        return existing

    entry = SuppressionEntry(
        value=value,
        kind=kind,
        source=source,
        reason=reason,
        lead_id=lead_id,
        created_by_id=created_by_id,
        org_id=org_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info(f"[compliance] Added suppression entry: {value} ({kind}, source={source})")
    return entry


def remove_suppression(db: Session, entry_id: str) -> bool:
    entry = db.query(SuppressionEntry).filter(SuppressionEntry.id == entry_id).first()
    if not entry:
        return False
    db.delete(entry)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Unsubscribe-intent detection
# ---------------------------------------------------------------------------

_UNSUBSCRIBE_PATTERNS = [
    r"\bunsubscribe\b",
    r"\bopt\s*(?:me\s*)?out\b",
    r"\bremove\s+me\b",
    r"\btake\s+me\s+off\b",
    r"\bstop\s+(?:e-?mail|contact|messag)\w*\b",
    r"\bdo\s+not\s+(?:e-?mail|contact)\b",
    r"\bdon'?t\s+(?:e-?mail|contact)\s+me\b",
    r"\bnever\s+contact\b",
    r"\bstop\s+reaching\s+out\b",
    r"^\s*stop\s*[.!]*\s*$",
]
_UNSUBSCRIBE_RE = re.compile("|".join(_UNSUBSCRIBE_PATTERNS), re.IGNORECASE)


def detect_unsubscribe_intent(text: str) -> bool:
    """True when a reply asks to stop being contacted (CAN-SPAM opt-out)."""
    return bool(_UNSUBSCRIBE_RE.search(text or ""))


# ---------------------------------------------------------------------------
# Sequence cancellation
# ---------------------------------------------------------------------------

def cancel_scheduled_emails(db: Session, lead_id: str, reason: str) -> int:
    """
    Cancel every not-yet-sent scheduled follow-up for a lead.
    Called when the lead replies, unsubscribes, or is suppressed.
    """
    pending = (
        db.query(OutreachEmail)
        .filter(
            OutreachEmail.lead_id == lead_id,
            OutreachEmail.status == "scheduled",
        )
        .all()
    )
    for email in pending:
        email.status = "cancelled"
        email.error_message = reason
    if pending:
        db.commit()
        log.info(f"[compliance] Cancelled {len(pending)} scheduled follow-ups for lead {lead_id[:8]} — {reason}")
    return len(pending)


def lead_has_replied(db: Session, lead_id: str) -> bool:
    return (
        db.query(OutreachEmail)
        .filter(OutreachEmail.lead_id == lead_id, OutreachEmail.status == "replied")
        .first()
        is not None
    )


def process_unsubscribe(
    db: Session,
    lead: Lead,
    source: str = "unsubscribe_link",
    reason: str | None = None,
) -> dict:
    """
    Full opt-out flow for a lead: suppress their address, cancel all pending
    follow-ups, and tag the lead so the UI shows why outreach stopped.
    """
    entry = add_suppression(
        db, lead.email, source=source,
        reason=reason or "Lead opted out of communications",
        lead_id=lead.id,
        org_id=lead.org_id,
    )
    cancelled = cancel_scheduled_emails(db, lead.id, f"Lead unsubscribed ({source})")

    tags = list(lead.tags or [])
    if "unsubscribed" not in tags:
        tags.append("unsubscribed")
        lead.tags = tags
        db.commit()

    return {"suppression_id": entry.id, "cancelled_emails": cancelled}


# ---------------------------------------------------------------------------
# Send guardrails — daily cap + quiet-hours window
# ---------------------------------------------------------------------------

def sent_in_last_24h(db: Session) -> int:
    cutoff = utcnow() - timedelta(hours=24)
    return (
        db.query(OutreachEmail)
        .filter(OutreachEmail.sent_at.isnot(None), OutreachEmail.sent_at >= cutoff)
        .count()
    )


def sent_in_last_24h_for_org(db: Session, org_id: str | None) -> int:
    """Org-scoped rolling send count — backs the campaign agent's daily target."""
    cutoff = utcnow() - timedelta(hours=24)
    q = (
        db.query(OutreachEmail)
        .join(Lead, OutreachEmail.lead_id == Lead.id)
        .filter(OutreachEmail.sent_at.isnot(None), OutreachEmail.sent_at >= cutoff)
    )
    if org_id is not None:
        q = q.filter(Lead.org_id == org_id)
    return q.count()


def can_send_now(db: Session, now: datetime | None = None) -> tuple[bool, str]:
    """
    Gate every outbound batch:
      1. Quiet hours    — only send inside the configured window (default 08–18 UTC).
      2. Weekdays only  — cold email on a Saturday reads as spam.
      3. Daily cap      — protects the sending domain's reputation.

    Returns (allowed, human-readable reason).
    """
    now = now or utcnow()

    if settings.OUTREACH_WEEKDAYS_ONLY and now.weekday() >= 5:
        return False, "Outside send window: weekends are excluded (OUTREACH_WEEKDAYS_ONLY)"

    start, end = settings.OUTREACH_SEND_WINDOW_START, settings.OUTREACH_SEND_WINDOW_END
    if not (start <= now.hour < end):
        return False, f"Outside send window: {start:02d}:00–{end:02d}:00 UTC"

    sent = sent_in_last_24h(db)
    if sent >= settings.OUTREACH_DAILY_SEND_LIMIT:
        return False, f"Daily send cap reached ({sent}/{settings.OUTREACH_DAILY_SEND_LIMIT} in last 24h)"

    return True, f"OK — {sent}/{settings.OUTREACH_DAILY_SEND_LIMIT} sent in last 24h"


def can_send_to_recipient(lead, now: datetime | None = None) -> tuple[bool, str]:
    """
    Send-window check on the recipient's local clock, falling back to the
    global UTC window when the lead has no inferable timezone.
    (The daily cap and weekday policy are enforced separately by the caller.)
    """
    from app.services.timezone_service import within_recipient_window

    now = now or utcnow()
    start, end = settings.OUTREACH_SEND_WINDOW_START, settings.OUTREACH_SEND_WINDOW_END

    ok, reason = within_recipient_window(
        getattr(lead, "timezone", None), now, start, end, settings.OUTREACH_WEEKDAYS_ONLY
    )
    if ok is not None:
        return ok, reason

    # No recipient timezone — global UTC window
    if settings.OUTREACH_WEEKDAYS_ONLY and now.weekday() >= 5:
        return False, "weekend (UTC fallback)"
    if not (start <= now.hour < end):
        return False, f"outside {start:02d}–{end:02d} UTC (no recipient timezone)"
    return True, "inside global UTC window"


def guardrail_status(db: Session) -> dict:
    allowed, reason = can_send_now(db)
    return {
        "can_send": allowed,
        "reason": reason,
        "sent_last_24h": sent_in_last_24h(db),
        "daily_limit": settings.OUTREACH_DAILY_SEND_LIMIT,
        "window_start_hour_utc": settings.OUTREACH_SEND_WINDOW_START,
        "window_end_hour_utc": settings.OUTREACH_SEND_WINDOW_END,
        "weekdays_only": settings.OUTREACH_WEEKDAYS_ONLY,
        "suppression_count": db.query(SuppressionEntry).count(),
    }
