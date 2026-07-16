"""
Sending-mailbox management: encrypted credentials, warm-up-aware rotation,
SMTP dispatch, and IMAP reply polling.

Rotation policy: among the org's active mailboxes that still have headroom
today, pick the one least-recently used. Headroom respects a warm-up ramp —
a fresh mailbox starts at 10 sends/day and earns +5/day until it reaches its
configured daily_limit, mirroring how deliverability tools warm domains.
"""

import base64
import email as email_lib
import hashlib
import imaplib
import logging
import smtplib
from datetime import timedelta
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Lead, OutreachEmail, SendingMailbox
from app.utils.time import utcnow

log = logging.getLogger(__name__)

WARMUP_START_SENDS = 10
WARMUP_DAILY_INCREMENT = 5

# Provider values whose credentials column holds an OAuth token blob rather
# than an SMTP password (dispatch + polling go through oauth_mailbox.py)
OAUTH_MAILBOX_PROVIDERS = ("gmail_oauth", "microsoft_oauth")


# ---------------------------------------------------------------------------
# Credential encryption
# ---------------------------------------------------------------------------

def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # SECRET_KEY changed since the credential was stored (e.g. the random
        # per-boot default) — the mailbox needs re-adding with a stable key.
        raise ValueError(
            "Cannot decrypt mailbox credential — SECRET_KEY changed since it was saved. "
            "Set a stable SECRET_KEY and re-add the mailbox."
        )


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def effective_daily_limit(mailbox: SendingMailbox, now=None) -> int:
    """Warm-up ramp: 10/day at the start, +5 per day, capped at daily_limit."""
    if mailbox.warmup_started_at is None:
        return mailbox.daily_limit
    now = now or utcnow()
    days = max(0, (now - mailbox.warmup_started_at).days)
    return min(mailbox.daily_limit, WARMUP_START_SENDS + WARMUP_DAILY_INCREMENT * days)


def sends_last_24h(db: Session, mailbox_id: str) -> int:
    cutoff = utcnow() - timedelta(hours=24)
    return (
        db.query(OutreachEmail)
        .filter(
            OutreachEmail.mailbox_id == mailbox_id,
            OutreachEmail.sent_at.isnot(None),
            OutreachEmail.sent_at >= cutoff,
        )
        .count()
    )


def pick_mailbox(db: Session, org_id: str | None) -> SendingMailbox | None:
    """Least-recently-used active mailbox with remaining daily headroom."""
    q = db.query(SendingMailbox).filter(SendingMailbox.is_active.is_(True))
    if org_id is not None:
        q = q.filter(SendingMailbox.org_id == org_id)
    candidates = q.order_by(SendingMailbox.last_used_at.asc().nullsfirst()).all()

    for mailbox in candidates:
        if sends_last_24h(db, mailbox.id) < effective_daily_limit(mailbox):
            return mailbox
    return None


# ---------------------------------------------------------------------------
# SMTP dispatch
# ---------------------------------------------------------------------------

def send_via_mailbox(
    db: Session,
    mailbox: SendingMailbox,
    email_record: OutreachEmail,
    to_address: str,
    unsubscribe_url: str = "",
) -> str:
    """Send one outreach email through a specific mailbox. Returns status string."""
    plain_body = email_record.body
    if unsubscribe_url:
        plain_body += f"\n\n—\nDon't want to hear from us? Unsubscribe: {unsubscribe_url}"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = email_record.subject
        from_header = f"{mailbox.display_name} <{mailbox.email}>" if mailbox.display_name else mailbox.email
        msg["From"] = from_header
        msg["To"] = to_address
        if unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.attach(MIMEText(plain_body, "plain"))

        if settings.APP_BASE_URL:
            pixel_url = f"{settings.APP_BASE_URL}/track/open/{email_record.id}"
            html_body = (
                f"<html><body><pre style='font-family:sans-serif'>{email_record.body}</pre>"
                f"<p style='font-size:11px;color:#888'>Don't want to hear from us? "
                f"<a href='{unsubscribe_url}'>Unsubscribe</a></p>"
                f"<img src='{pixel_url}' width='1' height='1' style='display:none' /></body></html>"
            )
            msg.attach(MIMEText(html_body, "html"))

        if mailbox.provider in OAUTH_MAILBOX_PROVIDERS:
            from app.services.oauth_mailbox import send_mime
            send_mime(db, mailbox, msg.as_bytes())
        else:
            password = decrypt_secret(mailbox.smtp_password_encrypted)
            with smtplib.SMTP_SSL(mailbox.smtp_host, mailbox.smtp_port) as server:
                server.login(mailbox.smtp_username, password)
                server.sendmail(mailbox.email, [to_address], msg.as_string())

        email_record.status = "sent"
        email_record.sent_at = utcnow()
        email_record.mailbox_id = mailbox.id
        mailbox.last_used_at = utcnow()
        db.commit()
        return "sent"

    except Exception as e:
        log.error(f"[mailbox] Send failed via {mailbox.email}: {e}")
        email_record.status = "failed"
        email_record.error_message = str(e)
        db.commit()
        return f"failed: {e}"


