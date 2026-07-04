"""
Close probability predictor using logistic regression.

Trains on leads with known conversion outcomes (converted / lost).
Falls back to a BANT-weighted estimate when training data is insufficient.

The model is a module-level singleton — lazy-trained on first prediction
request and re-trainable via retrain().
"""

from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock
from app.utils.time import utcnow

log = logging.getLogger(__name__)

FEATURE_NAMES = [
    "budget",
    "authority",
    "need",
    "timeline",
    "data_quality",
    "completeness",
    "icp_match",
    "seniority",
]

_SENIORITY_SCORES: dict[str, float] = {
    "C-Level": 1.0,
    "VP": 0.8,
    "Director": 0.6,
    "Manager": 0.4,
    "IC": 0.2,
}

_MIN_PER_CLASS = 3


def _build_feature_vector(lead, verdict, enrichment) -> list[float]:
    bant = verdict.bant_scores or {}
    seniority = _SENIORITY_SCORES.get(
        (enrichment.seniority or "") if enrichment else "", 0.3
    )
    return [
        float(bant.get("budget", 0.5)),
        float(bant.get("authority", 0.5)),
        float(bant.get("need", 0.5)),
        float(bant.get("timeline", 0.5)),
        float(lead.data_quality_score or 0.5),
        float(lead.completeness_score or 0.5),
        1.0 if verdict.icp_match else 0.0,
        seniority,
    ]


class CloseProbabilityModel:
    def __init__(self) -> None:
        self._model = None
        self._scaler = None
        self._lock = Lock()
        self.trained_at: datetime | None = None
        self.n_samples: int = 0
        self.n_converted: int = 0
        self.n_lost: int = 0

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(self, db) -> bool:
        """
        Build training set from leads with known outcomes and fit a
        logistic regression. Returns True if training succeeded.
        """
        try:
            import numpy as np
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            log.warning("scikit-learn not installed — ML scoring unavailable")
            return False

        try:
            from sqlalchemy.orm import selectinload
            from app.database.models import Lead

            rows = (
                db.query(Lead)
                .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
                .filter(Lead.conversion_status.in_(["converted", "lost"]))
                .all()
            )

            X, y = [], []
            for lead in rows:
                verdict = lead.verdicts[0] if lead.verdicts else None
                if not verdict or not verdict.bant_scores:
                    continue
                enrichment = lead.enrichments[0] if lead.enrichments else None
                X.append(_build_feature_vector(lead, verdict, enrichment))
                y.append(1 if lead.conversion_status == "converted" else 0)

            positives = sum(y)
            negatives = len(y) - positives
            if positives < _MIN_PER_CLASS or negatives < _MIN_PER_CLASS:
                log.info(
                    "Insufficient labeled leads for ML training",
                    converted=positives,
                    lost=negatives,
                    required=_MIN_PER_CLASS,
                )
                return False

            X_arr = np.array(X, dtype=float)
            y_arr = np.array(y, dtype=int)

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_arr)

            model = LogisticRegression(random_state=42, max_iter=500, C=1.0)
            model.fit(X_scaled, y_arr)

            with self._lock:
                self._model = model
                self._scaler = scaler
                self.trained_at = utcnow()
                self.n_samples = len(X)
                self.n_converted = positives
                self.n_lost = negatives

            log.info(
                "ML close probability model trained",
                n_samples=len(X),
                converted=positives,
                lost=negatives,
            )
            return True

        except Exception as exc:
            log.error("ML training failed", error=str(exc))
            return False

    def predict(self, lead, verdict, enrichment) -> dict | None:
        """
        Predict close probability for a single lead.
        Returns None if the model isn't trained yet.
        """
        with self._lock:
            if self._model is None:
                return None
            model = self._model
            scaler = self._scaler

        try:
            import numpy as np

            fv = _build_feature_vector(lead, verdict, enrichment)
            X = np.array([fv], dtype=float)
            X_scaled = scaler.transform(X)

            probability = float(model.predict_proba(X_scaled)[0][1])

            # Normalise coefficients to [-1, 1] for display
            coefs = model.coef_[0]
            max_abs = float(max(abs(c) for c in coefs)) or 1.0
            importances = {
                name: round(float(c / max_abs), 3)
                for name, c in zip(FEATURE_NAMES, coefs)
            }

            return {
                "probability": round(probability, 3),
                "importances": importances,
                "n_samples": self.n_samples,
                "n_converted": self.n_converted,
                "n_lost": self.n_lost,
                "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            }
        except Exception as exc:
            log.error("ML prediction failed", error=str(exc))
            return None


# Module-level singleton
_instance = CloseProbabilityModel()


def get_model() -> CloseProbabilityModel:
    return _instance


def ensure_trained(db) -> bool:
    """Train the singleton if not already trained."""
    if _instance.is_trained:
        return True
    return _instance.train(db)


def retrain(db) -> bool:
    """Force a full retrain regardless of current state."""
    return _instance.train(db)
