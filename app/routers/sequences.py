"""
Outreach sequence authoring — CRUD for multi-step email cadences.

Sequences are org-scoped. Global (org-less) sequences are the seeded
defaults every org can use; editing one clones it into the caller's org
first so tenants never mutate shared templates.

Template placeholders available in subject/body:
  {first_name} {name} {company} {industry} {job_title} {company_size}
  {sender_name} {value_prop}
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import ABTestResult, OutreachEmail, OutreachSequence, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sequences", tags=["sequences"])


class SequenceStep(BaseModel):
    step: int = Field(ge=1, le=10)
    delay_days: int = Field(ge=0, le=90)
    subject_template: str = Field(min_length=1, max_length=500)
    body_template: str = Field(min_length=1, max_length=10000)


class SequenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    ab_variant: str | None = Field(default=None, max_length=10)
    steps: list[SequenceStep] = Field(min_length=1, max_length=10)
    is_active: bool = True

    @field_validator("steps")
    @classmethod
    def steps_ordered_and_unique(cls, steps: list[SequenceStep]) -> list[SequenceStep]:
        numbers = [s.step for s in steps]
        if len(set(numbers)) != len(numbers):
            raise ValueError("step numbers must be unique")
        if sorted(numbers) != list(range(1, len(numbers) + 1)):
            raise ValueError("steps must be numbered 1..N without gaps")
        return sorted(steps, key=lambda s: s.step)


class SequenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    ab_variant: str | None = Field(default=None, max_length=10)
    steps: list[SequenceStep] | None = Field(default=None, min_length=1, max_length=10)
    is_active: bool | None = None

    @field_validator("steps")
    @classmethod
    def steps_ordered_and_unique(cls, steps):
        if steps is None:
            return steps
        return SequenceCreate.steps_ordered_and_unique(steps)


def _serialize(db: Session, seq: OutreachSequence) -> dict:
    emails_sent = (
        db.query(OutreachEmail)
        .filter(
            OutreachEmail.sequence_id == seq.id,
            OutreachEmail.status.in_(("sent", "opened", "clicked", "replied")),
        )
        .count()
    )
    ab = db.query(ABTestResult).filter(ABTestResult.sequence_id == seq.id).first()
    return {
        "id": seq.id,
        "name": seq.name,
        "ab_variant": seq.ab_variant,
        "is_active": seq.is_active,
        "is_global": seq.org_id is None,
        "steps": seq.steps or [],
        "emails_sent": emails_sent,
        "conversions": ab.conversions if ab else 0,
        "created_at": seq.created_at.isoformat() if seq.created_at else None,
    }


def _org_visible_query(db: Session, user: User):
    q = db.query(OutreachSequence)
    if user.org_id is not None:
        q = q.filter(
            (OutreachSequence.org_id == user.org_id) | (OutreachSequence.org_id.is_(None))
        )
    return q


@router.get("")
def list_sequences(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    include_inactive: bool = Query(True),
):
    """The org's sequences plus the shared global defaults."""
    q = _org_visible_query(db, current_user)
    if not include_inactive:
        q = q.filter(OutreachSequence.is_active)
    sequences = q.order_by(OutreachSequence.created_at.desc()).all()
    return {"sequences": [_serialize(db, s) for s in sequences], "total": len(sequences)}


@router.post("", status_code=201)
def create_sequence(
    payload: SequenceCreate,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    seq = OutreachSequence(
        name=payload.name,
        ab_variant=payload.ab_variant,
        steps=[s.model_dump() for s in payload.steps],
        is_active=payload.is_active,
        org_id=current_user.org_id,
    )
    db.add(seq)
    db.commit()
    db.refresh(seq)
    log.info(f"[sequences] Created '{seq.name}' ({len(payload.steps)} steps) by {current_user.email}")
    return _serialize(db, seq)


@router.put("/{sequence_id}")
def update_sequence(
    sequence_id: str,
    payload: SequenceUpdate,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Update a sequence. Editing a global (shared) sequence clones it into the
    caller's org and applies the edits to the clone — shared templates are
    never mutated in place.
    """
    seq = _org_visible_query(db, current_user).filter(OutreachSequence.id == sequence_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")

    cloned = False
    if seq.org_id is None and current_user.org_id is not None:
        clone = OutreachSequence(
            name=seq.name,
            ab_variant=seq.ab_variant,
            steps=list(seq.steps or []),
            is_active=seq.is_active,
            org_id=current_user.org_id,
        )
        db.add(clone)
        db.flush()
        seq = clone
        cloned = True

    if payload.name is not None:
        seq.name = payload.name
    if payload.ab_variant is not None:
        seq.ab_variant = payload.ab_variant
    if payload.steps is not None:
        seq.steps = [s.model_dump() for s in payload.steps]
    if payload.is_active is not None:
        seq.is_active = payload.is_active

    db.commit()
    db.refresh(seq)
    result = _serialize(db, seq)
    result["cloned_from_global"] = cloned
    return result


@router.delete("/{sequence_id}")
def deactivate_sequence(
    sequence_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Deactivate (soft-delete). Sent emails keep their FK to the sequence, so
    hard deletion would destroy outreach history — deactivation removes it
    from the bandit's rotation instead.
    """
    seq = _org_visible_query(db, current_user).filter(OutreachSequence.id == sequence_id).first()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence not found")
    if seq.org_id is None and current_user.org_id is not None:
        raise HTTPException(status_code=403, detail="Global sequences cannot be deactivated — clone and edit instead")

    seq.is_active = False
    db.commit()
    return {"status": "deactivated", "id": seq.id}
