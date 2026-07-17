"""
Inbound reply processing — one pipeline for every reply source.

Used by both the /ingest/email-reply webhook (SendGrid Inbound Parse,
Mailgun Routes, …) and the mailbox pollers, so behaviour is identical
regardless of how the reply arrived. Order is compliance-first:

  1. Opt-out keywords → suppress + cancel cadence, never argue. This check
     is keyword-based and runs before anything else — compliance never
     waits on an LLM.
  2. Autoresponders (OOO) → recorded, but they are NOT replies: the email
     stays "sent" and the cadence keeps running.
  3. Real replies → mark replied, classify, act per category:
       referral      → extracted contact becomes a new lead (referred_by)
       not_now       → cadence stops, re-engagement scheduled
       wrong_person  → org-chart traversal finds the right person
       objection     → recorded + aggregated; flagged for a human above a
                       confidence threshold; never auto-argued
     then stop the cadence (a human owns the thread) and apply the
     Bayesian "replied" update.
"""

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database.models import Conversation, Lead, LeadEvent, OutreachEmail
from app.services.reply_classifier import (
    DEFAULT_REENGAGE_DAYS,
    OBJECTION_NEEDS_HUMAN_CONFIDENCE,
    Classification,
    classify_reply,
)
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def _mark_replied(db: Session, lead: Lead, email_id: str | None) -> None:
    if email_id:
        email_rec = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email_rec and email_rec.status != "replied":
            email_rec.status = "replied"
            email_rec.replied_at = utcnow()
            db.commit()
        return
    # No explicit email id (mailbox-poll path): mark the latest sent email
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


def _store_classification(db: Session, lead: Lead, reply_text: str, classification: Classification) -> Conversation:
    """Attach the classification to the lead's latest email conversation
    (creating one if the conversational agent hasn't spoken yet)."""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead.id, Conversation.channel == "email")
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if conversation is None:
        conversation = Conversation(
            lead_id=lead.id,
            channel="email",
            messages=[{"role": "lead", "content": reply_text[:2000],
                       "timestamp": utcnow().isoformat()}],
        )
        db.add(conversation)

    conversation.classification = classification.model_dump()
    conversation.updated_at = utcnow()
    if (
        classification.category == "objection"
        and classification.confidence >= OBJECTION_NEEDS_HUMAN_CONFIDENCE
    ):
        conversation.needs_human = True
        conversation.human_flagged_at = utcnow()
    db.commit()
    db.refresh(conversation)
    return conversation


def _add_tag(db: Session, lead: Lead, tag: str) -> None:
    tags = list(lead.tags or [])
    if tag not in tags:
        tags.append(tag)
        lead.tags = tags
        db.commit()


def _handle_referral(db: Session, lead: Lead, classification: Classification) -> dict:
    """The warmest lead there is: 'talk to my colleague'."""
    email = (classification.extracted or {}).get("referral_email")
    name = (classification.extracted or {}).get("referral_name")
    if not email:
        return {"referral_created": False, "reason": "no contact extracted"}

    existing = db.query(Lead).filter(Lead.email.ilike(email)).first()
    if existing:
        return {"referral_created": False, "reason": "contact already a lead",
                "existing_lead_id": existing.id}

    from app.services.timezone_service import infer_timezone
    referred = Lead(
        name=name or email.split("@")[0].replace(".", " ").title(),
        email=email,
        company=lead.company,
        source="referral",
        org_id=lead.org_id,
        status="pending",
        referred_by_lead_id=lead.id,
        timezone=infer_timezone(email),
    )
    db.add(referred)
    db.commit()
    db.refresh(referred)
    _add_tag(db, lead, "gave-referral")

    try:
        from app.services.queue_service import push_lead_job
        push_lead_job(referred.id)
    except Exception:
        pass  # auto-enqueue scheduler picks up "pending" leads

    log.info(f"[reply] Referral from {lead.email} → new lead {email}")
    return {"referral_created": True, "referred_lead_id": referred.id}


def _handle_not_now(db: Session, lead: Lead, classification: Classification) -> dict:
    """Timing objection: stop the cadence now, come back when they said to."""
    days = int((classification.extracted or {}).get("resume_in_days") or DEFAULT_REENGAGE_DAYS)
    resume_at = utcnow() + timedelta(days=days)
    from app.database import crud
    crud.append_lead_event(db, lead.id, "reply.not_now", payload={
        "resume_at": resume_at.isoformat(),
    }, agent_name="reply_classifier")
    _add_tag(db, lead, "revisit-later")
    return {"reengage_at": resume_at.isoformat()}


