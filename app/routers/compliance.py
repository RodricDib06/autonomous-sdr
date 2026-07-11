"""
Compliance endpoints — one-click unsubscribe (public), suppression list
management, and live send-guardrail status.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import Lead, User

log = logging.getLogger(__name__)

router = APIRouter(tags=["compliance"])

# ===========================================================================
# Compliance — one-click unsubscribe + suppression list + send guardrails
# ===========================================================================

_UNSUBSCRIBE_PAGE = """<!doctype html>
<html><head><title>Unsubscribed</title></head>
<body style="font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center">
<h2>{title}</h2><p>{message}</p>
</body></html>"""


@router.api_route("/unsubscribe/{email_id}", methods=["GET", "POST"])
def unsubscribe(email_id: str, db: Session = Depends(get_db)):
    """
    One-click unsubscribe landing page (public, no auth).

    Linked from every outreach email footer and the RFC 8058
    List-Unsubscribe-Post header (POST for mail-client one-click).
    Suppresses the lead's address and cancels all pending follow-ups.
    """
    from fastapi.responses import HTMLResponse
    from app.database.models import OutreachEmail as OutreachEmailModel
    from app.services.compliance import process_unsubscribe

    email_rec = db.query(OutreachEmailModel).filter(OutreachEmailModel.id == email_id).first()
    if not email_rec:
        return HTMLResponse(
            _UNSUBSCRIBE_PAGE.format(
                title="Link not recognised",
                message="This unsubscribe link is invalid or has expired.",
            ),
            status_code=404,
        )

    lead = db.query(Lead).filter(Lead.id == email_rec.lead_id).first()
    if lead:
        process_unsubscribe(db, lead, source="unsubscribe_link")
        log.info(f"[unsubscribe] Lead {lead.id[:8]} opted out via one-click link")

    return HTMLResponse(
        _UNSUBSCRIBE_PAGE.format(
            title="You're unsubscribed",
            message="You won't receive any further emails from us. Sorry to see you go.",
        )
    )


@router.get("/suppressions")
def list_suppressions(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Do-not-contact list — emails and domains that will never be messaged."""
    from app.database.models import SuppressionEntry

    q = db.query(SuppressionEntry).order_by(SuppressionEntry.created_at.desc())
    if current_user.org_id is not None:
        q = q.filter(SuppressionEntry.org_id == current_user.org_id)
    total = q.count()
    entries = q.offset(offset).limit(limit).all()
    return {
        "total": total,
        "entries": [
            {
                "id": e.id,
                "value": e.value,
                "kind": e.kind,
                "source": e.source,
                "reason": e.reason,
                "lead_id": e.lead_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


@router.post("/suppressions", status_code=201)
def create_suppression(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Manually add an email or bare domain to the do-not-contact list.
    Body: {"value": "jane@acme.com" | "acme.com", "reason": "optional"}
    Cancels any scheduled outreach to matching leads.
    """
    from app.services.compliance import add_suppression, cancel_scheduled_emails, normalise

    value = normalise(payload.get("value") or "")
    if not value or ("." not in value):
        raise HTTPException(status_code=422, detail="Provide a valid email address or domain")

    entry = add_suppression(
        db, value, source="manual",
        reason=payload.get("reason"), created_by_id=current_user.id,
        org_id=current_user.org_id,
    )

    # Stop pending cadences for every lead this entry now covers
    cancelled = 0
    match_q = db.query(Lead)
    if current_user.org_id is not None:
        match_q = match_q.filter(Lead.org_id == current_user.org_id)
    if entry.kind == "email":
        matches = match_q.filter(Lead.email.ilike(value)).all()
    else:
        matches = match_q.filter(Lead.email.ilike(f"%@{value}")).all()
    for lead in matches:
        cancelled += cancel_scheduled_emails(db, lead.id, "Address added to suppression list")

    return {"id": entry.id, "value": entry.value, "kind": entry.kind, "cancelled_emails": cancelled}


@router.delete("/suppressions/{entry_id}")
def delete_suppression(
    entry_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    from app.services.compliance import remove_suppression

    if not remove_suppression(db, entry_id):
        raise HTTPException(status_code=404, detail="Suppression entry not found")
    return {"status": "deleted", "id": entry_id}


@router.get("/outreach/guardrails")
def get_outreach_guardrails(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Live send-safety status: whether the scheduler is currently allowed to
    send, how much of the daily cap is used, and the active quiet-hours window.
    """
    from app.services.compliance import guardrail_status

    return guardrail_status(db)


