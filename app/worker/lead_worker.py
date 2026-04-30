import time
import logging
from app.database.connection import SessionLocal, create_all_tables
from app.database import crud
from app.services.queue_service import pop_lead_job
from app.agents.enrichment_agent import EnrichmentAgent
from app.agents.analysis_agent import AnalysisAgent
from app.agents.validator_agent import ValidatorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

enrichment_agent = EnrichmentAgent()
analysis_agent = AnalysisAgent()
validator_agent = ValidatorAgent()


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
        log.info(f"[{lead.name}] Pipeline complete ✓")

    finally:
        db.close()


def run_worker() -> None:
    create_all_tables()
    log.info("Worker started. Waiting for jobs...")
    while True:
        try:
            lead_id = pop_lead_job(timeout=5)
            if lead_id:
                process_lead(lead_id)
        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception as e:
            log.error(f"Unexpected worker error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_worker()
