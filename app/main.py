import json
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request, BackgroundTasks
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
from app.auth.dependencies import require_admin, require_manager, require_rep
from app.database.models import User
from app.routers.auth import router as auth_router
from app.routers.ingest import router as ingest_router
from app.services.rate_limiter import limiter
from app.config import settings
from fastapi import UploadFile, File
from app.utils.time import utcnow


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

from app.routers.approvals import router as approvals_router  # noqa: E402
app.include_router(approvals_router)

from app.routers.sequences import router as sequences_router  # noqa: E402
app.include_router(sequences_router)

from app.routers.mailboxes import router as mailboxes_router  # noqa: E402
app.include_router(mailboxes_router)

from app.routers.ai_ops import router as ai_ops_router  # noqa: E402
app.include_router(ai_ops_router)

from app.routers.gdpr import router as gdpr_router  # noqa: E402
app.include_router(gdpr_router)

from app.routers.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router)

from app.routers.backtests import router as backtests_router  # noqa: E402
app.include_router(backtests_router)

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
            org_id=current_user.org_id,
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


@app.get("/leads/trend")
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
            "generated_at": utcnow().isoformat()
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


@app.get("/leads/{lead_id}", response_model=LeadDetail)
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


@app.get("/leads/{lead_id}/verdict-explanation")
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


# ===========================================================================
# Autonomy activity feed — "what did the system do while you were away?"
# ===========================================================================

@app.get("/autonomy-feed")
def get_autonomy_feed(
    hours: int = Query(24, ge=1, le=168, description="Look-back window in hours"),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """
    Return a reverse-chronological log of autonomous actions taken by the
    system in the last N hours.  Events include:

      follow_up_sent      — scheduler sent a step-2/3 sequence email
      trigger_fired       — trigger monitor detected a buying signal and created outreach
      lead_requalified    — Bayesian update pushed a Cold/Warm lead back through the pipeline
      bant_weights_updated — self-optimisation loop updated scoring weights
      lead_qualified      — pipeline completed qualification for a new lead
    """
    from datetime import timedelta
    from app.database.models import (
        OutreachEmail, IntentSignal, OptimizationRun, Lead as LeadModel,
    )
    from app.database.models import LeadEvent

    since = utcnow() - timedelta(hours=hours)
    events = []

    # ── Follow-up emails sent by the scheduler (step > 1) ───────────────────
    follow_ups = (
        db.query(OutreachEmail, LeadModel)
        .join(LeadModel, OutreachEmail.lead_id == LeadModel.id)
        .filter(
            OutreachEmail.sent_at >= since,
            OutreachEmail.step_number > 1,
        )
        .order_by(OutreachEmail.sent_at.desc())
        .limit(30)
        .all()
    )
    for email, lead in follow_ups:
        events.append({
            "type": "follow_up_sent",
            "ts": email.sent_at.isoformat(),
            "lead_name": lead.name,
            "company": lead.company,
            "step": email.step_number,
            "subject": email.subject,
        })

    # ── Trigger monitor fired (funding / job posting / news) ─────────────────
    signals = (
        db.query(IntentSignal, LeadModel)
        .join(LeadModel, IntentSignal.lead_id == LeadModel.id)
        .filter(IntentSignal.captured_at >= since)
        .order_by(IntentSignal.captured_at.desc())
        .limit(30)
        .all()
    )
    for sig, lead in signals:
        events.append({
            "type": "trigger_fired",
            "ts": sig.captured_at.isoformat(),
            "lead_name": lead.name,
            "company": lead.company,
            "trigger": sig.signal_type,
            "headline": (sig.signal_metadata or {}).get("headline", sig.signal_type),
            "score_delta": sig.score,
        })

    # ── Bayesian re-qualification (pipeline.complete events after open/click) ─
    requalified = (
        db.query(LeadEvent, LeadModel)
        .join(LeadModel, LeadEvent.lead_id == LeadModel.id)
        .filter(
            LeadEvent.event_type == "pipeline.complete",
            LeadEvent.created_at >= since,
        )
        .order_by(LeadEvent.created_at.desc())
        .limit(30)
        .all()
    )
    for ev, lead in requalified:
        verdict_val = (ev.payload or {}).get("verdict")
        events.append({
            "type": "lead_qualified",
            "ts": ev.created_at.isoformat(),
            "lead_name": lead.name,
            "company": lead.company,
            "verdict": verdict_val,
        })

    # ── Self-optimisation weight updates ─────────────────────────────────────
    opt_runs = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.run_at >= since)
        .order_by(OptimizationRun.run_at.desc())
        .limit(10)
        .all()
    )
    for run in opt_runs:
        events.append({
            "type": "bant_weights_updated",
            "ts": run.run_at.isoformat(),
            "old_weights": run.old_weights,
            "new_weights": run.new_weights,
            "improvement": round(run.improvement_score or 0, 4),
            "sample_size": run.sample_size,
        })

    # Sort all events newest-first
    events.sort(key=lambda e: e["ts"], reverse=True)

    # Compute summary stats
    summary = {
        "window_hours": hours,
        "total_events": len(events),
        "follow_ups_sent": sum(1 for e in events if e["type"] == "follow_up_sent"),
        "triggers_fired": sum(1 for e in events if e["type"] == "trigger_fired"),
        "leads_qualified": sum(1 for e in events if e["type"] == "lead_qualified"),
        "weight_updates": sum(1 for e in events if e["type"] == "bant_weights_updated"),
    }

    return {"summary": summary, "events": events[:50]}