def _handle_wrong_person(db: Session, lead: Lead) -> dict:
    _add_tag(db, lead, "wrong-person")
    try:
        from app.services.org_chart import traverse_org_chart
        result = traverse_org_chart(db, lead.id)
        return {"org_chart": {"traversed": result.get("traversed"),
                              "leads_created": result.get("leads_created", 0)}}
    except Exception as e:
        log.debug(f"[reply] org-chart traversal skipped: {e}")
        return {"org_chart": {"traversed": False}}


def handle_reply(
    db: Session,
    lead: Lead,
    reply_text: str,
    email_id: str | None = None,
    source: str = "webhook",
    ai_client=None,
) -> dict:
    """
    Synchronous part of reply handling (everything except the LLM response).
    Returns a dict with `status` ("unsubscribed" | "auto_reply" | "replied")
    plus the classification — callers decide whether to invoke the
    conversational agent afterwards.
    """
    from app.services.compliance import (
        cancel_scheduled_emails,
        detect_unsubscribe_intent,
        process_unsubscribe,
    )

    # 1. Opt-out — keyword-based, before anything else, never auto-argued
    if detect_unsubscribe_intent(reply_text):
        _mark_replied(db, lead, email_id)
        result = process_unsubscribe(
            db, lead, source="reply_keyword",
            reason=f"Reply text ({source}): {reply_text[:200]}",
        )
        log.info(f"[reply] Opt-out detected from {lead.email} via {source}")
        return {"status": "unsubscribed", **result}

    classification = classify_reply(reply_text, ai_client=ai_client, sender_email=lead.email)

    # 2. Autoresponders are not replies: don't mark replied, don't stop the
    #    cadence — the OOO-kills-the-sequence bug this fixes was real
    if classification.category == "auto_reply":
        _store_classification(db, lead, reply_text, classification)
        log.info(f"[reply] Autoresponder from {lead.email} — cadence continues")
        return {"status": "auto_reply", "classification": classification.model_dump()}

    # 3. A human answered
    _mark_replied(db, lead, email_id)
    _store_classification(db, lead, reply_text, classification)

    action_result: dict = {}
    if classification.category == "referral":
        action_result = _handle_referral(db, lead, classification)
    elif classification.category == "not_now":
        action_result = _handle_not_now(db, lead, classification)
    elif classification.category == "wrong_person":
        action_result = _handle_wrong_person(db, lead)

    # Stop the automated cadence — a human owns this thread now
    cancelled = cancel_scheduled_emails(db, lead.id, "Lead replied — sequence stopped")

    # Reply is the strongest positive engagement signal
    try:
        from app.services.intent_scoring import apply_bayesian_update
        apply_bayesian_update(db, lead.id, "replied")
    except Exception as e:
        log.warning(f"[reply] Bayesian update failed for {lead.id[:8]}: {e}")

    return {
        "status": "replied",
        "cancelled_emails": cancelled,
        "classification": classification.model_dump(),
        **action_result,
    }


# ---------------------------------------------------------------------------
# Re-engagement — "circle back next quarter" actually circles back
# ---------------------------------------------------------------------------

def process_due_reengagements(db: Session, now=None) -> dict:
    """
    Daily job: leads whose reply.not_now resume date has passed get re-queued
    for a fresh qualification pass. Each not_now event fires exactly once
    (a reply.reengaged event marks it consumed); volumes are small enough
    to filter payload dates in Python, which also keeps SQLite tests honest.
    """
    now = now or utcnow()
    events = (
        db.query(LeadEvent)
        .filter(LeadEvent.event_type == "reply.not_now")
        .order_by(LeadEvent.created_at.asc())
        .all()
    )

    requeued = 0
    for event in events:
        resume_at = (event.payload or {}).get("resume_at")
        if not resume_at or resume_at > now.isoformat():
            continue
        already = (
            db.query(LeadEvent)
            .filter(
                LeadEvent.lead_id == event.lead_id,
                LeadEvent.event_type == "reply.reengaged",
                LeadEvent.created_at >= event.created_at,
            )
            .first()
        )
        if already:
            continue

        lead = db.query(Lead).filter(Lead.id == event.lead_id).first()
        if lead is None or lead.archived:
            continue

        lead.status = "pending"  # auto-enqueue scheduler picks it up
        lead.reengagement_count = (lead.reengagement_count or 0) + 1
        from app.database import crud
        crud.append_lead_event(db, lead.id, "reply.reengaged", payload={
            "source_event_id": event.id,
        }, agent_name="reply_classifier")
        try:
            from app.services.queue_service import push_lead_job
            push_lead_job(lead.id)
        except Exception:
            pass
        requeued += 1
        log.info(f"[reply] Re-engaging {lead.email} (not_now resume date reached)")

    return {"checked": len(events), "requeued": requeued}


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
