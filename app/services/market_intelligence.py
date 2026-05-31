"""
Market Intelligence — cross-lead pattern analysis.

Analyses conversion patterns across lead segments (industry × seniority) to
surface which combinations convert at higher-than-average rates.

This is the "learning across leads" capability:
  - Segment: FinTech × VP → 41% hot rate vs 18% global average → 2.3× lift
  - Segment: SaaS × C-Level → 38% hot rate → 2.1× lift

Results feed the Analytics "Market Intelligence" card and can inform
weight adjustments in future optimization runs.
"""

from __future__ import annotations
import logging
from datetime import datetime

log = logging.getLogger(__name__)

_MIN_SEGMENT_SIZE = 3  # ignore segments with too few leads


def compute_market_intelligence(db) -> dict:
    """
    Analyse all complete leads and return segment-level conversion patterns.

    Returns:
        segments       — list of (industry, seniority, hot_rate, lift, counts)
        global_stats   — baseline hot_rate and total counts
        top_industries — industry-only breakdown
        computed_at    — ISO timestamp
    """
    from sqlalchemy.orm import selectinload
    from app.database.models import Lead, Verdict, Enrichment

    leads = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.status == "complete", Lead.archived == False)  # noqa: E712
        .all()
    )

    # ── Global baseline ──────────────────────────────────────────────────────
    global_counts = {"total": 0, "hot": 0, "warm": 0, "cold": 0}
    # segment_key → {total, hot, warm, cold, industry, seniority}
    segments: dict[tuple, dict] = {}
    industry_map: dict[str, dict] = {}

    for lead in leads:
        verdict = lead.verdicts[0] if lead.verdicts else None
        enrichment = lead.enrichments[0] if lead.enrichments else None
        if not verdict or not verdict.final_verdict:
            continue

        v_lower = verdict.final_verdict.lower()
        industry = (enrichment.industry or "Unknown").strip() if enrichment else "Unknown"
        seniority = (enrichment.seniority or "Unknown").strip() if enrichment else "Unknown"

        global_counts["total"] += 1
        global_counts[v_lower] = global_counts.get(v_lower, 0) + 1

        # ── Segment (industry × seniority) ──────────────────────────────────
        key = (industry, seniority)
        if key not in segments:
            segments[key] = {
                "industry": industry,
                "seniority": seniority,
                "total": 0, "hot": 0, "warm": 0, "cold": 0,
            }
        segments[key]["total"] += 1
        segments[key][v_lower] = segments[key].get(v_lower, 0) + 1

        # ── Industry-only breakdown ──────────────────────────────────────────
        if industry not in industry_map:
            industry_map[industry] = {"industry": industry, "total": 0, "hot": 0, "warm": 0, "cold": 0}
        industry_map[industry]["total"] += 1
        industry_map[industry][v_lower] = industry_map[industry].get(v_lower, 0) + 1

    total = global_counts["total"]
    global_hot_rate = global_counts["hot"] / total if total else 0.0

    # ── Enrich segments with rates + lift ────────────────────────────────────
    enriched_segments = []
    for seg in segments.values():
        if seg["total"] < _MIN_SEGMENT_SIZE:
            continue
        hot_rate = seg["hot"] / seg["total"]
        warm_rate = seg["warm"] / seg["total"]
        lift = hot_rate / global_hot_rate if global_hot_rate > 0 else 1.0
        enriched_segments.append({
            **seg,
            "hot_rate": round(hot_rate, 3),
            "warm_rate": round(warm_rate, 3),
            "lift": round(lift, 2),
        })

    enriched_segments.sort(key=lambda s: s["lift"], reverse=True)

    # ── Industry breakdown ───────────────────────────────────────────────────
    top_industries = []
    for ind in industry_map.values():
        if ind["total"] < 2:
            continue
        hr = ind["hot"] / ind["total"]
        top_industries.append({
            **ind,
            "hot_rate": round(hr, 3),
            "lift": round(hr / global_hot_rate, 2) if global_hot_rate else 1.0,
        })
    top_industries.sort(key=lambda i: i["hot_rate"], reverse=True)

    return {
        "segments": enriched_segments[:20],
        "top_industries": top_industries[:10],
        "global_stats": {
            **global_counts,
            "global_hot_rate": round(global_hot_rate, 3),
        },
        "computed_at": datetime.utcnow().isoformat(),
    }


def similar_leads(db, lead_id: str, limit: int = 5) -> list[dict]:
    """
    Return the top *limit* leads most similar to *lead_id* by BANT profile
    and enrichment features, using cosine similarity.

    Works without pgvector — pure Python cosine similarity over a
    7-dimensional feature vector: [budget, authority, need, timeline,
    seniority_score, icp_match, data_quality].
    """
    import math
    from sqlalchemy.orm import selectinload
    from app.database.models import Lead, Verdict, Enrichment

    _SENIORITY = {"C-Level": 1.0, "VP": 0.8, "Director": 0.6, "Manager": 0.4, "IC": 0.2}

    def feature_vector(lead, verdict, enrichment) -> list[float] | None:
        bant = verdict.bant_scores if verdict else None
        if not bant:
            return None
        sen = _SENIORITY.get((enrichment.seniority or "") if enrichment else "", 0.3)
        return [
            float(bant.get("budget", 0.5)),
            float(bant.get("authority", 0.5)),
            float(bant.get("need", 0.5)),
            float(bant.get("timeline", 0.5)),
            sen,
            1.0 if (verdict.icp_match is True) else 0.0,
            float(lead.data_quality_score or 0.5),
        ]

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a)) or 1e-9
        mag_b = math.sqrt(sum(x * x for x in b)) or 1e-9
        return dot / (mag_a * mag_b)

    # Target lead
    target = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not target:
        return []

    t_verdict = target.verdicts[0] if target.verdicts else None
    t_enrichment = target.enrichments[0] if target.enrichments else None
    target_vec = feature_vector(target, t_verdict, t_enrichment)
    if target_vec is None:
        return []

    # All other complete leads
    candidates = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.status == "complete", Lead.id != lead_id, Lead.archived == False)  # noqa: E712
        .limit(500)
        .all()
    )

    scored = []
    for c in candidates:
        c_verdict = c.verdicts[0] if c.verdicts else None
        c_enrichment = c.enrichments[0] if c.enrichments else None
        vec = feature_vector(c, c_verdict, c_enrichment)
        if vec is None:
            continue
        sim = cosine(target_vec, vec)
        scored.append({
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "company": c.company,
            "verdict": c_verdict.final_verdict if c_verdict else None,
            "confidence": c_verdict.confidence_score if c_verdict else None,
            "job_title": c_enrichment.job_title if c_enrichment else None,
            "industry": c_enrichment.industry if c_enrichment else None,
            "seniority": c_enrichment.seniority if c_enrichment else None,
            "similarity": round(sim, 3),
        })

    scored.sort(key=lambda r: r["similarity"], reverse=True)
    return scored[:limit]
