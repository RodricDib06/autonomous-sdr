"""
GDPR / privacy operations.

Right to erasure: hard-delete a lead and every PII-bearing satellite row
(enrichments, verdicts, conversations + embeddings, outreach emails,
bookings, signals, events, history — all cascade from Lead). LLM telemetry
is anonymised (lead link nulled, telemetry kept — it holds no PII), and any
suppression entry is kept but unlinked: "never contact them again" survives
the erasure, which is exactly what the requester wants.

A GdprErasureLog row records that the erasure happened without retaining
the data itself (email stored as SHA-256).

Retention: purge_expired_leads deletes non-converted leads older than
DATA_RETENTION_DAYS (0 = disabled) via the same erasure path, so retention
policy and manual erasure behave identically.
"""

import hashlib
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import GdprErasureLog, Lead, LLMCall, SuppressionEntry
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def erase_lead(
    db: Session,
    lead: Lead,
    requested_by_id: str | None,
    reason: str = "gdpr_request",
) -> dict:
    """Irreversibly erase one lead. Returns a summary of what was removed."""
    email_hash = hashlib.sha256((lead.email or "").lower().encode()).hexdigest()

    # Anonymise telemetry (no PII in llm_calls; drop the association only)
    anonymised = (
        db.query(LLMCall)
        .filter(LLMCall.lead_id == lead.id)
        .update({"lead_id": None}, synchronize_session=False)
    )

    # Keep the do-not-contact entry, drop the lead link
    db.query(SuppressionEntry).filter(SuppressionEntry.lead_id == lead.id).update(
        {"lead_id": None}, synchronize_session=False
    )

    counts = {
        "enrichments": len(lead.enrichments),
        "verdicts": len(lead.verdicts),
        "agent_logs": len(lead.agent_logs),
        "outreach_emails": len(lead.outreach_emails),
        "conversations": len(lead.conversations),
        "booking_requests": len(lead.booking_requests),
        "intent_signals": len(lead.intent_signals),
        "events": len(lead.events),
        "llm_calls_anonymised": anonymised,
    }

    erasure = GdprErasureLog(
        org_id=lead.org_id,
        email_hash=email_hash,
        requested_by_id=requested_by_id,
        reason=reason,
        purged_counts=counts,
    )
    db.add(erasure)

    db.delete(lead)  # cascades take everything else
    db.commit()

    log.info(f"[gdpr] Erased lead (hash {email_hash[:12]}…), reason={reason}")
    return {"erasure_id": erasure.id, "email_hash": email_hash, "purged": counts}


def purge_expired_leads(db: Session, limit: int = 200) -> dict:
    """
    Retention policy: erase non-converted leads older than DATA_RETENTION_DAYS.
    Converted/won leads are business records and are exempt.
    """
    days = settings.DATA_RETENTION_DAYS
    if not days or days <= 0:
        return {"purged": 0, "enabled": False}

    cutoff = utcnow() - timedelta(days=days)
    expired = (
        db.query(Lead)
        .filter(
            Lead.created_at < cutoff,
            ~Lead.conversion_status.in_(("won", "converted")),
        )
        .limit(limit)
        .all()
    )

    purged = 0
    for lead in expired:
        try:
            erase_lead(db, lead, requested_by_id=None, reason=f"retention_policy_{days}d")
            purged += 1
        except Exception as e:
            log.error(f"[gdpr] Retention purge failed for {lead.id[:8]}: {e}")
            db.rollback()

    return {"purged": purged, "enabled": True, "retention_days": days}
