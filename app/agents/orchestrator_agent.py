"""
Lead Orchestrator Agent

Sits at the top of the pipeline. For every incoming lead it:
  1. Checks deduplication status
  2. Scores initial priority (source + data completeness)
  3. Routes to the right sub-pipeline (enrichment → analysis → validator → action)
  4. After qualification, decides autonomous action: outreach / booking / human handoff

PoC: all logic runs in-process against the existing Postgres + Redis stack.

# PRODUCTION: replace this with a proper workflow orchestrator such as:
#   - Temporal (open-source, self-hosted) — durable workflows, retries, timeouts
#   - AWS Step Functions — managed, event-driven, pay-per-transition
#   - Prefect / Airflow — if the team already uses these for data pipelines
# Each "step" below maps 1-to-1 to a workflow activity in those systems.
"""

import logging
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.database import crud
from app.database.models import Lead

log = logging.getLogger(__name__)

# Priority scores by ingestion source — higher = process first
_SOURCE_PRIORITY = {
    "linkedin_signal": 10,   # explicit intent signal
    "inbound_email": 9,      # they reached out first
    "event": 8,              # attended a webinar/demo
    "website_form": 7,       # filled out a form
    "marketing_ad": 5,       # cold top-of-funnel
    "csv_import": 4,
    "webhook": 4,
    "manual": 3,
}

# Minimum completeness required before enrichment is worth running
_MIN_COMPLETENESS = 0.4


class OrchestratorAgent(BaseAgent):
    """
    Routes and prioritises leads before they enter the qualification pipeline.

    Returns a routing decision dict:
      {
        "action": "qualify" | "skip_duplicate" | "skip_incomplete" | "human_review",
        "priority": 1-10,
        "reason": str,
        "pipeline": ["enrichment", "analysis", "validator", "outreach" | "booking" | "handoff"]
      }
    """

    name = "orchestrator"

    def __init__(self):
        pass

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        lead = crud.get_lead(db, lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        # ── 1. Deduplication ────────────────────────────────────────────────
        is_dup, dup_id = self._check_duplicate(db, lead)
        if is_dup:
            crud.update_lead_status(db, lead_id, "duplicate")
            log.info(f"[orchestrator] Lead {lead_id} is a duplicate of {dup_id} — skipped")
            return {
                "action": "skip_duplicate",
                "duplicate_of": dup_id,
                "priority": 0,
                "reason": f"Exact email match with existing lead {dup_id}",
                "pipeline": [],
            }

        # ── 2. Completeness gate ────────────────────────────────────────────
        completeness = self._score_completeness(lead)
        if completeness < _MIN_COMPLETENESS:
            crud.update_lead_status(db, lead_id, "failed")
            log.warning(f"[orchestrator] Lead {lead_id} too incomplete ({completeness:.2f}) — skipped")
            return {
                "action": "skip_incomplete",
                "completeness": completeness,
                "priority": 0,
                "reason": "Insufficient data: name, email, and company are required",
                "pipeline": [],
            }

        # ── 3. Priority scoring ─────────────────────────────────────────────
        priority = self._compute_priority(lead, completeness)

        # ── 4. Route to action pipeline ─────────────────────────────────────
        pipeline = self._decide_pipeline(lead, input_data)

        crud.update_lead_status(db, lead_id, "processing")
        log.info(f"[orchestrator] Lead {lead_id} → priority={priority}, pipeline={pipeline}")

        return {
            "action": "qualify",
            "priority": priority,
            "completeness": completeness,
            "reason": f"Source={lead.source}, priority={priority}",
            "pipeline": pipeline,
        }

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _check_duplicate(self, db: Session, lead: Lead) -> tuple[bool, str | None]:
        existing = (
            db.query(Lead)
            .filter(Lead.email == lead.email, Lead.id != lead.id)
            .order_by(Lead.created_at.asc())
            .first()
        )
        if existing:
            return True, existing.id
        return False, None

    def _score_completeness(self, lead: Lead) -> float:
        fields = {
            "name": bool(lead.name and lead.name.strip()),
            "email": bool(lead.email and "@" in lead.email),
            "company": bool(lead.company and lead.company.strip()),
        }
        return sum(fields.values()) / len(fields)

    def _compute_priority(self, lead: Lead, completeness: float) -> int:
        base = _SOURCE_PRIORITY.get(lead.source, 4)
        # Boost by completeness (rounds to nearest integer, max +2)
        boost = round(completeness * 2)
        return min(10, base + boost)

    def _decide_pipeline(self, lead: Lead, input_data: dict) -> list[str]:
        """
        Build the ordered list of pipeline stages for this lead.

        Hot inbound (form / LinkedIn / event) → full qualification + booking.
        Cold (ads / CSV) → full qualification + outreach sequence.
        Manual / low-priority → qualify only, flag for human review.
        """
        source = lead.source
        pipeline = ["enrichment", "analysis", "validator"]

        if source in ("linkedin_signal", "inbound_email", "event", "website_form"):
            # High-intent source → try to book a meeting directly after qualification
            pipeline += ["booking", "outreach"]
        elif source in ("marketing_ad", "csv_import", "webhook"):
            # Cold outreach sequence
            pipeline += ["outreach"]
        else:
            # Unknown / manual source → human decides
            pipeline += ["human_handoff"]

        return pipeline
