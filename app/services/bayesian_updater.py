"""
Bayesian BANT score updater.

Each engagement signal (open, click, reply, booking) provides evidence about
the lead's BANT dimensions and increments scores using calibrated weights.
Scores are clamped to [0, 1] and the aggregate confidence is recomputed.

Signal weights (calibrated for SDR workflows):
  open    → small need bump  (they read the subject at least)
  click   → moderate need    (they engaged with content)
  reply   → need + authority + timeline (they're in-cycle)
  booking → strongest signal across all dimensions
"""

from __future__ import annotations
import logging
from datetime import datetime

log = logging.getLogger(__name__)

_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "open":    {"need": 0.05},
    "click":   {"need": 0.08},
    "reply":   {"need": 0.10, "authority": 0.08, "timeline": 0.06},
    "booking": {"budget": 0.05, "need": 0.12, "authority": 0.10, "timeline": 0.15},
}


def apply_bayesian_update(db, lead_id: str, signal: str) -> dict | None:
    """
    Increment BANT scores for *lead_id* based on *signal*.

    Returns a dict with the updated scores and new confidence, or None
    if the lead has no verdict / BANT scores yet.
    """
    from sqlalchemy.orm import selectinload
    from app.database.models import Lead, Verdict

    weights = _SIGNAL_WEIGHTS.get(signal)
    if not weights:
        return None

    lead = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead or not lead.verdicts:
        return None

    verdict: Verdict = lead.verdicts[0]
    if not verdict.bant_scores:
        return None

    updated = {k: float(v) for k, v in verdict.bant_scores.items()}
    changed = False
    for dim, delta in weights.items():
        if dim in updated:
            new_val = min(1.0, round(updated[dim] + delta, 3))
            if new_val != updated[dim]:
                updated[dim] = new_val
                changed = True

    if not changed:
        return None

    verdict.bant_scores = updated
    verdict.confidence_score = round(sum(updated.values()) / len(updated), 3)
    db.commit()

    log.info(
        "Bayesian BANT update applied",
        lead_id=lead_id,
        signal=signal,
        new_confidence=verdict.confidence_score,
    )

    return {
        "lead_id": lead_id,
        "signal": signal,
        "updated_scores": updated,
        "new_confidence": verdict.confidence_score,
        "updated_at": datetime.utcnow().isoformat(),
    }