# ===========================================================================
# Debate / Adversarial BANT endpoints
# ===========================================================================

@app.get("/leads/{lead_id}/debate")
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


# ===========================================================================
# Pre-call brief endpoints
# ===========================================================================

@app.get("/leads/{lead_id}/pre-call-brief")
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


# ===========================================================================
# Trigger signals endpoints
# ===========================================================================

_TRIGGER_SIGNAL_TYPES = frozenset({
    "funding_trigger", "job_posting_trigger", "news_trigger", "job_change_trigger",
})


@app.get("/leads/{lead_id}/trigger-signals")
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
            IntentSignal.signal_type.in_(list(_TRIGGER_SIGNAL_TYPES)),
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


@app.get("/analytics/signal-feed")
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
        .filter(IntentSignal.signal_type.in_(list(_TRIGGER_SIGNAL_TYPES)))
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
    booking.updated_at = utcnow()
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
            "sentiment": c.sentiment,
            "needs_human": c.needs_human,
            "human_flagged_at": c.human_flagged_at.isoformat() if c.human_flagged_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": (c.messages or [])[-20:],
        }
        for c in convs
    ]
    return {"conversations": rows, "count": len(rows)}


# ===========================================================================
# Global inbox — all conversations across leads, sorted by urgency
# ===========================================================================

