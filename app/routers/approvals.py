"""
Human-in-the-loop approval queue for outgoing outreach emails.

The autonomy dial (per-org setting `autonomy_mode`) has three positions:

  draft   — the agent writes every email but the platform never sends;
            content is copy-out only (approval endpoints refuse to queue).
  approve — every generated email waits here; approving moves it to
            "scheduled" and the outreach scheduler dispatches it when due.
  auto    — full autonomy; this queue stays empty.

This is the trust ramp: teams start in draft, graduate to approve,
and switch to auto once they trust the output.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_manager, require_rep
from app.config import settings
from app.database.connection import get_db
from app.database.models import Lead, OutreachEmail, User
from app.services.tenancy import get_org_setting, set_org_setting
from app.utils.time import utcnow

log = logging.getLogger(__name__)

router = APIRouter(tags=["approvals"])

AUTONOMY_MODES = ("draft", "approve", "auto")


def _org_email_or_404(db: Session, email_id: str, user: User) -> OutreachEmail:
    email = (
        db.query(OutreachEmail)
        .options(selectinload(OutreachEmail.lead))
        .filter(OutreachEmail.id == email_id)
        .first()
    )
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if user.org_id is not None and email.lead and email.lead.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


# ---------------------------------------------------------------------------
# Autonomy dial
# ---------------------------------------------------------------------------

@router.get("/outreach/autonomy")
def get_autonomy_mode(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Current autonomy mode for the caller's organization."""
    mode = get_org_setting(db, current_user.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE)
    pending = _pending_query(db, current_user).count()
    return {"mode": mode, "modes": list(AUTONOMY_MODES), "pending_count": pending}


@router.put("/outreach/autonomy")
def set_autonomy_mode(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Move the autonomy dial (manager+). Body: {"mode": "draft"|"approve"|"auto"}.
    Switching to auto does NOT retroactively send emails already waiting for
    approval — they stay in the queue until acted on.
    """
    mode = (payload.get("mode") or "").strip().lower()
    if mode not in AUTONOMY_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {AUTONOMY_MODES}")
    set_org_setting(db, current_user.org_id, "autonomy_mode", mode)
    log.info(f"[approvals] Autonomy mode set to '{mode}' by {current_user.email}")
    return {"mode": mode}


# ---------------------------------------------------------------------------
# Approval queue
# ---------------------------------------------------------------------------

def _pending_query(db: Session, user: User):
    q = (
        db.query(OutreachEmail)
        .join(Lead, OutreachEmail.lead_id == Lead.id)
        .filter(OutreachEmail.status == "pending_approval")
    )
    if user.org_id is not None:
        q = q.filter(Lead.org_id == user.org_id)
    return q


@router.get("/outreach/approvals")
def list_pending_approvals(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Emails the agent has written and is waiting for a human to review."""
    q = _pending_query(db, current_user).options(selectinload(OutreachEmail.lead))
    total = q.count()
    emails = (
        q.order_by(OutreachEmail.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    mode = get_org_setting(db, current_user.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE)
    return {
        "total": total,
        "mode": mode,
        "emails": [
            {
                "id": e.id,
                "lead_id": e.lead_id,
                "lead_name": e.lead.name if e.lead else None,
                "lead_email": e.lead.email if e.lead else None,
                "company": e.lead.company if e.lead else None,
                "step_number": e.step_number,
                "subject": e.subject,
                "body": e.body,
                "quality_score": e.quality_score,
                # Provenance: per-claim verification against research sources,
                # so reviewers see exactly which sentences are unsupported
                "claims": e.claims,
                "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in emails
        ],
    }


@router.post("/outreach/approvals/{email_id}/approve")
def approve_email(
    email_id: str,
    payload: dict | None = None,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Approve an email for sending, optionally with inline edits.
    Body (optional): {"subject": "...", "body": "..."} to override the draft.
    The outreach scheduler dispatches it once its scheduled_at arrives
    (immediately on the next tick if that time has already passed).
    """
    mode = get_org_setting(db, current_user.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE)
    if mode == "draft":
        raise HTTPException(
            status_code=409,
            detail="Organization is in draft-only mode — emails cannot be queued for sending. "
                   "Switch autonomy to 'approve' or 'auto' first.",
        )

    email = _org_email_or_404(db, email_id, current_user)
    if email.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Email is '{email.status}', not pending approval")

    payload = payload or {}
    if payload.get("subject"):
        email.subject = str(payload["subject"])[:500]
    if payload.get("body"):
        email.body = str(payload["body"])

    email.status = "scheduled"
    email.approved_by_id = current_user.id
    email.approved_at = utcnow()
    db.commit()

    log.info(f"[approvals] Email {email_id[:8]} approved by {current_user.email}")
    return {"status": "scheduled", "id": email.id, "edited": bool(payload)}


@router.post("/outreach/approvals/{email_id}/reject")
def reject_email(
    email_id: str,
    payload: dict | None = None,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Reject a draft. Body (optional): {"reason": "..."} — feeds future prompt tuning."""
    email = _org_email_or_404(db, email_id, current_user)
    if email.status != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Email is '{email.status}', not pending approval")

    email.status = "rejected"
    email.rejection_reason = (payload or {}).get("reason")
    email.approved_by_id = current_user.id
    email.approved_at = utcnow()
    db.commit()
    return {"status": "rejected", "id": email.id}


@router.post("/outreach/approvals/approve-all")
def approve_all(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Bulk-approve every pending email for the org (manager+)."""
    mode = get_org_setting(db, current_user.org_id, "autonomy_mode", settings.DEFAULT_AUTONOMY_MODE)
    if mode == "draft":
        raise HTTPException(status_code=409, detail="Organization is in draft-only mode")

    emails = _pending_query(db, current_user).all()
    now = utcnow()
    for email in emails:
        email.status = "scheduled"
        email.approved_by_id = current_user.id
        email.approved_at = now
    db.commit()
    return {"approved": len(emails)}
