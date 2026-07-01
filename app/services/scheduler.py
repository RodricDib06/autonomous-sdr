"""
Background scheduler — APScheduler running inside the FastAPI process.

Jobs:
  auto_enqueue_pending  (every 5 min) — picks up leads stuck in 'pending'
                         longer than AUTO_PROCESS_DELAY_SECONDS and re-queues
                         them. Covers leads created via direct DB insert, CSV
                         import, or any ingest that didn't reach the queue.

  refresh_metrics       (every 1 min) — updates Prometheus queue-size gauge
                         so Grafana dashboards stay current without scraping
                         individual leads.

This runs in-process alongside the API server, so no extra container is
needed for light scheduled work.

# PRODUCTION: For heavy scheduled jobs (nightly ML re-training, bulk
# re-enrichment, weekly report generation) use a dedicated worker process
# with Celery Beat or a cloud scheduler (Railway CRON jobs, GCP Cloud
# Scheduler, AWS EventBridge).
"""

from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

log = structlog.get_logger(__name__)

# How old a pending lead must be before auto-requeue (avoids race with worker)
_AUTO_PROCESS_DELAY_SECONDS: int = settings.AUTO_PROCESS_DELAY_SECONDS


async def _send_scheduled_outreach() -> None:
    """Dispatch follow-up emails (step 2, 3…) whose scheduled_at has passed."""
    from app.database.connection import SessionLocal
    from app.agents.outreach_agent import send_pending_scheduled_emails

    db = SessionLocal()
    try:
        summary = send_pending_scheduled_emails(db)
        if summary["sent"] or summary["failed"]:
            log.info("scheduler.outreach_followup", **summary)
    except Exception as e:
        log.error("scheduler.outreach_followup.error", error=str(e))
    finally:
        db.close()


async def _auto_enqueue_pending() -> None:
    """Re-queue any lead that has been sitting in 'pending' status too long."""
    from app.database.connection import SessionLocal
    from app.database.models import Lead
    from app.services.queue_service import push_lead_job

    cutoff = datetime.utcnow() - timedelta(seconds=_AUTO_PROCESS_DELAY_SECONDS)
    db = SessionLocal()
    try:
        stale = (
            db.query(Lead)
            .filter(Lead.status == "pending", Lead.created_at < cutoff)
            .limit(20)
            .all()
        )
        if not stale:
            return

        requeued = 0
        for lead in stale:
            try:
                push_lead_job(lead.id)
                requeued += 1
            except Exception as e:
                log.warning("scheduler.requeue.failed", lead_id=lead.id[:8], error=str(e))

        if requeued:
            log.info("scheduler.auto_enqueue", requeued=requeued, cutoff_age_s=_AUTO_PROCESS_DELAY_SECONDS)
    finally:
        db.close()


async def _run_trigger_check() -> None:
    """Scan all complete leads for funding events, news, and job postings; resurrect Cold leads on funding."""
    from app.database.connection import SessionLocal
    from app.services.trigger_monitor import run_trigger_check_job

    db = SessionLocal()
    try:
        summary = run_trigger_check_job(db)
        if summary["triggered"] or summary.get("resurrected"):
            log.info(
                "scheduler.trigger_check",
                checked=summary["checked"],
                triggered=summary["triggered"],
                resurrected=summary.get("resurrected", 0),
                errors=summary["errors"],
            )
    except Exception as e:
        log.error("scheduler.trigger_check.error", error=str(e))
    finally:
        db.close()


async def _run_job_change_check() -> None:
    """Re-check enriched leads for company/role changes via PDL or web search."""
    from app.database.connection import SessionLocal
    from app.services.job_change_detector import run_job_change_check

    db = SessionLocal()
    try:
        summary = run_job_change_check(db)
        if summary["changed"]:
            log.info(
                "scheduler.job_change_check",
                checked=summary["checked"],
                changed=summary["changed"],
                errors=summary["errors"],
            )
    except Exception as e:
        log.error("scheduler.job_change_check.error", error=str(e))
    finally:
        db.close()


async def _run_lookalike_scoring() -> None:
    """Recompute ICP lookalike scores for all complete leads."""
    from app.database.connection import SessionLocal
    from app.services.lookalike_scorer import update_all_lookalike_scores

    db = SessionLocal()
    try:
        summary = update_all_lookalike_scores(db)
        log.info("scheduler.lookalike_scoring", **summary)
    except Exception as e:
        log.error("scheduler.lookalike_scoring.error", error=str(e))
    finally:
        db.close()


