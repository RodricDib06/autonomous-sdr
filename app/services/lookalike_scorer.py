"""
ICP Lookalike Scorer

Computes how similar a lead is to your historically converted leads using
cosine similarity against a centroid computed from all converted leads.

Unlike the BANT-rules-based intent score, this is a purely learned signal:
the system discovers which lead profiles actually convert and scores new leads
against that observed pattern — not against a manually-configured ICP.

Algorithm:
  1. Gather all leads with conversion_status="converted"
  2. Build 8-dimensional feature vectors: [budget, authority, need, timeline,
     seniority, icp_match, data_quality, completeness]
  3. Compute the centroid (mean vector) across all converted leads
  4. For any lead, compute cosine similarity to the centroid
  5. Persist on Lead.lookalike_score (0.0–1.0)

The centroid is recomputed on each call to update_all_lookalike_scores()
so the signal improves automatically as more conversions accumulate.

Minimum 5 converted leads are required before scores are meaningful.
Below that threshold the function returns None without updating scores.
"""

from __future__ import annotations

import logging
import math
from sqlalchemy.orm import Session, selectinload

log = logging.getLogger(__name__)

_MIN_CONVERTED = 5

_SENIORITY_SCORES: dict[str, float] = {
    "C-Suite": 1.0, "VP": 0.8, "Director": 0.6,
    "Manager": 0.4, "Mid-Level": 0.3, "Senior": 0.35,
    "Junior": 0.1, "IC": 0.1,
}


def _feature_vector(lead, verdict, enrichment) -> list[float] | None:
    """Return an 8-dimensional feature vector or None if insufficient data."""
    bant = (verdict.bant_scores or {}) if verdict else {}
    if not bant:
        return None
    seniority = _SENIORITY_SCORES.get(
        (enrichment.seniority or "") if enrichment else "", 0.3
    )
    return [
        float(bant.get("budget", 0.5)),
        float(bant.get("authority", 0.5)),
        float(bant.get("need", 0.5)),
        float(bant.get("timeline", 0.5)),
        seniority,
        1.0 if (verdict and verdict.icp_match) else 0.0,
        float(lead.data_quality_score or 0.5),
        float(lead.completeness_score or 0.5),
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a)) or 1e-9
    mag_b = math.sqrt(sum(x * x for x in b)) or 1e-9
    return dot / (mag_a * mag_b)


def _compute_centroid(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / n for i in range(dim)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_converted_centroid(db: Session) -> list[float] | None:
    """
    Compute the centroid of all converted leads' feature vectors.
    Returns None if fewer than _MIN_CONVERTED leads are available.
    """
    from app.database.models import Lead

    converted = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.conversion_status == "converted")
        .all()
    )

    vectors = []
    for lead in converted:
        verdict = lead.verdicts[0] if lead.verdicts else None
        enrichment = lead.enrichments[0] if lead.enrichments else None
        vec = _feature_vector(lead, verdict, enrichment)
        if vec:
            vectors.append(vec)

    if len(vectors) < _MIN_CONVERTED:
        log.info(
            f"[lookalike] Only {len(vectors)} converted leads with BANT data "
            f"(need {_MIN_CONVERTED}) — skipping centroid computation"
        )
        return None

    centroid = _compute_centroid(vectors)
    log.info(f"[lookalike] Centroid computed from {len(vectors)} converted leads")
    return centroid


def score_lead_against_centroid(lead, verdict, enrichment, centroid: list[float]) -> float:
    """Return cosine similarity of this lead to the centroid. 0.0 if no BANT data."""
    vec = _feature_vector(lead, verdict, enrichment)
    if not vec:
        return 0.0
    return round(_cosine(vec, centroid), 4)


def update_lead_lookalike_score(db: Session, lead_id: str) -> float | None:
    """
    Recompute and persist the lookalike score for a single lead.
    Called at the end of the pipeline (node_sync_crm) when a lead completes.
    Returns the score or None if centroid unavailable.
    """
    from app.database.models import Lead

    centroid = compute_converted_centroid(db)
    if centroid is None:
        return None

    lead = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        return None

    verdict = lead.verdicts[0] if lead.verdicts else None
    enrichment = lead.enrichments[0] if lead.enrichments else None
    score = score_lead_against_centroid(lead, verdict, enrichment, centroid)

    lead.lookalike_score = score
    db.commit()
    log.info(f"[lookalike] Lead {lead_id[:8]} lookalike_score={score:.3f}")
    return score


def update_all_lookalike_scores(db: Session) -> dict:
    """
    Recompute lookalike scores for all complete leads. Run nightly via scheduler.
    Returns summary: {updated, skipped, centroid_available}.
    """
    from app.database.models import Lead

    centroid = compute_converted_centroid(db)
    if centroid is None:
        return {"updated": 0, "skipped": 0, "centroid_available": False}

    all_leads = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.status == "complete", Lead.archived == False)  # noqa: E712
        .all()
    )

    updated = 0
    skipped = 0
    for lead in all_leads:
        verdict = lead.verdicts[0] if lead.verdicts else None
        enrichment = lead.enrichments[0] if lead.enrichments else None
        score = score_lead_against_centroid(lead, verdict, enrichment, centroid)
        if score > 0:
            lead.lookalike_score = score
            updated += 1
        else:
            skipped += 1

    db.commit()
    log.info(f"[lookalike] Batch update complete: {updated} updated, {skipped} skipped")
    return {"updated": updated, "skipped": skipped, "centroid_available": True}
