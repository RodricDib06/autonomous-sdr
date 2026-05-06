"""
Data Quality Scoring service.

Produces three scores per lead:
  completeness_score  – % of expected fields that are filled (0-100)
  freshness_score     – how recently the lead was updated (0-100, not stored)
  data_quality_score  – weighted combination of all signals (0-100)

Stored on Lead: completeness_score, data_quality_score, quality_metadata, updated_at.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.database.models import Lead


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
_COMPLETENESS_WEIGHT = 0.40
_FRESHNESS_WEIGHT = 0.30
_EMAIL_QUALITY_WEIGHT = 0.30

# Lead base fields and their point values (sum = 50)
_BASE_FIELDS: dict[str, int] = {
    "name": 15,
    "email": 15,
    "company": 15,
    "source": 5,
}

# Enrichment fields and their point values (sum = 50)
_ENRICHMENT_FIELDS: dict[str, int] = {
    "job_title": 15,
    "seniority": 10,
    "company_size": 10,
    "industry": 10,
    "revenue_estimate": 5,
}

_MAX_COMPLETENESS = sum(_BASE_FIELDS.values()) + sum(_ENRICHMENT_FIELDS.values())  # 100


class DataQualityService:

    def calculate_completeness(self, lead: "Lead") -> tuple[float, dict]:
        """Return (score 0-100, breakdown dict)."""
        breakdown: dict[str, bool] = {}
        earned = 0

        for field, pts in _BASE_FIELDS.items():
            val = getattr(lead, field, None)
            present = bool(val and str(val).strip())
            breakdown[field] = present
            if present:
                earned += pts

        enrichment = lead.enrichments[0] if lead.enrichments else None
        for field, pts in _ENRICHMENT_FIELDS.items():
            val = getattr(enrichment, field, None) if enrichment else None
            present = bool(val and str(val).strip())
            breakdown[f"enrichment_{field}"] = present
            if present:
                earned += pts

        score = round(earned / _MAX_COMPLETENESS * 100, 1)
        return score, breakdown

    def calculate_freshness_score(self, lead: "Lead") -> float:
        """Return score 0-100 based on how recently the lead was updated."""
        reference = lead.updated_at or lead.created_at
        if reference is None:
            return 50.0

        now = datetime.utcnow()
        # Make naive comparison safe
        if reference.tzinfo is not None:
            now = now.replace(tzinfo=timezone.utc)

        age_days = (now - reference).days

        if age_days < 7:
            return 100.0
        if age_days < 30:
            return 80.0
        if age_days < 90:
            return 60.0
        if age_days < 180:
            return 30.0
        return 10.0

    def calculate_email_quality_score(self, email: str) -> tuple[float, str]:
        """Return (score 0-100, quality_label) without doing a live DNS lookup."""
        from app.services.validation import EmailDomainValidator, TEMPORARY_EMAIL_DOMAINS, FREE_EMAIL_DOMAINS

        if not email or "@" not in email:
            return 0.0, "invalid"

        domain = email.split("@")[1].lower()

        if domain in TEMPORARY_EMAIL_DOMAINS:
            return 0.0, "temporary"

        email_result = EmailDomainValidator.validate_email_format(email)
        if not email_result.is_valid:
            return 0.0, "invalid"

        if domain in FREE_EMAIL_DOMAINS:
            return 60.0, "free"

        return 90.0, "corporate"

    def calculate_overall_score(self, lead: "Lead") -> dict:
        """Compute and return all quality signals without persisting."""
        completeness, breakdown = self.calculate_completeness(lead)
        freshness = self.calculate_freshness_score(lead)
        email_score, email_label = self.calculate_email_quality_score(lead.email or "")

        overall = round(
            completeness * _COMPLETENESS_WEIGHT
            + freshness * _FRESHNESS_WEIGHT
            + email_score * _EMAIL_QUALITY_WEIGHT,
            1,
        )

        return {
            "completeness_score": completeness,
            "freshness_score": freshness,
            "email_quality_score": email_score,
            "email_quality_label": email_label,
            "data_quality_score": overall,
            "breakdown": breakdown,
        }

    def update_lead_quality(self, db: Session, lead: "Lead") -> dict:
        """Compute quality scores, persist to lead, and return the result."""
        scores = self.calculate_overall_score(lead)

        lead.completeness_score = scores["completeness_score"]
        lead.data_quality_score = scores["data_quality_score"]
        lead.updated_at = datetime.utcnow()
        lead.quality_metadata = {
            "freshness_score": scores["freshness_score"],
            "email_quality_score": scores["email_quality_score"],
            "email_quality_label": scores["email_quality_label"],
            "breakdown": scores["breakdown"],
            "scored_at": datetime.utcnow().isoformat(),
        }

        db.add(lead)
        db.commit()
        db.refresh(lead)
        return scores

    def get_quality_report(self, db: Session) -> dict:
        """System-wide quality summary."""
        from sqlalchemy import func
        from app.database.models import Lead

        total = db.query(Lead).count()
        scored = db.query(Lead).filter(Lead.data_quality_score.isnot(None)).count()

        avg_quality = (
            db.query(func.avg(Lead.data_quality_score))
            .filter(Lead.data_quality_score.isnot(None))
            .scalar()
        )
        avg_completeness = (
            db.query(func.avg(Lead.completeness_score))
            .filter(Lead.completeness_score.isnot(None))
            .scalar()
        )

        # Distribution buckets
        def _bucket(col, lo, hi):
            return (
                db.query(Lead)
                .filter(col >= lo, col < hi, col.isnot(None))
                .count()
            )

        quality_col = Lead.data_quality_score
        distribution = {
            "excellent_80_100": _bucket(quality_col, 80, 101),
            "good_60_80": _bucket(quality_col, 60, 80),
            "fair_40_60": _bucket(quality_col, 40, 60),
            "poor_0_40": _bucket(quality_col, 0, 40),
        }

        return {
            "total_leads": total,
            "scored_leads": scored,
            "unscored_leads": total - scored,
            "average_quality_score": round(avg_quality or 0, 1),
            "average_completeness_score": round(avg_completeness or 0, 1),
            "quality_distribution": distribution,
        }
