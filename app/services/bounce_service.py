"""
Bounce (DSN) detection and handling.

When a send fails, the receiving server mails a Delivery Status Notification
back to the sending mailbox. The reply poller passes every inbound message
through here first; DSNs never reach the reply pipeline (auto-responding to
mailer-daemon would be embarrassing) and hard bounces feed the suppression
list — the loop that actually protects the sending domain.

Hard bounce (5.x.x — mailbox doesn't exist)  → mark email bounced, suppress
the address (source="bounce"), cancel the cadence, flag the lead
undeliverable. Soft bounce (4.x.x — mailbox full, greylisting) → mark the
email only; the address may recover.
"""

from __future__ import annotations

import logging
import re
from email.message import Message

from sqlalchemy.orm import Session

from app.database.models import Lead, OutreachEmail

log = logging.getLogger(__name__)

_BOUNCE_SENDERS_RE = re.compile(r"(mailer-daemon|postmaster|mail\s*delivery)", re.IGNORECASE)
_BOUNCE_SUBJECTS_RE = re.compile(
    r"(undeliver|delivery\s+(status|has\s+failed|failure|incomplete)|"
    r"failure\s+notice|returned\s+mail|mail\s+delivery\s+failed|delivery\s+notification)",
    re.IGNORECASE,
)
_RECIPIENT_HEADER_RE = re.compile(
    r"(?:Final|Original)-Recipient:\s*(?:rfc822;)?\s*<?([^\s<>;]+@[^\s<>;]+)>?",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"^Status:\s*([45])\.\d{1,3}\.\d{1,3}", re.IGNORECASE | re.MULTILINE)
_SMTP_CODE_RE = re.compile(r"\b([45])\d{2}[ -]\d\.\d{1,3}\.\d{1,3}\b")
_HARD_PHRASES_RE = re.compile(
    r"(user\s+unknown|no\s+such\s+user|mailbox\s+(unavailable|not\s+found|does\s+not\s+exist)|"
    r"recipient\s+(rejected|address\s+rejected)|address\s+not\s+found|"
    r"account\s+(disabled|does\s+not\s+exist)|550)",
    re.IGNORECASE,
)
_EMAIL_IN_TEXT_RE = re.compile(r"<?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})>?")


def looks_like_bounce(from_address: str, subject: str, content_type: str = "") -> bool:
    """Cheap header-level classification, usable by IMAP and API pollers alike."""
    if "multipart/report" in (content_type or "").lower():
        return True
    if _BOUNCE_SENDERS_RE.search(from_address or ""):
        return True
    return bool(_BOUNCE_SUBJECTS_RE.search(subject or ""))


def _delivery_status_text(message: Message) -> str:
    """Concatenated text of message/delivery-status parts (empty if none)."""
    chunks = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "message/delivery-status":
                payload = part.get_payload()
                if isinstance(payload, list):
                    chunks.extend(str(p) for p in payload)
                else:
                    chunks.append(str(payload))
    return "\n".join(chunks)


def parse_bounce(message: Message | None, body_text: str = "") -> dict | None:
    """
    Extract {recipient, hard, diagnostic} from a DSN. Prefers the structured
    message/delivery-status part; falls back to scraping the human-readable
    body (the only option for API pollers, which pass message=None).
    None when no failed recipient can be identified.
    """
    status_text = _delivery_status_text(message) if message is not None else ""
    search_text = status_text or body_text or ""

    recipient = None
    m = _RECIPIENT_HEADER_RE.search(search_text)
    if m:
        recipient = m.group(1).lower()
    elif not status_text and body_text:
        # Unstructured bounce: first address in the body that isn't the daemon
        for candidate in _EMAIL_IN_TEXT_RE.findall(body_text):
            if not _BOUNCE_SENDERS_RE.search(candidate):
                recipient = candidate.lower()
                break
    if not recipient:
        return None

    hard = False
    m = _STATUS_RE.search(status_text)
    if m:
        hard = m.group(1) == "5"
    else:
        m = _SMTP_CODE_RE.search(search_text)
        if m:
            hard = m.group(1) == "5"
        else:
            hard = bool(_HARD_PHRASES_RE.search(search_text))

    diagnostic = " ".join(search_text.split())[:300]
    return {"recipient": recipient, "hard": hard, "diagnostic": diagnostic}


def handle_bounce(
    db: Session,
    recipient: str,
    hard: bool,
    diagnostic: str = "",
    org_id: str | None = None,
) -> dict:
    """
    Apply a bounce to our records. Returns what was done; safe to call for
    recipients we never emailed (no-op apart from the log line).
    """
    from app.database import crud
    from app.services.compliance import add_suppression, cancel_scheduled_emails
    from app.services.email_verification import mark_undeliverable

    recipient = (recipient or "").strip().lower()
    lead_q = db.query(Lead).filter(Lead.email.ilike(recipient))
    if org_id is not None:
        lead_q = lead_q.filter(Lead.org_id == org_id)
    lead = lead_q.first()
    if lead is None:
        log.info(f"[bounce] DSN for unknown recipient {recipient} — ignoring")
        return {"status": "no_lead", "recipient": recipient}

    # The DSN refers to the most recent dispatched email still counted as delivered
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
        email_rec.status = "bounced"
        email_rec.error_message = f"{'Hard' if hard else 'Soft'} bounce: {diagnostic[:200]}"
        db.commit()

    cancelled = suppressed = 0
    if hard:
        add_suppression(
            db, recipient, source="bounce",
            reason=f"Hard bounce: {diagnostic[:200]}",
            lead_id=lead.id, org_id=lead.org_id,
        )
        suppressed = 1
        cancelled = cancel_scheduled_emails(db, lead.id, "Address hard-bounced")
        mark_undeliverable(db, lead, f"Hard bounce: {diagnostic[:200]}")

    try:
        crud.append_lead_event(db, lead.id, "outreach.bounced", payload={
            "hard": hard, "diagnostic": diagnostic[:300],
            "email_id": email_rec.id if email_rec else None,
        }, agent_name="bounce_handler")
    except Exception:
        pass

    log.info(f"[bounce] {'Hard' if hard else 'Soft'} bounce for {recipient} "
             f"(suppressed={bool(suppressed)}, cancelled={cancelled})")
    return {
        "status": "hard_bounce" if hard else "soft_bounce",
        "recipient": recipient,
        "lead_id": lead.id,
        "email_marked": email_rec.id if email_rec else None,
        "suppressed": bool(suppressed),
        "cancelled_emails": cancelled,
    }
