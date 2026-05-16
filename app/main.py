import logging
import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, RedirectResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from sqlalchemy.orm import Session

# Configure structlog before any other imports that use logging
from app.logging_config import configure_logging
configure_logging()

import structlog
log = structlog.get_logger(__name__)

from app.database.connection import get_db, create_all_tables
from app.database import crud
from app.database.models import Lead, Enrichment, Verdict
from app.services.queue_service import push_lead_job, get_redis
from app.services.ollama_client import OllamaConnectionError
from app.services.deduplication import DeduplicationService
from app.services.csv_import import CSVImportService
from app.services.validation import EmailDomainValidator
from app.services.slack_notifier import SlackNotifier
from app.services.data_quality import DataQualityService
from app.services.export_service import build_export_rows, to_csv_bytes, to_hubspot_rows, to_salesforce_rows
from app.services.batch_service import execute_batch
from app.schemas.lead import LeadCreate, LeadResponse, LeadDetail, BatchRequest, ImportHistoryResponse, AssignRequest, ConversionRequest, LeadHistoryEntry, AssignmentStats
from app.auth.dependencies import get_current_user, require_admin, require_manager, require_rep
from app.database.models import User
from app.routers.auth import router as auth_router
from app.routers.ingest import router as ingest_router
from app.services.rate_limiter import limiter
from app.config import settings
from fastapi import UploadFile, File


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: Create tables and validate dependencies
    Shutdown: Cleanup if needed
    """
    try:
        import os as _os
        _testing = bool(_os.getenv("TESTING"))

        log.info("startup", service="AutonomousSDR")
        if not _testing:
            create_all_tables()

        # Validate Redis connection (skipped in test mode)
        if not _testing:
            try:
                redis = get_redis()
                redis.ping()
                log.info("startup.redis", status="ok")
            except Exception as e:
                log.error("startup.redis", status="failed", error=str(e))
                raise

        # Validate AI provider connection (optional — skipped in test mode)
        if not _testing:
            try:
                from app.services.providers import get_ai_client
                client = get_ai_client()
                client.generate("ping")
                log.info("startup.ai_provider", provider=settings.AI_PROVIDER, status="ok")
            except OllamaConnectionError as e:
                log.warning("startup.ai_provider", provider=settings.AI_PROVIDER, status="not_ready", error=str(e))
            except Exception as e:
                log.warning("startup.ai_provider", provider=settings.AI_PROVIDER, status="not_ready", error=str(e))
        
        # Seed initial admin if no users exist (skipped in test mode)
        if not _testing:
            try:
                from app.database.connection import SessionLocal
                from app.database.models import User as UserModel
                from app.services.auth_service import hash_password
                import uuid
                db_seed = SessionLocal()
                try:
                    if db_seed.query(UserModel).count() == 0:
                        admin = UserModel(
                            id=str(uuid.uuid4()),
                            email=settings.INITIAL_ADMIN_EMAIL,
                            password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
                            role="admin",
                        )
                        db_seed.add(admin)
                        db_seed.commit()
                        log.info("startup.admin_seed", email=settings.INITIAL_ADMIN_EMAIL)
                    else:
                        log.info("startup.admin_seed", status="already_exists")
                finally:
                    db_seed.close()
            except Exception as e:
                log.warning("startup.admin_seed", status="skipped", error=str(e))

        # Start background scheduler (auto-requeue + metrics refresh)
        scheduler = None
        if not _testing:
            try:
                from app.services.scheduler import create_scheduler
                scheduler = create_scheduler()
                scheduler.start()
                log.info("startup.scheduler", status="ok", jobs=len(scheduler.get_jobs()))
            except Exception as e:
                log.warning("startup.scheduler", status="failed", error=str(e))

        log.info("startup.ready", ai_provider=settings.AI_PROVIDER, enrichment_provider=settings.ENRICHMENT_PROVIDER)
        yield

        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("shutdown.scheduler")
        log.info("shutdown")
    except Exception as e:
        log.critical("startup.failed", error=str(e))
        raise


app = FastAPI(title="AutonomousSDR", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers
class _SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.APP_ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(_SecurityHeaders)

# CORS — localhost regex always active; production origins loaded from env
_prod_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()] if settings.ALLOWED_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_prod_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "Accept", "Origin"],
)

app.include_router(auth_router)
app.include_router(ingest_router)

# Global Slack notifier
slack_notifier = SlackNotifier()
# Store webhook URL in memory (in production, use database)
slack_webhook_url = None


@app.get("/health")
def health_check():
    from app.services.queue_service import get_worker_status
    worker = get_worker_status()
    return {
        "status": "healthy",
        "service": "AutonomousSDR",
        "version": "1.0.0",
        "ai_provider": settings.AI_PROVIDER,
        "enrichment_provider": settings.ENRICHMENT_PROVIDER,
        "worker_active": worker["worker_active"],
        "worker_last_seen": worker["worker_last_seen"],
    }


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """
    Prometheus-format metrics endpoint.
    Scrape with Grafana Agent or Prometheus: scrape_interval: 15s
    Grafana Cloud free tier: https://grafana.com/products/cloud/
    """
    from app.metrics import metrics_response
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


@app.get("/leads/{lead_id}/pipeline/stream", include_in_schema=False)
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


@app.post("/leads", response_model=LeadResponse)
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
        )
        push_lead_job(lead.id)
        log.info("lead.created", lead_id=lead.id[:8], email=lead.email)
        return lead
    except Exception as e:
        log.error("Failed to create lead", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create lead")


@app.get("/leads", response_model=list[LeadResponse])
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


@app.get("/leads/stats")
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


@app.get("/leads/quality-report")
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


@app.post("/leads/quality-backfill")
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


@app.get("/leads/hot")
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


@app.get("/leads/export")
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
        query = db.query(Lead).filter(Lead.status == "complete", Lead.archived == False)

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


# ============================================================================
# PHASE 1 FEATURES: Deduplication, CSV Import, Validation, Slack Alerts
# ============================================================================

@app.post("/leads/import-csv")
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
        result = import_service.import_leads(content, check_duplicates=check_duplicates)

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


@app.get("/leads/duplicates/report")
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
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        log.error("Failed to generate duplicate report", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate duplicate report")


@app.get("/leads/import-history")
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


@app.post("/leads/reprocess-failed")
def reprocess_failed(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Re-queue all failed leads back into the processing pipeline."""
    from app.services.queue_service import push_lead_job
    from datetime import datetime
    failed = db.query(Lead).filter(Lead.status == "failed").all()
    if not failed:
        return {"requeued": 0, "message": "No failed leads found"}
    now = datetime.utcnow()
    for lead in failed:
        lead.status = "processing"
        lead.updated_at = now
        push_lead_job(lead.id)
    db.commit()
    log.info("leads.reprocess", count=len(failed), triggered_by=current_user.email)
    return {"requeued": len(failed), "message": f"{len(failed)} leads re-queued for processing"}