@app.get("/inbox")
def get_inbox(
    needs_human: bool | None = Query(None, description="Filter to conversations flagged for human review"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return all conversation threads across leads, sorted: needs_human first, then newest."""
    from app.database.models import Conversation, Lead as LeadModel
    query = (
        db.query(Conversation, LeadModel)
        .join(LeadModel, Conversation.lead_id == LeadModel.id)
    )
    if needs_human is not None:
        query = query.filter(Conversation.needs_human == needs_human)
    results = (
        query
        .order_by(Conversation.needs_human.desc(), Conversation.updated_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    rows = [
        {
            "id": c.id,
            "lead_id": c.lead_id,
            "lead_name": lead.name,
            "lead_email": lead.email,
            "company": lead.company,
            "channel": c.channel,
            "message_count": len(c.messages or []),
            "summary": c.summary,
            "sentiment": c.sentiment,
            "needs_human": c.needs_human,
            "human_flagged_at": c.human_flagged_at.isoformat() if c.human_flagged_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "messages": (c.messages or [])[-20:],
        }
        for c, lead in results
    ]
    needs_review = sum(1 for r in rows if r["needs_human"])
    return {"conversations": rows, "count": len(rows), "needs_review": needs_review}


@app.post("/conversations/{conv_id}/resolve")
def resolve_conversation(
    conv_id: str,
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Clear the needs_human flag — rep has handled the escalation."""
    from app.database.models import Conversation
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.needs_human = False
    conv.human_flagged_at = None
    db.commit()
    return {"status": "resolved", "conversation_id": conv_id}


# ===========================================================================
# Revenue funnel — conversion stages with value estimates
# ===========================================================================

_FUNNEL_STAGES = ["unqualified", "qualified", "contacted", "scheduled", "won", "lost"]
_ACTIVE_STAGES = ["unqualified", "qualified", "contacted", "scheduled", "won"]


@app.get("/analytics/funnel")
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
            email.opened_at = utcnow()
            email.status = "opened"
            db.commit()
            record_event(db, email_id, "opened")
            log.info(f"[track/open] Email {email_id} opened")
            # Bayesian BANT update + autonomous re-qualification check
            if email.lead_id:
                from app.services.bayesian_updater import apply_bayesian_update
                from app.database.models import Verdict as _Verdict
                result = apply_bayesian_update(db, email.lead_id, "open")
                if result:
                    # If a Cold/Warm lead now crosses the Hot confidence threshold,
                    # push them back into the full qualification pipeline.
                    new_conf = result["new_confidence"]
                    verdict_row = (
                        db.query(_Verdict)
                        .filter(_Verdict.lead_id == email.lead_id)
                        .first()
                    )
                    current_verdict = verdict_row.final_verdict if verdict_row else None
                    requeued = False
                    if new_conf >= 0.70 and current_verdict in ("Cold", "Warm", None):
                        try:
                            push_lead_job(email.lead_id)
                            crud.update_lead_status(db, email.lead_id, "pending")
                            log.info(
                                f"[track/open] Re-queued lead {email.lead_id[:8]} for re-qualification "
                                f"(confidence {new_conf:.2f} crossed threshold, was {current_verdict})"
                            )
                            requeued = True
                        except Exception as _rq_err:
                            log.warning(f"[track/open] Re-queue failed: {_rq_err}")
                    try:
                        import redis as _redis
                        import json as _json
                        _r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
                        _r.publish("asdr:global_events", _json.dumps({
                            "type": "score_update",
                            "lead_id": email.lead_id,
                            "signal": "open",
                            "new_confidence": new_conf,
                            "requeued": requeued,
                        }))
                        _r.close()
                    except Exception:
                        pass
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
                email.opened_at = utcnow()
                email.status = "opened"
                record_event(db, email_id, "opened")
            db.commit()
            log.info(f"[track/click] Email {email_id} clicked → {url[:80]}")
            # Clicks are a stronger intent signal than opens — apply Bayesian update
            # and re-qualify at a lower threshold (0.60) since clicking shows real interest.
            if email.lead_id:
                from app.services.bayesian_updater import apply_bayesian_update
                from app.database.models import Verdict as _VerdictC
                result = apply_bayesian_update(db, email.lead_id, "click")
                if result and result["new_confidence"] >= 0.60:
                    verdict_row = (
                        db.query(_VerdictC)
                        .filter(_VerdictC.lead_id == email.lead_id)
                        .first()
                    )
                    if verdict_row and verdict_row.final_verdict in ("Cold", "Warm", None):
                        try:
                            push_lead_job(email.lead_id)
                            crud.update_lead_status(db, email.lead_id, "pending")
                            log.info(
                                f"[track/click] Re-queued lead {email.lead_id[:8]} after click "
                                f"(confidence={result['new_confidence']:.2f})"
                            )
                        except Exception:
                            pass
    except Exception as e:
        log.warning("[track/click] Failed to record click for {email_id}", error=str(e))
    return RedirectResponse(url=url, status_code=302)


@app.get("/leads/{lead_id}/outreach/generate/stream", include_in_schema=False)
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


@app.get("/track/visit", include_in_schema=False)
def track_visit(
    request: Request,
    page: str = Query("unknown", description="Page slug, e.g. 'pricing', 'home'"),
    ref: str = Query("", description="Document referrer (optional)"),
    db: Session = Depends(get_db),
):
    """
    Website visitor de-anonymization pixel.

    Embed on any page to identify corporate visitors without a form submission:
      <img src="{BASE_URL}/track/visit?page=pricing" width="1" height="1"
           style="display:none" />

    When a company employee visits from a corporate IP, we identify their
    company via reverse-IP lookup and create a lead with source="ip_visit".
    Subsequent visits from the same identified company add a pricing_page_visit
    intent signal to the existing lead (capped to one per 3 days).

    Returns the same 1x1 transparent GIF as the email open pixel.
    """
    from datetime import timedelta
    from app.services.ip_intelligence import identify_visitor, is_private_ip
    from app.database.models import Lead, IntentSignal

    # Resolve real visitor IP through common proxy headers
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = (
        forwarded.split(",")[0].strip()
        or request.headers.get("X-Real-IP", "")
        or (request.client.host if request.client else "")
    )

    if ip and not is_private_ip(ip):
        try:
            identity = identify_visitor(ip)
            if identity["identified"] and identity["company"]:
                company = identity["company"]
                domain = identity.get("domain") or ""
                # Synthetic email built from company name — deterministic so dupes are caught
                synthetic_email = f"visitor@{domain}" if domain else (
                    f"visitor+{re.sub(r'[^a-z0-9]', '', company.lower())}@unknown.com"
                )

                existing = db.query(Lead).filter(Lead.email == synthetic_email).first()
                if not existing:
                    new_lead = crud.create_lead(
                        db,
                        name=f"{company} (Anonymous Visitor)",
                        email=synthetic_email,
                        company=company,
                        source="ip_visit",
                    )
                    new_lead.identified_via_ip = True
                    new_lead.quality_metadata = {
                        "ip_org": identity.get("org_raw"),
                        "city": identity.get("city"),
                        "country": identity.get("country"),
                        "visited_page": page,
                        "referrer": ref[:200] if ref else "",
                    }
                    db.commit()
                    try:
                        from app.services.queue_service import push_lead_job
                        push_lead_job(new_lead.id)
                    except Exception:
                        pass
                    log.info(
                        f"[track/visit] New IP lead: '{company}' "
                        f"from {ip[:8]}*** page={page}"
                    )
                else:
                    # Add / refresh a pricing_page_visit intent signal
                    cutoff = utcnow() - timedelta(days=3)
                    recent = (
                        db.query(IntentSignal)
                        .filter(
                            IntentSignal.lead_id == existing.id,
                            IntentSignal.signal_type == "pricing_page_visit",
                            IntentSignal.captured_at > cutoff,
                        )
                        .first()
                    )
                    if not recent:
                        db.add(IntentSignal(
                            lead_id=existing.id,
                            signal_type="pricing_page_visit",
                            score=0.25,
                            source="ip_intelligence",
                            signal_metadata={
                                "page": page,
                                "city": identity.get("city"),
                                "country_code": identity.get("country_code"),
                            },
                        ))
                        db.commit()
                        log.info(
                            f"[track/visit] Visit signal added for '{existing.name}' "
                            f"page={page}"
                        )
        except Exception as e:
            log.debug(f"[track/visit] identification failed for {ip}: {e}")

    return Response(content=_TRACKING_PIXEL, media_type="image/gif")


# ===========================================================================
# Inbound email reply webhook
# ===========================================================================

@app.post("/ingest/email-reply", status_code=202)
async def ingest_email_reply(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Webhook endpoint for inbound email replies from a sending platform
    (Sendgrid Inbound Parse, Mailgun Routes, PostMark, etc.).

    Expected payload (all fields optional except `reply_text`):
      {
        "reply_text":   "Thanks, I'd love to learn more...",
        "from_email":   "jane@acme.com",
        "subject":      "Re: Quick question about Acme",
        "email_id":     "<uuid of the OutreachEmail that was replied to>",
        "lead_id":      "<uuid — alternative to email_id>"
      }

    The ConversationalAgent generates a contextual reply, persists the thread,
    and (if no SMTP is configured) marks the agent reply as "sent_demo".
    """
    from app.database.models import OutreachEmail as OutreachEmailModel

    reply_text = (payload.get("reply_text") or "").strip()
    if not reply_text:
        raise HTTPException(status_code=422, detail="reply_text is required")

    # Resolve lead_id: prefer explicit, fall back to OutreachEmail lookup
    lead_id = payload.get("lead_id") or ""
    email_id = payload.get("email_id") or ""
    from_email = payload.get("from_email") or ""

    if not lead_id and email_id:
        email_rec = db.query(OutreachEmailModel).filter(OutreachEmailModel.id == email_id).first()
        if email_rec:
            lead_id = email_rec.lead_id

    if not lead_id and from_email:
        match = db.query(Lead).filter(Lead.email == from_email).first()
        if match:
            lead_id = match.id

    if not lead_id:
        raise HTTPException(
            status_code=404,
            detail="Could not resolve lead — provide lead_id, email_id, or from_email",
        )

    # Shared reply pipeline (same one the IMAP poller uses)
    from app.services.reply_service import generate_agent_response, handle_reply

    lead_obj = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead_obj is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = handle_reply(db, lead_obj, reply_text, email_id=email_id or None, source="webhook")

    if result["status"] == "unsubscribed":
        return {
            "status": "unsubscribed",
            "lead_id": lead_id,
            "cancelled_emails": result["cancelled_emails"],
            "message": "Opt-out detected — lead suppressed and sequence stopped",
        }

    background_tasks.add_task(generate_agent_response, lead_id, reply_text)

    return {
        "status": "accepted",
        "lead_id": lead_id,
        "message": "Reply received and queued for autonomous response",
    }


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
# ML close probability
# ===========================================================================

@app.get("/leads/{lead_id}/close-probability")
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


@app.post("/analytics/ml/retrain")
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


# ===========================================================================
# ICP (Ideal Customer Profile) Builder
# ===========================================================================

@app.get("/icp")
def get_icp(
    current_user: User = Depends(require_rep),
    db: Session = Depends(get_db),
):
    """Return the current ICP configuration."""
    from app.services.icp_service import get_icp_config
    cfg = get_icp_config(db, org_id=current_user.org_id)
    if cfg is None:
        return {
            "configured": False,
            "industries": [],
            "seniority_levels": [],
            "excluded_industries": [],
            "min_employees": None,
            "max_employees": None,
            "updated_at": None,
            "updated_by_id": None,
        }
    return {
        "configured": True,
        "industries": cfg.industries or [],
        "seniority_levels": cfg.seniority_levels or [],
        "excluded_industries": cfg.excluded_industries or [],
        "min_employees": cfg.min_employees,
        "max_employees": cfg.max_employees,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by_id": cfg.updated_by_id,
    }


@app.put("/icp")
def update_icp(
    payload: dict,
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """
    Create or update the ICP configuration.
    Accepted fields: industries, seniority_levels, excluded_industries,
                     min_employees, max_employees
    """
    from app.services.icp_service import upsert_icp_config

    allowed = {
        "industries", "seniority_levels", "excluded_industries",
        "min_employees", "max_employees",
    }
    fields = {k: v for k, v in payload.items() if k in allowed}

    # Validate types
    for list_field in ("industries", "seniority_levels", "excluded_industries"):
        if list_field in fields:
            if fields[list_field] is None:
                fields[list_field] = []
            elif not isinstance(fields[list_field], list):
                raise HTTPException(status_code=422, detail=f"{list_field} must be a list")

    for int_field in ("min_employees", "max_employees"):
        if int_field in fields and fields[int_field] is not None:
            try:
                fields[int_field] = int(fields[int_field])
                if fields[int_field] < 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"{int_field} must be a non-negative integer")

    if not fields:
        raise HTTPException(status_code=422, detail="No valid fields provided")

    cfg = upsert_icp_config(db, user_id=current_user.id, org_id=current_user.org_id, **fields)
    return {
        "configured": True,
        "industries": cfg.industries or [],
        "seniority_levels": cfg.seniority_levels or [],
        "excluded_industries": cfg.excluded_industries or [],
        "min_employees": cfg.min_employees,
        "max_employees": cfg.max_employees,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "updated_by_id": cfg.updated_by_id,
    }


@app.get("/icp/preview")
def get_icp_preview(
    current_user: User = Depends(require_manager),
    db: Session = Depends(get_db),
):
    """Return counts of leads matching the current ICP — used for live preview."""
    from app.services.icp_service import icp_match_counts
    return icp_match_counts(db)


@app.get("/leads/{lead_id}/icp-evaluation")
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


# ===========================================================================
# Engagement decay — cooling leads at risk of going cold
# ===========================================================================

@app.get("/leads/cooling")
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


@app.get("/leads/{lead_id}/engagement-decay")
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


# ===========================================================================
# Global real-time event stream (SSE)
# ===========================================================================

@app.get("/events/stream", include_in_schema=False)
async def global_event_stream(
    token: str = Query(None, description="JWT token (EventSource cannot set headers)"),
    db: Session = Depends(get_db),
):
    """
    Server-Sent Events stream for global pipeline events.
    Subscribes to the Redis pub/sub channel "asdr:global_events".

    Event types:
      lead_complete  — a lead finished the pipeline (verdict + name/company)
      optimization   — a self-optimization run completed
      heartbeat      — keepalive ping every 30 s

    Frontend usage:
      const token = localStorage.getItem('access_token');
      const es = new EventSource(`/events/stream?token=${token}`);
      es.addEventListener('lead_complete', e => { ... });
    """
    if token:
        from app.auth.dependencies import _user_from_jwt
        user = _user_from_jwt(token, db)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid token")

    async def generator():
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe("asdr:global_events")

        # Initial connected event
        yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

        last_heartbeat = asyncio.get_event_loop().time()
        try:
            while True:
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat >= 30:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': utcnow().isoformat()})}\n\n"
                    last_heartbeat = now

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    try:
                        payload = json.loads(message["data"])
                        event_type = payload.get("type", "event")
                        yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                    except Exception:
                        pass

                await asyncio.sleep(0.05)
        finally:
            await pubsub.unsubscribe("asdr:global_events")
            await r.aclose()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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


# ===========================================================================
# CRM push — formatted single-lead export with simulated push response
# ===========================================================================

@app.post("/leads/{lead_id}/crm-push")
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


# ===========================================================================
# Referral chain — org-chart traversal relationships
# ===========================================================================

@app.get("/leads/{lead_id}/referral-chain")
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


# ===========================================================================
# Similar leads — cosine similarity over BANT + enrichment feature vectors
# ===========================================================================

@app.get("/leads/{lead_id}/similar")
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


# ===========================================================================
# Web signal enrichment — scrape company website for buying signals
# ===========================================================================

@app.post("/leads/{lead_id}/web-enrich")
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


# ===========================================================================
# Market intelligence — cross-lead segment pattern analysis
# ===========================================================================

@app.get("/analytics/market-intelligence")
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


# ===========================================================================
# Multi-axis A/B — breakdown by send time, subject style, message length
# ===========================================================================

@app.get("/ab-tests/multi-axis")
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


@app.get("/analytics/pipeline-velocity")
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


@app.get("/analytics/rep-performance")
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


@app.post("/seed/demo")
async def seed_demo(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Seed the database with demo data for the onboarding wizard.
    Runs asynchronously; returns immediately.
    """
    from app.database.models import Lead as LeadModel

    existing = db.query(LeadModel).filter(LeadModel.tags.contains(["demo"])).count()
    if existing > 0:
        return {"status": "already_seeded", "count": existing, "message": f"{existing} demo leads already exist."}

    def _run():
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scripts.seed_demo_data import seed
        from app.database.connection import SessionLocal
        _db = SessionLocal()
        try:
            seed(_db)
        finally:
            _db.close()

    background_tasks.add_task(_run)
    return {"status": "seeding", "message": "Demo data is being imported in the background. Refresh in ~5 seconds."}
