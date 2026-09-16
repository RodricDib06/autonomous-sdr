"""
Reporting: funnel, exports, ML, velocity, rep performance.

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

from app.services.trigger_monitor import TRIGGER_SIGNAL_TYPES  # noqa: F401

from app.database.connection import get_db  # noqa: F401
from app.database import crud  # noqa: F401
from app.database.models import Lead, Enrichment, Verdict, User  # noqa: F401
from app.auth.dependencies import require_admin, require_manager, require_rep  # noqa: F401
from app.config import settings  # noqa: F401
from app.utils.time import utcnow  # noqa: F401
from app.services.queue_service import push_lead_job, get_redis  # noqa: F401
from app.schemas.lead import AssignmentStats

log = structlog.get_logger(__name__)

router = APIRouter(tags=["analytics"])

_FUNNEL_STAGES = ["unqualified", "qualified", "contacted", "scheduled", "won", "lost"]
_ACTIVE_STAGES = ["unqualified", "qualified", "contacted", "scheduled", "won"]


@router.get("/dashboard/assignment-stats", response_model=list[AssignmentStats])
def get_assignment_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get assignment and conversion stats for all reps."""
    from app.database.models import User, Lead

    reps = db.query(User).filter(User.role == "rep", User.is_active).all()
    stats = []

    for rep in reps:
        assigned = db.query(Lead).filter(Lead.assigned_to_id == rep.id).count()
        contacted = db.query(Lead).filter(
            Lead.assigned_to_id == rep.id,
            Lead.conversion_status.in_(["contacted", "scheduled", "won"])
        ).count()
        won = db.query(Lead).filter(
            Lead.assigned_to_id == rep.id,
            Lead.conversion_status == "won"
        ).count()

        contacted_pct = (contacted / assigned * 100) if assigned > 0 else 0
        won_pct = (won / assigned * 100) if assigned > 0 else 0

        stats.append(
            AssignmentStats(
                rep_id=rep.id,
                rep_email=rep.email,
                assigned_count=assigned,
                contacted_count=contacted,
                contacted_pct=contacted_pct,
                won_count=won,
                won_pct=won_pct,
            )
        )

    return stats

