import asyncio
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from app.database.connection import SessionLocal, create_all_tables
from app.database import crud
from app.services.queue_service import pop_lead_job
from app.agents.enrichment_agent import EnrichmentAgent
from app.agents.analysis_agent import AnalysisAgent
from app.agents.validator_agent import ValidatorAgent
from app.services.slack_notifier import SlackNotifier
from app.services.data_quality import DataQualityService
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Create agent instances once
enrichment_agent = EnrichmentAgent()
analysis_agent = AnalysisAgent()
validator_agent = ValidatorAgent()
slack_notifier = SlackNotifier()

# Thread pool for database operations
executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_LEADS)


async def process_lead_async(lead_id: str) -> None:
    """Async wrapper for lead processing"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, process_lead, lead_id)


def process_lead(lead_id: str) -> None:
    db = SessionLocal()
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            log.error(f"Lead {lead_id} not found in database")
            return

        log.info(f"[{lead.name}] Starting pipeline")

        # --- Enrichment ---
        try:
            enrichment_result = enrichment_agent._timed_run(
                db, lead_id, {"email": lead.email, "company": lead.company}
            )
            log.info(f"[{lead.name}] Enriched → {enrichment_result['industry']}, {enrichment_result['seniority']}")
        except Exception as e:
            log.error(f"[{lead.name}] Enrichment failed: {e}")
            crud.update_lead_status(db, lead_id, "failed")
            return

        # --- Analysis ---
        try:
            analysis_result = analysis_agent._timed_run(db, lead_id, enrichment_result)
            log.info(f"[{lead.name}] Analysis → verdict={analysis_result['analysis_verdict']}")
        except Exception as e:
            log.error(f"[{lead.name}] Analysis failed: {e}")
            crud.update_lead_status(db, lead_id, "failed")
            return

        # --- Validation ---
        combined = {**enrichment_result, **analysis_result}
        try:
            validator_result = validator_agent._timed_run(db, lead_id, combined)
            log.info(
                f"[{lead.name}] Validated → final={validator_result['final_verdict']} "
                f"confidence={validator_result['confidence_score']:.2f}"
            )
        except Exception as e:
            log.error(f"[{lead.name}] Validation failed: {e}")
            # Non-fatal: keep the analysis verdict as final
            verdict = crud.get_verdict_by_lead(db, lead_id)
            if verdict:
                crud.update_verdict(db, verdict.id, {
                    "validated": False,
                    "final_verdict": analysis_result["analysis_verdict"],
                    "confidence_score": 0.5,
                    "consistency_notes": f"Validation failed: {e}",
                    "flags": ["validation_error"],
                })

        crud.update_lead_status(db, lead_id, "complete")

        # Refresh lead so enrichments/verdicts are visible, then score quality
        db.refresh(lead)
        quality_scores = DataQualityService().update_lead_quality(db, lead)
        log.info(
            f"[{lead.name}] Quality scored → "
            f"overall={quality_scores['data_quality_score']:.1f} "
            f"completeness={quality_scores['completeness_score']:.1f}"
        )

        log.info(f"[{lead.name}] Pipeline complete ✓")
        
        # Send Slack notification for Hot leads
        verdict = crud.get_verdict_by_lead(db, lead_id)
        if verdict and slack_notifier.enabled and verdict.final_verdict == "Hot":
            enrichment = lead.enrichments[0] if lead.enrichments else None
            lead_data = {
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "company": lead.company,
                "confidence_score": verdict.confidence_score or 0,
                "job_title": enrichment.job_title if enrichment else None,
                "industry": enrichment.industry if enrichment else None,
                "reasoning": verdict.analysis_reasoning or "Strong ICP match"
            }
            
            if slack_notifier.notify_hot_lead(lead_data):
                log.info(f"[{lead.name}] Slack notification sent ✓")
            else:
                log.warning(f"[{lead.name}] Slack notification failed")

    finally:
        db.close()


def recover_stale_leads() -> int:
    """Re-queue leads stuck in 'processing' for more than 15 minutes with no update.
    Uses updated_at (set whenever status changes) so actively-processing leads are safe."""
    from app.database.models import Lead
    from app.services.queue_service import push_lead_job
    from sqlalchemy import or_
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        stale = db.query(Lead).filter(
            Lead.status == "processing",
            # Only catch leads where updated_at is old OR null and created_at is old
            or_(
                Lead.updated_at < cutoff,
                (Lead.updated_at == None) & (Lead.created_at < cutoff),  # noqa: E711
            ),
        ).all()
        for lead in stale:
            push_lead_job(lead.id)
            log.warning(f"[watchdog] Re-queued stale lead: {lead.name} ({lead.id[:8]})")
        db.commit()
        return len(stale)
    finally:
        db.close()


async def run_worker_async() -> None:
    """Async worker that processes multiple leads concurrently"""
    create_all_tables()
    log.info(f"Worker started. Processing up to {settings.MAX_CONCURRENT_LEADS} leads concurrently...")

    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_LEADS)
    cycles_since_watchdog = 0
    cycles_since_heartbeat = 0

    while True:
        try:
            # Ping heartbeat every 5 cycles (~15s)
            cycles_since_heartbeat += 1
            if cycles_since_heartbeat >= 5:
                from app.services.queue_service import ping_worker_heartbeat
                ping_worker_heartbeat()
                cycles_since_heartbeat = 0

            # Every 30 cycles (~90s) run the stale-job watchdog
            cycles_since_watchdog += 1
            if cycles_since_watchdog >= 30:
                recovered = recover_stale_leads()
                if recovered:
                    log.info(f"[watchdog] Recovered {recovered} stale leads")
                cycles_since_watchdog = 0

            tasks = []
            for _ in range(settings.WORKER_BATCH_SIZE):
                lead_id = pop_lead_job(timeout=1)
                if lead_id:
                    tasks.append(process_lead_with_semaphore(lead_id, semaphore))
                else:
                    break

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(2)

        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception as e:
            log.error(f"Unexpected worker error: {e}")
            await asyncio.sleep(2)


async def process_lead_with_semaphore(lead_id: str, semaphore: asyncio.Semaphore) -> None:
    """Process a lead with concurrency control"""
    async with semaphore:
        await process_lead_async(lead_id)


def run_worker() -> None:
    """Main entry point - runs the async worker"""
    asyncio.run(run_worker_async())


if __name__ == "__main__":
    run_worker()
