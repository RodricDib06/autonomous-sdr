"""
Batch operations service.

Single entry point: execute_batch(db, action, lead_ids, payload) → BatchResult.
All actions are atomic per-lead with a single commit at the end.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database.models import Lead

VALID_ACTIONS = {"tag_add", "tag_remove", "status_update", "archive", "delete"}
VALID_STATUSES = {"processing", "complete", "failed", "archived"}


@dataclass
class BatchResult:
    action: str
    requested: int
    succeeded: int
    failed: int
    not_found: int
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "requested": self.requested,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "not_found": self.not_found,
            "errors": self.errors,
        }


def execute_batch(
    db: Session,
    action: str,
    lead_ids: list[str],
    payload: dict,
) -> BatchResult:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown action '{action}'. Valid actions: {sorted(VALID_ACTIONS)}")

    handlers = {
        "tag_add": _tag_add,
        "tag_remove": _tag_remove,
        "status_update": _status_update,
        "archive": _archive,
        "delete": _delete,
    }
    return handlers[action](db, lead_ids, payload)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _load_leads(db: Session, lead_ids: list[str]) -> tuple[list[Lead], list[str]]:
    """Return (found_leads, not_found_ids)."""
    leads = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
    found_ids = {lead.id for lead in leads}
    not_found = [lid for lid in lead_ids if lid not in found_ids]
    return leads, not_found


def _tag_add(db: Session, lead_ids: list[str], payload: dict) -> BatchResult:
    new_tags = payload.get("tags", [])
    if not isinstance(new_tags, list):
        raise ValueError("payload.tags must be a list of strings")

    leads, not_found = _load_leads(db, lead_ids)
    succeeded, failed, errors = 0, 0, []

    for lead in leads:
        try:
            existing = list(lead.tags or [])
            # Merge without duplicates, preserving order
            for t in new_tags:
                if t not in existing:
                    existing.append(t)
            lead.tags = existing
            db.add(lead)
            succeeded += 1
        except Exception as e:
            failed += 1
            errors.append({"lead_id": lead.id, "error": str(e)})

    db.commit()
    return BatchResult("tag_add", len(lead_ids), succeeded, failed, len(not_found), errors)


def _tag_remove(db: Session, lead_ids: list[str], payload: dict) -> BatchResult:
    remove_tags = set(payload.get("tags", []))
    if not isinstance(remove_tags, set):
        raise ValueError("payload.tags must be a list of strings")

    leads, not_found = _load_leads(db, lead_ids)
    succeeded, failed, errors = 0, 0, []

    for lead in leads:
        try:
            lead.tags = [t for t in (lead.tags or []) if t not in remove_tags]
            db.add(lead)
            succeeded += 1
        except Exception as e:
            failed += 1
            errors.append({"lead_id": lead.id, "error": str(e)})

    db.commit()
    return BatchResult("tag_remove", len(lead_ids), succeeded, failed, len(not_found), errors)


def _status_update(db: Session, lead_ids: list[str], payload: dict) -> BatchResult:
    status = payload.get("status")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}")

    leads, not_found = _load_leads(db, lead_ids)
    succeeded, failed, errors = 0, 0, []

    for lead in leads:
        try:
            lead.status = status
            db.add(lead)
            succeeded += 1
        except Exception as e:
            failed += 1
            errors.append({"lead_id": lead.id, "error": str(e)})

    db.commit()
    return BatchResult("status_update", len(lead_ids), succeeded, failed, len(not_found), errors)


def _archive(db: Session, lead_ids: list[str], payload: dict) -> BatchResult:
    leads, not_found = _load_leads(db, lead_ids)
    succeeded, failed, errors = 0, 0, []

    for lead in leads:
        try:
            lead.archived = True
            lead.status = "archived"
            db.add(lead)
            succeeded += 1
        except Exception as e:
            failed += 1
            errors.append({"lead_id": lead.id, "error": str(e)})

    db.commit()
    return BatchResult("archive", len(lead_ids), succeeded, failed, len(not_found), errors)


def _delete(db: Session, lead_ids: list[str], payload: dict) -> BatchResult:
    leads, not_found = _load_leads(db, lead_ids)
    succeeded, failed, errors = 0, 0, []

    for lead in leads:
        try:
            db.delete(lead)
            succeeded += 1
        except Exception as e:
            failed += 1
            errors.append({"lead_id": lead.id, "error": str(e)})

    db.commit()
    return BatchResult("delete", len(lead_ids), succeeded, failed, len(not_found), errors)
