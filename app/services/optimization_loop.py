"""
Self-Optimization Loop

Analyses conversion outcomes and adjusts the BANT scoring weights so the
qualification engine becomes more accurate over time.

PoC: reads `verdicts` + `leads.conversion_status` from Postgres, computes
     which BANT dimensions best predict conversion, and writes new weights
     to `optimization_runs`. The analysis agent is then seeded with the
     updated weights on the next run.

Logic:
  1. Gather all leads with a known conversion outcome (converted / lost).
  2. For each BANT dimension, compute the mean score for converted vs lost leads.
  3. Dimension weight ∝ (converted_mean − lost_mean) — dimensions that better
     separate winners from losers get higher weight.
  4. Persist the new weights and apply them to ICP scoring dynamically.

# PRODUCTION upgrades:
#   - Replace the heuristic weight update with a logistic regression or
#     gradient-boosted model (scikit-learn / XGBoost) trained on all outcomes.
#   - Use MLflow or Weights & Biases to track experiments across runs.
#   - Trigger retraining via a scheduled Celery task or Airflow DAG.
#   - A/B test the new model against the old one before fully promoting it.
#   - Add feature engineering: intent signals, email engagement rates,
#     time-to-conversion, outreach channel, rep assigned, etc.
"""

import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.database.models import Lead, Verdict, OptimizationRun
from app.config import settings

log = logging.getLogger(__name__)

# Default BANT weights (must sum to 1.0)
_DEFAULT_WEIGHTS = {
    "budget":    0.25,
    "authority": 0.25,
    "need":      0.25,
    "timeline":  0.25,
}

# Minimum sample of converted leads before we update weights
_MIN_CONVERSIONS = 10

# How aggressively to shift weights (0.0 = no change, 1.0 = fully replace)
_LEARNING_RATE = 0.3


def run_optimization(db: Session) -> dict:
    """
    Run one optimization cycle.

    Returns a dict with old_weights, new_weights, improvement_score, and sample_size.
    If insufficient data, returns {"status": "skipped", "reason": ...}.
    """
    converted, lost = _gather_outcomes(db)

    if len(converted) < _MIN_CONVERSIONS:
        log.info(
            f"[optimization] Not enough conversions yet ({len(converted)}/{_MIN_CONVERSIONS}) — skipping"
        )
        return {
            "status": "skipped",
            "reason": f"Need {_MIN_CONVERSIONS} conversions, have {len(converted)}",
        }

    old_weights = _load_current_weights(db)
    new_weights = _compute_new_weights(converted, lost, old_weights)

    improvement = _estimate_improvement(converted, lost, old_weights, new_weights)

    # Only persist if weights actually improved (avoid noisy updates)
    if improvement > 0:
        run = OptimizationRun(
            old_weights=old_weights,
            new_weights=new_weights,
            improvement_score=improvement,
            sample_size=len(converted) + len(lost),
            notes=(
                f"Converted: {len(converted)}, Lost: {len(lost)}. "
                f"Improvement: {improvement:.4f}"
            ),
        )
        db.add(run)
        db.commit()
        log.info(
            f"[optimization] Weights updated: {old_weights} → {new_weights} "
            f"(improvement={improvement:.4f})"
        )
    else:
        log.info(f"[optimization] No improvement found (score={improvement:.4f}) — keeping current weights")

    return {
        "status": "ran",
        "old_weights": old_weights,
        "new_weights": new_weights,
        "improvement_score": improvement,
        "sample_size": len(converted) + len(lost),
        "applied": improvement > 0,
    }


