"""
Lead assignment and conversion tracking service.

Handles lead-to-rep assignment, conversion status tracking, and audit history.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.database.models import Lead, LeadHistory

if TYPE_CHECKING:
    pass

VALID_CONVERSION_STATUSES = {
    "unqualified",
    "qualified",
    "contacted",
    "scheduled",
    "won",
    "lost",
    "no_contact",
}


def assign_lead(
    db: Session,
    lead_id: str,
    rep_id: str,
    reason: str | None = None,
    changed_by_id: str | None = None,
) -> Lead:
    """Assign a lead to a sales rep. Creates history entry."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    old_rep = lead.assigned_to_id
    lead.assigned_to_id = rep_id
    db.add(lead)

    # Create history entry
    history = LeadHistory(
        lead_id=lead_id,
        event_type="assigned",
        old_value=old_rep,
        new_value=rep_id,
        changed_by_id=changed_by_id,
    )
    db.add(history)
    db.commit()
    return lead


def unassign_lead(
    db: Session,
    lead_id: str,
    changed_by_id: str | None = None,
) -> Lead:
    """Unassign a lead from its sales rep. Creates history entry."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    old_rep = lead.assigned_to_id
    lead.assigned_to_id = None
    db.add(lead)

    history = LeadHistory(
        lead_id=lead_id,
        event_type="assigned",
        old_value=old_rep,
        new_value=None,
        changed_by_id=changed_by_id,
    )
    db.add(history)
    db.commit()
    return lead


def get_rep_assignments(db: Session, rep_id: str) -> list[Lead]:
    """Get all leads assigned to a specific rep."""
    return (
        db.query(Lead)
        .filter(Lead.assigned_to_id == rep_id, Lead.archived == False)
        .order_by(Lead.created_at.desc())
        .all()
    )


def auto_assign_round_robin(
    db: Session,
    lead_ids: list[str],
    rep_ids: list[str],
    changed_by_id: str | None = None,
) -> dict:
    """
    Distribute leads to reps using round-robin.
    Each rep gets roughly N/M leads where N=total_leads, M=total_reps.
    """
    if not rep_ids:
        raise ValueError("rep_ids must not be empty")

    # Count current assignments per rep
    rep_counts = {}
    for rep_id in rep_ids:
        count = db.query(Lead).filter(Lead.assigned_to_id == rep_id).count()
        rep_counts[rep_id] = count

    # Assign leads to rep with lowest current count
    assigned = 0
    failed = 0
    for lead_id in lead_ids:
        try:
            # Find rep with fewest assignments
            target_rep = min(rep_ids, key=lambda r: rep_counts[r])
            assign_lead(db, lead_id, target_rep, changed_by_id=changed_by_id)
            rep_counts[target_rep] += 1
            assigned += 1
        except Exception as e:
            failed += 1

    return {"assigned": assigned, "failed": failed, "total": len(lead_ids)}


def update_conversion_status(
    db: Session,
    lead_id: str,
    status: str,
    notes: str | None = None,
    changed_by_id: str | None = None,
) -> Lead:
    """Update lead conversion status. Creates history entry."""
    if status not in VALID_CONVERSION_STATUSES:
        raise ValueError(
            f"Invalid conversion status '{status}'. Valid: {sorted(VALID_CONVERSION_STATUSES)}"
        )

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    old_status = lead.conversion_status
    lead.conversion_status = status
    lead.conversion_updated_at = datetime.utcnow()
    if notes:
        lead.conversion_notes = notes
    db.add(lead)

    history = LeadHistory(
        lead_id=lead_id,
        event_type="conversion_updated",
        old_value=old_status,
        new_value=status,
        changed_by_id=changed_by_id,
    )
    db.add(history)
    db.commit()
    return lead


def get_lead_history(db: Session, lead_id: str) -> list[LeadHistory]:
    """Get all history entries for a lead, newest first."""
    return (
        db.query(LeadHistory)
        .filter(LeadHistory.lead_id == lead_id)
        .order_by(LeadHistory.changed_at.desc())
        .all()
    )


def record_history_event(
    db: Session,
    lead_id: str,
    event_type: str,
    old_value: str | None = None,
    new_value: str | None = None,
    changed_by_id: str | None = None,
) -> LeadHistory:
    """Low-level function to record a history event for any change."""
    history = LeadHistory(
        lead_id=lead_id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
        changed_by_id=changed_by_id,
    )
    db.add(history)
    db.commit()
    return history
