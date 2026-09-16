"""
A/B test results and the BANT self-optimization loop.

Extracted from app/main.py, which had grown to ~3.5k lines and 87 endpoints.
Route order matters in FastAPI — concrete paths must be registered before the
`/{lead_id}` style catch-alls — and that is far easier to keep right in a
file scoped to one concern.
"""

import json  # noqa: F401
import re  # noqa: F401
import asyncio  # noqa: F401
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks  # noqa: F401
from fastapi.responses import Response, RedirectResponse, StreamingResponse  # noqa: F401
from sqlalchemy.orm import Session  # noqa: F401
import structlog

from app.database.connection import get_db  # noqa: F401
from app.database import crud  # noqa: F401
from app.database.models import Lead, Enrichment, Verdict, User  # noqa: F401
from app.auth.dependencies import require_admin, require_manager, require_rep  # noqa: F401
from app.config import settings  # noqa: F401
from app.utils.time import utcnow  # noqa: F401
from app.services.queue_service import push_lead_job, get_redis  # noqa: F401

log = structlog.get_logger(__name__)

router = APIRouter(tags=["experiments"])


@router.get("/ab-tests/results")
def get_ab_results(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return per-variant conversion metrics for all outreach sequences."""
    from app.services.ab_testing import get_test_results, _chi_square_p, _MIN_SAMPLE
    from app.database.models import OutreachSequence

    raw = get_test_results(db)

    # Attach sequence names and normalise field names for the frontend
    seq_names: dict[str, str] = {
        s.id: s.name
        for s in db.query(OutreachSequence).all()
    }
    variants = [
        {
            "sequence_id": r["sequence_id"],
            "sequence_name": seq_names.get(r["sequence_id"], r["sequence_id"]),
            "variant": r["variant"],
            "emails_sent": r["emails_sent"],
            "opens": r["emails_opened"],
            "replies": int(r["reply_rate"] * r["emails_sent"]) if r["emails_sent"] else 0,
            "conversions": int(r["conversion_rate"] * r["emails_sent"]) if r["emails_sent"] else 0,
            "open_rate": r["open_rate"],
            "reply_rate": r["reply_rate"],
            "conversion_rate": r["conversion_rate"],
        }
        for r in raw
    ]

    # Compute significance across the two most-sent variants
    winner_variant: str | None = None
    p_value: float | None = None
    significant = False
    total_sample = sum(v["emails_sent"] for v in variants)

    eligible = [v for v in variants if v["emails_sent"] >= _MIN_SAMPLE]
    if len(eligible) >= 2:
        eligible.sort(key=lambda v: v["conversion_rate"], reverse=True)
        best, second = eligible[0], eligible[1]
        p = _chi_square_p(
            best["conversions"], best["emails_sent"],
            second["conversions"], second["emails_sent"],
        )
        p_value = round(p, 4)
        if p < 0.05:
            significant = True
            winner_variant = best["variant"]

    return {
        "variants": variants,
        "winner": winner_variant,
        "p_value": p_value,
        "significant": significant,
        "sample_size": total_sample,
    }

@router.post("/ab-tests/promote-winner")
def promote_ab_winner_legacy(
    sequence_id: str = Query(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Legacy query-param route — prefer POST /ab-tests/{sequence_id}/promote."""
    from app.services.ab_testing import promote_winner
    promote_winner(db, sequence_id)
    return {"status": "promoted", "winning_sequence_id": sequence_id}

@router.post("/ab-tests/{sequence_id}/promote")
def promote_ab_winner(
    sequence_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deactivate all other sequences and promote this one as the winner."""
    from app.services.ab_testing import promote_winner
    promote_winner(db, sequence_id)
    return {"status": "promoted", "winning_sequence_id": sequence_id}

@router.post("/optimization/run")
def run_optimization(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Trigger a scoring weight optimization cycle based on conversion outcomes."""
    from app.services.optimization_loop import run_optimization as _run
    try:
        result = _run(db)
        return result
    except Exception as e:
        log.error("Optimization run failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/optimization/history")
def get_optimization_history(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return recent optimization runs with old/new weights and improvement scores."""
    from app.services.optimization_loop import get_optimization_history
    raw = get_optimization_history(db, limit=limit)
    runs = []
    for r in raw:
        old_w = r.get("old_weights") or {}
        new_w = r.get("new_weights") or {}
        delta = {k: round(new_w.get(k, 0) - old_w.get(k, 0), 4) for k in set(old_w) | set(new_w)}
        runs.append({
            "id": r["id"],
            "created_at": r["run_at"],
            "leads_analysed": r.get("sample_size", 0),
            "old_weights": old_w,
            "new_weights": new_w,
            "weight_delta": delta,
            "notes": r.get("notes"),
        })
    return {"runs": runs, "count": len(runs)}

@router.get("/optimization/weights")
def get_current_weights_endpoint(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the BANT weights currently used for scoring."""
    from app.services.optimization_loop import get_current_weights
    return get_current_weights(db)

@router.get("/ab-tests/multi-axis")
def get_multi_axis_ab(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Break down A/B email performance by three axes derived from existing data:
      send_time_slot  — morning (6-12) | afternoon (12-17) | evening (17+)
      subject_style   — question (ends with ?) | statement
      message_length  — short (<300 chars) | long (≥300 chars)
    """
    from app.database.models import OutreachEmail as OE

    emails = db.query(OE).filter(OE.sent_at != None).all()  # noqa: E711

    def classify(email):
        slot = None
        if email.sent_at:
            h = email.sent_at.hour
            slot = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
        style = "question" if email.subject.rstrip().endswith("?") else "statement"
        length = "short" if len(email.body) < 300 else "long"
        opened = email.status in ("opened", "replied")
        replied = email.status == "replied"
        return slot, style, length, opened, replied

    def axis_breakdown(axis_vals, key_fn):
        result = {}
        for e in emails:
            slot, style, length, opened, replied = classify(e)
            key = key_fn(slot, style, length)
            if key is None:
                continue
            if key not in result:
                result[key] = {"label": key, "sent": 0, "opened": 0, "replied": 0}
            result[key]["sent"] += 1
            if opened:
                result[key]["opened"] += 1
            if replied:
                result[key]["replied"] += 1
        for r in result.values():
            s = r["sent"] or 1
            r["open_rate"] = round(r["opened"] / s, 3)
            r["reply_rate"] = round(r["replied"] / s, 3)
        return sorted(result.values(), key=lambda x: x["open_rate"], reverse=True)

    return {
        "send_time": axis_breakdown(emails, lambda sl, st, ln: sl),
        "subject_style": axis_breakdown(emails, lambda sl, st, ln: st),
        "message_length": axis_breakdown(emails, lambda sl, st, ln: ln),
        "total_emails_analysed": len(emails),
    }