def test_mailbox_connection(mailbox: SendingMailbox, db: Session | None = None) -> tuple[bool, str]:
    """Credential check without sending anything (SMTP login or OAuth refresh)."""
    if mailbox.provider in OAUTH_MAILBOX_PROVIDERS:
        if db is None:
            return False, "OAuth connection test requires a database session"
        from app.services.oauth_mailbox import test_connection
        return test_connection(db, mailbox)

    try:
        password = decrypt_secret(mailbox.smtp_password_encrypted)
        with smtplib.SMTP_SSL(mailbox.smtp_host, mailbox.smtp_port, timeout=10) as server:
            server.login(mailbox.smtp_username, password)
        return True, "SMTP login OK"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# IMAP reply polling
# ---------------------------------------------------------------------------

def _decode_header_value(raw: str) -> str:
    parts = decode_header(raw or "")
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _extract_text_body(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = message.get_payload(decode=True)
    if payload:
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    return ""


def _from_address(message) -> str:
    raw = _decode_header_value(message.get("From", ""))
    if "<" in raw and ">" in raw:
        return raw.split("<", 1)[1].split(">", 1)[0].strip().lower()
    return raw.strip().lower()


def _process_inbound(
    db: Session,
    mailbox: SendingMailbox,
    sender: str,
    subject: str,
    body: str,
    message=None,
    source: str = "imap",
) -> str:
    """
    Shared classification for one inbound message, whatever transport it
    arrived on. DSNs go to the bounce handler (never auto-respond to
    mailer-daemon); real replies from known leads enter the reply pipeline.
    Returns "bounce" | "reply" | "ignored".
    """
    from app.services.bounce_service import handle_bounce, looks_like_bounce, parse_bounce
    from app.services.reply_service import handle_reply

    content_type = message.get_content_type() if message is not None else ""
    if looks_like_bounce(sender, subject, content_type):
        bounce = parse_bounce(message, body)
        if bounce:
            handle_bounce(
                db, bounce["recipient"], bounce["hard"],
                bounce["diagnostic"], org_id=mailbox.org_id,
            )
            return "bounce"
        return "ignored"

    if not sender or not body:
        return "ignored"

    lead_q = db.query(Lead).filter(Lead.email.ilike(sender))
    if mailbox.org_id is not None:
        lead_q = lead_q.filter(Lead.org_id == mailbox.org_id)
    lead = lead_q.first()
    if lead is None:
        return "ignored"

    handle_reply(db, lead, body, source=f"{source}:{mailbox.email}")
    return "reply"


def poll_mailbox_replies(db: Session, imap_factory=None) -> dict:
    """
    Fetch unread messages from every reply-capable mailbox — UNSEEN over IMAP
    for SMTP mailboxes, unread inbox messages via the Gmail/Graph APIs for
    OAuth mailboxes — and run each through the shared classification
    (bounce handling first, then the reply pipeline).
    `imap_factory` is injectable for tests.
    """
    imap_factory = imap_factory or (lambda host, port: imaplib.IMAP4_SSL(host, port))

    mailboxes = (
        db.query(SendingMailbox)
        .filter(
            SendingMailbox.is_active.is_(True),
            (SendingMailbox.imap_enabled.is_(True))
            | (SendingMailbox.provider.in_(OAUTH_MAILBOX_PROVIDERS)),
        )
        .all()
    )

    processed = matched = bounces = errors = 0
    for mailbox in mailboxes:
        try:
            if mailbox.provider in OAUTH_MAILBOX_PROVIDERS:
                from app.services.oauth_mailbox import fetch_unread_messages, mark_message_read
                for item in fetch_unread_messages(db, mailbox):
                    processed += 1
                    outcome = _process_inbound(
                        db, mailbox, item["from"], item["subject"], item["body"],
                        source="oauth",
                    )
                    if outcome == "reply":
                        matched += 1
                    elif outcome == "bounce":
                        bounces += 1
                    mark_message_read(db, mailbox, item["id"])
            else:
                password = decrypt_secret(mailbox.smtp_password_encrypted)
                conn = imap_factory(mailbox.imap_host or mailbox.smtp_host, mailbox.imap_port)
                try:
                    conn.login(mailbox.smtp_username, password)
                    conn.select("INBOX")
                    _, data = conn.search(None, "UNSEEN")
                    for num in (data[0].split() if data and data[0] else []):
                        _, msg_data = conn.fetch(num, "(RFC822)")
                        if not msg_data or msg_data[0] is None:
                            continue
                        message = email_lib.message_from_bytes(msg_data[0][1])
                        processed += 1

                        outcome = _process_inbound(
                            db, mailbox,
                            _from_address(message),
                            _decode_header_value(message.get("Subject", "")),
                            _extract_text_body(message).strip(),
                            message=message,
                            source="imap",
                        )
                        if outcome == "reply":
                            matched += 1
                        elif outcome == "bounce":
                            bounces += 1
                finally:
                    try:
                        conn.logout()
                    except Exception:
                        pass

            mailbox.last_imap_poll_at = utcnow()
            db.commit()
        except Exception as e:
            errors += 1
            log.warning(f"[mailbox] Reply poll failed for {mailbox.email}: {e}")

    return {"mailboxes": len(mailboxes), "processed": processed, "matched": matched,
            "bounces": bounces, "errors": errors}
