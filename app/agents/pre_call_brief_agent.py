"""
Pre-Call Brief Generator

When a booking is confirmed, generates a one-page brief the rep reads before
the call. Pulls from everything the pipeline already knows:

  - Lead + enrichment snapshot (company, role, seniority, industry)
  - BANT scores with debate advocate/critic summary
  - Recent company news (from research_notes stored in pipeline)
  - 3 most likely objections based on BANT profile + company stage
  - 2 recommended opening angles tailored to their role and situation

The brief is stored in BookingRequest.pre_call_brief and optionally sent to
the rep via Slack. It is generated asynchronously after booking confirmation
so it does not block the booking response.
"""

import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.services.providers import get_ai_client

log = logging.getLogger(__name__)

_BRIEF_PROMPT = """You are a senior sales coach preparing a rep for a discovery call.

Lead profile:
{lead_json}

BANT qualification:
{bant_json}

Research notes from pipeline:
{research_notes}

Generate a concise pre-call brief. Include:

1. COMPANY SNAPSHOT (2 sentences): what the company does, company size, recent news if any.

2. LEAD CONTEXT (2 sentences): their role, seniority, likely priorities based on title and industry.

3. LIKELY OBJECTIONS (exactly 3 bullet points):
   - Most probable objections this lead profile raises, based on BANT scores and company stage.
   - Keep each bullet to one sentence.

4. RECOMMENDED ANGLES (exactly 2 bullet points):
   - Specific, role-relevant conversation openers that reference their situation.
   - NOT generic. Reference their industry, company size, or a recent signal.

5. WATCH OUT FOR (1 sentence): the biggest risk in this conversation.

Respond with ONLY valid JSON:
{{
  "company_snapshot": "...",
  "lead_context": "...",
  "likely_objections": ["...", "...", "..."],
  "recommended_angles": ["...", "..."],
  "watch_out_for": "...",
  "generated_at": "{now}"
}}"""


class PreCallBriefAgent(BaseAgent):
    name = "pre_call_brief"

    def __init__(self):
        self._ai = get_ai_client()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        from app.database.models import Enrichment, Verdict, BookingRequest, AgentLog
        from app.database import crud

        lead = crud.get_lead(db, lead_id)
        if not lead:
            return {"status": "no_lead"}

        enrichment = db.query(Enrichment).filter(Enrichment.lead_id == lead_id).first()
        verdict = db.query(Verdict).filter(Verdict.lead_id == lead_id).first()

        # Build lead profile dict
        lead_json = {
            "name": lead.name,
            "email": lead.email,
            "company": lead.company,
            "source": lead.source,
        }
        if enrichment:
            lead_json.update({
                "job_title": enrichment.job_title,
                "seniority": enrichment.seniority,
                "industry": enrichment.industry,
                "company_size": enrichment.company_size,
                "revenue_estimate": enrichment.revenue_estimate,
            })

        bant_json = {}
        research_notes = "No research notes available."
        if verdict:
            bant_json = {
                "final_verdict": verdict.final_verdict,
                "confidence": verdict.confidence_score,
                "bant_scores": verdict.bant_scores,
                "reasoning": verdict.analysis_reasoning,
                "flags": verdict.flags,
            }
            transcript = verdict.debate_transcript or {}
            if transcript.get("synthesis_reasoning"):
                bant_json["debate_summary"] = transcript["synthesis_reasoning"]
                bant_json["contested_dimensions"] = transcript.get("contested_dimensions", [])

        # Pull research notes from agent logs (research node stores them)
        research_log = (
            db.query(AgentLog)
            .filter(AgentLog.lead_id == lead_id, AgentLog.agent_name == "research")
            .order_by(AgentLog.created_at.desc())
            .first()
        )
        if research_log and research_log.output_data:
            notes = research_log.output_data.get("research_notes", [])
            summary = research_log.output_data.get("research_summary", "")
            if summary:
                research_notes = summary
            elif notes:
                research_notes = " | ".join(str(n) for n in notes[:5])

        prompt = _BRIEF_PROMPT.format(
            lead_json=json.dumps(lead_json, indent=2),
            bant_json=json.dumps(bant_json, indent=2),
            research_notes=research_notes,
            now=datetime.utcnow().isoformat(),
        )

        try:
            raw = self._ai.generate(prompt)
            brief_data = self._parse_json(raw)
        except Exception as e:
            log.warning(f"[brief] generation failed for lead {lead_id}: {e}")
            brief_data = {
                "company_snapshot": f"{lead.company} — enrichment data available.",
                "lead_context": f"{lead_json.get('job_title', 'Professional')} at {lead.company}.",
                "likely_objections": ["Timing concerns", "Budget approval needed", "Evaluating alternatives"],
                "recommended_angles": [
                    f"Ask about their current {lead_json.get('industry', 'industry')} stack.",
                    "Reference their growth stage and scaling challenges.",
                ],
                "watch_out_for": "Lead may need internal approval — confirm decision-making authority early.",
                "generated_at": datetime.utcnow().isoformat(),
            }

        # Serialize and persist on the booking request
        brief_text = json.dumps(brief_data, indent=2)
        booking = (
            db.query(BookingRequest)
            .filter(BookingRequest.lead_id == lead_id)
            .order_by(BookingRequest.created_at.desc())
            .first()
        )
        if booking:
            booking.pre_call_brief = brief_text
            booking.updated_at = datetime.utcnow()
            db.commit()

        # Notify Slack with brief highlights
        self._notify_slack(lead, brief_data)

        log.info(f"[brief] Pre-call brief generated for lead {lead_id[:8]}")
        return {"status": "generated", "brief": brief_data}

    def _notify_slack(self, lead, brief: dict) -> None:
        try:
            from app.services.slack_notifier import SlackNotifier
            from app.config import settings
            notifier = SlackNotifier(settings.SLACK_WEBHOOK_URL)
            if not notifier.enabled:
                return
            objections = "\n".join(f"• {o}" for o in brief.get("likely_objections", []))
            angles = "\n".join(f"• {a}" for a in brief.get("recommended_angles", []))
            msg = (
                f":clipboard: *Pre-call brief ready*: {lead.name} @ {lead.company}\n"
                f"*Likely objections:*\n{objections}\n"
                f"*Angles:*\n{angles}\n"
                f"*Watch out:* {brief.get('watch_out_for', '')}"
            )
            notifier.notify(msg)
        except Exception as e:
            log.debug(f"[brief] Slack notification failed: {e}")
