"""
Re-queues leads that are stuck in 'processing' or 'failed' back into the Redis
worker queue so they get processed on the next worker cycle.
"""
import sys
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def main():
    from app.database.connection import SessionLocal
    from app.database.models import Lead
    from app.services.queue_service import push_lead_job

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=5)

        stuck = (
            db.query(Lead)
            .filter(
                Lead.status.in_(["processing", "failed"]),
                Lead.created_at < cutoff,
            )
            .all()
        )

        if not stuck:
            log.info("Nothing to recover — no stuck or failed leads found.")
            return

        log.info(f"Found {len(stuck)} leads to recover:")
        now = datetime.utcnow()
        for lead in stuck:
            old_status = lead.status
            lead.status = "processing"
            lead.updated_at = now  # prevent watchdog from immediately re-queueing
            push_lead_job(lead.id)
            log.info(f"  ✓ Re-queued: {lead.name} ({old_status} → processing)")

        db.commit()
        log.info(f"\nDone — {len(stuck)} leads re-queued. Make sure 'make run-worker' is running.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