@app.post("/leads/batch")
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


@app.post("/leads/{lead_id}/assign")
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


@app.delete("/leads/{lead_id}/assign")
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


@app.post("/leads/{lead_id}/conversion")
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


@app.get("/leads/{lead_id}/history", response_model=list[LeadHistoryEntry])
def get_lead_history_endpoint(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get history timeline for a lead."""
    from app.services.assignment_service import get_lead_history
    return get_lead_history(db, lead_id)


@app.get("/dashboard/assignment-stats", response_model=list[AssignmentStats])
def get_assignment_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Get assignment and conversion stats for all reps."""
    from app.database.models import User, Lead

    reps = db.query(User).filter(User.role == "rep", User.is_active == True).all()
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


@app.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(
    lead_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Get detailed information about a specific lead"""
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        enrichment = lead.enrichments[0] if lead.enrichments else None
        verdict = lead.verdicts[0] if lead.verdicts else None

        detail = LeadDetail.model_validate(lead)
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


@app.get("/leads/{lead_id}/quality-score")
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


@app.post("/leads/{lead_id}/check-duplicate")
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


@app.post("/leads/{primary_id}/merge/{duplicate_id}")
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


@app.post("/validate/email")
def validate_email(
    email: str = Query(...),
    current_user: User = Depends(require_rep),
):
    """Validate email format, domain, and characteristics"""
    try:
        result = EmailDomainValidator.validate_email_with_domain(email, check_mx=True)
        
        return {
            "email": email,
            "validation": result,
            "is_valid": result['email']['is_valid'],
            "is_deliverable": result['is_deliverable'],
            "overall_quality": result['overall_quality'],
            "issues": result['email']['issues'] + (result['domain']['issues'] if result['domain'] else [])
        }
    except Exception as e:
        log.error("Failed to validate email {email}", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to validate email")


@app.post("/validate/email-batch")
def validate_email_batch(
    emails: list[str],
    current_user: User = Depends(require_rep),
):
    """Validate multiple emails at once"""
    try:
        results = []
        for email in emails:
            result = EmailDomainValidator.validate_email_with_domain(email, check_mx=True)
            results.append({
                "email": email,
                "is_valid": result['email']['is_valid'],
                "is_deliverable": result['is_deliverable'],
                "overall_quality": result['overall_quality'],
                "domain_type": EmailDomainValidator.get_domain_type(email)
            })
        
        return {
            "total": len(emails),
            "valid": sum(1 for r in results if r['is_valid']),
            "deliverable": sum(1 for r in results if r['is_deliverable']),
            "results": results
        }
    except Exception as e:
        log.error("Failed to validate email batch", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to validate emails")


@app.get("/config/slack")
def get_slack_config(current_user: User = Depends(require_admin)):
    """Get current Slack webhook configuration"""
    return {
        "configured": slack_notifier.enabled,
        "webhook_url": "***" if slack_notifier.webhook_url else None
    }


@app.post("/config/slack")
def set_slack_config(
    current_user: User = Depends(require_admin),
    webhook_url: str = Query(...),
):
    """Set Slack webhook URL for notifications"""
    try:
        global slack_webhook_url
        
        if not webhook_url or len(webhook_url) == 0:
            raise HTTPException(status_code=400, detail="Webhook URL cannot be empty")
        
        # Validate webhook URL format
        if not webhook_url.startswith('https://hooks.slack.com/'):
            raise HTTPException(
                status_code=400, 
                detail="Invalid webhook URL format. Must be from hooks.slack.com"
            )
        
        slack_notifier.set_webhook(webhook_url)
        slack_webhook_url = webhook_url
        
        log.info("slack.webhook.configured")
        
        return {
            "status": "success",
            "message": "Slack webhook configured",
            "configured": True
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to set Slack webhook", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to configure Slack")


@app.post("/config/slack/test")
def test_slack_webhook(current_user: User = Depends(require_admin)):
    """Test Slack webhook connectivity"""
    try:
        if not slack_notifier.enabled:
            raise HTTPException(
                status_code=400, 
                detail="Slack webhook not configured"
            )
        
        success = slack_notifier.test_webhook()
        
        return {
            "status": "success" if success else "failed",
            "message": "Webhook test successful" if success else "Webhook test failed",
            "configured": slack_notifier.enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to test Slack webhook", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to test webhook")


@app.get("/config/enrichment-provider")
def get_enrichment_provider(current_user: User = Depends(require_admin)):
    """Return the active enrichment provider."""
    return {"enrichment_provider": settings.ENRICHMENT_PROVIDER}


@app.post("/config/enrichment-provider")
def set_enrichment_provider(
    provider: str = Query(..., description="synthetic | hunter | pdl"),
    current_user: User = Depends(require_admin),
):
    """
    Toggle enrichment provider at runtime — no restart required.

    Providers:
      synthetic — default, free, heuristic (great for demos)
      hunter    — Hunter.io real company data (25 free lookups/month)
      pdl       — People Data Labs (100 free lookups/month)
    """
    _valid = {"synthetic", "hunter", "pdl"}
    if provider not in _valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider. Valid options: {', '.join(sorted(_valid))}")
    settings.ENRICHMENT_PROVIDER = provider
    log.info("config.enrichment_provider.updated", provider=provider, changed_by=current_user.email)
    return {"status": "updated", "enrichment_provider": provider}


@app.post("/config/slack/disable")
def disable_slack(current_user: User = Depends(require_admin)):
    """Disable Slack notifications"""
    try:
        global slack_webhook_url
        slack_notifier.set_webhook(None)
        slack_webhook_url = None

        log.info("slack.webhook.disabled")

        return {
            "status": "success",
            "message": "Slack notifications disabled",
            "configured": False
        }
    except Exception as e:
        log.error("Failed to disable Slack", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to disable Slack")


# ===========================================================================
# Outreach endpoints
# ===========================================================================

@app.post("/leads/{lead_id}/outreach")
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


@app.get("/leads/{lead_id}/outreach")
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
    return [
        {
            "id": e.id,
            "step": e.step_number,
            "subject": e.subject,
            "status": e.status,
            "scheduled_at": e.scheduled_at.isoformat() if e.scheduled_at else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
        }
        for e in emails
    ]


@app.post("/outreach/emails/{email_id}/event")
def track_email_event(
    email_id: str,
    event: str = Query(..., description="sent | opened | replied | booked | converted"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Record an engagement event on an outreach email (open, reply, etc.)."""
    from app.services.ab_testing import record_event
    try:
        record_event(db, email_id, event)
        return {"status": "recorded", "email_id": email_id, "event": event}
    except Exception as e:
        log.error("Failed to record event {event} on email {email_id}", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================================================
# Booking endpoints
# ===========================================================================

@app.post("/leads/{lead_id}/book")
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


@app.get("/leads/{lead_id}/bookings")
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
            "status": b.status,
            "booking_link": b.booking_link,
            "external_booking_id": b.external_booking_id,
            "start_time": b.start_time.isoformat() if b.start_time else None,
            "created_at": b.created_at.isoformat(),
        }
        for b in bookings
    ]
    return {"bookings": rows, "count": len(rows)}


@app.patch("/leads/{lead_id}/bookings/{booking_id}")
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
    booking.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "updated", "booking_id": booking_id, "new_status": status}


