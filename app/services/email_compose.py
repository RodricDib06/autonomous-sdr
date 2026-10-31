"""
Outbound email assembly — one place for the legally required parts.

Every commercial email needs a working opt-out and the sender's physical
postal address (CAN-SPAM §7704(a)(5)). Both the global SMTP path and the
per-org mailbox path (SMTP and OAuth) build their MIME message here, so the
footer can't drift between transports.
"""

import html
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.config import settings


def postal_address(db: Session, org_id: str | None) -> str:
    """The org's postal address, falling back to OUTREACH_POSTAL_ADDRESS."""
    from app.services.tenancy import get_org_setting
    value = get_org_setting(db, org_id, "postal_address", None) or settings.OUTREACH_POSTAL_ADDRESS
    return (value or "").strip()


def real_send_blocker(db: Session, org_id: str | None) -> str | None:
    """Why a real (non-demo) send must not go out yet, or None."""
    if not postal_address(db, org_id):
        return "no postal address configured — required in every commercial email (CAN-SPAM)"
    return None


def unsubscribe_url_for(email_id: str) -> str:
    return f"{settings.APP_BASE_URL}/unsubscribe/{email_id}" if settings.APP_BASE_URL else ""


def build_message(
    db: Session,
    email_record,
    from_header: str,
    to_address: str,
    org_id: str | None,
) -> MIMEMultipart:
    """Plain + HTML parts with the opt-out and postal-address footer, plus RFC 8058 headers."""
    unsubscribe_url = unsubscribe_url_for(email_record.id)
    address = postal_address(db, org_id)

    footer = ["—"]
    if unsubscribe_url:
        footer.append(f"Don't want to hear from us? Unsubscribe: {unsubscribe_url}")
    if address:
        footer.append(address)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = email_record.subject
    msg["From"] = from_header
    msg["To"] = to_address
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(email_record.body + "\n\n" + "\n".join(footer), "plain"))

    if settings.APP_BASE_URL:
        pixel_url = f"{settings.APP_BASE_URL}/track/open/{email_record.id}"
        unsubscribe_html = (
            f"Don't want to hear from us? <a href='{html.escape(unsubscribe_url)}'>Unsubscribe</a>"
        )
        address_html = f"<br>{html.escape(address)}" if address else ""
        msg.attach(MIMEText(
            f"<html><body><pre style='font-family:sans-serif'>{html.escape(email_record.body)}</pre>"
            f"<p style='font-size:11px;color:#888'>{unsubscribe_html}{address_html}</p>"
            f"<img src='{pixel_url}' width='1' height='1' style='display:none' /></body></html>",
            "html",
        ))
    return msg
