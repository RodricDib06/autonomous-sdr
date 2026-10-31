"""
Compliance endpoints — one-click unsubscribe (public), suppression list
management, and live send-guardrail status.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database import crud
from app.database.connection import get_db
from app.database.models import Lead, User

log = logging.getLogger(__name__)

router = APIRouter(tags=["compliance"])

# ===========================================================================
# Compliance — one-click unsubscribe + suppression list + send guardrails
# ===========================================================================

_UNSUBSCRIBE_PAGE = """<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title></head>
<body style="font-family:sans-serif;max-width:480px;margin:80px auto;padding:0 16px;text-align:center">
<h2>{title}</h2><p>{message}</p>{action}
</body></html>"""

_CONFIRM_FORM = """<form method="post">
<button type="submit" style="font-size:16px;padding:10px 24px;cursor:pointer">Unsubscribe</button>
</form>"""


def _page(title: str, message: str, action: str = "", status_code: int = 200):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        _UNSUBSCRIBE_PAGE.format(title=title, message=message, action=action),
        status_code=status_code,
    )


@router.api_route("/unsubscribe/{email_id}", methods=["GET", "POST"])
def unsubscribe(email_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Unsubscribe landing page (public, no auth).

    POST opts out: the confirm button on this page, and the RFC 8058
    List-Unsubscribe-Post one-click that Gmail/Outlook send. GET only shows
    the confirm button — corporate link scanners (Safe Links, Mimecast,
    Proofpoint) fetch every URL in inbound mail, so a GET that unsubscribed
    would silently opt out every recipient behind one.
    """
    from app.database.models import OutreachEmail as OutreachEmailModel
    from app.services.compliance import process_unsubscribe

    email_rec = db.query(OutreachEmailModel).filter(OutreachEmailModel.id == email_id).first()
    if not email_rec:
        return _page("Link not recognised", "This unsubscribe link is invalid or has expired.",
                     status_code=404)

    if request.method == "GET":
        return _page("Unsubscribe", "Click below and you won't receive any further emails from us.",
                     action=_CONFIRM_FORM)

    lead = db.query(Lead).filter(Lead.id == email_rec.lead_id).first()
    if lead:
        process_unsubscribe(db, lead, source="unsubscribe_link")
        log.info(f"[unsubscribe] Lead {lead.id[:8]} opted out via one-click link")

    return _page("You're unsubscribed",
                 "You won't receive any further emails from us. Sorry to see you go.")


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
        matches = match_q.filter(crud.email_equals(Lead.email, value)).all()
    else:
        # Escape so a literal "_" in the domain can't match any character
        escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matches = match_q.filter(Lead.email.ilike(f"%@{escaped}", escape="\\")).all()
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


@router.get("/outreach/sending-settings")
def get_sending_settings(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """The org's CAN-SPAM postal address and whether the agent may answer prospects."""
    from app.services.email_compose import postal_address
    from app.services.reply_service import auto_reply_enabled

    return {
        "postal_address": postal_address(db, current_user.org_id),
        "auto_reply_enabled": auto_reply_enabled(db, current_user.org_id),
    }


@router.put("/outreach/sending-settings")
def update_sending_settings(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Body (any subset): {"postal_address": "...", "auto_reply_enabled": bool}.
    An empty postal address holds every real send until one is set.
    """
    from app.services.tenancy import set_org_setting

    if "postal_address" in payload:
        address = str(payload["postal_address"] or "").strip()
        if len(address) > 300:
            raise HTTPException(status_code=422, detail="postal_address must be 300 characters or fewer")
        set_org_setting(db, current_user.org_id, "postal_address", address)
    if "auto_reply_enabled" in payload:
        if not isinstance(payload["auto_reply_enabled"], bool):
            raise HTTPException(status_code=422, detail="auto_reply_enabled must be true or false")
        set_org_setting(db, current_user.org_id, "auto_reply_enabled", payload["auto_reply_enabled"])
    log.info(f"[compliance] Sending settings updated by {current_user.email}: {sorted(payload)}")
    return get_sending_settings(current_user=current_user, db=db)


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

    return guardrail_status(db, current_user.org_id)




@router.post("/email-verification")
def verify_email_address(
    payload: dict,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    On-demand deliverability check. Body: {"email": "...", "lead_id": "..."?}.
    With a lead_id, the result is also persisted on that lead (org-scoped).
    Runs even when the automatic pre-send gate is disabled — an explicit
    request always gets a fresh answer.
    """
    from app.services.email_verification import verify_email
    from app.utils.time import utcnow

    lead_id = payload.get("lead_id")
    if lead_id:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead or (current_user.org_id is not None and lead.org_id != current_user.org_id):
            raise HTTPException(status_code=404, detail="Lead not found")
        result = verify_email(lead.email)
        lead.email_verification_status = result.status
        lead.email_verified_at = utcnow()
        lead.email_verification_detail = result.to_dict()
        db.commit()
        return lead.email_verification_detail

    email = (payload.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=422, detail="Provide 'email' or 'lead_id'")
    return verify_email(email).to_dict()
