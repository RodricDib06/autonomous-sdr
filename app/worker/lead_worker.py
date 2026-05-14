"""
Lead Worker — LangGraph edition

Pops lead IDs from the Redis queue and runs each one through the
LangGraph multi-agent state graph (app/agents/graph.py).

The graph handles all routing decisions internally:
  - Deduplication / completeness check (orchestrator node)
  - Enrichment + intent scoring
  - BANT qualification + validation
  - Conditional action: booking / outreach / human handoff
  - CRM sync + data quality scoring

The worker itself is intentionally thin — it only manages concurrency,
the heartbeat, and stale-job recovery. All business logic lives in the graph.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from app.database.connection import SessionLocal, create_all_tables
from app.database import crud
from app.services.queue_service import pop_lead_job
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_LEADS)

# Import graph at module level — this compiles the LangGraph state machine once
from app.agents.graph import graph as lead_graph  # noqa: E402


# ---------------------------------------------------------------------------
# Single-lead processor
# ---------------------------------------------------------------------------

def process_lead(lead_id: str) -> None:
    """Run one lead through the LangGraph pipeline synchronously."""
    db = SessionLocal()
    try:
        lead = crud.get_lead(db, lead_id)
        if not lead:
            log.error(f"Lead {lead_id} not found — skipping")
            return

        log.info(f"[worker] Starting graph for: {lead.name} ({lead_id[:8]})")

        initial_state = {
            "lead_id": lead_id,
            "lead_name": lead.name,
            "errors": [],
        }

        # LangGraph runs synchronously inside the thread pool
        final_state = lead_graph.invoke(initial_state)

        errors = final_state.get("errors", [])
        verdict = final_state.get("validation", {}).get("final_verdict", "unknown")
        log.info(
            f"[worker] Finished: {lead.name} → verdict={verdict} "
            f"errors={len(errors)}"
        )
        if errors:
            log.warning(f"[worker] Non-fatal errors for {lead.name}: {errors}")

    except Exception as e:
        log.error(f"[worker] Graph failed for {lead_id}: {e}", exc_info=True)
        try:
            crud.update_lead_status(db, lead_id, "failed")
        except Exception:
            pass
    finally:
        db.close()


async def process_lead_async(lead_id: str) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, process_lead, lead_id)


# ---------------------------------------------------------------------------
# Stale-job watchdog
# ---------------------------------------------------------------------------

def recover_stale_leads() -> int:
    """Re-queue leads stuck in 'processing' for more than 15 minutes."""
    from app.database.models import Lead
    from app.services.queue_service import push_lead_job
    from sqlalchemy import or_

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=15)
        stale = db.query(Lead).filter(
            Lead.status == "processing",
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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_worker_async() -> None:
    create_all_tables()
    log.info(
        f"LangGraph worker started — "
        f"concurrency={settings.MAX_CONCURRENT_LEADS}, "
        f"batch={settings.WORKER_BATCH_SIZE}"
    )

    semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_LEADS)
    cycles_since_watchdog = 0
    cycles_since_heartbeat = 0

    while True:
        try:
            cycles_since_heartbeat += 1
            if cycles_since_heartbeat >= 5:
                from app.services.queue_service import ping_worker_heartbeat
                ping_worker_heartbeat()
                cycles_since_heartbeat = 0

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
                    tasks.append(_run_with_semaphore(lead_id, semaphore))
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


async def _run_with_semaphore(lead_id: str, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        await process_lead_async(lead_id)


def run_worker() -> None:
    asyncio.run(run_worker_async())


if __name__ == "__main__":
    run_worker()
