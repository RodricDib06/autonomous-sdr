"""
ICP (Ideal Customer Profile) service.

Stores and evaluates the user-defined ICP against lead enrichment data.
The config is a singleton row in the icp_config table (id="default").
All criteria are optional — unset criteria are skipped when evaluating.
"""

from __future__ import annotations
import re
from typing import TypedDict
from app.utils.time import utcnow


# ---------------------------------------------------------------------------
# Company-size parser
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)")
_PLUS_RE  = re.compile(r"(\d[\d,]*)\s*\+")
_SOLE_RE  = re.compile(r"^\s*(\d[\d,]*)\s*$")


def parse_company_size(raw: str | None) -> int | None:
    """
    Parse enrichment.company_size into an integer midpoint.

    Examples
    --------
    "100-200"   → 150
    "1000+"     → 1000
    "1-10"      → 5
    "500"       → 500
    None / ""   → None
    """
    if not raw:
        return None
    raw = raw.strip().replace(",", "")

    m = _RANGE_RE.search(raw)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo + hi) // 2

    m = _PLUS_RE.search(raw)
    if m:
        return int(m.group(1))

    m = _SOLE_RE.match(raw)
    if m:
        return int(m.group(1))

    return None


# ---------------------------------------------------------------------------
# Criterion evaluation result
# ---------------------------------------------------------------------------

class ICPEvaluation(TypedDict):
    overall: bool | None       # None when no criteria are configured
    matched: list[str]         # human-readable passing criteria
    missed: list[str]          # human-readable failing criteria
    criteria_count: int


def evaluate_icp(enrichment, config) -> ICPEvaluation:
    """
    Evaluate a lead's enrichment data against the stored ICP config.

    Returns an ICPEvaluation dict with `overall`, `matched`, and `missed`.
    If `config` is None or no criteria are set, returns `overall=None`.
    """
    empty: ICPEvaluation = {
        "overall": None,
        "matched": [],
        "missed": [],
        "criteria_count": 0,
    }

    if config is None or enrichment is None:
        return empty

    matched: list[str] = []
    missed: list[str] = []

    # ── Target industries ────────────────────────────────────────────────────
    if config.industries:
        ind = (enrichment.industry or "").strip()
        if ind in config.industries:
            matched.append(f"Industry: {ind}")
        else:
            matched_partial = next(
                (t for t in config.industries if t.lower() in ind.lower()), None
            )
            if matched_partial:
                matched.append(f"Industry: {ind} (partial match to {matched_partial})")
            else:
                missed.append(
                    f"Industry: {ind or 'unknown'} — target: {', '.join(config.industries)}"
                )

    # ── Excluded industries ──────────────────────────────────────────────────
    if config.excluded_industries:
        ind = (enrichment.industry or "").strip()
        if ind and ind in config.excluded_industries:
            missed.append(f"Industry: {ind} is excluded")

    # ── Seniority levels ─────────────────────────────────────────────────────
    if config.seniority_levels:
        sen = (enrichment.seniority or "").strip()
        if sen in config.seniority_levels:
            matched.append(f"Seniority: {sen}")
        else:
            missed.append(
                f"Seniority: {sen or 'unknown'} — target: {', '.join(config.seniority_levels)}"
            )

    # ── Company size ─────────────────────────────────────────────────────────
    has_size_filter = (
        config.min_employees is not None or config.max_employees is not None
    )
    if has_size_filter:
        emp = parse_company_size(enrichment.company_size)
        if emp is not None:
            too_small = config.min_employees and emp < config.min_employees
            too_large = config.max_employees and emp > config.max_employees
            if not too_small and not too_large:
                matched.append(
                    f"Company size: {enrichment.company_size} in range "
                    f"{config.min_employees or 0}–{config.max_employees or '∞'}"
                )
            else:
                missed.append(
                    f"Company size: {enrichment.company_size} outside range "
                    f"{config.min_employees or 0}–{config.max_employees or '∞'}"
                )
        # Can't parse → don't penalise (missing data is not a disqualifier)

    total = len(matched) + len(missed)
    overall: bool | None = (len(missed) == 0) if total > 0 else None

    return {
        "overall": overall,
        "matched": matched,
        "missed": missed,
        "criteria_count": total,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_icp_config(db, org_id: str | None = None):
    """Return the org's ICPConfig row (falls back to the legacy singleton)."""
    from app.database.models import ICPConfig
    if org_id is not None:
        cfg = db.query(ICPConfig).filter(ICPConfig.org_id == org_id).first()
        if cfg is not None:
            return cfg
    return db.query(ICPConfig).filter(ICPConfig.id == "default").first()


def upsert_icp_config(db, user_id: str, org_id: str | None = None, **fields):
    """Create or update the org's ICP config row (one per organization)."""
    from app.database.models import ICPConfig

    row_id = org_id or "default"
    cfg = db.query(ICPConfig).filter(ICPConfig.id == row_id).first()
    if cfg is None:
        cfg = ICPConfig(id=row_id, org_id=org_id)
        db.add(cfg)

    for k, v in fields.items():
        setattr(cfg, k, v)
    cfg.updated_at = utcnow()
    cfg.updated_by_id = user_id

    db.commit()
    db.refresh(cfg)
    return cfg


def icp_match_counts(db) -> dict:
    """
    Return how many leads currently match the ICP, broken down by verdict.
    Used for the live preview on the ICP Builder page.
    """
    from app.database.models import Lead
    from sqlalchemy.orm import selectinload

    config = get_icp_config(db)
    if config is None:
        return {"total": 0, "matched": 0, "hot": 0, "warm": 0, "cold": 0, "unconfigured": True}

    leads = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.status == "complete", Lead.archived == False)  # noqa: E712
        .all()
    )

    counts = {"total": len(leads), "matched": 0, "hot": 0, "warm": 0, "cold": 0, "unconfigured": False}
    for lead in leads:
        enrichment = lead.enrichments[0] if lead.enrichments else None
        verdict = lead.verdicts[0] if lead.verdicts else None
        ev = evaluate_icp(enrichment, config)
        if ev["overall"]:
            counts["matched"] += 1
            if verdict:
                key = verdict.final_verdict.lower() if verdict.final_verdict else None
                if key in counts:
                    counts[key] += 1

    return counts
