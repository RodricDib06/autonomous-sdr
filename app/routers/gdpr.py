"""
Privacy / GDPR endpoints: right to erasure, erasure audit trail, and an
exportable lead-activity audit log.
"""

import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin, require_manager
from app.database.connection import get_db
from app.database.models import GdprErasureLog, Lead, LeadEvent, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/gdpr", tags=["gdpr"])


@router.delete("/leads/{lead_id}")
def erase_lead_endpoint(
    lead_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Right to erasure (GDPR art. 17). Irreversibly deletes the lead and every
    PII-bearing record; keeps anonymised telemetry and the do-not-contact
    entry. Admin only.
    """
    from app.services.gdpr_service import erase_lead

    q = db.query(Lead).filter(Lead.id == lead_id)
    if current_user.org_id is not None:
        q = q.filter(Lead.org_id == current_user.org_id)
    lead = q.first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = erase_lead(db, lead, requested_by_id=current_user.id)
    return {"status": "erased", **result}


@router.get("/erasures")
def list_erasures(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
):
    """Proof-of-deletion audit trail (emails stored only as SHA-256 hashes)."""
    q = db.query(GdprErasureLog).order_by(GdprErasureLog.created_at.desc())
    if current_user.org_id is not None:
        q = q.filter(GdprErasureLog.org_id == current_user.org_id)
    rows = q.limit(limit).all()
    return {
        "erasures": [
            {
                "id": e.id,
                "email_hash": e.email_hash,
                "reason": e.reason,
                "purged_counts": e.purged_counts,
                "requested_by_id": e.requested_by_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
        "total": len(rows),
    }


@router.get("/audit-log")
def export_audit_log(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(5000, ge=1, le=50000),
):
    """
    Exportable activity audit: every lead event (status changes, sends,
    qualifications) for the caller's org. JSON for programmatic use,
    CSV for compliance reviewers.
    """
    q = (
        db.query(LeadEvent, Lead.email)
        .join(Lead, Lead.id == LeadEvent.lead_id)
        .order_by(LeadEvent.created_at.desc())
    )
    if current_user.org_id is not None:
        q = q.filter(Lead.org_id == current_user.org_id)
    rows = q.limit(limit).all()

    records = [
        {
            "event_id": ev.id,
            "lead_id": ev.lead_id,
            "lead_email": email,
            "event_type": ev.event_type,
            "payload": ev.payload,
            "created_at": ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev, email in rows
    ]

    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["event_id", "lead_id", "lead_email", "event_type", "payload", "created_at"]
        )
        writer.writeheader()
        for r in records:
            writer.writerow({**r, "payload": str(r["payload"] or "")})
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
        )

    return {"events": records, "total": len(records)}