# ===========================================================================
# Conversational agent endpoints
# ===========================================================================

@app.post("/leads/{lead_id}/chat")
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


@app.get("/leads/{lead_id}/conversations")
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
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": (c.messages or [])[-10:],  # last 10 messages
        }
        for c in convs
    ]
    return {"conversations": rows, "count": len(rows)}


# ===========================================================================
# Intent scoring endpoints
# ===========================================================================

@app.post("/leads/{lead_id}/intent")
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


@app.get("/leads/{lead_id}/intent")
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
        "total_score": round(min(1.0, sum(s.score for s in signals)), 4),
        "signals": [
            {
                "type": s.signal_type,
                "score": s.score,
                "source": s.source,
                "captured_at": s.captured_at.isoformat(),
            }
            for s in signals
        ],
    }


# ===========================================================================
# CRM sync endpoints
# ===========================================================================

@app.post("/leads/{lead_id}/crm-sync")
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


# ===========================================================================
# A/B testing endpoints
# ===========================================================================

@app.get("/ab-tests/results")
def get_ab_results(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return per-variant conversion metrics for all outreach sequences."""
    from app.services.ab_testing import get_test_results, find_winner, _chi_square_p, _MIN_SAMPLE
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


@app.post("/ab-tests/promote-winner")
def promote_ab_winner_legacy(
    sequence_id: str = Query(...),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Legacy query-param route — prefer POST /ab-tests/{sequence_id}/promote."""
    from app.services.ab_testing import promote_winner
    promote_winner(db, sequence_id)
    return {"status": "promoted", "winning_sequence_id": sequence_id}


@app.post("/ab-tests/{sequence_id}/promote")
def promote_ab_winner(
    sequence_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deactivate all other sequences and promote this one as the winner."""
    from app.services.ab_testing import promote_winner
    promote_winner(db, sequence_id)
    return {"status": "promoted", "winning_sequence_id": sequence_id}


# ===========================================================================
# Self-optimization endpoints
# ===========================================================================

@app.post("/optimization/run")
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


@app.get("/optimization/history")
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


@app.get("/optimization/weights")
def get_current_weights_endpoint(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the BANT weights currently used for scoring."""
    from app.services.optimization_loop import get_current_weights
    return get_current_weights(db)


# ===========================================================================
# Email tracking — open pixel + click redirect
# ===========================================================================

# 1×1 transparent GIF — served for every open-tracking request
_TRACKING_PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!"
    b"\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


@app.get("/track/open/{email_id}", include_in_schema=False)
def track_open(email_id: str, db: Session = Depends(get_db)):
    """
    Called when a lead opens an email (via embedded <img> tag).
    Records the open time and returns a transparent 1×1 GIF so the
    email client doesn't display a broken image.

    Embed in outreach HTML body:
      <img src="{BASE_URL}/track/open/{email_id}" width="1" height="1" />
    """
    from app.database.models import OutreachEmail
    from app.services.ab_testing import record_event
    try:
        email = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email and not email.opened_at:
            email.opened_at = datetime.utcnow()
            email.status = "opened"
            db.commit()
            record_event(db, email_id, "opened")
            log.info(f"[track/open] Email {email_id} opened")
    except Exception as e:
        log.warning("[track/open] Failed to record open for {email_id}", error=str(e))
    return Response(content=_TRACKING_PIXEL, media_type="image/gif")


@app.get("/track/click/{email_id}", include_in_schema=False)
def track_click(
    email_id: str,
    url: str = Query(..., description="Destination URL after click is recorded"),
    db: Session = Depends(get_db),
):
    """
    Called when a lead clicks a tracked link.
    Records the click, then redirects to the real destination URL.

    Wrap links in outreach body:
      href="{BASE_URL}/track/click/{email_id}?url={urllib.parse.quote(real_url)}"
    """
    from app.database.models import OutreachEmail
    from app.services.ab_testing import record_event
    try:
        email = db.query(OutreachEmail).filter(OutreachEmail.id == email_id).first()
        if email:
            if not email.opened_at:
                email.opened_at = datetime.utcnow()
                email.status = "opened"
                record_event(db, email_id, "opened")
            db.commit()
            log.info(f"[track/click] Email {email_id} clicked → {url[:80]}")
    except Exception as e:
        log.warning("[track/click] Failed to record click for {email_id}", error=str(e))
    return RedirectResponse(url=url, status_code=302)


# ===========================================================================
# Power BI / analytics export
# ===========================================================================

@app.get("/analytics/powerbi-export")
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
    from app.database.models import OutreachEmail, IntentSignal, BookingRequest
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


@app.get("/analytics/powerbi-export.csv")
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


@app.get("/analytics/semantic-search")
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


# ===========================================================================
# Pipeline trace — LangGraph per-lead execution breakdown
# ===========================================================================

@app.get("/leads/{lead_id}/pipeline-trace")
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
    nodes_executed = list(dict.fromkeys(l.agent_name for l in logs if l.success))

    return {
        "lead_id": lead_id,
        "lead_name": lead.name,
        "status": lead.status,
        "final_verdict": verdict.final_verdict if verdict else None,
        "nodes_executed": nodes_executed,
        "agent_logs": [
            {
                "id": l.id,
                "agent_name": l.agent_name,
                "status": "success" if l.success else "failed",
                "duration_ms": l.duration_ms,
                "error_message": l.error_message,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


# ===========================================================================
# Outreach aggregate stats (for dashboard KPI cards)
# ===========================================================================

@app.get("/outreach/stats")
def get_outreach_stats(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Aggregate email engagement stats across all sequences."""
    from app.database.models import OutreachEmail as OutreachEmailModel
    from sqlalchemy import func

    rows = db.query(OutreachEmailModel).all()
    total_sent = sum(1 for r in rows if r.status in ("sent", "opened", "replied"))
    total_opened = sum(1 for r in rows if r.status in ("opened", "replied"))
    total_replied = sum(1 for r in rows if r.status == "replied")

    return {
        "total_sent": total_sent,
        "total_opened": total_opened,
        "total_replied": total_replied,
        "open_rate": round(total_opened / total_sent, 4) if total_sent else 0.0,
        "reply_rate": round(total_replied / total_sent, 4) if total_sent else 0.0,
        "emails_by_status": {
            status: sum(1 for r in rows if r.status == status)
            for status in ("scheduled", "sent", "opened", "replied", "failed")
        },
    }
