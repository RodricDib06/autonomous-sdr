"""
Backtest API — replay historical CRM exports through the qualifier.

Upload a CSV of past leads with known won/lost outcomes; get back a
calibration report ("the agent flagged X% of your closed-won deals as Hot")
plus per-row records for drill-down. Scoring is deterministic and synchronous
— 10k rows complete in seconds, so there is no job queue to babysit.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth.dependencies import require_manager, require_rep
from app.database.connection import get_db
from app.database.models import BacktestRecord, BacktestRun, User
from app.services.backtest import run_backtest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/backtests", tags=["backtests"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB ≈ well past the 20k row cap


def _serialize_run(run: BacktestRun, include_summary: bool = True) -> dict:
    data = {
        "id": run.id,
        "filename": run.filename,
        "status": run.status,
        "total_rows": run.total_rows,
        "skipped_rows": run.skipped_rows,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_summary:
        data["summary"] = run.summary
        data["errors"] = run.error_message
    return data


def _org_run_or_404(db: Session, run_id: str, user: User) -> BacktestRun:
    run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if not run or (user.org_id is not None and run.org_id != user.org_id):
        raise HTTPException(status_code=404, detail="Backtest not found")
    return run


@router.post("", status_code=201)
async def create_backtest(
    file: UploadFile = File(...),
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Upload a historical CSV (columns: name, email, company, outcome; optional:
    job_title, seniority, industry, company_size, revenue) and score it.
    """
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    try:
        content = raw.decode("utf-8-sig")  # tolerate Excel's BOM
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded CSV")

    try:
        run = run_backtest(
            db, content,
            filename=file.filename or "upload.csv",
            org_id=current_user.org_id,
            created_by_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    log.info(f"[backtests] Run {run.id[:8]} created by {current_user.email} ({run.total_rows} rows)")
    return _serialize_run(run)


@router.get("")
def list_backtests(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = db.query(BacktestRun)
    if current_user.org_id is not None:
        q = q.filter(BacktestRun.org_id == current_user.org_id)
    total = q.count()
    runs = q.order_by(BacktestRun.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "runs": [_serialize_run(r, include_summary=False) for r in runs]}


@router.get("/{run_id}")
def get_backtest(
    run_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Full calibration report for one run."""
    return _serialize_run(_org_run_or_404(db, run_id, current_user))


@router.get("/{run_id}/records")
def list_backtest_records(
    run_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    verdict: str | None = Query(None, pattern="^(Hot|Warm|Cold)$"),
    outcome: str | None = Query(None, pattern="^(won|lost)$"),
    misses_only: bool = Query(False, description="Only Hot-but-lost and Cold-but-won rows"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Per-row drill-down: prediction next to the real outcome."""
    run = _org_run_or_404(db, run_id, current_user)

    q = db.query(BacktestRecord).filter(BacktestRecord.run_id == run.id)
    if verdict:
        q = q.filter(BacktestRecord.predicted_verdict == verdict)
    if outcome:
        q = q.filter(BacktestRecord.actual_outcome == outcome)
    if misses_only:
        from sqlalchemy import and_, or_
        q = q.filter(or_(
            and_(BacktestRecord.predicted_verdict == "Hot", BacktestRecord.actual_outcome == "lost"),
            and_(BacktestRecord.predicted_verdict == "Cold", BacktestRecord.actual_outcome == "won"),
        ))

    total = q.count()
    records = q.order_by(BacktestRecord.row_number.asc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "records": [
            {
                "row_number": r.row_number,
                "name": r.name,
                "email": r.email,
                "company": r.company,
                "actual_outcome": r.actual_outcome,
                "predicted_verdict": r.predicted_verdict,
                "predicted_score": r.predicted_score,
                "icp_match": r.icp_match,
                "features": r.features,
                "reasoning": r.reasoning,
            }
            for r in records
        ],
    }
