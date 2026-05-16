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

import logging
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

log = structlog.get_logger(__name__)

# How old a pending lead must be before auto-requeue (avoids race with worker)
_AUTO_PROCESS_DELAY_SECONDS: int = int(
    getattr(settings, "AUTO_PROCESS_DELAY_SECONDS", 60)
)


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

    return scheduler
