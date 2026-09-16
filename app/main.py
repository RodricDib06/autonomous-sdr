import json
import asyncio
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
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
from app.database.models import Lead
from app.services.queue_service import get_redis
from app.services.ollama_client import OllamaConnectionError
from app.services.validation import EmailDomainValidator
from app.auth.dependencies import require_admin, require_manager, require_rep
from app.database.models import User
from app.routers.auth import router as auth_router
from app.routers.ingest import router as ingest_router
from app.services.rate_limiter import limiter
from app.config import settings
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

        # Validate Redis connection (skipped in test mode).
        #
        # Degraded, not fatal. Redis backs the job queue, SSE pub/sub, and
        # caching, but auth, the dashboard, and every read path run off
        # Postgres alone. Exiting here used to take the whole container down
        # before it could answer /health, which on a health-checked PaaS
        # turns one unset variable into "deploy failed" with no HTTP response
        # to diagnose from. Boot, serve, and report it on /health instead.
        app.state.redis_ok = False
        if not _testing:
            try:
                redis = get_redis()
                redis.ping()
                app.state.redis_ok = True
                log.info("startup.redis", status="ok")
            except Exception as e:
                log.error(
                    "startup.redis", status="degraded", error=str(e),
                    hint="REDIS_URL is unreachable — ingestion and live pipeline "
                         "streaming will fail until it is set. On Render: the "
                         "blueprint wires it from the keyvalue service. On Railway: "
                         "add a Redis service and set REDIS_URL=${{Redis.REDIS_URL}}. "
                         "Locally: docker compose up -d redis.",
                )

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

        # Optionally co-host the LangGraph worker (RUN_WORKER_IN_PROCESS).
        # It runs on its own thread with its own event loop: the queue pop is
        # a synchronous, blocking Redis call, so sharing the API's loop would
        # stall request handling for up to a second per idle poll.
        worker_thread = None
        worker_stop = threading.Event()
        if not _testing and settings.RUN_WORKER_IN_PROCESS:
            try:
                from app.worker.lead_worker import run_worker

                worker_thread = threading.Thread(
                    target=run_worker,
                    args=(worker_stop.is_set,),
                    name="lead-worker",
                    daemon=True,
                )
                worker_thread.start()
                log.info("startup.worker", mode="in_process", status="ok")
            except Exception as e:
                log.warning("startup.worker", mode="in_process", status="failed", error=str(e))

        log.info("startup.ready", ai_provider=settings.AI_PROVIDER, enrichment_provider=settings.ENRICHMENT_PROVIDER)
        yield

        if scheduler and scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("shutdown.scheduler")
        if worker_thread:
            worker_stop.set()
            # One queue poll blocks for at most a second; give it a little room.
            worker_thread.join(timeout=10)
            log.info("shutdown.worker", stopped=not worker_thread.is_alive())
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

# Extracted from this module — see each router's docstring.
from app.routers.tracking import router as tracking_router  # noqa: E402
app.include_router(tracking_router)

from app.routers.config import router as config_router  # noqa: E402
app.include_router(config_router)

from app.routers.icp import router as icp_router  # noqa: E402
app.include_router(icp_router)

from app.routers.experiments import router as experiments_router  # noqa: E402
app.include_router(experiments_router)

from app.routers.analytics import router as analytics_router  # noqa: E402
app.include_router(analytics_router)

from app.routers.leads import router as leads_router  # noqa: E402
app.include_router(leads_router)

from app.routers.compliance import router as compliance_router  # noqa: E402
app.include_router(compliance_router)

from app.routers.backtests import router as backtests_router  # noqa: E402
app.include_router(backtests_router)

from app.routers.campaigns import router as campaigns_router  # noqa: E402
app.include_router(campaigns_router)

from app.routers.prospecting import router as prospecting_router  # noqa: E402
app.include_router(prospecting_router)

from app.routers.crm import router as crm_router  # noqa: E402
app.include_router(crm_router)

# Global Slack notifier
# Store webhook URL in memory (in production, use database)
slack_webhook_url = None


@app.get("/health")
def health_check():
    """
    Liveness plus dependency state.

    Always 200 so a PaaS health check can distinguish "running but
    misconfigured" from "not running at all" — `status` carries the
    difference, and `redis` names the dependency when it is the problem.
    """
    from app.services.queue_service import get_worker_status
    worker = get_worker_status()

    redis_ok = getattr(app.state, "redis_ok", False)
    # Re-check on read: Redis may have come up after boot (or gone away).
    try:
        get_redis().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    app.state.redis_ok = redis_ok

    return {
        "status": "healthy" if redis_ok else "degraded",
        "service": "AutonomousSDR",
        "version": "1.0.0",
        "ai_provider": settings.AI_PROVIDER,
        "enrichment_provider": settings.ENRICHMENT_PROVIDER,
        "redis": "ok" if redis_ok else "unavailable",
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




















# ============================================================================
# PHASE 1 FEATURES: Deduplication, CSV Import, Validation, Slack Alerts
# ============================================================================





















# Registered before /leads/{lead_id}: FastAPI matches in definition order,
# so a concrete path declared after the catch-all is unreachable — this one
# returned "Lead not found" in production because 'cooling' was being read
# as a lead id.











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














# ===========================================================================
# Outreach endpoints
# ===========================================================================





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



# ===========================================================================
# Pre-call brief endpoints
# ===========================================================================



# ===========================================================================
# Trigger signals endpoints
# ===========================================================================









# ===========================================================================
# Conversational agent endpoints
# ===========================================================================





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
            "classification": c.classification,
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





# ===========================================================================
# Intent scoring endpoints
# ===========================================================================





# ===========================================================================
# CRM sync endpoints
# ===========================================================================



# ===========================================================================
# A/B testing endpoints
# ===========================================================================







# ===========================================================================
# Self-optimization endpoints
# ===========================================================================







# ===========================================================================
# Email tracking — open pixel + click redirect
# ===========================================================================

# 1×1 transparent GIF — served for every open-tracking request










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







# ===========================================================================
# ML close probability
# ===========================================================================





# ===========================================================================
# Pipeline trace — LangGraph per-lead execution breakdown
# ===========================================================================



# ===========================================================================
# ICP (Ideal Customer Profile) Builder
# ===========================================================================









# ===========================================================================
# Engagement decay — cooling leads at risk of going cold
# ===========================================================================





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



# ===========================================================================
# Referral chain — org-chart traversal relationships
# ===========================================================================



# ===========================================================================
# Similar leads — cosine similarity over BANT + enrichment feature vectors
# ===========================================================================



# ===========================================================================
# Web signal enrichment — scrape company website for buying signals
# ===========================================================================



# ===========================================================================
# Market intelligence — cross-lead segment pattern analysis
# ===========================================================================



# ===========================================================================
# Multi-axis A/B — breakdown by send time, subject style, message length
# ===========================================================================







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
