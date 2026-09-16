"""
Lead CRUD, import/export, enrichment views, outreach and booking actions.

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
from fastapi import UploadFile, File
from app.schemas.lead import (
    LeadCreate, LeadResponse, LeadDetail, BatchRequest, ImportHistoryResponse,
    AssignRequest, ConversionRequest, LeadHistoryEntry,
)
from app.services.deduplication import DeduplicationService
from app.services.csv_import import CSVImportService
from app.services.data_quality import DataQualityService
from app.services.batch_service import execute_batch
from app.services.export_service import (
    build_export_rows, to_csv_bytes, to_hubspot_rows, to_salesforce_rows,
)
from app.services.slack_notifier import slack_notifier
from app.services.trigger_monitor import TRIGGER_SIGNAL_TYPES

log = structlog.get_logger(__name__)

router = APIRouter(tags=["leads"])


@router.get("/leads/{lead_id}/pipeline/stream", include_in_schema=False)
async def stream_pipeline_events(
    lead_id: str,
    timeout: int = Query(120, ge=10, le=300, description="Max seconds to wait for completion"),
    token: str = Query(None, description="JWT token (EventSource can't set Authorization header)"),
    db: Session = Depends(get_db),
):
    """
    Server-Sent Events stream for live pipeline execution updates.

    Subscribes to the Redis pub/sub channel "pipeline:{lead_id}" and forwards
    each node event to the browser as an SSE data frame.

    Event shape (JSON):
      {"node": "enrich", "status": "running"|"complete"|"error", "duration_ms": 142, ...}
    Terminal event:
      {"node": "pipeline", "status": "complete", "verdict": "Hot"}

    Frontend usage:
      const es = new EventSource(`/leads/${id}/pipeline/stream`);
      es.onmessage = e => console.log(JSON.parse(e.data));
      es.addEventListener('complete', () => es.close());
    """
    # Authenticate via query-param token (EventSource doesn't support headers)
    if token:
        from app.auth.dependencies import _user_from_jwt
        user = _user_from_jwt(token, db)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid token")
    # (In dev/test, allow unauthenticated SSE when no token is provided)

    async def event_generator():
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"pipeline:{lead_id}")

        # Send an initial "connected" heartbeat so the client knows the stream is live
        yield f"data: {json.dumps({'node': 'stream', 'status': 'connected', 'lead_id': lead_id})}\n\n"

        deadline = asyncio.get_event_loop().time() + timeout
        try:
            async for message in pubsub.listen():
                if asyncio.get_event_loop().time() > deadline:
                    yield f"data: {json.dumps({'node': 'stream', 'status': 'timeout'})}\n\n"
                    break

                if message["type"] != "message":
                    continue

                data = message["data"]
                yield f"data: {data}\n\n"

                try:
                    event = json.loads(data)
                    if event.get("node") == "pipeline" and event.get("status") == "complete":
                        break
                except Exception:
                    pass
        finally:
            await pubsub.unsubscribe(f"pipeline:{lead_id}")
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx proxy buffering
        },
    )

@router.post("/leads", response_model=LeadResponse)
def receive_lead(
    payload: LeadCreate,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Submit a new lead for qualification"""
    try:
        lead = crud.create_lead(
            db,
            name=payload.name,
            email=payload.email,
            company=payload.company,
            source=payload.source,
            org_id=current_user.org_id,
        )
        push_lead_job(lead.id)
        log.info("lead.created", lead_id=lead.id[:8], email=lead.email)
        return lead
    except Exception as e:
        log.error("Failed to create lead", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create lead")

@router.get("/leads", response_model=list[LeadResponse])
def list_leads(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    verdict: str = Query(None, description="Filter by verdict: Hot, Warm, Cold"),
    bant_authority: str = Query(None, description="Filter by BANT authority: High, Medium, Low"),
    bant_budget: str = Query(None, description="Filter by BANT budget: High, Medium, Low"),
    bant_need: str = Query(None, description="Filter by BANT need: High, Medium, Low"),
    bant_timeline: str = Query(None, description="Filter by BANT timeline: High, Medium, Low"),
):
    """List all leads with pagination and optional BANT/verdict filters"""
    from sqlalchemy.orm import selectinload
    try:
        query = db.query(Lead).options(selectinload(Lead.verdicts))
        if current_user.org_id is not None:
            query = query.filter(Lead.org_id == current_user.org_id)

        bant_filters = {k: v for k, v in {
            "authority": bant_authority,
            "budget": bant_budget,
            "need": bant_need,
            "timeline": bant_timeline,
        }.items() if v}

        if verdict or bant_filters:
            query = query.join(Verdict, Verdict.lead_id == Lead.id)
            if verdict:
                query = query.filter(Verdict.final_verdict == verdict)
            for dim, val in bant_filters.items():
                query = query.filter(Verdict.bant_scores[dim].astext == val)

        leads = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
        return leads
    except Exception as e:
        log.error("Failed to list leads", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch leads")

@router.get("/leads/stats")
def get_lead_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get statistics about processed leads"""
    try:
        total_leads = db.query(Lead).count()
        completed_leads = db.query(Lead).filter(Lead.status == "complete").count()
        failed_leads = db.query(Lead).filter(Lead.status == "failed").count()
        processing_leads = db.query(Lead).filter(Lead.status == "processing").count()

        # Verdict breakdown
        hot_leads = db.query(Verdict).filter(Verdict.final_verdict == "Hot").count()
        warm_leads = db.query(Verdict).filter(Verdict.final_verdict == "Warm").count()
        cold_leads = db.query(Verdict).filter(Verdict.final_verdict == "Cold").count()

        return {
            "total_leads": total_leads,
            "completed": completed_leads,
            "failed": failed_leads,
            "processing": processing_leads,
            "success_rate": completed_leads / total_leads if total_leads > 0 else 0,
            "verdict_breakdown": {
                "hot": hot_leads,
                "warm": warm_leads,
                "cold": cold_leads
            }
        }
    except Exception as e:
        log.error("Failed to get stats", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get statistics")

@router.get("/leads/trend")
def get_lead_trend(
    days: int = Query(30, ge=7, le=90),
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return daily lead intake counts for the last N days."""
    from datetime import timedelta
    from sqlalchemy import func, case

    since = utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.date(Lead.created_at).label("day"),
            func.count(Lead.id).label("total"),
            func.sum(case((Verdict.final_verdict == "Hot", 1), else_=0)).label("hot"),
            func.sum(case((Verdict.final_verdict == "Warm", 1), else_=0)).label("warm"),
            func.sum(case((Verdict.final_verdict == "Cold", 1), else_=0)).label("cold"),
        )
        .outerjoin(Verdict, Lead.id == Verdict.lead_id)
        .filter(Lead.created_at >= since)
        .group_by(func.date(Lead.created_at))
        .order_by(func.date(Lead.created_at))
        .all()
    )
    return {
        "days": days,
        "data": [
            {
                "day": str(r.day),
                "total": r.total,
                "hot": int(r.hot or 0),
                "warm": int(r.warm or 0),
                "cold": int(r.cold or 0),
            }
            for r in rows
        ],
    }

