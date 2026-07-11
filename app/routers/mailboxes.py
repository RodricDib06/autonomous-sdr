"""
Sending mailbox management API. Credentials are write-only: passwords are
encrypted at rest and never returned by any endpoint.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import SendingMailbox, User
from app.services.mailbox_service import (
    effective_daily_limit,
    encrypt_secret,
    sends_last_24h,
    test_mailbox_connection,
)
from app.utils.time import utcnow

log = logging.getLogger(__name__)

router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])


class MailboxCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(default="", max_length=255)
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str = Field(min_length=1, max_length=255)
    smtp_password: str = Field(min_length=1)
    imap_host: str | None = None
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_enabled: bool = False
    daily_limit: int = Field(default=50, ge=1, le=500)
    start_warmup: bool = True


def _serialize(db: Session, m: SendingMailbox) -> dict:
    used = sends_last_24h(db, m.id)
    limit = effective_daily_limit(m)
    return {
        "id": m.id,
        "email": m.email,
        "display_name": m.display_name,
        "provider": m.provider,
        "smtp_host": m.smtp_host,
        "imap_enabled": m.imap_enabled,
        "is_active": m.is_active,
        "daily_limit": m.daily_limit,
        "effective_daily_limit": limit,
        "sent_last_24h": used,
        "warming_up": limit < m.daily_limit,
        "last_used_at": m.last_used_at.isoformat() if m.last_used_at else None,
        "last_imap_poll_at": m.last_imap_poll_at.isoformat() if m.last_imap_poll_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _org_query(db: Session, user: User):
    q = db.query(SendingMailbox)
    if user.org_id is not None:
        q = q.filter(SendingMailbox.org_id == user.org_id)
    return q


@router.get("")
def list_mailboxes(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    boxes = _org_query(db, current_user).order_by(SendingMailbox.created_at.asc()).all()
    return {"mailboxes": [_serialize(db, m) for m in boxes], "total": len(boxes)}


@router.post("", status_code=201)
def create_mailbox(
    payload: MailboxCreate,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Register a sending identity. `start_warmup=true` (default) ramps it from
    10 sends/day up to `daily_limit` — turn it off only for already-warm boxes.
    """
    mailbox = SendingMailbox(
        org_id=current_user.org_id,
        user_id=current_user.id,
        email=str(payload.email).lower(),
        display_name=payload.display_name,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password_encrypted=encrypt_secret(payload.smtp_password),
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        imap_enabled=payload.imap_enabled,
        daily_limit=payload.daily_limit,
        warmup_started_at=utcnow() if payload.start_warmup else None,
    )
    db.add(mailbox)
    db.commit()
    db.refresh(mailbox)
    log.info(f"[mailboxes] Added {mailbox.email} (warmup={payload.start_warmup}) by {current_user.email}")
    return _serialize(db, mailbox)


@router.post("/{mailbox_id}/test")
def test_mailbox(
    mailbox_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    mailbox = _org_query(db, current_user).filter(SendingMailbox.id == mailbox_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    ok, message = test_mailbox_connection(mailbox)
    return {"ok": ok, "message": message}


@router.delete("/{mailbox_id}")
def deactivate_mailbox(
    mailbox_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Deactivate (sent emails keep their FK, so no hard delete)."""
    mailbox = _org_query(db, current_user).filter(SendingMailbox.id == mailbox_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    mailbox.is_active = False
    db.commit()
    return {"status": "deactivated", "id": mailbox.id}