def get_current_weights(db: Session) -> dict:
    """Return the most recently applied weights, or defaults if none exist."""
    return _load_current_weights(db)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gather_outcomes(db: Session) -> tuple[list[dict], list[dict]]:
    """
    Returns (converted, lost) — lists of BANT score dicts for leads with
    known conversion outcomes.
    """
    converted: list[dict] = []
    lost: list[dict] = []

    leads = (
        db.query(Lead)
        .filter(Lead.conversion_status.in_(["converted", "lost"]))
        .all()
    )

    for lead in leads:
        verdict = (
            db.query(Verdict)
            .filter(Verdict.lead_id == lead.id, Verdict.bant_scores.isnot(None))
            .first()
        )
        if not verdict or not verdict.bant_scores:
            continue
        scores = verdict.bant_scores  # {"budget": float, "authority": float, ...}
        if lead.conversion_status == "converted":
            converted.append(scores)
        else:
            lost.append(scores)

    return converted, lost


def _load_current_weights(db: Session) -> dict:
    """Load the most recent optimization weights, falling back to defaults."""
    latest = (
        db.query(OptimizationRun)
        .order_by(OptimizationRun.run_at.desc())
        .first()
    )
    if latest and latest.new_weights:
        return dict(latest.new_weights)
    return dict(_DEFAULT_WEIGHTS)


def _compute_new_weights(
    converted: list[dict],
    lost: list[dict],
    old_weights: dict,
) -> dict:
    """
    Compute updated BANT weights based on which dimensions best separate
    converted from lost leads.

    Strategy: weight ∝ (mean_converted[dim] − mean_lost[dim]).
    Blend with old weights using the learning rate to avoid large swings.
    """
    dims = list(_DEFAULT_WEIGHTS.keys())

    def mean_score(records: list[dict], dim: str) -> float:
        vals = [r.get(dim, 0.5) for r in records if isinstance(r.get(dim), (int, float))]
        return sum(vals) / len(vals) if vals else 0.5

    separations = {}
    for dim in dims:
        conv_mean = mean_score(converted, dim)
        lost_mean = mean_score(lost, dim)
        separations[dim] = max(0.0, conv_mean - lost_mean)

    total_sep = sum(separations.values())
    if total_sep == 0:
        # Dimensions are equally predictive — keep equal weights
        raw_weights = {dim: 0.25 for dim in dims}
    else:
        raw_weights = {dim: separations[dim] / total_sep for dim in dims}

    # Blend with old weights
    new_weights = {
        dim: round(old_weights.get(dim, 0.25) * (1 - _LEARNING_RATE) + raw_weights[dim] * _LEARNING_RATE, 4)
        for dim in dims
    }

    # Renormalise so weights sum to 1.0
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {dim: round(v / total, 4) for dim, v in new_weights.items()}

    return new_weights


def _estimate_improvement(
    converted: list[dict],
    lost: list[dict],
    old_weights: dict,
    new_weights: dict,
) -> float:
    """
    Estimate improvement as the increase in AUC-like separation score
    between converted and lost leads under the new weights vs old.

    Score = mean weighted_score(converted) − mean weighted_score(lost)
    """
    def weighted_score(bant: dict, weights: dict) -> float:
        return sum(bant.get(dim, 0.5) * w for dim, w in weights.items())

    def separation(records_pos, records_neg, weights):
        pos = [weighted_score(r, weights) for r in records_pos]
        neg = [weighted_score(r, weights) for r in records_neg]
        return (sum(pos) / len(pos) if pos else 0) - (sum(neg) / len(neg) if neg else 0)

    old_sep = separation(converted, lost, old_weights)
    new_sep = separation(converted, lost, new_weights)
    return round(new_sep - old_sep, 6)


def get_optimization_history(db: Session, limit: int = 20) -> list[dict]:
    """Return recent optimization runs for the analytics dashboard."""
    runs = (
        db.query(OptimizationRun)
        .order_by(OptimizationRun.run_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "run_at": r.run_at.isoformat(),
            "old_weights": r.old_weights,
            "new_weights": r.new_weights,
            "improvement_score": r.improvement_score,
            "sample_size": r.sample_size,
            "notes": r.notes,
        }
        for r in runs
    ]