@router.get("/analytics/signal-feed")
def get_signal_feed(
    limit: int = Query(50, ge=1, le=200),
    signal_type: str | None = Query(None, description="Filter by type: funding_trigger | job_posting_trigger | news_trigger | job_change_trigger"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Recent trigger signals across all leads — the global signal feed."""
    from app.database.models import IntentSignal, Lead as LeadModel
    query = (
        db.query(IntentSignal, LeadModel)
        .join(LeadModel, IntentSignal.lead_id == LeadModel.id)
        .filter(IntentSignal.signal_type.in_(list(TRIGGER_SIGNAL_TYPES)))
    )
    if signal_type:
        query = query.filter(IntentSignal.signal_type == signal_type)
    results = query.order_by(IntentSignal.captured_at.desc()).limit(limit).all()
    rows = [
        {
            "id": s.id,
            "lead_id": s.lead_id,
            "lead_name": lead.name,
            "company": lead.company,
            "signal_type": s.signal_type,
            "score": s.score,
            "signal_metadata": getattr(s, "signal_metadata", None),
            "triggered_at": s.captured_at.isoformat(),
        }
        for s, lead in results
    ]
    return {"signals": rows, "count": len(rows)}

@router.get("/analytics/funnel")
def get_revenue_funnel(
    acv: float = Query(25000.0, ge=0, description="Average contract value in dollars"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Return lead counts and estimated value by conversion stage.
    Uses close_probability where available; falls back to stage-based multipliers.
    """

    stage_multipliers = {
        "unqualified": 0.05,
        "qualified": 0.20,
        "contacted": 0.35,
        "scheduled": 0.65,
        "won": 1.0,
        "lost": 0.0,
    }

    stage_counts: dict[str, int] = {}
    for stage in _FUNNEL_STAGES:
        count = db.query(Lead).filter(Lead.conversion_status == stage).count()
        stage_counts[stage] = count

    # Fetch BANT-weighted close probabilities for each stage for better value estimates
    stages_out = []
    for stage in _ACTIVE_STAGES:
        count = stage_counts.get(stage, 0)
        multiplier = stage_multipliers[stage]
        estimated_value = int(count * acv * multiplier)
        stages_out.append({
            "name": stage,
            "label": stage.replace("_", " ").title(),
            "count": count,
            "estimated_value": estimated_value,
            "multiplier": multiplier,
        })

    total_active = sum(s["count"] for s in stages_out if s["name"] != "won")
    won = stage_counts.get("won", 0)
    lost = stage_counts.get("lost", 0)
    closed = won + lost
    win_rate = round(won / closed, 3) if closed > 0 else None

    # Conversion rates between adjacent active stages
    for i, stage in enumerate(stages_out):
        if i == 0:
            stage["conversion_from_prev"] = None
        else:
            prev_count = stages_out[i - 1]["count"]
            stage["conversion_from_prev"] = (
                round(stage["count"] / prev_count, 3) if prev_count > 0 else None
            )

    return {
        "stages": stages_out,
        "lost": lost,
        "win_rate": win_rate,
        "total_active": total_active,
        "acv": acv,
    }

@router.get("/analytics/powerbi-export")
def powerbi_export(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(5000, ge=1, le=50000),
):
    """
    Flat JSON export optimised for Power BI Desktop's 'Get Data > Web' connector.

    How to connect in Power BI Desktop:
      1. Get Data → Web
      2. URL: http://localhost:8000/analytics/powerbi-export
      3. Add header: Authorization: Bearer {your_jwt_token}
      4. Power BI will parse the JSON array into a table automatically.
      5. Use 'Transform Data' to set column types, then build visuals.

    Recommended Power BI measures to create:
      - Hot Rate       = DIVIDE(COUNTIF([verdict],"Hot"), COUNT([id]))
      - Avg Confidence = AVERAGE([confidence_score])
      - Intent P75     = PERCENTILE([intent_score], 0.75)
      - Conversion Rate= DIVIDE(COUNTIF([conversion_status],"converted"), COUNT([id]))
    """
    from sqlalchemy.orm import selectinload

    leads = (
        db.query(Lead)
        .options(
            selectinload(Lead.enrichments),
            selectinload(Lead.verdicts),
            selectinload(Lead.outreach_emails),
            selectinload(Lead.intent_signals),
            selectinload(Lead.booking_requests),
        )
        .order_by(Lead.created_at.desc())
        .limit(limit)
        .all()
    )

    rows = []
    for lead in leads:
        enrichment = lead.enrichments[0] if lead.enrichments else None
        verdict = lead.verdicts[0] if lead.verdicts else None
        intent_score = round(min(1.0, sum(s.score for s in lead.intent_signals)), 4)

        emails = lead.outreach_emails or []
        emails_sent    = sum(1 for e in emails if e.status in ("sent", "opened", "replied"))
        emails_opened  = sum(1 for e in emails if e.opened_at)
        emails_replied = sum(1 for e in emails if e.replied_at)

        bookings = lead.booking_requests or []
        meeting_booked = any(b.status in ("confirmed", "link_sent") for b in bookings)

        bant = verdict.bant_scores or {} if verdict else {}

        rows.append({
            # Lead
            "id":                  lead.id,
            "name":                lead.name,
            "email":               lead.email,
            "company":             lead.company,
            "source":              lead.source,
            "status":              lead.status,
            "conversion_status":   lead.conversion_status,
            "created_at":          lead.created_at.isoformat() if lead.created_at else None,
            "archived":            lead.archived,

            # Enrichment
            "job_title":           enrichment.job_title if enrichment else None,
            "seniority":           enrichment.seniority if enrichment else None,
            "company_size":        enrichment.company_size if enrichment else None,
            "industry":            enrichment.industry if enrichment else None,
            "revenue_estimate":    enrichment.revenue_estimate if enrichment else None,
            "enrichment_source":   enrichment.enrichment_source if enrichment else None,

            # Qualification
            "verdict":             verdict.final_verdict if verdict else None,
            "confidence_score":    verdict.confidence_score if verdict else None,
            "bant_budget":         bant.get("budget") if bant else None,
            "bant_authority":      bant.get("authority") if bant else None,
            "bant_need":           bant.get("need") if bant else None,
            "bant_timeline":       bant.get("timeline") if bant else None,
            "icp_match":           verdict.icp_match if verdict else None,

            # Intent
            "intent_score":        intent_score,

            # Outreach
            "emails_sent":         emails_sent,
            "emails_opened":       emails_opened,
            "emails_replied":      emails_replied,
            "open_rate":           round(emails_opened / emails_sent, 4) if emails_sent else 0,
            "reply_rate":          round(emails_replied / emails_sent, 4) if emails_sent else 0,

            # Booking
            "meeting_booked":      meeting_booked,

            # Quality
            "data_quality_score":  lead.data_quality_score,
            "completeness_score":  lead.completeness_score,
        })

    return rows

@router.get("/analytics/powerbi-export.csv")
def powerbi_export_csv(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(5000, ge=1, le=50000),
):
    """Same data as /analytics/powerbi-export but as CSV download for Excel / manual import."""
    rows = powerbi_export(current_user=current_user, db=db, limit=limit)
    from app.services.export_service import to_csv_bytes
    csv_bytes = to_csv_bytes(rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sdr_pipeline_export.csv"},
    )

@router.get("/analytics/semantic-search")
def semantic_search(
    query: str = Query(..., description="Natural language search across conversation history"),
    lead_id: str = Query(None, description="Scope search to a specific lead"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Search conversation history by meaning using pgvector.
    Falls back to keyword search if pgvector is not enabled.

    Example queries:
      - 'leads who mentioned pricing concerns'
      - 'prospects interested in enterprise features'
      - 'companies evaluating competitors'
    """
    from app.services.embedding_service import semantic_search_conversations
    results = semantic_search_conversations(db, query, lead_id=lead_id, limit=limit)
    return {"query": query, "results": results, "count": len(results)}

@router.post("/analytics/ml/retrain")
def retrain_ml_model(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Force-retrain the close probability model on current conversion data."""
    from app.services.ml_scorer import retrain, get_model

    success = retrain(db)
    if not success:
        return {
            "status": "insufficient_data",
            "message": "Need at least 3 converted and 3 lost leads. Run the seed script or mark some leads as converted/lost.",
        }

    model = get_model()
    return {
        "status": "trained",
        "n_samples": model.n_samples,
        "converted": model.n_converted,
        "lost": model.n_lost,
        "trained_at": model.trained_at.isoformat() if model.trained_at else None,
    }

@router.get("/analytics/market-intelligence")
def get_market_intelligence(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Return segment-level hot rates and lift vs baseline.
    Shows which industry × seniority combinations convert best.
    """
    from app.services.market_intelligence import compute_market_intelligence
    return compute_market_intelligence(db)

@router.get("/analytics/pipeline-velocity")
def get_pipeline_velocity(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    How fast does the system work?

    Returns average durations (in hours) for each stage:
      - time_to_qualify:  lead created → pipeline complete
      - time_to_book:     pipeline complete → booking request created
      - time_to_close:    pipeline complete → conversion_status in (won, converted)

    Also returns p50 and p90 percentiles for time_to_qualify.
    """
    from app.database.models import BookingRequest as BookingModel

    complete_leads = (
        db.query(Lead)
        .filter(Lead.status == "complete", Lead.updated_at.isnot(None))
        .all()
    )

    qualify_hours: list[float] = []
    book_hours: list[float] = []
    close_hours: list[float] = []

    for lead in complete_leads:
        if not lead.updated_at or not lead.created_at:
            continue

        ttq = (lead.updated_at - lead.created_at).total_seconds() / 3600
        qualify_hours.append(ttq)

        # Time to first booking
        booking = (
            db.query(BookingModel)
            .filter(BookingModel.lead_id == lead.id)
            .order_by(BookingModel.created_at)
            .first()
        )
        if booking:
            ttb = (booking.created_at - lead.updated_at).total_seconds() / 3600
            book_hours.append(max(0, ttb))

        # Time to close
        if lead.conversion_status in ("won", "converted") and lead.conversion_updated_at:
            ttc = (lead.conversion_updated_at - lead.updated_at).total_seconds() / 3600
            close_hours.append(max(0, ttc))

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {"avg": None, "p50": None, "p90": None, "count": 0}
        vals_sorted = sorted(vals)
        n = len(vals_sorted)
        avg = sum(vals_sorted) / n
        p50 = vals_sorted[n // 2]
        p90 = vals_sorted[int(n * 0.9)]
        return {
            "avg": round(avg, 2),
            "p50": round(p50, 2),
            "p90": round(p90, 2),
            "count": n,
        }

    return {
        "time_to_qualify_hours": _stats(qualify_hours),
        "time_to_book_hours": _stats(book_hours),
        "time_to_close_hours": _stats(close_hours),
        "total_complete": len(complete_leads),
        "booking_rate": round(len(book_hours) / max(1, len(qualify_hours)), 4),
        "close_rate": round(len(close_hours) / max(1, len(qualify_hours)), 4),
    }

@router.get("/analytics/rep-performance")
def get_rep_performance(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Per-rep performance leaderboard.

    Returns each rep's: leads assigned, hot qualified, emails sent, meetings booked,
    conversion count, and pipeline value (hot leads × ACV proxy).
    """
    from app.database.models import User as UserModel, BookingRequest as BookingModel, OutreachEmail as OutreachEmailModel, Verdict as VerdictModel

    reps = db.query(UserModel).filter(UserModel.is_active == True).all()  # noqa: E712
    rows = []

    for rep in reps:
        assigned = db.query(Lead).filter(Lead.assigned_to_id == rep.id).all()
        lead_ids = [ld.id for ld in assigned]

        hot_count = 0
        conversions = 0
        for lead in assigned:
            if lead.conversion_status in ("won", "converted"):
                conversions += 1
            verdict = (
                db.query(VerdictModel)
                .filter(VerdictModel.lead_id == lead.id)
                .first()
            )
            if verdict and verdict.final_verdict == "Hot":
                hot_count += 1

        emails_sent = 0
        if lead_ids:
            emails_sent = (
                db.query(OutreachEmailModel)
                .filter(
                    OutreachEmailModel.lead_id.in_(lead_ids),
                    OutreachEmailModel.status.in_(("sent", "opened", "replied")),
                )
                .count()
            )

        bookings = 0
        if lead_ids:
            bookings = (
                db.query(BookingModel)
                .filter(BookingModel.lead_id.in_(lead_ids))
                .count()
            )

        rows.append({
            "rep_id": rep.id,
            "rep_email": rep.email,
            "role": rep.role,
            "leads_assigned": len(assigned),
            "hot_qualified": hot_count,
            "emails_sent": emails_sent,
            "meetings_booked": bookings,
            "conversions": conversions,
            "conversion_rate": round(conversions / max(1, len(assigned)), 4),
            "hot_rate": round(hot_count / max(1, len(assigned)), 4),
        })

    # Sort by conversions desc, then hot_qualified desc
    rows.sort(key=lambda r: (-r["conversions"], -r["hot_qualified"]))

    return {
        "reps": rows,
        "total_reps": len(rows),
    }
