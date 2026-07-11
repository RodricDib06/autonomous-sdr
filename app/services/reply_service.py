"""
Inbound reply processing — one pipeline for every reply source.

Used by both the /ingest/email-reply webhook (SendGrid Inbound Parse,
Mailgun Routes, …) and the IMAP mailbox poller, so behaviour is identical
regardless of how the reply arrived:

  1. Mark the originating OutreachEmail as replied.
  2. Opt-out keywords → suppress + cancel cadence, never argue with them.
  3. Otherwise: cancel remaining scheduled steps (a human owns the thread),
     apply the Bayesian "replied" update, and optionally hand the text to
     the ConversationalAgent for an autonomous response.
"""

import logging

from sqlalchemy.orm import Session

from app.database.models import Lead, OutreachEmail
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def handle_reply(
    db: Session,
    lead: Lead,
    reply_text: str,
    email_id: str | None = None,
    source: str = "webhook",
) -> dict:
    """
    Synchronous part of reply handling (everything except the LLM response).
    Returns a dict with `status` ("unsubscribed" | "replied") — callers decide
    whether to invoke the conversational agent afterwards.
    """
    from app.services.compliance import (
        cancel_scheduled_emails,
        detect_unsubscribe_intent,
        process_unsubscribe,
    )

    # Mark the originating email as replied
    if email_id:
        email_rec = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email_rec and email_rec.status != "replied":
            email_rec.status = "replied"
            email_rec.replied_at = utcnow()
            db.commit()
    else:
        # No explicit email id (IMAP path): mark the latest sent email
        email_rec = (
            db.query(OutreachEmail)
            .filter(
                OutreachEmail.lead_id == lead.id,
                OutreachEmail.status.in_(("sent", "opened", "clicked")),
            )
            .order_by(OutreachEmail.sent_at.desc())
            .first()
        )
        if email_rec:
            email_rec.status = "replied"
            email_rec.replied_at = utcnow()
            db.commit()

    # Opt-out request: suppress, stop, and do NOT auto-respond
    if detect_unsubscribe_intent(reply_text):
        result = process_unsubscribe(
            db, lead, source="reply_keyword",
            reason=f"Reply text ({source}): {reply_text[:200]}",
        )
        log.info(f"[reply] Opt-out detected from {lead.email} via {source}")
        return {"status": "unsubscribed", **result}

    # A human answered — stop the automated cadence
    cancelled = cancel_scheduled_emails(db, lead.id, "Lead replied — sequence stopped")

    # Reply is the strongest positive engagement signal
    try:
        from app.services.intent_scoring import apply_bayesian_update
        apply_bayesian_update(db, lead.id, "replied")
    except Exception as e:
        log.warning(f"[reply] Bayesian update failed for {lead.id[:8]}: {e}")

    return {"status": "replied", "cancelled_emails": cancelled}


def generate_agent_response(lead_id: str, reply_text: str) -> None:
    """
    Run the ConversationalAgent on its own DB session. Blocking (LLM call) —
    callers should run this in a background task or worker thread.
    """
    from app.agents.conversational_agent import ConversationalAgent
    from app.database.connection import SessionLocal

    db = SessionLocal()
    try:
        agent = ConversationalAgent()
        result = agent.run(
            db, lead_id,
            {"channel": "email", "mode": "reply", "message": reply_text},
        )
        log.info(
            f"[reply] Agent responded for {lead_id[:8]} "
            f"(needs_human={result.get('needs_human')})"
        )
    except Exception as e:
        log.error(f"[reply] Agent error for {lead_id[:8]}: {e}")
    finally:
        db.close()