async def _run_decay_check() -> None:
    """Persist decay scores and trigger re-engagement emails for cooling leads."""
    from app.database.connection import SessionLocal
    from app.services.decay_service import run_decay_check_job

    db = SessionLocal()
    try:
        summary = run_decay_check_job(db)
        if summary["re_engaged"]:
            log.info(
                "scheduler.decay_check",
                processed=summary["processed"],
                re_engaged=summary["re_engaged"],
                errors=summary["errors"],
            )
    except Exception as e:
        log.error("scheduler.decay_check.error", error=str(e))
    finally:
        db.close()


async def _refresh_metrics() -> None:
    """Update Prometheus gauges for queue depth and in-flight leads."""
    try:
        from app.services.queue_service import get_redis
        from app.metrics import pipeline_queue_size, leads_in_flight
        from app.database.connection import SessionLocal
        from app.database.models import Lead

        r = get_redis()
        queue_len = r.llen("lead_queue") or 0
        pipeline_queue_size.set(queue_len)

        db = SessionLocal()
        try:
            in_flight = db.query(Lead).filter(Lead.status == "processing").count()
            leads_in_flight.set(in_flight)
        finally:
            db.close()
    except Exception as e:
        log.debug("scheduler.metrics.error", error=str(e))


def create_scheduler() -> AsyncIOScheduler:
    """Build and return a configured (not yet started) scheduler."""
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        _send_scheduled_outreach,
        trigger=IntervalTrigger(seconds=900),   # every 15 minutes
        id="send_scheduled_outreach",
        name="Send follow-up emails (step 2, 3…) when their scheduled_at arrives",
        replace_existing=True,
        misfire_grace_time=120,
    )

    scheduler.add_job(
        _auto_enqueue_pending,
        trigger=IntervalTrigger(seconds=300),   # every 5 minutes
        id="auto_enqueue_pending",
        name="Auto-enqueue stale pending leads",
        replace_existing=True,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        _refresh_metrics,
        trigger=IntervalTrigger(seconds=60),    # every minute
        id="refresh_metrics",
        name="Refresh Prometheus queue metrics",
        replace_existing=True,
        misfire_grace_time=30,
    )

    scheduler.add_job(
        _run_decay_check,
        trigger=IntervalTrigger(seconds=3600),  # every hour
        id="decay_check",
        name="Decay scoring and re-engagement triggers",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        _run_trigger_check,
        trigger=IntervalTrigger(seconds=21600),  # every 6 hours
        id="trigger_check",
        name="Real-time trigger monitor (funding/news/job postings)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    scheduler.add_job(
        _run_lookalike_scoring,
        trigger=IntervalTrigger(seconds=86400),   # nightly
        id="lookalike_scoring",
        name="ICP lookalike score batch update",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _run_job_change_check,
        trigger=IntervalTrigger(seconds=172800),  # every 48 hours
        id="job_change_check",
        name="Job change detector (PDL re-check + web search)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _run_optimization_loop,
        trigger=IntervalTrigger(seconds=604800),  # weekly
        id="optimization_loop",
        name="Self-optimization: update BANT weights from conversion outcomes",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    scheduler.add_job(
        _run_ml_retrain,
        trigger=IntervalTrigger(seconds=86400),   # nightly
        id="ml_retrain",
        name="ML close-probability model retrain",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler


async def _run_optimization_loop() -> None:
    """Run BANT weight self-optimization cycle."""
    from app.database.connection import SessionLocal
    from app.services.optimization_loop import run_optimization

    db = SessionLocal()
    try:
        result = run_optimization(db)
        if result.get("status") == "ran":
            log.info(
                "scheduler.optimization_loop",
                applied=result.get("applied"),
                improvement=result.get("improvement_score"),
                sample_size=result.get("sample_size"),
            )
        else:
            log.debug("scheduler.optimization_loop.skipped", reason=result.get("reason"))
    except Exception as e:
        log.error("scheduler.optimization_loop.error", error=str(e))
    finally:
        db.close()


async def _run_ml_retrain() -> None:
    """Retrain the close-probability logistic regression model."""
    from app.database.connection import SessionLocal
    from app.services.ml_scorer import retrain

    db = SessionLocal()
    try:
        trained = retrain(db)
        log.info("scheduler.ml_retrain", trained=trained)
    except Exception as e:
        log.error("scheduler.ml_retrain.error", error=str(e))
    finally:
        db.close()