@router.get("/leads/quality-report")
def get_quality_report(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get system-wide data quality summary"""
    try:
        report = DataQualityService().get_quality_report(db)
        return report
    except Exception as e:
        log.error("Failed to get quality report", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get quality report")

@router.post("/leads/quality-backfill")
def backfill_quality_scores(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Score all leads that have never been quality-scored."""
    try:
        unscored = db.query(Lead).filter(Lead.data_quality_score.is_(None)).all()
        service = DataQualityService()
        for lead in unscored:
            service.update_lead_quality(db, lead)
        log.info("quality.backfill.complete", scored=len(unscored))
        return {"scored": len(unscored)}
    except Exception as e:
        log.error("Quality backfill failed", error=str(e))
        raise HTTPException(status_code=500, detail="Quality backfill failed")

@router.get("/leads/hot")
def get_hot_leads(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """Get high-priority (Hot) leads ready for sales follow-up"""
    try:
        hot_leads = db.query(Lead).join(Verdict).filter(
            Lead.status == "complete",
            Verdict.final_verdict == "Hot"
        ).order_by(Verdict.confidence_score.desc()).limit(limit).all()

        results = []
        for lead in hot_leads:
            verdict = lead.verdicts[0] if lead.verdicts else None
            enrichment = lead.enrichments[0] if lead.enrichments else None

            results.append({
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "company": lead.company,
                "confidence": verdict.confidence_score if verdict else 0,
                "job_title": enrichment.job_title if enrichment else None,
                "seniority": enrichment.seniority if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "reasoning": verdict.analysis_reasoning if verdict else None
            })

        return {"hot_leads": results, "count": len(results)}
    except Exception as e:
        log.error("Failed to get hot leads", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get hot leads")

@router.get("/leads/export")
def export_leads(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    verdict_filter: str = Query(None, description="Filter by verdict: Hot, Warm, Cold"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confidence score"),
    industry_filter: str = Query(None, description="Filter by industry (partial match)"),
    format: str = Query("json", description="Output format: json, csv, hubspot, salesforce"),
):
    """Export leads data — supports JSON and CRM-formatted CSV (HubSpot, Salesforce)."""
    try:
        query = db.query(Lead).filter(Lead.status == "complete", not Lead.archived)

        if verdict_filter:
            query = query.join(Verdict).filter(Verdict.final_verdict == verdict_filter)
        elif min_confidence > 0:
            query = query.join(Verdict).filter(Verdict.confidence_score >= min_confidence)

        if industry_filter:
            query = query.join(Enrichment, Enrichment.lead_id == Lead.id, isouter=True).filter(
                Enrichment.industry.ilike(f"%{industry_filter}%")
            )

        leads = query.order_by(Lead.created_at.desc()).all()
        rows = build_export_rows(leads)

        if format == "json":
            return {
                "export": rows,
                "count": len(rows),
                "filters": {
                    "verdict": verdict_filter,
                    "min_confidence": min_confidence,
                    "industry": industry_filter,
                    "format": format,
                },
            }

        if format == "hubspot":
            csv_rows = to_hubspot_rows(rows)
            filename = "leads_hubspot.csv"
        elif format == "salesforce":
            csv_rows = to_salesforce_rows(rows)
            filename = "leads_salesforce.csv"
        elif format == "csv":
            csv_rows = rows
            filename = "leads.csv"
        else:
            raise HTTPException(status_code=400, detail=f"Unknown format '{format}'. Use: json, csv, hubspot, salesforce")

        csv_bytes = to_csv_bytes(csv_rows)
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to export leads", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to export leads")

@router.post("/leads/import-csv")
def import_csv_leads(
    file: UploadFile = File(...),
    current_user: User = Depends(require_manager),
    check_duplicates: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Import leads from CSV file"""
    try:
        # Read CSV content
        content = file.file.read().decode('utf-8')
        file.file.close()

        # Import using CSVImportService
        import_service = CSVImportService(db)
        result = import_service.import_leads(
            content, check_duplicates=check_duplicates, org_id=current_user.org_id
        )

        # Persist import audit record
        import_service.persist_history(db, file.filename or "unknown.csv", result)

        # Send Slack notification if configured
        if slack_notifier.enabled:
            slack_notifier.notify_import_complete(result.to_dict())

        log.info("csv.import.complete", successful=result.successful, failed=result.failed)

        return result.to_dict()

    except Exception as e:
        log.error("Failed to import CSV", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to import CSV: {str(e)}")

@router.get("/leads/duplicates/report")
def get_duplicate_report(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get report of potential duplicate leads in system"""
    try:
        dedup_service = DeduplicationService(db)
        report = dedup_service.get_duplicate_report()

        return {
            "report": report,
            "generated_at": utcnow().isoformat()
        }
    except Exception as e:
        log.error("Failed to generate duplicate report", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate duplicate report")

@router.get("/leads/import-history")
def get_import_history(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    """List past CSV import operations, newest first."""
    try:
        from app.database.models import ImportHistory
        records = (
            db.query(ImportHistory)
            .order_by(ImportHistory.started_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "imports": [ImportHistoryResponse.model_validate(r).model_dump() for r in records],
            "count": len(records),
        }
    except Exception as e:
        log.error("Failed to get import history", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get import history")

@router.post("/leads/reprocess-failed")
def reprocess_failed(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Re-queue all failed leads back into the processing pipeline."""
    from app.services.queue_service import push_lead_job
    failed = db.query(Lead).filter(Lead.status == "failed").all()
    if not failed:
        return {"requeued": 0, "message": "No failed leads found"}
    now = utcnow()
    for lead in failed:
        lead.status = "processing"
        lead.updated_at = now
        push_lead_job(lead.id)
    db.commit()
    log.info("leads.reprocess", count=len(failed), triggered_by=current_user.email)
    return {"requeued": len(failed), "message": f"{len(failed)} leads re-queued for processing"}

@router.post("/leads/batch")
def batch_leads(
    request: BatchRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Perform a bulk action on multiple leads at once."""
    try:
        result = execute_batch(db, request.action, request.lead_ids, request.payload)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("Batch action '{request.action}' failed", error=str(e))
        raise HTTPException(status_code=500, detail="Batch action failed")

@router.post("/leads/{lead_id}/assign")
def assign_lead_endpoint(
    lead_id: str,
    request: AssignRequest,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Assign a lead to a sales rep."""
    try:
        from app.services.assignment_service import assign_lead
        lead = assign_lead(db, lead_id, request.rep_id, changed_by_id=current_user.id)
        log.info("lead.assigned", lead_id=lead_id[:8], rep_id=request.rep_id, by=current_user.email)
        return {"success": True, "lead_id": lead_id, "assigned_to_id": lead.assigned_to_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Failed to assign lead", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to assign lead")

@router.delete("/leads/{lead_id}/assign")
def unassign_lead_endpoint(
    lead_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Unassign a lead from its sales rep."""
    try:
        from app.services.assignment_service import unassign_lead
        unassign_lead(db, lead_id, changed_by_id=current_user.id)
        log.info("lead.unassigned", lead_id=lead_id[:8], by=current_user.email)
        return {"success": True, "lead_id": lead_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Failed to unassign lead", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to unassign lead")

@router.post("/leads/{lead_id}/conversion")
def update_conversion_status_endpoint(
    lead_id: str,
    request: ConversionRequest,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Update lead conversion status."""
    try:
        from app.services.assignment_service import update_conversion_status
        lead = update_conversion_status(
            db,
            lead_id,
            request.status,
            notes=request.notes,
            changed_by_id=current_user.id,
        )
        log.info("lead.conversion.updated", lead_id=lead_id[:8], status=request.status, by=current_user.email)
        return {"success": True, "lead_id": lead_id, "conversion_status": lead.conversion_status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("Failed to update conversion status", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update conversion status")

@router.get("/leads/{lead_id}/history", response_model=list[LeadHistoryEntry])
def get_lead_history_endpoint(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get history timeline for a lead."""
    from app.services.assignment_service import get_lead_history
    return get_lead_history(db, lead_id)

@router.get("/leads/cooling")
def get_cooling_leads(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Return warm leads that haven't engaged recently, sorted by days overdue.
    Only 'watch' (7–13 days) and 'urgent' (14+ days) leads are returned.
    """
    from app.services.decay_service import get_cooling_leads as _get_cooling
    results = _get_cooling(db, limit=limit)
    return {"leads": results, "count": len(results)}

@router.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get detailed information about a specific lead"""
    try:
        lead = crud.get_lead(db, lead_id, org_id=current_user.org_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        enrichment = lead.enrichments[0] if lead.enrichments else None
        verdict = lead.verdicts[0] if lead.verdicts else None

        detail = LeadDetail.model_validate(lead)
        detail.email_verification_status = lead.email_verification_status
        detail.email_verified_at = lead.email_verified_at
        detail.email_verification_reason = (lead.email_verification_detail or {}).get("reason")
        if enrichment:
            detail.enrichment = {
                "job_title": enrichment.job_title,
                "seniority": enrichment.seniority,
                "company_size": enrichment.company_size,
                "industry": enrichment.industry,
                "revenue_estimate": enrichment.revenue_estimate,
                "tech_stack": enrichment.tech_stack,
                "confidence": enrichment.confidence,
                "enrichment_source": enrichment.enrichment_source,
            }
        if verdict:
            detail.verdict = {
                "analysis_verdict": verdict.analysis_verdict,
                "final_verdict": verdict.final_verdict,
                "confidence_score": verdict.confidence_score,
                "reasoning": verdict.analysis_reasoning,
                "bant_scores": verdict.bant_scores,
                "icp_match": verdict.icp_match,
                "validated": verdict.validated,
                "consistency_notes": verdict.consistency_notes,
                "flags": verdict.flags,
            }
        return detail
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to fetch lead {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch lead")

@router.get("/leads/{lead_id}/verdict-explanation")
def get_verdict_explanation(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    LLM-generated plain-English explanation of the verdict for a lead.

    Returns:
      - summary: 2-3 sentence human-readable explanation of why the lead got this verdict
      - counterfactual: what would need to change to get a better verdict
      - key_drivers: top 3 BANT factors that drove the decision
      - verdict / confidence_score: echoed from Verdict record
    """
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    verdict = lead.verdicts[0] if lead.verdicts else None
    if not verdict:
        raise HTTPException(status_code=404, detail="No verdict available for this lead yet")

    enrichment = lead.enrichments[0] if lead.enrichments else None
    bant = verdict.bant_scores or {}

    # Build a compact context string for the LLM
    bant_lines = "\n".join(
        f"  {k.upper()}: {v:.2f}" for k, v in bant.items() if isinstance(v, (int, float))
    ) or "  (no BANT scores)"

    prompt = f"""You are an AI sales analyst. Given this lead qualification data, explain the verdict in plain English for a sales rep.

Lead: {lead.name} | {lead.company}
Title: {enrichment.job_title if enrichment else 'Unknown'} ({enrichment.seniority if enrichment else '?'})
Industry: {enrichment.industry if enrichment else 'Unknown'}
Company size: {enrichment.company_size if enrichment else 'Unknown'}

BANT Scores (0-1):
{bant_lines}

Verdict: {verdict.final_verdict} (confidence: {verdict.confidence_score or 0:.0%})
System reasoning: {verdict.analysis_reasoning or 'None'}
ICP match: {verdict.icp_match}
Flags: {', '.join(verdict.flags or []) or 'none'}

Write a JSON object with exactly these keys:
- "summary": 2-3 sentences explaining WHY this lead received this verdict, in language a sales rep can understand. Be specific about which factors mattered most.
- "counterfactual": 1-2 sentences on what would need to be true for this lead to receive a better (Hot) verdict.
- "key_drivers": array of exactly 3 strings, each naming a factor and its impact (e.g. "Budget score 0.85 — strong indicator of purchase readiness").

Respond ONLY with the JSON object, no markdown."""

    try:
        from app.services.providers import get_ai_client
        ai = get_ai_client()
        raw = ai.generate(prompt, max_tokens=500)
        parsed = None
        if raw:
            import json as _json
            # Strip markdown fences if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
                if clean.endswith("```"):
                    clean = clean[: clean.rfind("```")]
            try:
                parsed = _json.loads(clean.strip())
            except Exception:
                pass
        if not parsed:
            parsed = {
                "summary": verdict.analysis_reasoning or f"This lead was classified as {verdict.final_verdict}.",
                "counterfactual": "Improve BANT scores, particularly budget and authority, to reach Hot status.",
                "key_drivers": [
                    f"Budget: {bant.get('budget', 0):.0%}",
                    f"Authority: {bant.get('authority', 0):.0%}",
                    f"Timing: {bant.get('timing', 0):.0%}",
                ],
            }
    except Exception as e:
        log.warning("verdict_explanation.llm_failed", lead_id=lead_id[:8], error=str(e))
        parsed = {
            "summary": verdict.analysis_reasoning or f"This lead was classified as {verdict.final_verdict}.",
            "counterfactual": "Improve BANT scores to reach Hot status.",
            "key_drivers": [
                f"Budget: {bant.get('budget', 0):.2f}",
                f"Authority: {bant.get('authority', 0):.2f}",
                f"Timing: {bant.get('timing', 0):.2f}",
            ],
        }

    return {
        "lead_id": lead_id,
        "verdict": verdict.final_verdict,
        "confidence_score": verdict.confidence_score,
        "summary": parsed.get("summary", ""),
        "counterfactual": parsed.get("counterfactual", ""),
        "key_drivers": parsed.get("key_drivers", []),
    }

@router.get("/leads/{lead_id}/quality-score")
def get_lead_quality_score(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get data quality scores for a specific lead, recomputing live."""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        scores = DataQualityService().update_lead_quality(db, lead)
        return {
            "lead_id": lead_id,
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            **scores,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to get quality score for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get quality score")

@router.post("/leads/{lead_id}/check-duplicate")
def check_lead_duplicate(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Check if a lead has duplicates"""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        dedup_service = DeduplicationService(db)
        potential_dupes = dedup_service.find_potential_duplicates(
            lead.name, lead.email, lead.company
        )

        # Filter out the lead itself
        potential_dupes = [
            d for d in potential_dupes if d['lead'].id != lead_id
        ]

        return {
            "lead_id": lead_id,
            "has_duplicates": len(potential_dupes) > 0,
            "potential_duplicates": [
                {
                    "id": d['lead'].id,
                    "name": d['lead'].name,
                    "email": d['lead'].email,
                    "company": d['lead'].company,
                    "match_score": d['score'],
                    "match_type": d['match_type'],
                    "reason": d['reason']
                }
                for d in potential_dupes
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to check duplicates for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to check duplicates")

@router.post("/leads/{primary_id}/merge/{duplicate_id}")
def merge_duplicate_leads(
    primary_id: str,
    duplicate_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Merge a duplicate lead into the primary lead"""
    try:
        primary = crud.get_lead(db, primary_id)
        duplicate = crud.get_lead(db, duplicate_id)

        if not primary or not duplicate:
            raise HTTPException(status_code=404, detail="One or both leads not found")

        dedup_service = DeduplicationService(db)
        success = dedup_service.merge_leads(primary_id, duplicate_id)

        if success:
            log.info("lead.merged", primary=primary_id[:8], duplicate=duplicate_id[:8])
            return {
                "status": "success",
                "message": f"Lead {duplicate_id} merged into {primary_id}",
                "primary_lead_id": primary_id
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to merge leads")

    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to merge leads {primary_id} and {duplicate_id}", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to merge leads")

@router.post("/leads/{lead_id}/outreach")
def trigger_outreach(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Manually trigger outreach sequence for a qualified lead."""
    from app.agents.outreach_agent import OutreachAgent
    agent = OutreachAgent()
    try:
        result = agent._timed_run(db, lead_id, {"triggered_by": current_user.email})
        return result
    except Exception as e:
        log.error("Outreach failed for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/leads/{lead_id}/outreach")
def get_outreach_emails(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """List all outreach emails scheduled or sent for a lead."""
    from app.database.models import OutreachEmail
    emails = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.lead_id == lead_id)
        .order_by(OutreachEmail.step_number)
        .all()
    )
    rows = [
        {
            "id": e.id,
            "lead_id": e.lead_id,
            "sequence_id": e.sequence_id,
            "step_number": e.step_number,
            "subject": e.subject,
            "body": e.body,
            "status": e.status,
            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "opened_at": e.opened_at.isoformat() if e.opened_at else None,
            "replied_at": e.replied_at.isoformat() if e.replied_at else None,
            "error_message": e.error_message,
            "quality_score": e.quality_score,
            "quality_flags": e.quality_flags,
            "quality_reasoning": e.quality_reasoning,
        }
        for e in emails
    ]
    return {"emails": rows, "count": len(rows)}

@router.post("/leads/{lead_id}/book")
def trigger_booking(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Send a booking link to a qualified lead."""
    from app.agents.booking_agent import BookingAgent
    agent = BookingAgent()
    try:
        result = agent._timed_run(db, lead_id, {})
        return result
    except Exception as e:
        log.error("Booking failed for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/leads/{lead_id}/bookings")
def get_bookings(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """List all booking requests for a lead."""
    from app.database.models import BookingRequest
    bookings = (
        db.query(BookingRequest)
        .filter(BookingRequest.lead_id == lead_id)
        .order_by(BookingRequest.created_at.desc())
        .all()
    )
    rows = [
        {
            "id": b.id,
            "lead_id": b.lead_id,
            "status": b.status,
            "booking_link": b.booking_link,
            "scheduling_url": b.booking_link,
            "external_booking_id": b.external_booking_id,
            "start_time": b.start_time.isoformat() if b.start_time else None,
            "meeting_time": b.start_time.isoformat() if b.start_time else None,
            "notes": getattr(b, "notes", None),
            "created_at": b.created_at.isoformat(),
            "pre_call_brief": b.pre_call_brief,
        }
        for b in bookings
    ]
    return {"bookings": rows, "count": len(rows)}

@router.get("/leads/{lead_id}/debate")
def get_lead_debate(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the adversarial BANT debate transcript and verdict for a lead."""
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    from app.database.models import Verdict
    verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
    if not verdict:
        return {
            "lead_id": lead_id,
            "lead_name": lead.name,
            "final_verdict": None,
            "confidence_score": None,
            "bant_scores": None,
            "debate_transcript": None,
            "flags": None,
        }
    return {
        "lead_id": lead_id,
        "lead_name": lead.name,
        "final_verdict": verdict.final_verdict,
        "confidence_score": verdict.confidence_score,
        "bant_scores": verdict.bant_scores,
        "debate_transcript": verdict.debate_transcript,
        "flags": verdict.flags,
    }

@router.get("/leads/{lead_id}/pre-call-brief")
def get_pre_call_brief(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the most recent pre-call brief for a lead (generated on booking confirmation)."""
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    from app.database.models import BookingRequest
    import json
    booking = (
        db.query(BookingRequest)
        .filter(BookingRequest.lead_id == lead_id, BookingRequest.pre_call_brief.isnot(None))
        .order_by(BookingRequest.created_at.desc())
        .first()
    )
    brief_data = None
    booking_id = None
    booking_status = None
    start_time = None
    if booking:
        booking_id = booking.id
        booking_status = booking.status
        start_time = booking.start_time.isoformat() if booking.start_time else None
        if booking.pre_call_brief:
            try:
                brief_data = json.loads(booking.pre_call_brief)
            except (json.JSONDecodeError, TypeError):
                brief_data = {"raw": booking.pre_call_brief}
    return {
        "lead_id": lead_id,
        "lead_name": lead.name,
        "booking_id": booking_id,
        "booking_status": booking_status,
        "start_time": start_time,
        "brief": brief_data,
    }

@router.get("/leads/{lead_id}/trigger-signals")
def get_lead_trigger_signals(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return trigger-type buying signals for a specific lead."""
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    from app.database.models import IntentSignal
    signals = (
        db.query(IntentSignal)
        .filter(
            IntentSignal.lead_id == lead_id,
            IntentSignal.signal_type.in_(list(TRIGGER_SIGNAL_TYPES)),
        )
        .order_by(IntentSignal.captured_at.desc())
        .all()
    )
    rows = [
        {
            "id": s.id,
            "lead_id": lead_id,
            "lead_name": lead.name,
            "company": lead.company,
            "signal_type": s.signal_type,
            "score": s.score,
            "signal_metadata": getattr(s, "signal_metadata", None),
            "triggered_at": s.captured_at.isoformat(),
        }
        for s in signals
    ]
    return {"signals": rows, "count": len(rows)}

@router.patch("/leads/{lead_id}/bookings/{booking_id}")
def update_booking_status(
    lead_id: str,
    booking_id: str,
    status: str = Query(..., description="confirmed | cancelled | rescheduled | no_show"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Update booking status (e.g. after a Cal.com webhook fires)."""
    from app.database.models import BookingRequest
    booking = db.query(BookingRequest).filter(
        BookingRequest.id == booking_id,
        BookingRequest.lead_id == lead_id,
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    booking.status = status
    booking.updated_at = utcnow()
    db.commit()
    return {"status": "updated", "booking_id": booking_id, "new_status": status}

@router.post("/leads/{lead_id}/chat")
def send_chat_message(
    lead_id: str,
    channel: str = Query("email", description="email | sms | chat | linkedin"),
    mode: str = Query("reply", description="initiate | reply"),
    message: str = Query("", description="Inbound message from the lead"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Generate and send a contextual reply to a lead message."""
    from app.agents.conversational_agent import ConversationalAgent
    agent = ConversationalAgent()
    try:
        result = agent._timed_run(db, lead_id, {
            "channel": channel,
            "mode": mode,
            "message": message,
        })
        return result
    except Exception as e:
        log.error("Conversational agent failed for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/leads/{lead_id}/conversations")
def get_conversations(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return all conversation threads for a lead."""
    from app.services.memory_service import get_all_conversations
    convs = get_all_conversations(db, lead_id)
    rows = [
        {
            "id": c.id,
            "channel": c.channel,
            "message_count": len(c.messages or []),
            "summary": c.summary,
            "sentiment": c.sentiment,
            "classification": c.classification,
            "needs_human": c.needs_human,
            "human_flagged_at": c.human_flagged_at.isoformat() if c.human_flagged_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": (c.messages or [])[-20:],
        }
        for c in convs
    ]
    return {"conversations": rows, "count": len(rows)}

@router.post("/leads/{lead_id}/intent")
def compute_intent(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Run intent scoring for a lead and persist the signals."""
    from app.services.intent_scoring import compute_intent_score
    from app.database.models import Enrichment, Verdict
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
    verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()
    score = compute_intent_score(db, lead, enrichment, verdict)
    return {"lead_id": lead_id, "intent_score": score}

@router.get("/leads/{lead_id}/intent")
def get_intent_signals(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return all intent signals captured for a lead."""
    from app.database.models import IntentSignal
    signals = db.query(IntentSignal).filter(IntentSignal.lead_id == lead_id).all()
    return {
        "lead_id": lead_id,
        "score": round(min(1.0, sum(s.score for s in signals)), 4),
        "computed_at": signals[0].captured_at.isoformat() if signals else None,
        "signals": [
            {
                "rule": s.signal_type,
                "description": s.source or s.signal_type,
                "weight": s.score,
                "triggered": True,
            }
            for s in signals
        ],
    }

@router.post("/leads/{lead_id}/crm-sync")
def sync_to_crm(
    lead_id: str,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Push a lead to the configured CRM (or log mock if none configured)."""
    from app.services.crm_sync import sync_lead_to_crm
    try:
        result = sync_lead_to_crm(db, lead_id)
        return result
    except Exception as e:
        log.error("CRM sync failed for {lead_id}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/leads/{lead_id}/outreach/generate/stream", include_in_schema=False)
async def stream_outreach_generation(
    lead_id: str,
    step: int = Query(1, ge=1, le=3, description="Sequence step to preview (1–3)"),
    token: str = Query(None),
    db: Session = Depends(get_db),
):
    """
    Stream the LLM generation of an outreach email token-by-token.

    Emits SSE events:
      {"type": "token", "content": "Hi Sarah"}
      {"type": "complete", "subject": "...", "body": "..."}

    Frontend usage:
      const es = new EventSource(`/leads/${id}/outreach/generate/stream?token=${jwt}`);
      es.onmessage = e => {
        const ev = JSON.parse(e.data);
        if (ev.type === 'token') appendToPreview(ev.content);
        if (ev.type === 'complete') es.close();
      };
    """
    if token:
        from app.auth.dependencies import _user_from_jwt
        user = _user_from_jwt(token, db)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid token")

    async def generate():
        from app.database.models import Enrichment, OutreachSequence
        from app.agents.outreach_agent import _PERSONALISE_PROMPT, OutreachAgent

        lead = crud.get_lead(db, lead_id)
        if not lead:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Lead not found'})}\n\n"
            return

        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
        agent = OutreachAgent()
        profile = agent._build_profile(lead, enrichment)

        seq = db.query(OutreachSequence).filter(
            OutreachSequence.is_active == True  # noqa: E712
        ).first()
        if not seq or not seq.steps:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No active sequence'})}\n\n"
            return

        steps = {s["step"]: s for s in seq.steps}
        step_data = steps.get(step, seq.steps[0])

        prompt = _PERSONALISE_PROMPT.format(
            profile_json=json.dumps(profile, indent=2),
            subject_template=step_data.get("subject_template", ""),
            body_template=step_data.get("body_template", ""),
        )

        from app.services.providers import get_ai_client
        ai = get_ai_client()
        full_text = ""
        try:
            async for tok in ai.stream_generate(prompt):
                full_text += tok
                yield f"data: {json.dumps({'type': 'token', 'content': tok})}\n\n"
        except (AttributeError, NotImplementedError):
            full_text = ai.generate(prompt)
            yield f"data: {json.dumps({'type': 'token', 'content': full_text})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        try:
            match = re.search(r"\{.*\}", full_text, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}
            subject = parsed.get("subject", "")
            body = parsed.get("body", full_text)
        except Exception:
            subject, body = "", full_text

        yield f"data: {json.dumps({'type': 'complete', 'subject': subject, 'body': body})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.get("/leads/{lead_id}/close-probability")
def get_close_probability(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    ML-predicted probability this lead converts to a customer.
    Uses logistic regression trained on leads with known outcomes (converted / lost).
    Falls back to the BANT average when insufficient training data exists.
    """
    from sqlalchemy.orm import selectinload
    from app.services.ml_scorer import ensure_trained, get_model

    lead = (
        db.query(Lead)
        .options(selectinload(Lead.verdicts), selectinload(Lead.enrichments))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    verdict = lead.verdicts[0] if lead.verdicts else None
    enrichment = lead.enrichments[0] if lead.enrichments else None

    if not verdict or not verdict.bant_scores:
        raise HTTPException(status_code=422, detail="Lead has no BANT scores yet")

    bant = verdict.bant_scores
    bant_score = round(sum(float(v) for v in bant.values()) / len(bant), 3)

    ready = ensure_trained(db)

    if ready:
        model = get_model()
        result = model.predict(lead, verdict, enrichment)
        if result:
            prob = result["probability"]
            divergence = round(prob - bant_score, 3)

            if abs(divergence) >= 0.12:
                divergence_note = (
                    "ML scores lower than BANT — strong individual scores "
                    "but the profile pattern differs from past conversions."
                    if divergence < 0 else
                    "ML scores higher than BANT — profile closely matches "
                    "leads that previously converted."
                )
            else:
                divergence_note = None

            return {
                "lead_id": lead_id,
                "probability": prob,
                "bant_score": bant_score,
                "divergence": divergence,
                "divergence_note": divergence_note,
                "feature_importances": result["importances"],
                "model_info": {
                    "trained_on": result["n_samples"],
                    "converted": result["n_converted"],
                    "lost": result["n_lost"],
                    "trained_at": result["trained_at"],
                },
                "fallback": False,
            }

    return {
        "lead_id": lead_id,
        "probability": bant_score,
        "bant_score": bant_score,
        "divergence": 0,
        "divergence_note": None,
        "feature_importances": None,
        "model_info": None,
        "fallback": True,
        "fallback_reason": "Need at least 3 converted and 3 lost leads to train the ML model.",
    }

@router.get("/leads/{lead_id}/pipeline-trace")
def get_pipeline_trace(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Return the agent execution trace for a lead.
    Shows which LangGraph nodes ran, their duration, and any errors.
    """
    from app.database.models import AgentLog
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    logs = (
        db.query(AgentLog)
        .filter(AgentLog.lead_id == lead_id)
        .order_by(AgentLog.created_at)
        .all()
    )

    verdict = lead.verdicts[0] if lead.verdicts else None
    nodes_executed = list(dict.fromkeys(lg.agent_name for lg in logs if lg.success))

    return {
        "lead_id": lead_id,
        "lead_name": lead.name,
        "status": lead.status,
        "final_verdict": verdict.final_verdict if verdict else None,
        "nodes_executed": nodes_executed,
        "agent_logs": [
            {
                "id": lg.id,
                "agent_name": lg.agent_name,
                "status": "success" if lg.success else "failed",
                "duration_ms": lg.duration_ms,
                "error_message": lg.error_message,
                "created_at": lg.created_at.isoformat() if lg.created_at else None,
            }
            for lg in logs
        ],
    }

@router.get("/leads/{lead_id}/icp-evaluation")
def get_lead_icp_evaluation(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return detailed ICP criterion breakdown for a single lead."""
    from sqlalchemy.orm import selectinload
    from app.services.icp_service import get_icp_config, evaluate_icp

    lead = (
        db.query(Lead)
        .options(selectinload(Lead.enrichments))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    enrichment = lead.enrichments[0] if lead.enrichments else None
    config = get_icp_config(db, org_id=lead.org_id)
    evaluation = evaluate_icp(enrichment, config)

    return {
        "lead_id": lead_id,
        "icp_configured": config is not None,
        **evaluation,
    }

@router.get("/leads/{lead_id}/engagement-decay")
def get_lead_engagement_decay(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return engagement decay metrics for a single lead."""
    from sqlalchemy.orm import selectinload
    from app.services.decay_service import compute_decay

    lead = (
        db.query(Lead)
        .options(
            selectinload(Lead.outreach_emails),
            selectinload(Lead.booking_requests),
        )
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return compute_decay(lead, lead.outreach_emails, lead.booking_requests)

@router.post("/leads/{lead_id}/crm-push")
def crm_push(
    lead_id: str,
    format: str = Query("hubspot", pattern="^(hubspot|salesforce|pipedrive)$"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Format a single lead for a specific CRM and return the payload.
    In production swap the mock body for live API calls (see crm_sync.py).
    """
    from sqlalchemy.orm import selectinload
    lead = (
        db.query(Lead)
        .options(
            selectinload(Lead.verdicts),
            selectinload(Lead.enrichments),
        )
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    verdict = lead.verdicts[0] if lead.verdicts else None
    enrichment = lead.enrichments[0] if lead.enrichments else None
    name_parts = lead.name.split(" ", 1)
    first, last = name_parts[0], name_parts[1] if len(name_parts) > 1 else ""

    if format == "hubspot":
        payload = {
            "properties": {
                "email": lead.email,
                "firstname": first,
                "lastname": last,
                "company": lead.company,
                "jobtitle": enrichment.job_title if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "hs_lead_status": verdict.final_verdict if verdict else "New",
                "description": verdict.analysis_reasoning if verdict else None,
                "leadsource": lead.source,
            }
        }
    elif format == "salesforce":
        payload = {
            "FirstName": first,
            "LastName": last,
            "Email": lead.email,
            "Company": lead.company,
            "Title": enrichment.job_title if enrichment else None,
            "Industry": enrichment.industry if enrichment else None,
            "LeadSource": lead.source,
            "Status": verdict.final_verdict if verdict else "New",
            "Description": verdict.analysis_reasoning if verdict else None,
        }
    else:  # pipedrive
        payload = {
            "person": {"name": lead.name, "email": [{"value": lead.email}]},
            "organization": {"name": lead.company},
            "deal": {
                "title": f"{lead.company} — {verdict.final_verdict if verdict else 'Lead'}",
                "status": "open",
            },
        }

    return {
        "format": format,
        "lead_id": lead_id,
        "payload": payload,
        "simulated": True,
        "pushed_at": utcnow().isoformat(),
        "note": (
            "Production: uncomment CRM API calls in app/services/crm_sync.py "
            "and set the relevant API key env vars."
        ),
    }

@router.get("/leads/{lead_id}/referral-chain")
def get_referral_chain(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Return the referral chain for a lead:
      - referred_by: the lead whose org-chart traversal discovered this one
      - discovered: leads this lead's traversal found (its org-chart children)
    """
    lead = crud.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    def _lead_stub(ld) -> dict:
        return {
            "id": ld.id,
            "name": ld.name,
            "email": ld.email,
            "company": ld.company,
            "job_title": ld.enrichments[0].job_title if ld.enrichments else None,
            "seniority": ld.enrichments[0].seniority if ld.enrichments else None,
            "final_verdict": ld.verdicts[0].final_verdict if ld.verdicts else None,
            "status": ld.status,
        }

    # Parent — who discovered this lead
    referred_by = None
    if lead.referred_by_lead_id:
        parent = crud.get_lead(db, lead.referred_by_lead_id)
        if parent:
            referred_by = _lead_stub(parent)

    # Children — leads this lead's org-chart traversal found
    from sqlalchemy.orm import selectinload
    children = (
        db.query(Lead)
        .options(selectinload(Lead.enrichments), selectinload(Lead.verdicts))
        .filter(Lead.referred_by_lead_id == lead_id)
        .order_by(Lead.created_at.asc())
        .all()
    )
    discovered = [_lead_stub(c) for c in children]

    return {
        "lead_id": lead_id,
        "referred_by": referred_by,
        "discovered": discovered,
        "has_chain": referred_by is not None or len(discovered) > 0,
    }

@router.get("/leads/{lead_id}/similar")
def get_similar_leads(
    lead_id: str,
    limit: int = Query(5, ge=1, le=20),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return leads with the most similar BANT + enrichment profile."""
    from app.services.market_intelligence import similar_leads
    results = similar_leads(db, lead_id, limit=limit)
    return {"lead_id": lead_id, "similar": results, "count": len(results)}

@router.post("/leads/{lead_id}/web-enrich")
def web_enrich_lead(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Scrape the lead's company domain for buying signals and tech stack."""
    from sqlalchemy.orm import selectinload
    from app.services.web_enrichment import enrich_from_domain

    lead = db.query(Lead).options(selectinload(Lead.enrichments)).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    domain_source = lead.email
    enrichment = lead.enrichments[0] if lead.enrichments else None

    result = enrich_from_domain(domain_source)
    result["lead_id"] = lead_id
    result["lead_name"] = lead.name

    # Merge detected tech into existing enrichment
    if enrichment and result["tech_stack"]:
        existing = list(enrichment.tech_stack or [])
        for t in result["tech_stack"]:
            if t not in existing:
                existing.append(t)
        enrichment.tech_stack = existing
        db.commit()

    return result
